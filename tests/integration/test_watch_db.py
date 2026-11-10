"""Watched folder (SCOPE 4.1): new or changed files become episodes, unchanged files do not."""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings
from app.core.db import session_scope
from app.ingest import watch
from app.store import episodes as estore

pytestmark = pytest.mark.db


def test_scan_submits_new_and_changed_files_once(db, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    monkeypatch.setattr(get_settings(), "blob_dir", tmp_path / "blobs")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note.md").write_text("# Parking\n\nVisitors park in bay C.\n", encoding="utf-8")
    (inbox / "~$lock.docx").write_bytes(b"office lock file")
    (inbox / ".hidden").mkdir()
    (inbox / ".hidden" / "x.md").write_text("ignored", encoding="utf-8")

    first = watch.scan(inbox)
    assert len(first) == 1
    assert watch.scan(inbox) == []  # nothing changed

    p = inbox / "note.md"
    p.write_text("# Parking\n\nVisitors park in bay D.\n", encoding="utf-8")
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 10_000_000))
    second = watch.scan(inbox)
    assert len(second) == 1 and second != first

    with session_scope() as s:
        ep = estore.get_episode(s, second[0])
        assert ep.channel == "watched_folder" and ep.sender == watch.SENDER
    st = watch.status()
    assert st["files_seen"] == 1 and st["last_scan_at"]
