"""Second company (TEST_PLAN level 16): a new tenant, no plug-ins, no code or config changes.

Drops synthetic/corpus2_hr/ through the upload connector, accepts the induced schema as it is
(auto-freeze, no edits), extracts, places unplaced facts, indexes, and asks the 10 questions in
questions.csv. A question passes when its status matches, an expected value is in the current
answer, the must-not-say value is not, and a citation points at the expected file.

    python scripts/run_second_corpus.py
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

os.environ["PLUGINS"] = ""  # the second company runs on the core alone
os.environ.setdefault("SCHEMA_MODE", "induced")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The owner seeding or measuring the knowledge base: no approval step for these inputs.
os.environ.setdefault("GOVERNANCE", "false")

from app import worker  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.graph import pipeline as gp  # noqa: E402
from app.ingest.connectors import from_paths  # noqa: E402
from app.ingest.intake import submit  # noqa: E402
from app.store import episodes as estore  # noqa: E402
from app.store import jobs  # noqa: E402
from app.store.base import use_tenant  # noqa: E402

CORPUS = ROOT / "synthetic" / "corpus2_hr"
REPORTS = ROOT / "reports"
TODAY = date.today()  # the corpus files are dated by when they were written


def build(tenant: str) -> dict[str, float]:
    t: dict[str, float] = {}
    with use_tenant(tenant):
        start = time.perf_counter()
        with session_scope() as s:
            estore.delete_tenant_content(s)
            files = [p for p in sorted(CORPUS.iterdir()) if p.name != "questions.csv"]
            for p in files:
                for ep in from_paths([p]):
                    submit(s, ep)
        worker.drain(kinds=["parse_episode", "plugin_hooks"], threads=2)
        t["parse_s"] = time.perf_counter() - start
        version, status = gp.ensure_schema(auto_freeze=True, mode="induced")
        t["schema_s"] = time.perf_counter() - start - t["parse_s"]
        with session_scope() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM jobs WHERE kind='extract_episode' "
                    "AND status='queued' AND tenant_id=:t"
                ),
                {"t": tenant},
            )
            for eid in estore.parsed_episode_ids(s):
                jobs.enqueue(s, "extract_episode", {"episode_id": eid})
        worker.drain(kinds=["extract_episode", "reresolve_source"], threads=2)
        with session_scope() as s:
            s.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM jobs WHERE kind='evolve_schema' AND tenant_id=:t"
                ),
                {"t": tenant},
            )
        gp.evolve_schema(auto_freeze=True, mode="induced")
        from app.answer.index import index_all

        index_all()
        t["build_s"] = time.perf_counter() - start
    print(f"built tenant {tenant}: schema v{version} ({status}); {t}")
    return t


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def grade(q: dict[str, str], card: dict) -> tuple[bool, str]:
    current = norm(
        " ".join([(card.get("rule") or {}).get("text") or "", card.get("decision") or ""])
    )
    status = "answered" if card.get("status") == "provisional" else card.get("status")
    if status != q["status"]:
        return False, f"status {card.get('status')}, expected {q['status']}"
    if q["status"] == "unsupported":
        ok = bool(card.get("route_to"))
        return ok, "abstained and routed" if ok else "abstained without a route"
    wants = [w for w in q["expected"].split("|") if w]
    if wants and not any(
        re.search(rf"(?<![\w.]){re.escape(norm(w))}(?![\w.])", current) for w in wants
    ):
        return False, f"expected one of {wants}"
    if q["must_not_say"] and re.search(
        rf"(?<![\w.]){re.escape(norm(q['must_not_say']))}(?![\w.])", current
    ):
        return False, f"says the superseded value {q['must_not_say']!r}"
    files = {c.get("file") for c in (card.get("rule") or {}).get("citations") or []}
    if q["file"] and not files & set(q["file"].split("|")):
        return False, f"cites {sorted(f for f in files if f)}, expected {q['file']}"
    return True, "ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="corpus2")
    ap.add_argument("--skip-build", action="store_true", help="ask only (graph already built)")
    args = ap.parse_args()
    timings = {} if args.skip_build else build(args.tenant)
    from app.answer.pipeline import ask

    with (CORPUS / "questions.csv").open(encoding="utf-8") as f:
        questions = list(csv.DictReader(f))
    rows = []
    with use_tenant(args.tenant):
        for q in questions:
            started = time.perf_counter()
            card = ask(
                q["question"],
                as_of=date.fromisoformat(q["as_of"]) if q["as_of"] else None,
                today=TODAY,
                viewer="eval",
            )
            ok, why = grade(q, card)
            rows.append(
                {
                    "id": q["id"],
                    "ok": ok,
                    "why": why,
                    "status": card.get("status"),
                    "latency_s": round(time.perf_counter() - started, 1),
                    "answer": (card.get("rule") or {}).get("text", "")[:300],
                    "cites": "; ".join(
                        c.get("short_label", "")
                        for c in (card.get("rule") or {}).get("citations") or []
                    ),
                    "question": q["question"],
                }
            )
            print(f"  {q['id']} {'PASS' if ok else 'FAIL'} {why}")
    passed = sum(r["ok"] for r in rows)
    REPORTS.mkdir(exist_ok=True)
    md = REPORTS / f"second_corpus_{date.today():%Y%m%d}.md"
    lines = [
        f"# Second company (Kestrel Freight HR) — {datetime.now():%d %b %Y %H:%M}",
        "",
        f"- passed: {passed}/{len(rows)} (target 10/10, each with a valid citation)",
        "- plug-ins enabled: none; schema: induced and accepted without edits",
        f"- build timings: {timings or 'skipped'}",
        "",
        "| id | ok | status | why | cites | answer |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {'PASS' if r['ok'] else 'FAIL'} | {r['status']} | {r['why']} "
            f"| {r['cites']} | {r['answer'].replace('|', '/')[:160]} |"
        )
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"{passed}/{len(rows)} passed; report {md}")


if __name__ == "__main__":
    main()
