"""Ask the demo questions once through the deployed API, so on stage they come from the cache.

Every model call is cached on the server's disk by its exact prompt, so a question asked again
in the same wording returns in seconds with the same answer. Run after each deploy that changes
code, and again on the demo morning. Asked as user `eval-warm` (left out of analytics).

    python scripts/warm_demo.py --base https://<service>.up.railway.app
    python scripts/warm_demo.py --base ... --file deploy/demo_questions.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _http(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read())


def ask(base: str, question: str, timeout_s: float = 240) -> tuple[dict, float]:
    t0 = time.perf_counter()
    job = _http("POST", f"{base}/ask/jobs", {"question": question, "user_id": "eval-warm"})
    while True:
        time.sleep(1.0)
        st = _http("GET", f"{base}/ask/jobs/{job['job_id']}")
        if st["status"] != "pending" or time.perf_counter() - t0 > timeout_s:
            return st, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="the API address, e.g. https://x.up.railway.app")
    ap.add_argument("--file", default=str(ROOT / "deploy" / "demo_questions.txt"))
    args = ap.parse_args()
    base = args.base.rstrip("/")
    questions = [
        ln.strip()
        for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    try:
        print("health:", _http("GET", f"{base}/health"))
    except (urllib.error.URLError, OSError) as exc:
        print(f"API not reachable at {base}: {exc}", file=sys.stderr)
        return 1
    bad = 0
    for i, q in enumerate(questions, 1):
        st, secs = ask(base, q)
        card = st.get("card") or {}
        status = card.get("status") or st.get("status")
        text = " ".join(((card.get("rule") or {}).get("text") or st.get("error") or "").split())
        print(f"{i}. [{status}, {secs:.0f} s] {q}\n   {text[:220]}")
        bad += st.get("status") != "done"
    print(f"\nwarmed {len(questions) - bad}/{len(questions)}; asked again, they come from cache")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
