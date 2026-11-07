"""Write sources, passages and vendors to the database. Idempotent."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.models import Passage, Source, Vendor
from app.core.pack import Pack
from app.ingest.passages import ParsedCorpus, parse_corpus


@dataclass
class IngestReport:
    sources: int = 0
    passages_total: int = 0
    passages_inserted: int = 0
    passages_updated: int = 0
    passages_unchanged: int = 0
    passages_deleted: int = 0
    vendors: int = 0
    per_source: dict[str, int] = field(default_factory=dict)


def upsert_sources(session: Session, pack: Pack, source_meta: dict[str, dict[str, str]]) -> int:
    for s in pack.sources.values():
        values = {
            "id": s.id,
            "file": s.file,
            "part": s.part,
            "title": s.title,
            "label": s.label,
            "version": s.version,
            "dated": s.dated,
            "status": s.status,
            "status_note": s.status_note,
            "owner": s.owner,
            "authority_rank": s.authority_rank,
            "client_scope": s.client_scope,
            "kind": s.kind,
            "valid_to": s.valid_to,
            "meta": source_meta.get(s.id, {}),
        }
        stmt = insert(Source).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Source.id], set_={k: v for k, v in values.items() if k != "id"}
        )
        session.execute(stmt)
    return len(pack.sources)


def upsert_passages(session: Session, corpus: ParsedCorpus, report: IngestReport) -> None:
    existing = dict(session.execute(select(Passage.id, Passage.content_hash)).all())
    new_ids = {p.id for p in corpus.passages}
    for p in corpus.passages:
        report.per_source[p.source_id] = report.per_source.get(p.source_id, 0) + 1
        values = asdict(p)
        old_hash = existing.get(p.id)
        if old_hash == p.content_hash:
            report.passages_unchanged += 1
            continue
        stmt = (
            insert(Passage)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Passage.id], set_={k: v for k, v in values.items() if k != "id"}
            )
        )
        session.execute(stmt)
        if old_hash is None:
            report.passages_inserted += 1
        else:
            report.passages_updated += 1

    # Remove passages that no longer exist in the corpus, unless a claim cites them
    # (claims are never deleted, so their evidence must stay).
    sources = sorted({p.source_id for p in corpus.passages})
    stale = [pid for pid in existing if pid not in new_ids]
    if stale:
        result = session.execute(
            text(
                "DELETE FROM passages p WHERE p.id = ANY(:ids) AND p.source_id = ANY(:srcs) "
                "AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.passage_id = p.id)"
            ),
            {"ids": stale, "srcs": sources},
        )
        report.passages_deleted = result.rowcount or 0
    report.passages_total = len(corpus.passages)


def _clean(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def _bool(v: Any) -> bool | None:
    v = _clean(v)
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return bool(v)


def load_vendors(session: Session, pack: Pack, data_dir: Path) -> int:
    ops = pack.operations
    if not ops:
        return 0
    df = pd.read_excel(data_dir / ops["file"], sheet_name=ops["vendors_sheet"])
    forbidden = {
        c for c in df.columns if any(k in c.lower() for k in ("pan", "bank", "ifsc", "account"))
    }
    if forbidden:
        raise ValueError(f"vendor sheet has sensitive columns {forbidden}; refusing to load")
    count = 0
    for rec in df.to_dict(orient="records"):
        term = _clean(rec.get("payment_term_days"))
        aato = _clean(rec.get("aato_crore"))
        values = {
            "vendor_id": str(rec["vendor_id"]),
            "name": str(rec["vendor_name"]),
            "primary_client": pack.client_key_for_name(_clean(rec.get("primary_client"))),
            "state": _clean(rec.get("state")),
            "msme_category": _clean(rec.get("msme_category")),
            "supply_type": _clean(rec.get("supply_type")),
            "aato_crore": float(aato) if aato is not None else None,
            "einvoice_required": _bool(rec.get("einvoice_required")),
            "qrmp_filer": _bool(rec.get("qrmp_filer")),
            "default_tds_section": _clean(rec.get("default_tds_section")),
            "payment_term_days": int(term) if term is not None else None,
            "written_term_agreement": _bool(rec.get("written_term_agreement")),
            "habit_note": _clean(rec.get("habit_note")),
        }
        stmt = (
            insert(Vendor)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Vendor.vendor_id],
                set_={k: v for k, v in values.items() if k != "vendor_id"},
            )
        )
        session.execute(stmt)
        count += 1
    return count


def ingest(session: Session, pack: Pack, data_dir: Path, with_vendors: bool = True) -> IngestReport:
    corpus = parse_corpus(pack, data_dir)
    report = IngestReport()
    report.sources = upsert_sources(session, pack, corpus.source_meta)
    upsert_passages(session, corpus, report)
    if with_vendors:
        report.vendors = load_vendors(session, pack, data_dir)
    return report
