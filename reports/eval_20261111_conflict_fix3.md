# Evaluation — all split — 11 Nov 2026 13:55

- questions: 23
- today: 2026-11-07
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 23
- **accuracy**: 87.0% (20/23)
- **partial**: 4.3% (1/23)
- **citation_strict**: 87.0% (20/23)
- **citation_lenient**: 91.3% (21/23)
- **outdated_conflict**: 8.7% (2/23)
- **outdated_must_not_say**: 8.7% (2/23)
- **abstained**: 0.0% (0/23)
- **unverified**: 4.3% (1/23)
- **errors**: 2
- **latency_p50_s**: 68.3
- **latency_p95_s**: 260.7
- **llm_calls**: 85
- **tokens_in**: 92932
- **tokens_out**: 12541
- **cost_usd**: 0.0

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 15 | 93.3% (14/15) | 93.3% (14/15) | 93.3% (14/15) | 0.0% (0/15) | 0.0% (0/15) | 0.0% (0/15) |
| holdout | 8 | 75.0% (6/8) | 75.0% (6/8) | 87.5% (7/8) | 25.0% (2/8) | 25.0% (2/8) | 0.0% (0/8) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 23 | 87.0% (20/23) | 87.0% (20/23) | 91.3% (21/23) | 8.7% (2/23) | 8.7% (2/23) | 0.0% (0/23) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 8 | 87.5% (7/8) | 87.5% (7/8) | 87.5% (7/8) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/8) |
| hard | 4 | 75.0% (3/4) | 75.0% (3/4) | 100.0% (4/4) | 0.0% (0/4) | 0.0% (0/4) | 0.0% (0/4) |
| medium | 11 | 90.9% (10/11) | 90.9% (10/11) | 90.9% (10/11) | 18.2% (2/11) | 18.2% (2/11) | 0.0% (0/11) |

### Routes and statuses

- routes: lookup 16, calculator:ap 5, None 2
- statuses: answered 20, error 2, unverified 1
- failure causes: infra error 2, generation 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q002 | conflict | wrong | False | False | infra error | LLMError('model output did not match SupportOut: 1 validation error for SupportOut\nitems.1.problem\n  Input should be a valid string [type=string_type, input_v |
| Q042 | conflict | wrong | False | False | infra error | InternalError('(psycopg.errors.IdleInTransactionSessionTimeout) terminating connection due to idle-in-transaction timeout') |
| Q017 | conflict | partial | False | False | generation | The answer correctly states that e-mail alone is insufficient and describes the letterhead and cancelled cheque requirement, but it omits the mandatory approval |

Per-question CSV: `reports/eval_20261111_all_D.csv`
