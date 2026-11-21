#!/usr/bin/env python3
"""nepse-scanner: which liquid NEPSE equities fired a setup on the last close?

Each hit shows the setup, the stock's own backtested record for that setup
(so a hit is never shown without its track record), the proposed entry
(next session's open, so: limit near last close), ATR stop and target.

  python scan.py                          # all setups, all liquid equities
  python scan.py --setups high52 --sector "Hydro Power"
  python scan.py --symbols NABIL,NICA --date 2024-08-14   # replay a past day
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402


def own_record(bars, ind, setup, cfg, upto):
    """Past trades of this setup on this stock that closed before `upto`."""
    res, busy = [], -1
    for i in range(260, upto - 1):
        if i <= busy or not nc.liquid(ind, i, cfg):
            continue
        if nc.SETUPS[setup]["fn"](bars, ind, i):
            t = nc.simulate_trade(bars, ind, i + 1, setup, cfg)
            if t and not t.get("open") and t["exit_i"] < upto:
                res.append(nc.net_return_pct(t, cfg, 100000))
                busy = t["exit_i"]
    if not res:
        return {"n": 0}
    return {"n": len(res), "win_pct": round(100 * sum(1 for x in res if x > 0) / len(res)),
            "avg_net_pct": round(sum(res) / len(res), 2)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--setups", default=",".join(nc.SETUPS))
    ap.add_argument("--symbols", default="")
    ap.add_argument("--sector", default="")
    ap.add_argument("--date", default="", help="scan as of this date (YYYY-MM-DD)")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    sectors = nc.load_sectors(cfg)
    setups = [s for s in a.setups.split(",") if s]
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or nc.universe(cfg)
    if a.sector:
        syms = [s for s in syms if sectors.get(s, "").lower() == a.sector.lower()]
    if not syms:
        sys.exit("No symbols to scan. Run nepse-update, or check --sector spelling.")

    hits, latest = [], ""
    for sym in syms:
        try:
            bars, _ = nc.load_bars(sym, cfg)
        except FileNotFoundError:
            continue
        if a.date:
            bars = [b for b in bars if b["date"] <= a.date]
        if len(bars) < 270:
            continue
        ind = nc.compute_indicators(bars)
        i = len(bars) - 1
        latest = max(latest, bars[i]["date"])
        if not nc.liquid(ind, i, cfg):
            continue
        for s in setups:
            if not nc.SETUPS[s]["fn"](bars, ind, i):
                continue
            sp = nc.SETUPS[s]
            e = bars[i]["close"]
            atr = ind["atr14"][i]
            stop = e - sp["stop_atr"] * atr
            tgt = e + sp["target_r"] * (e - stop) if sp["target_r"] else None
            hits.append({"symbol": sym, "sector": sectors.get(sym, ""), "setup": s,
                         "date": bars[i]["date"], "close": round(e, 2),
                         "day_chg_pct": round(100 * (e / bars[i - 1]["close"] - 1), 2),
                         "turnover20_lakh": round(ind["turn20"][i] / 1e5, 1),
                         "atr_pct": round(100 * atr / e, 2),
                         "stop": round(stop, 2), "target": round(tgt, 2) if tgt else None,
                         "exit_rule": sp["exit"], "max_sessions": sp["max_sessions"],
                         "record": own_record(bars, ind, s, cfg, i)})

    age = nc.data_age_days([{"date": latest}]) if latest and not a.date else 0
    tag = "REPLAY" if a.date else ("LIVE-EOD" if age <= 4 else "STALE")
    print(f"[{tag}] NEPSE scan as of close {latest} | {len(syms)} symbols | {len(hits)} hits")
    if tag == "STALE":
        print(f"WARNING: data is {age} days old. Run nepse-update first.")
    print(f"{'symbol':<9}{'setup':<15}{'close':>9}{'chg%':>7}{'stop':>9}{'target':>9}"
          f"{'ATR%':>6}{'T/O lakh':>10}  own record")
    for h in sorted(hits, key=lambda x: (x["setup"], -x["turnover20_lakh"])):
        r = h["record"]
        rec = (f"{r['n']} past, {r['win_pct']}% won, avg {r['avg_net_pct']:+}% net"
               if r["n"] else "no past signals")
        print(f"{h['symbol']:<9}{h['setup']:<15}{h['close']:>9}{h['day_chg_pct']:>7}"
              f"{h['stop']:>9}{(h['target'] or '-'):>9}{h['atr_pct']:>6}"
              f"{h['turnover20_lakh']:>10}  {rec}")
    print("\nEntry is at the next session's open; T+2 means no sale for 2 sessions."
          " Size with nepse-budget, gate with nepse-risk before any order.")
    print("Market-wide record of each setup: run nepse-backtest. "
          "Most setups have NOT beaten random entries after costs.")
    print(nc.DISCLAIMER)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"as_of": latest, "tag": tag, "hits": hits}, f, indent=2)
    return hits


if __name__ == "__main__":
    main()
