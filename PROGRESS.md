# PROGRESS

Running log of what was built, test results, assumptions and open issues. Newest at the bottom.

## Resume here (keep this block current)

**Status (7 Nov 2026):** Phases 0, 1 done. Phase 2 code done and tested on hand-built claims; **the real graph has not been built yet: needs `ANTHROPIC_API_KEY` in `.env`**. Phase 8 steps 1–2 (web shell + Ask page on fixtures) done.

**Next actions, in order**
1. Put `ANTHROPIC_API_KEY` in `.env`. Run `python scripts/build_graph.py --dry-run` (expect ~121 passages, ~$1.25), then `python scripts/build_graph.py`.
2. Run `pytest -q -m live_llm` → the Phase 2 acceptance tests in `tests/integration/test_graph_acceptance.py` must pass. Inspect the printed claims-per-topic summary and quotes that weren't found verbatim; fix the prompt (bump `PROMPT_VERSION` in `app/graph/extract.py`) if needed.
3. Then Phase 3 (calculators reading thresholds through `app/graph/rules.get_rule`).

**How to run on this machine (Windows, no Docker)**
- Python: `.venv\Scripts\python.exe` (3.11). DB: `python scripts/dev_db.py start` (embedded Postgres + pgvector; writes `.pgdata/database_url.txt`), `... stop` when done. Then `alembic upgrade head`, `python scripts/ingest_all.py`.
- Tests: `pytest -q` (creates and migrates its own `ps07_test` database). Lint: `ruff check app scripts tests`.
- Web: `cd web && npm run dev` (port 3000); checks: `npx tsc --noEmit`, `npm run lint`, `npm run check:tokens`, `npm run build`. Stop the dev server afterwards (check port 3000: a child `node` process can outlive the task).
- The spec documents (CLAUDE.md, BUILD_PLAN.md, TEST_PLAN.md, DESIGN.md) must be in the repo root; they were provided in chat and are **not yet in the folder**.

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

---

## 2026-11-07 — Phase 8, steps 1–2 (web shell + Ask page on fixtures)

Started early, as BUILD_PLAN allows ("run the UI in parallel … against fixture answer cards").

### Built (`web/`)
- Next.js 14.2.35 (App Router) + TypeScript (strict) + Tailwind 3.4 + lucide-react; versions pinned exactly.
- Design tokens from DESIGN.md §2 in `tailwind.config.ts` only; fonts Hanken Grotesk, Inter, JetBrains Mono via `next/font/google`.
- Shell: 64px left rail (brand glyph, nav, avatar with Processor / Process owner switch in localStorage) → fixed top bar with menu below `md`; main column `max-w-[760px]`; 320/360px sticky right rail → stacks below the answer below `lg`. Owner-only nav items (Conflicts, Review, Analytics) are hidden for processors.
- Ask page: change banner with "Got it", eyebrow with client chip and `kb v42`, question heading, Answer / Sources / History tabs, source-chip strip with `+N` overflow, status pill, answer text with rose superscript citation chips, decision row, working card, current-vs-older card, expert tip card, not-covered route card, Related list, composer (auto-grow textarea, invoice picker, client chip, rose send button), loading skeleton with "Checking SOP v4.0, client memos and transcripts…".
- Right rail: invoice context card (when an invoice is attached), sources with counts, active card in `rose-tint`/`rose-line` with a filled badge, older sources, "Show all N sources", and a source drawer (full quote, file, locator, status, passage id).
- `lib/types.ts` mirrors the Phase 4 answer-card schema exactly; `lib/api.ts` calls the API when `NEXT_PUBLIC_API_BASE_URL` is set and otherwise runs in a labelled **demo mode** over `web/fixtures/`.
- Fixtures: T1 (price tolerance, older sources), T5 (₹395 vs ₹400 × 500 → working card, PRICE_VAR), T8 (canteen subsidy → unsupported, route to HR / Admin), T3 (Pharma excipients → conflict with the 2023 FAQ, expert tip). Passage ids and quotes are taken from the real parsed corpus; invoice rows from the operations workbook. No eval content was used.
- Placeholder pages for Changes, Conflicts, Review queue, Expert capture and Analytics in the same shell.
- `npm run check:tokens`: fails on any hex colour outside `tailwind.config.ts` (checked with a planted value).

### Verified
- `tsc --noEmit` clean, `next lint` clean, token check passes, `next build` succeeds (Ask page 102 kB first load).
- In the browser (Playwright MCP) at 1440px: T1, T5 and T8 render as specified. Hovering inline citation 2 activates source card 2 only; the rail scrolls, the page does not. The source drawer opens with focus on Close and closes on Escape. No console errors or warnings.
- At 390px: top bar replaces the rail, no horizontal scroll (`scrollWidth` 375), the chip strip scrolls, the current-vs-older card stacks into Now / Before, sources stack below the answer.
- Bugs found and fixed while checking: `scrollIntoView` scrolled the whole window (now scrolls only the rail); the screen-reader label inside document glyphs escaped the scrolling chip strip and widened the page to 571px at 390px; citation superscripts sat too high with a gap.
- `pytest -q` still 49 passed / 1 skipped (the leakage test now also scans `web/`).

### Not done yet / open
- Playwright test files under `web/tests/` and a Lighthouse run are not in the repo yet; the checks above were done by hand through the browser tools.
- The Changes, Conflicts, Review, Capture and Analytics pages are placeholders (Phase 8 step 4 and later phases).
- The source drawer shows the citation's quote; it should load the full passage from `GET /passages/{id}` once the API exists.
- T8 routes to "HR / Admin team" (added to `roles.yaml` as a non-AP role). Change it if the team prefers routing to the Team Lead.

