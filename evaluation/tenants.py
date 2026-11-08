"""Fresh evaluation tenants that share a source tenant's vocabulary and configuration."""

from __future__ import annotations

from pathlib import Path

from app import worker
from app.core.db import session_scope
from app.graph.ontology import Ontology
from app.ingest.connectors import from_paths
from app.ingest.intake import submit
from app.store import episodes as estore
from app.store import kb
from app.store.base import use_tenant

KINDS = ["parse_episode", "plugin_hooks", "extract_episode", "reresolve_source"]


def clone_config(target: str, source: str = "default", mode: str = "induced") -> Ontology:
    """Empty `target`, then give it `source`'s frozen schema and plug-in bindings (vocabulary and
    configuration only, never facts)."""
    with use_tenant(source), session_scope() as s:
        row = kb.active_schema(s, mode=mode)
        if row is None or row.status != "frozen":
            raise LookupError(f"tenant {source!r} has no frozen {mode} schema")
        ontology, version = dict(row.ontology), row.version
        binds = [
            (b.plugin, b.param, b.attribute_key, b.confidence, dict(b.meta or {}))
            for b in kb.get_bindings(s)
        ]
    with use_tenant(target), session_scope() as s:
        estore.delete_tenant_content(s)
        kb.save_schema(s, ontology, mode, frozen_by=f"copy of {source} v{version}")
        for plugin, param, attr, conf, meta in binds:
            kb.put_binding(
                s,
                plugin,
                param,
                attribute_key=attr,
                confidence=conf,
                confirmed_by="copy",
                meta=meta,
            )
    return Ontology.model_validate(ontology)


def ingest(target: str, paths: list[Path], threads: int = 1) -> None:
    """Upload files into `target` and run parsing and extraction to completion."""
    with use_tenant(target), session_scope() as s:
        for p in paths:
            for ep in from_paths([p]):
                submit(s, ep)
    worker.drain(kinds=KINDS, threads=threads)
