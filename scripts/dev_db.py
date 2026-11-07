"""Embedded Postgres 16 + pgvector for machines without Docker.

    python scripts/dev_db.py start   # starts it, writes .pgdata/database_url.txt
    python scripts/dev_db.py url     # prints the URL
    python scripts/dev_db.py stop    # stops it and frees the port

Docker users should use `docker compose up -d db` and DATABASE_URL instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import DEV_DB_URL_FILE  # noqa: E402

DATA_DIR = ROOT / ".pgdata"


def start() -> str:
    import pgserver
    import psycopg

    server = pgserver.get_server(DATA_DIR, cleanup_mode=None)
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    url = uri.replace("postgresql://", "postgresql+psycopg://", 1)
    DEV_DB_URL_FILE.write_text(url, encoding="utf-8")
    return url


def stop() -> None:
    import pgserver

    server = pgserver.get_server(DATA_DIR, cleanup_mode="stop")
    server.cleanup()
    DEV_DB_URL_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        print(start())
    elif cmd == "url":
        print(DEV_DB_URL_FILE.read_text(encoding="utf-8").strip())
    elif cmd == "stop":
        stop()
        print("stopped")
    else:
        raise SystemExit(f"unknown command {cmd!r}")
