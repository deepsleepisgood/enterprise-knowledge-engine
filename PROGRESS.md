# PROGRESS

Running log of what was built, test results, assumptions and open issues. Newest at the bottom.

## Resume here (keep this block current)

**Status (7 Nov 2026, evening): v2 P0 and P1 committed; P2 and P3 code written and unit/integration-tested offline (141 tests); first live induced-schema build running.** The spec changed to BUILD_PLAN v2 (generic engine); SCOPE.md, CLAUDE.md, BUILD_PLAN.md, TEST_PLAN.md and DESIGN.md are in the repo root. v1 (hand-written pack) is at commit 7add2d0.

**Next actions, in order**
1. **Run the new tests (written, never run):** `pytest -q tests/unit/test_evolve.py tests/integration/test_evolve_db.py`, then the full `pytest -q`. Fix what fails.
2. Rebuild with evolution: `python scripts/build_graph.py --auto-freeze --threads 1` (extraction is cached; evolution makes a few new LLM calls). Check the `schema evolution:` line, the `other:*` share and that `payments.default_term_days` is now bound.
3. Live acceptance: `pytest -m live_llm tests/integration/test_graph_acceptance.py` (it was interrupted before producing results), then `SCENARIO_MODES=induced` and `baseline` for `tests/plugins/test_ap_scenarios.py`; document misses in `reports/scenario_misses_<mode>.md`.
4. PROGRESS entry with live results, commit, stop the dev DB.

**v2 migration plan (phases 0–3 redone)**
- [x] **P0** `app/store/` repository layer (only code touching tables) with `tenant_id` everywhere; new tables (entities, entity_aliases, facts with valid_from/valid_to/recorded_at/retracted_at, schemas, plugin_bindings, escalations, jobs); fresh Alembic baseline; Postgres job queue + `app/worker.py`; `llm.vision`; `tests/test_core_is_generic.py`; bitemporal query test.
- [x] **P1** connectors (upload incl. folders/zip, api text, eml) → blob store + hash dedupe → type sniffing (signature, not extension) → tier-1 parsers to canonical blocks (docx, pdf text layer, xlsx/csv, pptx, html, md/txt, eml, vtt/srt/`[mm:ss] Speaker:`, json) → generic structure inference (`app/ingest/segment.py`) → metadata inference with provenance (`app/ingest/metadata.py`) → version matching/diff (`app/ingest/versions.py`). No hand-written pack at runtime.
- [~] **P2** schema induction (code + offline tests done; live acceptance pending) (`app/graph/induce.py`, `SCHEMA_MODE=induced|baseline`), extraction to entities + facts, entity resolution (fastembed + LLM confirm), authority resolution on related facts only, `store.facts.get_facts(valid_on, known_at)`, `graph.rules.get_rule` via schema synonyms + plug-in bindings.
- [~] **P3** `plugins/ap/` (code + offline tests done; live scenarios pending) (calculators moved from `app/calc`, params extraction, `bindings.yaml`, `roles.yaml`, baseline_schema from the v1 pack, ops loaders) + `app/plugins/` registry and bind step; scenario test under both schema modes.

**Local deviations (documented):** embedded Postgres (pgserver) has `vector` but not `pg_trgm`/`btree_gist`; the migration enables them only when available (Neon has them). Without them: GiST index is on the time range alone, and trigram candidate search falls back to Python string similarity. No LibreOffice on this machine → tier-2 legacy files are stored and flagged `needs_attention`. LLM provider stays NVIDIA NIM until Anthropic keys arrive.

**How to run on this machine (Windows, no Docker)**
- Python: `.venv\Scripts\python.exe` (3.11). DB: `python scripts/dev_db.py start` (embedded Postgres + pgvector; writes `.pgdata/database_url.txt`), `... stop` when done. Then `alembic upgrade head`, `python scripts/ingest_all.py`.
- Tests: `pytest -q` (creates and migrates its own `ps07_test` database). Lint: `ruff check app scripts tests plugins`.
- Web: `cd web && npm run dev` (port 3000); checks: `npx tsc --noEmit`, `npm run lint`, `npm run check:tokens`, `npm run build`. Stop the dev server afterwards (check port 3000: a child `node` process can outlive the task).

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

---

