"""Render the SOP into other formats (TEST_PLAN level 15): synthetic/variants/.

Reads the original .docx (headings, paragraphs, tables in order) and writes the same content as
PDF (text layer), Markdown, HTML (with site boilerplate), XLSX (tables only), email text, a flat
docx (heading styles removed, numbering kept as plain text), PPTX, and a scanned PDF (pages
rasterised, no text layer). Pure Python (python-docx, PyMuPDF, openpyxl, python-pptx).

    python scripts/render_variants.py [--source data/raw/PS-07_AP_SOP_v4.0_2026.docx]
"""

from __future__ import annotations

import argparse
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "synthetic" / "variants"
SOURCE = ROOT / "data" / "raw" / "PS-07_AP_SOP_v4.0_2026.docx"


def read_blocks(path: Path) -> list[tuple[str, object]]:
    """[(kind, value)] in document order: ('h1'|'h2'|'h3', text), ('p', text),
    ('li', text), ('table', rows)."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    out: list[tuple[str, object]] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style.startswith("heading") or style == "title":
                level = (
                    1 if style == "title" else int(style.split()[-1]) if style[-1].isdigit() else 1
                )
                out.append((f"h{min(level, 3)}", text))
            elif "list" in style:
                out.append(("li", text))
            else:
                out.append(("p", text))
        elif tag == "tbl":
            t = Table(child, doc)
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            if rows:
                out.append(("table", rows))
    return out


def to_markdown(blocks) -> str:
    lines = []
    for kind, v in blocks:
        if kind.startswith("h"):
            lines += ["#" * int(kind[1]) + " " + v, ""]
        elif kind == "li":
            lines.append(f"- {v}")
        elif kind == "p":
            lines += [v, ""]
        else:
            rows = v
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("|" + " --- |" * len(rows[0]))
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            lines.append("")
    return "\n".join(lines)


def to_html(blocks) -> str:
    body = []
    for kind, v in blocks:
        if kind.startswith("h"):
            body.append(f"<{kind}>{html.escape(v)}</{kind}>")
        elif kind == "li":
            body.append(f"<ul><li>{html.escape(v)}</li></ul>")
        elif kind == "p":
            body.append(f"<p>{html.escape(v)}</p>")
        else:
            rows = "".join(
                "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in v
            )
            body.append(f"<table>{rows}</table>")
    return (
        "<!doctype html><html><head><title>AP SOP</title></head><body>"
        "<nav>Intranet | Home | Policies | Search | Log out</nav><main>"
        + "\n".join(body)
        + "</main><footer>Internal use only. Printed copies are uncontrolled.</footer>"
        "</body></html>"
    )


def to_pdf(blocks, path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page, y = doc.new_page(), 60.0
    sizes = {"h1": 16, "h2": 13, "h3": 11.5, "p": 10, "li": 10, "table": 9}

    def write(text: str, size: float, indent: float = 0) -> None:
        nonlocal page, y
        text = text.replace("₹", "Rs ").replace("—", "-").replace("–", "-").replace("’", "'")
        text = text.replace("“", '"').replace("”", '"').replace("→", "->")
        height = 14 * (1 + len(text) * size / 6.2 // 460) + size
        if y + height > 790:
            page, y = doc.new_page(), 60.0
        rect = pymupdf.Rect(60 + indent, y, 535, y + height + 40)
        spare = page.insert_textbox(rect, text, fontsize=size, fontname="helv")
        y += (height + 40 - spare) + 4 if spare >= 0 else height

    for kind, v in blocks:
        if kind == "table":
            for r in v:
                write("   |   ".join(r), sizes["table"])
            y += 6
        else:
            write(("- " if kind == "li" else "") + v, sizes[kind], 12 if kind == "li" else 0)
    doc.save(path)


def to_scanned(pdf: Path, path: Path) -> None:
    import pymupdf

    src, out = pymupdf.open(pdf), pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=150)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=pix.tobytes("jpeg", jpg_quality=80))  # no text layer
    out.save(path)


def to_xlsx(blocks, path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    title, n = "Document", 0
    for kind, v in blocks:
        if kind.startswith("h"):
            title = v
        elif kind == "table":
            n += 1
            ws = wb.create_sheet(f"Table {n}")
            ws.append([title])
            for r in v:
                ws.append(r)
    wb.save(path)


def to_email(blocks) -> str:
    body = to_markdown(blocks).replace("#", "").strip()
    return (
        "From: AP Process Excellence <ap.process@meridian.example>\n"
        "To: AP team <ap.team@meridian.example>\n"
        "Subject: FW: AP SOP v4.0 (full text below)\n"
        "Date: Wed, 1 Apr 2026 09:00:00 +0530\n"
        'Content-Type: text/plain; charset="utf-8"\n\n'
        "Team, the full SOP is pasted below for those who cannot open attachments.\n\n"
        f"{body}\n\nRegards,\nAP Process Excellence\n\n"
        "> -----Original Message-----\n> From: Knowledge team\n> Can you circulate the SOP?\n"
    )


def to_flat_docx(blocks, path: Path) -> None:
    from docx import Document

    d = Document()
    for kind, v in blocks:
        if kind == "table":
            t = d.add_table(rows=0, cols=len(v[0]))
            for r in v:
                cells = t.add_row().cells
                for c, text in zip(cells, r, strict=False):
                    c.text = text
        else:
            d.add_paragraph(("• " if kind == "li" else "") + v)  # Normal style everywhere
    d.save(path)


def to_pptx(blocks, path: Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    slide, body = None, None
    for kind, v in blocks:
        if kind in ("h1", "h2") or slide is None:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = v if kind.startswith("h") else "AP SOP"
            body = slide.placeholders[1].text_frame
            body.clear()
            if kind.startswith("h"):
                continue
        if kind == "table":
            # A real table shape, as a deck would have it (not text with separators).
            rows, cols = len(v), max(len(r) for r in v)
            shape = slide.shapes.add_table(
                rows, cols, Inches(0.5), Inches(4.0), Inches(9.0), Inches(0.3) * rows
            )
            for i, r in enumerate(v):
                for j in range(cols):
                    cell = shape.table.cell(i, j)
                    cell.text = r[j] if j < len(r) else ""
                    for p in cell.text_frame.paragraphs:
                        p.font.size = Pt(9)
            continue
        para = body.add_paragraph()
        para.text = v
        para.font.size = Pt(10)
    prs.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=SOURCE)
    args = ap.parse_args()
    blocks = read_blocks(args.source)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = args.source.stem
    (OUT / f"{stem}.md").write_text(to_markdown(blocks), encoding="utf-8")
    (OUT / f"{stem}.html").write_text(to_html(blocks), encoding="utf-8")
    (OUT / f"{stem}.eml").write_text(to_email(blocks), encoding="utf-8")
    to_pdf(blocks, OUT / f"{stem}.pdf")
    to_scanned(OUT / f"{stem}.pdf", OUT / f"{stem}_scanned.pdf")
    to_xlsx(blocks, OUT / f"{stem}_tables.xlsx")
    to_flat_docx(blocks, OUT / f"{stem}_flat.docx")
    to_pptx(blocks, OUT / f"{stem}.pptx")
    print(f"{len(blocks)} blocks -> {sorted(p.name for p in OUT.iterdir())}")


if __name__ == "__main__":
    main()
