"""Point the Vercel web app at an API address and rebuild it (about a minute).

Uses VERCEL_TOKEN from .env (never printed) and the web/ folder's link to the Vercel project
(web/.vercel, made once with `vercel link`). Run it once after the Railway service has its
address; run it again to switch to another host (e.g. the laptop tunnel as a backup).

    python scripts/point_vercel.py https://<service>.up.railway.app
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serve_public import SITE, env_value, redeploy  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        print(__doc__)
        return 2
    url = sys.argv[1].rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=30) as r:
            print("API health:", r.read().decode()[:200])
    except OSError as exc:
        print(f"The API at {url} does not answer /health ({exc}); fix that first.")
        return 1
    token = env_value("VERCEL_TOKEN")
    if not token:
        print("VERCEL_TOKEN is not in .env: set NEXT_PUBLIC_API_BASE_URL on Vercel by hand.")
        return 1
    if not redeploy(url, token):
        return 1
    print(f"{SITE} now uses {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
