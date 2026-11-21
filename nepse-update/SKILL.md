---
name: nepse-update
description: Download or refresh free NEPSE end-of-day prices (about 276 listed equities, adjusted for bonus and rights) and the NEPSE index. Use before any NEPSE scan, plan or backtest, or when data is reported STALE.
---

# NEPSE data update

Run `python nepse-update/update.py` from the repo root. The first run clones two public GitHub datasets into `~/.nepse-trader/` (about 70 MB, sparse): Aabishkar2/nepse-data (per-company daily OHLCV) and zeutonx/NEPSE-Data (index files only). Later runs pull the latest data.

`python nepse-update/update.py --status` shows the date of the latest bar. Data more than 4 days old is labelled STALE, and the risk gate blocks trades on stale data.

Tell the user:
- the date of the latest bar and how many equities are available
- that these datasets are run by third parties: no data means no trade, and a key price should be checked against NEPSE or ShareSansar before ordering
