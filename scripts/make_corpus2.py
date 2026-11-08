"""Write the second-company corpus (TEST_PLAN level 16): synthetic/corpus2_hr/.

A small, unrelated company (Kestrel Freight, fictional) with an HR leave policy in two versions
and other formats: v1 .docx with unnumbered headings, v2 .pdf with a later date, an FAQ .md, a
department memo .html that overrides one rule, an announcement .eml, and an entitlement table
.xlsx. Plus questions.csv. Written once; never used to tune prompts or thresholds.

    python scripts/make_corpus2.py
"""

from __future__ import annotations

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "synthetic" / "corpus2_hr"

V1 = [
    ("title", "Kestrel Freight — Leave Policy"),
    ("meta", [("Version", "1.0"), ("Effective", "1 January 2025"), ("Owner", "People Team")]),
    ("h", "Purpose"),
    ("p", "This policy sets out leave for all Kestrel Freight employees."),
    ("h", "Annual leave"),
    ("p", "Employees get 20 days of annual leave per calendar year."),
    ("p", "Up to 5 unused days can be carried forward to the next year."),
    ("h", "Sick leave"),
    ("p", "Employees get 10 days of paid sick leave per year."),
    ("h", "Applying for leave"),
    ("p", "Annual leave must be requested at least 14 days before the first day of leave."),
]

V2 = [
    ("title", "Kestrel Freight — Leave Policy, version 2"),
    (
        "meta",
        [
            ("Version", "2.0"),
            ("Effective", "1 April 2026"),
            ("Owner", "People Team"),
            ("Supersedes", "Leave Policy version 1.0"),
        ],
    ),
    ("h", "1. Purpose"),
    ("p", "This policy sets out leave for all Kestrel Freight employees. It replaces version 1.0."),
    ("h", "2. Annual leave"),
    (
        "p",
        "Employees get 24 days of annual leave per calendar year at grade L1. Higher grades get "
        "more; see the leave entitlement table.",
    ),
    ("p", "Up to 8 unused days can be carried forward to the next year."),
    ("h", "3. Sick leave"),
    (
        "p",
        "Employees get 12 days of paid sick leave per year. A doctor's note is needed for more "
        "than 2 consecutive days.",
    ),
    ("h", "4. Applying for leave"),
    (
        "p",
        "Annual leave must be requested at least 10 days before the first day of leave, through "
        "the HR portal.",
    ),
]

FAQ = """# Leave FAQ — People Team

Last reviewed: 15 April 2026

## How do I apply for leave?
Apply through the HR portal under "My leave". Your line manager approves the request.

## Can I cash out unused leave?
No. Unused days beyond the carry-forward limit lapse at the end of the year.

## Who do I ask about a leave balance that looks wrong?
Raise a ticket with the People Team in the HR portal.
"""

MEMO = """<!doctype html>
<html><head><title>Warehouse Operations memo WO-12</title></head>
<body>
<nav>Kestrel intranet | Home | Teams | Search</nav>
<article>
<h1>Memo WO-12: Leave notice during peak season (Warehouse Operations)</h1>
<table>
<tr><td>Issued</td><td>1 September 2026</td></tr>
<tr><td>From</td><td>Head of Warehouse Operations</td></tr>
<tr><td>Applies to</td><td>Warehouse Operations staff only</td></tr>
</table>
<p>From 1 October to 31 December each year, Warehouse Operations staff must request annual
leave at least 30 days before the first day of leave. This replaces the general notice period
for this department during that season only. All other leave rules are unchanged.</p>
</article>
<footer>Kestrel Freight internal. Do not forward.</footer>
</body></html>
"""

EMAIL = """From: People Team <people@kestrel.example>
To: All staff <all@kestrel.example>
Subject: New: quarterly wellness day from January 2027
Date: Tue, 20 Oct 2026 09:00:00 +0000
Message-ID: <wellness-2027@kestrel.example>
Content-Type: text/plain; charset="utf-8"

Hello everyone,

From 1 January 2027, every employee gets one paid wellness day per quarter, in addition to
annual leave. Wellness days cannot be carried forward to the next quarter. Book them in the
HR portal like any other leave.

Best wishes,
People Team
"""

