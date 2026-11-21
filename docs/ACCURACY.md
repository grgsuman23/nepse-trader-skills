# Accuracy report (data to 20 Nov 2026)

The tests were run on 21 Nov 2026 against 276 listed NEPSE equities with daily data from 2016 to 20 Nov 2026, using prices adjusted for bonus and rights issues.

**Trade rules applied to every test:**
- Each trade enters at the next session's open after the signal.
- No sale is possible for 2 sessions (T+2). If the stop was broken while the shares were locked in, the trade exits at the open of the first session it can sell.
- A gap down fills at the open. If one bar touches both the stop and the target, the stop counts as hit first.
- A stock locked at its upper limit is skipped, because the buy would not fill.
- Only liquid stocks count: 20-day average turnover of at least Rs 50 lakh.

**Costs:** every return is net of all charges on a Rs 1 lakh position, using the real commission slab, the SEBON fee, the DP charge on both sides and 5% CGT.

**Baseline:** random entries on the same stocks and liquid days, with the same exits. "Edge" is the setup's average net % minus the random average.

## 1. Engine correctness: 30/30 tests pass

The fee code was checked against ShareHub's published worked examples:
- Buying 100 shares at Rs 500 costs Rs 50,212.50 in total, matching ShareHub exactly.
- Sell-side charges on a Rs 5.6 lakh sale come to Rs 1,845, also matching. ShareHub's CGT figure in the same example differs only because it leaves out the Rs 25 DP charge on the buy side.

The rest of the engine is covered by tests for:
- commission slabs and the minimum commission
- break-even price
- bonus back-adjustment, checked on NABIL's January 2023 bonus
- indicators
- target, stop, gap, T+2, time and same-bar exits
- skipping stocks locked at the upper limit
- signals that use no future data
- sizing caps
- every risk-gate rule

Three real trades (GRDBL, RLFL, SPIL) were also traced bar by bar against the raw CSVs.

## 2. Setup accuracy, after all costs

| Setup | Trades | Win % | Avg net % | Random avg % | Edge pp | 2016–22 avg | 2023–26 avg |
|---|---|---|---|---|---|---|---|
| breakout20 | 4,432 | 36.5 | −0.85 | −0.71 | −0.14 | −0.32 | −1.18 |
| ma20_reclaim | 3,078 | 35.1 | −1.26 | −0.70 | −0.56 | −0.74 | −1.56 |
| rsi2_pullback | 6,083 | 48.3 | −0.72 | −1.08 | +0.36 | −0.84 | −0.65 |
| high52 | 1,519 | 43.4 | **+0.69** | −0.46 | **+1.15** | +1.19 | +0.22 |

What this shows:
- **breakout20 and ma20_reclaim** have no edge. Both lost money and did no better than random entries.
- **rsi2_pullback** beats random entries consistently, by about 4.5 standard errors, but still loses money after costs. It is a better way to lose than picking at random, not a way to make money.
- **high52**, buying a new 52-week high, is the only setup with a positive average. Its edge over random holds in both periods, but the 2023–26 average of +0.22% is within one standard error (0.42) of zero. It worked well in strong market years (2021: +2.3%, 2024: +1.5%) and lost in weak ones (2025: −2.0%, 2026 so far: −4.5%).

Only stopping out after T+2 is not what sinks these setups: random entries lose about 0.5–1% per trade, which is roughly the round-trip cost. A setup has to beat that cost before it can make money.

## 3. NEPSE index trend filter (`--regime`)

The filter takes trades only when the NEPSE index is above its 50-day average. It did not help: high52 averaged +0.61% with the filter against +0.69% without it, and the other setups were unchanged or worse.

## 4. Robustness of high52 to its exit settings

| Stop | Target | Max sessions | Avg net % | Edge pp | 2023–26 avg |
|---|---|---|---|---|---|
| 2.0 ATR | 2R | 20 (default) | +0.69 | +0.86 | +0.22 |
| 1.5 ATR | 2R | 20 | −0.19 | +0.15 | −0.43 |
| 2.5 ATR | 2R | 20 | +1.29 | +1.60 | +0.49 |
| 2.0 ATR | 3R | 30 | +1.58 | +1.89 | +0.54 |
| 3.0 ATR | 3R | 40 | +2.39 | +1.90 | +0.91 |

The edge over random entries survives most of these changes, and wider exits that let winners run did better. But every variant's 2023–26 result is within about 1–1.2 standard errors of zero. The defaults were not changed to the best row, because picking the winner on the same data would be overfitting.

The edge pp column here comes from a separate random-baseline run, so the default row's +0.86 differs slightly from the +1.15 in section 2.

## 5. Time machine calibration (1,500 past signals, pre-signal data only)

| Output | Mean predicted | Actually happened | Brier score (model vs always guessing the average) |
|---|---|---|---|
| P(profit after costs), trend removed (default) | 37.9% | 36.6% | 0.235 vs 0.232 |
| P(target), trend removed (default) | 25.1% | 31.1% | 0.220 vs 0.214 |
| P(profit after costs), trend kept (`--keep-drift`) | 46.7% | 36.6% | 0.252 vs 0.232 |

- On average the odds are about right. Replaying the stock's past trend made them about 10 percentage points too rosy, so the trend is removed by default.
- Per-trade odds don't separate good trades from bad ones (the Brier score is no better than always guessing the average). Use them as typical odds for this kind of trade, not as a forecast for one trade.

## Known limits

- **Survivorship bias:** the data covers only companies listed today. Delisted and merged names are missing, which flatters every result.
- Prices are adjusted from the reported % change and the base-price reset. Unusual corporate actions can slip through this.
- There is no slippage beyond gap fills, and no queue position at the price limit.
- The earlier daily price limit (10%, before 20 Apr 2026) is in the history. The simulator caps price moves at today's 15%.
- Fees and CGT are as of 21 Nov 2026 and have changed twice this year. Check them in config.json.
