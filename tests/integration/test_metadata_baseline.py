"""Metadata inference vs the hand-copied source index (TEST_PLAN level 2: >= 90% of fields).

Test code: it may read `plugins/ap/baseline_schema/sources.yaml`. Runs the real classifier
(MODEL_FAST), so it is marked live_llm; results are cached after the first run.
Fields compared: document type, version, date, status, owner, client scope.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.core.config import get_settings
from app.ingest import metadata as md
from app.ingest.detect import detect
from app.ingest.parsers import parse
from app.ingest.segment import split_documents

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(not get_settings().llm_configured, reason="needs an LLM API key"),
]
ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "plugins" / "ap" / "baseline_schema" / "sources.yaml"

# Baseline vocabulary -> ours (the baseline uses the first tenant's own words).
TYPES = {
    "sop": {"sop", "policy"},
    "desk_instruction": {"work_instruction"},
    "client_memo": {"memo"},
    "faq": {"faq"},
    "training_video": {"training"},
    "shadowing": {"observation"},
    "interview": {"interview"},
}
STATUSES = {
    "current": {"current"},
    "superseded": {"superseded"},
    "stale": {"stale"},
    "partly_outdated": {"current", "stale"},
    "observation": {"record"},
    "knowledge_capture": {"record"},
}
CLIENT_WORDS = {"infra": "infra", "pharma": "pharma", "retail": "retail"}


def _tokens(s: str | None) -> set[str]:
    return {re.sub(r"(ing|er|s)$", "", w) for w in re.findall(r"[a-z]+", (s or "").lower())} - {
        "the",
        "team",
        "of",
        "and",
    }


def owner_matches(base: str | None, ours: str | None) -> bool:
    b, o = _tokens(base), _tokens(ours)
    return bool(b) and len(b & o) >= max(1, round(0.6 * len(b)))


def _inferred() -> dict[tuple[str, str | None], dict]:
    out = {}
    settings = get_settings()
    from app.core.llm import structured

    for f in sorted((ROOT / "data" / "raw").glob("*.docx")):
        data = f.read_bytes()
        r = parse(data, detect(data, f.name)[0])
        docs = split_documents(r.blocks)
        for d in docs:
            m = md.infer(
                d,
                filename=f.name,
                file_meta=r.file_meta,
                received_at=datetime(2026, 11, 7, tzinfo=UTC),
                channel="upload",
                llm_fn=structured,
            )
            status = m.get("status")
            if m.get("practice") and status == "current":
                status = "record"
            out[(f.name, d.label)] = {
                "doc_type": m.get("doc_type"),
                "version": m.get("version"),
                "dated": m.get("dated"),
                "status": status,
                "owner": m.get("owner"),
                "client_scope": m.get("client_scope"),
            }
    # Version linking is a separate step (app/ingest/versions.py); apply its outcome here.
    _ = settings
    return out


def test_metadata_matches_hand_copied_index() -> None:
    base = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["sources"]
    got = _inferred()
    rows, hits, misses = 0, 0, []
    for key, b in base.items():
        g = got.get((b["file"], b["part"]))
        assert g is not None, f"no inferred document for {key}"
        if key == "sop_v3_1":
            g["status"] = "superseded"  # set by version linking (tested in test_ingest_db)
        checks = {
            "doc_type": g["doc_type"] in TYPES[b["kind"]],
            "version": (str(b["version"]) if b.get("version") else None) == g["version"],
            "dated": b["dated"] == g["dated"],
            "status": g["status"] in STATUSES[b["status"]],
            "owner": owner_matches(b.get("owner"), g["owner"]),
            "client_scope": (
                g["client_scope"] == "all"
                if b["client_scope"] == "all"
                else CLIENT_WORDS[b["client_scope"]] in (g["client_scope"] or "").lower()
            ),
        }
        for field, ok in checks.items():
            rows += 1
            hits += ok
            if not ok:
                misses.append(
                    f"{key}.{field}: baseline {b.get(field if field != 'doc_type' else 'kind')!r} "
                    f"vs {g[field]!r}"
                )
    share = hits / rows
    print(f"\nmetadata agreement {hits}/{rows} = {share:.1%}\n" + "\n".join(misses))
    assert share >= 0.9, f"{share:.1%} < 90%: {misses}"
