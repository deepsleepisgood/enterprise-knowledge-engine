# PS-07 Knowledge Engine — MVP scope and roadmap

**Requirement from Abhishek's discovery call:** the product must ingest data continually and keep a **bitemporal knowledge graph** up to date from it. Any company should be able to drop its data in and start using it to extract information, without anyone writing code or configuration for its domain first.

**What this changes.** The first version of BUILD_PLAN treated the Meridian AP corpus as *the* product: a hand-written domain pack, AP-only calculators, a one-off ingestion run. BUILD_PLAN v2 replaces it. From here on, **the engine is generic and Meridian AP is the first tenant and the evaluation dataset.** Anything AP-specific becomes a plug-in on top of a domain-agnostic core.

---

## 1. Product definition (one line each)

| | |
| --- | --- |
| **Input** | Any mix of company documents and messages, dropped in once and then added to over time |
| **Core** | A bitemporal knowledge graph of entities and facts. Every fact records when it was true in the world and when the system learned it, and links back to its exact source passage |
| **Output** | Cited answers, "what was true on date X", "what changed since Y", conflicts between sources, and a review queue for a process owner |
| **Promise** | Dump data in → answerable within minutes → stays correct as new data arrives |

## 2. Core concepts

**Episode.** One raw unit of input, such as a file, a file version, an email or a chat message. Episodes are stored unchanged, deduplicated by content hash, and never deleted.

**Passage.** A structure-aware chunk of an episode (section, table, transcript turn, email body). It carries a locator so it can be cited.

**Entity.** A node in the graph: a person, role, organisation, client, vendor, policy, parameter, product, document, and so on. Entity types are **induced from the data**, not hard-coded. Variant names resolve to one entity ("Arvana Infra", "Infra BU", "AIL").

**Fact (edge).** `(subject entity) —[attribute / relation]→ (value or object entity)`, with scope (for example client = Infra), a typed value, and four timestamps:

| Timestamp | Axis | Meaning |
| --- | --- | --- |
| `valid_from` | Valid time | When the fact became true in the world (an effective date) |
| `valid_to` | Valid time | When it stopped being true (supersession, expiry) |
| `recorded_at` | Transaction time | When the system learned it |
| `retracted_at` | Transaction time | When the system stopped believing it (a correction or a rejected review) |

Nothing is ever overwritten. A change closes the old fact's interval and opens a new one. That makes two kinds of question answerable:
- *As of*: "What was the price tolerance on 1 Mar 2026?" (valid time)
- *As known at*: "What would the engine have told someone on 10 Nov?" (transaction time; this is what audits and answer recall need)

**Authority.** Each source has a rank and a scope. The engine proposes the ranking from document type, version numbers, dates and status words ("superseded", "draft"), and the owner confirms it. The resolution rules are in BUILD_PLAN Phase 2 and run over induced types.

**Governance.** The team's decision stands: **a process owner verifies every new or changed rule.** Trusted sender in their own scope on a low-risk topic → published as *provisional* and queued for confirmation. Anything else → *pending*, not applied.

### 2.5 Architecture decision: Zep's data model, on Postgres

We follow the data model of the Zep paper (Graphiti engine): raw **episodes**, an **entity and fact-edge** layer with bi-temporal validity, and edges that are closed rather than deleted. We implement it on Postgres rather than adopting the Graphiti library.

| | Zep / Graphiti | Our engine |
| --- | --- | --- |
| Episode layer (raw input, never deleted) | Yes | Yes |
| Entities and fact edges | Yes | Yes, with typed values and scopes |
| Bitemporal validity and invalidation | Yes | Yes (`valid_from`/`valid_to`, `recorded_at`/`retracted_at`) |
| Which fact wins in a contradiction | The newer one | **Source authority first**, then effective date. A stale document ingested later never overrides a better-ranked one |
| Publishing | Written directly to the graph | **Owner review** for changes from non-owners and high-risk topics |
| Citations | Back to episodes | Back to the exact passage, with its position in the original file |
| Community layer | Yes | Post-MVP |
| Storage | Neo4j or FalkorDB | Postgres + pgvector, behind a repository layer (`app/store/`) |

Algorithms borrowed from Graphiti: entity resolution by candidate search then LLM confirmation; comparing a new fact only against related existing facts; graph-hop expansion in retrieval. A Graphiti run on the second corpus is an optional baseline for comparison.

