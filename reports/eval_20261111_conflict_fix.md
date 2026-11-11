# Evaluation — all split — 11 Nov 2026 12:39

- questions: 23
- today: 2026-11-07
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 23
- **accuracy**: 95.7% (22/23)
- **partial**: 4.3% (1/23)
- **citation_strict**: 95.7% (22/23)
- **citation_lenient**: 100.0% (23/23)
- **outdated_conflict**: 8.7% (2/23)
- **outdated_must_not_say**: 8.7% (2/23)
- **abstained**: 0.0% (0/23)
- **unverified**: 17.4% (4/23)
- **errors**: 0
- **latency_p50_s**: 42.0
- **latency_p95_s**: 132.7
- **llm_calls**: 96
- **tokens_in**: 86027
- **tokens_out**: 15693
- **cost_usd**: 0.0

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 15 | 100.0% (15/15) | 100.0% (15/15) | 100.0% (15/15) | 0.0% (0/15) | 0.0% (0/15) | 0.0% (0/15) |
| holdout | 8 | 87.5% (7/8) | 87.5% (7/8) | 100.0% (8/8) | 25.0% (2/8) | 25.0% (2/8) | 0.0% (0/8) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 23 | 95.7% (22/23) | 95.7% (22/23) | 100.0% (23/23) | 8.7% (2/23) | 8.7% (2/23) | 0.0% (0/23) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (8/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) |
| hard | 4 | 75.0% (3/4) | 75.0% (3/4) | 100.0% (4/4) | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) |
| medium | 11 | 100.0% (11/11) | 100.0% (11/11) | 100.0% (11/11) | 18.2% (2/11) | 18.2% (2/11) | 0.0% (0/11) |

### Routes and statuses

- routes: lookup 18, calculator:ap 5
- statuses: answered 19, unverified 4
- failure causes: verifier 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q017 | conflict | partial | False | False | verifier | The answer correctly states that e-mail alone is insufficient and that a letterhead request with cancelled cheque and a call-back are required, but it omits the |

Per-question CSV: `reports/eval_20261111_all_D.csv`
