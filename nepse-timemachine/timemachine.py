#!/usr/bin/env python3
"""nepse-timemachine: replay a plan thousands of times before risking money.

Two views, both on the stock's own adjusted history:
  1. Bootstrap: 10,000 future paths built from randomly drawn real daily
     bars of this stock (open/high/low/close relative to prior close, last
     N sessions), each capped at the daily price limit. The plan's stop,
     target, time stop and T+2 rule are applied to every path.
  2. History: every past day this stock fired the same setup, run with the
     same exits.

  python timemachine.py                      # reads plan.json
  python timemachine.py --plan plan.json --paths 10000 --lookback 250
"""

import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402


def bootstrap(bars, plan, cfg, paths=10000, lookback=250, seed=11, demean=True):
    lim = cfg.get("price_limit_pct", nc.PRICE_LIMIT_PCT) / 100
    hist = bars[-lookback - 1:]
    rel = []
    for a, b in zip(hist, hist[1:]):
        pc = a["close"]
        rel.append((b["open"] / pc, b["high"] / pc, b["low"] / pc, b["close"] / pc))
    if len(rel) < 60:
        raise ValueError("Need at least 60 sessions of history")
    if demean:
        # remove the stock's recent trend so a hot past year is not replayed
        # as a free future drift (calibration showed it made odds too rosy)
        import math
        m = math.exp(sum(math.log(r[3]) for r in rel) / len(rel))
        rel = [(o / m, h / m, l / m, c / m) for o, h, l, c in rel]
    rng = random.Random(seed)
    e, stop, tgt = plan["entry"], plan["stop"], plan.get("target")
    n_max, first = plan["max_sessions"], cfg["earliest_sell_session"]
    use_sma5 = plan.get("exit_rule") == "close_above_sma5"
    seed_closes = [b["close"] for b in bars[-4:]]
    res = {"target": 0, "stop": 0, "time": 0, "signal": 0}
    rets = []
    for _ in range(paths):
        pc = e
        closes = list(seed_closes)
        out = None
        for j in range(n_max + 1):
            o, h, l, c = rng.choice(rel)
            cap = lambda x: min(max(x, 1 - lim), 1 + lim)  # noqa: E731
            if j == 0:                       # entry bar: we bought at the open
                o, h, l, c = 1.0, cap(h / o), cap(l / o), cap(c / o)
            o, h, l, c = pc * cap(o), pc * cap(h), pc * cap(l), pc * cap(c)
            closes.append(c)
            if j >= first:
                if j == first and o <= stop:
                    out = ("stop", o); break
                if l <= stop:
                    out = ("stop", min(o, stop)); break
                if tgt and h >= tgt:
                    out = ("target", max(o, tgt)); break
                if use_sma5 and c > sum(closes[-5:]) / 5:
                    out = ("signal", c); break
            pc = c
        if out is None:
            out = ("time", pc)
        res[out[0]] += 1
        rets.append(out[1])
    shares = max(cfg["lot_size"], nc.round_lot(100000 / e, cfg["lot_size"]))
    nets = [nc.round_trip(shares, e, x, cfg, 15)["net_return_pct"] for x in rets]
    nets.sort()
    return {"paths": paths, "lookback_sessions": len(rel),
            "p_target": round(100 * res["target"] / paths, 1),
            "p_stop": round(100 * res["stop"] / paths, 1),
            "p_time": round(100 * res["time"] / paths, 1),
            "p_signal_exit": round(100 * res["signal"] / paths, 1),
            "p_profit_after_costs": round(100 * sum(1 for x in nets if x > 0) / paths, 1),
            "expected_net_pct": round(statistics.mean(nets), 2),
            "p5_net_pct": round(nets[int(0.05 * paths)], 2),
            "p95_net_pct": round(nets[int(0.95 * paths)], 2)}


def history(bars, plan, cfg):
    ind = nc.compute_indicators(bars)
    s = plan["setup"]
    trades, busy = [], -1
    for i in range(260, len(bars) - 1):
        if i <= busy or not nc.liquid(ind, i, cfg):
            continue
        if nc.SETUPS[s]["fn"](bars, ind, i):
            t = nc.simulate_trade(bars, ind, i + 1, s, cfg)
            if t and not t.get("open"):
                t["net_pct"] = nc.net_return_pct(t, cfg, 100000)
                trades.append(t)
                busy = t["exit_i"]
    if not trades:
        return {"n": 0}
    r = [t["net_pct"] for t in trades]
    return {"n": len(r), "win_pct": round(100 * sum(1 for x in r if x > 0) / len(r), 1),
            "avg_net_pct": round(statistics.mean(r), 2),
            "median_net_pct": round(statistics.median(r), 2),
            "last5": [(t["entry_date"], t["reason"], round(t["net_pct"], 1)) for t in trades[-5:]]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--paths", type=int, default=10000)
    ap.add_argument("--lookback", type=int, default=250)
    ap.add_argument("--keep-drift", action="store_true",
                    help="replay the stock's past trend too (over-optimistic in tests)")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    if not os.path.exists(a.plan):
        sys.exit(f"No {a.plan}. Run nepse-exit first.")
    plan = json.load(open(a.plan, encoding="utf-8"))
    bars, _ = nc.load_bars(plan["symbol"], cfg)
    b = bootstrap(bars, plan, cfg, a.paths, a.lookback, demean=not a.keep_drift)
    h = history(bars, plan, cfg)
    print(f"TIME MACHINE {plan['symbol']} | entry {plan['entry']} stop {plan['stop']} "
          f"target {plan.get('target') or 'SMA5 exit'} | {plan['max_sessions']} sessions, T+2")
    print(f"1) {b['paths']:,} paths from the last {b['lookback_sessions']} real sessions:")
    print(f"   target {b['p_target']}% | stop {b['p_stop']}% | time-out {b['p_time']}%"
          + (f" | SMA5 exit {b['p_signal_exit']}%" if b['p_signal_exit'] else ""))
    print(f"   profit after costs {b['p_profit_after_costs']}% of paths | expected "
          f"{b['expected_net_pct']:+}% net | 5th-95th pct {b['p5_net_pct']}% to {b['p95_net_pct']}%")
    if h["n"]:
        print(f"2) Past '{plan['setup']}' signals on {plan['symbol']}: {h['n']} trades, "
              f"{h['win_pct']}% won, avg {h['avg_net_pct']:+}% / median {h['median_net_pct']:+}% net")
        print("   last 5: " + "; ".join(f"{d} {r} {x:+}%" for d, r, x in h["last5"]))
    else:
        print(f"2) No past '{plan['setup']}' signals on {plan['symbol']} to compare.")
    print("Bootstrap draws days independently, so it misses momentum and "
          "streaks; treat it as odds for a typical stretch, not a forecast.")
    print(nc.DISCLAIMER)


if __name__ == "__main__":
    main()