**Why Postgres scales for us.** The scaling limit is LLM calls per document, not the database. Controls: re-extract only changed passages, triage before extraction, cache every extraction, run ingestion as async workers, and never compare a new fact against the whole graph. Storage side: `tenant_id` on every table from day one, GiST range indexes for bitemporal queries, HNSW for vectors, partitioning by tenant later. A graph store becomes worth it only if multi-hop traversal dominates at about 10M facts per tenant.

## 3. The ingestion loop

Every new episode, whether from the first bulk dump or the hundredth email, goes through the same pipeline:

```
Connector → store raw episode → hash dedupe → redact PII → parse to passages
 → (if this is a new version of a known document: diff, keep only changed passages)
 → triage (rule change / fact / question / practice tip / noise)
 → extract entities and facts (typed values, scope, dates resolved against the episode date)
 → entity resolution (embedding match + LLM confirm)
 → match each fact against the graph: same / update / conflict / new
 → governance: publish, provisional, or pending review
 → publish in one transaction: close old intervals, open new ones, bump kb_version, write a change row
 → re-index passages for search
```

It runs as a background worker on a Postgres-backed job queue, so dumps of hundreds of files don't block the API. Each episode shows its status in the UI: queued, parsed, extracted, published, or waiting for review.

**Schema induction (cold start).** On a tenant's first dump the engine samples the corpus and proposes an ontology: entity types, topics and parameters with synonyms, source types, and a draft authority ranking and risk list. The owner reviews and edits it on one Setup screen, and it is frozen as `schema v1`. Topics found later are proposed incrementally through the review queue. This replaces the hand-written `plugins/ap/baseline_schema/`. The hand-written schema is kept only as an **evaluation baseline**, so we can show how close the induced schema gets.

### 3.5 Handling any document in any format

**Principle: nothing downstream may know what a Meridian SOP looks like.** The first version of BUILD_PLAN hard-coded Meridian's layout (numbered headings, "Part A–F", `**[mm:ss] Speaker:**`). All of that moves out of the core. The core only sees a **canonical block list**, and every format-specific or template-specific rule becomes a replaceable hint.

**Layer 1: Normalise (format → blocks).** Every file becomes an ordered list of typed blocks:
`{type: heading | paragraph | list_item | table | table_row | turn | quote | figure | header_footer, text, level?, page?, bbox?, time_range?, speaker?, style?}`.
Detection is by file signature (libmagic), not file extension. Parsers run as a cascade, cheapest first:

| Tier | Handles | How |
| --- | --- | --- |
| 1. Native | docx, xlsx/csv, pptx, html, md/txt, eml/mbox, json, vtt/srt, text-layer PDF | Direct parsers that keep real structure (styles, numbering, tables, slide order, thread headers) |
| 2. Legacy | .doc, .ppt, .xls, .rtf, .odt | Convert to the modern format with LibreOffice headless, then Tier 1 |
| 3. Vision fallback | Scanned PDFs, images, photos of printouts, PDFs with broken text or tables | Render each page to an image, then a vision model returns structured markdown with tables and reading order |
| 4. Media (post-MVP) | Audio, video | Whisper with timestamps and speaker labels, then the same turn blocks as transcripts |
| 5. Unknown | Anything else | Best-effort text extraction; if that fails, store the file as an opaque episode and flag it on the Sources screen |

**Layer 2: Infer structure (blocks → passages).** Structure is inferred from evidence, in this order:
1. Explicit signals: style names, numbering lists, table of contents, slide titles, email headers.
2. Visual signals: font size and weight relative to body text, spacing, all-caps lines, short lines followed by long ones.
3. Numbering patterns (`4.2`, `Part C`, `Q1.`), used as hints only, never required.
4. **LLM structure repair** when 1–3 give a flat or doubtful outline: the model gets the candidate headings and assigns levels.
5. **No structure at all:** split at topic boundaries, with a 200–400 token window and overlap as the last resort.

Chunking by type:

