# Evaluation — all split — 11 Nov 2026 12:04

- questions: 160
- today: 2026-11-07
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 160
- **accuracy**: 96.9% (155/160)
- **partial**: 0.6% (1/160)
- **citation_strict**: 98.1% (157/160)
- **citation_lenient**: 98.8% (158/160)
- **outdated_conflict**: 8.7% (2/23)
- **outdated_must_not_say**: 4.2% (3/71)
- **abstained**: 0.0% (0/160)
- **unverified**: 3.1% (5/160)
- **errors**: 2
- **latency_p50_s**: 36.4
- **latency_p95_s**: 129.0
- **llm_calls**: 563
- **tokens_in**: 582807
- **tokens_out**: 86841
- **cost_usd**: 0.0

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 96 | 99.0% (95/96) | 99.0% (95/96) | 99.0% (95/96) | 0.0% (0/15) | 2.3% (1/43) | 0.0% (0/96) |
| holdout | 64 | 93.8% (60/64) | 96.9% (62/64) | 98.4% (63/64) | 25.0% (2/8) | 7.1% (2/28) | 0.0% (0/64) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 23 | 95.7% (22/23) | 95.7% (22/23) | 100.0% (23/23) | 8.7% (2/23) | 8.7% (2/23) | 0.0% (0/23) |
| factual | 23 | 91.3% (21/23) | 91.3% (21/23) | 91.3% (21/23) | n/a | n/a | 0.0% (0/23) |
| procedural | 13 | 92.3% (12/13) | 100.0% (13/13) | 100.0% (13/13) | n/a | n/a | 0.0% (0/13) |
| scenario | 92 | 98.9% (91/92) | 100.0% (92/92) | 100.0% (92/92) | n/a | 0.0% (0/47) | 0.0% (0/92) |
| tacit | 9 | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) | n/a | 100.0% (1/1) | 0.0% (0/9) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 33 | 97.0% (32/33) | 97.0% (32/33) | 97.0% (32/33) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/33) |
| hard | 42 | 95.2% (40/42) | 97.6% (41/42) | 100.0% (42/42) | 0.0% (0/4) | 3.4% (1/29) | 0.0% (0/42) |
| medium | 85 | 97.6% (83/85) | 98.8% (84/85) | 98.8% (84/85) | 18.2% (2/11) | 5.9% (2/34) | 0.0% (0/85) |

### Routes and statuses

- routes: calculator:ap 98, lookup 59, None 2, practice 1
- statuses: answered 152, unverified 5, error 2, needs_specialist 1
- failure causes: infra error 2, generation 1, verifier 1, calculator 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q011 | factual | wrong | False | False | infra error | InternalError('(psycopg.errors.IdleInTransactionSessionTimeout) terminating connection due to idle-in-transaction timeout') |
| Q039 | procedural | wrong | True | False | verifier | The answer misreads the threshold (exactly vs above ₹5 crore) and contradicts the gold answer by allowing payment when the gold says nothing is paid until a val |
| Q054 | factual | wrong | False | False | infra error | InternalError("(psycopg.InternalError) received 2 results from command 'ROLLBACK'") |
| Q092 | scenario | wrong | True | False | calculator | expected {'passed': False, 'excess': 132.0, 'limit': 120.0}; calculator price: {'passed': True, 'excess': 100.0, 'limit': 120.0} |
| Q017 | conflict | partial | False | False | generation | The answer correctly states that e-mail alone is insufficient and describes the letterhead and cancelled cheque requirement, but it omits the mandatory approval |

Per-question CSV: `reports/eval_20261111_all_D.csv`
