"""Induce (or load) the schema, extract facts for every parsed episode, resolve and publish.

    python scripts/build_graph.py --auto-freeze              # induced schema (SCHEMA_MODE)
    SCHEMA_MODE=baseline python scripts/build_graph.py       # the plug-in's hand-written schema
    python scripts/build_graph.py --dry-run                  # count work, no LLM calls

Extraction runs as `extract_episode` jobs through the worker; LLM results are cached on disk,
so a re-run only pays for passages whose text or prompt changed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import worker  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.graph import pipeline as gp  # noqa: E402
from app.graph.induce import coverage  # noqa: E402
from app.graph.ontology import Ontology  # noqa: E402
from app.store import entities, jobs, kb  # noqa: E402
from app.store import episodes as estore  # noqa: E402
from app.store import facts as fstore  # noqa: E402


def llm_usage(since: str) -> dict[str, float]:
    path = get_settings().log_dir / "llm_calls.jsonl"
    calls = cached = tokens_in = tokens_out = 0
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("at", "") < since:
                continue
            calls += 1
            cached += bool(rec.get("cached"))
            tokens_in += rec.get("input_tokens") or 0
            tokens_out += rec.get("output_tokens") or 0
    return {
        "calls": calls,
        "cache_hits": cached,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-freeze", action="store_true", help="freeze an induced schema at once")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--reset-graph",
        action="store_true",
        help="drop schema, entities and facts first (keeps passages; dev only)",
    )
    ap.add_argument("--threads", type=int, default=2, help="episodes extracted in parallel")
    ap.add_argument(
        "--no-evolve", action="store_true", help="skip schema evolution (placing other:* facts)"
    )
    args = ap.parse_args()
    settings = get_settings()
    started, since = time.perf_counter(), datetime.now(UTC).isoformat()

    with session_scope() as s:
        passages = estore.extractable_passages(s)
        eps = estore.parsed_episode_ids(s)
    print(
        f"{len(eps)} episodes, {len(passages)} passages to extract "
        f"(records and parent passages are not sent to the LLM)"
    )
    if args.dry_run:
        return
    if not settings.llm_configured:
        sys.exit("No LLM key configured (LLM_PROVIDER / NVIDIA_API_KEY / ANTHROPIC_API_KEY).")

    if args.reset_graph:
        with session_scope() as s:
            estore.delete_graph(s)
            s.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM jobs WHERE kind IN ('extract_episode', 'reresolve_source')"
                )
            )
        print("graph reset")
    version, status = gp.ensure_schema(auto_freeze=args.auto_freeze)
    print(
        f"schema v{version} ({settings.schema_mode}, {status}) "
        f"in {time.perf_counter() - started:.0f}s"
    )
    with session_scope() as s:
        onto = gp.active_ontology(s)
    if onto is None:
        sys.exit("Schema is a draft: review and freeze it (or pass --auto-freeze).")
    print(
        f"  {len(onto.topics)} topics, {len(onto.attributes)} attributes, "
        f"{len(onto.entity_types)} entity types, units {onto.units}"
    )
    print("  ranking:", [(r.doc_type, r.rank) for r in onto.source_ranking])
    if settings.schema_mode != "baseline":
        from app.plugins import registry

        base = registry.baseline_schema()
        if base:
            cov = coverage(onto, Ontology.model_validate(base))
            cov.pop("_names", None)
            print("  coverage of the baseline schema:", cov)

    with session_scope() as s:
        queued = {
            j
            for j in s.execute(
                __import__("sqlalchemy").text(
                    "SELECT payload->>'episode_id' FROM jobs WHERE kind='extract_episode' "
                    "AND status IN ('queued','running')"
                )
            ).scalars()
        }
        for eid in eps:
            if eid not in queued:
                jobs.enqueue(s, "extract_episode", {"episode_id": eid})
    ran = worker.drain(kinds=["extract_episode", "reresolve_source"], threads=args.threads)
    print(f"ran {ran} jobs in {time.perf_counter() - started:.0f}s")
    with session_scope() as s:
        s.execute(
            __import__("sqlalchemy").text(
                "DELETE FROM jobs WHERE kind = 'evolve_schema' AND status = 'queued'"
            )
        )
    if not args.no_evolve and settings.schema_mode == "induced":
        ev = gp.evolve_schema(auto_freeze=args.auto_freeze)
        if isinstance(ev.get("skipped"), str):
            print("schema evolution:", ev["skipped"])
        else:
            if ev["to_version"] is None:
                outcome = "schema unchanged"
            elif ev["frozen"]:
                outcome = f"schema v{ev['to_version']} frozen, {ev['rekeyed']} facts re-keyed"
            else:
                outcome = f"schema v{ev['to_version']} drafted (review on Setup)"
            print(
                f"schema evolution: {ev['groups']} groups of unplaced facts -> "
                f"{ev['mapped']} mapped, {ev['proposed']} new attributes, "
                f"{ev['skipped']} skipped; {outcome}"
            )
            for d in ev["decisions"]:
                if d["action"] != "skip":
                    print(
                        f"  {d['action']:<4} {', '.join(d['keys'])[:70]} -> {d['attribute']} "
                        f"({d['method']})"
                    )
        with session_scope() as s:
            onto = gp.active_ontology(s)

    with session_scope() as s:
        for j in jobs.failed_jobs(s):
            print(f"  FAILED job {j.id} {j.kind}: {(j.error or '')[:300]}")
        rows = (
            s.execute(
                __import__("sqlalchemy").text(
                    "SELECT result FROM jobs WHERE kind='extract_episode' AND status='done' "
                    "AND finished_at > :since"
                ),
                {"since": since},
            )
            .scalars()
            .all()
        )
        fails = [f for r in rows for f in (r or {}).get("failures", [])]
        for f in fails:
            print("  passage failed:", f)
        summ = fstore.summary(s)
        print("facts (live):", summ["by_status"], "| rows total", summ["rows_total"])
        attrs = Counter(summ["by_attribute"])
        print(
            f"  {len(attrs)} attributes used; other:* "
            f"{sum(n for a, n in attrs.items() if a.startswith('other:'))}"
        )
        for a, n in attrs.most_common(25):
            print(f"    {n:>3} {a}")
        print("entities:", entities.count(s))
        print("conflicts:", Counter(c.kind for c in kb.list_conflicts(s)))
        print("kb version:", kb.current_kb_version(s))
    from app.core.llm import structured
    from app.plugins import registry
    from app.plugins.bindings import bind

    with session_scope() as s:
        for plugin in registry.plugins():
            results = bind(s, plugin, onto, structured_fn=structured)
            bound = [r for r in results if r.attribute]
            print(f"plug-in {plugin.name}: {len(bound)}/{len(results)} parameters bound")
            for r in results:
                if r.attribute is None:
                    print(f"  UNBOUND {r.param}")
                elif r.method != "exact key":
                    print(f"  {r.param} -> {r.attribute} ({r.method})")
    print("LLM:", llm_usage(since))


if __name__ == "__main__":
    main()
