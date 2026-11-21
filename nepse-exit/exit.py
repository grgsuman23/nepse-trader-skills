#!/usr/bin/env python3
"""nepse-exit: set the stop and the target BEFORE buying, and save a plan.

  python exit.py NABIL                         # setup defaults (ATR stop, 2R)
  python exit.py NABIL --setup high52 --entry 555
  python exit.py NABIL --stop pct:6 --target r:2.5
  python exit.py NABIL --stop price:520 --target price:610
  python exit.py NABIL --stop swing            # below the 10-session low

Writes plan.json (or --out) for nepse-budget, nepse-risk, nepse-ticket and
nepse-timemachine.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402


def plan_exit(sym, cfg, setup="breakout20", entry=None, stop_spec="atr",
              target_spec=None, bars=None):
    if bars is None:
        bars, _ = nc.load_bars(sym, cfg)
    ind = nc.compute_indicators(bars)
    i = len(bars) - 1
    sp = nc.SETUPS[setup]
    e = float(entry) if entry else bars[i]["close"]
    atr = ind["atr14"][i]
    if stop_spec == "atr":
        stop, how = e - sp["stop_atr"] * atr, f"{sp['stop_atr']} x ATR(14) {atr:.2f}"
    elif stop_spec == "swing":
        lo = min(b["low"] for b in bars[-10:])
        stop, how = lo * 0.995, f"0.5% under 10-session low {lo:.2f}"
    elif stop_spec.startswith("pct:"):
        p = float(stop_spec[4:])
        stop, how = e * (1 - p / 100), f"{p}% below entry"
    elif stop_spec.startswith("price:"):
        stop, how = float(stop_spec[6:]), "fixed price"
    else:
        raise ValueError("stop must be atr, swing, pct:N or price:N")
    risk = e - stop
    if risk <= 0:
        raise ValueError(f"Stop {stop:.2f} is not below entry {e:.2f}")
    tspec = target_spec or (f"r:{sp['target_r']}" if sp["target_r"] else None)
    if tspec is None:
        target, thow = None, "exit on close above 5-day average (mean reversion)"
    elif tspec.startswith("r:"):
        r = float(tspec[2:])
        target, thow = e + r * risk, f"{r}R"
    elif tspec.startswith("price:"):
        target, thow = float(tspec[6:]), "fixed price"
    else:
        raise ValueError("target must be r:N or price:N")

    lim = cfg.get("price_limit_pct", nc.PRICE_LIMIT_PCT)
    risk_pct = 100 * risk / e
    warns = []
    if risk_pct > lim:
        warns.append(f"Stop is {risk_pct:.1f}% away, wider than the {lim:.0f}% daily "
                     "price limit: it can take 2+ sessions to reach, and a stock "
                     "locked at the lower limit cannot be sold at all.")
    if risk_pct < 1.0:
        warns.append("Stop is under 1% away - normal daily noise will hit it.")
    if atr and risk < 0.75 * atr:
        warns.append(f"Stop is inside 0.75 x ATR ({atr:.2f}); expect it to be hit by noise.")
    warns.append(f"T+2: you cannot sell for {cfg['earliest_sell_session']} sessions after "
                 "buying. If the stock falls through the stop before then, the real exit "
                 "is the open of the first session you can sell.")
    if target and target > e * (1 + lim / 100) ** 2:
        warns.append("Target is more than two full limit-up days away.")
    shares = 100
    be = nc.break_even_price(shares, e, cfg)
    return {"symbol": sym.upper(), "setup": setup, "as_of": bars[i]["date"],
            "last_close": round(bars[i]["close"], 2), "entry": round(e, 2),
            "stop": round(stop, 2), "stop_rule": how,
            "target": round(target, 2) if target else None, "target_rule": thow,
            "exit_rule": sp["exit"] if not target_spec else "bracket",
            "max_sessions": sp["max_sessions"], "risk_per_share": round(risk, 2),
            "risk_pct": round(risk_pct, 2),
            "reward_risk": round((target - e) / risk, 2) if target else None,
            "break_even": be, "atr14": round(atr, 2), "warnings": warns}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--setup", default="breakout20", choices=list(nc.SETUPS))
    ap.add_argument("--entry", type=float)
    ap.add_argument("--stop", default="atr")
    ap.add_argument("--target", default=None)
    ap.add_argument("--out", default="plan.json")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    try:
        p = plan_exit(a.symbol, cfg, a.setup, a.entry, a.stop, a.target)
    except (ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
    print(f"EXIT PLAN {p['symbol']} ({p['setup']}) | data to {p['as_of']} close {p['last_close']}")
    print(f"  Entry      {p['entry']:>10}")
    print(f"  Stop       {p['stop']:>10}   -{p['risk_pct']}%  ({p['stop_rule']})")
    print(f"  Target     {str(p['target'] or '-'):>10}   ({p['target_rule']})")
    print(f"  Time stop  {p['max_sessions']} sessions | reward:risk {p['reward_risk'] or 'n/a'}")
    print(f"  Break-even {p['break_even']:>10}   (fees both sides, before CGT)")
    for w in p["warnings"]:
        print("  ! " + w)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)
    print(f"Saved {a.out}. Next: nepse-budget to size it.")
    print(nc.DISCLAIMER)


if __name__ == "__main__":
    main()
