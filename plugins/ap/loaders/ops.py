"""AP plug-in loader: vendors and invoices from an operations workbook (the simulated ERP).

Called by the core's `on_spreadsheet` hook for every spreadsheet episode; it acts only on
workbooks that have `vendors` and `invoices` sheets with the expected id columns. Plug-in tables
carry `tenant_id`; they hold no bank, PAN, IFSC or account columns (dropped on load).
"""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd
from sqlalchemy import Column, MetaData, String, Table, Text, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

META = MetaData()
VENDORS = Table(
    "ap_vendors",
    META,
    Column("tenant_id", String(64), primary_key=True),
    Column("vendor_id", String(64), primary_key=True),
    Column("name", Text, nullable=False),
    Column("client", Text),
    Column("data", JSONB, nullable=False),
)
INVOICES = Table(
    "ap_invoices",
    META,
    Column("tenant_id", String(64), primary_key=True),
    Column("invoice_id", String(64), primary_key=True),
    Column("vendor_id", String(64)),
    Column("client", Text),
    Column("data", JSONB, nullable=False),
)
SENSITIVE = re.compile(r"\b(pan|bank|ifsc|account|acct|a_c)\b", re.I)


def _clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    dropped = [c for c in df.columns if SENSITIVE.search(str(c).replace("_", " "))]
    df = df.drop(columns=dropped)
    return df, dropped


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    # Cleaned per record: a column of None would be re-inferred as float NaN by pandas.
    return [{k: _cell(v) for k, v in r.items()} for r in df.to_dict(orient="records")]


def _cell(v: Any) -> Any:
    """A JSON-safe cell: blanks (NaN, NaT) become None, dates become ISO days."""
    if v is None or (not isinstance(v, (list, dict, str)) and pd.isna(v)):
        return None
    return v.isoformat()[:10] if hasattr(v, "isoformat") else v


def applies(sheets: dict[str, pd.DataFrame]) -> bool:
    v, i = sheets.get("vendors"), sheets.get("invoices")
    return (
        v is not None and i is not None and "vendor_id" in v.columns and "invoice_id" in i.columns
    )


def load(session: Any, data: bytes, tenant_id: str) -> dict[str, Any]:
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    if not applies(sheets):
        return {"skipped": "not an AP operations workbook"}
    META.create_all(session.get_bind(), checkfirst=True)
    vendors, v_drop = _clean(sheets["vendors"])
    invoices, i_drop = _clean(sheets["invoices"])
    for table in (VENDORS, INVOICES):
        session.execute(delete(table).where(table.c.tenant_id == tenant_id))
    v_rows = [
        {
            "tenant_id": tenant_id,
            "vendor_id": str(r["vendor_id"]),
            "name": str(r.get("vendor_name") or r["vendor_id"]),
            "client": r.get("primary_client"),
            "data": r,
        }
        for r in _records(vendors)
    ]
    i_rows = [
        {
            "tenant_id": tenant_id,
            "invoice_id": str(r["invoice_id"]),
            "vendor_id": str(r.get("vendor_id")) if r.get("vendor_id") else None,
            "client": r.get("client"),
            "data": r,
        }
        for r in _records(invoices)
    ]
    for table, rows in ((VENDORS, v_rows), (INVOICES, i_rows)):
        for k in range(0, len(rows), 1000):
            session.execute(pg_insert(table), rows[k : k + 1000])
    return {
        "vendors": len(v_rows),
        "invoices": len(i_rows),
        "dropped": v_drop + i_drop,
        "row_facts": habit_facts(_records(vendors)),
    }


