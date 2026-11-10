"""Intake and governance check (TEST_PLAN level 9).

Feeds every synthetic email in synthetic/emails/ through the email channel, one at a time and
with governance on, into a tenant whose knowledge base is already built (default: the live
one). For each it records the triage label, what governance decided and how long it took to
settle, compares with eval/episodes_expected.csv, then removes everything it added (unless
--keep), so the knowledge base is left as it was.

    python scripts/run_intake.py                 # tenant from TENANT_ID
    python scripts/run_intake.py --tenant replay --keep

Writes reports/intake_<date>.md and .csv. Uses the configured LLM for triage, extraction and
the one emailed question.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["GOVERNANCE"] = "true"  # live inputs: the point of this check

from app import worker  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.ingest.connectors import from_eml  # noqa: E402
from app.ingest.intake import submit  # noqa: E402
from app.store import episodes as estore  # noqa: E402
from app.store import kb  # noqa: E402
from app.store.base import use_tenant  # noqa: E402

EMAILS = ROOT / "synthetic" / "emails"
EXPECTED = ROOT / "eval" / "episodes_expected.csv"
REPORTS = ROOT / "reports"
KINDS = ["parse_episode", "extract_episode", "plugin_hooks", "apply_review"]


def outcome(s, eid: str, created: bool) -> tuple[str, str, int]:
    """(triage label, outcome, confirmations) for one episode."""
    ep = estore.get_episode(s, eid)
    if not created:
        return "", "duplicate", ep.confirmations if ep else 0
    if ep is None:
        return "", "missing", 0
    if ep.status in ("ignored", "answered", "needs_attention", "failed"):
        return ep.triage_label or "", ep.status, ep.confirmations
    item = next(
        (
            i
            for i in kb.list_review_items(s)
            if i.kind == "change" and (i.payload or {}).get("episode_id") == eid
        ),
        None,
    )
    if item is not None:
        return ep.triage_label or "", (item.payload or {}).get("status", "?"), ep.confirmations
    return ep.triage_label or "", ep.status, ep.confirmations


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=get_settings().tenant_id)
    ap.add_argument("--keep", action="store_true", help="leave the emails in the tenant")
    args = ap.parse_args()

    with EXPECTED.open(encoding="utf-8") as f:
        expected = {r["file"]: r for r in csv.DictReader(f)}
    rows, added = [], []
    with use_tenant(args.tenant):
        with session_scope() as s:
            kb_before = kb.current_kb_version(s)
        for path in sorted(EMAILS.glob("*.eml")):
            started = time.perf_counter()
            with session_scope() as s:
                ep = from_eml(path.read_bytes(), channel="email")[0]
                eid, created = submit(s, ep)
            if created:
                added.append(eid)
                worker.drain(kinds=KINDS, threads=1)
            secs = time.perf_counter() - started
            with session_scope() as s:
                label, got, confirmations = outcome(s, eid, created)
                ep_row = estore.get_episode(s, eid)
                answer = ((ep_row.meta or {}).get("answer") or {}) if ep_row else {}
            want = expected.get(path.name, {})
            ok = got == want.get("expect_outcome") and (
                not want.get("expect_triage") or label == want.get("expect_triage")
            )
            rows.append(
                {
                    "file": path.name,
                    "triage": label,
                    "outcome": got,
                    "expected": (
                        f"{want.get('expect_triage') or '-'} / {want.get('expect_outcome')}"
                    ),
                    "ok": ok,
                    "seconds": round(secs, 1),
                    "confirmations": confirmations,
                    "answer": (answer.get("text") or "")[:160],
                }
            )
            print(f"{'PASS' if ok else 'FAIL'} {path.name}: {label or '-'} -> {got} ({secs:.0f}s)")
        with session_scope() as s:
            kb_after = kb.current_kb_version(s)
        if added and not args.keep:
            with session_scope() as s:
                estore.delete_episodes(s, added)
                kb.bump_kb_version(s, "removed the intake check's test emails")
            print(f"removed {len(added)} test episodes from {args.tenant}")

    passed = sum(r["ok"] for r in rows)
    stamp = date.today().strftime("%Y%m%d")
    REPORTS.mkdir(exist_ok=True)
    with (REPORTS / f"intake_{stamp}.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    single = next((r["seconds"] for r in rows if r["file"].startswith("01_")), None)
    lines = [
        f"# Intake and governance check — {date.today():%d %b %Y}",
        "",
        f"- tenant: {args.tenant}; governance on; emails: {len(rows)}",
        f"- **passed: {passed}/{len(rows)}**",
        f"- one email to a settled change (01): {single} s (target < 60 s)",
        f"- kb_version {kb_before} -> {kb_after} during the check"
        + ("" if args.keep else "; test episodes removed afterwards"),
        "",
        "| file | triage | outcome | expected | ok | s | confirmations |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *[
            f"| {r['file']} | {r['triage'] or '-'} | {r['outcome']} | {r['expected']} | "
            f"{'yes' if r['ok'] else 'NO'} | {r['seconds']} | {r['confirmations']} |"
            for r in rows
        ],
    ]
    if any(r["answer"] for r in rows):
        lines += ["", "Emailed question, answer given:", ""]
        lines += [f"- {r['file']}: {r['answer']}" for r in rows if r["answer"]]
    (REPORTS / f"intake_{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed}/{len(rows)} -> reports/intake_{stamp}.md")


if __name__ == "__main__":
    main()
