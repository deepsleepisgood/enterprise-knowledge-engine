"""Run the whole app from one terminal: database, API, worker and web app.

    run                          # from the project root (run.cmd on Windows)
    python scripts/run_app.py    # same thing
    python scripts/run_app.py --no-browser --no-worker

Starts the embedded Postgres (unless DATABASE_URL is set), the API on :8000, the job worker
and the Next.js dev server on :3000, prints every line with a [api]/[worker]/[web] prefix
(also written to logs/<name>.log), waits until both servers answer, then opens the browser.
Ctrl+C stops all three and frees the ports. If any one of them dies, the rest are stopped too.
The embedded database is left running (it holds no port the app needs freed and is reused next
time); `python scripts/dev_db.py stop` stops it.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LOGS = ROOT / "logs"
WINDOWS = os.name == "nt"
API_PORT, WEB_PORT = 8000, 3000
COLORS = {"api": "36", "worker": "35", "web": "32", "run": "33"}


def say(name: str, line: str) -> None:
    tag = f"[{name}]".ljust(9)
    if sys.stdout.isatty():
        tag = f"\x1b[{COLORS.get(name, '0')}m{tag}\x1b[0m"
    print(f"{tag}{line}", flush=True)


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 (localhost only)
            return r.status < 500
    except Exception:
        return False


def ensure_database() -> None:
    sys.path.insert(0, str(ROOT))
    from app.core.config import get_settings

    if get_settings().database_url:
        say("run", "using DATABASE_URL from the environment")
        return
    sys.path.insert(0, str(ROOT / "scripts"))
    dev_db = importlib.import_module("dev_db")

    say("run", "starting the embedded database...")
    dev_db.start()
    say("run", "database ready")


class Proc:
    def __init__(self, name: str, cmd: list[str], cwd: Path) -> None:
        self.name = name
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0"}
        # Own process group, so Ctrl+C reaches only this launcher and it stops each child cleanly.
        extra: dict = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if WINDOWS
            else {"start_new_session": True}
        )
        self.p = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **extra,
        )
        self.log = (LOGS / f"{name}.log").open("w", encoding="utf-8")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            line = line.rstrip()
            self.log.write(line + "\n")
            self.log.flush()
            if line:
                say(self.name, line)

    def alive(self) -> bool:
        return self.p.poll() is None

    def stop(self) -> None:
        if not self.alive():
            return
        try:
            if WINDOWS:
                self.p.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(self.p.pid, signal.SIGINT)
            self.p.wait(timeout=6)
        except Exception:
            pass
        if self.alive() or WINDOWS:
            # Kill the whole tree: `next dev` leaves a child server holding the port otherwise.
            if WINDOWS:
                subprocess.run(
                    ["taskkill", "/PID", str(self.p.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.p.pid, signal.SIGKILL)
        self.log.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run database, API, worker and web app together.")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument(
        "--no-worker", action="store_true", help="skip the job worker (uploads stay queued)"
    )
    args = ap.parse_args()
    # Child output (Next.js prints check marks) must never crash the launcher on a cp1252 console.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    busy = [p for p in (API_PORT, WEB_PORT) if port_busy(p)]
    if busy:
        say(
            "run",
            f"port {', '.join(map(str, busy))} already in use; stop the running copy first.",
        )
        return 1
    node = shutil.which("node")
    next_bin = WEB / "node_modules" / "next" / "dist" / "bin" / "next"
    if not node or not next_bin.exists():
        say("run", "web dependencies missing: run `npm install` in web/ first.")
        return 1
    if not (WEB / ".env.local").exists():
        say(
            "run",
            "note: web/.env.local is missing, so the web app runs on sample data, not the API.",
        )

    LOGS.mkdir(exist_ok=True)
    ensure_database()

    py = sys.executable
    procs = [Proc("api", [py, "-m", "uvicorn", "app.api.main:app", "--port", str(API_PORT)], ROOT)]
    if not args.no_worker:
        procs.append(Proc("worker", [py, "-m", "app.worker"], ROOT))
    # node directly, not npm: npm.cmd asks "Terminate batch job (Y/N)?" on Ctrl+C.
    procs.append(Proc("web", [node, str(next_bin), "dev", "-p", str(WEB_PORT)], WEB))

    def shutdown() -> None:
        say("run", "stopping...")
        for p in reversed(procs):
            p.stop()
        say("run", "stopped; ports 8000 and 3000 are free")

    def interrupt(*_: object) -> None:
        raise KeyboardInterrupt

    # Ctrl+Break (Windows) and SIGTERM stop everything the same way Ctrl+C does.
    signal.signal(signal.SIGBREAK if WINDOWS else signal.SIGTERM, interrupt)

    url = f"http://localhost:{WEB_PORT}"
    ready = False
    try:
        start = time.monotonic()
        while True:
            dead = [p for p in procs if not p.alive()]
            if dead:
                say(
                    "run",
                    f"{dead[0].name} exited ({dead[0].p.returncode}), see logs/{dead[0].name}.log",
                )
                shutdown()
                return 1
            if not ready and answers(f"http://localhost:{API_PORT}/health") and answers(url):
                ready = True
                say(
                    "run",
                    f"ready in {time.monotonic() - start:.0f}s: open {url}   (Ctrl+C to stop)",
                )
                if not args.no_browser:
                    webbrowser.open(url)
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
