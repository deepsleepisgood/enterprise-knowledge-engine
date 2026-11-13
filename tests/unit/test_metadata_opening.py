"""Document metadata comes from the opening blocks even when a banner line above the title was
read as a heading (an outline rebuilt from plain text, a slide title): the header table and the
"effective" line then sit under that heading, not in the preamble. Before the fix, such a file
was dated by its file timestamp and the classifier never saw the "Applies to" row."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ingest import metadata as md
from app.ingest.blocks import Block
from app.ingest.segment import split_documents


def _blocks() -> list[Block]:
    return [
        Block("heading", "ACME · DATA PACK", level=1, style="inferred"),
        Block("paragraph", "Expense Policy — version 2.0"),
        Block("paragraph", "Acme Ltd · effective 1 March 2026"),
        Block(
            "table",
            rows=[
                ["Document", "Expense Policy"],
                ["Version", "2.0"],
                ["Effective", "1 March 2026"],
                ["Applies to", "Acme North, Acme South"],
            ],
        ),
        Block("heading", "1. Purpose", level=2, style="inferred"),
        Block("paragraph", "This policy explains how staff claim expenses."),
    ]


def test_header_table_under_a_banner_heading_dates_the_document() -> None:
    (doc,) = split_documents(_blocks())
    seen: dict[str, str] = {}

    def classifier(prompt, schema, **_):  # records what the classifier was shown
        seen["prompt"] = prompt
        return schema(
            doc_type="policy",
            short_label="Expense v2.0",
            title="Expense Policy",
            client_scope="all",
            status="current",
            practice=False,
            confidence=0.9,
        )

    m = md.infer(
        doc,
        filename="policy.docx",
        file_meta={"modified": "2013-12-23T23:15:00+00:00"},  # a library's template date
        received_at=datetime(2026, 11, 14, tzinfo=UTC),
        channel="upload",
        llm_fn=classifier,
    )
    assert str(m.get("dated")) == "2026-03-01"
    assert m.fields["dated"].origin == "header table 'Effective'"
    assert m.get("version") == "2.0"
    assert "Applies to: Acme North, Acme South" in seen["prompt"]
