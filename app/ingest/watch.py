"""Watched folder (SCOPE 4.1): a local or mounted directory polled every `watch_interval_s`.

New or changed files become episodes through the normal intake (hash dedupe, parsing, version
matching, extraction and governance), so "keep dumping files here" behaves like uploading them.
A file is read again only when its size or modification time changes; identical content that
reappears is counted as a confirmation by intake, never as a second copy.

    python -m app.ingest.watch                 # scan once (WATCH_DIR or data/inbox)
    python -m app.ingest.watch path/to/folder --loop
The worker runs the same scan in the background (app/worker.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.db import session_scope
from app.ingest.connectors import _skip, from_upload
from app.ingest.intake import submit
from app.store.base import tenant

log = logging.getLogger("watch")
SENDER = "watched folder"


def folder() -> Path:
    s = get_settings()
    return Path(s.watch_dir) if s.watch_dir else s.data_dir / "inbox"


def state_path() -> Path:
    return get_settings().data_dir / "watch" / f"{tenant()}.json"


def status() -> dict[str, Any]:
    """What the Sources page shows: the folder, whether it is on, and the last scan."""
    st = _load(state_path())
    return {
        "path": str(folder()),
        "enabled": get_settings().watch_enabled,
        "interval_s": get_settings().watch_interval_s,
        "last_scan_at": st.get("last_scan_at"),
        "files_seen": len(st.get("files", {})),
        "last_added": st.get("last_added", []),
    }


def _load(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(p)


def scan(root: Path | None = None) -> list[str]:
    """Submit new or changed files under `root`. Returns the new episode ids."""
    root = root or folder()
    root.mkdir(parents=True, exist_ok=True)
    sp = state_path()
    st = _load(sp)
    seen: dict[str, list[int]] = st.get("files", {})
    added: list[str] = []
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = f.relative_to(root).as_posix()
        if _skip(rel) or any(part.startswith(".") for part in f.relative_to(root).parts):
            continue
        info = f.stat()
        sig = [info.st_size, info.st_mtime_ns]
        if seen.get(rel) == sig:
            continue
        try:
            data = f.read_bytes()
        except OSError:  # still being written: next scan
            continue
        with session_scope() as s:
            for ep in from_upload(rel, data, sender=SENDER):
                ep.channel = "watched_folder"
                ep.meta = {**ep.meta, "path": rel}
                eid, created = submit(s, ep)
                if created:
                    added.append(eid)
        seen[rel] = sig
    st.update(
        files=seen,
        last_scan_at=datetime.now(UTC).isoformat(timespec="seconds"),
        last_added=added or st.get("last_added", []),
    )
    _save(sp, st)
    if added:
        log.info("watched folder %s: %d new episodes", root, len(added))
    return added


def loop(root: Path | None = None) -> None:  # pragma: no cover - long-running
    every = get_settings().watch_interval_s
    while True:
        try:
            scan(root)
        except Exception:  # a bad file or a database hiccup must not stop the watcher
            log.exception("watched folder scan failed")
        time.sleep(every)


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="Scan the watched folder")
    ap.add_argument("folder", nargs="?", type=Path)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    if args.loop:
        loop(args.folder)
    else:
        print(scan(args.folder))


if __name__ == "__main__":  # pragma: no cover
    main()
