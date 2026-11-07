"""Drop data/raw (and data/ops) through the upload connector and parse everything.

    python scripts/ingest_all.py              # upload + parse (metadata classifier uses MODEL_FAST)
    python scripts/ingest_all.py --no-ops     # documents only
    python scripts/ingest_all.py --show       # print documents and passage locators afterwards

Nothing here is specific to one company: the same path serves any folder of files.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import worker  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.ingest.connectors import from_paths  # noqa: E402
from app.ingest.intake import submit  # noqa: E402
from app.store import episodes as store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--no-ops", action="store_true", help="skip data/ops")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    data = get_settings().data_dir
    paths = args.paths or [data / "raw"] + ([] if args.no_ops else [data / "ops"])
    started = time.perf_counter()
    eps = from_paths(paths)
    created = 0
    with session_scope() as s:
        for ep in eps:
            _, new = submit(s, ep)
            created += new
    print(f"{len(eps)} files, {created} new episodes, {len(eps) - created} duplicates")
    ran = worker.drain(kinds=["parse_episode"], threads=args.threads)
    print(f"parsed {ran} episodes in {time.perf_counter() - started:.1f}s")
    with session_scope() as s:
        print("episodes:", store.episode_counts(s))
        for src in store.list_sources(s):
            ps = store.passages_for_source(s, src.id)
            kinds = Counter(p.segment_kind for p in ps)
            print(
                f"  {src.short_label:<22} {src.doc_type:<17} v{src.version or '-':<4} "
                f"{src.dated or '-'}  {src.status:<10} scope={src.client_scope:<22} "
                f"{len(ps):>5} passages {dict(kinds)}"
            )
            if args.show:
                print("     ", [p.locator for p in ps][:40])
        for ep in store.list_episodes(s):
            if ep.status in ("needs_attention", "failed"):
                print(f"  HELD {ep.source_uri}: {ep.error}")


if __name__ == "__main__":
    main()
