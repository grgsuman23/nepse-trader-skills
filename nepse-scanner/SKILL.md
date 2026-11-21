---
name: nepse-scanner
description: Scan liquid NEPSE equities for daily swing setups (20-day breakout, 20-day average reclaim, RSI(2) pullback, 52-week high) on the last close, each shown with the stock's own past record for that setup. Use when the user asks what is setting up on NEPSE, for trade ideas, or to scan a sector.
---

# NEPSE scanner

`python nepse-scanner/scan.py [--setups high52,breakout20] [--sector "Hydro Power"] [--symbols NABIL,NICA] [--date YYYY-MM-DD]`

These are end-of-day swing setups, not intraday ones. NEPSE's T+2 settlement means a share can't be sold on the day it is bought, and there are no free intraday bars.

When reporting hits:
1. Lead with the data tag (LIVE-EOD, STALE or REPLAY) and the as-of date. If STALE, run nepse-update first.
2. Every hit carries its own record on that stock. Always show it, and don't present a hit without it.
3. State the market-wide fact from nepse-backtest: on 2016–2026 data, after costs, breakout20, ma20_reclaim and rsi2_pullback did not make money. Only high52 had a positive average, and it was near zero for 2023–2026. A hit is a candidate, not a recommendation.
4. Next steps: nepse-exit → nepse-budget → nepse-risk → nepse-ticket, with nepse-timemachine for odds.
