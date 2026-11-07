# PROGRESS

Running log of what was built, test results, assumptions and open issues. Newest at the bottom.

---

## 2026-11-07 — Phase 0 (scaffold) and Phase 1 (domain pack + ingestion)

### Built

**Phase 0**
- Repo layout from CLAUDE.md. Data moved to `data/raw/` (4 .docx), `data/ops/` (operations workbook), `eval/` (evaluation workbook).
- `pyproject.toml` (ruff, pytest config), `.env.example`, `.gitignore`, `docker-compose.yml` (`pgvector/pgvector:pg16`).
- `scripts/dev_db.py`: an embedded Postgres 16.2 + pgvector 0.6.2 (via `pgserver`) for machines without Docker. `start` writes `.pgdata/database_url.txt`, which settings pick up when `DATABASE_URL` is unset; `stop` frees the port.
- `app/core/config.py`, `db.py`, `models.py`: all 13 tables from BUILD_PLAN (`acks` and `notifications` as two tables). Alembic migration `0001` creates the `vector` extension, the tables, a GIN index on `passages.tsv` and a `(source_id, locator)` index.
- `app/core/redaction.py`: PAN, IFSC, bank account numbers (9–18 digits next to account / a/c / acct), Indian mobiles, email addresses. GSTINs, rupee amounts, invoice numbers and timestamps are left alone (tested).
- `app/core/llm.py`: `complete()` and `structured()`; redacts the prompt and system text; on-disk cache in `.cache/llm/` keyed by sha256(prompt_version, model, style, system, prompt, schema, effort); JSONL log in `logs/llm_calls.jsonl` with the redacted prompt, model, tokens, cost, latency and cache hits; raises on `refusal` and `max_tokens`. `model="fast" | "smart" | <id>`.
- `tests/test_no_leakage.py`: scans `app/`, `web/`, `packs/` and `scripts/ingest_*` for `qa_evaluation_set`, `known_conflicts`, `gold_answer`.

