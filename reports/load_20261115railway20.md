# Load test, 15 Nov 2026

API https://enterprise-knowledge-engine-production.up.railway.app; each simulated user asks 1 questions one after another, all users starting at the same moment; 63 distinct real processor questions (Teams samples). Times are what the asker waits (submit to card, polling every 0.5 s).

| Users | Answers ok | Errors | Median s | 95th pct s | Slowest s | Answering median s | Waiting median s | Waiting max s | Answers/min | DB conns (start → peak) | API CPU peak % | API RAM peak MB | Model calls cached / new | New cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20 | 10/20 | 10 | 150.2 | 219.1 | 219.1 | 148.1 | 2.0 | 19.8 | 2.7 | – → – | – | – | 0 / 0 | $0.000 |

Card statuses per level:

- 20 users: {'answered': 8, 'needs_specialist': 1, 'unsupported': 1}

Errors:

- 20 users: URLError: <urlopen error [WinError 10060] A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected ho
- 20 users: URLError: <urlopen error [WinError 10060] A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected ho
- 20 users: TimeoutError: The read operation timed out
- 20 users: TimeoutError: The read operation timed out
- 20 users: TimeoutError: The read operation timed out
- 20 users: TimeoutError: The read operation timed out
- 20 users: TimeoutError: The read operation timed out
- 20 users: TimeoutError: The read operation timed out
- 20 users: URLError: <urlopen error [WinError 10060] A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected ho
- 20 users: TimeoutError: The read operation timed out
