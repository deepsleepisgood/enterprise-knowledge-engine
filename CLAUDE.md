# PS-07 Enterprise Knowledge Engine — project rules for Claude Code

Read this file and BUILD_PLAN.md before every session. SCOPE.md says what is in the MVP and why. TEST_PLAN.md defines how the work is judged. DESIGN.md is the spec for all UI work.

## What we are building

A **generic knowledge engine**. A company drops its documents and messages in (SOPs, spreadsheets, PDFs, slides, emails, chat exports, transcripts, in any layout) and keeps adding to them. The engine continually updates one **bitemporal knowledge graph** of entities and facts: every fact records when it was true in the world and when the system learned it, links to its exact source passage, and is retired, never deleted, when something newer or more authoritative arrives. On top of the graph it answers questions in seconds with exact citations (including "as of" any date), flags conflicting and outdated content to a process owner, and tells people when a rule they relied on has changed.

Our first tenant and evaluation dataset is Meridian Shared Services' accounts-payable team (a fictional case company; the problem is PS-07). Everything specific to Meridian lives in the **AP plug-in** (`plugins/ap/`): six deterministic calculators, role routing, the invoice picker, and a hand-written baseline schema used only for comparison and as a safety net. **The core under `app/` must never mention Meridian, Arvana, AP section numbers, tax terms or rupee thresholds, and must never import from `plugins/`.** A test enforces this.

The data model follows the Zep/Graphiti paper (episodes, entities, bi-temporal fact edges, invalidation instead of deletion), implemented on Postgres. We differ from Zep deliberately: resolution is by source authority, not "newer wins"; values are typed; changes pass an owner review before going live.

Key dates: MVP (gate A) due **12 Nov 2026** (deployed public URL + one-page note). Gate B / internal auction 16 Nov. Final 18 Nov.

## Hard rules (never break these)

1. **No answer-key leakage.** Application code under `app/`, `web/` and `scripts/ingest_*` must never open `eval/PS-07_qa_evaluation_set.xlsx`. The `known_conflicts` and `questions` sheets are for evaluation only. Document metadata from the `source_index` sheet is copied by hand into `plugins/ap/baseline_schema/sources.yaml`; it is used only for comparison tests and when `SCHEMA_MODE=baseline`. Runtime metadata is inferred from the documents. Few-shot examples in prompts must be written from the SOP, never copied from the questions sheet. A test enforces this (`tests/test_no_leakage.py`).
2. **No hard-coded rule values anywhere.** Plug-in calculators read thresholds (₹500, 1%, 45 days…) from current facts in the graph through `app/graph/rules.py` and the plug-in's bindings. If a required parameter or binding is missing, raise an error. Never silently fall back to a default.
3. **All LLM calls go through `app/core/llm.py`.** It redacts PAN, bank account numbers, IFSC codes and phone numbers before sending, logs every call (redacted), records tokens and cost, and sets temperature 0. Vision calls use the same gateway.
4. **Every answer cites its sources, and only from the knowledge base.** If the verifier cannot confirm an answer after one retry, processors do not see the draft: they get the not-covered card. If the corpus does not support an answer, say so, route to a named role, and let the asker send the question to that expert. Never answer from general knowledge. Never give tax advice beyond what the documents say.
5. **Never present an outdated rule as current.** Older sources may appear only in the `older_sources` field of the answer card, labelled with what superseded them and when. For an `as_of` question, "current" means the rule valid on that date.
6. **Facts are retired, never deleted.** Close the valid-time interval (`valid_to`) and the transaction-time interval (`retracted_at`); keep the row. Episodes and original files are never deleted.
7. **Publishing is one transaction.** Retiring the old fact, adding the new one, bumping `kb_version` and recording the change happen together or not at all.
8. **Reproducible builds.** Cache every LLM extraction result on disk keyed by a hash of (prompt version + input text), so re-running ingestion gives the same graph.
9. **Authority beats recency.** A newer fact from a lower-ranked source never overrides a higher-ranked one. Practice facts (expert habits) never override rules. A change from anyone other than the registered owner of that scope, or on a high-risk topic, is held as pending for the process owner.
10. **The core is format- and domain-agnostic.** Parsers produce a canonical block list; nothing downstream depends on layout, numbering style or file type. Anything that only makes sense for one company goes in a plug-in.
11. **Every table has `tenant_id`, and all graph reads and writes go through `app/store/`.** No other package imports table models or writes SQL against graph tables.
12. **Never compare a new fact against the whole graph.** Fetch only related facts (same subject and attribute, or nearest neighbours by embedding).
13. **An expert's reply is input, not a rule.** Replies to escalated questions enter as episodes and pass the same triage, extraction and governance as an email. Nothing an expert writes changes the knowledge base until governance allows it.

## Stack

- Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2 + psycopg 3
- Postgres 16 with pgvector, `pg_trgm` and `btree_gist` (local via docker compose; deployed on Neon or Supabase). Bitemporal intervals are stored as timestamptz pairs with GiST range indexes
- Background work: a Postgres job queue (`SELECT … FOR UPDATE SKIP LOCKED`) and `app/worker.py`
- Retrieval: Postgres full-text search + pgvector cosine, fused with reciprocal rank fusion; embeddings and reranker via `fastembed` (`BAAI/bge-small-en-v1.5`, reranker `BAAI/bge-reranker-base`) running locally on CPU
- LLMs via the `anthropic` SDK: `claude-haiku-5-5` for triage, routing and structure repair, `claude-sonnet-5-5` for schema induction, extraction, judging, answering, verification and vision. Model names come from env vars `MODEL_FAST` and `MODEL_SMART`
- Documents: `python-docx`, `openpyxl` + `pandas`, `python-pptx`, `PyMuPDF`, `beautifulsoup4`, `python-magic` (libmagic) for type detection, LibreOffice headless for legacy Office files
- UI: Next.js 14 (App Router) + TypeScript + Tailwind CSS + lucide-react in `web/`, built exactly to DESIGN.md (light, rose accent, Hanken Grotesk + Inter + JetBrains Mono). It calls the FastAPI backend over HTTP only; no business logic in the frontend
- Tests: `pytest`; lint: `ruff`; frontend: `eslint`, `tsc --noEmit`, Playwright for UI smoke tests
- Deploy: API and worker as Docker services on Render; web app on Vercel; Postgres on Neon

## Repository layout

```
CLAUDE.md  SCOPE.md  BUILD_PLAN.md  TEST_PLAN.md  DESIGN.md  PROGRESS.md
data/raw/                      four corpus .docx files
data/ops/PS-07_ap_operations.xlsx
eval/PS-07_qa_evaluation_set.xlsx      evaluation only, never read by app code
eval/                          paraphrases.csv, abstain.csv, adversarial.csv, replay_probes.csv,
                               entity_aliases.csv, episodes_expected.csv, judge/
plugins/ap/                    plugin.yaml, bindings.yaml, roles.yaml, calc/ (price, quantity, tds,
                               approvals, msme, einvoice, registry), loaders/ (vendors, invoices),
                               baseline_schema/ (hand-written schema + sources.yaml; comparison only)
synthetic/                     emails/*.eml, teams_export.json, corpus2_hr/ (second company),
                               variants/ (SOP rendered in other formats)
app/core/                      config, db, llm gateway, redaction, versioning
app/store/                     repository layer: the only code that touches graph tables
app/ingest/                    connectors/, parsers/, segment, metadata, versions, pipeline
app/graph/                     induce, extract, entities, resolve, conflicts, rules
app/plugins/                   plug-in registry and binding resolution (loads plugins/*)
app/answer/                    router, retrieve, generate, verify, card
app/govern/                    authority registry, review queue
app/distribute/                changes, acknowledgements, answer recall
app/capture/                   expert capture flow
app/api/                       FastAPI routers
app/worker.py                  job runner
web/                           Next.js app (see DESIGN.md); web/fixtures/ for mock answer cards
scripts/                       ingest_all.py, build_graph.py, run_eval.py, run_replay.py,
                               run_format_invariance.py, run_second_corpus.py, render_variants.py,
                               conflict_report.py
tests/                         unit/, integration/, acceptance/
reports/                       evaluation outputs (committed)
```

## Commands

```
.\run.ps1                             # everything at once: db, API, worker, web; Ctrl+C stops all
                                      # (run.cmd from cmd; scripts/run_app.py elsewhere)
                                      # files dropped in data/inbox (WATCH_DIR) are ingested
                                      # live inputs wait for owner approval (GOVERNANCE)
docker compose up -d db
python -m app.worker                  # background jobs
python scripts/ingest_all.py          # drop data/raw through the upload connector
python scripts/build_graph.py         # induce schema, extract, resolve, conflicts
uvicorn app.api.main:app --reload
cd web && npm run dev                # http://localhost:3000
pytest -q
python scripts/run_eval.py --split dev     # or holdout / all / ablation
python scripts/run_replay.py          # continuous-update probes
SCHEMA_MODE=baseline python scripts/build_graph.py   # hand-written schema instead of induced
```

## Working style

- Work one phase of BUILD_PLAN.md at a time. Start each phase in plan mode, then implement.
- A phase is done only when its acceptance criteria pass. Run `pytest -q` before saying so.
- After each phase, append a short entry to PROGRESS.md (what was built, test results, open issues) and commit.
- If a requirement is ambiguous, write the assumption in PROGRESS.md and continue. Stop and ask only before changing the API contract or the database schema in a breaking way.
- Keep functions small, type-hinted, and covered by tests. Prefer boring, explicit code.
- When tempted to special-case a document, a company or a file format in the core, stop: make it a signal the parser or schema can detect, or move it into a plug-in.
