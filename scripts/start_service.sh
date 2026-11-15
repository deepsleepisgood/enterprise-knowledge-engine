#!/usr/bin/env bash
# Container entry point: bring the database schema up to date, then run the background worker
# and the API side by side. If either stops, stop the container so the host restarts it.
set -euo pipefail

BLOB_DIR="${BLOB_DIR:-/data/blobs}"
mkdir -p "$BLOB_DIR" "${CACHE_DIR:-/data/llm-cache}" "${LOG_DIR:-/data/logs}"

# Originals of documents ingested before this host existed (found by their content-hash name).
if [ -d deploy/seed_blobs ]; then
  cp -rn deploy/seed_blobs/. "$BLOB_DIR"/
fi

echo "[start] migrations"
python -m alembic upgrade head

echo "[start] worker"
python -m app.worker &
WORKER=$!

echo "[start] api on port ${PORT:-8000}"
python -m uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*' &
API=$!

trap 'kill -TERM "$WORKER" "$API" 2>/dev/null || true' TERM INT
wait -n "$WORKER" "$API"
echo "[start] a process stopped; stopping the container so it is restarted"
kill -TERM "$WORKER" "$API" 2>/dev/null || true
exit 1