| Content | Passage rule |
| --- | --- |
| Sections | One per leaf section; long ones are split at paragraph boundaries and keep their heading path |
| Tables | Kept whole if small; otherwise one passage per row with the header repeated |
| Spreadsheets | Each row becomes a record; column headers name the attributes; a sheet description is stored once |
| Transcripts, chat | One passage per turn or short window; the question joins its answer |
| Email | Strip quoted replies and signatures, keep headers as metadata, one passage per message |
| Slides | One passage per slide, including speaker notes |
| Q&A, FAQ | One passage per question and answer pair |

Every passage gets a **context header** (document title, type, version, date, heading path), so retrieval and extraction work on any layout.

**Layer 3: Infer document metadata.** Document type, version, date, status, owner, client scope and "supersedes" are read from, in order: file properties, filename, header tables and first-page text, footers, then an LLM classifier. Each value stores its source and a confidence. Low confidence is shown on the Sources screen for the owner to correct once. **Date precedence, which matters for bitemporal correctness:** an explicit effective date in the text, then the document date in the header, then the email sent date, then the file modified time, then the ingestion time. The winning source of every date is recorded.

**Layer 4: Format-independent extraction.** The fact extractor reads passage text plus its context header, and the induced schema tells it what to look for. It never sees formats or layouts. Tables use a variant of the same prompt that includes the header row.

**Citations survive any format.** The original file is always kept. Every passage stores the page and box (PDF, image), cell range (spreadsheet), slide number, character offsets (text) or time range (media). The source drawer shows the passage highlighted in the original, and a verifier check confirms the quote exists in the extracted text.

**Quality gates (so bad parsing is caught, not trusted).** Each episode gets a parse-quality score: extracted characters versus expected, junk-character ratio, heading and table integrity, and OCR confidence. A low score escalates to the next tier; if it is still low, the episode is marked "needs attention" and its facts are held for review rather than published.

**Locators stay compatible with the evaluation set.** Where a detected number label exists (`4.2`, `Part C, step 3`), it becomes part of the locator, so Meridian's gold section references still resolve. Where none exists, the locator is the heading path plus page.

**Proof: format-invariance test (MVP acceptance).** Take the Meridian SOP and re-render it as PDF, scanned PDF (image only), Markdown, HTML, PPTX, XLSX tables and pasted email text. Run each version through the pipeline. Pass if the extracted facts match the docx baseline (fact-level F1 ≥ 0.9 for text formats, ≥ 0.8 for scanned) and the 92 scenario answers do not change. Gate A covers the text formats and a flat docx with no heading styles; gate B adds PPTX and the scanned PDF. The second corpus (4.6) is deliberately built with different structure: no numbered headings, mixed formats.

---

## 4. MVP: what is in

### 4.1 Ingestion and connectors

| In the MVP | Detail |
| --- | --- |
| Drag-and-drop upload (single files, folders, zip) | Web UI plus `POST /episodes/upload` |
| Watched folder | A local or mounted directory polled every 30 s; new or changed files become episodes. This simulates "keep dumping" |
| Email | `.eml` upload plus `POST /episodes` for raw text; IMAP polling of one mailbox if time allows |
| Generic API | `POST /episodes` with `{channel, sender, received_at, text or file}`, so any system can push data in |
| File types | Tiers 1–3 of section 3.5: `.docx`, `.pdf` (text and scanned), `.xlsx`/`.csv`, `.pptx`, `.html`, `.md`/`.txt`, `.eml`, `.vtt`/transcripts, images, and legacy Office files via LibreOffice. Unknown types are stored and flagged |
| Incremental updates | Dedupe by hash; when a new version of a document arrives, diff by passage and re-extract only the changes |
| Replay mode | Feed a dated corpus in chronological order (SOP v3.1 2023 → FAQ → videos → SOP v4.0 2026 → memos → emails) and watch the graph evolve. This is the main demo of continuous updating |

### 4.2 Graph

- Postgres + pgvector, keeping the current stack. Tables: `episodes`, `passages`, `entities`, `entity_aliases`, `facts` (bitemporal), `conflicts`, `review_items`, `kb_versions`, `changes`, `schemas`. The existing `claims` table generalises into `facts`.
- Schema induction plus the owner's Setup screen.
- Entity resolution with an alias table, including owner merge and split.
- Temporal extraction: explicit dates, relative dates ("from next Monday") resolved against the episode's `received_at`, and expiry dates ("valid till 31 Mar 2027").
- Supersession and conflict detection on every write, and a full conflict scan on demand.
- Query API: `get_facts(entity, attribute, scope, valid_on?, known_at?)`.