## 2026-11-07 — LLM provider: NVIDIA NIM (user decision), models chosen by probe

The user asked to use NVIDIA NIM keys for now and Anthropic later. This deviates from CLAUDE.md's stack line ("LLMs via the anthropic SDK"); everything else in rule 3 still holds.

### Built
- `app/core/nim.py`: OpenAI-compatible `/chat/completions` client, standard library only (`urllib`). Retries 408/429/5xx and timeouts with backoff 3 s / 10 s / 30 s; timeout `NIM_TIMEOUT_S` (default 300 s).
- `app/core/llm.py` dispatches on `LLM_PROVIDER` (`nim` | `anthropic`). Redaction, cache, JSONL log and the `complete` / `structured` API are unchanged. On NIM:
  - temperature 0 (so CLAUDE.md rule 3 now holds in full on this provider);
  - JSON mode, with the Pydantic JSON Schema in the system prompt;
  - `<think>` blocks and code fences stripped before parsing;
  - Pydantic validation with one corrective retry;
  - `finish_reason=length` raises; `effort` is ignored (Anthropic-only).
- The cache key includes the model id, so switching provider never reuses the other provider's outputs.
- Settings: `LLM_PROVIDER`, `NVIDIA_API_KEY`, `NIM_BASE_URL`, `NIM_TIMEOUT_S`, plus `settings.llm_configured`. `build_graph.py` checks the selected provider's key and takes `--workers N` (parallel extraction; results stay in passage order, so claim keys are stable).
- Live tests are now opt-in: the default `pytest -q` excludes `live_llm`, because with a working key the acceptance test would rebuild the whole graph. Run them with `pytest -m live_llm`.
- `tests/unit/test_llm_nim.py` (7 tests, fake transport): JSON mode, temperature 0, schema in the prompt, redaction before sending, reasoning and fences stripped, corrective retry, failure after the retry, truncation, token logging and the cache.

### Model choice (probe on 7 Nov 2026, same prompt and schema as the real extraction of SOP §4.2)

