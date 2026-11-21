#!/usr/bin/env python3
"""nepse-risk: PASS or BLOCK before any order. Any single BLOCK stops it.

Checks: data freshness, liquidity, upper-limit chasing, lower-limit lock,
stop vs daily limit, reward:risk after costs, loss cap, position cap,
sector cap (with your holdings), duplicate holding, trading calendar.

  python check.py --plan plan.json --portfolio portfolio.json
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nepse-budget"))
import size as sizer  # noqa: E402


def gate(plan, cfg, portfolio=None, bars=None, today=None):
    sym = plan["symbol"]
    if bars is None:
        bars, _ = nc.load_bars(sym, cfg)
    ind = nc.compute_indicators(bars)
    i = len(bars) - 1
    sectors = nc.load_sectors(cfg)
    sector = sectors.get(sym, "Unknown")
    sz = plan.get("sizing") or sizer.size_plan(plan, cfg, portfolio)
    block, warn, ok = [], [], []
    lim = cfg.get("price_limit_pct", nc.PRICE_LIMIT_PCT)

    age = nc.data_age_days(bars, today)
    (block if age > 4 else ok).append(f"Data {age} days old (last bar {bars[i]['date']})")

    t20 = ind["turn20"][i] or 0
    pos_val = sz.get("shares", 0) * plan["entry"]
    if t20 < cfg["min_avg_turnover_npr"]:
        block.append(f"Thin: 20-day avg turnover {nc.fmt_npr(t20)} < "
                     f"{nc.fmt_npr(cfg['min_avg_turnover_npr'])}")
    elif pos_val > t20 * cfg["max_pct_of_turnover"] / 100:
        block.append(f"Position {nc.fmt_npr(pos_val)} is over {cfg['max_pct_of_turnover']}% "
                     f"of daily turnover {nc.fmt_npr(t20)}; hard to exit")
    else:
        ok.append(f"Liquidity fine: avg turnover {nc.fmt_npr(t20)}/day")

    chg = 100 * (bars[i]["close"] / bars[i - 1]["close"] - 1)
    if chg >= lim - 1.5:
        block.append(f"Up {chg:.1f}% today, at/near the +{lim:.0f}% limit: chasing a "
                     "limit-up stock; tomorrow's open is unknowable")
    elif chg <= -(lim - 1.5):
        block.append(f"Down {chg:.1f}% today, near the lower limit: possible lock, "
                     "no buyers to exit into")
    else:
        ok.append(f"Day change {chg:+.1f}% (limit +/-{lim:.0f}%)")

    if plan["risk_pct"] > lim:
        warn.append(f"Stop {plan['risk_pct']}% away is beyond one day's {lim:.0f}% limit")

    if sz.get("shares", 0) <= 0:
        block.append("Sizing gives 0 shares: " + sz.get("reason", ""))
    else:
        if -sz["loss_at_stop"] > cfg["max_loss_per_trade_npr"] + 1:
            block.append(f"Loss at stop {nc.fmt_npr(-sz['loss_at_stop'])} > cap "
                         f"{nc.fmt_npr(cfg['max_loss_per_trade_npr'])}")
        else:
            ok.append(f"Loss at stop {nc.fmt_npr(-sz['loss_at_stop'])} within cap")
        rr = sz.get("net_reward_risk")
        if rr is not None:
            (block if rr < cfg["min_reward_risk"] else ok).append(
                f"Net reward:risk {rr} (min {cfg['min_reward_risk']}) after fees & CGT")
        else:
            warn.append("No fixed target (mean-reversion exit): reward:risk not checkable")
        if sz["position_pct"] > cfg["max_position_pct"] + 0.01:
            block.append(f"Position {sz['position_pct']}% > {cfg['max_position_pct']}% cap")

    holds = (portfolio or {}).get("holdings", [])
    sec_val = sum(h["qty"] * h.get("last_price", h["avg_cost"]) for h in holds
                  if sectors.get(h["symbol"].upper()) == sector) + pos_val
    sec_pct = 100 * sec_val / cfg["budget_npr"]
    (block if sec_pct > cfg["max_sector_pct"] else ok).append(
        f"{sector} exposure would be {sec_pct:.1f}% (cap {cfg['max_sector_pct']}%)")
    if any(h["symbol"].upper() == sym for h in holds):
        warn.append(f"You already hold {sym}: this adds to it")

    rec = nc.BACKTEST_RECORD.get(plan.get("setup"))
    if rec and rec["avg_net_pct"] <= 0:
        warn.append(f"Setup '{plan['setup']}' averaged {rec['avg_net_pct']:+}% net per trade "
                    "across NEPSE in the 2016-26 backtest: it has lost money after costs")

    now = dt.datetime.now(nc.NPT) if today is None else None
    if now and now.weekday() in (4, 5):   # Fri, Sat
        warn.append("NEPSE is closed Friday and Saturday: order goes in Sunday 11:00")
    warn.append("Check for an upcoming book closure / AGM: the price resets after it")

    return {"symbol": sym, "verdict": "BLOCK" if block else "PASS",
            "block": block, "warn": warn, "ok": ok, "sizing": sz}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--portfolio", default="")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    if not os.path.exists(a.plan):
        sys.exit(f"No {a.plan}. Run nepse-exit (and nepse-budget) first.")
    plan = json.load(open(a.plan, encoding="utf-8"))
    pf = json.load(open(a.portfolio, encoding="utf-8")) if a.portfolio else None
    r = gate(plan, cfg, pf)
    print(f"RISK GATE {r['symbol']}: {r['verdict']}")
    for x in r["block"]:
        print("  BLOCK " + x)
    for x in r["warn"]:
        print("  warn  " + x)
    for x in r["ok"]:
        print("  ok    " + x)
    print(nc.DISCLAIMER)
    sys.exit(0 if r["verdict"] == "PASS" else 2)


if __name__ == "__main__":
    main()
