# Demo script — 16 Nov auction (about 12 minutes, with a 3-minute version)

Companion to [STUDY_GUIDE.md](STUDY_GUIDE.md). Expected answers are the real cards from `reports/eval_20261115_all_D_cards.jsonl`.

## Run of show

One message carries the whole demo: **the engine never presents an outdated rule as current, and it proves every answer.** Every act shows one more piece of evidence for that sentence, and the close repeats it with the numbers.

**Two people on stage.** The *presenter* talks and faces the judges; the *driver* types and clicks. The driver never talks over an answer while it loads (10–25 s): the presenter fills that time with the line marked **While it loads**. If you only have one person, read the presenter column and click as you go. Timing caveat: the times quoted below come from the evaluation run on a laptop. In the first load test on Railway (15 Nov, before MODEL_THREADS was set) answers took 32–35 s at the median and up to 47 s, so until a rerun shows otherwise, plan for 30–45 s per uncached answer and keep a second filler line ready.

**What you type is in bold italics; ask it word for word.** `warm_demo.py` caches answers by exact text, so a changed word means a fresh, slower answer that may be worded differently.

| Act                             | What it proves                                                          | Time                 | Pages used                                             |
|---------------------------------|-------------------------------------------------------------------------|----------------------|--------------------------------------------------------|
| 1\. Opening                     | The problem is real and costly                                          | 0:45                 | Sources                                                |
| 2\. Cited answers, client scope | Every sentence is traceable; a client memo applies only where it should | 2:30                 | Ask, source drawer                                     |
| 3\. Time                        | Old rules are labelled old; you can ask about any past date             | 3:00                 | Ask (as-of picker), Entities, Sources → Replay history |
| 4\. Calculation and know-how    | Numbers come from code, not the model; expert habits are captured       | 2:00                 | Ask                                                    |
| 5\. Knowing its limits          | It hands over, follows fraud controls, refuses what isn't documented    | 2:15                 | Ask, Review queue                                      |
| 6\. Change and close            | People are told when a rule changes; the results                        | 1:30                 | Changes                                                |
| **Total**                       |                                                                         | **about 12 minutes** |                                                        |

**Order of the questions** (all from `deploy/demo_questions.txt`, plus one extra in Act 3):

1.  ***What is the quantity tolerance for cement at Arvana Infra?***

2.  ***Does the Infra bulk-material tolerance apply to electrical cables?***

3.  ***Which GST return is used to decide whether input tax credit can be claimed?***

4.  ***What is the price tolerance for an invoice line where the unit price is higher than the PO?*** (asked twice: today, then as of 1 Mar 2026)

5.  ***A medium enterprise supplier registered on Udyam; invoice accepted on 16 April 2026; agreed payment term 45 days. What is the due date and which payment run should pay it?***

6.  ***A transporter's invoice 'TR/2026/0881/A' looks like an earlier 'TR/2026/881'. Is it a new invoice?***

7.  ***How is a CCTV maintenance contract with remote monitoring classified for TDS?***

8.  ***A bank change request asks me to call a mobile number to verify. What do I do?***

9.  An out-of-scope question (see Act 5: do not use the canteen question until it has been checked)

The expected answers below are the real answer cards from the 15 Nov evaluation run (`reports/eval_20261115_all_D_cards.jsonl`). On stage the wording may differ slightly; the facts, citations and codes should match.

## Before the demo

Most demo failures are decided the night before: the three risks at the end of this section are real and specific to our data, so check each one in the rehearsal.

**The night before (15 Nov)**

- Railway service healthy: `https://<railway-address>/health` shows `"status":"ok"` and `db_pool`

- Website points at Railway: ask one question on https://ps07-knowledge-engine.vercel.app and get an answer

- Model limits set from `scripts/probe_llm_limits.py`; MODEL_THREADS set to the service's vCPUs (GET /health shows the CPU quota); load test at 5 / 10 / 20 users passed with no errors and p95 under 30 s

- Full rehearsal once, timed, with both people, in the exact order of this script

