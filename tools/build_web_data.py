#!/usr/bin/env python3
"""Build the static JSON the web app reads (web/data/).

Run after nepse-update. The GitHub Action runs it every trading day.

  python tools/build_web_data.py [--out web/data] [--bars 300]
"""

import argparse
import contextlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in ("lib", "nepse-scanner", "nepse-backtest"):
    sys.path.insert(0, os.path.join(ROOT, p))
import nepse_common as nc  # noqa: E402
import scan  # noqa: E402
import backtest  # noqa: E402

# measured by nepse-backtest/calibrate.py (1,500 signals) - see docs/ACCURACY.md
CALIBRATION = {"p_profit_pred": 37.9, "p_profit_actual": 36.6,
               "p_target_pred": 25.1, "p_target_actual": 31.1,
               "note": "Average odds are about right; per-trade odds do not "
                       "rank good trades above bad ones."}


def r2(x):
    return None if x is None else round(x, 2)


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "web", "data"))
    ap.add_argument("--bars", type=int, default=300)
    ap.add_argument("--skip-backtest", action="store_true")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    os.makedirs(os.path.join(a.out, "stocks"), exist_ok=True)
    sectors = nc.load_sectors(cfg)
    syms = nc.universe(cfg)
    if not syms:
        sys.exit(f"No data in {cfg['data_dir']}; run nepse-update first.")

    with contextlib.redirect_stdout(io.StringIO()):
        hits = scan.main(["--json", os.devnull])
    hit_map = {}
    for h in hits:
        hit_map.setdefault(h["symbol"], []).append(h["setup"])

    uni, as_of = [], ""
    for sym in syms:
        bars, events = nc.load_bars(sym, cfg)
        if len(bars) < 30:
            continue
        ind = nc.compute_indicators(bars)
        i = len(bars) - 1
        as_of = max(as_of, bars[i]["date"])
        tail = bars[-a.bars:]
        k0 = len(bars) - len(tail)
        records = {s: scan.own_record(bars, ind, s, cfg, len(bars)) for s in nc.SETUPS} \
            if len(bars) >= 270 else {}
        dump(os.path.join(a.out, "stocks", sym + ".json"), {
            "symbol": sym, "sector": sectors.get(sym, ""),
            "d": [b["date"] for b in tail],
            "o": [r2(b["open"]) for b in tail], "h": [r2(b["high"]) for b in tail],
            "l": [r2(b["low"]) for b in tail], "c": [r2(b["close"]) for b in tail],
            "v": [round(b["volume"]) for b in tail], "t": [round(b["turnover"]) for b in tail],
            "atr": [r2(x) for x in ind["atr14"][k0:]],
            "sma20": [r2(x) for x in ind["sma20"][k0:]],
            "sma50": [r2(x) for x in ind["sma50"][k0:]],
            "sma200": [r2(x) for x in ind["sma200"][k0:]],
            "records": records,
            "adjustments": events[-6:]})
        c = bars[i]["close"]
        uni.append({"s": sym, "sec": sectors.get(sym, ""), "d": bars[i]["date"],
                    "c": r2(c), "chg": r2(100 * (c / bars[i - 1]["close"] - 1)),
                    "t20": round(ind["turn20"][i] or 0),
                    "atrp": r2(100 * ind["atr14"][i] / c) if ind["atr14"][i] else None,
                    "rsi14": r2(ind["rsi14"][i]),
                    "a50": None if ind["sma50"][i] is None else c > ind["sma50"][i],
                    "a200": None if ind["sma200"][i] is None else c > ind["sma200"][i],
                    "h52p": r2(100 * (c / ind["hh250"][i] - 1)) if ind["hh250"][i] else None,
                    "liq": nc.liquid(ind, i, cfg), "hits": hit_map.get(sym, [])})
    dump(os.path.join(a.out, "universe.json"), uni)
    dump(os.path.join(a.out, "scan.json"), {"as_of": as_of, "hits": hits})

    if not a.skip_backtest:
        with contextlib.redirect_stdout(io.StringIO()):
            rep = backtest.main(["--json", os.devnull])
        dump(os.path.join(a.out, "backtest.json"), rep)

    idx = nc.load_index(cfg)[-a.bars:]
    setups = {k: {kk: vv for kk, vv in v.items() if kk != "fn"} for k, v in nc.SETUPS.items()}
    dump(os.path.join(a.out, "meta.json"), {
        "as_of": as_of, "generated": nc.now_npt(), "symbols": len(uni),
        "hits": len(hits), "setups": setups, "record": nc.BACKTEST_RECORD,
        "calibration": CALIBRATION,
        "config": {k: v for k, v in cfg.items()
                   if k not in ("data_dir", "index_csv", "sectors_csv")},
        "sectors": sorted(set(sectors.values())),
        "index": {"d": [b["date"] for b in idx], "c": [r2(b["close"]) for b in idx]},
        "disclaimer": nc.DISCLAIMER})
    print(f"Built web data: {len(uni)} stocks, {len(hits)} hits, as of {as_of} -> {a.out}")


if __name__ == "__main__":
    main()