| Model | Result |
| --- | --- |
| `nvidia/nemotron-3-ultra-550b-a55b` | 47 s; pct_of_line = 1, cap_inr = 500; 6 claims, 6/6 quotes verified → **MODEL_SMART** |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 7 s; correct "different" verdict → **MODEL_FAST** |
| `nvidia/nemotron-3.5-bolt-e4b` | 1 s; correct, but a 4B model; kept as a faster fallback |
| `deepseek-ai/deepseek-v4.1-flash` (user's suggestion) | listed for the key but timed out (> 150 s, no response) on 4 attempts, with and without JSON mode; kept commented out in `.env` |
| `mistralai/mistral-large-4-1t-a52b` | once correct in 70 s, once timed out |
| `moonshotai/kimi-k2.6`, `nvidia/nemotron-3-super-120b-a12b`, `nemotron-nano-3-30b-a3b`, `mistral-large-2-instruct`, `llama-3.1-nemotron-70b-instruct` | HTTP 404: listed but not served for this key |

### Notes
- NIM free-tier cost is recorded as unknown (`cost_usd` = null) because there is no price table for these models; tokens are still logged.
- The NVIDIA key was pasted in chat; it lives only in `.env` (git-ignored). Rotate it on build.nvidia.com after the hackathon.
- Corpus passages sent to NIM are synthetic and redacted before sending, as with Anthropic.

---

## 2026-11-07 — v2 Phase 0: generic bitemporal store, job queue, worker

### Built
- `app/store/` is now the only code that touches tables: `models.py` (all BUILD_PLAN v2 tables, `tenant_id` on every one), `facts.py` (bitemporal `insert`, `retract`, `revise`, `get_facts(subject, attribute, scope, valid_on, known_at)` using `tstzrange @>` so the GiST indexes apply), `entities.py` (deterministic ids, aliases, candidates by trigram or Python similarity plus embedding, owner merge), `episodes.py` (episodes with hash dedupe and confirmation count, sources, passages with change detection and retirement), `kb.py` (schemas, kb versions, changes, conflicts, review items, plug-in bindings), `jobs.py` (enqueue, `FOR UPDATE SKIP LOCKED` claim, retry with backoff 5/30/120 s, failed after the last attempt, stale-job requeue), `base.py` (tenant context var, day/interval helpers).
- **Bitemporal convention:** valid time `[valid_from, valid_to)` and transaction time `[recorded_at, retracted_at)` as timestamptz; a day `d` is stored as `d 00:00 UTC`, a "last day in force" `d` as `valid_to = d+1`. A row is never edited except to close `retracted_at`; a change of belief retracts the live row and inserts a new version with the same `origin_key` (partial unique index on live origin keys). This is what lets `known_at` return what the engine believed on a past date.
- `app/worker.py`: handler registry, `drain()` for scripts/tests, `serve()` with N threads (`python -m app.worker`).
- `app/core/llm.py`: new `vision()` call style (image parts on NIM and Anthropic; cache key includes image hashes; `model="vision"` → `MODEL_VISION` or `MODEL_SMART`).
- Fresh Alembic baseline `0001_generic_bitemporal_schema` (v1 migrations removed; the dev database is disposable). Extensions `pg_trgm`/`btree_gist` and their indexes are created only when available. `alembic check` is clean (hand-made indexes excluded in `migrations/env.py`).
- Settings: `TENANT_ID`, `SCHEMA_MODE`, `PLUGINS`, `BLOB_DIR`, `MODEL_VISION`, `WORKER_THREADS`; `PACK` removed.
- Moved: `app/calc/` → `plugins/ap/calc/`; the v1 pack → `plugins/ap/` (`roles.yaml`, `calculators.yaml`) and `plugins/ap/baseline_schema/` (vocabulary, authority, risk, sources, extraction examples, and the old `v1_pack.yaml` for reference). Deleted the pack-bound v1 modules (ingest loader/segmenters, graph store/extract/rules, scripts); they are in git at 7add2d0.
- Core made generic: redaction and the text comparer no longer name a currency (any Unicode currency symbol).

### Tests
- `pytest -q`: **49 passed**. New: `tests/test_core_is_generic.py` (no Meridian/Arvana/tax terms/rupee sign in `app/`, no `plugins` imports), `tests/integration/test_store_db.py` (every table has `tenant_id`; GiST indexes exist; hand-inserted fact: `known_at` before recording → nothing, `valid_on` 1 Mar 2026 → the old value closed on 31 Mar 2026, today → the new value, `known_at` before the change → the old value with an open interval; rows only grow; scope filter; dedupe; tenant isolation; aliases and merge; kb version; job through the worker; retry then fail; 4 threads never double-claim 20 jobs; stale job requeued), vision call with a fake transport.
- Live: `llm.structured` on NIM returned a validated object; the log line shows `[REDACTED_PAN]` and `[REDACTED_PHONE]`.
- Parked until their phase (`collect_ignore` in `tests/conftest.py`): locator coverage (P1), resolve unit tests (P2), AP plug-in tests (P3).
- Note: `logs/llm_calls.jsonl` has one corrupt line from before the write lock (v1 run); readers should skip bad lines.

---

## 2026-11-07 — v2 Phase 1: connectors and universal ingestion (no hand-written pack)

### Built
- **Connectors** (`app/ingest/connectors/`): files, folders (recursive) and zips (one episode per member); raw text (`from_text`, the API path); `.eml` (sender and Date header become `sender`/`received_at`; each attachment becomes its own episode). All produce `EpisodeIn`.
- **Intake** (`app/ingest/intake.py`): original kept in `BLOB_DIR/<tenant>/<hash>`; sha256 dedupe (a duplicate adds a confirmation to the first episode); type detection by signature (`app/ingest/detect.py`; libmagic used when present); queues `parse_episode`.
- **Parser cascade** (`app/ingest/parsers/`), all emitting the canonical block list (`app/ingest/blocks.py`): docx (styles, list numbering format -> ordered vs bullet, bold and font size, core properties), xlsx/csv (sheets -> tables; prose sheets -> paragraphs), pptx (slides, tables, speaker notes), PDF text layer (font-size and bold headings, bullets, header/footer removal, PyMuPDF tables, two-column reading order), HTML (nav/header/footer stripped), Markdown and text, eml (quoted replies and signatures stripped), VTT/SRT (speakers, merged cues), JSON chat exports. Timestamped lines become `turn` blocks in any format. Quality score (junk ratio, letter ratio, characters per page, broken tokens, structure); below 0.5 a PDF or image escalates to the vision tier (only when `MODEL_VISION` is set), otherwise the episode is `needs_attention`. Legacy Office without LibreOffice -> tier 5, flagged. Native parsing is serialised with a lock (python-docx/lxml is not thread-safe; parallel parsing corrupted two episodes in a first run).
- **Structure inference** (`app/ingest/segment.py`): headings from styles, tags and slides; without them, from numbering (`4.2 ...`, `Part C ...`) and visual signals, with an optional MODEL_FAST structure-repair hook; sliding windows as the last resort. **Packs are split generically:** when two or more top-level sections open with a key-value header table (keys from a generic vocabulary: version, effective, issued, owner, from, recorded, valid until ...), each top-level section is its own document. Passages: leaf sections; parent passages for sections with children; ordered lists -> `<label>, step N` (bullets stay in the section); tables with 6+ data rows -> one passage per row with the header; spreadsheets -> records (`<sheet> row N`); turns with question-to-answer joining; long sections split at paragraphs. Locators come from heading labels (`4.2`, `Part A, step 4`, `Video 1 [04:30]`, `Expert interview 1 [00:42]`, `Shadowing notes 10:05`).
- **Metadata inference** (`app/ingest/metadata.py`): header table -> title, version, ref, effective/issued/updated/recorded dates (month precision for "February 2026"), valid until, owner, supersedes, applies-to; then heading and first-page text, file name, email Date, file modified time, ingestion time (date precedence as in SCOPE.md). MODEL_FAST classifier (`docmeta-v1`) for doc type, short label, client scope, owner, status and a practice flag. Generic overrides: the document's own type words in its heading ("memo", "FAQ", "interview", "desk instruction") beat the classifier; its own reference code (else its section label) is the short label; a scope that names several organisations is `all`. Every field stores origin and confidence in `sources.meta_provenance`; fields under 0.7 create a `metadata` review item.
- **Versions** (`app/ingest/versions.py`): same type and same ref, or titles at least 0.85 similar; the newer (version, else date) supersedes the older in either arrival order; the older gets `status superseded` and `valid_until = newer.dated - 1 day`; identical passages are marked `carried_from` for reuse by extraction; removed passages become a `retire` review item; context headers of the older source are refreshed.
- **Pipeline** (`app/ingest/pipeline.py`, job `parse_episode`): parse -> structure -> documents -> metadata (parallel per document) -> passages (redacted, with context headers like `AP SOP v4.0 · §4.2 Price tolerance · effective 1 Apr 2026 · status current · all clients`) -> store -> version links -> queue `extract_episode`.
- `scripts/ingest_all.py`: uploads `data/raw` and `data/ops` and drains the parse jobs.

### Corpus result (live classifier on NIM)
4 docx + the operations workbook -> 5 episodes, **15 documents**, 63 s end to end: AP SOP v4.0 (sop, 76 passages), AP SOP v3.1 (sop, **superseded**, valid until 31 Mar 2026), DI-03 and DI-07 (work_instruction, steps), CM-INF-02 / CM-PHA-01 / CM-RET-03 (memo, scoped to their client; CM-INF-02 valid until 31 Mar 2027), Part F FAQ (faq, **stale**, 10 rows), Video 1-3 (training; Video 2 stale), Shadowing notes (observation, record), Expert interview 1-2 (interview, record), AP operations workbook (spreadsheet, 11,809 records).

### Tests: `pytest -q` 90 passed (+1 live)
- Locator coverage (rewritten for the generic segmenter): every eval locator exists. Matching normalises `§`, drops parentheticals, and lets a locator label carry extra heading words (`Interview 1 [02:30]` = `Expert interview 1 [02:30]`, `Shadowing 10:05` = `Shadowing notes 10:05`); numbers and timestamps must match exactly. **Assumption:** citation scoring in Phase 5 uses the same rule, and a citation of `8.2, step 3` counts for gold `8.2` (it cites inside the gold section).
- Parser unit tests per format (TEST_PLAN level 2 list): docx with and without heading styles, PDF headings by font size, two-column order, PDF table, near-empty PDF held, xlsx multi-sheet records, pptx with notes, HTML boilerplate, eml reply and signature stripping, VTT speakers with question joining, unknown binary flagged, legacy Office without LibreOffice flagged, windows for unstructured text, detection by content.
- Segment unit tests: labels, metadata-table detection, pack splitting, steps vs bullets, row split, transcript joining, structure-repair hook, dates, metadata provenance.
- DB integration: SOP v4.0 has 14 top-level sections and 17+ subsections; FAQ 10 rows; Video 1 9 turns; shadowing 9 notes; interview turn counts equal the answers counted from the docx; every passage has source, locator, context header and status; re-ingest creates nothing (duplicates add confirmations); v3.1 superseded with `valid_until` 31 Mar 2026 even when it arrives after v4.0; planted PAN, account and phone redacted; email with attachment -> two episodes, sender and date from headers, signature stripped; unknown binary -> `needs_attention`; parsing the 4 documents takes about 4 s.
- **Metadata vs hand-copied index (live): 78/84 = 92.9%** (target 90%). Misses: the three memos' version (index says 1.0; the documents state none), FAQ owner (not stated), Video 3 and shadowing owner (the documents name the presenter or observer, the index names the owning team).

### Open issues
- Spreadsheet records are passages (cheap, no LLM). Phase 2 must not send 11,809 records through the LLM extractor: records get deterministic handling or triage. The operations workbook is also the AP plug-in's ERP data (P3 loads vendors and invoices from it).
- No LibreOffice and no vision model on this machine: tiers 2 and 3 are wired but only exercised by tests that check they flag.

---

## 2026-11-07 — Schema evolution (fix for induced-schema gaps) — code written, tests NOT yet run

**Why.** The first full induced build placed only part of the facts in the schema: 201 of 266 attribute names in use were improvised `other:*` keys. Three causes: topics induction never sampled (credit and debit notes, month-end, exception owners, match types, the default payment term, which left `payments.default_term_days` unbound), document metadata extracted as facts, and near-misses where a fitting attribute existed. Chosen fix (user decision, option 3 of 4): close the loop after extraction instead of narrowing the extraction prompt, because it fixes both missing topics and near-misses, it is how new topics in later documents get into the schema (SCOPE.md 3.5 / BUILD_PLAN 2a), and it needs no re-extraction.

**Built** (`app/graph/evolve.py`, wired in `app/graph/pipeline.py` and `scripts/build_graph.py`):
- Group live `other:*` facts by proposed name; merge names whose embeddings are ≥0.88 similar and whose value types are compatible.
- Map each group to an existing attribute: score = 0.7·cosine + 0.3·word overlap (words only without embeddings), compatible value type required; ≥0.90 maps directly, otherwise MODEL_FAST picks among the top 5 or says none (`evolve-v1`, cached).
- Propose: unmatched groups go to MODEL_SMART in batches of 40, which names an attribute under an existing or a new topic, or marks the group `keep=false` (document metadata, one-off statements). Keys naming versions/time, scope words ("general_") or `other` are refused in code.
- Save schema v(n+1) as a draft plus a `schema` review item listing new topics, new attributes, remaps and skipped groups. `evolve_schema(auto_freeze=True)` (build script with `--auto-freeze`, tests) freezes it and re-keys at once; otherwise `apply_schema(version, by)` does that when the owner approves. A second evolution waits while a draft is open.
- Re-keying (`evolve.apply`) retracts each fact and inserts a new version under the new attribute (topic-level facts move to the new topic's entity; facts about a named entity keep their subject), then runs authority resolution on the groups they joined, bumps `kb_version` and records a change, all in one transaction. History is kept: a `known_at` query before the evolution still returns the `other:*` row.
- Continuous ingestion: an `extract_episode` job that produced unplaced facts queues one `evolve_schema` job (owner review, not auto-freeze) in induced mode. Baseline mode never evolves.
- Store helpers: `facts.live_with_attribute_prefix`, `kb.get_schema`, `kb.decide_review_item`.

**Tests written but not run (by request):** `tests/unit/test_evolve.py` (grouping, type compatibility, key cleaning, map/propose/skip with a fake LLM and embedding) and `tests/integration/test_evolve_db.py` (auto-freeze re-keys and keeps history; owner-review path; topic facts move to the new topic entity). Lint and import checks pass; all job handlers register.
