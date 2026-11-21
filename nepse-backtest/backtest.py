#!/usr/bin/env python3
"""nepse-backtest: how accurate has each setup actually been?

Runs every setup over every liquid NEPSE equity, one trade at a time per
stock, with T+2 selling, gap fills, locked-limit skips, real fee slabs and
CGT. Reports win rate, average and median net return, profit factor and
expectancy, split into an earlier and a later period, and compares each
setup with random entries on the same stocks and dates range under the same
exit rules (the honest yardstick: does the signal beat a coin flip?).

  python backtest.py                         # all setups, default periods
  python backtest.py --setups breakout20 --regime
  python backtest.py --split 2023-01-01 --start 2016-01-01 --json out.json
"""

import argparse
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402


def run_symbol(sym, cfg, setups, start, end, regime, rng, notional, random_mult):
    bars, _ = nc.load_bars(sym, cfg)
    if len(bars) < 300:
        return {}
    ind = nc.compute_indicators(bars)
    out = {s: {"sig": [], "rnd": []} for s in setups}
    for s in setups:
        sp = nc.SETUPS[s]
        busy_until = -1
        eligible = []
        for i in range(260, len(bars) - 1):
            d = bars[i]["date"]
            if d < start or d > end:
                continue
            if not nc.liquid(ind, i, cfg):
                continue
            if ind["atr14"][i] is None:
                continue
            if regime and not nc.regime_ok(regime[0], d, regime[1]):
                continue
            eligible.append(i)
            if i <= busy_until:
                continue
            if not sp["fn"](bars, ind, i):
                continue
            if nc.locked_upper(bars, i + 1, cfg):
                continue
            t = nc.simulate_trade(bars, ind, i + 1, s, cfg)
            if not t or t.get("open"):
                continue
            t["net_pct"] = nc.net_return_pct(t, cfg, notional)
            t["symbol"] = sym
            out[s]["sig"].append(t)
            busy_until = t["exit_i"]
        # random baseline: same stock, same liquid days, same exits
        k = len(out[s]["sig"]) * random_mult
        if eligible and k:
            for i in rng.sample(eligible, min(k, len(eligible))):
                if nc.locked_upper(bars, i + 1, cfg):
                    continue
                t = nc.simulate_trade(bars, ind, i + 1, s, cfg)
                if not t or t.get("open"):
                    continue
                t["net_pct"] = nc.net_return_pct(t, cfg, notional)
                out[s]["rnd"].append(t)
    return out


def stats(trades):
    if not trades:
        return {"trades": 0}
    r = [t["net_pct"] for t in trades]
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x <= 0]
    pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    return {"trades": len(r),
            "win_rate_pct": round(100 * len(wins) / len(r), 1),
            "avg_net_pct": round(statistics.mean(r), 2),
            "median_net_pct": round(statistics.median(r), 2),
            "avg_win_pct": round(statistics.mean(wins), 2) if wins else 0,
            "avg_loss_pct": round(statistics.mean(losses), 2) if losses else 0,
            "profit_factor": round(pf, 2) if pf else None,
            "avg_sessions": round(statistics.mean(t["sessions"] for t in trades), 1),
            "exit_reasons": reasons,
            # standard error, to judge whether avg_net_pct differs from 0
            "se_pct": round(statistics.stdev(r) / len(r) ** 0.5, 2) if len(r) > 1 else None}