### 4.3 Answering

- Hybrid retrieval: full-text plus vector search with RRF fusion, scope filtering, and current facts injected from the graph.
- Cited answer cards exactly as in DESIGN.md: citations, older sources, expert tip, abstain and route-to.
- **Time travel:** an "as of" date picker on the Ask page; answers and citations reflect that date.
- **"What changed since"** feed by kb_version and date.
- Verifier: citations exist, numbers are grounded, no superseded values appear, and each sentence is supported. An answer that fails is withheld from processors.
- **Grounding guardrails:** scope guard, closed-book generation with a passage id on every sentence, retrieval gate, verifier, deterministic numbers, injection resistance, audit log and a "report a wrong answer" button. Tested directly by removing the supporting passages and checking that the engine abstains (TEST_PLAN level 8).
- **Plug-in calculators:** the six AP calculators (price, quantity, TDS, approvals, MSME, e-invoice) stay, but are registered as a *domain plug-in* that reads its thresholds from the graph. The core never imports them. This is how we keep 92/92 on the scenario questions without making the core AP-specific.

### 4.4 Governance and review

- Sender authority rules, induced and then confirmed by the owner: who may change which topic, for which scope.
- Risk tiers: high-risk topics (bank changes, payments, approvals, tax) always go to review.
- Review queue with approve / reject / edit and a `row_version` lock.
- Every published change is attributable: the episode, the sender and the reviewer.
- **Escalation to an expert:** a question the knowledge base cannot answer (or an answer that fails verification) can be sent to the routed expert from the route card. The expert's reply goes to the asker immediately, labelled as not yet in the knowledge base, and enters the pipeline as an `expert_answer` episode under the same governance as any change. After approval the question is re-asked and answered with a citation. In-app notifications only.

### 4.5 UI (in DESIGN.md's style)

The existing pages are Ask, Changes, Conflicts and Review queue. Three new ones:
1. **Sources**: drop zone, connector status, and an episode log with per-item pipeline status and errors.
2. **Setup**: the induced schema (entity types, topics, authority ranking, risk list), editable, with "freeze schema".
3. **Entity timeline**: one entity, its facts, and each fact's history as horizontal bars on a time axis, each bar linking to its source. This is the visual proof of the bitemporal graph.

### 4.6 Proof that it is generic (MVP acceptance, not a stretch goal)

- The Meridian AP corpus is ingested **with no hand-written pack**: induced schema only, plus owner edits made through the UI.
- A **second, small, unrelated corpus** is ingested through the same drop zone with zero code changes: a synthetic HR leave policy in mixed formats (v1 docx, v2 PDF, FAQ in Markdown, a department memo in HTML, an announcement email, an entitlement spreadsheet). It must answer 10 questions with citations, including one "as of" question, one superseded rule, one department override and one abstention.

### 4.7 MVP acceptance criteria (gate A unless marked)

| Area | Bar |
| --- | --- |
| Scenario questions | 92/92 correct, or each miss documented |
| QA evaluation set | Accuracy, citation accuracy and outdated-answer rate reported on dev and holdout (targets as in TEST_PLAN.md) |
| Conflict recall | ≥ 12 of 15 known conflicts |
| Induced vs hand schema | Report topic and parameter coverage; answer accuracy with the induced schema within 5 points of the hand-written schema |
| Continuous update | Replay test: after each episode, a fixed set of "as of" probes returns the right value. The Infra 7% email changes the answer from its effective date onwards, not before |
| Freshness | Single email → answerable in < 60 s; 50-document dump → answerable in < 15 min |
| Governance | TEST_PLAN level 9 routing table passes, including the spoofed bank-change email being held |
| Genericity | Second corpus: 10/10 questions answered with citations, no code changes |
| Format invariance | Same SOP as PDF, Markdown, HTML, XLSX, email text and a flat docx: fact F1 ≥ 0.9 against the docx baseline, scenario answers unchanged (gate A). Scanned PDF (≥ 0.8) and PPTX (gate B) |
| Deployed | One public URL; T1–T9 runnable from the UI by a non-technical teammate |

### 4.8 Explicitly not in the MVP

