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
    df = df.astype(object).where(pd.notna(df), None)
    for c in df.columns:
        df[c] = df[c].map(lambda v: v.isoformat()[:10] if hasattr(v, "isoformat") else v)
    return df, dropped


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
        for r in vendors.to_dict(orient="records")
    ]
    i_rows = [
        {
            "tenant_id": tenant_id,
            "invoice_id": str(r["invoice_id"]),
            "vendor_id": str(r.get("vendor_id")) if r.get("vendor_id") else None,
            "client": r.get("client"),
            "data": r,
        }
        for r in invoices.to_dict(orient="records")
    ]
    for table, rows in ((VENDORS, v_rows), (INVOICES, i_rows)):
        for k in range(0, len(rows), 1000):
            session.execute(pg_insert(table), rows[k : k + 1000])
    return {"vendors": len(v_rows), "invoices": len(i_rows), "dropped": v_drop + i_drop}


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
