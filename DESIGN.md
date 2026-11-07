# PS-07 Knowledge Engine — UI design spec

The web app follows the "AI Answer Engine UI (Rose Research Assistant with Cited Answers + Sources)" pattern from the Superdesign library: a light, Perplexity-style answer screen with inline numbered citations that trace to a sources rail. This file adapts that design to our engine. Where the reference shows web search results, we show SOP sections, client memos, desk instructions, spreadsheet rows, slides and transcript timestamps from whatever a company has dropped in.

Reference: https://superdesign.dev/library/ai-answer-engine-ui-rose-research-assistant-with-cited-answers-sources

Use the reference for look and feel only. Do not copy its brand text (for example its model-picker label); every label here is ours.

The product is generic: no label in the shell may say "Meridian" or "accounts payable". Domain-specific cards (decision row, working card, invoice picker) appear only when the answer card contains the data for them, which comes from an installed plug-in.

## 1. Stack

- Next.js 14 (App Router) + TypeScript + Tailwind CSS, in `web/`
- Icons: `lucide-react`
- Fonts via `next/font/google`: Hanken Grotesk (600, 700), Inter (400, 500, 600), JetBrains Mono (400, 500)
- Data: typed fetch client generated from the FastAPI OpenAPI schema (`openapi-typescript`); SWR for polling `/changes`, `/version` and `/episodes`
- Deploy on Vercel; `NEXT_PUBLIC_API_BASE_URL` points to the Render API. The FastAPI app enables CORS for the Vercel domain.
- Until the API is ready, build against fixtures in `web/fixtures/*.json` that match the answer-card schema exactly (one fixture each for T1, T5, T8, a conflict, and an as-of answer), plus fixtures for the episode list, the induced schema and an entity timeline.

## 2. Design tokens

Put these in `tailwind.config.ts` under `theme.extend` and use only these.

| Token | Value | Use |
| --- | --- | --- |
| `canvas` | `#f5f6f8` | App background (cool paper) |
| `surface` | `#ffffff` | Cards, rails, composer |
| `ink` | `#14161b` | Headings and body text |
| `muted` | `#5b6472` | Meta text, labels, domains |
| `hairline` | `#e6e8ec` | Borders and dividers |
| `fill` | `#eef0f3` | Subtle fills, hover rows, neutral pills |
| `rose` | `#e11d48` | The single accent |
| `rose-hover` | `#be123c` | Accent hover |
| `rose-tint` | `#fff1f3` | Active source card background |
| `rose-line` | `#fbcfd8` | Active source card border |

The rose accent is used sparingly: brand glyph, inline citation chips, links, the active tab underline, the active source card, the active nav indicator, the send button, and the "now" marker and current-fact bar on the Entity timeline. Nothing else.

Rules that come from the reference and must hold: light mode only; no purple, indigo, violet, teal or emerald; no dark backgrounds; do not centre everything.

Status states we need that the reference doesn't have, kept within the palette:
- **Provisional / Unverified / Pending review / Needs attention:** a neutral pill (`fill` background, `muted` text) with a small icon (`Clock`, `ShieldAlert`, `FileWarning`). No new colours.
- **Superseded:** source text in `muted` with the value struck through, plus a mono label "superseded 31 Mar 2026".
- **Changed-rule banner:** a white card with a 3px rose left border.
- **Pipeline status** (queued, parsed, extracted, published): neutral pills; the current step has a small rose dot.

Type scale:
- Question heading: Hanken Grotesk 700, 28–32px desktop, 24px mobile, tight leading
- Section labels and eyebrows: Hanken 600, 12px, uppercase, letter-spacing 0.06em, `muted`
- Body: Inter 400, 15–16px, line-height 1.65, `ink`
- UI text: Inter 500, 13–14px
- Mono (citation numbers, file names, locators like `§4.2` or `[04:30]`, kb_version, dates, exception codes such as `PRICE_VAR`): JetBrains Mono 11–13px

Shape: cards `rounded-2xl`, chips and pills `rounded-full`, hairline borders, soft shadow on white cards only (`shadow-[0_1px_2px_rgba(20,22,27,0.04),0_4px_12px_rgba(20,22,27,0.04)]`), generous whitespace.

## 3. App shell

A three-zone frameless layout, `min-h-screen`, max width 1440px, centred:

| Zone | Size | Contents |
| --- | --- | --- |
| Left nav rail | 64px, white, hairline right border, sticky, full height | Brand glyph (rose sparkle) on top; nav icons; avatar with role switch pinned at the bottom |
| Main column | flex-1, `max-w-[760px] mx-auto`, `min-w-0` | The page content |
| Right rail | 320px (`xl:` 360px), hairline left border, sticky, full height, internal scroll | Sources, or context for the page |

