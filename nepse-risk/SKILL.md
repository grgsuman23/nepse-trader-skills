---
name: nepse-risk
description: PASS/BLOCK pre-trade risk gate for a NEPSE plan, checking stale data, thin turnover, chasing a stock near the upper limit, lower-limit lock, reward:risk after costs, loss cap, position cap, sector cap including holdings, and existing holdings. Use before any NEPSE order, or when the user asks whether a trade is safe or within their rules.
---

# NEPSE risk gate

`python nepse-risk/check.py --plan plan.json [--portfolio portfolio.json]` exits with 0 on PASS and 2 on BLOCK.

Format of portfolio.json: `{"holdings": [{"symbol": "NABIL", "qty": 100, "avg_cost": 520, "last_price": 550}]}`

Rules for reporting:
- A single BLOCK blocks the trade. Report each block reason in plain words, and never soften a BLOCK into "probably fine".
- Mention the warnings too: an upcoming book closure or AGM (which resets the price), the weekend, and stops wider than the daily limit.
- Limits are in config.json. Change them only when the user explicitly asks, and never to make a blocked trade pass.
