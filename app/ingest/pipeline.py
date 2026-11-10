"""Ingestion jobs: parse an episode into sources and passages.

parse_episode: blob -> detect -> parser cascade -> structure inference -> documents ->
metadata inference -> passages with context headers (redacted) -> store -> version linking ->
queue extraction. Low parse quality holds the episode as needs_attention.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.redaction import redact
from app.ingest import metadata as md
from app.ingest import versions
from app.ingest.detect import detect
from app.ingest.parsers import QUALITY_FLOOR, parse
from app.ingest.segment import DocPart, PassageDraft, infer_headings, segment, split_documents
from app.store import episodes as store
from app.store import jobs, kb
from app.store.base import stable_id
from app.worker import handler

REPAIR_PROMPT_VERSION = "structure-repair-v1"


class _Levels(BaseModel):
    levels: list[int] = Field(
        description="One integer per line: 0 = not a heading, 1 = top "
        "level, 2 = sub-section, 3 or 4 = deeper"
    )


def _llm_structured() -> Any | None:
    if not get_settings().llm_configured:
        return None
    from app.core.llm import structured

    return structured


def _repair(structured: Any):
    def repair(lines: list[str]) -> list[int]:
        prompt = "Candidate heading lines, in document order:\n" + "\n".join(
            f"{i + 1}. {line}" for i, line in enumerate(lines)
        )
        out = structured(
            prompt,
            _Levels,
            model="fast",
            prompt_version=REPAIR_PROMPT_VERSION,
            max_tokens=4096,
            system="You rebuild the outline of a document whose heading styles were lost. "
            "Assign each candidate line a heading level from its numbering and wording.",
        )
        return (out.levels + [0] * len(lines))[: len(lines)]

    return repair


def _fmt_day(d: Any) -> str:
    return f"{d.day} {d:%b %Y}" if d else "undated"


def display_locator(locator: str) -> str:
    head = locator.split(",")[0].split(" ")[0]
    return f"§{locator}" if head.replace(".", "").isdigit() else locator


def context_header(src: dict[str, Any], d: PassageDraft) -> str:
    parts = [src["short_label"]]
    loc = display_locator(d.locator)
    parts.append(
        f"{loc} {d.section_title}".strip()
        if d.section_title and d.section_title not in loc
        else loc
    )
    parts.append(f"effective {_fmt_day(src.get('dated'))}")
    if src.get("valid_until"):
        parts.append(f"until {_fmt_day(src['valid_until'])}")
    parts.append(f"status {src['status']}")
    scope = src.get("client_scope") or "all"
    parts.append("all clients" if scope == "all" else scope)
    return " · ".join(parts)


def _source_row(episode: Any, doc: DocPart, m: md.DocMeta) -> dict[str, Any]:
    sid = stable_id(episode.id, doc.ordinal)
    status = m.get("status", "current")
    if m.get("practice") and status == "current":
        status = "record"
    return {
        "id": sid,
        "episode_id": episode.id,
        "ordinal": doc.ordinal,
        "title": m.get("title_clean") or m.get("title") or episode.source_uri or "Document",
        "short_label": m.get("short_label") or "Document",
        "part_label": doc.label,
        "doc_type": m.get("doc_type", "other"),
        "version": m.get("version"),
        "dated": m.get("dated"),
        "valid_until": m.get("valid_until"),
        "status": status,
        "status_note": None,
        "owner": m.get("owner"),
        "client_scope": m.get("client_scope", "all"),
        "meta": {
            "header": doc.meta_kv,
            "ref": m.get("ref"),
            "practice": bool(m.get("practice")),
            "supersedes_hint": m.get("supersedes"),
            "applies_to": m.get("scope"),
            "container_title": doc.container_title,
        },
        "meta_provenance": {
            k: {"origin": v["origin"], "confidence": round(v["confidence"], 2)}
            for k, v in m.provenance().items()
        },
    }


def passage_rows(src: dict[str, Any], drafts: list[PassageDraft]) -> list[dict[str, Any]]:
    ids = {d.key: stable_id(src["id"], d.key) for d in drafts}
    rows = []
    for d in drafts:
        text = redact(d.text)
        rows.append(
            {
                "id": ids[d.key],
                "source_id": src["id"],
                "episode_id": src["episode_id"],
                "parent_id": ids.get(d.parent_key) if d.parent_key else None,
                "ordinal": d.ordinal,
                "segment_kind": d.segment_kind,
                "locator": d.locator,
                "heading_path": d.heading_path,
                "section_title": d.section_title,
                "speaker": d.speaker,
                "text": text,
                "context_header": redact(context_header(src, d)),
                "position": d.position,
                "client_scope": src.get("client_scope") or "all",
                "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "meta": {**d.meta, "leaf": d.leaf},
            }
        )
    return rows


def refresh_context_headers(session: Any, source_id: str) -> None:
    """Re-render context headers after a source's status or validity changed."""
    src = store.get_source(session, source_id)
    info = {
        c: getattr(src, c)
        for c in ("short_label", "dated", "valid_until", "status", "client_scope")
    }
    for p in store.passages_for_source(session, source_id):
        d = PassageDraft(
            p.id, p.segment_kind, p.locator, p.heading_path, p.section_title, "", 0, True
        )
        store.update_passage(session, p.id, context_header=redact(context_header(info, d)))


