# NEPSE Trader Skills

Eight Claude skills for **swing trading on the Nepal Stock Exchange**. They use daily end-of-day data, rupee sizing with the real fee slabs and CGT, a hard PASS/BLOCK risk gate and a ticket you type into TMS yourself. A backtest reports how each setup has actually performed.

This project is separate from Nepse-Screener: it shares no code and changes nothing there. The skill layout follows [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill), which is MIT-licensed and built for the US market. Everything here is written from scratch for NEPSE.

> **Read [docs/ACCURACY.md](docs/ACCURACY.md) first.** On 2016–2026 data, after costs, three of the four setups lost money. Only `high52` (a new 52-week high) had a positive average, and in 2023–26 it was within one standard error of zero. This is a tool for testing ideas and enforcing discipline, not a money machine.

## The eight skills

| Skill | What it does |
|---|---|
| `nepse-update` | Downloads or refreshes free EOD data: about 276 equities plus the NEPSE index, from public GitHub datasets |
| `nepse-scanner` | Finds setups on the last close, each shown with that stock's own track record |
| `nepse-exit` | Sets the stop, target and time stop. Warns about T+2 and the 15% daily price limit. Writes `plan.json` |
| `nepse-budget` | Sizes in lots of 10 under three caps (risk, position, cash), with commission, SEBON fee, DP charge and CGT |
| `nepse-risk` | PASS/BLOCK gate: stale data, thin turnover, chasing the upper limit, lower-limit lock, net reward:risk, sector cap |
| `nepse-ticket` | Plain TMS ticket for manual entry. Refuses to write one when the gate blocks |
| `nepse-timemachine` | Replays the plan 10,000 times from the stock's own bars (trend removed) and checks the stock's past signals |
| `nepse-backtest` | Accuracy of every setup against random entries, early vs late period, plus a calibration check of the time machine |

## NEPSE rules built in (verified 21 Nov 2026)

- **Commission** by slab, applied to the whole trade value:

  | Trade value | Rate |
  |---|---|
  | Up to Rs 50,000 | 0.36% (minimum Rs 10) |
  | Up to Rs 5 lakh | 0.33% |
  | Up to Rs 20 lakh | 0.31% |
  | Up to Rs 1 crore | 0.27% |
  | Above Rs 1 crore | 0.24% |

- **Other charges:** SEBON fee 0.015%, and a DP charge of Rs 25 per scrip per day on each side.
- **CGT** for resident individuals since 22 Sep 2026: 5% if held 365 days or less, 3.75% if held longer.
- **Daily price limit:** ±15% per stock since 20 Apr 2026 (it was 10% before).
- **Lots:** regular-session orders must be in multiples of 10 units.
- **Settlement:** T+2, so no sale for 2 sessions after buying.
- **Trading hours:** Sunday to Thursday.

All rates live in `config.json`. They changed twice in 2026, so check them again before relying on any rupee figure.

## Setup

Requires Python 3.8+ and git. There is nothing to install with pip.

```bash
git clone <this repo> nepse-trader-skills && cd nepse-trader-skills
cp config.example.json config.json        # set your budget and limits
python nepse-update/update.py             # ~70 MB, first run only
python -m unittest discover tests         # 30 tests should pass
```

**In Claude Code**, either add the plugin:

```
/plugin marketplace add <path-or-repo>
/plugin install nepse-trader-skills@nepse-trader-skills
```

or copy the `nepse-*` folders together with `lib/` and `data/` into `.claude/skills/`. The scripts expect `lib/` and `data/` to sit next to them.

## Typical flow

```bash
python nepse-scanner/scan.py --setups high52
python nepse-exit/exit.py SHINE --setup high52
python nepse-budget/size.py --portfolio portfolio.json --out plan.json
python nepse-timemachine/timemachine.py
python nepse-risk/check.py --portfolio portfolio.json
python nepse-ticket/ticket.py --portfolio portfolio.json
```

To check accuracy yourself at any time:

```bash
python nepse-backtest/backtest.py --json results.json
python nepse-backtest/calibrate.py
```

## Data sources

The price data comes from two third-party datasets, both public on GitHub:

- [Aabishkar2/nepse-data](https://github.com/Aabishkar2/nepse-data): per-company daily OHLCV
- [zeutonx/NEPSE-Data](https://github.com/zeutonx/NEPSE-Data): the NEPSE index and the sector list in `data/sectors.csv`

Prices are back-adjusted for bonus and rights issues using the base-price reset that NEPSE reports. Always confirm a price against NEPSE or ShareSansar before you place an order.

## Safety

Nothing in this pack can place an order. Every output is labelled LIVE-EOD, STALE or REPLAY. The results describe the past and are not financial advice.
