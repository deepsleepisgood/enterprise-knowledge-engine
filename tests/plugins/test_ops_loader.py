"""AP operations loader: blank cells must reach Postgres JSONB as null, never NaN."""

from __future__ import annotations

import json
import math
from datetime import datetime

import pandas as pd

from app.plugins import registry


def test_blank_cells_become_null_and_dates_iso() -> None:
    ops = registry.get("ap").module("loaders.ops")
    df = pd.DataFrame(
        {
            "vendor_id": ["V1", "V2"],
            "default_tds_section": [float("nan"), float("nan")],  # an all-blank column
            "joined": [datetime(2026, 4, 1), pd.NaT],
            "bank_account": ["123", "456"],
        }
    )
    clean, dropped = ops._clean(df)
    rows = ops._records(clean)
    assert dropped == ["bank_account"]
    assert rows[0] == {"vendor_id": "V1", "default_tds_section": None, "joined": "2026-04-01"}
    assert rows[1]["joined"] is None
    text = json.dumps(rows, allow_nan=False)  # raises on NaN
    assert "NaN" not in text and not any(
        isinstance(v, float) and math.isnan(v) for r in rows for v in r.values()
    )
