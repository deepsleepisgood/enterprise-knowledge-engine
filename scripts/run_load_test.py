"""How the engine holds up with several people asking at once.

Starts N simulated users at the same moment; each asks K questions one after another through the
running API exactly as the web app does (POST /ask/jobs, then poll GET /ask/jobs/{id}). Levels run
one after another (default 5, 10 and 25 users). Questions are real processor messages from the
Teams samples already run today (reports/teams_sample_*.jsonl), so most model calls come from the
disk cache and the run costs close to nothing; the report counts how many did not.

Per level: answers, errors, response time (median, 95th percentile, slowest) as the asker sees it,
how much of that was waiting for a free answer thread, answers per minute, peak database
connections, the API process's peak CPU and memory, and model calls (cached or new, with cost).

Users are `eval-load-*`, so the answers are left out of analytics and answer recall.

    python scripts/run_load_test.py                          # API on http://127.0.0.1:8000
    python scripts/run_load_test.py --levels 5,10 --per-user 2
    python scripts/run_load_test.py --api-pid 1234           # also sample that process's CPU
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCES = ["teams_sample_20261114_final_fresh.jsonl", "teams_sample_20261114_final32.jsonl"]
LLM_LOG = ROOT / "logs" / "llm_calls.jsonl"
POLL_S = 0.5
TIMEOUT_S = 300.0


def questions() -> list[str]:
    seen: dict[str, None] = {}
    for name in SOURCES:
        path = ROOT / "reports" / name
        if path.exists():
            for line in path.open(encoding="utf-8"):
                q = json.loads(line).get("question")
                if q:
                    seen.setdefault(q.strip(), None)
    if not seen:
        raise SystemExit("no questions: run scripts/run_teams_sample.py first")
    return list(seen)


def _http(method: str, url: str, body: dict | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


def ask_once(base: str, question: str, user: str) -> dict[str, Any]:
    """One question as the web app asks it. Wall time is what the asker waits."""
    t0 = time.perf_counter()
    out: dict[str, Any] = {"user": user, "question": question[:80]}
    try:
        job = _http("POST", f"{base}/ask/jobs", {"question": question, "user_id": user})
        while True:
            time.sleep(POLL_S)
            st = _http("GET", f"{base}/ask/jobs/{job['job_id']}")
            if st["status"] != "pending":
                break
            if time.perf_counter() - t0 > TIMEOUT_S:
                st = {"status": "error", "error": f"no card after {TIMEOUT_S:.0f} s"}
                break
        card = st.get("card") or {}
        out.update(
            ok=st["status"] == "done",
            card_status=card.get("status"),
            pipeline_s=(card.get("latency_ms") or 0) / 1000,
            error=st.get("error"),
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        out.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:200])
    out["wall_s"] = time.perf_counter() - t0
    # Answering itself (pipeline time) vs waiting for a free answer thread and polling.
    out["wait_s"] = max(0.0, out["wall_s"] - out.get("pipeline_s", 0.0)) if out.get("ok") else None
    return out


class Sampler(threading.Thread):
    """Every second: database connections for this database, and the API process's CPU/RSS."""

    def __init__(self, db_url: str | None, api_pid: int | None) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.conns: list[int] = []
        self.cpu: list[float] = []
        self.rss_mb: list[float] = []
        self.error: str | None = None
        self.db_url = db_url
        self.proc = None
        if api_pid:
            import psutil

            self.proc = psutil.Process(api_pid)
            self.proc.cpu_percent(None)

    def run(self) -> None:
        conn = None
        if self.db_url:
            try:
                import psycopg

                conn = psycopg.connect(self.db_url, autocommit=True, connect_timeout=10)
            except Exception as exc:  # noqa: BLE001 - reported, the run goes on
                self.error = f"{type(exc).__name__}"
        while not self.stop.is_set():
            if conn is not None:
                try:
                    n = conn.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                    ).fetchone()[0]
                    self.conns.append(int(n))
                except Exception as exc:  # noqa: BLE001
                    self.error = f"{type(exc).__name__}"
            if self.proc is not None:
                try:
                    self.cpu.append(self.proc.cpu_percent(None))
                    self.rss_mb.append(self.proc.memory_info().rss / 2**20)
                except Exception:  # noqa: BLE001 - process gone
                    self.proc = None
            self.stop.wait(1.0)
        if conn is not None:
            conn.close()


def llm_calls_since(offset: int) -> tuple[int, dict[str, Any]]:
    """Model calls logged after byte `offset` of the call log: (new offset, counts)."""
    if not LLM_LOG.exists():
        return offset, {"cached": 0, "new": 0, "errors": 0, "cost_usd": 0.0}
    with LLM_LOG.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    out = {"cached": 0, "new": 0, "errors": 0, "cost_usd": 0.0}
    for line in chunk.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("error"):
            out["errors"] += 1
        elif row.get("cached"):
            out["cached"] += 1
        else:
            out["new"] += 1
            out["cost_usd"] += float(row.get("cost_usd") or 0)
    return offset + len(chunk), out


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, round(p * (len(s) - 1)))]


