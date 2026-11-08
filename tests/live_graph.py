"""Build the real graph for a tenant (live LLM; cached on disk after the first run).

Shared by the live acceptance suites. Each schema mode is its own tenant in the test database.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_built: set[str] = set()


def build_tenant(mode: str) -> None:
    """Ingest data/raw into tenant `mode`, freeze its schema, extract, publish and bind."""
    if mode in _built:
        return
    from app import worker
    from app.core.config import get_settings
    from app.core.db import session_scope
    from app.core.llm import structured
    from app.graph import pipeline as gp
    from app.ingest.connectors import from_paths
    from app.ingest.intake import submit
    from app.plugins import registry
    from app.plugins.bindings import bind
    from app.store import episodes as estore
    from app.store import jobs
    from app.store.base import use_tenant

    settings = get_settings()
    old = settings.schema_mode
    settings.schema_mode = mode
    try:
        with use_tenant(mode), session_scope() as s:
            for ep in from_paths([ROOT / "data" / "raw"]):
                submit(s, ep)
        worker.drain(kinds=["parse_episode", "reresolve_source"], threads=2)
        with use_tenant(mode):
            gp.ensure_schema(auto_freeze=True, mode=mode)
            with session_scope() as s:
                for eid in estore.parsed_episode_ids(s):
                    jobs.enqueue(s, "extract_episode", {"episode_id": eid})
        worker.drain(kinds=["extract_episode", "reresolve_source"], threads=2)
        if mode == "induced":  # same as scripts/build_graph.py: place unplaced facts
            with use_tenant(mode), session_scope() as s:
                from sqlalchemy import text

                s.execute(text("DELETE FROM jobs WHERE kind = 'evolve_schema'"))
            with use_tenant(mode):
                gp.evolve_schema(auto_freeze=True, mode=mode)
        with use_tenant(mode), session_scope() as s:
            bind(s, registry.get("ap"), gp.active_ontology(s, mode), structured_fn=structured)
        from app.answer.index import index_all

        with use_tenant(mode):
            index_all()
    finally:
        settings.schema_mode = old
    _built.add(mode)
