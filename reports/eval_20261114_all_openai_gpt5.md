# Evaluation — all split — 14 Nov 2026 21:12

- questions: 158
- today: 2026-11-07
- excluded: Q017, Q062 (eval/excluded_questions.csv)
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 158
- **accuracy**: 88.6% (140/158)
- **partial**: 4.4% (7/158)
- **citation_strict**: 98.7% (156/158)
- **citation_lenient**: 98.7% (156/158)
- **outdated_conflict**: 0.0% (0/21)
- **outdated_must_not_say**: 1.4% (1/69)
- **abstained**: 0.0% (0/158)
- **unverified**: 0.6% (1/158)
- **errors**: 2
- **latency_p50_s**: 32.5
- **latency_p95_s**: 80.4
- **llm_calls**: 543
- **tokens_in**: 586056
- **tokens_out**: 297428
- **cost_usd**: 0.0

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 96 | 89.6% (86/96) | 99.0% (95/96) | 99.0% (95/96) | 0.0% (0/15) | 2.3% (1/43) | 0.0% (0/96) |
| holdout | 62 | 87.1% (54/62) | 98.4% (61/62) | 98.4% (61/62) | 0.0% (0/6) | 0.0% (0/26) | 0.0% (0/62) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 21 | 76.2% (16/21) | 100.0% (21/21) | 100.0% (21/21) | 0.0% (0/21) | 0.0% (0/21) | 0.0% (0/21) |
| factual | 23 | 91.3% (21/23) | 100.0% (23/23) | 100.0% (23/23) | n/a | n/a | 0.0% (0/23) |
| procedural | 13 | 84.6% (11/13) | 100.0% (13/13) | 100.0% (13/13) | n/a | n/a | 0.0% (0/13) |
| scenario | 92 | 93.5% (86/92) | 97.8% (90/92) | 97.8% (90/92) | n/a | 0.0% (0/47) | 0.0% (0/92) |
| tacit | 9 | 66.7% (6/9) | 100.0% (9/9) | 100.0% (9/9) | n/a | 100.0% (1/1) | 0.0% (0/9) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 33 | 90.9% (30/33) | 100.0% (33/33) | 100.0% (33/33) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/33) |
| hard | 41 | 85.4% (35/41) | 95.1% (39/41) | 95.1% (39/41) | 0.0% (0/3) | 3.6% (1/28) | 0.0% (0/41) |
| medium | 84 | 89.3% (75/84) | 100.0% (84/84) | 100.0% (84/84) | 0.0% (0/10) | 0.0% (0/33) | 0.0% (0/84) |

### Routes and statuses

- routes: calculator:ap 93, lookup 62, None 2, practice 1
- statuses: answered 155, error 2, unverified 1
- failure causes: generation 12, routing 3, infra error 2, calculator 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q012 | conflict | wrong | True | False | generation | It correctly says courier invoices need a PO, but cites the wrong SOP version and omits that travel-agency invoices also require a PO per the gold answer. Missi |
| Q016 | procedural | wrong | True | False | generation | It correctly says a Senior Processor clears suspected duplicates before posting, but wrongly introduces a ₹10 lakh threshold that contradicts the gold rule. |
| Q034 | tacit | wrong | True | False | generation | Gold requires treating it as a mixed case always escalated to the Tax Desk (raise TDS_SECTION_UNCLEAR), but the answer instructs the user to classify it themsel |
| Q044 | factual | wrong | True | False | generation | It correctly lists the required fields but incorrectly narrows the return condition to when both are missing, contradicting the rule to return if both are not p |
| Q050 | tacit | wrong | True | False | generation | It contradicts the gold by instructing an immediate NO_GRN raise instead of holding and waiting a couple of days for this known supplier. |
| Q092 | scenario | wrong | True | False | calculator | expected {'passed': False, 'excess': 132.0, 'limit': 120.0}; calculator price: {'passed': True, 'excess': 100.0, 'limit': 120.0} |
| Q144 | scenario | wrong | False | False | infra error | OperationalError('(psycopg.OperationalError) consuming input failed: server closed the connection unexpectedly\n\tThis probably means the server terminated abno |
| Q146 | scenario | wrong | False | False | infra error | InternalError('(psycopg.errors.IdleInTransactionSessionTimeout) terminating connection due to idle-in-transaction timeout') |
| Q154 | scenario | wrong | True | False | routing | expected {'passed': True, 'exception': None}; graded from text |
| Q155 | scenario | wrong | True | False | routing | expected {'passed': True, 'exception': None}; graded from text |
| Q159 | scenario | wrong | True | False | routing | expected {'passed': True, 'exception': None}; graded from text |
| Q002 | conflict | partial | True | False | generation | It correctly states there is no tolerance except for Arvana Infra bulk materials but omits citing the required memo code CM-INF-02 from the gold answer. Missing |
| Q021 | conflict | partial | True | False | generation | It correctly states the 45-day cap from acceptance and 15 days without a written agreement, but omits that the agreed term applies if shorter than 45 days. Miss |
| Q039 | procedural | partial | True | False | generation | It correctly says to return as IRN_MISSING and not pay the base value when e-invoicing is required, but omits that the invoice is not valid for ITC and that no  |
| Q040 | conflict | partial | True | False | generation | It correctly states the 5% and ₹25,000 limits for cement and adds acceptable escalation detail, but it omits explicitly naming the other three materials to whic |

Per-question CSV: `reports/eval_20261114_all_D.csv`
