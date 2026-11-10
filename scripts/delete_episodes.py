"""Remove test uploads from a development graph, and optionally discard a schema draft.

    python scripts/delete_episodes.py                       # list episodes
    python scripts/delete_episodes.py <episode_id> ... [--discard-schema 4] --yes

Without --yes it only shows what would be removed. The knowledge graph never deletes real
content (it retires it); this is for test data only. Bumps the kb version when it removes
anything, so open pages refresh.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import session_scope  # noqa: E402
from app.store import episodes as estore  # noqa: E402
from app.store import kb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("episode_ids", nargs="*")
    ap.add_argument("--discard-schema", type=int, action="append", default=[])
    ap.add_argument("--yes", action="store_true", help="really delete")
    args = ap.parse_args()

    with session_scope() as s:
        eps = {e.id: e for e in estore.list_episodes(s)}
        if not args.episode_ids and not args.discard_schema:
            for e in sorted(eps.values(), key=lambda e: e.created_at):
                labels = ", ".join(
                    x.short_label or x.title or "" for x in estore.list_sources(s, e.id)
                )
                print(
                    f"{e.id}  {e.created_at:%Y-%m-%d}  {e.channel:<14} {e.source_uri}  [{labels}]"
                )
            return 0
        missing = [i for i in args.episode_ids if i not in eps]
        if missing:
            print("unknown episode ids:", ", ".join(missing))
            return 1
        for i in args.episode_ids:
            print(f"episode {i}: {eps[i].source_uri} ({eps[i].channel})")
        for v in args.discard_schema:
            sch = kb.get_schema(s, v)
            print(f"schema v{v}: {sch.status if sch else 'not found'}")
        if not args.yes:
            print("dry run: add --yes to delete")
            return 0
        out = estore.delete_episodes(s, args.episode_ids)
        for v in args.discard_schema:
            out[f"schema_v{v}_discarded"] = int(kb.discard_schema_draft(s, v))
        if any(out.values()):
            out["kb_version"] = kb.bump_kb_version(s, "removed test uploads")
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
