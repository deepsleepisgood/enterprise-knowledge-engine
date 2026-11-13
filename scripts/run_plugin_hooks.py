"""Re-run the plug-ins' hooks on an episode already ingested (for example after a plug-in learned to
read more from it), then embed whatever is new.

    python scripts/run_plugin_hooks.py --file PS-07_ap_operations.xlsx
    python scripts/run_plugin_hooks.py --file PS-07_ap_operations.xlsx --approve --by "owner"

Facts a hook reads from data rows are held for the owner unless `--approve` says the owner is
publishing them (or governance is off). Uses DATABASE_URL and TENANT_ID like everything else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.answer.index import index_all  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.ingest.pipeline import plugin_hooks  # noqa: E402
from app.store import episodes as estore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="the episode's original file name")
    ap.add_argument("--event", default="on_spreadsheet")
    ap.add_argument("--approve", action="store_true", help="publish row facts without review")
    ap.add_argument("--by", default="process owner", help="who approves (recorded on the facts)")
    args = ap.parse_args()
    with session_scope() as s:
        hits = [e for e in estore.list_episodes(s) if (e.source_uri or "").endswith(args.file)]
    if len(hits) != 1:
        sys.exit(f"expected one episode named {args.file}, found {len(hits)}")
    payload = {"episode_id": hits[0].id, "event": args.event, "by": args.by}
    if args.approve:
        payload["approve_row_facts"] = True
    out = plugin_hooks(payload)
    print(json.dumps(out, indent=2, default=str))
    print("embeddings:", index_all())


if __name__ == "__main__":
    main()
