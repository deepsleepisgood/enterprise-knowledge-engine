# Format invariance — 14 Nov 2026 (full matrix, gate B)

The AP SOP v4.0 rendered in eight other formats (`synthetic/variants/`, made by
`scripts/render_variants.py`) and ingested into fresh tenants. Each is compared with the original
.docx ingested the same way. Local database; LLM `deepseek-v4.1-flash-1017-fast` on Isoquant for
extraction and, for the scanned PDF, vision. `--variants pdf,md,html,xlsx,eml,flat_docx,pptx`
plus `--variants scanned` with `MODEL_VISION` set to the same model.

Baseline: original .docx, 170 facts, 76 passages.

| variant | F1 | precision | recall | rule F1 | passages | scenarios (92) | target | pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pdf (text layer) | 0.94 | 0.96 | 0.92 | 0.94 | 47% | 100% | F1 ≥ 0.9 | PASS |
| md | 1.00 | 1.00 | 1.00 | 1.00 | 50% | 100% | F1 ≥ 0.9 | PASS |
| html | 1.00 | 1.00 | 1.00 | 1.00 | 50% | 100% | F1 ≥ 0.9 | PASS |
| eml (email text) | 0.93 | 0.92 | 0.94 | 0.93 | 50% | 97% | F1 ≥ 0.9 | PASS |
| scanned pdf (vision) | 0.90 | 0.93 | 0.88 | 0.94 | 47% | 100% | F1 ≥ 0.8 | PASS |
| pptx | 0.87 | 0.87 | 0.86 | 0.87 | 50% | 100% | F1 ≥ 0.9 | FAIL (F1) |
| xlsx (tables only) | 0.86 | 0.87 | 0.85 | 0.90 | 5% | 89% (not judged) | F1 ≥ 0.9 | FAIL (F1) |
| flat docx (no heading styles) | 0.80 | 0.79 | 0.80 | 0.84 | 50% | 100% | F1 ≥ 0.9 | FAIL (F1) |

**Pass mark:** fact F1 at the target, and at least 95% of the 92 scenario calculations giving the
same decision and numbers as the .docx.

**What the columns mean**
- **F1:** a fact matches when its subject, attribute, client scope and value all match after
  normalisation.
- **rule F1:** the same match without the subject. It is reported only, not part of the pass mark.
  The extractor may file one rule under different subject entities in different layouts, while
  answers and calculators look rules up by attribute and scope.
- **passages:** the share of the baseline's passages whose sentences reappear. About 50% is
  expected, because the .docx also has a passage per table row.
- **xlsx** holds the tables only. Its F1 counts only the baseline facts that come from tables.
  Its scenario figure is not judged: the calculators also need rules stated in prose (the rate
  without a PAN, default payment terms), which a tables-only file cannot contain.

## Every variant now gives the same calculations

Every variant except the tables-only xlsx gives the same results as the .docx on 97–100% of
scenario calculations. The remaining fact-F1 gap on pptx and the flat docx is mostly free-text
values worded differently (for example "returned to the supplier for a corrected invoice" against
a paraphrase), since the metric requires the normalised text to be equal. The lists below give the
first 15 per variant (`_text_variants.md`, `_scanned.md`).

## Changes from 11 Nov

| variant | 11 Nov | 14 Nov | why |
| --- | --- | --- | --- |
| pdf | 0.88 | 0.94 | parser fixes (text tables) |
| eml | 0.77 | 0.93 | pipe and plain-text tables in email |
| xlsx | 0.00 | 0.86 | header-row fix; values in lists merged |
| flat docx | 0.92 | 0.80 | see note 1 |
| pptx | — (0.71 first run) | 0.87 | see note 2 |
| scanned | not run | 0.90 | vision tier enabled (`MODEL_VISION`) |

## Bugs found by this run and fixed (all general, none specific to these files)

1. **Metadata read only from the preamble** (`app/ingest/metadata.py`).
   - When the outline put a banner line above the title (an outline rebuilt from plain text, a
     slide title), the header table and the "effective …" line fell outside the preamble.
   - The document was then dated by the file's timestamp. Here that was the library template's
     2013 date.
   - The classifier, never shown the "Applies to" row, invented a client scope. Every fact of
     the flat docx and the pptx was scoped to that client, so F1 was 0.00.
   - Now the opening blocks before the first section heading are read too.
   - Test: `tests/unit/test_metadata_opening.py`.
2. **The pptx variant had no tables** (`scripts/render_variants.py`).
   - It wrote each table as one bullet ("a / b / c | …"), which is not how a deck holds a table.
   - It now writes real table shapes, which the parser reads cell by cell.
   - The first run on the flattened file scored 0.71 (`_first_run.md`).
3. **Money units naming the multiple and the currency together** (`app/graph/extract.py`).
   - "lakh INR" and "crore INR" were not converted, so ₹10 lakh was stored as 10.
   - Now currency words are dropped and the known multiplier applied. Unknown words are still
     never guessed.
   - The same bug is in 4 live facts on Neon; the repair is `scripts/renormalise_money.py`
     (dry run lists them).
4. **One passage's list values split into conflicting facts** (`app/graph/extract.py`).
   - "Payment runs are on Tuesday and Friday" came back as two facts, "Tuesday" and "Friday".
     Resolution treated them as a conflict and kept only "Tuesday", which changed 9 MSME
     payment-date calculations.
   - List-type values of one attribute from one passage are now merged into one fact. Numbers
     are never merged.
   - Tests: `tests/unit/test_money_units.py`.

## Open

- The pptx and flat docx F1 (0.87, 0.80) are below 0.9. Their calculations match 100%. The gap is
  wording and subject choice on free-text facts. A semantic comparison of text values (like the
  conflict judge) would measure this more fairly than exact text, but has not been built.
- xlsx F1 0.86 (rule F1 0.90).
- Vision is off unless `MODEL_VISION` is set; `.env.example` now says so.
