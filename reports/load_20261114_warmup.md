# Load test, 14 Nov 2026

API http://127.0.0.1:8000; each simulated user asks 1 questions one after another, all users starting at the same moment; 63 distinct real processor questions (Teams samples). Times are what the asker waits (submit to card, polling every 0.5 s).

| Users | Answers ok | Errors | Median s | 95th pct s | Slowest s | Answering median s | Waiting median s | Waiting max s | Answers/min | DB conns (start → peak) | API CPU peak % | API RAM peak MB | Model calls cached / new | New cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1/1 | 0 | 20.4 | 20.4 | 20.4 | 18.2 | 2.1 | 2.1 | 2.9 | 1 → 3 | 807 | 1987 | 2 / 2 | $0.000 |

Card statuses per level:

- 1 users: {'answered': 1}
