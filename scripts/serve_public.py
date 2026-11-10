"""Serve the deployed demo from this machine: API and worker on the Neon database, a Cloudflare
quick tunnel giving the API a public HTTPS address, and the Vercel web app pointed at it.

    python scripts/serve_public.py                # .\\run_public.ps1 does the same
    python scripts/serve_public.py --no-redeploy  # keep the Vercel build as it is

Reads NEON_DATABASE_URL and VERCEL_TOKEN from .env (never printed). A quick tunnel's address
changes every time it starts, so when it differs from the last one (logs/tunnel_url.txt) the web
app is rebuilt on Vercel with the new address (about a minute). Ctrl+C stops the API, the
worker and the tunnel. Needs tools/cloudflared.exe and, for the redeploy, npx (Node).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_app import API_PORT, LOGS, ROOT, WEB, WINDOWS, Proc, answers, port_busy, say  # noqa: E402

CLOUDFLARED = ROOT / "tools" / ("cloudflared.exe" if WINDOWS else "cloudflared")
URL_FILE = LOGS / "tunnel_url.txt"
SITE = "https://ps07-knowledge-engine.vercel.app"


def env_value(name: str) -> str | None:
    text = (ROOT / ".env").read_text(encoding="utf-8")
    m = re.search(rf"^{name}=(.*)$", text, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def tunnel_url(timeout: float = 90) -> str | None:
    log = LOGS / "tunnel.log"
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if log.exists():
            m = re.search(
                r"https://[a-z0-9-]+\.trycloudflare\.com", log.read_text("utf-8", "replace")
            )
            if m:
                return m.group(0)
        time.sleep(1)
    return None


def redeploy(url: str, token: str) -> bool:
    """Point the Vercel production build at `url` and rebuild it."""
    npx = shutil.which("npx")
    if not npx:
        say("run", "npx not found: set NEXT_PUBLIC_API_BASE_URL on Vercel by hand")
        return False
    env = {**os.environ, "VERCEL_TOKEN": token}
    base = [npx, "--yes", "vercel@latest"]
    var = "NEXT_PUBLIC_API_BASE_URL"
    subprocess.run(
        [*base, "env", "rm", var, "production", "--yes", "--token", token],
        cwd=WEB,
        env=env,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [*base, "env", "add", var, "production", "--token", token],
        cwd=WEB,
        env=env,
        input=url,
        capture_output=True,
        text=True,
    )
    say("run", "rebuilding the web app on Vercel with the new API address...")
    done = subprocess.run(
        [*base, "deploy", "--prod", "--yes", "--token", token, "--build-env", f"{var}={url}"],
        cwd=WEB,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode != 0:
        say("run", "Vercel deploy failed: " + done.stderr.replace(token, "<token>")[-400:])
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the demo publicly from this machine.")
    ap.add_argument("--no-redeploy", action="store_true", help="do not rebuild the web app")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    neon, token = env_value("NEON_DATABASE_URL"), env_value("VERCEL_TOKEN")
    if not neon:
        say("run", "NEON_DATABASE_URL is missing from .env")
        return 1
    if not CLOUDFLARED.exists():
        say("run", f"{CLOUDFLARED} is missing (download cloudflared into tools/)")
        return 1
    if port_busy(API_PORT):
        say("run", f"port {API_PORT} is in use; stop the local app first")
        return 1
    LOGS.mkdir(exist_ok=True)
    (LOGS / "tunnel.log").unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = neon  # children only; .env keeps the local database

    py = sys.executable
    procs = [
        Proc("api", [py, "-m", "uvicorn", "app.api.main:app", "--port", str(API_PORT)], ROOT),
        Proc("worker", [py, "-m", "app.worker"], ROOT),
        Proc(
            "tunnel",
            [
                str(CLOUDFLARED),
                "tunnel",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{API_PORT}",
            ],
            ROOT,
        ),
    ]

    def shutdown() -> None:
        say("run", "stopping...")
        for p in reversed(procs):
            p.stop()
        say(
            "run",
            "stopped: API, worker and tunnel are down; the site cannot answer until restarted",
        )

    def interrupt(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGBREAK if WINDOWS else signal.SIGTERM, interrupt)
    try:
        url = tunnel_url()
        if not url:
            say("run", "the tunnel gave no address; see logs/tunnel.log")
            shutdown()
            return 1
        for _ in range(60):
            if answers(f"{url}/health"):
                break
            time.sleep(2)
        else:
            say("run", f"{url}/health does not answer; see logs/api.log and logs/tunnel.log")
        last = URL_FILE.read_text().strip() if URL_FILE.exists() else ""
        if url != last and not args.no_redeploy:
            if token and redeploy(url, token):
                URL_FILE.write_text(url)
            elif not token:
                say("run", "VERCEL_TOKEN missing: set NEXT_PUBLIC_API_BASE_URL on Vercel by hand")
        elif url == last:
            URL_FILE.write_text(url)
        say("run", f"API (public): {url}")
        say("run", f"open {SITE}   (Ctrl+C to stop)")
        while True:
            dead = [p for p in procs if not p.alive()]
            if dead:
                say("run", f"{dead[0].name} exited ({dead[0].p.returncode}), see logs/")
                shutdown()
                return 1
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