Below `lg` the right rail drops out and its content stacks below the main column as its own section. Below `md` the left rail becomes a fixed top bar with a hamburger menu. No horizontal overflow at 390px.

**Nav icons** (active item: rose 2px left-edge indicator and ink icon; others `muted`):

| Icon | Page | Who |
| --- | --- | --- |
| `Search` | Ask | Everyone |
| `Bell` with a rose count dot | Changes | Everyone |
| `Upload` with a count dot for items needing attention | Sources | Owner |
| `GitCompare` | Conflicts | Owner |
| `Inbox` | Review queue | Owner |
| `SlidersHorizontal` | Setup | Owner |
| `Network` | Entities (timeline) | Owner, experts |
| `BookUser` | Expert capture | Experts, reviewers |
| `BarChart3` | Analytics | Owner |

The avatar menu switches between Processor and Process owner. No real auth for the MVP; the role is stored in `localStorage` (wrapped in try/catch).

## 4. Ask page — maps to the answer card

Main column, top to bottom:

1. **Change banner** (only when `/changes?since=<last seen>` returns items): "1 rule changed since you last looked · Infra bulk-material tolerance 5% → 7% from 16 Nov · provisional". Link to Changes; an "Got it" button calls `POST /changes/{id}/ack`.
2. **Eyebrow row:** rose sparkle + `ANSWER`, then on the right in mono: client chip (e.g. `Arvana Infra`), the `as of` chip when a date other than today is set (e.g. `as of 1 Mar 2026`), and `kb v42`.
3. **Question** as the large Hanken heading.
4. **Tabs:** Answer / Sources / History. Active tab has a rose underline. History lists `older_sources` and earlier answers to the same question at older kb versions.
5. **Source-chip strip:** one `rounded-full` white chip per citation, in citation order: a 16px square with the document-type glyph (see section 6), the short locator in mono (`SOP v4.0 §4.2`, `CM-PHA-01`, `Interview 1 [02:30]`), and the rose citation number. Trailing `+N` overflow chip. Scrolls horizontally on mobile with hidden scrollbars.
6. **Status line**, only if not plain "answered": neutral pill such as `Provisional — owner confirming`. An answer that fails verification is never shown to processors (they get the not-covered card below); the process owner sees the draft with an `Unverified — citation could not be confirmed` pill. For an `as_of` answer: `Rule in force on 1 Mar 2026 — superseded since 1 Apr 2026`.
7. **Answer body** (`rule.text`), rendered from the card:
   - Paragraphs with inline citation chips: the API returns markers like `[1]`; render each as a rose superscript in JetBrains Mono, 10–11px, a hair of left margin, tappable. Hover or tap highlights the matching source card in the right rail (and scrolls it into view).
   - **Decision row** for calculator routes: a check-bullet list (rose `CircleCheck` or `CircleX` icons): decision, exception code in mono, who acts next.
   - **Working card** for calculator routes: a `rounded-2xl` white card with a hairline header row (Step / Value) and hairline-divided rows, e.g. "Excess on line · ₹2,500", "1% of PO line value · ₹1,975", "Cap · ₹500", "Limit (lower of the two) · ₹500". Labels in `muted`, values in ink, numbers in mono.
   - **Current vs older card** when `older_sources` is not empty: three columns (Topic / Current rule / Older sources say). The current value in ink with its citation chip; the older value struck through in `muted` with "SOP v3.1 §3 · superseded 31 Mar 2026" in mono. This replaces the reference's Feature / RAG / Fine-tuning table and is the visual proof of version awareness.
   - **Expert tip card** (`expert_tip`): white card, `BookUser` icon, "Expert practice" label, the tip text, then mono attribution "Lakshmi Reddy · Interview 1 [02:30] · approved by AP Process Excellence". Clearly separate from the rule.
   - **Not covered** (status `unsupported`): one plain sentence "The documents don't cover this." and a route card: role name, why, and a rose-outline **Send to {role}** button (e.g. "Send to the Tax Desk"; generic fallback "Send to the process owner"). After sending, the card shows a neutral `Sent to {role} · waiting` pill. When the expert replies, the change banner area shows "Your question was answered" and the reply appears as an expert tip card labelled "Expert reply — not yet part of the knowledge base" until the owner confirms it; then the question is re-asked automatically and answered with a citation. Never show invented content.
   - Every answer card has a small "Report a wrong answer" text action in its footer.
