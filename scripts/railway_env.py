"""Write the Railway service's variables to deploy/railway.env (git-ignored), from .env.

Paste the file's contents into Railway: the service -> Variables -> Raw Editor -> Update
Variables. Values are never printed; only the names are listed. Delete the file afterwards.

    python scripts/railway_env.py

What goes in: the database (Neon's pooled URL as DATABASE_URL), the model provider and models
as configured locally, and fixed settings for the container (files on the Railway volume at
/data, folder watching off, owner approval on). Keys only a laptop needs (the Vercel token, the
evaluation judge's Anthropic key, the unused NVIDIA key) stay out.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy" / "railway.env"

FROM_ENV = [
    "LLM_PROVIDER",
    "NIM_BASE_URL",
    "ISOQUANT_API_KEY",
    "OPENAI_API_KEY",
    "MODEL_FAST",
    "MODEL_SMART",
    "MODEL_VISION",
    "ROUTER_MODEL",
    "NIM_MAX_RPM",
    "NIM_MAX_CONCURRENT",
    "NIM_TIMEOUT_S",
    "MODEL_PRICES",
    "PLUGINS",
    "SCHEMA_MODE",
    "TENANT_ID",
]
FIXED = {
    "BLOB_DIR": "/data/blobs",
    "CACHE_DIR": "/data/llm-cache",
    "LOG_DIR": "/data/logs",
    "WATCH_ENABLED": "false",
    "GOVERNANCE": "true",
    "WORKER_THREADS": "2",
}


def clean(v: str | None) -> str:
    return (v or "").strip().strip('"').strip("'")


def main() -> int:
    env = dotenv_values(ROOT / ".env")
    db = clean(env.get("NEON_DATABASE_URL")) or clean(env.get("DATABASE_URL"))
    if not db or "localhost" in db or "127.0.0.1" in db:
        print("No deployed database URL in .env (NEON_DATABASE_URL).", file=sys.stderr)
        return 1
    rows = {"DATABASE_URL": db}
    rows.update({k: clean(env.get(k)) for k in FROM_ENV if clean(env.get(k))})
    rows.update(FIXED)
    if not (rows.get("ISOQUANT_API_KEY") or rows.get("OPENAI_API_KEY")):
        print("No model API key in .env.", file=sys.stderr)
        return 1
    OUT.write_text("".join(f"{k}={v}\n" for k, v in rows.items()), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} with {len(rows)} variables (values not shown):")
    print("  " + ", ".join(rows))
    print("Paste it into Railway (service -> Variables -> Raw Editor), then delete the file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