- Add question 4 to the warm-up list: append *What is the price tolerance for an invoice line where the unit price is higher than the PO?* to `deploy/demo_questions.txt` (the as-of version is cached by asking it once in rehearsal with the date set)

- Screen-record the full rehearsal (the last-resort backup)

- Laptop backup tested: `run_public.ps1` (or `serve_public.py`) starts and the site answers through the tunnel

- Team decision on the watched folder: it is off on Railway (`WATCH_ENABLED=false`); gate B lists it, so either turn it on or show upload on the Sources page and say why

**Demo morning (16 Nov)**

- `python scripts/warm_demo.py --base https://<railway-address>` → every line `OK`

- Ask questions 4 (today and as of 1 Mar 2026) once by hand, so both are cached

- Open the site from mobile data, not the venue Wi-Fi

- Browser: one window, zoom 125% so the back row can read it, notifications off, other tabs closed

- Pre-open tabs in this order: Sources, Ask, Entities, Sources → Replay history, Review queue, Changes

**15 minutes before**

- `/health` once more

- Ask question 1 once; if it takes over 30 s, warm again

- Rule for both presenters: nobody clicks Approve, Reject, Run conflict scan or **Run again from empty** on stage. Each one changes the shared database or starts a long job

**Three known risks (check them in rehearsal)**

| Risk                                                     | Why it can happen                                                                                                                                                                                         | What to do                                                                                                                                                            |
|----------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| The canteen question gets an answer instead of a refusal | On 11 Nov, acceptance test T11 approved an expert's *test* reply about the canteen subsidy on the public site, so the deployed knowledge base may now hold that fact                                      | Ask it in rehearsal. If it answers, use ***How many days of annual leave does an AP processor get?*** instead (abstention set, refused and routed to HR / Admin team) |
| The Infra tolerance answer changes on 16 Nov             | The test data includes an Infra owner's email announcing a 7% bulk tolerance **from Monday 16 Nov**. If that email is in the live knowledge base, today's answer becomes the provisional 7% instead of 5% | Ask question 1 the morning of the 16th. If it shows 7% provisional, use it: "the rule changed today, and the engine knows". If 5%, keep the script                    |
| A slow or uncached answer                                | Any change to the wording, the date or the knowledge base makes a fresh model call                                                                                                                        | Keep the exact wording; have the presenter's **While it loads** line ready; never wait in silence                                                                     |

## Act 1 — Opening (0:45)

The opening sets up the one failure we prevent: someone following a rule that was replaced. Keep it to three sentences and get to the first question fast.

**Driver:** the Sources page is on screen, showing the uploaded documents and the **Knowledge base totals** panel.

**Presenter says:**

> "Meridian's accounts-payable team keeps its rules in two SOP versions, desk instructions, client memos, an FAQ nobody updated, training videos and expert interviews. The old SOP from 2023 is still in circulation, the FAQ contradicts the current one, and new processors ask each other in Teams and get answers from memory. Pay a supplier on last year's tolerance and the company loses money."

> "We built an engine that reads all of it, keeps one dated record of every rule and where it comes from, and answers in about 15 seconds, with proof. Let me show you."

**Point at:** the list of documents (SOP v3.1 and v4.0 side by side makes the point), then the totals panel.

**Don't:** explain the architecture here. It lands better after they have seen an answer.

## Act 2 — Cited answers and client scope (2:30)

This act proves two things: every sentence links to the exact passage it came from, and a client's own rule applies only to that client and only to what it covers.

### Step 2.1 — A current rule for one client (question 1, about 15 s)

**Driver:** open **Ask**, leave the date pill on **Today** and the client chip on all clients, type ***What is the quantity tolerance for cement at Arvana Infra?*** and press **Send question**.

**While it loads, presenter says:**

> "The general SOP allows no quantity tolerance at all. But Arvana Infra has a client memo that changes that for some materials. A keyword search would find both and probably mix them up."

**What appears (15 Nov run, 15.5 s):**

