# Evaluation — all split — 10 Nov 2026 13:05

- questions: 160
- today: 2026-11-07
- judge calibration: not yet graded (eval/judge/hand_graded.csv)

## Config D

- **n**: 160
- **accuracy**: 91.9% (147/160)
- **partial**: 4.4% (7/160)
- **citation_strict**: 97.5% (156/160)
- **citation_lenient**: 98.1% (157/160)
- **outdated_conflict**: 8.7% (2/23)
- **outdated_must_not_say**: 2.8% (2/71)
- **abstained**: 0.0% (0/160)
- **unverified**: 7.5% (12/160)
- **errors**: 3
- **latency_p50_s**: 22.9
- **latency_p95_s**: 299.2
- **llm_calls**: 643
- **tokens_in**: 753867
- **tokens_out**: 61414
- **cost_usd**: 0.0

### By split

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev | 96 | 91.7% (88/96) | 97.9% (94/96) | 97.9% (94/96) | 0.0% (0/15) | 0.0% (0/43) | 0.0% (0/96) |
| holdout | 64 | 92.2% (59/64) | 96.9% (62/64) | 98.4% (63/64) | 25.0% (2/8) | 7.1% (2/28) | 0.0% (0/64) |

### By question type

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conflict | 23 | 82.6% (19/23) | 95.7% (22/23) | 100.0% (23/23) | 8.7% (2/23) | 8.7% (2/23) | 0.0% (0/23) |
| factual | 23 | 95.7% (22/23) | 100.0% (23/23) | 100.0% (23/23) | n/a | n/a | 0.0% (0/23) |
| procedural | 13 | 76.9% (10/13) | 100.0% (13/13) | 100.0% (13/13) | n/a | n/a | 0.0% (0/13) |
| scenario | 92 | 95.7% (88/92) | 96.7% (89/92) | 96.7% (89/92) | n/a | 0.0% (0/47) | 0.0% (0/92) |
| tacit | 9 | 88.9% (8/9) | 100.0% (9/9) | 100.0% (9/9) | n/a | 0.0% (0/1) | 0.0% (0/9) |

### By difficulty

| group | n | accuracy | citation_strict | citation_lenient | outdated_conflict | outdated_must_not_say | abstained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| easy | 33 | 93.9% (31/33) | 100.0% (33/33) | 100.0% (33/33) | 0.0% (0/8) | 0.0% (0/8) | 0.0% (0/33) |
| hard | 42 | 90.5% (38/42) | 95.2% (40/42) | 97.6% (41/42) | 0.0% (0/4) | 0.0% (0/29) | 0.0% (0/42) |
| medium | 85 | 91.8% (78/85) | 97.6% (83/85) | 97.6% (83/85) | 18.2% (2/11) | 5.9% (2/34) | 0.0% (0/85) |

### Routes and statuses

- routes: calculator:ap 95, lookup 61, None 3, practice 1
- statuses: answered 142, unverified 12, needs_specialist 3, error 3
- failure causes: generation 7, routing 3, verifier 2, calculator 1

### 15 worst questions

| id | type | verdict | cited | outdated | cause | why |
| --- | --- | --- | --- | --- | --- | --- |
| Q039 | procedural | wrong | True | False | verifier | The answer incorrectly interprets the AATO threshold and contradicts the gold answer by stating the invoice is acceptable without IRN when it should be returned |
| Q060 | procedural | wrong | True | False | generation | The answer directly contradicts the gold answer by permitting manual addition of the HSN/SAC code instead of returning the invoice to the supplier as INV_INCOMP |
| Q091 | scenario | wrong | False | False | routing | NimError('NIM request failed after retries: NIM HTTP 429: {"status":429,"title":"Too Many Requests"}') |
| Q092 | scenario | wrong | True | False | calculator | expected {'passed': False, 'excess': 132.0, 'limit': 120.0}; calculator price: {'passed': True, 'excess': 100.0, 'limit': 120.0} |
| Q108 | scenario | wrong | False | False | routing | NimError('NIM request failed after retries: NIM HTTP 429: {"status":429,"title":"Too Many Requests"}') |
| Q116 | scenario | wrong | False | False | routing | NimError('NIM request failed after retries: NIM HTTP 429: {"status":429,"title":"Too Many Requests"}') |
| Q004 | conflict | partial | True | False | generation | The answer correctly states payment runs are on Tuesday and Friday but omits the cut-off time of 1 pm on the previous working day. Missing: ['cut-off 1 pm on th |
| Q007 | conflict | partial | True | False | generation | The answer correctly identifies GSTR-2B as the return used for ITC claims but omits the specific generation date (14th of the following month) mentioned in the  |
| Q017 | conflict | partial | False | False | verifier | The answer correctly states that email alone is insufficient and describes the letterhead and cancelled cheque requirement, but omits the mandatory approvals an |
| Q035 | procedural | partial | True | False | generation | The answer correctly states the invoice is not wrong and explains the reverse charge mechanism, but omits the required procedural step to flag RCM_REVIEW and ro |
| Q048 | tacit | partial | True | False | generation | The answer correctly identifies the invoice as a re-sent copy and explains the '/A' suffix, but omits the required action to raise DUP_SUSPECT with a note and h |
| Q055 | conflict | partial | True | False | generation | The answer correctly states the cutoff (after the third-last working day) but omits the gold answer's second key fact that open GRNs are accrued instead. Missin |
| Q065 | factual | partial | True | False | generation | The answer correctly states that supplier bank details and PAN must never be pasted into e-mail, chat, or external tools, but it omits the gold answer's specifi |

Per-question CSV: `reports/eval_20261110_all_D.csv`
