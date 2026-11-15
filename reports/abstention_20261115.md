# Abstention set — 15 Nov 2026

20 questions the corpus does not cover (`eval/abstain.csv`). Target: at least 90% not answered and routed to a sensible role.

- **Not answered (abstained):** 19/20 (95%)
- **Abstained and routed to an acceptable role (pass):** 17/20 (85%)
- **Answered anyway (false answers):** 1/20

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
| A14 | process_gap | How do I process a supplier invoice billed in US dollars? | answered | — | FAIL |
| A15 | process_gap | Can we pay a supplier in cryptocurrency? | unsupported | Team Lead | PASS |
| A16 | process_gap | Which ERP system will Meridian migrate to next year? | unsupported | Team Lead | PASS |
| A17 | it_support | How do I reset my SAP password? | unsupported | HR / Admin team | FAIL |
| A18 | company_data | What was Arvana Infra's total supplier spend last quarter? | unsupported | Team Lead | PASS |
| A19 | general_knowledge | What is the capital of Telangana? | unsupported | Team Lead | PASS |
| A20 | company_data | Who is the CFO of Arvana Retail by name? | unsupported | AP Controller | PASS |

## Not passed

- **A09** Should Arvana Pharma choose the new income tax regime for its employees? — status `unsupported`, routed to HR / Admin team (acceptable: Tax Desk|Team Lead)
- **A14** How do I process a supplier invoice billed in US dollars? — status `answered`, routed to nobody (acceptable: Team Lead|AP Process Excellence|Treasury (client)); said: “Start with the duplicate check before indexing: every invoice is compared with invoices received in the last 18 months for the same supplier, and suspected duplicates go to the exception queue as DUP_SUSPECT and are never posted until a Senior Processor clears them. [1] Then check the mandatory fiel”
- **A17** How do I reset my SAP password? — status `unsupported`, routed to HR / Admin team (acceptable: Team Lead|AP Process Excellence)