8. **Related:** label `RELATED` with a `Layers` icon, then 3–4 hairline-divided rows from `card.related` (leading `Plus` icon that turns rose on hover, question text, trailing `ChevronRight`). Clicking asks that question.
9. **Composer** at the end of the column, in normal flow (never fixed over the answer): a `rounded-2xl` white card with soft shadow; an auto-grow textarea "Ask about a rule, a document or an entity…"; bottom row with:
   - a `Paperclip` button that opens the **invoice picker** (shown only when an installed plug-in provides one; the AP plug-in's simulated ERP: choose an invoice from the operations data; its id goes into `invoice_id`),
   - a pill **client chip** with a rose dot and caret (the scopes the schema knows, plus "All"), in place of the reference's model picker,
   - an **as-of pill** with a `CalendarClock` icon: "Today" by default; opens a date picker; when set, the question is sent with `as_of` and the pill shows the date,
   - a round rose send button with an `ArrowRight` icon.

**Right rail on the Ask page:**
- If an invoice is attached: an **Invoice context** card first, from `/context`: invoice id and vendor in mono, MSME due date and payment run, e-invoice requirement, and approved supplier habits ("Adds /A when re-sending").
- Then `SOURCES` with a count. One card per citation: document-type glyph, section title in semibold (e.g. "4.2 Price tolerance"), the file and status in mono muted (`PS-07_AP_SOP_v4.0 · current`), a two-line clamped quote, and a circular citation-number badge. The card for the citation being hovered (default: citation 1) is tinted `rose-tint` with a `rose-line` border and a filled rose badge. Clicking a card opens a drawer with the full passage, its version, date and status, and the **original document** with the passage highlighted (page and box for PDFs and images, cell range for spreadsheets, slide for decks, timestamp for transcripts), from `/passages/{id}` and `/episodes/{id}/original`.
- Below, an `OLDER SOURCES` group for superseded passages, styled muted with the struck-through value and the superseded date.
- Footer button "Show all N sources".

**Loading state:** skeleton lines in `fill` for heading, chips and three paragraphs; the right rail shows three skeleton cards. Answers usually take a few seconds, so show "Checking the documents and the rules in force…" in muted text.

## 5. Other pages (same shell)

**Sources** (owner) — the place to feed the engine.
- Main column, top: a large dashed-border drop zone (`rounded-2xl`, hairline border, `Upload` icon): "Drop documents, folders or emails here", with a "Choose files" button and the supported types in muted mono (`docx pdf xlsx pptx html md eml txt vtt` and images). Below it, small connector cards: Upload (active), Email (`.eml`), API endpoint (shows the URL), Watched folder (when enabled), each with a status pill. A **Replay corpus** button runs the dated corpus through in order for demos.
- Below: the **episode log**, newest first. Each row: file or subject, channel glyph, received time in mono, the pipeline status pills (queued → parsed → extracted → published), parse tier and quality in mono (`tier 1 · q 0.97`), and counts (`23 passages · 14 facts`). A row that is held shows `Needs attention` or `Pending review` with the reason; a failed row shows its error and a Retry button. Clicking a row opens its facts and passages.
- **Metadata check:** where document type, version, date or status was inferred with low confidence, the row shows the inferred values as editable chips with their origin in mono (`from header`, `from filename`) so the owner can correct them once.
- Right rail: totals (documents, passages, facts, entities), kb version, queue depth.

**Setup** (owner) — what the engine learned about this company.
- A header with the schema version and a `Draft` or `Frozen` pill, and a rose **Freeze schema** button.
- Sections, each a white card with hairline-divided rows, all editable inline: **Entity types** (name, count), **Attributes** (key, label, synonyms as chips, value type, unit, risk flag), **Source authority** (documents types in rank order, drag to reorder, with the reason the engine proposed), **High-risk topics**, **Who may change what** (sender or role → topics and scope), **Plug-in bindings** (each plug-in parameter with the attribute it was bound to, a confidence value in mono, and Confirm; unresolved bindings are listed first).
- **Entities** tab: search, list with aliases, Merge and Split actions.
- Right rail: "Proposed by the engine" with the sample it learned from, and new-attribute proposals waiting for review.

**Entities / timeline** (owner, experts) — the visual proof of the bitemporal graph.
- Entity header: name, type, aliases as chips.
- A time axis (months, mono labels) with one horizontal row per attribute (and scope). Each fact is a `rounded-full` bar spanning its valid interval, labelled with its value; the current fact's bar is rose, superseded bars are `fill` with muted text and the value struck through. A thin rose vertical line marks "now"; a draggable marker sets the as-of date and the page shows the values in force.
- A second toggle, **Known at**, replays what the engine believed on a given date (transaction time): bars appear or change as the toggle moves.
- Clicking a bar opens the fact: statement, value, scope, source chip, recorded and retracted times.
- Right rail: the facts list with filters (attribute, scope, status).

**Changes** — main column: list of change cards, newest first. Each card: summary sentence, old → new value (old struck through), effective date, source chip (e.g. `Email · Infra FC · 5 Nov`), status pill (provisional, confirmed, rejected), and for the owner an acknowledgement meter ("41 of 120 have seen this", a thin rose bar on `fill`). Right rail: filters (client, topic, status).

**Conflicts** (owner) — header with a "Run conflict scan" button and the result summary in mono ("15 conflicts · last run 14:02"). Each conflict is a card with two columns side by side: the authoritative passage (left, with a small rose "authoritative" badge) and the conflicting passage (right, muted), each with its file and locator in mono, then the reason ("Client memo overrides the SOP for Infra only; issued 15 Apr 2026"). Actions: "Mark resolved", "Open in review". On mobile the two passages stack.

**Review queue** (owner) — rows grouped by risk tier (High risk first). Each row: what changed, who sent it and on which channel, effective date, affected agents and invoices count, the drafted SOP edit as a small diff (removed text struck through, added text underlined in ink). Item kinds include rule changes, conflicts, tacit entries, schema proposals, low-confidence metadata and **escalated questions**. A question row shows the question, the asker's client, what the engine found and why it abstained, the age of the request, and a reply box (with optional effective date and scope) for the expert, whose Send action replaces Approve and Reject. Approve (rose button) and Reject (outlined). A 409 from the API shows "Someone else just decided this item" and refreshes.

**Expert capture** — a chat-style flow in the main column: the engine asks five questions about supplier habits; each answer becomes a structured entry card on the right rail (supplier, habit, trigger, what to do, source, date, status "pending review"). Reviewers see Approve / Edit / Reject on each entry.

**Analytics** (owner) — simple cards: most-asked topics (horizontal bars in `fill` with a rose bar for the top topic), unanswered questions list, most-cited sources, knowledge latency, acknowledgement rate. Keep charts minimal and on-palette.

## 6. Document-type glyphs

16px rounded squares in `fill` with a 9px mono letter or lucide icon in `muted`:

| Type | Glyph |
| --- | --- |
| SOP / policy | `S` |
| Client memo | `M` |
| Desk instruction | `D` |
| FAQ | `F` |
| Training video | `Play` icon |
| Interview / shadowing | `Mic` icon |
| Email | `Mail` icon |
| Chat | `MessageSquare` icon |
| Expert entry | `BookUser` icon |
| Spreadsheet | `Table` icon |
| Slides | `Presentation` icon |
| Scanned page or image | `ScanLine` icon |
| Other document type | `FileText` icon |

## 7. API fields the UI needs

The answer card from `POST /ask` must include (Phase 4 of BUILD_PLAN.md):

- `rule.text` with `[n]` citation markers, and `rule.citations[]` in the same order, each with `{n, passage_id, file, short_label, locator, section_title, doc_type, status, quote}`
- `working[]` as `{label, value}` rows, `decision`, `exception_code`, `next_owner` (present only for plug-in calculator routes)
- `older_sources[]` with `{topic, current_value, older_value, file, locator, superseded_on}`
- `expert_tip`, `route_to`, `status`, `kb_version`, `as_of`, `client`
- `entities[]` as `{id, name, type}`
- `related[]`: 3–4 follow-up questions
- `latency_ms`

The Sources, Setup and timeline pages use `/episodes`, `/episodes/{id}`, `/schema`, `/bindings`, `/entities`, `/entities/{id}/timeline` (facts with `valid_from`, `valid_to`, `recorded_at`, `retracted_at`, status and source) and `/review-queue`.

## 8. Done when

- The Ask page for T1, T5 and T8 looks like the reference at 1440px: three zones, rose citation chips that highlight their source card, the current vs older card on T1, the working card on T5, the route card on T8.
- Changing the as-of date on T1 to 1 Mar 2026 shows the older rule, with the as-of chip and status line.
- Dropping a file on Sources shows it progress to published; a held file explains why.
- The Setup page shows the induced schema, lets an attribute be edited, and freezes it.
- The Entities page shows a fact's history as bars on a time axis, with a working as-of marker (gate B).
- At 390px: no horizontal scroll, chip strip scrolls, sources stack below the answer, top bar replaces the left rail.
- Only the tokens above appear in the CSS (a test greps `web/` for hex colours outside the token file).
- Keyboard: tab order follows the reading order; citation chips and source cards are focusable; visible focus ring in rose.
- Lighthouse accessibility score ≥ 90 on the Ask page.
