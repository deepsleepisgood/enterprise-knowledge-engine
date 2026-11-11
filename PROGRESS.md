# PROGRESS

Running log of what was built, test results, assumptions and open issues. Newest at the bottom.

## Resume here (keep this block current)

**Status (11 Nov 2026, 14:20): Phase 9 deployed for testing (Vercel + Neon + this laptop via Cloudflare tunnel; demo stopped). Tests paused for the night; code changes since the last commit are NOT committed.**

Results so far (NVIDIA NIM, Neon): eval 157/160 (98.1%; dev 100%, holdout 95.3%; citations 98.1%; p50 36 s); replay 22/22, idempotent; second company 10/10 (after the uploaded-.eml filename fix); UI gate 6/6; intake 11/12; privacy grep 0 hits; format invariance md 0.99, html 0.99, flat docx 0.92, pdf 0.88 (was 0.65), eml 0.77 (was 0.61), xlsx 0.00 (fix since made, not yet rerun). Conflict questions: 0/23 present an old rule as current; 2/23 (Q021, Q062, holdout, examined with the user's consent) name an old value while correcting it.

Uncommitted changes since the last commit: eval runner survives judge errors and has `--ids`; outdated metric fix ("60 days"); answer-v8 prompt; router route-v5 reads dates asked about in words (as_of); support check sees source in-force tags; search runs while the router runs (`early_retrieval`); uploaded .eml keeps its file name; PDF "a | b" text tables; pipe tables in plain text/email; numbered section titles kept in plain text; header table under a leading caption row or under the first of several headings (xlsx).

**Next actions, in order**
1. Rerun format invariance for xlsx and eml (`python scripts/run_format_invariance.py --no-scenarios --variants xlsx,eml`), then `python scripts/run_second_corpus.py` (parser changes touch its xlsx/eml/pdf).
2. Full `pytest -q`, then the full eval on the final code (`run_eval.py --split all --workers 2`, DATABASE_URL=Neon) and the 6 fresh conflict questions (scratchpad script `fresh_conflicts.py`, copy into scripts/ if kept).
3. Build the Replay button on the Sources page (user approved; after the usage limit resets).
4. Not yet measured for gate A: entity-resolution F1, induced vs baseline schema, conflict scan on Neon, T2-T4/T6/T7/T9/T11 by hand on the public URL.
5. Decide the demo LLM: Claude is faster (p50 14 s on 10 Nov) but only about $1.47 credit is left; NIM p50 36 s. Retrieval itself is 4.5-5.5 s on this laptop (reranker on CPU ~3 s).
6. PROGRESS entry, one-page MVP note, commit (when the user asks), restart `run_public.ps1`.

**Never:** sleep the laptop with tests running (DNS fails, runs hang); look at holdout failures beyond Q021/Q062.

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


---

## 2026-11-08 — Testing P2-P4 fixes, Phase 4 (answer pipeline), Phase 5 (evaluation harness)

**Evolution verified.** Unit + DB tests (7) pass after one real fix: evolution now waits while a newer draft schema is open (`kb.latest_schema`). Rebuild: schema v2 frozen (15 new topics, 145 remaps), improvised `other:*` facts 201 -> 46 (the rest is document metadata, correctly skipped), 22/22 plug-in parameters bound.

**Phase 4 built** (`app/answer/`): embedding index (passages, facts, entities; `index_embeddings` job); hybrid retrieval (full-text OR-query + pgvector, RRF, `BAAI/bge-reranker-base` cross-encoder, keep 6) filtered to sources in force on the day asked; graph context from linked entities (alias + embedding) one hop out plus facts of the kept passages; router over plug-in calculators; closed-book generation with per-sentence passage ids; verifier (quote occurs, numbers grounded, no value not in force, support check) with one retry, unverified drafts hidden from processors; answer card per web/lib/types.ts with older sources, expert tip (practice sources only), routing to plug-in roles; answers_log; escalation, report-wrong, expert reply as an `expert_answer` episode, re-ask after publish.

**Fixes found by the live smoke tests** (each covered by a test):
- Reasoning models on NIM made answers take 45-260 s. Gateway now takes `thinking=False` (NIM `chat_template_kwargs.enable_thinking`), used on the answer path: p50 ~10 s. `ROUTER_MODEL=smart` in the local .env (the fast model routes badly without reasoning).
- Calculator inputs hallucinated from the prompt's worked example, and a crore read as a lakh: calculators now run only when the question has figures and every numeric input comes from the question with the unit written next to it.
- Complementary list values ("Tuesday", "Friday", "Tuesday and Friday" from one SOP) were resolved as a conflict: the widest list now wins and parts corroborate (T7 now Friday 14 Aug).
- A binding pointed at an attribute with nothing in force (e-invoice threshold): binding now prefers attributes with a rule in force and shows their values to the LLM.
- Induced ranking had ties (latest-wins fallback picked DI-03 over SOP v4.0) and a client-named topic (`client_specific_rules.arvana_infra_*`): ranks are now strict by listed order; topics and attributes named after a client scope are dropped.
- Older sources were noisy (exception-code lists): only versions of what the answer cites, no self-supersession, no item lists.
- `build_graph.py` silently re-extracted everything after a schema change (the vocabulary is in the extraction prompt): it now extracts only new episodes unless `--reextract`; `--resolve-only` re-runs authority resolution without extraction.

**Live smoke on the dev graph (before the last fixes):** T1, as-of 1 Mar 2026 (v3.1 values), T2 (after unit fix), T5, T6, T7 (after list fix), T8 correct and verified; T3 cites CM-PHA-01 (FAQ flag to check); T4 cites SOP 4.6 and Interview 1 [02:30]. p50 9.9 s.

**Phase 5 built:** `evaluation/` (split: grouped duplicates, stratified 60/40, seed 7, `eval/split.csv`; deterministic scenario grading shared with the scenario test; citation strict/lenient per TEST_PLAN locator rules; outdated answers on the current-rule part only; LLM judge with `eval/judge/prompt.md` and calibration with agreement + Cohen's kappa; ablation configs A naive RAG, B whole corpus, C + authority layer, D full system; per-question tokens/cost via LLM trace tags; reports with the 15 worst and failure causes). Runners: `run_replay.py` (22 probes in `eval/replay_probes.csv` from SOP 14 and a synthetic Infra email), `run_second_corpus.py` (Kestrel Freight HR corpus in six formats, no plug-ins), `run_format_invariance.py` + `render_variants.py` (eight SOP variants). Smoke: 2 dev conflict questions correct with strict citations; ablation paths A-D run.

**Second company (TEST_PLAN level 16): 10/10** (`reports/second_corpus_20261108.md`), no plug-ins, induced schema accepted unedited. Three runs: 3/10 -> 8/10 -> 10/10. Fixes, all generic (AP corpus metadata unchanged):
- `Key: value` lines before the first heading (PDF, Markdown) are read as header fields; `Effective:`/`Last reviewed:` take a colon; an uploaded .eml uses its Date header (the replay email now dates 2 Nov). Before, v2 PDF/FAQ/email were dated by ingestion time and so not in force on the day asked.
- Sheets of <= 30 rows are one leaf passage holding the whole table (extracted, retrievable); large exports stay records. The AP 6-row sheet is now searchable too.
- The support check skips sentences that restate their evidence (90%+ words, all negations and numbers): the fast model rejected a verbatim sentence.
- A number missing from a sentence's citations is attached to the in-force evidence passage that states it, before verification.
- H04 gold accepts the entitlement table as well as v2 (v2 points to the table; the answer gave the grade split).

**Live P2-P4 (8 Nov):** first run 62/110; after fixes 104/110 (`reports/live_p2_p4_rerun.log`). Scenarios 90/92: Q092 is an eval-set defect (the question's rounded invoice price gives excess 100 < limit 120; gold 132 uses an unrounded price), Q112 hit a NIM 429 during the run. The other four (Infra memo rule, T3 FAQ flag, T4 tip, T7 date serialisation) were fixed and re-checked on the same test graph: all pass. Fixes: scenario excess graded to the stated price precision; PAN absence and unwritten agreements must be stated; one-percentage rule text yields its number, 'none' reads 0; ties go to where a document first states a rule; a value deferring to another source does not beat it and rule lookup follows it for that client; tips ordered by rerank score; cards list sources the conflict scan found disagreeing.

**Phase 6 conflict scan:** `app/graph/conflicts.py`, run after every build (`build_graph.py`, test build) and by `scripts/conflict_report.py --score`. Recall 12/15 on the whole graph and 12/15 with SOP v4.0 14 excluded; authoritative right 11/12 (C15: the key names v4.0 7, the scan reports v3.1's self-contradiction). Missed C03 (FAQ price tolerance on cement vs memo quantity tolerance), C07, C11. 46 extra conflicts to label for precision (`reports/conflicts_20261108_extra.csv`). C14 matched on a weak pair (exception review) rather than the cut-off change.

**Open issues:** live acceptance and full eval numbers pending; T11 needs Phase 9 governance (expert replies held for the owner); NIM cost is not priced (cost_usd 0); `bge-reranker-base` is 1 GB (watch memory on the deploy host); schema v2 has some value-in-key attributes and a near-duplicate default-payment-term pair.

## 2026-11-08 — Phase 7 (API) and conflict scan v2

### Phase 7: API (`app/api/`, `uvicorn app.api.main:app --port 8000`, docs at `/docs`)

Every BUILD_PLAN endpoint, as thin routers over the same store, answer and graph functions the scripts and worker use: `POST /ask`; `POST /episodes` (text or base64 .eml), `POST /episodes/upload` (files, zips), `GET /episodes[/{id}[/original]]`; `GET/PUT /schema`, `POST /schema/freeze`; `GET /entities[/{id}[/timeline]]`, `POST /entities/merge`, `POST /entities/{id}/split` (501: cut line); `GET /facts` (`valid_on`, `known_at`); `GET /plugins`, `GET /bindings`, `PUT /bindings/{id}`, `POST /calculate/{plugin}/{family}`; `GET /context`, `GET /invoices`, `GET /scopes`; `GET /changes`, `POST /changes/{id}/ack`; `GET /review-queue`, `POST /review/{id}` (`row_version`, 409); `POST/GET /escalations`, `/reply`, `/close`; `POST /answers/{id}/report`; `POST /conflict-scan` (queued as worker job `conflict_scan`), `GET /conflicts`, `POST /conflicts/{id}` (resolve/dismiss); `GET /passages/{id}`; `GET /version`, `GET /health`.

- Tenant from `X-Tenant` (else TENANT_ID), set by an ASGI middleware for the whole request. Every response carries `X-KB-Version`; object bodies also `kb_version` (lists stay lists: the web client reads them as arrays). Reads use one REPEATABLE READ, read-only snapshot. CORS: localhost:3000 and `*.vercel.app` (`CORS_ORIGINS`, `CORS_ORIGIN_REGEX`), `X-KB-Version` exposed.
- AP specifics stay in the plug-in: new hooks `invoice_search` and `context` in `plugins/ap/plugin.yaml`; the core calls `registry.hooks(...)`. `/ask` with `invoice_id` takes the invoice's client (mapped onto a rule scope: "Arvana Infra Projects Ltd" -> "Arvana Infra Projects") and returns `invoice_context` on the card.
- `/scopes` lists client scopes rules are actually scoped to (`facts.scope_values`), not every entity typed `client` (extraction had typed "client CFO", "Client QA" as clients).
- Review decisions are recorded with the optimistic lock; publishing their effects is Phase 9.
- Tests: `tests/integration/test_api_db.py` (14) covers every endpoint on the leave-policy graph with fake LLM: answers and as-of, intake and dedupe, timeline with superseded versions kept, merge, calculator errors (422, never a default), change feed and acks, review 409s, escalation reply/close/report, conflict queue/list/status, tenant isolation, CORS, OpenAPI. Full suite 206 passed.
- Live check (uvicorn on the dev graph): `/ask` T1 answered with SOP v4.0 4.2 and 14 (2 min 17 s while the conflict scan held the NIM rate budget; ~10 s normally); `/passages`, timeline (2% superseded -> 1%), `/facts?valid_on=2025-06-01` (2%), `/invoices`, `/context`, `/docs` all correct.

Bugs the API work exposed and fixed:
- `get_source`, `get_passage` and `entities.get` did not check the tenant (a known id from another tenant was readable). Fixed in the store.
- The AP operations loader wrote NaN into JSONB for blank cells (Postgres rejects it), so vendors and invoices never loaded; the hook job had also run before the hook was declared. Cells are now cleaned per record (pandas re-infers a None column as NaN); dev DB reloaded: 650 vendors, 9,000 invoices. Test: `tests/plugins/test_ops_loader.py`.
- Conflicts piled up across scans (77 + new, never closed). Scans now upsert (an owner's resolve/dismiss survives a rescan) and a complete scan marks open conflicts it no longer finds `cleared` (kept, not deleted).

**Not in the MVP:** no authentication (anyone with the URL can call write endpoints: needs at least a shared key before the public deploy); entity split; SSE `/stream` (Phase 11).

### Conflict scan v2 (`conflict-v2`): recall 14/15 both ways (was 12/15)

`scripts/conflict_report.py --score` on the dev graph: **14/15 with and 14/15 without SOP v4.0 14; authoritative source right 13/14; extras to label 36 (was 46) and 28 without the change table.** Report: `reports/conflicts_20261108.md`. Changes, all generic:
- A shorter list from an outdated document (superseded or stale source, or a non-current fact) is no longer settled as "narrower" without a model: the judge reads it (C07: one approver in v3.1 vs two in v4.0).
- The judge sees each fact's source passage, not only the extractor's paraphrase, and is told parameter names can be imprecise.
- When a neighbour finds the passage stating a rule, the outdated fact is also compared with that passage's numeric facts in the same unit (the matching number can sit in a sibling fact).
- Judge calls run 4 at a time through the gateway's rate limiter (the scan was serial: 34 min for 168 judgements).
- Scorer (test code): when several known conflicts share the same sections, ties on topic words are broken by the values each one names (C11's "45 vs 60 days" had been credited to C08 "Payment runs").

Still missed: **C03**. The FAQ row ("Infra cement over-invoiced by 6%? ... 10% tolerance on cement and steel") was extracted as a *price* tolerance and the memo's 5% is a *quantity* tolerance; the judge calls them unrelated even with both passages. The FAQ wording is ambiguous; not tuned further to avoid fitting one case. C14 now has the real cut-off pair (third-last vs second-last working day); the scorer's listed match is a weaker pair from the same sections (accrual restated), which is also one of the extras to label. One judge call failed (NIM) and stayed undecided.

## 2026-11-08 — Phase 8: web app wired to the API, every page built

**Run it:** API `uvicorn app.api.main:app --port 8000`, worker `python -m app.worker`, web `cd web && npm run dev` with `web/.env.local` = `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` (git-ignored). Without the variable the app runs in **demo mode** on `web/fixtures` (read-only; `npm run fixtures` re-snapshots them from a running API, loaded on demand so API users never download them). Smoke tests: `npm run test:e2e` (Playwright, installed Chrome, needs the stack running).

**Ask** (DESIGN §4): welcome screen with sample questions; `?q=` and `?as_of=` in the URL (shareable, Related and Analytics links use it); answer with citation chips that highlight their source card; source drawer loads `/passages/{id}` and marks the cited words in the full passage, with version/date/status, position (part n of N, before/after) and "Open original"; current-vs-older card grouped (one row per change, all older documents listed); as-of pill re-asks at once; client chip from `/scopes`; invoice picker from `/invoices` with vendor tips from `/context`; not-covered card **Send to {role}** (`POST /escalations`) then "Sent to {role} · waiting"; expert replies arrive as "Your question was answered" (polls `/notifications` every 10 s) and as an "Expert reply — not yet part of the knowledge base" card; "Report a wrong answer" in every card footer; owner sees an unverified draft with its problems (`viewer=owner`). Change banner and nav badges come from one shared 10 s poll (`/stats`, `/changes?since=`), acknowledgements go to `POST /changes/{id}/ack`.

**Pages** (DESIGN §5), all on the same shell and tokens: **Sources** (drop zone for files and folders, connector cards, episode log with queued → parsed → extracted → published pills and a rose dot on the current step, tier/quality and passage/fact counts, Retry for failed or held episodes, low-confidence metadata as editable chips → `PATCH /sources/{id}` + re-resolution, 2 s polling while anything is processing, totals rail); **Conflicts** (run scan + last-run summary, authoritative vs conflicting side by side, reason, Dismiss / Open in review / Mark resolved, filters by kind and disagreeing source); **Review queue** (grouped by risk tier; metadata, retire, conflict, report and change items rendered per kind; Approve/Reject with `row_version`, 409 → "Someone else just decided this item"; escalated questions with a reply box, effective date and scope); **Setup** (schema version with Draft/Frozen pill, Edit schema → draft, Save draft, Freeze; entity types with counts, topics and attributes with search, editable labels and risk, source authority with reorder, high-risk topics, who may change what, plug-in bindings with Confirm; Entities tab with search, aliases and Merge; Split disabled, cut line); **Entities** (picker, time axis with one row per attribute and scope, overlapping statements in lanes, current bars rose, superseded struck on fill, "now" line, as-of slider and date with the values in force, Known-at replay over transaction time, fact detail and filtered facts rail); **Changes** (cards with old → new, status, source, owner acknowledgement meter, filters); **Expert capture** (five generic questions → `expert_answer` episode, entries with live status); **Analytics** (`GET /analytics`: questions, answered rate, median/p90 wait, acknowledgement rate, top topics, most-cited sources, unanswered questions, outcomes and routes).

**API added for the pages:** `/episodes` with passage/fact counts and documents (with low-confidence fields), `POST /episodes/{id}/retry`, `PATCH /sources/{id}`, `GET /stats`, `GET /analytics`, `GET /notifications`, `POST /notifications/{id}/read`, `POST /schema/draft`, `GET /conflict-scan` (last run), `POST /conflicts/{id}/review`, entity fact counts. 4 more integration tests (18 in `test_api_db.py`).

**Verified live** (Playwright MCP on the dev graph, 1440 px and 390 px): T1 answered with SOP v4.0 4.2 and 14, hovering citation 2 tints its card; drawer highlights the quote; as of 1 Mar 2026 shows 2% / ₹1,000 from v3.1 with "superseded since 1 Apr 2026"; T8 → Send to HR / Admin team → owner replies in Review → asker sees the reply; a dropped .md reached published (1 passage, 2 facts, kb v29 → v30); its date chip corrected to 1 Nov 2026; Conflicts 73 open; Setup schema; Entities timeline as of 1 Jun 2025 shows v3.1 values; Analytics; Capture. 390 px: no horizontal scroll, top bar, sources stacked. `npm run test:e2e`: 3/3 pass (T1 hover → rose card; as-of; upload → published in 1.9 min). lint, tsc, token check, build clean; pytest 211 passed.

**Fixed on the way:** `python -m app.worker` served an empty handler table (the module ran as `__main__` while handlers registered on `app.worker`; it now delegates, test added) — before this only `drain()` from scripts processed jobs; a race let a stale notification fetch wipe the reply banner; duplicated labels ("Video 1 · Video 1 [02:10]") in cards and in the scan's reasons; duplicate React keys in the induced ranking; no dark backgrounds (DESIGN §2).

**Deviations from DESIGN §1:** no SWR and no generated OpenAPI client: a 50-line `useApi` hook on native fetch (AGENTS.md: native APIs over packages) and hand-written types in `web/lib/types.ts` (most endpoints return free-form dicts, so generated types would be `any`). The drawer shows the passage text with the quote marked plus the original file link, not a page/bbox render of the original. Lighthouse accessibility score not measured (no Lighthouse on this machine).

**Gaps found (for Phase 9 and later):** expert replies and uploads publish facts straight away (the canteen reply was cited by a later answer): governance must hold them (T11). Changes are recorded per extraction batch, not per rule, so the change banner rarely has an old → new pair to show. A `Key: value` header line after the first heading is not read as metadata (the test note's "Effective:" date). Evolution drafted schema v3 after the test uploads; left unfrozen. Test uploads left in the dev graph: `visitor_parking_note.md`, one canteen expert reply, and one smoke-test note per e2e run.

## 2026-11-10 — One-command launcher, Ask page keeps its state, conflict-scan precision, dev graph cleaned

- **Launcher:** `.\run.ps1` (or `run.cmd`, or `python scripts/run_app.py`) starts the embedded database, API, worker and web app in one terminal with `[api]/[worker]/[web]` prefixes (also `logs/<name>.log`), opens the browser when both answer, and stops everything on Ctrl+C (whole process tree, so `next dev` frees :3000). Verified with a real Ctrl+C in a separate console for both wrappers: ports freed, no processes left.
- **Ask page:** the unsent question and the last answer (with as-of, client, invoice, "Sent to") are kept per tab in `sessionStorage`; returning from another page restores them without re-asking (0 `/ask` requests); a question still in flight is re-asked on return.
- **Conflict scan:** three false `practice_vs_rule` conflicts showed AP SOP v3.1 / Part F "holding" over v4.0 (a v4.0 responsibilities-table row extracted as practice with value `true`, compared through a neighbour hit on a v3.1 `corroborating` fact). New generic rules in `comparable()`: the rule side is never from an outdated source (also in `_authoritative` and the sibling expansion); "practice" from a document ranked at least as high as the rule is not practice-vs-rule; a bare yes/no neighbour is not compared with a value. Recall unchanged 14/15 both ways, authoritative right 13/14; extras 36 → 32 (all) and 28 → 24 (without the change table); open conflicts 73 → 67. Report `reports/conflicts_20261110.md`.
- **Dev graph cleanup:** `episodes.delete_episodes` (test data only; the graph itself still never deletes) and `kb.discard_schema_draft`, driven by `scripts/delete_episodes.py` (dry run by default). Removed the canteen expert reply, the visitor parking note and the smoke-test note (3 facts, 3 review items, 8 jobs, 1 escalation and its notification) and schema draft v4; kb v31. Schema draft v3 (from the original corpus) is kept for the owner.
- `pytest -q`: 215 passed (4 new: three scan rules, one delete test). Ruff clean.
- **Not fixed:** extraction still labels 26 SOP facts as `practice`; the scan now ignores them as practice-vs-rule, but re-extraction would correct the label itself.

## 2026-11-10 (later) — Client scopes, answer completeness, and the MVP gaps closed

**Client memos:** "Arvana Retail" had been aliased to "Arvana Group" by entity resolution, so the Retail memo's 7 facts were filed under the group. New `app/graph/scope.py`: clients a document declares (`client_scope`) are pinned by exact name (`entities.pin`, `Resolver.resolve(exact=True)`), a client-scoped source keeps its client unless a fact names another known client, and a general source below the memos that names exactly one known client by a distinctive word is that client's fact (not when the condition calls it general). `pipeline.rescope_clients()` moved 21 live facts (kb v32). Verified live per client (Retail, Pharma, Infra).

**Evaluation (160 questions, config D):** 147/160 (91.9%), 3 were NIM 429s → 150/160 (93.8%), citations 97.5%. Answer prompt `answer-v4`: a `details` field filled before the sentences (cut-offs, dates, codes, actions, owners) and a "Can I…" rule; the 10 misses rechecked: 8 now correct → **158/160 (98.8%)** (remaining: Q092 answer-key defect, Q017 partial). The other 150 questions have not been re-run on v4 yet.

**MVP gaps implemented:**
- **Governance** (`app/govern/`): live inputs after setup (upload, email, API, expert replies, watched folder; `GOVERNANCE=true`, bulk/eval scripts set it false) are held: registered sender + own scope + no high-risk topic → provisional (answerable, labelled), else pending (not applied; sources pending so passages are not evidence). `publish(hold=...)` keeps held facts out of resolution; a new version's link to the old one is deferred until approval. Review approve/reject runs `apply_review`: approve → facts current, sources current, groups resolved, change recorded with sender and reviewer, escalations re-asked; reject → retracted, sources rejected. Retire items now apply too. Live T11: canteen reply held (answer stayed unsupported), approved in Review, asker notified, answer cited the reply; then removed.
- **Watched folder** (`app/ingest/watch.py`): worker scans `WATCH_DIR` (default `data/inbox`) every 30 s; new/changed files only; `/connectors` and the Sources card show the last scan. Verified live (picked up, dated from its "Effective:" line, held for review).
- **Entity split** (`app/graph/split.py`, `POST /entities/{id}/split`, Setup → Entities): aliases move to a new entity; facts whose own words name them move as new versions; groups re-resolved.
- **Department/site scopes:** the metadata classifier's `client_scope` now covers any one audience (client, department, site, region); router wording likewise (`docmeta-v2`, `route-v4`). Not yet re-verified on the Kestrel corpus (needs a re-ingest).
- **Per-rule changes:** `publish` records one change per replaced rule (old → new, effective date) when the outcome changed.
- **"Effective:" under the title** is read as header metadata.
- **Ranking:** one rank per document type (`Ontology` validator; `/schema` returns the validated form): Meridian shows 1–8.
- **No client chosen:** a rule that exists only for named clients is answered for them by name.
- **C03:** an outdated numeric statement is compared with in-force rules of the same client, unit and materials under another attribute. **Conflict recall 15/15** both ways, authoritative right 14/15, extras unchanged (30 / 22).
- Tests: 225 passed (new: governance 4, watch 1, split 1, scope 3, conflict rules 3, delete 1, metadata 1).

## 2026-11-10 (evening) — Claude as the LLM provider, full evaluation, replay findings

**Provider switched to Anthropic** (`.env`: `LLM_PROVIDER=anthropic`, Sonnet 5.5 smart, Haiku 5.5 fast, `ROUTER_MODEL=fast`; the NIM lines are kept, commented). The key has $5 of credit, so the graph is **not** rebuilt on Claude: the knowledge base built on NIM is answered from. LLM cache keys include the model, so nothing cached on NIM is reused; rebuilding the graph or `pytest -m live_llm` (which rebuilds it) would cost tens of dollars. Gateway: `thinking=False` now reaches Anthropic too (`between_tools` on Sonnet 5.5, `disabled` on Haiku 5.5); before, every Claude call thought at the default effort.

**Fixed: plug-in modules loaded half-way under concurrency.** Three eval workers importing the AP plug-in at once could get a module before its code had run (`no attribute 'CALCULATORS'`), and the broken module then failed every later question. `Plugin.module` now loads under a re-entrant lock and never leaves a failed module in `sys.modules` (test fails without the fix).

**Full evaluation on Claude (answer-v4, support-v2): 153/160 (95.6%)**, citations strict 98.8%, outdated on conflict questions 2/23, 0 errors, p50 14 s, $2.67 (`reports/eval_20261110_all.md`; the NIM run is kept as `eval_20261110_all_nim.*`). Dev 94/96, holdout 59/64. Weak spots: tacit questions 5/9 (Claude kept to the written rule and dropped or contradicted the colleagues' know-how) and 24 answers (15%) unverified, which processors would see as "not covered".

**Fixes, then a targeted recheck (46 questions, $0.79):**
- Outdated-value check: a value that also appears in the asker's question or the calculator output (of the same kind: money, percentage, days) is the case's own figure or a result, not an old rule. It had blocked a ₹1,000 excess (equal to the retired ₹1,000 cap) and a Thursday cut-off (Thursday was the old run day).
- Support check `support-v3`: conclusions that follow from the evidence plus the case and calculator are supported; wording, framing and omissions are not problems; the model writes its check before the verdict (it had written "On reflection the sentence is supported" and still failed it).
- Answer prompt `answer-v5`, rule 6: practice is given after the rule as "In practice, ..." advice when it concerns the asker's case; it never changes or overrides a rule and is not dismissed when it works within the rule.
- Result: affected dev 15→16 correct, unverified 13→0; affected holdout 12→14 (scores only), unverified 11→1; 12 dev controls 12→12. The other 114 questions were not re-run on v5/v3.

**Replay (`run_replay.py`, on NIM, first complete run): 15/22**, now **18/22** on the same graph after these fixes (probes re-run on the replay tenant; no re-extraction):
- `get_rule` no longer returns a fact whose document has ended (a source's `valid_until`, set when a newer version supersedes it) for what the engine believes now. A rule dropped from the new version stays open until the owner approves the retire item, and the replay has no owner, so v3.1's 2% quantity tolerance had come back as current in Nov 2026. Not applied to `known_at` queries: source end dates are not bitemporal.
- A list value written as one phrase ("Tuesday and Friday") is split into items (R10).
- Probe R21 corrected (expected `none` → `2`): v3.1 has no end date of its own, so with only v3.1 known its 2% applies on 1 Apr 2026. The probe file is ours, not the answer key.
- **Open: R15, R17, R18, R19 (Infra bulk-material tolerance).** The induced schema files the memo's 5% under its own attribute (`quantity_tolerance.infra_material_percentage`), not as an Infra-scoped value of the general tolerance the plug-in binds (`general_percentage`). The answer path finds the memo (Q040, Q041, Q002 correct), but rule lookups through the binding do not, so the quantity calculator would apply 0% to an Infra cement invoice. Fix proposed, not built: let the schema mark an attribute as a client-specific version of another (owner-editable on Setup), and have client lookups search those versions. R19 (the email's provisional 7% from 16 Nov) also depends on how an owner's email ranks against the memo it amends; the replay graph currently marks the 7% overridden.

Spend on the Claude key so far: about $3.53 of $5.

**Next (deferred until the user's usage limit resets):** build the Infra fix described above (schema marks an attribute as a client-specific version of another, editable on Setup; client rule lookups search those versions), then re-run the replay probes (on NIM or against the existing replay tenant, never a Claude re-extraction) and an Infra cement quantity check through the calculator.

## 2026-11-10 (night) — Infra fix: client-specific versions of an attribute

- Schema: an attribute may carry `variant_of` = the general attribute it is a client-specific version of (validated: another attribute of the same value type). `get_rule` for a client also reads that client's facts on its variants; general lookups and other clients are unchanged.
- Setup → Topics and attributes: a "Client-specific version of" selector per attribute (same-type peers only; editable in a draft).
- Meridian: new schema v4 (from frozen v2, not from the unreviewed v3 draft) links `quantity_tolerance.infra_material_percentage` → `general_percentage`; replay tenant v3 likewise (from v1, not its v2 draft). Frozen as owner actions, nothing re-keyed, no LLM calls.
- Quantity calculator on the Meridian graph: Infra cement +3% passes (5%, cap ₹25,000), Infra cement +7% and Infra cables +3% hold with QTY_VAR, Retail +3% holds.
- Replay probes on the existing replay tenant: **21/22**. Open: R19 expects the email's provisional 7% from 16 Nov; the email ranks below the client memo, so authority keeps 5%. A policy question (should an owner's email amending a memo rank with it?), not a lookup bug.
- Not linked: `price_tolerance.infra_cement_steel_percentage` (the FAQ's 10%, an outdated low-ranked claim): linking it would make it count for Infra.
- Tests: 236 pass, including new unit (validator) and integration (variant lookup) tests; ruff, tsc, eslint, token check clean.

## 2026-11-11 — Pre-deploy fixes: owner amendments, email triage, answer speed

**1. An owner's email amends their client's memo (replay R19).** SCOPE §4.7: "The Infra 7% email changes the answer from its effective date onwards." A source scoped to one client and sent by that client's registered owner (schema sender authority, client-specific grants only) now ranks with that client's own documents (`write.source_ranker`), so the later-starting change wins the tie. Uploaded `.eml` files are read as emails; the From display name ("Financial Controller, Client X") becomes the sender role, parsed leniently (unquoted commas). An uploader named by the caller (app uploads, watched folder) is who governance judges, never the header of the file they hand in. Grant clients match full names ("Client X" ~ "Client X Pvt Ltd"). A revised fact now also takes its new rank (rank-only revisions are not recorded as rule changes). On the replay data: R19 7% from 16 Nov passes; R16/R17 fail only when re-probed on the final state (in the real replay they run before the email arrives) — confirm with a full replay rerun. Tests: owner vs stranger email (integration), connectors and owner matching (unit).

**2. Email triage and the level-9 intake check.** `app/ingest/triage.py`: one fast-model call per message (`triage-v1`): rule_change, document, tacit_tip, question, noise. Noise → episode `ignored`, nothing extracted; question → answered through `/ask`, episode `answered` with the answer in its meta, knowledge base unchanged; tacit_tip → stored as practice and always held for review; others → normal path. Emails are identified by the original message text, so forwards are confirmations of the first episode, not new ones. A change whose effective date precedes its receipt lists the retroactive window in its review item. 11 new synthetic emails (`synthetic/emails/02–12`, marked `X-Synthetic`), `eval/episodes_expected.csv`, and `scripts/run_intake.py` (feeds them with governance on, times each, compares, removes them afterwards). **Not run yet.** Expected outcomes follow CLAUDE.md rule 9, so the Infra FC email is `pending` (quantity_tolerance is high-risk in the frozen schema), not TEST_PLAN's `provisional`. Note: the replay now feeds all 12 emails.

**3. Answer speed.** Calculator inputs are read from the question in parallel with routing and search (`early_calculator_inputs`, on by default; wait measured at 0 s). Each answer records step timings in `diagnostics.timings_s`. A date shown to the model in a passage's tags ("in force until 2027-03-31") now counts as cited, so correct answers are no longer sent back for a slow second attempt. On NVIDIA four dev questions took 16–42 s: the free endpoint's answer call alone took 6.7–32.7 s, so the < 10 s target is not reachable on it; on Claude the answer call is about 6 s.

**Environment:** the user added a Neon `DATABASE_URL` to `.env`; it is renamed `NEON_DATABASE_URL(_UNPOOLED)` so local runs keep the embedded database (the deployed host gets it as `DATABASE_URL`). Tests now never use `DATABASE_URL` (only `TEST_DATABASE_URL` or the embedded server). Tests: 248 pass; ruff, tsc, eslint, token check clean.

## 2026-11-11 — Phase 9 deploy (test setup): Vercel + Neon + this laptop via Cloudflare tunnel

- **Database:** the local database (Meridian on schema v4, kb_version 39; Kestrel; replay) copied to Neon (Postgres 18, `neondb`). Schema from `pg_dump --section=pre-data/post-data`, rows streamed table by table with COPY over psycopg (the embedded server's `pg_restore` has no SSL); every table's row count matched; search, vector search and the Infra calculator check verified against Neon. Original files are still on this disk (BLOB_DIR), which is fine while the API runs here.
- **API + worker:** run on this laptop against Neon (`DATABASE_URL` set for the child processes only; `.env` keeps the local database, Neon is `NEON_DATABASE_URL`). Public HTTPS address from a Cloudflare quick tunnel (`tools/cloudflared.exe`, git-ignored; no account). Hugging Face Docker Spaces need a paid plan now, so they were dropped; Google Cloud Run is the recommended host when the laptop should be off.
- **Web:** Vercel project `ps07-knowledge-engine`, production at https://ps07-knowledge-engine.vercel.app, built with `NEXT_PUBLIC_API_BASE_URL` = the tunnel address (deployed with `VERCEL_TOKEN` from `.env`; the GitHub link failed because the Vercel account has no GitHub login connection, so deploys are from the CLI).
- **One command:** `.\run_public.ps1` (`scripts/serve_public.py`) starts API, worker and tunnel; a quick tunnel's address changes on every start, so when it differs from `logs/tunnel_url.txt` the web app is rebuilt on Vercel with it (about a minute). Ctrl+C stops all three; the site cannot answer while they are down.
- **Checked:** the public site answered "What is the quantity tolerance for cement at Arvana Infra?" correctly with the CM-INF-02 citation (46 s on the NVIDIA endpoint); no console errors; CORS preflight 200; the rebuilt bundle calls the current tunnel. No access code (user's decision): anyone with the URL can ask, upload and approve.