def habit_facts(vendors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each vendor's habit note as a practice statement about that supplier, citing its row of
    the vendors sheet. Vendor names repeat across ids, so the entity is named with the id and the
    statement says which supplier and client it is about."""
    out = []
    for i, r in enumerate(vendors):
        note = str(r.get("habit_note") or "").strip()
        if not note:
            continue
        vid, name = str(r["vendor_id"]), str(r.get("vendor_name") or r["vendor_id"]).strip()
        client = str(r.get("primary_client") or "").strip()
        who = f"{name} ({vid}{', ' + client if client else ''})"
        # "Adds /A ..." reads as "Balaji Logistics (V20000, ...): adds /A ..."; acronyms stay.
        said = note[0].lower() + note[1:] if note[1:2].islower() else note
        out.append(
            {
                "subject": f"{name} ({vid})",
                "subject_type": "supplier",
                "aliases": [name, vid],
                "attrs": {"vendor_id": vid, "primary_client": client},
                "attribute": "supplier_habits.habit_note",
                "statement": f"{who}: {said}",
                "locator": f"vendors row {i + 1}",
                "kind": "practice",
            }
        )
    return out


def on_spreadsheet(session: Any, data: bytes, tenant_id: str) -> dict[str, Any]:
    return load(session, data, tenant_id)


def search_invoices(session: Any, tenant_id: str, q: str = "", limit: int = 20) -> list[dict]:
    stmt = select(
        INVOICES.c.invoice_id, INVOICES.c.vendor_id, INVOICES.c.client, INVOICES.c.data
    ).where(INVOICES.c.tenant_id == tenant_id)
    if q:
        stmt = stmt.where(INVOICES.c.invoice_id.ilike(f"%{q}%"))
    return [dict(r._mapping) for r in session.execute(stmt.limit(limit))]


def vendor(session: Any, tenant_id: str, vendor_id: str) -> dict | None:
    row = session.execute(
        select(VENDORS.c.data).where(
            VENDORS.c.tenant_id == tenant_id, VENDORS.c.vendor_id == vendor_id
        )
    ).first()
    return row[0] if row else None


def _loaded(session: Any) -> bool:
    from sqlalchemy import inspect

    return inspect(session.get_bind()).has_table(INVOICES.name)


def _vendors(session: Any, tenant_id: str, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = session.execute(
        select(VENDORS.c.vendor_id, VENDORS.c.data).where(
            VENDORS.c.tenant_id == tenant_id, VENDORS.c.vendor_id.in_(ids)
        )
    )
    return {vid: data for vid, data in rows}


def invoice_context(inv: dict, ven: dict | None) -> dict[str, Any]:
    """One invoice as the invoice picker and the answer composer show it."""
    d, v = inv.get("data") or {}, ven or {}
    habits = [h for h in [v.get("habit_note")] if h]
    return {
        "invoice_id": inv["invoice_id"],
        "client": inv.get("client") or d.get("client") or "",
        "vendor_id": inv.get("vendor_id") or "",
        "vendor_name": v.get("vendor_name") or inv.get("vendor_id") or "",
        "invoice_date": d.get("invoice_date") or "",
        "total_inr": d.get("total_inr") or 0,
        "po_backed": bool(d.get("po_backed")),
        "msme_category": v.get("msme_category") or "",
        "einvoice_required": bool(v.get("einvoice_required")),
        "qrmp_filer": bool(v.get("qrmp_filer")),
        "due_date": d.get("due_date") or "",
        "payment_run": "",  # computed by the msme calculator when asked, not stored
        "habits": habits,
    }


def invoice_search(session: Any, tenant_id: str, q: str = "", limit: int = 20) -> list[dict]:
    """Hook `invoice_search`: invoices whose id, vendor or client matches `q`."""
    if not _loaded(session):
        return []
    stmt = (
        select(INVOICES.c.invoice_id, INVOICES.c.vendor_id, INVOICES.c.client, INVOICES.c.data)
        .select_from(
            INVOICES.outerjoin(
                VENDORS,
                (VENDORS.c.tenant_id == INVOICES.c.tenant_id)
                & (VENDORS.c.vendor_id == INVOICES.c.vendor_id),
            )
        )
        .where(INVOICES.c.tenant_id == tenant_id)
    )
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            INVOICES.c.invoice_id.ilike(like)
            | INVOICES.c.client.ilike(like)
            | VENDORS.c.name.ilike(like)
            | INVOICES.c.vendor_id.ilike(like)
        )
    rows = [
        dict(r._mapping) for r in session.execute(stmt.order_by(INVOICES.c.invoice_id).limit(limit))
    ]
    vens = _vendors(session, tenant_id, sorted({r["vendor_id"] for r in rows if r["vendor_id"]}))
    return [invoice_context(r, vens.get(r["vendor_id"])) for r in rows]


def context(
    session: Any, tenant_id: str, invoice_id: str | None = None, vendor_id: str | None = None
) -> dict[str, Any] | None:
    """Hook `context`: the invoice (if any) and its vendor's tips, for the answer composer."""
    if not _loaded(session):
        return None
    inv = None
    if invoice_id:
        row = session.execute(
            select(
                INVOICES.c.invoice_id, INVOICES.c.vendor_id, INVOICES.c.client, INVOICES.c.data
            ).where(INVOICES.c.tenant_id == tenant_id, INVOICES.c.invoice_id == invoice_id)
        ).first()
        if row is None:
            return None
        inv = dict(row._mapping)
        vendor_id = inv["vendor_id"]
    ven = _vendors(session, tenant_id, [vendor_id]).get(vendor_id) if vendor_id else None
    if inv is None and ven is None:
        return None
    return {
        "invoice": invoice_context(inv, ven) if inv else None,
        "vendor": {
            k: ven.get(k)
            for k in (
                "vendor_id",
                "vendor_name",
                "primary_client",
                "msme_category",
                "supply_type",
                "einvoice_required",
                "qrmp_filer",
                "default_tds_section",
                "payment_term_days",
                "written_term_agreement",
            )
        }
        if ven
        else None,
        "tips": [ven["habit_note"]] if ven and ven.get("habit_note") else [],
        "client": (inv or {}).get("client") or (ven or {}).get("primary_client"),
    }