def run_level(
    base: str, users: int, per_user: int, qs: list[str], start: int, sampler_args: tuple
) -> dict[str, Any]:
    offset = LLM_LOG.stat().st_size if LLM_LOG.exists() else 0
    sampler = Sampler(*sampler_args)
    sampler.start()
    barrier = threading.Barrier(users)
    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    stamp = datetime.now().strftime("%H%M%S")

    def user(i: int) -> None:
        barrier.wait()  # everyone asks at the same moment
        for k in range(per_user):
            q = qs[(start + i * per_user + k) % len(qs)]
            r = ask_once(base, q, f"eval-load-{stamp}-{users}u-{i}")
            with lock:
                results.append(r)

    t0 = time.perf_counter()
    threads = [threading.Thread(target=user, args=(i,)) for i in range(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0
    sampler.stop.set()
    sampler.join()
    _, calls = llm_calls_since(offset)
    ok = [r for r in results if r.get("ok")]
    wall = [r["wall_s"] for r in ok]
    return {
        "users": users,
        "answers": len(results),
        "ok": len(ok),
        "errors": [r.get("error") for r in results if not r.get("ok")],
        "statuses": {
            s: sum(r.get("card_status") == s for r in ok)
            for s in sorted({r.get("card_status") or "" for r in ok})
        },
        "elapsed_s": elapsed,
        "per_min": len(ok) / elapsed * 60 if elapsed else 0.0,
        "wall_p50": statistics.median(wall) if wall else float("nan"),
        "wall_p95": pct(wall, 0.95),
        "wall_max": max(wall) if wall else float("nan"),
        "pipeline_p50": statistics.median([r["pipeline_s"] for r in ok]) if ok else float("nan"),
        "wait_p50": statistics.median([r["wait_s"] for r in ok]) if ok else float("nan"),
        "wait_max": max((r["wait_s"] for r in ok), default=float("nan")),
        "db_conns_peak": max(sampler.conns, default=None),
        "db_conns_start": sampler.conns[0] if sampler.conns else None,
        "db_error": sampler.error,
        "cpu_peak": max(sampler.cpu, default=None),
        "cpu_mean": statistics.mean(sampler.cpu) if sampler.cpu else None,
        "rss_peak_mb": max(sampler.rss_mb, default=None),
        "llm": calls,
        "results": results,
    }


def report(levels: list[dict[str, Any]], base: str, per_user: int, n_q: int) -> str:
    def f(x: Any, fmt: str = ".1f") -> str:
        return "–" if x is None or (isinstance(x, float) and x != x) else format(x, fmt)

    lines = [
        f"# Load test, {date.today():%d %b %Y}",
        "",
        f"API {base}; each simulated user asks {per_user} questions one after another, all users "
        f"starting at the same moment; {n_q} distinct real processor questions (Teams samples). "
        "Times are what the asker waits (submit to card, polling every 0.5 s).",
        "",
        "| Users | Answers ok | Errors | Median s | 95th pct s | Slowest s | Answering median s "
        "| Waiting median s | Waiting max s | Answers/min | DB conns (start → peak) "
        "| API CPU peak % | API RAM peak MB | Model calls cached / new | New cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lv in levels:
        c = lv["llm"]
        lines.append(
            f"| {lv['users']} | {lv['ok']}/{lv['answers']} | {len(lv['errors'])} "
            f"| {f(lv['wall_p50'])} | {f(lv['wall_p95'])} | {f(lv['wall_max'])} "
            f"| {f(lv['pipeline_p50'])} | {f(lv['wait_p50'])} | {f(lv['wait_max'])} "
            f"| {f(lv['per_min'])} "
            f"| {f(lv['db_conns_start'], 'd')} → {f(lv['db_conns_peak'], 'd')} "
            f"| {f(lv['cpu_peak'], '.0f')} | {f(lv['rss_peak_mb'], '.0f')} "
            f"| {c['cached']} / {c['new']} | ${c['cost_usd']:.3f} |"
        )
    lines += ["", "Card statuses per level:", ""]
    for lv in levels:
        lines.append(f"- {lv['users']} users: {lv['statuses']}")
    errs = [(lv["users"], e) for lv in levels for e in lv["errors"]]
    if errs:
        lines += ["", "Errors:", ""] + [f"- {u} users: {e}" for u, e in errs[:20]]
    if any(lv["db_error"] for lv in levels):
        lines += [
            "",
            f"DB sampler error: {next(lv['db_error'] for lv in levels if lv['db_error'])}",
        ]
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--levels", default="5,10,25")
    ap.add_argument("--per-user", type=int, default=2)
    ap.add_argument("--api-pid", type=int, default=None)
    ap.add_argument("--pause", type=float, default=10.0, help="seconds between levels")
    ap.add_argument("--tag", default="")
    ap.add_argument(
        "--start", type=int, default=0, help="first question (skip ones already cached there)"
    )
    args = ap.parse_args()

    qs = questions()
    _http("GET", f"{args.base}/health")  # fail fast when the API is not up
    db_url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    levels = []
    start = args.start
    for i, n in enumerate(int(x) for x in args.levels.split(",")):
        if i:
            time.sleep(args.pause)
        print(f"{n} users x {args.per_user} questions ...", flush=True)
        lv = run_level(args.base, n, args.per_user, qs, start, (db_url or None, args.api_pid))
        start += n * args.per_user
        levels.append(lv)
        print(
            f"  ok {lv['ok']}/{lv['answers']}  median {lv['wall_p50']:.1f}s  "
            f"p95 {lv['wall_p95']:.1f}s  max {lv['wall_max']:.1f}s  "
            f"{lv['per_min']:.1f}/min  db peak {lv['db_conns_peak']}  "
            f"llm new {lv['llm']['new']}",
            flush=True,
        )
    stem = f"load_{date.today():%Y%m%d}{args.tag}"
    out = ROOT / "reports"
    (out / f"{stem}.md").write_text(
        report(levels, args.base, args.per_user, len(qs)), encoding="utf-8"
    )
    with (out / f"{stem}.jsonl").open("w", encoding="utf-8") as fh:
        for lv in levels:
            fh.write(json.dumps(lv, default=str) + "\n")
    print(f"report: reports/{stem}.md")


if __name__ == "__main__":
    main()
