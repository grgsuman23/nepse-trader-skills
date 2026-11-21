---
name: nepse-backtest
description: Measure how accurate each NEPSE setup has really been, across all liquid equities since 2016, after fees and CGT and with the T+2 rule, compared with random entries under the same exits, split into early and late periods, plus a calibration check of the time machine. Use when the user asks whether a strategy works, for its win rate or accuracy, or to backtest NEPSE setups.
---

# NEPSE backtest and accuracy

- `python nepse-backtest/backtest.py [--setups high52] [--regime] [--start 2016-01-01] [--split 2023-01-01] [--json out.json]`
- `python nepse-backtest/calibrate.py [--sample 1500 --paths 1000]`

How to read the output:
- **edge pp** = the setup's average net % minus the average for random entries.
- An edge is real only if it is above about 2 standard errors and keeps the same sign in the early and late periods.
- Random entries lose around 0.5–1% per trade, which is roughly the round-trip cost.

Results on data to 20 Nov 2026 are in docs/ACCURACY.md. Quote those results, or rerun the scripts, rather than guessing. Caveats to state: survivorship bias (only today's listed companies), adjusted prices, and no slippage beyond gap fills.