---

## 2026-11-07 — Phase 2 (claims and the authority graph): code complete, graph build pending an API key

### Built
- Migration `0002` (additive): `claims.origin_key` (unique; a stable key so a rebuild updates rows in place) and `claims.meta`; unique `(claim_a, claim_b, kind)` on conflicts.
- `app/graph/schema.py`: the `ExtractionResult` schema for structured outputs, plus `ClaimRec`, `ConflictRec` and `ResolveResult`.
- `app/graph/extract.py`: one `MODEL_SMART` call per leaf passage (`prompt_version extract-v1`). The model proposes and code checks:
  - topic and parameter must be in the vocabulary (otherwise kept as `other` / `other_<name>` with the proposal recorded);
  - money is normalised to the pack currency using `extraction.yaml` units (lakh, crore);
  - interview and shadowing passages always give `practice` claims;
  - memo passages take the memo's client scope;
  - each quote is checked as a verbatim substring of its passage (`meta.quote_verified`).
  - Domain guidance and few-shot examples live in the new `packs/meridian_ap/extraction.yaml` (written from SOP text), so engine code has no rupee values.
- `app/graph/compare.py`: deterministic comparison (numbers with the same unit, equal lists, normalised text); anything it can't decide goes to a cached `MODEL_FAST` judge (`compare-v1`).
- `app/graph/resolve.py`: pure function implementing the six precedence rules:
  - claims are bucketed by client, so a memo overrides only its own client;
  - the lowest rank among `current` sources wins, and its invalid_at is the source's valid_to;
  - agreeing claims become `corroborating`;
  - disagreeing claims become `superseded`, with invalid_at the day before the winner took effect;
  - two current sources that disagree open a `value` conflict;
  - practice claims stay `current` as tips, and open `practice_vs_rule` only on a clear contradiction.
- `app/graph/store.py`: loads leaf passages only (parents would double every claim), and persists in one transaction:
  - upserts by origin_key and sets `expired_at` on superseded claims;
  - **retires (never deletes)** corpus claims that a rebuild no longer extracts;
  - links `supersedes_id`, inserts unique conflicts, and bumps `kb_versions` only when something changed.
- `app/graph/rules.py`: `get_rule(session, topic, parameter, client, as_of, known_at)` → `RuleValue` (value, claim id, citation such as `SOP v4.0 §4.2`). Behaviour:
  - client-specific first, then the general rule;
  - expiry applied on read;
  - an `as_of` (audit) query ranks by document kind from `authority.yaml` `kind_precedence`;
  - **raises `RuleNotFound`, never defaults**.
  - Also `older_claims()` (for `older_sources`) and `expert_tips()`.
- `scripts/build_graph.py`: `--dry-run` (passage count and cost estimate, no LLM calls), `--limit N`, and a full build printing claims per topic, current/superseded counts and unverified quotes.

### Tests: 81 passed, 15 skipped
- `tests/unit/test_resolve.py` (10, hand-built claims mirroring the corpus):
  - v4.0 beats v3.1 and the FAQ (invalid_at 31 Mar 2026), and Video 1 corroborates;
  - the memo overrides for Infra only and carries its expiry;
  - the FAQ excipient claim is superseded by CM-PHA-01 (invalid_at 1 Jan 2026);
  - Video 2's staleness is per claim (no-PAN 20% corroborates; the ₹10 crore claim is superseded);
  - practice never overrides; two current sources that disagree open a conflict; a stale-only claim is `pending`.
- `tests/unit/test_extract.py` (10, fake LLM): money normalisation, quote verification, practice forcing, memo scope, unknown vocabulary, stable keys, prompt contents, the LLM judge called only when the deterministic check can't decide.
- `tests/integration/test_graph_db.py` (11, Postgres): first persist bumps kb_version; current rule and citation; superseded rows kept with dates and `supersedes_id`; `as_of` 1 Mar 2026 returns v3.1; memo current for Infra only and gone on 1 Apr 2027 (no tolerance); `known_at` before ingestion returns nothing; missing rule raises; tips are not rules; rebuild idempotent; missing claims retired not deleted; conflicts unique.
- **Skipped until a key is set:** `tests/integration/test_graph_acceptance.py`, the real Phase 2 acceptance:
  - for each of the 11 rows of §14 (read from the parsed SOP), a current v4.0 claim exists and the v3.1 claims are superseded with invalid_at 31 Mar 2026;
  - CM-INF-02 is current for Infra only and expired on 1 Apr 2027;
  - the FAQ excipient claim is superseded by CM-PHA-01.

### Assumptions and decisions
1. Claims are bucketed by (topic, parameter, client). Materials and categories are stored in `scope` and `condition`, not in the grouping key, so the FAQ's "Infra 10% on cement and steel" competes with the memo's "5% on four materials".
2. A bucket with no claim from a `current` source gets status `pending` (never shown as current). Example: an FAQ-only statement.
3. When two current sources are worded differently and the check can't tell, the lower-ranked one is `corroborating`; the Phase 6 conflict scan judges these.
4. invalid_at is the last valid day (inclusive): SOP v3.1 claims → 31 Mar 2026; the CM-INF-02 claim → 31 Mar 2027.
5. `expired_at` (transaction time) is set when a claim is superseded or retired. `known_at` queries use `created_at` and `expired_at`; `as_of` queries use `valid_at` and `invalid_at`.
6. A list that is a subset of another counts as unknown, not as agreement ("only APIs" vs "APIs and excipients" is a contradiction), so it is decided by the judge or by authority.
