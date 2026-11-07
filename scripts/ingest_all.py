"""Parse the corpus into cited passages and load sources, passages and vendors.

python scripts/ingest_all.py            # parse + write to the database
python scripts/ingest_all.py --dry-run  # parse only, print passages per source
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.pack import get_pack  # noqa: E402
from app.ingest.passages import parse_corpus  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", metavar="SOURCE", help="print every passage of one source")
    args = ap.parse_args()

    settings = get_settings()
    pack = get_pack()

    if args.dry_run or args.show:
        corpus = parse_corpus(pack, settings.data_dir)
        counts: dict[str, int] = {}
        for p in corpus.passages:
            counts[p.source_id] = counts.get(p.source_id, 0) + 1
            if args.show == p.source_id:
                print(f"--- [{p.segment_kind}] {p.locator}")
                print(f"    {p.context_header}\n    {p.text[:160]!r}")
        for sid, n in counts.items():
            print(f"{sid:14s} {n:4d}")
        print(f"{'total':14s} {len(corpus.passages):4d}")
        return

    from app.core.db import session_scope
    from app.ingest.loader import ingest

    with session_scope() as session:
        report = ingest(session, pack, settings.data_dir)
    for sid, n in report.per_source.items():
        print(f"{sid:14s} {n:4d}")
    print(
        f"sources={report.sources} passages={report.passages_total} "
        f"(inserted={report.passages_inserted} updated={report.passages_updated} "
        f"unchanged={report.passages_unchanged} deleted={report.passages_deleted}) "
        f"vendors={report.vendors}"
    )


if __name__ == "__main__":
    main()
