"""Continuous-update replay (TEST_PLAN level 14).

Starts an empty tenant, gives it the source tenant's frozen schema and plug-in bindings (the
vocabulary and configuration, never facts), and feeds the corpus in order through the real
ingestion and extraction path:

    SOP v3.1 -> SOP v4.0 -> training and interview transcripts (lower-ranked, arriving late)
    -> desk instructions and client memos -> synthetic emails

After each episode it runs the probes in eval/replay_probes.csv whose `after_episode` is that
file; transaction-time probes (`after_episode` END) run last with known_at = the moment the
named episode had been processed. Probes read rules through the plug-in bindings, so they test
the graph and its time axes, not answer generation. Then an idempotence check re-ingests every
file and expects no new facts and no new kb_versions.

    python scripts/run_replay.py                  # schema from the default tenant
    python scripts/run_replay.py --stop-after PS-07_AP_SOP_v3.1_2023.docx

Writes reports/replay_<date>.md and .csv. Extraction is cached, so a second run is fast.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The owner seeding or measuring the knowledge base: no approval step for these inputs.
os.environ.setdefault("GOVERNANCE", "false")

from app import worker  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.graph.ontology import Ontology  # noqa: E402
from app.graph.rules import RuleNotFound, get_rule  # noqa: E402
from app.ingest.connectors import from_paths  # noqa: E402
from app.ingest.intake import submit  # noqa: E402
from app.store import facts as fstore  # noqa: E402
from app.store import kb  # noqa: E402
from app.store.base import use_tenant  # noqa: E402
from evaluation.tenants import clone_config  # noqa: E402

ORDER = [
    ROOT / "data" / "raw" / "PS-07_AP_SOP_v3.1_2023.docx",
    ROOT / "data" / "raw" / "PS-07_AP_SOP_v4.0_2026.docx",
    ROOT / "data" / "raw" / "PS-07_training_and_expert_transcripts.docx",
    ROOT / "data" / "raw" / "PS-07_desk_instructions_and_client_memos.docx",
    *sorted((ROOT / "synthetic" / "emails").glob("*.eml")),
]
PROBES = ROOT / "eval" / "replay_probes.csv"
REPORTS = ROOT / "reports"
TODAY = date(2026, 11, 7)
KINDS = ["parse_episode", "plugin_hooks", "extract_episode", "reresolve_source"]


def setup(target: str, source: str, mode: str) -> Ontology:
    try:
        onto = clone_config(target, source, mode)
    except LookupError as exc:
        sys.exit(str(exc))
    print(f"tenant {target}: schema and bindings copied from {source}")
    return onto


def probe(onto: Ontology, binds: dict[str, str], p: dict[str, str], known_at: datetime | None):
    attr = binds.get(p["param"])
    if not attr:
        return "unbound", False
    topic, _, parameter = p["param"].partition(".")
    as_of = date.fromisoformat(p["as_of"]) if p["as_of"] else None
    want = p["expected"].strip()
    try:
        with session_scope() as s:
            rv = get_rule(
                s,
                onto,
                topic,
                parameter,
                client=p["client"] or None,
                as_of=as_of,
                known_at=known_at,
                today=TODAY,
                attribute=attr,
            )
        if want.startswith("items:"):
            got = {x.strip().lower() for x in (rv.items or [rv.text])}
            return ", ".join(sorted(got)), got == {x.lower() for x in want[6:].split("|")}
        got_n = rv.value.get("number")
        if want == "none":
            return f"{rv.text} ({rv.source_label})", got_n is None
        return f"{got_n} ({rv.source_label} {rv.status})", got_n is not None and abs(
            float(got_n) - float(want)
        ) < 1e-6
    except RuleNotFound as exc:
        return f"none ({exc})", want == "none"


def ingest(path: Path) -> float:
    started = time.perf_counter()
    with session_scope() as s:
        for ep in from_paths([path]):
            submit(s, ep)
    worker.drain(kinds=KINDS, threads=1)
    return time.perf_counter() - started


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="replay")
    ap.add_argument("--source-tenant", default="default")
    ap.add_argument("--mode", default="induced")
    ap.add_argument("--stop-after", help="file name: stop the replay after this episode")
    args = ap.parse_args()

    with PROBES.open(encoding="utf-8") as f:
        probes = list(csv.DictReader(f))
    onto = setup(args.tenant, args.source_tenant, args.mode)
    rows, known_after, timings = [], {}, {}
    with use_tenant(args.tenant):
        with session_scope() as s:
            binds = {b.param: b.attribute_key for b in kb.get_bindings(s, "ap") if b.attribute_key}
        for path in ORDER:
            secs = ingest(path)
            known_after[path.name] = datetime.now(UTC)
            timings[path.name] = secs
            with session_scope() as s:
                n = fstore.count_live(s)
            print(f"{path.name}: {secs:.0f}s, {n} live facts")
            for p in probes:
                if p["after_episode"] == path.name:
                    got, ok = probe(onto, binds, p, None)
                    rows.append({**p, "got": got, "ok": ok})
                    print(f"  {p['id']} {'PASS' if ok else 'FAIL'} {p['covers']}: {got}")
            if args.stop_after and path.name == args.stop_after:
                break
        for p in probes:
            if p["after_episode"] == "END" and p["known_after"] in known_after:
                got, ok = probe(onto, binds, p, known_after[p["known_after"]])
                rows.append({**p, "got": got, "ok": ok})
                print(f"  {p['id']} {'PASS' if ok else 'FAIL'} {p['covers']}: {got}")
        # Idempotence: re-ingesting everything adds no facts and no kb versions.
        with session_scope() as s:
            before = (fstore.total_rows(s), kb.current_kb_version(s))
        for path in [p for p in ORDER if p.name in known_after]:
            ingest(path)
        with session_scope() as s:
            after = (fstore.total_rows(s), kb.current_kb_version(s))
    idempotent = before == after
    write_report(rows, timings, idempotent, before, after)


def write_report(rows, timings, idempotent, before, after) -> None:
    REPORTS.mkdir(exist_ok=True)
    stamp = f"{date.today():%Y%m%d}"
    passed = sum(r["ok"] for r in rows)
    lines = [
        f"# Replay — {datetime.now():%d %b %Y %H:%M}",
        "",
        f"- probes: {passed}/{len(rows)} pass (target 100%)",
        f"- idempotence: {'PASS' if idempotent else 'FAIL'} "
        f"(fact rows, kb_version before {before}, after re-ingesting everything {after})",
        "- seconds per episode: " + ", ".join(f"{k} {v:.0f}" for k, v in timings.items()),
        "",
        "| id | after | param | client | as of | known after | expected | got | ok | covers |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['after_episode']} | {r['param']} | {r['client']} | {r['as_of']} "
            f"| {r['known_after']} | {r['expected']} | {str(r['got']).replace('|', '/')[:90]} "
            f"| {'PASS' if r['ok'] else 'FAIL'} | {r['covers']} |"
        )
    (REPORTS / f"replay_{stamp}.md").write_text("\n".join(lines), encoding="utf-8")
    with (REPORTS / f"replay_{stamp}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    print(f"probes {passed}/{len(rows)}; idempotent {idempotent}; report reports/replay_{stamp}.md")


if __name__ == "__main__":
    main()
