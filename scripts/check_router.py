"""Route-only regression check: run just the question router on every evaluation question and
the abstention set, and compare two router versions question by question.

    python scripts/check_router.py --tag v5              # writes reports/router_routes_v5.csv
    python scripts/check_router.py --compare v5 v6       # what changed between two runs

A router change needs the full answer pipeline re-run only for questions whose route, scope or
as_of date changed; the rest reach the same downstream steps with the same inputs. Holdout rows
are compared by count only (TEST_PLAN: no looking at holdout questions beyond their scores).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.answer.pipeline import _default_structured, known_clients  # noqa: E402
from app.answer.router import PROMPT_VERSION, route  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.plugins import calculate as calc_mod  # noqa: E402
from app.plugins import registry  # noqa: E402
from evaluation import dataset  # noqa: E402

OUT = ROOT / "reports"
FIELDS = ["id", "split", "route", "client", "as_of", "role", "reason", "confidence"]
DOWNSTREAM = ("route", "client", "as_of")  # what the rest of the pipeline reads


def questions() -> list[tuple[str, str, str]]:
    qs = dataset.with_split(dataset.load())
    rows = [(q.id, q.split, q.question) for q in qs]
    with (ROOT / "eval" / "abstain.csv").open(encoding="utf-8") as f:
        rows += [(r["id"], "abstain", r["question"]) for r in csv.DictReader(f)]
    return rows


def run(tag: str) -> None:
    roles = registry.roles()
    calculators = calc_mod.routes()
    with session_scope() as s:
        clients = known_clients(s)
    structured = _default_structured()
    rows = questions()

    def one(item: tuple[str, str, str]) -> dict:
        qid, split, text = item
        r = route(text, clients, calculators, roles, structured)
        return {
            "id": qid,
            "split": split,
            "route": r.route,
            "client": r.client or "",
            "as_of": r.as_of or "",
            "role": r.role or "",
            "reason": r.out_of_scope_reason or "",
            "confidence": r.confidence,
        }

    t0 = time.perf_counter()
    with ThreadPoolExecutor(4) as pool:
        out = list(pool.map(one, rows))
    path = OUT / f"router_routes_{tag}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    secs = time.perf_counter() - t0
    print(f"{PROMPT_VERSION}: {len(out)} questions routed in {secs:.0f} s -> {path}")


def compare(a: str, b: str) -> None:
    def load(tag: str) -> dict[str, dict]:
        with (OUT / f"router_routes_{tag}.csv").open(encoding="utf-8") as f:
            return {r["id"]: r for r in csv.DictReader(f)}

    old, new = load(a), load(b)
    changed = [i for i in old if any(old[i][k] != new[i][k] for k in DOWNSTREAM)]
    role_only = [i for i in old if i not in changed and old[i]["role"] != new[i]["role"]]
    by_split: dict[str, list[str]] = {}
    for i in changed:
        by_split.setdefault(old[i]["split"], []).append(i)
    print(f"{len(old)} questions; route, scope or date changed for {len(changed)}")
    for split, ids in sorted(by_split.items()):
        if split == "holdout":
            print(f"  holdout: {len(ids)} (ids withheld)")
            continue
        print(f"  {split}: {len(ids)}")
        for i in ids:
            diff = ", ".join(
                f"{k} {old[i][k] or '-'} -> {new[i][k] or '-'}"
                for k in DOWNSTREAM
                if old[i][k] != new[i][k]
            )
            print(f"    {i}: {diff}")
    eval_roles = [i for i in role_only if old[i]["split"] != "abstain"]
    print(f"role changed only (no downstream effect): {len(role_only)} ({len(eval_roles)} eval)")
    for i in role_only:
        if old[i]["split"] == "abstain":
            print(f"    {i}: {old[i]['role'] or '-'} -> {new[i]['role'] or '-'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    args = ap.parse_args()
    if args.compare:
        compare(*args.compare)
    elif args.tag:
        run(args.tag)
    else:
        ap.error("give --tag or --compare")


if __name__ == "__main__":
    main()
