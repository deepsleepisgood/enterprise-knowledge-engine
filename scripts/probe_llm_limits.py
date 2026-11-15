"""Measure how many parallel model calls the configured OpenAI-compatible endpoint accepts
(Isoquant, NVIDIA NIM or OpenAI), so NIM_MAX_CONCURRENT / NIM_MAX_RPM can be set from evidence.

Sends bursts of tiny requests ("Reply OK", 5 output tokens) straight to the endpoint, without the
engine's own throttle or retries, at rising levels of parallel calls. Stops at the first level
that returns a rate limit (HTTP 429). Prints any rate-limit headers the provider sends, then a
suggested setting. Costs a fraction of a cent: about 100 tiny calls at most.

    python scripts/probe_llm_limits.py                     # MODEL_FAST from .env
    python scripts/probe_llm_limits.py --model smart --levels 4,8,16,32,48

Run it from a laptop with the same key the deployment uses (the limit is per account), and not
while a load test or the demo is running: the probe would take their share.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402

LIMIT_HEADERS = ("ratelimit", "retry-after", "x-concurrency")


def one_call(url: str, headers: dict[str, str], body: bytes, timeout: float) -> dict[str, Any]:
    start = time.perf_counter()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            code, hdrs = r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        code, hdrs = e.code, dict(e.headers or {})
    except (TimeoutError, urllib.error.URLError) as e:
        code, hdrs = 0, {"error": type(e).__name__}
    seen = {k: v for k, v in hdrs.items() if any(h in k.lower() for h in LIMIT_HEADERS)}
    return {"code": code, "s": time.perf_counter() - start, "limit_headers": seen}


def burst(n: int, url: str, headers: dict[str, str], body: bytes, timeout: float) -> list[dict]:
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda _: one_call(url, headers, body, timeout), range(n)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="fast", help='"fast", "smart" or a model id')
    ap.add_argument("--levels", default="4,8,16,24,32", help="parallel calls per burst")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between bursts")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    s = get_settings()
    if s.llm_provider.strip().lower() not in ("nim", "openai"):
        print("LLM_PROVIDER is not nim/openai: this probe is for OpenAI-compatible endpoints.")
        print("For Anthropic, read the limits in the Anthropic console (Settings -> Limits).")
        return 1
    model = {"fast": s.model_fast, "smart": s.model_smart}.get(args.model, args.model)
    url = s.chat_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {s.chat_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if s.is_isoquant:
        headers["Isoquant-ZDR"] = "required"
    msg: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
    }
    msg["max_completion_tokens" if s.is_openai else "max_tokens"] = 5
    body = json.dumps(msg).encode()

    print(f"endpoint {s.chat_base_url}  model {model}")
    print(
        f"engine's current throttle: NIM/OPENAI max {s.chat_max_concurrent} at once, "
        f"{s.chat_max_rpm}/min\n"
    )
    clean, headers_seen, latencies = 0, {}, []
    for n in [int(x) for x in args.levels.split(",") if x.strip()]:
        t0 = time.perf_counter()
        res = burst(n, url, headers, body, args.timeout)
        wall = time.perf_counter() - t0
        codes: dict[int, int] = {}
        for r in res:
            codes[r["code"]] = codes.get(r["code"], 0) + 1
            headers_seen.update(r["limit_headers"])
        ok = [r["s"] for r in res if r["code"] == 200]
        latencies += ok
        med = statistics.median(ok) if ok else 0.0
        print(f"{n:>3} at once: {codes}  median {med:.1f} s  burst took {wall:.1f} s")
        if any(c in codes for c in (401, 403, 404)):
            print("  key, model or endpoint rejected: fix .env before reading the numbers")
            return 1
        if codes.get(200) != n:
            break
        clean = n
        time.sleep(args.pause)

    if headers_seen:
        print("\nrate-limit headers sent by the provider (the most reliable numbers):")
        for k, v in sorted(headers_seen.items()):
            print(f"  {k}: {v}")

    if clean == 0:
        print(
            "\nEven the first level was limited: keep NIM_MAX_CONCURRENT low and ask the "
            "provider for its limits."
        )
        return 0
    conc = max(1, int(clean * 0.75))
    per_call = statistics.median(latencies) if latencies else 3.0
    print(f"\nall {clean} parallel calls were accepted (a higher level may also work).")
    print("Suggested (75% of what passed, leaving room for the worker and a teammate's laptop):")
    print(f"  NIM_MAX_CONCURRENT={conc}")
    print(
        f"  NIM_MAX_RPM={int(conc * 60 / max(per_call, 1.0))}   "
        "(only if the headers above show no lower per-minute limit)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
