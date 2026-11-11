"""Text-layout signals in PDFs and plain text: pipe tables, numbered section titles."""

from __future__ import annotations

import pymupdf

from app.ingest.parsers.pdf import _pipe_cells, parse_pdf


def _pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for text in lines:
        page.insert_text((72, y), text, fontsize=10)
        y += 14 if text else 28
    return doc.tobytes()


def test_pipe_cells() -> None:
    assert _pipe_cells("Code   |   Owner") == ["Code", "Owner"]
    assert _pipe_cells("A sentence with no cells.") is None
    assert _pipe_cells("x | ") is None  # an empty cell is not a row


def test_text_table_becomes_a_table_block() -> None:
    data = _pdf(
        [
            "Rates are set out below.",
            "",
            "Nature of payment   |   Section   |   Rate",
            "Contract work by an individual   |   S1   |   1%",
            "Rent of a building   |   S2   |   10%",
            "",
            "After the table comes a paragraph.",
        ]
    )
    blocks, _ = parse_pdf(data)
    tables = [b for b in blocks if b.type == "table"]
    assert len(tables) == 1
    assert tables[0].rows[0] == ["Nature of payment", "Section", "Rate"]
    assert tables[0].rows[2] == ["Rent of a building", "S2", "10%"]
    texts = [b.text for b in blocks if b.type == "paragraph"]
    assert any("After the table" in t for t in texts)
    assert not any("|" in (t or "") for t in texts)


def test_pipe_table_in_an_email_body_is_a_table() -> None:
    from app.ingest.parsers.textual import parse_eml

    raw = (
        b"From: Ops <ops@example.com>\nSubject: Rates\nContent-Type: text/plain\n\n"
        b"Rates below.\n\n| Payment | Rate |\n| --- | --- |\n| Contract | 1% |\n| Rent | 10% |\n"
    )
    blocks, _ = parse_eml(raw)
    [table] = [b for b in blocks if b.type == "table"]
    assert table.rows[-1] == ["Rent", "10%"]


def test_numbered_title_alone_in_plain_text_keeps_its_number() -> None:
    from app.ingest.parsers.textual import parse_text

    text = "7. Approvals\n\nInvoices above the limit need sign-off.\n\n1. Check it.\n2. Post it.\n"
    blocks, _ = parse_text(text, markdown=False)
    assert blocks[0].type == "paragraph" and blocks[0].text == "7. Approvals"
    assert [b.type for b in blocks[2:]] == ["list_item", "list_item"]
