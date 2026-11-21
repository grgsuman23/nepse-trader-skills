---
name: nepse-exit
description: Set the stop, target and time stop for a NEPSE stock before buying, with checks against the 15% daily price limit and the T+2 lock-in, and save plan.json. Use when the user wants to plan an entry or exit, a stop-loss or a target for a NEPSE stock.
---

# NEPSE exit plan

`python nepse-exit/exit.py SYMBOL [--setup high52] [--entry 555] [--stop atr|swing|pct:6|price:520] [--target r:2|price:610]`

This writes plan.json, which the budget, risk, ticket and time-machine skills read.

Explain the warnings in plain words:
- **T+2:** shares can't be sold for 2 sessions. If the price falls through the stop before then, the real exit is the next allowed open, which may be well below the stop.
- **Wide stop:** a stop more than 15% away can't be reached in a single session, and a stock locked at the lower limit has no buyers.
- **Break-even:** the sell price needed to cover charges on both sides, before CGT.

Always confirm the plan with the user before sizing it.
