# Evaluation — all split — 14 Nov 2026 22:23

- questions: 158
- today: 2026-11-07
- excluded: Q017, Q062 (eval/excluded_questions.csv)
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 158
- **accuracy**: 88.0% (139/158)
- **partial**: 9.5% (15/158)
- **citation_strict**: 100.0% (158/158)
- **citation_lenient**: 100.0% (158/158)
- **outdated_conflict**: 0.0% (0/21)
- **outdated_must_not_say**: 1.4% (1/69)
- **abstained**: 0.0% (0/158)
- **unverified**: 0.6% (1/158)
- **errors**: 0
- **latency_p50_s**: 15.5
- **latency_p95_s**: 21.1
- **llm_calls**: 538
- **tokens_in**: 723841
- **tokens_out**: 122587
- **cost_usd**: 1.5002

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 96 | 87.5% (84/96) | 100.0% (96/96) | 100.0% (96/96) | 0.0% (0/15) | 2.3% (1/43) | 0.0% (0/96) |
| holdout | 62 | 88.7% (55/62) | 100.0% (62/62) | 100.0% (62/62) | 0.0% (0/6) | 0.0% (0/26) | 0.0% (0/62) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 21 | 71.4% (15/21) | 100.0% (21/21) | 100.0% (21/21) | 0.0% (0/21) | 0.0% (0/21) | 0.0% (0/21) |
| factual | 23 | 78.3% (18/23) | 100.0% (23/23) | 100.0% (23/23) | n/a | n/a | 0.0% (0/23) |
| procedural | 13 | 61.5% (8/13) | 100.0% (13/13) | 100.0% (13/13) | n/a | n/a | 0.0% (0/13) |
| scenario | 92 | 98.9% (91/92) | 100.0% (92/92) | 100.0% (92/92) | n/a | 0.0% (0/47) | 0.0% (0/92) |
| tacit | 9 | 77.8% (7/9) | 100.0% (9/9) | 100.0% (9/9) | n/a | 100.0% (1/1) | 0.0% (0/9) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 33 | 81.8% (27/33) | 100.0% (33/33) | 100.0% (33/33) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/33) |
| hard | 41 | 92.7% (38/41) | 100.0% (41/41) | 100.0% (41/41) | 0.0% (0/3) | 3.6% (1/28) | 0.0% (0/41) |
| medium | 84 | 88.1% (74/84) | 100.0% (84/84) | 100.0% (84/84) | 0.0% (0/10) | 0.0% (0/33) | 0.0% (0/84) |

### Routes and statuses

- routes: calculator:ap 99, lookup 58, practice 1
- statuses: answered 156, needs_specialist 1, unverified 1
- failure causes: generation 18, calculator 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q010 | conflict | wrong | True | False | generation | The gold answer says only the Client CFO approves via the workflow; the graded answer adds a budget owner and extra rules, contradicting the gold. |
| Q039 | procedural | wrong | True | False | generation | The graded answer allows payment without IRN at ₹5 crore and omits the IRN_MISSING return, ITC invalidity, and the hold on payment until a valid e-invoice, dire |
| Q057 | factual | wrong | True | False | generation | The answer contradicts the gold by saying the rule is to apply the credit note to the original invoice, while the gold specifies setting it off against the next |
| Q092 | scenario | wrong | True | False | calculator | expected {'passed': False, 'excess': 132.0, 'limit': 120.0}; calculator price: {'passed': True, 'excess': 100.0, 'limit': 120.0} |
| Q003 | conflict | partial | True | False | generation | It correctly states the ₹10 at invoice-total level auto-acceptance, but adds extra conditions and procedural details not present in the gold answer. Missing: [' |
| Q004 | conflict | partial | True | False | generation | It correctly states payment runs are on Tuesday and Friday, but omits the 1 pm previous working day cut-off noted in the gold answer. Missing: ['Cut-off is 1 pm |
| Q005 | conflict | partial | True | False | generation | It correctly gives the 1 pm previous working day cut-off and aligns with run days and payment timing guidance, but the expert tip omits Tuesday, missing a key f |
| Q009 | conflict | partial | True | False | generation | It correctly states AP Controller approval for ₹10–50 lakh but adds Budget owner approval for a non‑PO invoice, which is an extra condition not present in the g |
| Q011 | factual | partial | True | False | generation | It correctly states that non-PO rent invoices need budget owner approval and that amount-based approvals still apply, but it introduces an extraneous ₹10 lakh c |
| Q012 | conflict | partial | True | False | generation | It correctly states courier invoices require a PO now, but omits that travel-agency invoices also require a PO per the gold answer. Missing: ['Travel-agency inv |
| Q014 | procedural | partial | True | False | generation | Includes hold as NO_GRN, automatic notification, 2-day reminder, 5-day escalation, and never post without GRN, but adds an unsupported 5-day target resolution o |
| Q018 | procedural | partial | True | False | generation | Includes the core actions (don’t call the number in the request; call the vendor-master number; log as suspicious; inform AP Controller) but adds non-required s |
| Q022 | factual | partial | True | False | generation | It correctly states that MSME payment limits do not apply to medium enterprises and that they follow normal terms, but adds an extra rule about non‑MSME payment |
| Q030 | factual | partial | True | False | generation | It correctly states the core rule (deduct TDS at 20% or the applicable rate, whichever is higher) but adds extra procedural details not in the gold; no contradi |
| Q033 | tacit | partial | True | False | generation | States the correct section (194J) and rate (2%) with proper rationale and includes general practice notes, but the expert tip provided is about lift AMC, not th |

Per-question CSV: `reports/eval_20261114_all_D.csv`
