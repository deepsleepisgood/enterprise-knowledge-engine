# Load test, 15 Nov 2026

API https://enterprise-knowledge-engine-production.up.railway.app; each simulated user asks 1 questions one after another, all users starting at the same moment; 63 distinct real processor questions (Teams samples). Times are what the asker waits (submit to card, polling every 0.5 s).

| Users | Answers ok | Errors | Median s | 95th pct s | Slowest s | Answering median s | Waiting median s | Waiting max s | Answers/min | DB conns (start → peak) | API CPU peak % | API RAM peak MB | Model calls cached / new | New cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20 | 19/20 | 1 | 25.5 | 38.4 | 40.9 | 21.5 | 1.0 | 19.8 | 27.9 | – → – | – | – | 0 / 0 | $0.000 |

Card statuses per level:

- 20 users: {'answered': 17, 'needs_specialist': 1, 'unverified': 1}

Errors:

- 20 users: URLError: <urlopen error [WinError 10060] A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected ho
