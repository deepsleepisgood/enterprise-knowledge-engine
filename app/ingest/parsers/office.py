"""Tier-1 parsers for Office Open XML: docx, xlsx (and csv), pptx."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from app.ingest.blocks import Block, clean

_HEADING_STYLE = re.compile(r"^(?:Heading|Überschrift|Titre)\s*(\d)$", re.I)


# ---------------------------------------------------------------- docx


def _para_meta(p: Any) -> dict[str, Any]:
    runs = [r for r in p.runs if r.text.strip()]
    sizes = [r.font.size.pt for r in runs if r.font.size is not None]
    return {
        "bold": bool(runs) and all(bool(r.bold) for r in runs),
        "font_size": max(sizes) if sizes else None,
        "all_caps": p.text.isupper() and len(p.text) > 3,
    }


def _list_formats(document: Any) -> Any:
    """(numId, ilvl) -> numFmt ("decimal", "bullet", ...) from the numbering part."""
    try:
        numbering = document.part.numbering_part.numbering_definitions._numbering
    except (KeyError, NotImplementedError, AttributeError):
        return lambda num_id, ilvl: None
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    abstract = {}
    for num in numbering.findall(f"{w}num"):
        a = num.find(f"{w}abstractNumId")
        if a is not None:
            abstract[num.get(f"{w}numId")] = a.get(f"{w}val")
    fmts = {}
    for an in numbering.findall(f"{w}abstractNum"):
        for lvl in an.findall(f"{w}lvl"):
            f = lvl.find(f"{w}numFmt")
            if f is not None:
                fmts[(an.get(f"{w}abstractNumId"), lvl.get(f"{w}ilvl"))] = f.get(f"{w}val")
    return lambda num_id, ilvl: fmts.get((abstract.get(str(num_id)), str(ilvl)))


def parse_docx(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    list_format = _list_formats(document)
    blocks: list[Block] = []
    offset = 0
    for el in document.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, document)
            text = clean(p.text)
            if not text:
                continue
            style = p.style.name if p.style is not None else ""
            meta = _para_meta(p)
            pos = {"char_offset": offset}
            offset += len(text) + 1
            m = _HEADING_STYLE.match(style)
            numpr = p._p.pPr is not None and p._p.pPr.numPr is not None
            if m:
                blocks.append(
                    Block(
                        "heading", text, level=int(m.group(1)), style=style, meta=meta, position=pos
                    )
                )
            elif style == "Title":
                blocks.append(
                    Block(
                        "paragraph", text, style=style, meta={**meta, "title": True}, position=pos
                    )
                )
            elif numpr or style.lower().startswith("list"):
                level, fmt = 0, None
                if numpr:
                    np_ = p._p.pPr.numPr
                    level = int(np_.ilvl.val) if np_.ilvl is not None else 0
                    fmt = list_format(np_.numId.val if np_.numId is not None else None, level)
                meta["ordered"] = fmt not in (None, "bullet", "none")
                blocks.append(
                    Block("list_item", text, level=level, style=style, meta=meta, position=pos)
                )
            elif style.lower().startswith(("quote", "intense quote")):
                blocks.append(Block("quote", text, style=style, meta=meta, position=pos))
            else:
                blocks.append(Block("paragraph", text, style=style, meta=meta, position=pos))
        elif tag == "tbl":
            t = Table(el, document)
            rows = [[clean(c.text.replace("\n", " / ")) for c in r.cells] for r in t.rows]
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append(Block("table", rows=rows, position={"char_offset": offset}))
    cp = document.core_properties
    props = {
        "title": cp.title or None,
        "author": cp.author or None,
        "subject": cp.subject or None,
        "created": cp.created.isoformat() if cp.created else None,
        "modified": cp.modified.isoformat() if cp.modified else None,
        "keywords": cp.keywords or None,
    }
    return blocks, {k: v for k, v in props.items() if v}


# ---------------------------------------------------------------- spreadsheets


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        s = v.isoformat()
        return s[:10] if s.endswith("T00:00:00") or len(s) == 19 and s.endswith("00:00:00") else s
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return clean(str(v))


def _sheet_blocks(name: str, rows: list[list[str]], sheet_index: int) -> list[Block]:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # Drop columns that are empty everywhere.
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    out = [Block("heading", name, level=1, style="sheet", position={"sheet": name})]
    # A sheet whose rows are mostly single cells is prose (a README), not a table.
    if sum(1 for r in rows if sum(1 for c in r if c) <= 1) > 0.6 * len(rows):
        for i, r in enumerate(rows):
            text = " ".join(c for c in r if c)
            out.append(Block("paragraph", text, position={"sheet": name, "row": i + 1}))
        return out
    out.append(
        Block(
            "table",
            rows=rows,
            style="sheet",
            position={"sheet": name, "sheet_index": sheet_index, "first_row": 1},
            meta={"spreadsheet": True},
        )
    )
    return out


def parse_xlsx(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    blocks: list[Block] = []
    for i, ws in enumerate(wb.worksheets):
        rows = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        blocks += _sheet_blocks(ws.title, rows, i)
    props = wb.properties
    meta = {
        "title": props.title,
        "author": props.creator,
        "created": props.created.isoformat() if props.created else None,
        "modified": props.modified.isoformat() if props.modified else None,
    }
    return blocks, {k: v for k, v in meta.items() if v}


def parse_csv(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:5000]) if text.strip() else csv.excel
    rows = [[clean(c) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    return _sheet_blocks("Sheet1", rows, 0), {}


# ---------------------------------------------------------------- pptx


def parse_pptx(data: bytes) -> tuple[list[Block], dict[str, Any]]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    blocks: list[Block] = []
    for n, slide in enumerate(prs.slides, 1):
        pos = {"slide": n}
        title_shape = slide.shapes.title
        title = clean(title_shape.text_frame.text) if title_shape is not None else ""
        blocks.append(Block("heading", title or f"Slide {n}", level=1, style="slide", position=pos))
        for shape in slide.shapes:
            if shape is title_shape:
                continue
            if shape.has_table:
                rows = [[clean(c.text) for c in r.cells] for r in shape.table.rows]
                blocks.append(Block("table", rows=rows, position=pos))
            elif shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = clean("".join(r.text for r in para.runs))
                    if not text:
                        continue
                    kind = (
                        "list_item"
                        if para.level > 0 or len(shape.text_frame.paragraphs) > 1
                        else "paragraph"
                    )
                    blocks.append(Block(kind, text, level=para.level, position=pos))
        if slide.has_notes_slide:
            notes = clean(slide.notes_slide.notes_text_frame.text)
            if notes:
                blocks.append(Block("paragraph", notes, position=pos, meta={"speaker_notes": True}))
    cp = prs.core_properties
    meta = {
        "title": cp.title or None,
        "author": cp.author or None,
        "modified": cp.modified.isoformat() if cp.modified else None,
    }
    return blocks, {k: v for k, v in meta.items() if v}
