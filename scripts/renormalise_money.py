"""Re-apply money normalisation to facts stored before the unit fix (14 Nov 2026).

Extraction used to keep a money amount as written when its unit named the multiple and the
currency together (number 5, unit "<multiple> <currency code>"), so it was not in the base
currency. This finds live money facts with no `as_written` record whose unit now resolves to a
multiplier other than 1, and revises them (the old row is retracted and kept, never deleted).

    python scripts/renormalise_money.py --tenants default,replay           # dry run: list them
    python scripts/renormalise_money.py --tenants default,replay --apply   # revise them

Uses DATABASE_URL like everything else. The revision is bookkeeping (the stated value is the
same), so no kb version or change notice is recorded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import session_scope  # noqa: E402
from app.graph.extract import money_multiplier  # noqa: E402
from app.graph.pipeline import active_ontology  # noqa: E402
from app.store import facts as fstore  # noqa: E402
from app.store.base import use_tenant  # noqa: E402


def fix_tenant(tenant: str, apply: bool) -> int:
    with use_tenant(tenant), session_scope() as s:
        onto = active_ontology(s)
        if onto is None:
            print(f"{tenant}: no frozen schema, skipped")
            return 0
        n = 0
        for f in fstore.get_facts(s):
            v = dict(f.value or {})
            if v.get("type") != "money" or v.get("number") is None or v.get("as_written"):
                continue
            mult = money_multiplier(str(v.get("unit") or ""), onto)
            if mult is None or mult == 1.0:
                continue
            new = {
                **v,
                "number": float(v["number"]) * mult,
                "unit": onto.base_currency or v.get("unit"),
                "as_written": {"number": v["number"], "unit": v.get("unit")},
            }
            was = f"{v['number']} {v.get('unit')}"
            print(f"{tenant}: fact {f.id} {f.attribute}: {was} -> {new['number']:g} {new['unit']}")
            if apply:
                fstore.revise(s, f.id, value=new)
            n += 1
        if not apply:
            s.rollback()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", default="default")
    ap.add_argument("--apply", action="store_true", help="revise the facts (default: dry run)")
    args = ap.parse_args()
    total = sum(fix_tenant(t.strip(), args.apply) for t in args.tenants.split(",") if t.strip())
    print(f"{'revised' if args.apply else 'would revise'} {total} facts")


if __name__ == "__main__":
    main()
