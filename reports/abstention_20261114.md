# Abstention set — 14 Nov 2026

20 questions the corpus does not cover (`eval/abstain.csv`). Target: at least 90% not answered and routed to a sensible role.

- **Not answered (abstained):** 20/20 (100%)
- **Abstained and routed to an acceptable role (pass):** 18/20 (90%)
- **Answered anyway (false answers):** 0/20

| id | category | question | status | routed to | pass |
| --- | --- | --- | --- | --- | --- |
| A01 | hr_policy | What is the canteen subsidy per meal for staff at the Hyderabad centre? | unsupported | HR / Admin team | PASS |
| A02 | hr_policy | How many days of annual leave does an AP processor get? | unsupported | HR / Admin team | PASS |
| A03 | hr_policy | Can I work from home on Fridays? | unsupported | HR / Admin team | PASS |
| A04 | hr_policy | How do I claim my own travel expenses after a client visit? | unsupported | HR / Admin team | PASS |
| A05 | hr_policy | What is the dress code for the office? | unsupported | HR / Admin team | PASS |
| A06 | tax_rate | What is the GST rate on cement? | unsupported | Tax Desk | PASS |
| A07 | tax_rate | Which GST rate applies to courier services? | unsupported | Tax Desk | PASS |
| A08 | tax_rate | What is the TDS rate under section 194T on payments to partners? | unsupported | Tax Desk | PASS |
| A09 | tax_advice | Should Arvana Pharma choose the new income tax regime for its employees? | unsupported | HR / Admin team | FAIL |
| A10 | tax_rate | What interest rate does the MSMED Act set for late payment to a micro enterprise? | unsupported | Tax Desk | PASS |
| A11 | supplier_data | What is the phone number of Balaji Logistics? | unsupported | Vendor Master team | PASS |
| A12 | supplier_data | What is the bank account number of Ganga Electricals? | unsupported | Vendor Master team | PASS |
| A13 | supplier_data | Who is the account manager at Deccan Cement for Arvana Infra? | unsupported | Vendor Master team | PASS |
| A14 | process_gap | How do I process a supplier invoice billed in US dollars? | unsupported | Team Lead | PASS |
| A15 | process_gap | Can we pay a supplier in cryptocurrency? | unsupported | Team Lead | PASS |
| A16 | process_gap | Which ERP system will Meridian migrate to next year? | unsupported | Team Lead | PASS |
| A17 | it_support | How do I reset my SAP password? | unsupported | HR / Admin team | FAIL |
| A18 | company_data | What was Arvana Infra's total supplier spend last quarter? | unsupported | Team Lead | PASS |
| A19 | general_knowledge | What is the capital of Telangana? | unsupported | Team Lead | PASS |
| A20 | company_data | Who is the CFO of Arvana Retail by name? | unsupported | AP Controller | PASS |

## Not passed

- **A09** Should Arvana Pharma choose the new income tax regime for its employees? — status `unsupported`, routed to HR / Admin team (acceptable: Tax Desk|Team Lead)
- **A17** How do I reset my SAP password? — status `unsupported`, routed to HR / Admin team (acceptable: Team Lead|AP Process Excellence)

## Router v6 (14 Nov, after the first run)

This run uses router prompt `route-v6`. The earlier run with `route-v5` (15/20) is kept in `abstention_20261114_router_v5.md`.

- **What changed:** the router must pick a role for every route, out-of-scope included. Its role list shows each role's "first contact for" categories (`default_for` in the plug-in's roles.yaml). A role marked `asker: true` (the AP Processor) is left out of the list, and the router can never return it.
- **Result:** 20/20 not answered (unchanged), **18/20 routed to an acceptable role** (was 15/20). All 5 earlier mis-routes are fixed: A05 goes to HR / Admin, A06 to Tax Desk, A11 and A12 to the Vendor Master team, and A14 to the Team Lead.
- **Two new misses, both arguable:**
  - A09 (new income-tax regime for employees) goes to HR / Admin. Payroll tax is plausibly HR's, but the acceptable list says Tax Desk or Team Lead.
  - A17 (SAP password reset) goes to HR / Admin. The plug-in has no IT role.
- **Regression check (`scripts/check_router.py`):**
  - The router alone ran on all 160 evaluation questions with v5 and with v6, about $0.01 each. Fresh v5 matched the 13 Nov eval's routes on 160/160.
  - v6 changed route, scope or date on 10 evaluation questions (6 dev, 4 holdout): "Arvana Retail Pvt Ltd", which is not a known scope, now maps to "Arvana Group".
  - Those 10 went through the full pipeline: **10/10 correct** (`eval_20261114_router_v6_changed.md`). The other 150 reach the same downstream steps with the same inputs, so the 13 Nov score stands.