TABLE = [
    ("Grade", "Annual leave days (from 1 April 2026)", "Carry forward limit"),
    ("L1", 24, 8),
    ("L2", 26, 8),
    ("L3", 28, 10),
    ("L4", 30, 10),
]

QUESTIONS = [
    # id, question, as_of, expected (any of, |), must_not_say, status, file
    (
        "H01",
        "How many days of paid sick leave do employees get per year?",
        "",
        "12",
        "10",
        "answered",
        "leave_policy_v2.pdf",
    ),
    (
        "H02",
        "How much notice is needed for annual leave?",
        "",
        "10 days",
        "14 days",
        "answered",
        "leave_policy_v2.pdf",
    ),
    ("H03", "How do I apply for leave?", "", "HR portal", "", "answered", "leave_faq.md"),
    (
        "H04",
        "How many unused annual leave days can be carried forward?",
        "",
        "8",
        "",
        "answered",
        "leave_policy_v2.pdf",
    ),
    (
        "H05",
        "How many days of annual leave did employees get?",
        "2025-06-01",
        "20",
        "24",
        "answered",
        "leave_policy_v1.docx",
    ),
    (
        "H06",
        "How many days of annual leave does a grade L1 employee get per year?",
        "",
        "24",
        "20 days",
        "answered",
        "leave_policy_v2.pdf",
    ),
    (
        "H07",
        "I work in Warehouse Operations. How much notice do I need for leave in November?",
        "",
        "30 days",
        "",
        "answered",
        "warehouse_memo_wo12.html",
    ),
    (
        "H08",
        "How many annual leave days does a grade L3 employee get?",
        "",
        "28",
        "",
        "answered",
        "leave_entitlements.xlsx",
    ),
    ("H09", "What is the reimbursement limit for gym memberships?", "", "", "", "unsupported", ""),
    (
        "H10",
        "How many wellness days will each employee get?",
        "",
        "one|1",
        "",
        "answered",
        "wellness_announcement.eml",
    ),
]


def write_docx(path: Path, blocks: list) -> None:
    from docx import Document

    d = Document()
    for kind, val in blocks:
        if kind == "title":
            d.add_heading(val, level=0)
        elif kind == "meta":
            t = d.add_table(rows=0, cols=2)
            for k, v in val:
                row = t.add_row().cells
                row[0].text, row[1].text = k, v
        elif kind == "h":
            d.add_heading(val, level=1)  # unnumbered headings
        else:
            d.add_paragraph(val)
    d.save(path)


def write_pdf(path: Path, blocks: list) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    y = 72

    def line(text: str, size: float) -> None:
        nonlocal page, y
        if y > 760:
            page, y = doc.new_page(), 72
        rect = fitz.Rect(72, y, 523, y + 200)
        text = text.replace("—", "-").replace("’", "'")  # base-14 font encoding
        used = page.insert_textbox(rect, text, fontsize=size, fontname="helv")
        y += (200 - used) + size * 0.8 if used > 0 else size * 3

    for kind, val in blocks:
        if kind == "title":
            line(val, 18)
        elif kind == "meta":
            for k, v in val:
                line(f"{k}: {v}", 10)
        elif kind == "h":
            line(val, 14)
        else:
            line(val, 10.5)
    doc.save(path)


def write_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Leave entitlement"
    for row in TABLE:
        ws.append(list(row))
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_docx(OUT / "leave_policy_v1.docx", V1)
    write_pdf(OUT / "leave_policy_v2.pdf", V2)
    (OUT / "leave_faq.md").write_text(FAQ, encoding="utf-8")
    (OUT / "warehouse_memo_wo12.html").write_text(MEMO, encoding="utf-8")
    (OUT / "wellness_announcement.eml").write_text(EMAIL, encoding="utf-8")
    write_xlsx(OUT / "leave_entitlements.xlsx")
    with (OUT / "questions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "question", "as_of", "expected", "must_not_say", "status", "file"])
        w.writerows(QUESTIONS)
    print(f"wrote {len(list(OUT.iterdir()))} files to {OUT}")


if __name__ == "__main__":
    main()
