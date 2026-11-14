# Evaluation — all split — 14 Nov 2026 15:33

- questions: 160
- today: 2026-11-07
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 160
- **accuracy**: 97.5% (156/160)
- **partial**: 0.6% (1/160)
- **citation_strict**: 98.1% (157/160)
- **citation_lenient**: 98.8% (158/160)
- **outdated_conflict**: 4.3% (1/23)
- **outdated_must_not_say**: 2.8% (2/71)
- **abstained**: 1.2% (2/160)
- **unverified**: 0.0% (0/160)
- **errors**: 0
- **latency_p50_s**: 13.0
- **latency_p95_s**: 23.6
- **llm_calls**: 539
- **tokens_in**: 731577
- **tokens_out**: 93497
- **cost_usd**: 0.0602

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 96 | 99.0% (95/96) | 99.0% (95/96) | 99.0% (95/96) | 0.0% (0/15) | 2.3% (1/43) | 1.0% (1/96) |
| holdout | 64 | 95.3% (61/64) | 96.9% (62/64) | 98.4% (63/64) | 12.5% (1/8) | 3.6% (1/28) | 1.6% (1/64) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 23 | 95.7% (22/23) | 95.7% (22/23) | 100.0% (23/23) | 4.3% (1/23) | 4.3% (1/23) | 0.0% (0/23) |
| factual | 23 | 91.3% (21/23) | 91.3% (21/23) | 91.3% (21/23) | n/a | n/a | 8.7% (2/23) |
| procedural | 13 | 100.0% (13/13) | 100.0% (13/13) | 100.0% (13/13) | n/a | n/a | 0.0% (0/13) |
| scenario | 92 | 98.9% (91/92) | 100.0% (92/92) | 100.0% (92/92) | n/a | 0.0% (0/47) | 0.0% (0/92) |
| tacit | 9 | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) | n/a | 100.0% (1/1) | 0.0% (0/9) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 33 | 100.0% (33/33) | 100.0% (33/33) | 100.0% (33/33) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/33) |
| hard | 42 | 95.2% (40/42) | 97.6% (41/42) | 100.0% (42/42) | 0.0% (0/4) | 3.4% (1/29) | 0.0% (0/42) |
| medium | 85 | 97.6% (83/85) | 97.6% (83/85) | 97.6% (83/85) | 9.1% (1/11) | 2.9% (1/34) | 2.4% (2/85) |

### Routes and statuses

- routes: calculator:ap 99, lookup 59, practice 2
- statuses: answered 157, unsupported 2, needs_specialist 1
- failure causes: generation 3, calculator 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q044 | factual | wrong | False | False | generation | no answer given (unsupported) |
| Q045 | factual | wrong | False | False | generation | no answer given (unsupported) |
| Q092 | scenario | wrong | True | False | calculator | expected {'passed': False, 'excess': 132.0, 'limit': 120.0}; calculator price: {'passed': True, 'excess': 100.0, 'limit': 120.0} |
| Q017 | conflict | partial | False | False | generation | The answer correctly rejects the e-mailed request and covers the letterhead/cancelled cheque requirement and the call-back to the vendor master number, but it o |

Per-question CSV: `reports/eval_20261114_all_D.csv`