- Live SaaS connectors: Google Drive, SharePoint, Confluence, Slack, Teams, Gmail OAuth
- Audio/video transcription (scanned PDFs and images ARE in, through the vision fallback)
- Real authentication, multi-tenant isolation, SSO, and per-document access control (the MVP is one tenant with a role switch)
- Answer recall notifications, acknowledgement tracking, live SSE stream (the MVP polls)
- Tacit-knowledge interview capture (T10)
- Analytics page
- A graph database (Neo4j or similar). Postgres is enough at this size
- Communities (Zep's third tier, clusters of entities with summaries): not needed for rule lookups
- Auto-generated plug-ins (calculators for a new domain are still written by hand)

---

## 5. Delivery gates and build order

BUILD_PLAN.md (v2) has the phases, tracks and day-by-day schedule. The gates:

| Gate | Date | Must be true |
| --- | --- | --- |
| **A: MVP** | Thu 12 Nov | Generic pipeline ingests the Meridian corpus with no hand-written pack; replay shows the graph evolving; T1–T9 and T11 (expert escalation) on the deployed URL; second company answers 10/10; text-format invariance passes (PDF with text layer, Markdown, HTML, XLSX, email text, flat docx) |
| **B: Auction** | Mon 16 Nov | Vision fallback for scanned PDFs and images, PPTX, watched folder, Entity timeline page, the full format matrix, distribution basics |
| **C: Final** | Wed 18 Nov | Tacit capture, more channels, analytics, business case, usability tests |

The 12 Nov date leaves five days for a scope larger than v1's, so it needs three parallel build tracks (core backend; plug-in, evaluation and test data; web). If behind, cut in this order: Entity timeline page → watched folder → reranker → entity merge/split UI → hop expansion → History tab and source drawer → analytics.
**Never cut:** continuous ingestion through the pipeline, bitemporal facts, as-of answers, citations, verifier, calculators, governance, replay, second corpus, deployment.
**Safety net:** `SCHEMA_MODE=baseline` runs the engine on the hand-written schema, so an induction failure can never block the demo.

---

## 6. Beyond the MVP

### Phase A — Final round (internal auction → final)
- **Distribution:** answer recall (when a fact's interval closes, notify everyone whose answer in the last 7 days cited it), acknowledgements with the "41 of 120 have seen this" counter, daily digest, live SSE updates.
- **Tacit capture (T10):** an expert interview chat that writes practice facts linked to vendor entities, with owner review.
- **More channels:** Teams/Slack export (JSON), Whisper transcription of video and audio with timestamped citations.
- **Analytics:** most-asked topics, unanswered questions, knowledge latency (episode received → fact published), acknowledgement rates.
- **Redlines:** auto-generated "v3.1 → v4.0 what changed" documents from fact differences.

### Phase B — Product (if this goes past the competition)
- **Live connectors** with incremental sync and webhooks: Google Drive, SharePoint/OneDrive, Gmail/Outlook, Slack, Teams, Confluence, Notion; ERP read connectors (Tally, SAP) for operational facts.
- **Multi-tenancy and security:** tenant isolation, SSO, document-level ACLs carried through to answers (no one sees facts from a source they can't open), audit log, data residency, PII vault.
- **Plug-in builder:** the owner describes a calculation in plain language → the engine drafts a calculator bound to graph parameters → tests it against examples → owner approves. This removes the last hand-written, domain-specific code.
- **Agents and integrations:** MCP server and REST SDK so other tools and agents can query "the rule as of today" with citations; inline checks inside the ERP invoice screen.
- **Scale:** partitioned fact tables or a temporal graph store when a tenant passes ~10M facts; streaming ingestion.
- **Quality loop:** user feedback on answers turns into evaluation items; drift alerts when the same question's answer changes without a published change.

---

## 7. Open questions to confirm with Abhishek

1. Is "any company can dump data" a demo claim (we prove it on a second corpus) or does the panel expect a live connector to a real system?
2. Which channels does the continuous feed have to cover in the demo: email only, or also chat and new SOP versions?
3. Is an owner-reviewed induced schema acceptable, or must ingestion work with zero human setup?
4. Does the as-known-at axis (transaction time) need to be visible in the UI, or is it enough as an audit API?
5. Does the 12 Nov MVP check expect the genericity proofs (second company, format variants), or only the Meridian case? We plan to show both.
