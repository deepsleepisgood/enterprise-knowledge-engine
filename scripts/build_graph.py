"""Extract claims from every leaf passage, resolve authority, and persist the graph.

    python scripts/build_graph.py --dry-run     # list passages and estimate the cost; no LLM calls
    python scripts/build_graph.py               # full build (needs ANTHROPIC_API_KEY)
    python scripts/build_graph.py --limit 5     # first 5 passages only, for a smoke test

Extraction results are cached on disk (.cache/llm), so a re-run costs nothing and gives
the same graph. Prints claims per topic and current/superseded counts.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.pack import get_pack  # noqa: E402
from app.graph.compare import LLMComparator  # noqa: E402
from app.graph.extract import build_prompt, system_prompt  # noqa: E402
from app.graph.resolve import resolve, summarise  # noqa: E402
from app.graph.store import extract_all, load_passages, persist  # noqa: E402

# Rough sizes for the estimate: output tokens per passage and characters per token.
EST_OUTPUT_TOKENS = 600
CHARS_PER_TOKEN = 3.5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4, help="parallel extraction calls")
    args = ap.parse_args()

    pack = get_pack()
    settings = get_settings()
    with session_scope() as s:
        passages = load_passages(s)
    if args.limit:
        passages = passages[: args.limit]

    if args.dry_run:
        from app.core.llm import cost_usd

        system = system_prompt(pack)
        in_tok = sum(len(system) + len(build_prompt(p, pack)) for p in passages) / CHARS_PER_TOKEN
        out_tok = EST_OUTPUT_TOKENS * len(passages)
        est = cost_usd(settings.model_smart, int(in_tok), out_tok)
        print(
            f"{len(passages)} leaf passages; ~{int(in_tok):,} input and ~{out_tok:,} output tokens"
        )
        price = f"${est:.2f}" if est is not None else "unknown (no price table for this model)"
        print(f"estimated cost on {settings.model_smart}: {price} (cached re-runs: $0)")
        return

    if not settings.llm_configured:
        key = "NVIDIA_API_KEY" if settings.llm_provider == "nim" else "ANTHROPIC_API_KEY"
        raise SystemExit(f"{key} is not set (put it in .env). Use --dry-run to estimate.")

    def progress(i: int, n: int, p) -> None:
        print(f"  [{i:3d}/{n}] {p.source_id:12s} {p.locator}", flush=True)

    claims = extract_all(passages, pack, on_progress=progress, workers=args.workers)
    result = resolve(claims, compare=LLMComparator())
    with session_scope() as s:
        report = persist(s, result)

    by_topic = Counter(c.topic for c in result.claims)
    print("\nclaims per topic:")
    for topic, n in by_topic.most_common():
        cur = sum(1 for c in result.claims if c.topic == topic and c.status == "current")
        sup = sum(1 for c in result.claims if c.topic == topic and c.status == "superseded")
        print(f"  {topic:22s} {n:3d}  current={cur:<3d} superseded={sup}")
    print("\nstatus:", summarise(result))
    unverified = sum(1 for c in result.claims if not c.meta.get("quote_verified"))
    print(f"quotes not found verbatim in their passage: {unverified}")
    print(
        f"persisted: inserted={report.inserted} updated={report.updated} "
        f"unchanged={report.unchanged} "
        f"retired={report.retired} new_conflicts={report.conflicts} kb_version={report.kb_version}"
    )


if __name__ == "__main__":
    main()
