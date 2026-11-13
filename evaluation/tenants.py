"""Fresh evaluation tenants that share a source tenant's vocabulary and configuration."""

from __future__ import annotations

from pathlib import Path

from app import worker
from app.core.db import session_scope
from app.graph.ontology import Ontology
from app.ingest.connectors import from_paths
from app.ingest.intake import submit
from app.ingest.replay import copy_config
from app.store import kb
from app.store.base import use_tenant

KINDS = ["parse_episode", "plugin_hooks", "extract_episode", "reresolve_source"]


def clone_config(target: str, source: str = "default", mode: str = "induced") -> Ontology:
    """Empty `target`, then give it `source`'s frozen schema and plug-in bindings (vocabulary and
    configuration only, never facts)."""
    copy_config(target, source, mode)
    with use_tenant(target), session_scope() as s:
        row = kb.active_schema(s, mode=mode)
        assert row is not None
        return Ontology.model_validate(dict(row.ontology))


def ingest(target: str, paths: list[Path], threads: int = 1) -> None:
    """Upload files into `target` and run parsing and extraction to completion."""
    with use_tenant(target), session_scope() as s:
        for p in paths:
            for ep in from_paths([p]):
                submit(s, ep)
    worker.drain(kinds=KINDS, threads=threads)
