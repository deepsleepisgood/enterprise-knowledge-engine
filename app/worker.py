"""Background job runner.

Handlers register with `@handler("kind")`. Each job runs in its own transaction under the job's
tenant; a handler that raises is retried with backoff (see `app/store/jobs.py`), and the job is
marked failed after its last attempt so it surfaces on the Sources page.

    python -m app.worker            # run forever with WORKER_THREADS threads
    python -m app.worker --drain    # process until the queue is empty, then exit
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from app.core.db import session_scope
from app.store import jobs
from app.store.base import use_tenant

log = logging.getLogger("worker")

Handler = Callable[[dict[str, Any]], dict[str, Any] | None]
HANDLERS: dict[str, Handler] = {}

# Modules whose import registers handlers. Plain module names, no plug-in imports.
HANDLER_MODULES = ("app.ingest.pipeline", "app.graph.pipeline")


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def load_handlers() -> None:
    import importlib

    for name in HANDLER_MODULES:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise


def run_one(worker_id: str, kinds: list[str] | None = None) -> bool:
    """Claim and run one job. Returns False when nothing was claimable."""
    with session_scope() as s:
        job = jobs.claim(s, worker_id, kinds)
    if job is None:
        return False
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise LookupError(f"no handler for job kind {job.kind!r}")
        with use_tenant(job.tenant_id):
            result = fn(job.payload)
        with session_scope() as s:
            jobs.complete(s, job.id, result)
    except Exception as exc:  # recorded on the job row; the worker keeps going
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
        with session_scope() as s:
            status = jobs.fail(s, job, err)
        log.warning("job %s (%s) failed: %s -> %s", job.id, job.kind, exc, status)
    return True


def drain(kinds: list[str] | None = None, threads: int = 1, worker_id: str | None = None) -> int:
    """Run jobs until none are claimable right now. Returns how many ran."""
    load_handlers()
    base = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    count = 0
    lock = threading.Lock()

    def loop(i: int) -> None:
        nonlocal count
        while run_one(f"{base}:{i}", kinds):
            with lock:
                count += 1

    if threads <= 1:
        loop(0)
    else:
        ts = [threading.Thread(target=loop, args=(i,)) for i in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    return count


def serve(threads: int, poll_s: float = 1.0) -> None:  # pragma: no cover - long-running
    load_handlers()
    base = f"{socket.gethostname()}:{os.getpid()}"

    def loop(i: int) -> None:
        while True:
            if not run_one(f"{base}:{i}"):
                time.sleep(poll_s)

    with session_scope() as s:
        jobs.requeue_stale(s)
    for i in range(threads):
        threading.Thread(target=loop, args=(i,), daemon=True).start()
    log.info("worker running with %d threads", threads)
    while True:
        time.sleep(60)
        with session_scope() as s:
            jobs.requeue_stale(s)


def main() -> None:  # pragma: no cover
    from app.core.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--drain", action="store_true")
    ap.add_argument("--threads", type=int, default=get_settings().worker_threads)
    args = ap.parse_args()
    if args.drain:
        print(f"ran {drain(threads=args.threads)} jobs")
    else:
        serve(args.threads)


if __name__ == "__main__":
    main()
