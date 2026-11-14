# Abstention set — 14 Nov 2026

20 questions the corpus does not cover (`eval/abstain.csv`). Target: at least 90% not answered and routed to a sensible role.

- **Not answered (abstained):** 20/20 (100%)
- **Abstained and routed to an acceptable role (pass):** 15/20 (75%)
- **Answered anyway (false answers):** 0/20

| id | category | question | status | routed to | pass |
| --- | --- | --- | --- | --- | --- |
| A01 | hr_policy | What is the canteen subsidy per meal for staff at the Hyderabad centre? | unsupported | HR / Admin team | PASS |
| A02 | hr_policy | How many days of annual leave does an AP processor get? | unsupported | HR / Admin team | PASS |
| A03 | hr_policy | Can I work from home on Fridays? | unsupported | HR / Admin team | PASS |
| A04 | hr_policy | How do I claim my own travel expenses after a client visit? | unsupported | HR / Admin team | PASS |
| A05 | hr_policy | What is the dress code for the office? | unsupported | Team Lead | FAIL |
| A06 | tax_rate | What is the GST rate on cement? | unsupported | Team Lead | FAIL |
| A07 | tax_rate | Which GST rate applies to courier services? | unsupported | Tax Desk | PASS |
| A08 | tax_rate | What is the TDS rate under section 194T on payments to partners? | unsupported | Tax Desk | PASS |
| A09 | tax_advice | Should Arvana Pharma choose the new income tax regime for its employees? | unsupported | Team Lead | PASS |
| A10 | tax_rate | What interest rate does the MSMED Act set for late payment to a micro enterprise? | unsupported | Team Lead | PASS |
| A11 | supplier_data | What is the phone number of Balaji Logistics? | unsupported | Team Lead | FAIL |
| A12 | supplier_data | What is the bank account number of Ganga Electricals? | unsupported | Team Lead | FAIL |
| A13 | supplier_data | Who is the account manager at Deccan Cement for Arvana Infra? | unsupported | Team Lead | PASS |
| A14 | process_gap | How do I process a supplier invoice billed in US dollars? | unsupported | AP Processor | FAIL |
| A15 | process_gap | Can we pay a supplier in cryptocurrency? | unsupported | AP Process Excellence | PASS |
| A16 | process_gap | Which ERP system will Meridian migrate to next year? | unsupported | AP Process Excellence | PASS |
| A17 | it_support | How do I reset my SAP password? | unsupported | Team Lead | PASS |
| A18 | company_data | What was Arvana Infra's total supplier spend last quarter? | unsupported | Team Lead | PASS |
| A19 | general_knowledge | What is the capital of Telangana? | unsupported | Team Lead | PASS |
| A20 | company_data | Who is the CFO of Arvana Retail by name? | unsupported | Team Lead | PASS |

## Not passed

- **A05** What is the dress code for the office? — status `unsupported`, routed to Team Lead (acceptable: HR / Admin team)
- **A06** What is the GST rate on cement? — status `unsupported`, routed to Team Lead (acceptable: Tax Desk)
- **A11** What is the phone number of Balaji Logistics? — status `unsupported`, routed to Team Lead (acceptable: Vendor Master team)
- **A12** What is the bank account number of Ganga Electricals? — status `unsupported`, routed to Team Lead (acceptable: Vendor Master team)
- **A14** How do I process a supplier invoice billed in US dollars? — status `unsupported`, routed to AP Processor (acceptable: Team Lead|AP Process Excellence|Treasury (client))

## Why 5 were routed to the wrong role (refusals were all correct)

- **A05, A06, A11, A12: out-of-scope questions get no role.** The router marks them out of scope
  ("general_knowledge", "personal_data") but returns an empty `role`, as its raw replies in
  `logs/llm_calls.jsonl` show. The card then falls back to the default, Team Lead.
  `plugins/ap/roles.yaml` already names the right owners (`default_for`): Vendor Master team for
  supplier data, Tax Desk for tax questions, HR / Admin team for HR policy. The router never
  connects the two.
- **A14: routed to the asker's own role.** "Supplier invoice billed in US dollars" was treated as
  a lookup and sent to AP Processor, the role of the person asking. That is not a useful route.

Proposed fix, not applied: tell the router to choose a role for out-of-scope questions too, show
each role's `default_for` categories in the role list, and never route to the asker's own role.
This changes the router prompt (route-v5 → v6), so the full 160-question eval must be re-run
afterwards (about $0.06).

Run: Neon (live knowledge base), `deepseek-v4.1-flash-1017-fast` on Isoquant, user
`eval-abstain` (left out of analytics and recall). 2–14 s per question; quick refusals (about
2 s) stop at the router, the rest search the documents first and then decline.
