# PS-07 Knowledge Engine — build plan for Claude Code (v2: generic engine)

**What changed from v1.** v1 built an accounts-payable engine around a hand-written domain pack and a table of rule values. Abhishek's call changed the requirement: the engine must ingest data continually into a **bitemporal knowledge graph**, and any company must be able to dump its documents in and use it, whatever their format. So v2 builds a **generic core** (connectors, universal parsing, schema induction, entities, bitemporal facts, authority resolution, governance, cited answers). Everything specific to Meridian accounts payable lives in a **plug-in** (`plugins/ap/`): the six calculators, role routing and the invoice picker. Meridian is the first tenant and the evaluation dataset. SCOPE.md has the full scope and reasoning; CLAUDE.md has the rules.

**Architecture decision.** We follow the data model of the Zep paper (Graphiti): episodes, entities, and fact edges with bi-temporal validity, with edges invalidated rather than deleted. We implement it on Postgres rather than adopting the Graphiti library, because we need three things Graphiti does not give us: authority-ranked resolution (newer does not always win), typed rule values that calculators and conflict checks can compare, and owner review before anything goes live. Algorithms borrowed from Graphiti: entity resolution by candidate search then LLM confirmation, comparing a new fact only against related existing facts, and graph-hop expansion in retrieval. Communities (Zep's third tier) are post-MVP. All graph reads and writes go through one repository layer (`app/store/`) so the storage engine can be swapped later.

**How to run this with Claude Code.** Put CLAUDE.md, BUILD_PLAN.md, TEST_PLAN.md, SCOPE.md and DESIGN.md in the repo root and copy the data files into `data/` and `eval/` as laid out in CLAUDE.md. Then, for each phase, prompt:

> Read CLAUDE.md, BUILD_PLAN.md and PROGRESS.md. Implement Phase N. Plan first, then build, then run the acceptance criteria and pytest. Update PROGRESS.md and commit.

Review the result before starting the next phase.

## Gates and tracks

There are three delivery gates: A is the MVP, B is the internal auction, C is the final.

| Gate | Must be true |
| --- | --- |
| **A: MVP** | The generic pipeline ingests the Meridian corpus with no hand-written pack; replay shows the graph evolving; T1–T9 and T11 (expert escalation) pass on the deployed URL; the second corpus answers 10/10; text-format invariance passes (PDF with text layer, Markdown, HTML, email text, XLSX) |
| **B: Auction** | Vision fallback for scanned PDFs and images, PPTX, watched folder, Entity timeline page, the full format-invariance matrix, distribution basics (Phase 11) |
| **C: Final** | Remaining post-MVP phases 12–15 |

Three parallel Claude Code sessions are needed to reach gate A:

| Track | Phases | Owner works on |
| --- | --- | --- |
| 1. Core backend | 0, 1, 2, 4, 6, 7, 9 | `app/` |
| 2. Plug-in, evaluation, data | 3, 5, and all test data (emails, second corpus, format variants, probes) | `plugins/`, `scripts/`, `eval/`, `synthetic/` |
| 3. Web | 8 | `web/`, against fixtures first |

| Day | Track 1 | Track 2 | Track 3 |
| --- | --- | --- | --- |
| Day 1 | Phase 0 | Calculators as pure functions against stub rules (Phase 3 part 1); write the synthetic emails and the second corpus | Shell, tokens, Ask page on fixtures |
| Day 2 | Phase 1 (tier-1 parsers, upload and API connectors) | Calculator unit tests; replay probes; paraphrase and abstention sets | Ask page complete; Sources page |
| Day 3 | Phase 2 (induction, entities, facts, resolution) | Bindings (Phase 3 part 2); eval harness skeleton | Review, Conflicts, Changes pages |
| Day 4 | Phase 4 (retrieval, answer card, verifier); first dev run | Harness complete; format variants rendered | Wire to the API; Setup page |
| Day 5 | Phase 6 conflict scan; Phase 9 governance, email intake, deploy; **evening: freeze** | Fix-loop support; holdout run | Polish; Playwright checks |
| Day 6 | Full eval; second corpus; MVP note | Format invariance (text formats); ablation | Final UI checks |

**This is tight.** If behind, cut in this order: Entity timeline page → watched folder → reranker (keep RRF) → entity merge and split UI (keep automatic resolution) → hop expansion → History tab and source drawer → analytics. Never cut: continuous ingestion through the pipeline, bitemporal facts, as-of answers, citations, the verifier, calculators, the evaluation harness, conflict scan, governance, replay, the second corpus, deployment.

**Safety net.** Set `SCHEMA_MODE=baseline` to run the engine on the hand-written schema in `plugins/ap/baseline_schema/` instead of the induced one. The demo can never be blocked by an induction failure, and the same switch gives the induced-versus-hand comparison.

---

## Phase 0 — Scaffold, bitemporal store, job queue (half a day)

Build:
- Repo layout from CLAUDE.md; `pyproject.toml`; `ruff`; `pytest`; `.env.example` with `ANTHROPIC_API_KEY`, `DATABASE_URL`, `BLOB_DIR`, `MODEL_FAST=claude-haiku-5-5`, `MODEL_SMART=claude-sonnet-5-5`, `API_BASE_URL`, `SCHEMA_MODE=induced`.
- `docker-compose.yml` with `pgvector/pgvector:pg16`. Enable the `vector`, `pg_trgm` and `btree_gist` extensions.
- `app/core/llm.py`: one function per call style (`complete`, `structured` using tool-use with a Pydantic schema, `vision` taking page images). Redaction before sending; JSONL call log in `logs/llm_calls.jsonl` (redacted prompt, model, tokens, cost, latency); on-disk cache keyed by hash(prompt_version, model, input).
- `app/core/redaction.py`: PAN `[A-Z]{5}[0-9]{4}[A-Z]`, IFSC `[A-Z]{4}0[A-Z0-9]{6}`, bank account numbers (9–18 digits next to words like "account" or "a/c"), Indian mobile numbers, email addresses in message bodies (keep sender addresses as metadata only).
- **Repository layer** `app/store/`: every SQL statement for graph tables lives here. Other packages call functions such as `store.add_episode`, `store.upsert_entity`, `store.write_fact`, `store.get_facts(entity, attribute, scope, valid_on, known_at)`. Nothing outside `app/store/` imports table models.
- **Job queue** in Postgres: `jobs` table claimed with `SELECT … FOR UPDATE SKIP LOCKED`; `app/worker.py` runs N workers; retries with backoff; failed jobs surface on the Sources page.
- Database schema (Alembic migration). **Every table has `tenant_id`** (default `'default'`) from day one:

| Table | Key columns |
| --- | --- |
| `episodes` | id, channel, source_uri, blob_path (original file), mime, sender, sender_role, received_at, effective_hint, scope_hint, content_hash (unique per tenant), parse_tier, parse_quality, triage_label, status (queued, parsed, extracted, published, pending_review, needs_attention, failed), error |
| `sources` | id, episode_id, title, doc_type, version, dated, status, owner, client_scope, authority_rank, supersedes_source_id, meta_provenance jsonb (each field → {origin, confidence}), confirmed_by |
| `passages` | id, source_id, episode_id, locator, heading_path, text, context_header, position jsonb (page, bbox, cell range, slide, char offsets, time range), client_scope, tsv (generated), embedding vector(384) |
| `schemas` | id, version, status (draft, frozen), ontology jsonb: entity_types; attributes {key, label, synonyms, value_type, unit, risk}; source_type ranking; risk topics; sender authority |
| `entities` | id, type, name, summary, attrs jsonb, embedding, merged_into |
| `entity_aliases` | entity_id, alias, episode_id |
| `facts` | id, subject_id, attribute, object_id (nullable), value jsonb {type, number, unit, text, date}, scope jsonb {client, material, category…}, condition, statement, kind (rule, practice, definition, procedure, attribute), passage_id, episode_id, source_id, authority_rank, **valid_from, valid_to, recorded_at, retracted_at**, status (current, superseded, overridden, corroborating, provisional, pending, rejected), supersedes_id, confidence, embedding |
| `plugin_bindings` | plugin, param, attribute_key, subject_entity_id, confirmed_by |
| `conflicts` | id, subject_id, attribute, scope, fact_a, fact_b, kind (value, scope, self_contradiction, practice_vs_rule), authoritative_fact, reason, status, detected_at |
| `review_items` | id, kind (change, conflict, tacit, schema, metadata, question), payload jsonb, risk_tier, status, row_version, decided_by, decided_at |
| `kb_versions` | id serial, published_at, summary |
| `changes` | id, kb_version, new_fact, old_fact, summary, effective_at, source_episode |
| `answers_log` | id, user_id, question, client, as_of, kb_version, route, card jsonb, cited_fact_ids, cited_passage_ids, latency_ms, created_at |
| `acks`, `notifications` | change_id or answer_id, user_id, at |
| `escalations` | id, answer_id, question, client, asked_by, routed_to_role, assignee, status (open, answered, closed), expert_reply, expert_id, episode_id (the reply as an episode), resulting_fact_ids, created_at, answered_at |
| `jobs` | id, kind, payload, status, attempts, run_after, locked_by, error |

  Plug-in tables (created by the plug-in, not the core): `ap_vendors` and `ap_invoices`, loaded from the operations workbook; they hold no bank or PAN fields.
- Indexes: GiST on `tstzrange(valid_from, valid_to)` and on `tstzrange(recorded_at, retracted_at)` for facts; btree on (tenant, subject_id, attribute); HNSW on every embedding; GIN on `passages.tsv`; trigram index on `entities.name` and `entity_aliases.alias`.
- `tests/test_no_leakage.py`: fails if any file under `app/`, `web/` or `scripts/ingest_*` references `qa_evaluation_set`, `known_conflicts` or `gold_answer`. `tests/test_core_is_generic.py`: fails if any file under `app/` contains "Meridian", "Arvana", "TDS", "GSTIN", "MSME", a rupee sign, or imports from `plugins/`.

Acceptance: `docker compose up`, migrations apply, `pytest -q` passes, a sample `llm.structured` call returns a validated object and appears redacted in the log, a job enqueued and processed by the worker, and a bitemporal query on a hand-inserted fact returns the right row for `valid_on` and `known_at`.

## Phase 1 — Connectors and universal ingestion (1.5 days)

Nothing here may know what a Meridian SOP looks like. Format and layout rules are replaceable hints (SCOPE.md section 3.5).

**Connectors** (`app/ingest/connectors/`), all producing the same `EpisodeIn {channel, sender, received_at, files/text}`:
- `upload`: single files, folders and zips, via `POST /episodes/upload`.
- `api`: `POST /episodes` for raw text or a file.
- `eml`: `.eml` files and raw RFC 822 text.
- `watched_folder` (gate B): polls a directory every 30 s; new or changed files become episodes.

**Intake step:** store the original in `BLOB_DIR`; compute the content hash; skip duplicates (a duplicate email adds a confirmation count to the first episode instead); detect the type with libmagic, not the extension; enqueue `parse_episode`.

**Parser cascade** (`app/ingest/parsers/`), cheapest first. Every parser returns a list of typed blocks `{type: heading | paragraph | list_item | table | table_row | turn | quote | figure | header_footer, text, level?, page?, bbox?, time_range?, speaker?, style?}`:

| Tier | Handles | How |
| --- | --- | --- |
| 1 | docx, xlsx/csv, pptx, html, md/txt, eml/mbox, json, vtt/srt and `[mm:ss] Speaker:` transcripts, text-layer PDF | python-docx (keep style names and list numbering), openpyxl/pandas, python-pptx, BeautifulSoup, PyMuPDF for PDFs (font sizes and positions kept) |
| 2 | .doc, .ppt, .xls, .rtf, .odt | LibreOffice headless conversion, then tier 1 |
| 3 (gate B) | Scanned PDFs, images, PDFs with broken text or tables | Render pages to images; `llm.vision` returns structured markdown with tables and reading order |
| 4 (post-MVP) | Audio, video | Whisper with timestamps, then turn blocks |
| 5 | Unknown | Best-effort text; otherwise store as opaque and flag |

**Quality gate:** score each episode (extracted characters versus expected, junk-character ratio, heading and table integrity, OCR confidence). A low score escalates to the next tier; still low means status `needs_attention` and its facts are held for review, not published.

**Structure inference** (`app/ingest/segment.py`), evidence in this order: style names and list levels, table of contents, slide titles, email headers; font size and weight relative to body text; numbering patterns (`4.2`, `Part C`, `Q1.`) as hints only; an LLM structure-repair pass when the outline is flat or doubtful (`MODEL_FAST` assigns heading levels to candidate lines); and as a last resort a 200–400 token window with overlap. Passage rules by content:

| Content | Rule |
| --- | --- |
| Sections | One passage per leaf section; long ones split at paragraph boundaries and keep their heading path. A parent passage keeps the whole section for context |
| Tables | Whole if small; otherwise one passage per row with the header repeated. Rendered as Markdown |
| Spreadsheets | Each row is a record (column header → value); one description passage per sheet |
| Step lists | One passage per step, plus the whole list as a parent |
| Transcripts, chat | One passage per turn; the interviewer's question joins the following answer; timed notes (`10:05 — …`) are passages |
| Email | Quoted replies and signatures stripped; headers kept as metadata |
| Slides | One passage per slide, including speaker notes |
| Q&A and FAQ | One passage per pair |

**Locators:** where a number label is detected it is used (`4.2`, `Part B, step 3`, `Video 1 [04:30]`, `Shadowing 10:05`), so the evaluation's gold references still resolve; otherwise the locator is the heading path plus page.

**Context header** on every passage, for search and extraction only: `SOP v4.0 · §4.2 Price tolerance · effective 1 Apr 2026 · status current · all clients`.

**Document metadata inference** (`app/ingest/metadata.py`): doc type, version, dated, status, owner, client scope and "supersedes" are read, in order, from file properties, filename, header tables and first-page text, footers, then a `MODEL_FAST` classifier. Each field stores its origin and confidence in `sources.meta_provenance`. Fields below 0.7 confidence create a `metadata` review item for the owner. **Date precedence:** explicit effective date in the text, then document date in the header, then email sent date, then file modified time, then ingestion time; the winner is recorded. Client scope: memo-style documents are scoped to the client they name; everything else defaults to `all`.

**New versions of a known document:** match a new source to an existing one (similar title, same doc type, higher version or later date). Align passages; passages with identical text are carried over and not re-extracted; changed and added passages are enqueued; removed passages create a review item proposing to retire their facts. The new source gets `supersedes_source_id`.

Acceptance:
- All four Meridian documents plus transcripts and the operations workbook ingest with no hand-written pack, and the expected passage counts in TEST_PLAN level 2 hold.
- Every passage has source, version, date, locator and status (unit test).
- Locator coverage: every distinct `gold_source_section` value in the eval set exists as a passage locator (`tests/integration/test_coverage.py`, which may read the eval file because it is a test).
- Metadata inference matches the hand-copied `plugins/ap/baseline_schema/sources.yaml` on at least 90% of fields (test code only).
- Re-running ingestion is idempotent (same counts, no duplicates).
- Parsing 14 document parts takes under 2 minutes.

## Phase 2 — Schema induction, entities and the bitemporal fact graph (2 days)

This is the core of the product.

**2a. Schema induction** (`app/graph/induce.py`). On a tenant's first dump, sample passages (stratified by source and document type) and have `MODEL_SMART` propose an ontology: entity types; attributes with key, label, synonyms, value type (percentage, money, days, date, enum, text, number) and unit; topics; a source-type ranking (authority) using document type, version numbers, dates and status words such as "superseded" or "draft"; a risk list (topics involving money, legal, tax, security or access); and sender authority (who owns which topics, from ownership statements in the documents). The result is saved as `schemas` v1 (draft). The Setup page lets the owner edit it and freeze it. `--auto-freeze` is used in tests. New attributes found later are proposed as `schema` review items. With `SCHEMA_MODE=baseline`, the hand-written schema is loaded instead.

**2b. Extraction** (`app/graph/extract.py`). For each passage, `MODEL_SMART` returns entity mentions and facts, using the frozen schema and the passage's context header. A fact has: subject, attribute (from the schema, or `other:<proposed>`), typed value, scope, condition, kind, a statement (one sentence), the source quote, and any dates mentioned (effective, expiry) with their original wording. Interviews and shadowing notes produce `kind=practice`. Relative dates ("from next Monday") are resolved against the episode's `received_at`. Formal documents take `valid_from` from the source's `dated`; transcripts take their recorded date. Tables use a variant of the same prompt that includes the header row.

**2c. Entity resolution** (`app/graph/entities.py`). For each mention: exact alias match first; otherwise candidates from trigram similarity and embedding search among entities of the same type; one clear candidate above the high threshold merges without an LLM call; ambiguous cases go to a `MODEL_FAST` confirm step (cached); no candidate creates a new entity. Aliases are recorded. The owner can merge or split entities on the Setup page.

**2d. Write path and authority resolution** (`app/graph/resolve.py`). For each new fact, fetch only related existing facts: same subject and attribute, plus, for `other:` attributes, the nearest neighbours by embedding. Never compare against the whole graph. Then:
1. **Same value:** the new fact is `corroborating`; it can be cited as an additional source.
2. **Different value, narrower scope:** a client-scoped fact from a client memo overrides the general rule for that client only; both stay current in their scopes.
3. **Different value, same scope:** the lowest `authority_rank` among sources with status current wins and becomes `current`. On equal rank, the later effective date wins. Newer does not win over a better-ranked source.
4. The loser becomes `superseded`: `valid_to` = the day before the winner's `valid_from`, `retracted_at` = now, and `supersedes_id` set on the winner. If the loser's own `valid_from` is not earlier than the winner's, it is marked `overridden` with an empty validity interval and kept for audit.
5. **Practice facts never override rules.** If compatible they attach as expert tips; if they contradict a rule, open a `practice_vs_rule` conflict for the owner.
6. **Facts with `valid_to` in the past** (a memo that has expired) read as superseded without any write; `get_facts` applies the interval.
7. **Text values** go to a `MODEL_SMART` judge that returns same, different or narrower scope.

Governance (Phase 9) decides whether a write is published, provisional or pending. In bulk ingestion of the initial corpus, all sources are treated as owner-approved.

**2e. Query layer** (`app/store/facts.py`, `app/graph/rules.py`):
- `get_facts(entity, attribute, scope, valid_on=None, known_at=None)`. `valid_on` filters the valid-time interval; `known_at` filters the transaction-time interval (`recorded_at ≤ known_at < retracted_at`).
- `get_rule(topic, parameter, client, as_of=None, known_at=None) -> RuleValue(value, fact_id, citation)` is a thin wrapper used by plug-ins. Topic and parameter names are resolved through the schema's synonyms and the plug-in's bindings.

**2f.** `scripts/build_graph.py` enqueues extraction, entity resolution and resolution for all passages and prints a summary: entities per type, facts per attribute, current versus superseded counts, resolution decisions, LLM cost.

Acceptance:
- For each row of SOP §14, the current fact has the v4.0 value and the v3.1 value is superseded with `valid_to` 31 Mar 2026 (an integration test that reads §14 from the parsed SOP, not from the answer key).
- CM-INF-02 is current for Infra only, with `valid_to` 31 Mar 2027. The FAQ's excipient answer is superseded by CM-PHA-01 for Pharma.
- Video 2's GSTIN and TDS facts are `corroborating`; its ₹10 crore and GSTR-2A facts are superseded.
- Bitemporal queries: `known_at` before ingestion returns nothing; `valid_on` 1 Mar 2026 returns the v3.1 tolerance.
- Entity resolution on the hand-labelled alias set (TEST_PLAN level 16) reaches F1 ≥ 0.85.
- Induced-schema coverage of the baseline schema's topics and parameters is reported, and answer accuracy with `SCHEMA_MODE=induced` is within 5 points of `baseline` (measured in Phase 5).

## Phase 3 — AP plug-in: bindings and calculators (1 day, in parallel with Phase 2)

The core never imports this. A plug-in is a folder `plugins/<name>/` with `plugin.yaml`, `bindings.yaml`, a calculator registry, `roles.yaml` (who owns what, for "who to ask" routing, e.g. tax questions go to Tax Desk, queue and policy gaps to Team Lead), router hints, and optional data loaders.

**Bindings.** `bindings.yaml` lists the parameters the calculators need in plain language, for example `price_tolerance.pct_of_line: "price tolerance as a percentage of PO line value"`. A bind step maps each to an induced attribute key and subject entity using embedding match plus an LLM confirm, and stores it in `plugin_bindings`. Unresolved or low-confidence bindings appear on the Setup page for the owner. If a required binding is missing at calculation time, the calculator raises an error; it never falls back to a default.

Each calculator is a pure function taking typed inputs plus `RuleValue`s from `rules.py`, and returning `{decision, exception_code, working (list of steps with numbers), result fields, citations}`. Parameter extraction from free text uses `MODEL_FAST` with a Pydantic schema; never parse the eval templates with regex.

| Calculator | Logic (thresholds come from the graph) |
| --- | --- |
| Price tolerance (§4.2) | excess = max(0, invoice_price − po_price) × qty; limit = min(pct × po_price × qty, cap). Pass if excess ≤ limit, else PRICE_VAR. An invoice price below the PO passes at the invoice price. Show the 1% figure and the cap in the working. |
| Quantity tolerance (§4.3 + CM-INF-02) | Any excess over GRN fails with QTY_VAR, except Infra bulk materials (cement, reinforcement steel, sand, aggregates) within the memo's validity: pass if excess ≤ 5% of GRN qty and excess value ≤ ₹25,000. |
| TDS (§6) | Base = taxable value excluding GST. A nature classifier (`MODEL_FAST`) maps the description to an enum: contract_individual_huf, contract_other, professional, technical_service, rent_plant_machinery, rent_land_building, goods_purchase, amc_manpower, amc_technical, amc_unclear. Section and rate come from the graph's §6 table. No PAN: rate = max(no_pan_rate, normal rate). AMC rules come from the expert practice in Interview 2 [03:10] (lift, HVAC, DG set → 194C; software, ERP, network monitoring → 194J 2%; CCTV with remote monitoring → unclear). amc_unclear returns TDS_SECTION_UNCLEAR and routes to the Tax Desk. 194Q applies only on purchases above the ₹50 lakh threshold, on the excess. If payee type is unknown for a contract, state both rates and the condition. Advocate or law-firm legal services also flag RCM_REVIEW (§5.6). |
| Approvals (§7) | Uses the total including GST. Up to and including ₹10 lakh: none beyond a clean match. Above 10 up to and including 50 lakh: AP Controller. Above 50 lakh: Client CFO. Non-PO adds budget owner. |
| MSME payment (§9) | Micro or small: term = min(agreed, 45) if there is a written agreement, else 15 days. Medium or not MSME: agreed term or 60 days by default. Due = acceptance date + term. Payment run = the latest Tuesday or Friday on or before the due date (the due date itself if it is a run day). Also show the cut-off: 1 pm on the previous working day. Assume no holidays and say so. |
| E-invoice (§5.4) | Required if the highest AATO since 2017-18 exceeds ₹5 crore. Without IRN: IRN_MISSING, pay nothing including base. With IRN, or AATO at or below the threshold: acceptable on this check. |

The plug-in also loads the operations workbook's vendors and invoices into `ap_vendors` and `ap_invoices` for the invoice picker and `/context`.

Tests: `tests/unit/test_calculators.py` with hand-written cases from the SOP, including boundaries (excess exactly equal to the limit; exactly ₹10 lakh and ₹50 lakh; AATO exactly 5.0 crore; a due date falling on a Tuesday or Friday; a due date on a Saturday or Sunday; no PAN combined with a 10% section). Part 1 runs against stub `RuleValue`s so it does not wait for Phase 2. Then `tests/integration/test_scenarios.py` runs all 92 scenario questions through extraction plus calculator and compares decision and numbers to the gold answer (TEST_PLAN level 1), under both `SCHEMA_MODE=induced` and `baseline`.

Acceptance: 92 of 92 scenario questions correct on decision and numbers, or every miss documented with a reason (for example, the gold answer contradicts the SOP).

## Phase 4 — Retrieval and the answer pipeline (1 day)

- **Index:** embed context header + passage text with fastembed; GIN index on `tsv`; embeddings for entities and facts.
- **Entity linking:** the question is linked to entities by alias match and embedding search (the client too).
- **Retrieve** (`app/answer/retrieve.py`): full-text top 20 + vector top 20 → reciprocal rank fusion → rerank top 20 → keep 6. Filter by client scope (general plus the asker's client). **Graph context:** for linked entities, fetch their current facts at the requested `as_of` (default now), and expand one or two hops along object-entity relations, capped at 10 facts ranked by similarity. Superseded facts and passages are fetched separately for the "older sources" line, never as the main evidence.
- **Time travel:** `/ask` accepts `as_of` (valid time) and optionally `known_at` (transaction time). With `as_of` set, current facts and citations are those valid on that date, and the answer says so.
- **Router** (`app/answer/router.py`, `MODEL_FAST`): returns `{route: calculator:<plugin>.<name> | lookup | practice | out_of_scope, client, params, confidence}`. The calculator list comes from installed plug-ins. Below a confidence threshold, fall back to lookup.
- **Generate** (`app/answer/generate.py`, `MODEL_SMART`, structured output): inputs are the question, the client, the current facts for the linked entities, the retrieved passages with ids, the calculator output if any, the superseded facts for the topic, and approved expert tips. Output is the answer card:

```
{answer_id, kb_version, as_of, client, route,
 status: answered | provisional | unverified | unsupported | needs_specialist,
 rule: {text,                      # prose with [1], [2] markers in citation order
        citations: [{n, passage_id, file, short_label, locator, section_title,
                     doc_type, status, quote}]},
 working: [{label, value}] | null, decision, exception_code, next_owner,
 older_sources: [{topic, current_value, older_value, file, locator,
                  superseded_by, superseded_on}],
 expert_tip: {text, author, date, citation, approved_by} | null,
 route_to: {role, reason} | null,
 entities: [{id, name, type}],
 related: [3-4 follow-up questions],
 latency_ms}
```

The UI renders this card directly (DESIGN.md section 4), so keep field names stable. `related` comes from a cheap `MODEL_FAST` call or route-based templates. Every `[n]` marker must have a matching citation; the verifier checks this.

- **Verify** (`app/answer/verify.py`), in order:
    1. Every cited passage id was in the retrieved set, and the quote occurs in the passage text.
    2. Every number in `rule.text` appears in a cited passage or in the calculator output.
    3. No superseded value for the matched topics appears in `rule.text` (deterministic check against the facts table, as of the requested date).
    4. A `MODEL_FAST` support check confirms each sentence is backed by its cited quote.
  On failure, retry generation once with the failures listed. If it still fails, the card becomes `unverified`: the draft moves to a separate `draft` field that only the process owner and the evaluation harness can read, and processors get the not-covered card with the escalate action instead. A processor never sees text the verifier did not confirm.
- **Abstain:** if the top reranked score is below a threshold or the model returns unsupported, set status unsupported and fill `route_to` from the plug-in's `roles.yaml` (generic fallback: the owner of the topic in the schema, then "the process owner"). T8 (canteen subsidy) must take this path.

**Grounding guardrails (answers come only from the knowledge base).** Several layers, none of which depends on the model behaving:
1. **Scope guard:** the router returns `out_of_scope` for general knowledge, chit-chat, legal or tax advice beyond the documents, and requests for personal data. These never reach generation.
2. **Closed-book generation:** the generator receives only the retrieved passages, current facts and calculator output. Its instructions forbid outside knowledge, and its structured output must attach a passage id to every sentence of `rule.text`; a sentence without one is rejected before verification.
3. **Retrieval gate:** a weak top score abstains (above).
4. **Verifier:** the four checks above; a failing answer is withheld from processors.
5. **Deterministic numbers:** calculator output and graph values, never model arithmetic.
6. **Injection resistance:** retrieved text, emails and uploaded documents are data. Instructions inside them are ignored, and the extraction and governance layers treat them the same way (TEST_PLAN level 8).
7. **Audit trail:** every answer, its citations and its verifier result are logged. A "Report a wrong answer" button on every card creates an escalation of kind `report` for the owner and adds the question to the evaluation backlog.

**Escalation to an expert.** An unexpected question is never left as a dead end:
- On an `unsupported` or `needs_specialist` card, or an `unverified` one, the route card offers **Send to {role}**. `POST /escalations` creates a record with the question, the client, the asker, and what the engine found (the top passages and why it abstained). It is routed to the role from `route_to`, and the asker sees "Sent to {role}".
- The expert sees it as a `question` item in the Review queue and replies in free text, optionally with an effective date and scope.
- The reply is delivered to the asker straight away, labelled "Expert reply — not yet part of the knowledge base", and also enters the normal pipeline as an episode on channel `expert_answer` with the expert as sender. It is triaged, extracted (as a rule or a practice fact), resolved, and goes through governance exactly like an email: a registered owner of that scope on a low-risk topic publishes as provisional; anyone else, or a high-risk topic, becomes a pending review item for the process owner. An expert reply alone never changes a rule.
- Once the resulting fact is published, the original question is re-asked automatically. The new answer cites the expert's reply, and the asker is notified.
- Open escalations are listed oldest first so none is forgotten. In-app notification only for the MVP.

Log every answer to `answers_log` with cited fact ids.

Acceptance: acceptance tests T1–T8 and T11 pass (TEST_PLAN level 4). The support-removal test (TEST_PLAN level 8) shows zero unsupported answers. p50 latency under 10 s on the dev split. An `as_of` question for 1 Mar 2026 returns the v3.1 tolerance, labelled as the rule in force on that date.

## Phase 5 — Evaluation harness (half a day; build early, run often)

Implement `scripts/run_eval.py` exactly as specified in TEST_PLAN levels 5 and 6: dev and holdout split, deterministic scenario grading, LLM judge for the rest, citation and outdated-answer metrics, latency, cost, four-way ablation, and Markdown plus CSV reports in `reports/`. The judge prompt and the hand-graded calibration set live in `eval/judge/`.

Add the generic-engine runners (TEST_PLAN levels 14–16):
- `scripts/run_replay.py`: feeds the dated corpus and synthetic emails in chronological order; after each episode runs the probes in `eval/replay_probes.csv` (as-of and as-known-at questions with expected values, written from the SOP §14 and the synthetic emails, not from the answer key).
- `scripts/run_format_invariance.py`: renders the SOP into the format variants (LibreOffice and pandoc scripts in `scripts/render_variants.py`), ingests each into a fresh tenant, and scores fact-level F1 against the docx baseline and scenario-answer stability.
- `scripts/run_second_corpus.py`: ingests `synthetic/corpus2_hr/` through the upload connector with no code changes and runs its 10 questions.
- Reports compare `SCHEMA_MODE=induced` against `baseline`.

Acceptance: one command produces `reports/eval_<date>_<split>.md` with all metrics and a per-question table, including the 15 worst questions with failure reasons; the three runners above each produce a report.

## Phase 6 — Fix loop and conflict scan (1 day)

- Run the dev split. Group failures by cause: retrieval miss, wrong authority, calculator, extraction, entity resolution, generation, verifier false alarm. Fix the largest bucket first. Do not look at holdout failures until the freeze (TEST_PLAN section 3).
- **Conflict scan** (`app/graph/conflicts.py`, `POST /conflict-scan`): compare facts within each (subject, attribute, scope) group. Numeric values are compared directly; text values go to a `MODEL_SMART` judge that returns same / different / narrower scope. Also check facts within one document for self-contradiction (SOP v3.1's worked example). Each conflict records both passages, the authoritative fact and the reason (precedence rule and dates). Add a flag to run the scan with SOP §14 excluded, so recall can be reported honestly both ways.

Acceptance: conflict report finds at least 12 of the 15 known conflicts, measured by `scripts/conflict_report.py --score` (test code reads the answer key; the scan itself does not).

## Phase 7 — API (half a day)

FastAPI routers matching the solution doc. MVP set:

| Endpoint | Purpose |
| --- | --- |
| `POST /ask` | {question, user_id, client?, invoice_id?, as_of?, known_at?} → answer card |
| `POST /episodes` | submit an email, chat item or text to intake |
| `POST /episodes/upload` | files, folders or zips |
| `GET /episodes`, `GET /episodes/{id}` | pipeline status, parse tier and quality, errors, facts produced |
| `GET /episodes/{id}/original` | the original file, for the source drawer |
| `GET /schema`, `PUT /schema`, `POST /schema/freeze` | view, edit and freeze the induced schema |
| `GET /entities`, `GET /entities/{id}`, `GET /entities/{id}/timeline` | entity list, detail, and fact history for the timeline page |
| `POST /entities/merge`, `POST /entities/{id}/split` | owner corrections (cut-line) |
| `GET /facts` | by entity, attribute, scope, `valid_on`, `known_at` |
| `GET /plugins`, `GET /bindings`, `PUT /bindings/{id}` | installed plug-ins and their bindings |
| `POST /calculate/{plugin}/{family}` | direct calculator access |
| `GET /context` | vendor tips, recent changes and checks for a vendor or invoice (AP plug-in) |
| `GET /changes?since=` | change feed by kb_version |
| `GET /review-queue`, `POST /review/{id}` | approve, reject or edit, with `row_version` check (409 on conflict) |
| `POST /escalations`, `GET /escalations?status=&assignee=` | send a question to the routed expert; list open and answered escalations |
| `POST /escalations/{id}/reply`, `POST /escalations/{id}/close` | expert reply (becomes an `expert_answer` episode); close without a reply |
| `POST /answers/{id}/report` | "Report a wrong answer" from any card |
| `POST /conflict-scan`, `GET /conflicts` | conflict report |
| `GET /passages/{id}` | full passage with version, date, status and position in the original |
| `GET /invoices?q=` | search the operations invoices for the invoice picker |
| `GET /version`, `GET /health` | current kb_version; health check |

Every response carries `kb_version`. Enable CORS for the Vercel domain and localhost:3000. Reads use one snapshot transaction. Acceptance: OpenAPI docs render; integration tests cover each endpoint.

## Phase 8 — Web app (built in parallel from day 1; wired up here)

Build `web/` exactly to DESIGN.md: Next.js + Tailwind, the rose answer-engine design, calling the API only.

1. **Shell and tokens:** Tailwind tokens and fonts from DESIGN.md section 2; the three-zone shell; the responsive behaviour.
2. **Ask page against fixtures:** eyebrow, question heading, tabs, source-chip strip, answer body with inline rose citation chips linked to the sources rail, decision row, working card, current-vs-older card, expert tip card, not-covered route card (with Send to expert), Related list, composer with invoice picker and client chip, and the **as-of date picker**. Fixtures for T1, T5, T8 and an as-of answer.
3. **Wire to the API:** `POST /ask`, `/context` for an attached invoice, `/passages/{id}` for the source drawer (shows the passage highlighted in the original), and change polling every 10 s with the banner and acknowledgement.
4. **Owner and expert pages:** Conflicts, Review queue (including schema, metadata, change and escalated-question items, with a reply box for experts), Changes list.
5. **Generic-engine pages** (DESIGN.md section 5): **Sources** (drop zone, connector status, episode log with pipeline status and errors), **Setup** (induced schema, authority ranking, risk list, bindings, entity merge; freeze), **Entity timeline** (gate B).
6. **Role switch** in the avatar menu (Processor / Process owner); no real auth for the MVP.

Acceptance:
- A non-technical teammate can run T1–T9 and T11 from the UI without help, and can drop a file on Sources and see it reach "published".
- DESIGN.md section 8 "done when" checks pass.
- Playwright smoke tests: ask T1, see a citation chip, hover it, the matching source card turns rose-tinted; upload a file and see its status progress.

## Phase 9 — Continuous intake, governance and deploy (1 day)

- `synthetic/emails/`: write 12 `.eml` files as the team's own test data, clearly marked synthetic. Include: the Infra Financial Controller raising the bulk-material tolerance to 7% from next Monday; a colleague claiming the price tolerance is still 2%; a spoofed email changing the bank-change process; the same Infra email forwarded twice; three noise emails; a question; a supplier-habit tip from a senior; a client email with a past effective date.
- **Intake** uses the same pipeline as bulk ingestion: store raw → hash dedupe → redact → strip quoted replies and signatures → triage (`MODEL_FAST`: rule_change, fact, question, tacit_tip, noise) → extraction → entity resolution → resolve against the graph → governance. Dates resolve against `received_at`.
- **Governance** (`app/govern/`): the schema's sender-authority map (confirmed by the owner) says who may change what. Sender is the registered owner for the scope and the topic is not high-risk → publish as `provisional` and create a review item to confirm. Any other sender, or a high-risk topic → `pending` review item, not applied. Tacit tips → pending review. Parse-quality failures → held. Expert replies to escalated questions (channel `expert_answer`) follow the same rules.
- **Publish** in one transaction: retire the old fact (set `valid_to` and `retracted_at`), insert the new one, bump `kb_versions`, insert a `changes` row. A future `valid_from` is stored as-is; `get_facts` applies it only from that date.
- **Replay mode:** `scripts/run_replay.py` and a button on the Sources page feed the dated corpus in chronological order (SOP v3.1 2023 → FAQ → videos → SOP v4.0 2026 → memos → emails), so the graph can be watched evolving.
- **Deploy:** API and worker as Docker services on Render; web app on Vercel with `NEXT_PUBLIC_API_BASE_URL`; Neon Postgres with pgvector; a seed job runs ingestion and graph build on first deploy. One public URL, with processor and owner pages behind the role switch.

Acceptance: TEST_PLAN level 9 routing table passes; replay probes pass (level 14); T1–T9 and T11 pass on the deployed URL. A single email is answerable in under 60 seconds.

## Phase 10 — Gate A freeze

- Run the full evaluation (dev, holdout, all), the ablation, the induced-versus-baseline comparison, the replay, the second corpus and the text-format invariance runs on the deployed build; commit the reports.
- Write the one-page MVP note: what works, test results (accuracy, citation accuracy, outdated rate, conflict recall, latency, genericity), what is left, and what changed after the discovery call (continuous ingestion, bitemporal graph, governance, any-format parsing).
- Check that the links open without login.

---

## After the MVP

**Phase 11 — Distribution (gate B, basics).** Answer recall: when a fact's interval closes, notify every user whose `answers_log` entry cited it in the last 7 days. Acknowledgements: `POST /changes/{id}/ack` and an owner counter ("41 of 120 have seen this"). Changes page with acknowledgement meters and a daily digest (DESIGN.md section 5). Live updates through `GET /stream` (server-sent events), replacing polling. Draft SOP edit text for each approved change.

**Phase 12 — Tacit capture (T10).** `/capture/sessions` plus the Expert capture page (DESIGN.md section 5): a chat that interviews an expert with five questions about supplier habits, fills `{supplier, habit, trigger, what_to_do, evidence, author, date}`, checks each entry against the current rules (compatible, or a conflict to review), and sends it to a named reviewer. Approved entries become passages and practice facts linked to vendor entities, so they appear as expert tips and in `/context`. Seed it with the 21 vendor habit notes and the two interviews.

**Phase 13 — More formats and channels (gate B for the first three).**
- Vision fallback for scanned PDFs and images (parser tier 3), PPTX, and the watched folder.
- The full format-invariance matrix: PDF, scanned PDF, Markdown, HTML, PPTX, XLSX, email text (scanned: fact F1 ≥ 0.8).
- Entity timeline page.
- Teams chat export (JSON) connector.
- Whisper transcription of a recorded 3–5 minute walkthrough into timestamped passages, with a timestamp cited in an answer.
- Optional: a v3.1 → v4.0 redline generated from fact differences; a Graphiti baseline run on the second corpus to compare entity resolution quality and cost per document.

**Phase 14 — Analytics and business case.** Analytics page (DESIGN.md section 5): most-asked topics, unanswered questions, most-cited content, knowledge latency, acknowledgement rates. Run the Teams replay and the business-case model (TEST_PLAN level 12). Run usability tests with five people (level 13).

**Phase 15 — Rehearsal and final.** Freeze code the day before the internal auction. Run the full test plan on the deployed build. Rehearse the live demo script:

1. Drop a new document on Sources and watch it reach "published"; show the entity and its history on the timeline.
2. Ask T1; show the current rule and the "older sources" line; change the as-of date to 1 Mar 2026 and show the old rule.
3. Ask T5; show the working.
4. Ask T8; show the "don't know" route, send it to the expert, answer it as the expert, approve it as the owner, and show the question re-asked with a citation to the expert's reply.
5. Run the conflict scan; show 12 or more conflicts with both passages.
6. Send the Infra FC email; show the provisional change, the banner, answer recall and the acknowledgement count.
7. Send the spoofed bank email; show it held as high-risk.
8. Drop in the second company's documents; ask it a question with a citation.

After the internal auction, fix only what the panel raised.

**Phase 16 — Product hardening (not scheduled).** Live connectors with incremental sync (Drive, SharePoint, Gmail/Outlook, Slack, Teams, Confluence, Notion, ERP read connectors); tenant isolation, SSO and document-level access control carried through to answers; communities (Zep's third tier) for broad summary questions; a plug-in builder that drafts calculators from plain-language descriptions; an MCP server and SDK; partitioned fact tables or a graph store if a tenant passes about 10M facts and multi-hop queries dominate.