- **Answer:** for Arvana Infra Projects, cement is one of four bulk materials where an invoice quantity up to **5% above the GRN** is accepted, if the excess value is **no more than ₹25,000**; above either limit, raise **QTY_VAR**. The tolerance comes from client memo **CM-INF-02**, in force until 2027-03-31, and overrides the SOP for that client only. All other materials follow SOP v4.0 §4.3: no tolerance.

- **Citations:** \[1\] CM-INF-02 Part C · \[2\] AP SOP v4.0 §1 (purpose and scope) · \[3\] AP SOP v4.0 §4.3 (quantity tolerance).

- **Expert practice:** Lakshmi Reddy, Senior Processor (Expert interview 1 \[07:50\]): "Infra's tolerance is five per cent and only for four materials, not ten per cent."

- **Older sources on this topic:** the SOP's general rule and a training video, shown as overridden by CM-INF-02 from 15 Apr 2026.

**Driver:** click citation **\[1\]**. The drawer opens on the memo passage with the cited words marked.

**Presenter says:**

> "Every sentence has a number, and every number opens the exact passage, with the words it used highlighted. Notice the expert's note: 'five per cent, not ten.' Ten per cent is what an outdated FAQ says. The engine knows the FAQ is outranked."

### Step 2.2 — The limits of a client rule (question 2, about 20 s)

**Driver:** type ***Does the Infra bulk-material tolerance apply to electrical cables?***

**While it loads:**

> "A memo that changes the rule for some materials is exactly where people make mistakes. Does the 5% apply to cables?"

**What appears (21.0 s):** "**No** — the Infra bulk-material tolerance does not apply to electrical cables, because it covers only cement, reinforcement steel, sand and aggregates." Then the 5% / ₹25,000 limits for those four, and that everything else, cables included, follows SOP v4.0 §4.3 with **no quantity tolerance**. Citations: CM-INF-02 Part C, AP SOP v4.0 §4.3.

**Presenter says (transition):**

> "So it applies a client's rule, and knows where that rule stops. Now the harder problem: rules that changed over time."

## Act 3 — Time: the rule that was replaced (3:00)

This is the act that separates us from a chatbot over documents: every fact carries the dates it was in force, so the old rule is labelled old, and you can ask what the rule was on any past day.

### Step 3.1 — A rule that changed between SOP versions (question 3, about 10 s)

**Driver:** type ***Which GST return is used to decide whether input tax credit can be claimed?***

**While it loads:**

> "Between the 2023 SOP and the 2026 SOP, the GST reconciliation rules changed. Both documents are still in the system."

**What appears (10.0 s):**

- **Answer:** input tax credit is decided using the client's **GSTR-2B**; credit is claimed only for invoices that appear in it. GSTR-2B is generated on the **14th of the following month**; if the invoice is missing, pay the base value on the due date and hold the GST. Still missing after two more cycles: raise **NOT_IN_2B** to the vendor relationship owner.

- **Citations:** AP SOP v4.0 §5.5 (GSTR-2B reconciliation) · Expert interview 2 \[06:55\], Imran Qureshi, Tax Desk Lead.

- **Expert practice:** check whether the supplier files quarterly (QRMP) before chasing a mismatch.

- **Older sources on this topic:** SOP v3.1 and the desk instructions said the **20th**; superseded by SOP v4.0 §5.5 on **1 Apr 2026**.

**Driver:** scroll to **Older sources on this topic**.

**Presenter says:**

> "The old date, the 20th, is still in two documents. The engine never gives it as the answer. It shows it only down here, labelled with what replaced it and from when. Our rule is: an outdated rule is never presented as current. On 23 questions built around exactly this trap, it was wrong zero times."

### Step 3.2 — Ask about the past (question 4, twice; about 15–20 s each)

**Driver:** type ***What is the price tolerance for an invoice line where the unit price is higher than the PO?*** with the date pill on **Today**.

**What appears (16.2 s):** the line passes only if the excess is no more than **the lower of 1% of the PO line value and ₹500**; otherwise hold with **PRICE_VAR**, sent to the PO buyer, resolved within 3 working days. Citations: AP SOP v4.0 §4.2, §10. Older sources: SOP v3.1 and desk instructions said **2%** and **₹1,000**, superseded on 1 Apr 2026.

