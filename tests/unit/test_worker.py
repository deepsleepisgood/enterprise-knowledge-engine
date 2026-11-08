"""The worker's handler table: every job kind the app queues has a handler."""

from __future__ import annotations


def test_load_handlers_registers_every_job_kind() -> None:
    from app import worker

    worker.load_handlers()
    kinds = {
        "parse_episode",
        "extract_episode",
        "index_embeddings",
        "conflict_scan",
        "reresolve_source",
    }
    assert kinds <= set(worker.HANDLERS)