def by_year(trades):
    yrs = {}
    for t in trades:
        yrs.setdefault(t["entry_date"][:4], []).append(t["net_pct"])
    return {y: {"n": len(v), "avg": round(statistics.mean(v), 2),
                "win": round(100 * sum(1 for x in v if x > 0) / len(v), 1)}
            for y, v in sorted(yrs.items())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--setups", default=",".join(nc.SETUPS))
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2099-12-31")
    ap.add_argument("--split", default="2023-01-01",
                    help="first date of the later (out-of-sample) period")
    ap.add_argument("--regime", action="store_true",
                    help="only take signals when NEPSE index > its 50-day avg")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--notional", type=float, default=100000)
    ap.add_argument("--random-mult", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", default="")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)

    cfg = nc.load_config(a.config)
    setups = [s.strip() for s in a.setups.split(",") if s.strip()]
    for s in setups:
        if s not in nc.SETUPS:
            sys.exit(f"Unknown setup {s}. Choose from {', '.join(nc.SETUPS)}")
    syms = ([s.strip().upper() for s in a.symbols.split(",") if s.strip()]
            or nc.universe(cfg))
    if not syms:
        sys.exit("No price data found. Run nepse-update first "
                 f"(looked in {cfg['data_dir']}).")
    regime = nc.index_regime(cfg) if a.regime else None
    if a.regime and not regime[0]:
        sys.exit(f"--regime needs the NEPSE index file at {cfg['index_csv']}")
    rng = random.Random(a.seed)

    allt = {s: {"sig": [], "rnd": []} for s in setups}
    last_date = ""
    for sym in syms:
        try:
            r = run_symbol(sym, cfg, setups, a.start, a.end, regime, rng,
                           a.notional, a.random_mult)
        except FileNotFoundError:
            continue
        for s, v in r.items():
            allt[s]["sig"] += v["sig"]
            allt[s]["rnd"] += v["rnd"]
            for t in v["sig"]:
                last_date = max(last_date, t["exit_date"])

    report = {"generated": nc.now_npt(), "symbols": len(syms),
              "period": [a.start, a.end], "split": a.split,
              "regime_filter": a.regime, "notional_npr": a.notional,
              "costs": "commission slabs + SEBON + DP both sides + CGT",
              "last_trade_exit": last_date, "setups": {}}
    print(f"NEPSE setup backtest | {len(syms)} equities | {a.start} to "
          f"{last_date or a.end} | split {a.split}"
          f"{' | regime filter ON' if a.regime else ''}")
    print(f"Net of fees and CGT on a Rs {a.notional:,.0f} position. "
          "Random = same stocks, random liquid days, same exits.\n")
    hdr = (f"{'setup':<15}{'period':<8}{'trades':>7}{'win%':>7}{'avg%':>7}"
           f"{'med%':>7}{'PF':>6}  {'random avg%':>11}{'edge pp':>9}")
    print(hdr)
    print("-" * len(hdr))
    for s in setups:
        sig, rnd = allt[s]["sig"], allt[s]["rnd"]
        parts = {"all": (sig, rnd),
                 "early": ([t for t in sig if t["entry_date"] < a.split],
                           [t for t in rnd if t["entry_date"] < a.split]),
                 "late": ([t for t in sig if t["entry_date"] >= a.split],
                          [t for t in rnd if t["entry_date"] >= a.split])}
        rep = {}
        for name, (ts, rs) in parts.items():
            st, rst = stats(ts), stats(rs)
            edge = (round(st["avg_net_pct"] - rst["avg_net_pct"], 2)
                    if st["trades"] and rst["trades"] else None)
            rep[name] = {"signal": st, "random": rst, "edge_pp": edge}
            if st["trades"]:
                print(f"{s:<15}{name:<8}{st['trades']:>7}{st['win_rate_pct']:>7}"
                      f"{st['avg_net_pct']:>7}{st['median_net_pct']:>7}"
                      f"{(st['profit_factor'] or 0):>6}  "
                      f"{rst.get('avg_net_pct', 0):>11}{(edge if edge is not None else 0):>9}")
            else:
                print(f"{s:<15}{name:<8}{0:>7}")
        rep["by_year"] = by_year(sig)
        rep["about"] = nc.SETUPS[s]["about"]
        report["setups"][s] = rep
        print()
    print("Read: edge pp = setup avg net % minus random-entry avg net %. "
          "Treat an edge smaller than ~2x its standard error, or one that "
          "flips sign between early and late, as no edge.")
    print("Caveats: today's listed companies only (delisted/merged names "
          "missing), adjusted prices, no slippage beyond gap fills.")
    print(nc.DISCLAIMER)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved {a.json}")
    return report


if __name__ == "__main__":
    main()
