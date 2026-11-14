# Real Teams questions — 14 Nov 2026

32 questions taken from the `teams_questions` sheet of `data/ops/PS-07_ap_operations.xlsx`
(1,900 questions processors asked colleagues in Teams, April–September 2026). They were chosen
to stress client memos (Pharma QA release, Infra cement quantity), expert habits (Infra GRN
timing) and supplier habits (resent invoices with -REV, quarterly GSTR-2B filers). The sample
includes all 7 questions where the colleague's reply in Teams was wrong. Asked through the
normal pipeline (`scripts/run_teams_sample.py`) on the local knowledge base (same corpus as
Neon), Isoquant `deepseek-v4.1-flash-1017-fast`. The sheet has no gold answers, so each card was
judged by hand against the documents. Cards: `teams_sample_20261114.jsonl`.

## Result

| | count |
| --- | --- |
| Correct and cited | **24/32 (75%)** |
| Partly right (right substance, wrong or hedged decision) | 5/32 |
| No answer (not covered / could not verify) | 3/32 |
| Stated a wrong or outdated rule as current | **0/32** |
| Questions the colleague got wrong in Teams, answered correctly by the engine | **7/7** |

Latency 7–31 s per answer (median about 13 s).

## By topic

| topic | asked | correct | notes |
| --- | --- | --- | --- |
| Pharma QA release (client memo CM-PHA-01) | 3 | 3 | Excipients need QA release; raise QA_RELEASE_PENDING; may post, payment blocked. Explains the old FAQ is outdated. |
| Infra cement quantity (client memo CM-INF-02) | 7 | 7 | 6% and 8% over: QTY_VAR. 2.5% and 4%: within 5%, provided the excess value is at most ₹25,000. Cites the memo and SOP 4.3. |
| Infra GRN timing (expert habit) | 3 | 0 (3 partial) | See finding 1. |
| Duplicate (-REV invoices) | 3 | 0 (1 partial, 2 no answer) | See finding 2. |
| GSTR-2B missing | 3 | 3 | Hold GST only, pay base value; NOT_IN_2B after two more cycles; QRMP tip from the expert interview. |
| Price tolerance | 3 | 2 (1 no answer) | ₹820 on ₹30,000 and on ₹140,000: PRICE_VAR, correct. ₹340 on ₹12,000: "could not verify". |
| Approvals | 3 | 3 | ₹8 lakh: clean match only; ₹18 lakh: AP Controller; ₹60 lakh: Client CFO. |
| E-invoice / IRN | 2 | 2 | ₹6.8 crore > ₹5 crore: return as IRN_MISSING (the old ₹10 crore is not used). |
| Legal fee without GST (RCM) | 1 | 0 (1 partial) | See finding 3. |
| TDS section for an AMC | 1 | 1 | 194C if mainly manpower/repairs, 194J if technical; mixed or unclear: TDS_SECTION_UNCLEAR. |
| Bank change | 1 | 1 | E-mail from the registered id is not enough: letterhead, cancelled cheque, call-back on the number on file. |
| Non-PO courier | 1 | 1 | Courier needs a PO under v4.0 (it was non-PO under v3.1). |
| MSME due date | 1 | 1 | Small enterprise: at most 45 days, 15 without a written agreement. |

## Findings

1. **Expert habits are mentioned but don't drive the decision (Infra GRN timing, 3/3 partial).**
   "Infra invoice has no GRN since Saturday, should I raise NO_GRN now?" The expert's documented
   practice (Interview 1 [02:30], Shadowing 10:05) is to wait until Tuesday noon, because Infra
   sites post GRNs in a Monday batch. The engine's decision line says "Raise NO_GRN" (one says
   "No — hold as NO_GRN") from SOP 4.6, and only adds the Tuesday-noon habit as a closing
   sentence. A processor reading the decision would raise it. The SOP doesn't say *when* to
   raise it, so the habit doesn't contradict the rule. The answer should put the habit into the
   decision ("wait until Tuesday noon, then raise NO_GRN"). Same pattern as eval Q050.
2. **Duplicate-number questions are not worked out (2 no answer, 1 hedged).** SOP 3.3 gives a
   mechanical normalisation (drop spaces, slashes, hyphens, leading zeros and a trailing -REV).
   INV/0605 becomes INV605 and INV715-REV becomes INV715, so the numbers differ. The engine never
   applies it: twice "not covered", once "the evidence does not establish…". Fix: a small
   duplicate-check calculator in the AP plug-in that normalises both numbers (the rule's
   suffixes read from the graph), then says "different numbers; still check supplier, date and
   amount".
3. **Legal fee without GST (partial).** The substance is right (don't return it; legal fees
   are reverse charge). But it cites only the expert interview, ends as "needs specialist", and
   misses SOP 5.6: flag **RCM_REVIEW** and route to the Tax Desk before posting.
4. **One small calculation not verified.** "₹340 on a ₹12,000 line" (1% = ₹120 → PRICE_VAR) came
   back unverified, while the same template with other figures passed. Likely the verifier
   rejecting the derived ₹120. The price calculator was not chosen (the question gives a
   difference, not unit prices).
5. **Supplier habits from the vendor master are not used.** For Sunrise Auto Parts and Kaveri
   Foods (quarterly filers in the vendor master) the GSTR-2B answer gives the general QRMP tip,
   not "this supplier is a quarterly filer, expect it at quarter-end". For Jai Auto Parts
   (known to resend with -REV) the duplicate question got no answer. The engine does not look up
   the named supplier's habit note.
6. **Irrelevant expert tips on 4 cards.** IRN question with the Infra-tolerance tip; ₹18 lakh
   approval with the legal-fee RCM tip; courier non-PO with the transporter -REV tip; ₹8 lakh
   approval with "Lakshmi holds the invoice as per SOP". The tip is picked by similarity, not
   checked for topic.
7. **Minor:** the MSME answer calls Sandeep a "senior processor"; he is the Team Lead.

## Suggested fixes (in order of value)

1. Let a practice fact that refines *when or how* to apply a rule shape the decision line (GRN
   timing). Keep rule 9: a habit never overrides a rule's *value*.
2. A duplicate-check calculator in the AP plug-in (number normalisation from SOP 3.3).
3. Supplier-aware answers: when the question names a supplier with a habit note, add that habit
   as the expert tip.
4. Topic check on the expert tip (only show a tip about the same topic or attribute).
5. Cite the SOP rule (RCM_REVIEW) when an expert passage and an SOP section say the same thing.
