"""Conflict scan report (BUILD_PLAN Phase 6, TEST_PLAN level 6).

Runs the scan on a tenant's live graph, records the conflicts, and writes
reports/conflicts_<date>.md. With --score it matches them to the known_conflicts sheet (this
script is test code; the scan never reads the key) and reports recall twice: on the whole
graph, and with the passages of the change-table section excluded (--caveat), because that
section states many conflicts outright.

    python scripts/conflict_report.py --score
    python scripts/conflict_report.py --no-judge          # deterministic part only, no LLM
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.db import session_scope  # noqa: E402
from app.graph.conflicts import Found, ModelJudge, describe, scan, value_text  # noqa: E402
from app.store.base import use_tenant  # noqa: E402
from app.store.models import Episode, Passage  # noqa: E402

REPORTS = ROOT / "reports"
CAVEAT = "PS-07_AP_SOP_v4.0_2026.docx:14"  # SOP v4.0 §14, the v3.1 -> v4.0 change table


def passage_places(session) -> dict[str, tuple[str, str]]:
    rows = session.execute(
        select(Passage.id, Episode.source_uri, Passage.locator).join(
            Episode, Episode.id == Passage.episode_id
        )
    )
    return {pid: (Path(uri or "").name, loc or "") for pid, uri, loc in rows}


def excluded(places: dict[str, tuple[str, str]], spec: str) -> set[str]:
    file, _, section = spec.partition(":")
    return {
        pid
        for pid, (f, loc) in places.items()
        if f == file and (loc == section or loc.startswith((section + ".", section + " ")))
    }


def detected(found: list[Found], places: dict[str, tuple[str, str]]):
    from evaluation.conflict_key import Detected

    out = []
    for c in found:
        a, b = c.authoritative, c.other
        fa, la = places.get(a.passage_id or "", ("", ""))
        fb, lb = places.get(b.passage_id or "", ("", ""))
        out.append(
            Detected(
                auth_file=fa,
                auth_loc=la,
                other_file=fb,
                other_loc=lb,
                auth_source=a.source_label or "",
                kind=c.kind,
                text=" ".join(
                    [a.attribute, a.statement, b.statement, value_text(a), value_text(b)]
                ),
                extra=describe(c),
                auth_also=[places.get(x.passage_id or "", ("", "")) for x in c.support],
            )
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--score", action="store_true", help="match against known_conflicts")
    ap.add_argument("--no-judge", action="store_true", help="deterministic comparisons only")
    ap.add_argument("--caveat", default=CAVEAT, help="FILE:SECTION reported without")
    args = ap.parse_args()

    runs: dict[str, dict] = {}
    with use_tenant(args.tenant), session_scope() as s:
        places = passage_places(s)
        caveat = excluded(places, args.caveat)
        for name, skip, record in [("all", set(), True), ("without caveat", caveat, False)]:
            judge = None if args.no_judge else ModelJudge()
            t0 = time.perf_counter()
            rep = scan(s, judge=judge, exclude_passages=skip, record=record)
            runs[name] = {
                "report": rep,
                "seconds": time.perf_counter() - t0,
                "detected": detected(rep.found, places),
            }
            print(f"{name}: {rep.summary()} in {runs[name]['seconds']:.0f}s")

    scores = {}
    if args.score:
        from evaluation.conflict_key import load_known, score

        key = load_known()
        for name, r in runs.items():
            scores[name] = score(r["detected"], key)
            sc = scores[name]
            print(
                f"{name}: recall {sc['recall']}/{sc['total']} "
                f"(missed {sc['missed']}); authoritative right "
                f"{len(sc['authoritative_right'])}/{sc['recall']}; extra {len(sc['extra'])}"
            )

    REPORTS.mkdir(exist_ok=True)
    stamp = f"{date.today():%Y%m%d}"
    full = runs["all"]
    lines = [
        f"# Conflict scan — {datetime.now():%d %b %Y %H:%M} (tenant {args.tenant})",
        "",
        f"- scan: {full['report'].summary()} in {full['seconds']:.0f}s",
        f"- judge: {'none (deterministic only)' if args.no_judge else 'MODEL_SMART, thinking off'}",
    ]
    if scores:
        lines += ["", "## Recall against the known conflicts", ""]
        lines += ["| run | recall | authoritative right | missed | extra (to label) |"]
        lines += ["| --- | --- | --- | --- | --- |"]
        for name, sc in scores.items():
            lines.append(
                f"| {name} | {sc['recall']}/{sc['total']} | "
                f"{len(sc['authoritative_right'])}/{sc['recall']} | "
                f"{', '.join(sc['missed']) or '-'} | {len(sc['extra'])} |"
            )
        lines += [
            "",
            f"'without caveat' excludes passages in {args.caveat} (the change table).",
            "",
            "## Matched",
            "",
        ]
        for kid, ds in sorted(scores["all"]["hits"].items()):
            d = ds[0].extra
            lines.append(
                f"- **{kid}** {d['topic']}: {d['authoritative']['source']} "
                f"{d['authoritative']['locator']} = {d['authoritative']['value']} vs "
                f"{d['conflicting']['source']} {d['conflicting']['locator']} = "
                f"{d['conflicting']['value']}. {d['reason']}"
            )
    lines += ["", "## All conflicts found", ""]
    lines += ["| kind | topic | authoritative | conflicting | reason | by |"]
    lines += ["| --- | --- | --- | --- | --- | --- |"]
    for d in full["detected"]:
        x = d.extra
        a, b = x["authoritative"], x["conflicting"]
        lines.append(
            f"| {x['kind']} | {x['topic']} | {a['source']} {a['locator']}: {a['value'][:60]} "
            f"| {b['source']} {b['locator']}: {b['value'][:60]} | {x['reason'][:140]} "
            f"| {x['judged_by']}/{x['via']} |".replace("\n", " ")
        )
    md = REPORTS / f"conflicts_{stamp}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    if scores:  # extra conflicts to label real or false by hand (precision)
        extra_csv = REPORTS / f"conflicts_{stamp}_extra.csv"
        with extra_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["topic", "authoritative", "conflicting", "reason", "label (real/false)"])
            for d in scores["all"]["extra"]:
                x = d.extra
                w.writerow(
                    [
                        x["topic"],
                        f"{x['authoritative']['source']} {x['authoritative']['locator']}: "
                        f"{x['authoritative']['value']}",
                        f"{x['conflicting']['source']} {x['conflicting']['locator']}: "
                        f"{x['conflicting']['value']}",
                        x["reason"],
                        "",
                    ]
                )
    (REPORTS / f"conflicts_{stamp}.json").write_text(
        json.dumps([d.extra for d in full["detected"]], indent=1, default=str), encoding="utf-8"
    )
    print("report:", md)


if __name__ == "__main__":
    main()
