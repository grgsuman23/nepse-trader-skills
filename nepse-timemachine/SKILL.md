---
name: nepse-timemachine
description: Replay a NEPSE trade plan 10,000 times from the stock's own real daily bars (trend removed, ±15% limit and T+2 applied) and against every past signal of the same setup on that stock, giving odds of target, stop and profit after costs. Use when the user asks for the odds of a NEPSE trade, or to stress-test a plan.
---

# NEPSE time machine

`python nepse-timemachine/timemachine.py --plan plan.json [--paths 10000] [--lookback 250] [--keep-drift]`

Report three things: P(target), P(stop) and P(profit after costs); the expected net % with its 5th–95th percentile range; and the stock's own history with this setup.

Be honest about what the calibration (nepse-backtest/calibrate.py, 1,500 past signals) showed:
- Its average odds are about right: profit after costs was predicted 37.9% and happened 36.6% of the time.
- It slightly understates target hits on breakouts (predicted 25%, actual 31%).
- It does not separate good trades from bad ones. Its per-trade odds scored no better than quoting the overall average.

So present the numbers as typical odds for this kind of trade, not as a forecast for this particular one. `--keep-drift` replays the stock's past trend and tested about 10 percentage points too optimistic.
