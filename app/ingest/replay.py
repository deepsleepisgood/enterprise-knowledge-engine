"""Replay: rebuild the knowledge base from empty, one file at a time, in the plug-ins' order.

The replay tenant gets the main tenant's frozen schema and plug-in bindings (vocabulary and
configuration, never facts). Each file then goes through the real intake, parsing, extraction
and resolution path, and the next file is sent only once every job for the previous one has
finished, so each step's transaction time is clean and "what did the engine know after step N"
has an exact answer. The run happens on one background thread of the API process: a single
worker job would outlive the queue's stale-job timeout on a long corpus.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import worker
from app.core.config import get_settings
from app.core.db import session_scope
from app.ingest.connectors import from_paths
from app.ingest.intake import submit
from app.plugins.registry import plugins
from app.store import episodes as estore
from app.store import history, kb
from app.store.base import use_tenant

log = logging.getLogger("replay")

KINDS = ["parse_episode", "plugin_hooks", "extract_episode", "reresolve_source", "index_embeddings"]
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"running": False}


def planned_files() -> list[Path]:
    """Files to replay, in order: each enabled plug-in's `replay` list (paths are relative to the
    folder that holds the plug-ins folder; a folder means its files in name order)."""
    out: list[Path] = []
    for p in plugins():
        root = p.path.parent.parent
        for rel in p.manifest.get("replay") or []:
            path = (root / rel).resolve()
            if path.is_dir():
                out += sorted(x for x in path.iterdir() if x.is_file())
            elif path.is_file():
                out.append(path)
    return out


def state() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def copy_config(target: str, source: str, mode: str | None = None) -> int:
    """Empty `target`, then give it `source`'s frozen schema and plug-in bindings.
    Returns the copied schema version."""
    mode = mode or get_settings().schema_mode
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
    return version


def _settle(target: str, poll_s: float = 2.0) -> None:
    """Run the target tenant's jobs here, then wait for any that another worker picked up."""
    while True:
        worker.drain(kinds=KINDS, tenant_id=target)
        with use_tenant(target), session_scope() as s:
            if history.busy(s) == 0:
                return
        time.sleep(poll_s)


def run(target: str, source: str, files: list[Path], by: str) -> None:
    """The whole replay (blocking). Progress is in `state()`; results are in the target tenant."""
    try:
        copy_config(target, source)
        for i, path in enumerate(files):
            with _LOCK:
                _STATE.update(step=i + 1, file=path.name)
            with use_tenant(target), session_scope() as s:
                # As the files arrive on their own: an email keeps its own sender and date.
                for ep in from_paths([path]):
                    submit(s, ep)
            _settle(target)
        with _LOCK:
            _STATE.update(running=False, finished_at=datetime.now(UTC), error=None, file=None)
        log.info("replay into %s finished: %d files", target, len(files))
    except Exception as exc:  # reported on the page; the tenant keeps what was done
        log.exception("replay into %s failed", target)
        with _LOCK:
            _STATE.update(running=False, finished_at=datetime.now(UTC), error=str(exc))


def start(by: str) -> dict[str, Any]:
    """Start a replay on a background thread. Raises LookupError when there is nothing to replay
    and RuntimeError when a replay is already running."""
    cfg = get_settings()
    files = planned_files()
    if not files:
        raise LookupError("no plug-in lists files to replay")
    with _LOCK:
        if _STATE.get("running"):
            raise RuntimeError("a replay is already running")
        _STATE.clear()
        _STATE.update(
            running=True,
            started_at=datetime.now(UTC),
            started_by=by,
            step=0,
            total=len(files),
            file=None,
            error=None,
        )
    worker.load_handlers()
    threading.Thread(
        target=run, args=(cfg.replay_tenant, cfg.tenant_id, files, by), daemon=True
    ).start()
    return state()
