"""Parser cascade (SCOPE.md 3.5): cheapest tier first, escalate when parse quality is low.

Tier 1 native parsers; tier 2 converts legacy formats with LibreOffice and re-parses; tier 3
renders pages and asks the vision model (gate B, only when a vision-capable model is set);
tier 5 stores the file as opaque and flags it. Every result carries a quality score.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.ingest.blocks import Block, ParseResult, detect_turns

QUALITY_FLOOR = 0.5  # below this the episode is escalated or held
# python-docx, python-pptx and openpyxl share lxml state that is not thread-safe.
_PARSE_LOCK = threading.Lock()


def _native(kind: str, data: bytes) -> tuple[list[Block], dict[str, Any]]:
    from app.ingest.parsers import office, pdf, textual

    fns = {
        "docx": office.parse_docx,
        "xlsx": office.parse_xlsx,
        "csv": office.parse_csv,
        "pptx": office.parse_pptx,
        "pdf": pdf.parse_pdf,
        "html": textual.parse_html,
        "markdown": lambda d: textual.parse_text(d, markdown=True),
        "text": lambda d: textual.parse_text(d, markdown=False),
        "eml": textual.parse_eml,
        "vtt": textual.parse_cues,
        "srt": textual.parse_cues,
        "json": textual.parse_json,
    }
    if kind not in fns:
        raise LookupError(kind)
    return fns[kind](data)


def _tidy_tables(blocks: list[Block]) -> list[Block]:
    for b in blocks:
        if b.type == "table" and b.rows:
            width = max(len(r) for r in b.rows)
            rows = [r + [""] * (width - len(r)) for r in b.rows]
            keep = [j for j in range(width) if any(r[j] for r in rows)]
            b.rows = [[r[j] for j in keep] for r in rows]
    return blocks


def quality(blocks: list[Block], meta: dict[str, Any], kind: str) -> tuple[float, list[str]]:
    """0..1 from extracted volume, junk characters, and structure. Notes explain deductions."""
    notes: list[str] = []
    text = " ".join(b.text for b in blocks) + " ".join(c for b in blocks for r in b.rows for c in r)
    n = len(text)
    if n == 0:
        return 0.0, ["no text extracted"]
    score = 1.0
    junk = sum(1 for c in text if c == "�" or (ord(c) < 32 and c not in "\n\t"))
    letters = sum(1 for c in text if c.isalpha())
    junk_ratio = junk / n
    if junk_ratio > 0.02:
        score -= min(0.6, junk_ratio * 5)
        notes.append(f"junk characters {junk_ratio:.1%}")
    if letters / n < 0.4 and kind not in ("xlsx", "csv"):
        score -= 0.3
        notes.append(f"low letter ratio {letters / n:.0%}")
    if kind == "pdf":
        pages = meta.get("pages", 1)
        per_page = meta.get("chars", n) / max(pages, 1)
        if per_page < 40:
            score -= 0.7
            notes.append(f"{per_page:.0f} characters per page (scanned or image-only?)")
    words = text.split()
    if words:
        long_tokens = sum(1 for w in words if len(w) > 40) / len(words)
        if long_tokens > 0.05:
            score -= 0.3
            notes.append("many unbroken long tokens (broken text layer?)")
    if n > 3000 and not any(b.type in ("heading", "table", "turn", "list_item") for b in blocks):
        score -= 0.1
        notes.append("no structure detected")
    return max(0.0, round(score, 3)), notes


def _libreoffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert_legacy(data: bytes, kind: str) -> tuple[bytes, str] | None:
    exe = _libreoffice()
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.bin"
        src.write_bytes(data)
        # Let LibreOffice pick the family from content; try writer, calc, impress targets.
        for target, out_kind in (("docx", "docx"), ("xlsx", "xlsx"), ("pptx", "pptx")):
            subprocess.run(
                [exe, "--headless", "--convert-to", target, "--outdir", tmp, str(src)],
                capture_output=True,
                timeout=180,
                check=False,
            )
            out = Path(tmp) / f"input.{target}"
            if out.exists() and out.stat().st_size > 0:
                return out.read_bytes(), out_kind
    return None


def _vision(data: bytes, kind: str) -> tuple[list[Block], dict[str, Any]] | None:
    from app.core.config import get_settings

    if not get_settings().model_vision:
        return None  # no vision-capable model configured
    from app.core import llm
    from app.core.redaction import redact
    from app.ingest.parsers import pdf, textual

    if kind == "pdf":
        images = [(png, "image/png") for png in pdf.render_pages(data)]
    elif kind == "image":
        from app.ingest.detect import _magic_mime

        images = [(data, _magic_mime(data) or "image/png")]
    else:
        return None
    pages: list[str] = []
    for i, img in enumerate(images, 1):
        out = llm.vision(
            "Transcribe this page as Markdown. Keep headings (#), numbered and bulleted lists, "
            "and tables (| pipes |) in reading order. Do not summarise or add anything.",
            [img],
            prompt_version="vision-page-v1",
        )
        pages.append(redact(out.text))
        _ = i
    blocks, _m = textual.parse_text("\n\n".join(pages), markdown=True)
    return blocks, {"pages": len(images), "vision": True}


def parse(data: bytes, kind: str) -> ParseResult:
    notes: list[str] = []
    if kind in ("legacy_office", "odf", "rtf"):
        converted = _convert_legacy(data, kind)
        if converted is None:
            return ParseResult(
                [],
                tier=5,
                quality=0.0,
                notes=[f"{kind}: LibreOffice is not installed; stored, not parsed"],
            )
        data, kind = converted
        tier = 2
    else:
        tier = 1
    blocks: list[Block] = []
    meta: dict[str, Any] = {}
    score = 0.0
    if kind in ("image",):
        tier = 3
    else:
        try:
            with _PARSE_LOCK:
                blocks, meta = _native(kind, data)
            blocks = _tidy_tables(detect_turns(blocks))
            score, qnotes = quality(blocks, meta, kind)
            notes += qnotes
        except LookupError:
            return ParseResult([], tier=5, quality=0.0, notes=[f"no parser for {kind}"])
        except Exception as exc:  # a corrupt file is flagged, never dropped
            notes.append(f"parser error: {type(exc).__name__}: {exc}")
    if score < QUALITY_FLOOR and kind in ("pdf", "image"):
        vis = _vision(data, kind)
        if vis is not None:
            vblocks, vmeta = vis
            vblocks = detect_turns(vblocks)
            vscore, vnotes = quality(vblocks, vmeta, "markdown")
            notes.append(f"escalated to vision (tier 3): quality {vscore}")
            if vscore > score:
                blocks, meta, score, tier = vblocks, {**meta, **vmeta}, vscore, 3
        else:
            notes.append("vision tier not configured (MODEL_VISION unset)")
    return ParseResult(blocks, tier=tier, quality=score, file_meta=meta, notes=notes)