**Phase 1**
- Domain pack `packs/meridian_ap/`: `pack.yaml` (clients, documents and how to segment each one, metadata-table keys, paragraphs to skip), `sources.yaml` (14 sources from source_index, ranks per BUILD_PLAN, CM-INF-02 `valid_to: 2027-03-31`, SOP v3.1 `valid_to: 2026-03-31`), `vocabulary.yaml` (23 topics with parameters and value types), `roles.yaml`, `authority.yaml`, `risk.yaml`.
- `app/core/pack.py`: typed pack loader with validation of statuses, kinds and client scopes.
- `app/ingest/docx_parser.py`: walks the .docx body in document order (so tables stay next to their headings), and renders lists and tables as Markdown.
- `app/ingest/segmenters.py`, all driven by `pack.yaml` (no Meridian names in engine code):
  - `numbered_sections` (SOPs): one passage per section or subsection (locator `4.2`), a parent passage for sections that only have subsections, and the §14 change table split one passage per row (locator `14`, plus the whole table as the §14 section).
  - `lettered_parts` (desk instructions): steps style gives `Part A` parent + `Part A, step 4`; whole style gives one memo passage `Part C (CM-INF-02)`; table_rows style gives one FAQ passage per row (`Part F`).
  - `transcripts`: `Video 1 [04:30]` turns, interviewer questions joined to the following answer (`Interview 1 [02:30]` cites the answer's timestamp), shadowing bullets as `Shadowing 10:05`.
  - Two-column metadata tables (Recorded, Presenter, Valid until…) go into `sources.meta`, not into passages.
- `app/ingest/passages.py`: stable passage ids (hash of source, locator and occurrence, so ids survive text edits), context headers such as `SOP v4.0 · §4.2 Price tolerance · effective 1 Apr 2026 · status current · all clients`, redaction of passage text, content hash for change detection.
- `app/ingest/loader.py`: upserts sources, passages (inserts new, updates changed, skips unchanged, deletes vanished passages only if no claim cites them) and the 650 vendors. Refuses a vendor sheet with PAN, bank, IFSC or account columns.
- `scripts/ingest_all.py` (`--dry-run`, `--show <source>`).

### Corpus result

128 passages: SOP v4.0 42 (14 top-level sections; 17 subsections; 4 parents; §14 as 1 section + 11 rows), SOP v3.1 12, DI-03 9 (parent + 8 steps), DI-07 7 (parent + 6 steps), 3 memos, FAQ 10, Video 1 9, Video 2 8, Video 3 8, shadowing 9, Interview 1 6, Interview 2 5. 650 vendors.

### Tests (`pytest -q`): 49 passed, 1 skipped

- Leakage: pass.
- Redaction: planted PAN, IFSC, account, phone and email are redacted; business text is untouched.
- LLM gateway (fake client): validated object returned, prompt redacted before sending and in the log, cost computed, second identical call is a cache hit, prompt_version changes the key, refusal raises. **Live test skipped: no `ANTHROPIC_API_KEY` on this machine.**
- Parser (TEST_PLAN level 2): provenance on every passage; 14 top-level SOP sections; FAQ 10; Video 1 9; shadowing 9; interview turn counts equal the non-interviewer turns counted straight from the docx; timestamps exact (`[04:30]`); §14 has 11 rows; parents link children; ids unique and stable across runs; no sensitive strings in any passage; planted values redacted at ingest.
- **Locator coverage: every `gold_source_section` and every `also_valid_sources` locator in the eval set (>35 distinct) exists as a passage.** `Part C` matches `Part C (CM-INF-02)` through the part alias; `8.2 and 11` needs both.
- DB (embedded Postgres, separate `ps07_test` database, real Alembic migration): all tables and the vector extension exist; first ingest = 14 sources, 128 passages, 650 vendors; **re-ingest inserts 0, updates 0, deletes 0, no duplicates**; full-text search finds §4.2 for "price tolerance"; vendor table has no sensitive columns; memo scope is infra only.
- Also checked by hand: `alembic upgrade head`, `downgrade base`, `upgrade head`, and `alembic check` reports no drift; `ruff check` is clean.

### Assumptions and deviations

1. **No Docker on this machine.** `docker-compose.yml` is provided as specified; local runs use `scripts/dev_db.py` (pgserver). Both give Postgres 16 + pgvector.
2. **Temperature 0 is not possible.** `claude-sonnet-5-5` and `claude-haiku-5-5` reject non-default `temperature` (HTTP 400), and forced `tool_choice` too. `llm.structured` uses the API's structured outputs (`messages.parse` with a Pydantic `output_format`) instead of forced tool use, and reproducibility comes from the on-disk cache (CLAUDE.md rule 8). Run-to-run stability (TEST_PLAN level 7) therefore depends on cache hits; a cold cache can vary slightly.
3. Prices used for cost: Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10 per million input / output tokens.
4. Document preambles (title block, "SYNTHETIC" disclaimer, statutory disclaimer, the intro paragraphs of the desk-instruction and transcript files) are not passages. The desk-instruction intro says the FAQ is outdated; that fact is carried by the FAQ's `stale` status and rank instead.
5. Transcript sources have no version in source_index; their passages carry the recorded date only.
6. Schema additions beyond BUILD_PLAN (non-breaking): `sources.label/status_note/valid_to/meta`; `passages.parent_id/ordinal/segment_kind/section_title/speaker/content_hash/meta`; `vendors.state/supply_type`; `notifications.read_at`. Passage ids are strings (stable hashes) rather than serials, so citations survive re-ingestion.
7. `passages.tsv` weights section title (A) above the context header (B) and body (D).

### Open issues for later phases

- **Retrieval (Phase 4):** plain full-text ranking still puts the stale FAQ row first for "price tolerance" (§4.2 is second), and parent passages (`section_parent`, `part`) duplicate their children. Phase 4 should keep parents and stale or superseded sources out of the main evidence (they belong in `older_sources`) and rely on vector + RRF + rerank.
- `embedding` column exists but is empty; filled in Phase 4 with fastembed.
- Live LLM check (Phase 0 acceptance item "a sample llm.structured call … appears redacted in the log") is covered by the fake-client test; run `pytest -m live_llm` once a key is in `.env`.
- The four spec documents (CLAUDE.md, BUILD_PLAN.md, TEST_PLAN.md, DESIGN.md) are not yet in this folder; copy them into the repo root.