**Driver:** click the **Today** pill → **Rules in force on** → pick **1 March 2026** → ask the same question again.

**While it loads:**

> "Now the same question, as of the first of March this year, a month before the new SOP took effect. An auditor asks exactly this: what rule did we apply then?"

**What appears (acceptance test T1, 18.2 s):** **the lower of 2% and ₹1,000**, labelled as the rule in force on 2026-03-01, citing SOP v3.1.

**Presenter says:**

> "Same question, different date, different correct answer, and it says which rule was in force when. Every fact stores two dates: when it was true in the business, and when we learned it."

**Driver:** click the pill → **Back to today**. Don't forget this: every later question needs today's rules.

### Step 3.3 — The rule's whole life on one screen (Entities page, 45 s)

**Driver:** open **Entities** → **Find an entity** → type *price* → pick the price-tolerance entity (check the exact name in rehearsal).

**What appears:** the **Entity timeline**: one row per attribute, bars for each value over time. The current value is highlighted, superseded ones struck through, with a "now" line. Click a bar to see **Valid from**, **Valid to**, **Recorded**, **Retracted**, **Authority rank** and **Open original**.

**Presenter says:**

> "This is the record behind the answers: each value of the price tolerance, when it was in force, which document said it, and how authoritative that document is. Nothing is deleted. A replaced rule is closed off, so the history is auditable."

### Step 3.4 — Watch the knowledge build itself (Replay, 45 s, optional if short on time)

**Driver:** **Sources** → **Replay history** (top right) → the page "Watch the knowledge base build itself". Step through with **Next step**. Do **not** press **Run again from empty**: it re-extracts every file and takes 20–30 minutes.

**What appears, step by step** (from the recorded replay; check the steps on Neon in rehearsal):

- **SOP v3.1 arrives:** the 2023 rules become current.

- **SOP v4.0 arrives:** under **Rules it replaced**, 19 rules change, among them price tolerance 2% / ₹1,000 → 1% / ₹500, approval limit ₹25 lakh → ₹10 lakh, e-invoice threshold ₹10 crore → ₹5 crore, payment cut-off 5 pm → 1 pm, GSTR-2A → GSTR-2B.

- **Memos and FAQ arrive:** the FAQ's "Infra 10%" claim appears under **Held for review, not used in answers**.

- **The Infra owner's email arrives:** **Change announced**: 7% bulk tolerance from 16 Nov.

**Driver (optional):** at the SOP v3.1 step, use **Ask at this step**: the price tolerance comes back as 2% / ₹1,000, as the engine knew it then.

**Presenter says (transition):**

> "So the engine knows not just the rule, but its history, and it can answer as of any moment. Next: what happens when the answer needs a calculation."

## Act 4 — It calculates, and it knows the experts' habits (2:00)

Language models get arithmetic and dates wrong, so the model never does them: a calculator in the AP plug-in does, reading every threshold from the graph. And the know-how that lives only in colleagues' heads comes in as advice, never as a rule.

### Step 4.1 — A payment-date calculation (question 5, about 17 s)

**Driver:** type ***A medium enterprise supplier registered on Udyam; invoice accepted on 16 April 2026; agreed payment term 45 days. What is the due date and which payment run should pay it?***

**While it loads:**

> "MSME payment rules have caps for micro and small suppliers, payment runs on fixed days and a cut-off time. People get this wrong by a day all the time, and that's a legal problem."

**What appears (17.2 s):**

- **Decision:** due **Sunday 31 May 2026**; pay in the **Friday 29 May 2026** run.

- **Answer:** medium enterprises follow normal terms, so the agreed 45 days apply, not the micro/small cap. Runs are on Tuesday and Friday; the cut-off is 1 pm on the previous working day, **Thursday 28 May 2026**. Never pay early without Treasury approval. Citation: AP SOP v4.0 §9 (Payments).