@handler("plugin_hooks")
def plugin_hooks(payload: dict[str, Any]) -> dict[str, Any]:
    """Let enabled plug-ins load their own data from an episode (e.g. ERP exports)."""
    from app.plugins import registry
    from app.store.base import tenant

    with session_scope() as s:
        ep = store.get_episode(s, payload["episode_id"])
        data = Path(ep.blob_path).read_bytes()
        out = {}
        for plugin, fn in registry.hooks(payload["event"]):
            out[plugin.name] = fn(s, data, tenant())
    return out


@handler("parse_episode")
def parse_episode(payload: dict[str, Any]) -> dict[str, Any]:
    eid = payload["episode_id"]
    with session_scope() as s:
        ep = store.get_episode(s, eid)
        if ep is None:
            raise LookupError(f"episode {eid} not found")
        data = Path(ep.blob_path).read_bytes()
        filename = ep.source_uri or ""
        episode = type(
            "E", (), {c: getattr(ep, c) for c in ("id", "channel", "received_at", "source_uri")}
        )()
    kind, _mime = detect(data, filename)
    result = parse(data, kind)
    summary: dict[str, Any] = {
        "kind": kind,
        "tier": result.tier,
        "quality": result.quality,
        "notes": result.notes,
    }
    if not result.blocks or result.quality < QUALITY_FLOOR:
        with session_scope() as s:
            store.set_status(
                s,
                eid,
                "needs_attention",
                parse_tier=result.tier,
                parse_quality=result.quality,
                error="; ".join(result.notes) or "nothing could be parsed",
            )
        return summary

    structured = _llm_structured()
    blocks = infer_headings(result.blocks, repair=_repair(structured) if structured else None)
    docs = split_documents(blocks)

    def one(doc: DocPart) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        m = md.infer(
            doc,
            filename=filename,
            file_meta=result.file_meta,
            received_at=episode.received_at,
            channel=episode.channel,
            llm_fn=structured,
        )
        src = _source_row(episode, doc, m)
        return src, passage_rows(src, segment(doc)), m.low_confidence()

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=6) as pool:
        sources = list(pool.map(one, docs))

    with session_scope() as s:
        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        for src, rows, low in sources:
            store.upsert_source(s, src)
            for k, v in store.upsert_passages(s, rows).items():
                counts[k] += v
            if low:
                kb.add_review_item(
                    s,
                    "metadata",
                    {
                        "source_id": src["id"],
                        "label": src["short_label"],
                        "fields": low,
                        "values": {k: str(src.get(k) or src["meta"].get(k)) for k in low},
                    },
                )
        links = []
        govern = get_settings().governance
        for src, _, _ in sources:
            if govern:
                break  # a governed new version replaces the old one only once approved
            for link in versions.link_versions(s, src["id"]):
                links.append(link.__dict__)
                refresh_context_headers(s, link.older_id)
                # Facts already published from the older version must be re-resolved.
                jobs.enqueue(s, "reresolve_source", {"source_id": link.older_id})
        old_meta = store.get_episode(s, eid).meta or {}
        store.set_status(
            s,
            eid,
            "parsed",
            parse_tier=result.tier,
            parse_quality=result.quality,
            error=None,
            meta={
                **old_meta,
                "sources": len(sources),
                "passages": sum(len(r) for _, r, _ in sources),
                "versions": links,
                "parse_notes": result.notes,
                "defer_versions": govern,
            },
        )
        jobs.enqueue(s, "extract_episode", {"episode_id": eid, "govern": govern})
        jobs.enqueue_once(s, "index_embeddings", {})
        if kind in ("xlsx", "csv"):
            jobs.enqueue(s, "plugin_hooks", {"episode_id": eid, "event": "on_spreadsheet"})
    summary.update(sources=len(sources), passages=counts, versions=links)
    return summary
