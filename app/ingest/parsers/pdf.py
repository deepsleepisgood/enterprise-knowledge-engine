"""Tier-1 PDF parser (text layer) with PyMuPDF; page rendering for the vision tier.

Structure comes from layout: font size relative to the body, bold, short lines. Lines repeated
at the top or bottom of most pages are headers and footers. Tables found by PyMuPDF become table
blocks and their text is not repeated as paragraphs.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.ingest.blocks import Block, clean


def _norm_hf(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def _inside(b: tuple[float, ...], boxes: list[tuple[float, ...]]) -> bool:
    x0, y0, x1, y1 = b
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in boxes)


def _assign_columns(lines: list[dict[str, Any]]) -> None:
    """Two-column pages: lines left of the middle read before lines right of it.

    A page is two-column when both halves hold several narrow lines and few lines cross the
    middle. Lines that span the middle (titles) keep column 0.
    """
    by_page: dict[int, list[dict[str, Any]]] = {}
    for ln in lines:
        ln["col"] = 0
        by_page.setdefault(ln["page"], []).append(ln)
    for page_lines in by_page.values():
        if not page_lines:
            continue
        mid = page_lines[0]["width"] / 2
        left = [ln for ln in page_lines if ln["x1"] <= mid + 5]
        right = [ln for ln in page_lines if ln["x0"] >= mid - 5]
        crossing = len(page_lines) - len(left) - len(right)
        if len(left) >= 3 and len(right) >= 3 and crossing <= 0.2 * len(page_lines):
            for ln in right:
                ln["col"] = 1


def parse_pdf(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    lines: list[dict[str, Any]] = []
    table_blocks: list[Block] = []
    for pno, page in enumerate(doc, 1):
        h, w = page.rect.height, page.rect.width
        boxes: list[tuple[float, ...]] = []
        try:
            for t in page.find_tables().tables:
                rows = [[clean(c or "") for c in r] for r in t.extract()]
                rows = [r for r in rows if any(r)]
                if len(rows) >= 2:
                    boxes.append(tuple(t.bbox))
                    table_blocks.append(Block("table", rows=rows, page=pno, bbox=tuple(t.bbox)))
        except Exception:  # table detection is best effort
            pass
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = clean("".join(s["text"] for s in ln["spans"]))
                bbox = tuple(ln["bbox"])
                if _inside(bbox, boxes):
                    continue
                lines.append(
                    {
                        "x0": bbox[0],
                        "x1": bbox[2],
                        "width": w,
                        "text": text,
                        "size": round(max(s["size"] for s in spans), 1),
                        "bold": all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans),
                        "page": pno,
                        "bbox": bbox,
                        "top": bbox[1] < h * 0.07,
                        "bottom": bbox[3] > h * 0.93,
                    }
                )
    _assign_columns(lines)
    lines.sort(key=lambda ln: (ln["page"], ln["col"], ln["bbox"][1]))
    pages = max(1, len(doc))
    # Headers and footers: same text (digits folded) at the page edge on most pages.
    edge = Counter(_norm_hf(ln["text"]) for ln in lines if ln["top"] or ln["bottom"])
    repeated = {t for t, n in edge.items() if pages >= 3 and n >= max(2, 0.6 * pages)}
    sizes = Counter()
    for ln in lines:
        sizes[ln["size"]] += len(ln["text"])
    body = sizes.most_common(1)[0][0] if sizes else 10.0
    heading_sizes = sorted({ln["size"] for ln in lines if ln["size"] >= body * 1.15}, reverse=True)

    blocks: list[Block] = []
    para: list[dict[str, Any]] = []

    def flush() -> None:
        if para:
            text = clean(" ".join(p["text"] for p in para))
            first = para[0]
            blocks.append(
                Block(
                    "paragraph",
                    text,
                    page=first["page"],
                    bbox=first["bbox"],
                    meta={"font_size": first["size"], "bold": first["bold"], "col": first["col"]},
                )
            )
            para.clear()

    prev = None
    for ln in lines:
        if (ln["top"] or ln["bottom"]) and _norm_hf(ln["text"]) in repeated:
            continue
        is_heading = ln["size"] in heading_sizes[:4] and len(ln["text"]) < 120
        is_bold_head = ln["bold"] and len(ln["text"]) < 90 and not ln["text"].endswith((".", ","))
        bullet = re.match(r"^(?:[•▪◦\-–*]|\d{1,2}[.)])\s+(?=\S)", ln["text"])
        if is_heading or (is_bold_head and (prev is None or not prev["bold"])):
            flush()
            level = (
                heading_sizes.index(ln["size"]) + 1 if is_heading else len(heading_sizes[:4]) + 1
            )
            blocks.append(
                Block(
                    "heading",
                    ln["text"],
                    level=level,
                    page=ln["page"],
                    bbox=ln["bbox"],
                    meta={"font_size": ln["size"], "bold": ln["bold"]},
                )
            )
        elif bullet:
            flush()
            blocks.append(
                Block(
                    "list_item",
                    ln["text"][bullet.end() :],
                    page=ln["page"],
                    bbox=ln["bbox"],
                    meta={"ordered": ln["text"][0].isdigit()},
                )
            )
        else:
            gap = prev is not None and (
                ln["page"] != prev["page"] or ln["bbox"][1] - prev["bbox"][3] > ln["size"] * 0.8
            )
            if gap or (
                prev
                and prev["text"].endswith((".", ":", "?"))
                and ln["text"][:1].isupper()
                and len(prev["text"]) < 60
            ):
                flush()
            if blocks and blocks[-1].type == "list_item" and not gap and not para:
                blocks[-1].text = clean(blocks[-1].text + " " + ln["text"])
            else:
                para.append(ln)
        prev = ln
    flush()
    # Put tables back in reading order by page and vertical position.
    allb = blocks + table_blocks
    allb.sort(key=lambda b: (b.page or 0, b.meta.get("col", 0), (b.bbox or (0, 0, 0, 0))[1]))
    meta = {
        k: v
        for k, v in (doc.metadata or {}).items()
        if v and k in ("title", "author", "subject", "creationDate", "modDate")
    }
    meta["pages"] = pages
    meta["chars"] = sum(len(ln["text"]) for ln in lines)
    return allb, meta


def render_pages(data: bytes, dpi: int = 150, limit: int = 40) -> list[bytes]:
    """PNG images of each page, for the vision tier."""
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    return [page.get_pixmap(dpi=dpi).tobytes("png") for page in list(doc)[:limit]]