- **Working** (the calculator's steps, shown on the card): supplier category *medium* → accepted *Thursday 16 April 2026* → term *45 days (agreed, normal terms)* → due *Sunday 31 May 2026* → payment run *Friday 29 May 2026 (last on or before due)* → cut-off *1 pm, Thursday 28 May 2026*.

**Driver:** point the cursor at the **Working** block.

**Presenter says:**

> "Every step is shown. The 45 days, the Tuesday-and-Friday runs, the 1 pm cut-off: none of these are in our code. The calculator reads them from the current SOP in the graph. Change the SOP, and the calculator changes with it. If a rule it needs is missing, it raises an error instead of guessing."

### Step 4.2 — A duplicate invoice, and an expert habit (question 6, about 30 s; the slowest of the demo)

**Driver:** type ***A transporter's invoice 'TR/2026/0881/A' looks like an earlier 'TR/2026/881'. Is it a new invoice?***

**While it loads (this one takes ~30 s, so use both lines):**

> "This is a real habit from our shadowing notes: one transporter re-sends invoices with a slash-A on the end. A new processor would pay it twice."

> "The SOP has a normalisation rule for invoice numbers. The engine applies it with a calculator, then adds what the senior processor knows."

**What appears (31.5 s):**

- **Decision:** suspected duplicate, raise **DUP_SUSPECT**; next owner: Senior Processor (clears DUP_SUSPECT).

- **Answer:** under the rule in force, both numbers normalise to **TR2026881**, so it is a suspected duplicate, not a new invoice. Normalisation removes spaces, slashes, hyphens and leading zeros and drops a trailing /A, /R or -REV. Never posted until a Senior Processor clears it. "In practice, this transporter adds /A whenever they re-send." Citations: AP SOP v4.0 §3.3 (Duplicate check) · Shadowing notes 10:50.

- **Working:** normalisation rule → TR/2026/0881/A → TR2026881 → TR/2026/881 → TR2026881 → match: Yes.

- **Older sources:** SOP v3.1 said to *reject* a duplicate; v4.0 changed it to DUP_SUSPECT and review.

**Presenter says:**

> "The rule comes from the SOP, the habit from a colleague, and the card keeps them apart: practice never overrides a rule. Experts can add these notes themselves through an Expert capture page, and every note is reviewed before anyone sees it."

**Presenter says (transition):**

> "A good assistant also knows when *not* to answer."

## Act 5 — Knowing its limits (2:15)

This act shows the three ways the engine stays safe: it hands a judgment call to the named expert, it follows fraud controls to the letter, and it refuses anything the documents don't cover, routing it to a person instead of answering from general knowledge.

### Step 5.1 — A judgment call goes to the expert (question 7, about 18 s)

**Driver:** type ***How is a CCTV maintenance contract with remote monitoring classified for TDS?***

**While it loads:**

> "Tax sections for maintenance contracts depend on what is mostly supplied. A CCTV contract with remote monitoring is half manpower, half technical. A wrong guess is a tax error."

**What appears (18.4 s):**

- **Answer:** a mixed security-systems contract, decided **case by case**, not by a fixed rule. The general rule: mainly manpower and repairs is 194C; mainly technical or software support is 194J at 2%. When mixed or unclear, raise **TDS_SECTION_UNCLEAR** to the Tax Desk and don't guess. Citations: Expert interview 2 \[03:10\], Imran Qureshi · AP SOP v4.0 §6.

- **Who to ask:** **Tax Desk**, with the reason, and a **Send to Tax Desk** button.

**Presenter says:**

> "It explains the rule, says this case is not decidable by rule, and names who decides. It never invents a tax section, and it gives no tax advice beyond what the documents say."

### Step 5.2 — A fraud control (question 8, about 8 s, the fastest)

**Driver:** type ***A bank change request asks me to call a mobile number to verify. What do I do?***

**What appears (8.0 s):** "**No** — do not call the mobile number given in the request; log the request as suspicious and tell the AP Controller." Then the full control: call the number **already in the vendor master**, ask for the authorised signatory, confirm the last four digits of the old and new accounts, record the call in the change ticket, approval by the Vendor Master lead then the AP Controller, a **24-hour payment block** that IT must not lift, no changes in the 3 working days before month-end close. Eight citations: desk instruction **DI-07** Part B steps 2–6, AP SOP v4.0 §8.2, and shadowing notes.

**Presenter says:**

> "This is the classic invoice-fraud attack. The answer is a complete procedure, step by step, and every step cites the desk instruction. The engine also brings in missing steps of a procedure, so an answer never skips the one in the middle."

### Step 5.3 — Not in the documents: refuse and route (question 9, about 9 s)

**Driver:** type the out-of-scope question checked in rehearsal: ***What is the canteen subsidy for employees?*** if it was still refused, otherwise ***How many days of annual leave does an AP processor get?***

**While it loads:**

> "Now something an AP knowledge base shouldn't know."

**What appears:** **"The documents in the knowledge base do not cover this."** Who to ask: **HR / Admin team**, with a **Send to HR / Admin team** button. (In the abstention test, 20 out of 20 such questions were refused, and 18 of 20 routed to a sensible role.)

**Presenter says:**

> "A chatbot would answer this from general knowledge, confidently and wrongly for this company. Ours says it doesn't know, and sends the question to the team that does."

**Driver (optional):** click **Send to HR / Admin team** → the card shows "Sent … waiting". Open **Review queue** and point at the question under escalated questions. Do **not** type a reply or approve anything.

**Presenter says:**

> "The expert answers here. Their reply reaches the person straight away, labelled 'not yet part of the knowledge base'. It only becomes knowledge after the process owner approves it. Then the engine re-asks the question and tells the person. An expert's reply is input, never automatically a rule."

## Act 6 — When rules change, people are told; the close (1:30)

Answering questions is half the job; the other half is telling people when a rule they relied on has changed. End on that, then close with the numbers.

### Step 6.1 — The change feed (45 s)

**Driver:** open **Changes**. The page is titled "What changed in the rules".

**What appears:** one card per published change: old value → new value, from which date, which source, and how many people acknowledged it ("Got it"). Filters by topic; a **For you** view. The **Daily digest** card summarises a day's changes, with **Copy as text** and channels for **Email** and **Teams**. Where a new rule contradicts a document still in force, a **Draft document edit** shows the suggested new wording.

**Presenter says:**

> "When a rule changes, three things happen. Everyone sees it here, and we track who acknowledged it. Anyone who got an answer in the last week that relied on the old rule gets a notice: 'An answer you got has changed.' And if the new rule contradicts a document still in force, the engine drafts the edit to that document, so the SOP catches up."

**Don't:** click **Send now** on the digest; it sends a real email or Teams message if those are configured.

### Step 6.2 — The close (45 s)

**Driver:** go back to **Ask** with the last good answer on screen, or show the results slide.

**Presenter says:**

> "To sum up. On the 160-question evaluation: 158 right, 98.8%, graded by a model from a different family than the one answering. 99.4% of citations correct. Zero outdated rules on the 23 questions built to trap us. About 12 seconds a median answer, and four-hundredths of a cent a question."

> "And it is not built for Meridian. Everything specific to accounts payable is a plug-in. We dropped in a second, unrelated company, an HR team at a freight firm, with no code changes, and it answered 10 out of 10."

> "The engine never presents an outdated rule as current, and it proves every answer. Thank you. We're happy to take questions, and to ask it anything you like live."

**Why end with "ask it anything":** an off-script question answered honestly, even with "not covered, here's who knows", is more convincing than any rehearsed one.

## The 3-minute version

If the slot is cut, keep the four proofs and drop everything else: one cited answer, the as-of date, one calculation, one refusal.

1.  **Opening (20 s):** "Rules live in two SOP versions, memos, an outdated FAQ and people's heads. Follow last year's rule and the company loses money. Our engine keeps one dated record of every rule and proves every answer."

2.  **Cited answer (40 s):** question 1 (cement at Arvana Infra). Open citation \[1\]. "Every sentence opens the exact passage. A client memo applies only to that client."

3.  **Time (50 s):** question 4 today (1% / ₹500), then the date pill → 1 March 2026 → again (2% / ₹1,000). "Same question, different date, the rule that was in force then. The old rule is never given as current: zero times wrong on 23 trap questions." Then **Back to today**.

4.  **Calculation (30 s):** question 5 (MSME). Point at **Working**. "Numbers come from a calculator that reads the thresholds from the current SOP. The model never does arithmetic."

5.  **Refusal (20 s):** the out-of-scope question. "Not in the documents, so no answer from general knowledge; it goes to HR."

6.  **Close (20 s):** "158 of 160 right, zero outdated rules, 12 seconds, four-hundredths of a cent a question, and a second company with no code changes."

## If something goes wrong

A calm recovery is part of the demo: decide the fallback now, so nobody improvises on stage.

| Symptom                                                  | What the driver does                                                                                                | What the presenter says                                                                              |
|----------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| An answer takes over 30 s                                | Leave it running; move to the next step                                                                             | "It's checking its answer; let's come back to it"                                                    |
| An answer comes back "not covered" for a script question | Move on; don't retry on stage                                                                                       | "When it can't verify an answer, it withholds it rather than risk a wrong one. That's the design"    |
| The wording differs from the script                      | Nothing; facts and codes are what matter                                                                            | Read the card as it is                                                                               |
| Answers never arrive                                     | Check `/health` in another tab. Down: start the laptop backup (`run_public.ps1`), about 2 minutes                   | Take questions on the architecture while it starts                                                   |
| The site can't reach the API at all                      | Play the recorded rehearsal                                                                                         | Narrate over the recording                                                                           |
| Wrong date still selected                                | Click the pill → **Back to today** and ask again                                                                    | "I left the date in March, let's bring it back to today"                                             |
| Every uncached answer takes 30–45 s                      | Stick to the warmed questions (cached answers skip the model calls); skip Step 3.4 Replay and Step 6.1 to save time | Use both While-it-loads lines; "It is checking every sentence against its sources before showing it" |

## Quick answers to judges' questions

Short answers here; the full reasoning is in [STUDY_GUIDE.md](STUDY_GUIDE.md), sections 4 and 7.

| They ask                                               | You answer                                                                                                                                                                                                                                                               |
|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Isn't this just RAG?                                   | Search finds passages, but rule values come from a dated facts table by direct lookup, numbers from calculators, and four checks run before anything is shown                                                                                                            |
| How do you know it's not tuned to your test questions? | The app never reads the evaluation workbook (a test enforces it), holdout failures aren't inspected, and a second company scored 10/10 with no code changes                                                                                                              |
| What if two documents disagree?                        | The higher-authority source wins, not the newer one; a client memo wins only for its client. A conflict scan found 15/15 known conflicts and opened review items                                                                                                         |
| Who can change a rule?                                 | Only the registered owner of that scope, on a low-risk topic, goes live (as provisional). Everything else waits for the process owner                                                                                                                                    |
| What does it cost to run?                              | About \$0.0004 a question on DeepSeek; the demo hosting is about \$5                                                                                                                                                                                                     |
| Why DeepSeek?                                          | Best of three we measured: DeepSeek 98.8% at \$0.06 a run; Claude 95.6% at \$2.67; GPT-5 95.6% by hand review. Switching is one setting                                                                                                                                  |
| How does it handle scanned PDFs?                       | A vision model reads the pages: fact F1 0.90 against the original Word file                                                                                                                                                                                              |
| Does it scale?                                         | The database isn't the limit; model calls and CPU are. We raised the connection pool and parallel answers for the demo, and set the local models' CPU threads to the container's share after the first Railway test gave 32–35 s at 3–5 users; a hosted reranker is next |
| Is the data safe?                                      | Bank accounts, PAN, IFSC and phone numbers are redacted before any model call, every call is logged, and zero data retention is requested from the provider                                                                                                              |
| What's not done yet?                                   | Audio/video transcription; pptx and flat-docx extraction just under target; usability tests and judge calibration this week                                                                                                                                              |
