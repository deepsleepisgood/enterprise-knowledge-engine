# Load test, 15 Nov 2026

API https://enterprise-knowledge-engine-production.up.railway.app; each simulated user asks 1 questions one after another, all users starting at the same moment; 63 distinct real processor questions (Teams samples). Times are what the asker waits (submit to card, polling every 0.5 s).

| Users | Answers ok | Errors | Median s | 95th pct s | Slowest s | Answering median s | Waiting median s | Waiting max s | Answers/min | DB conns (start → peak) | API CPU peak % | API RAM peak MB | Model calls cached / new | New cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 3/3 | 0 | 34.8 | 43.2 | 43.2 | 33.3 | 1.4 | 1.5 | 4.2 | – → – | – | – | 0 / 0 | $0.000 |
| 5 | 4/5 | 1 | 31.9 | 47.2 | 47.2 | 30.8 | 1.0 | 1.1 | 3.2 | – → – | – | – | 0 / 0 | $0.000 |

Card statuses per level:

- 3 users: {'answered': 2, 'needs_specialist': 1}
- 5 users: {'answered': 4}

Errors:

- 5 users: URLError: <urlopen error [WinError 10060] A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected ho
