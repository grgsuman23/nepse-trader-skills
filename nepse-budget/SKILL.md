---
name: nepse-budget
description: Size a NEPSE trade in whole 10-share lots and show every charge (SEBON commission slab, 0.015% SEBON fee, Rs 25 DP, 5% or 3.75% CGT), the loss at the stop and the gain at the target. Use for "how many shares", position sizing, or "what will this trade cost" on NEPSE.
---

# NEPSE budget and fees

- `python nepse-budget/size.py --plan plan.json [--portfolio portfolio.json] [--budget 300000] --out plan.json`
- `python nepse-budget/size.py --fees SHARES BUY SELL` gives just the charges.

The size is the smallest of three caps: the risk cap (`max_loss_per_trade_npr`, including fees), the position cap (`max_position_pct`) and free cash (budget minus holdings minus a 5% buffer). It is then rounded down to a multiple of 10, because regular-session orders must be in multiples of 10.

Rates verified on 21 Nov 2026, all set in config.json:
- Commission by slab, applied to the whole trade value: 0.36% up to Rs 50k (minimum Rs 10), 0.33% to Rs 5 lakh, 0.31% to Rs 20 lakh, 0.27% to Rs 1 crore, 0.24% above that
- SEBON fee 0.015%, and DP charge Rs 25 per scrip per day on each side
- CGT for resident individuals: 5% if held 365 days or less, 3.75% if held longer (from 22 Sep 2026). Institutions: check the rate with the broker or a tax adviser.

Always say which cap is binding. Show the net reward:risk after costs, which is lower than the nominal R.
