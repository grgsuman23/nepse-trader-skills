#!/usr/bin/env python3
"""nepse-budget: how many shares, in whole lots of 10, after every charge.

Size is the smallest of: the risk cap (rupees lost at the stop, fees
included), the position cap (% of budget) and cash on hand (budget minus
holdings minus buffer). Shows commission slab, SEBON fee, DP charge and CGT
on both outcomes.

  python size.py                      # reads plan.json
  python size.py --plan plan.json --portfolio portfolio.json --budget 300000
  python size.py --fees 1000 450 560  # just the charges: shares buy sell
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402


def invested(portfolio):
    return sum(h["qty"] * h.get("last_price", h["avg_cost"])
               for h in (portfolio or {}).get("holdings", []))


def size_plan(plan, cfg, portfolio=None, budget=None):
    budget = float(budget or cfg["budget_npr"])
    lot = cfg["lot_size"]
    e, stop, tgt = plan["entry"], plan["stop"], plan.get("target")
    cash = budget * (1 - cfg["cash_buffer_pct"] / 100) - invested(portfolio)
    pos_cap = budget * cfg["max_position_pct"] / 100

    def loss_at_stop(n):
        return -nc.round_trip(n, e, stop, cfg, 10)["net_pnl"]

    # largest lot count whose stop-out loss (with fees) fits the risk cap
    n = nc.round_lot(cfg["max_loss_per_trade_npr"] / (e - stop), lot)
    while n > 0 and loss_at_stop(n) > cfg["max_loss_per_trade_npr"]:
        n -= lot
    caps = {"risk": n,
            "position": nc.round_lot(pos_cap / (e * 1.004), lot),
            "cash": nc.round_lot(max(cash, 0) / (e * 1.004), lot)}
    shares = max(0, min(caps.values()))
    binding = min(caps, key=caps.get)
    out = {"symbol": plan["symbol"], "shares": shares, "binding_cap": binding,
           "caps": caps, "budget": budget, "cash_available": round(cash, 2)}
    if shares == 0:
        out["reason"] = (f"Even {lot} shares breaks the {binding} cap.")
        return out
    buy = nc.side_costs(shares * e, cfg["fees"], "buy")
    st = nc.round_trip(shares, e, stop, cfg, 10)
    out.update({"cost_with_fees": round(buy["value"] + buy["total"], 2),
                "buy_charges": buy, "position_pct": round(100 * shares * e / budget, 1),
                "loss_at_stop": st["net_pnl"], "loss_at_stop_pct": st["net_return_pct"],
                "break_even": nc.break_even_price(shares, e, cfg)})
    if tgt:
        tg = nc.round_trip(shares, e, tgt, cfg, 30)
        out.update({"gain_at_target": tg["net_pnl"], "gain_at_target_pct": tg["net_return_pct"],
                    "cgt_at_target": tg["cgt"],
                    "net_reward_risk": round(tg["net_pnl"] / -st["net_pnl"], 2)
                    if st["net_pnl"] < 0 else None})
    return out


def print_fees(shares, b, s, cfg):
    rt = nc.round_trip(shares, b, s, cfg, 30)
    for side in ("buy", "sell"):
        x = rt[side]
        print(f"{side.upper():<5} value {nc.fmt_npr(x['value'])}: commission "
              f"{x['commission_rate_pct']}% {nc.fmt_npr(x['commission'])}, SEBON "
              f"{nc.fmt_npr(x['sebon'])}, DP {nc.fmt_npr(x['dp'])} = {nc.fmt_npr(x['total'])}")
    print(f"CGT {rt['cgt_rate_pct']}%: {nc.fmt_npr(rt['cgt'])} | net P&L "
          f"{nc.fmt_npr(rt['net_pnl'])} ({rt['net_return_pct']:+.2f}%) | "
          f"break-even {nc.break_even_price(shares, b, cfg)}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--portfolio", default="")
    ap.add_argument("--budget", type=float)
    ap.add_argument("--fees", nargs=3, type=float, metavar=("SHARES", "BUY", "SELL"))
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    if a.fees:
        print_fees(int(a.fees[0]), a.fees[1], a.fees[2], cfg)
        print("[VERIFY] Rates as of 21 Nov 2026; edit config.json if SEBON/IRD change them.")
        return
    if not os.path.exists(a.plan):
        sys.exit(f"No {a.plan}. Run nepse-exit first.")
    plan = json.load(open(a.plan, encoding="utf-8"))
    pf = json.load(open(a.portfolio, encoding="utf-8")) if a.portfolio else None
    r = size_plan(plan, cfg, pf, a.budget)
    print(f"SIZE {r['symbol']} @ {plan['entry']} stop {plan['stop']} | budget "
          f"{nc.fmt_npr(r['budget'])}, cash free {nc.fmt_npr(r['cash_available'])}")
    print(f"  caps (shares): risk {r['caps']['risk']}, position {r['caps']['position']}, "
          f"cash {r['caps']['cash']} -> binding: {r['binding_cap']}")
    if not r["shares"]:
        print("  NO TRADE: " + r["reason"])
    else:
        b = r["buy_charges"]
        print(f"  BUY {r['shares']} shares (multiple of {cfg['lot_size']}) = "
              f"{nc.fmt_npr(r['cost_with_fees'])} incl. commission {b['commission_rate_pct']}% "
              f"{nc.fmt_npr(b['commission'])}, SEBON {nc.fmt_npr(b['sebon'])}, DP {nc.fmt_npr(b['dp'])}")
        print(f"  {r['position_pct']}% of budget | break-even {r['break_even']}")
        print(f"  If stopped: {nc.fmt_npr(r['loss_at_stop'])} ({r['loss_at_stop_pct']:+.2f}%) after fees")
        if "gain_at_target" in r:
            print(f"  If target:  {nc.fmt_npr(r['gain_at_target'])} ({r['gain_at_target_pct']:+.2f}%) "
                  f"after fees and CGT {nc.fmt_npr(r['cgt_at_target'])} | net R:R {r['net_reward_risk']}")
    print("[VERIFY] Fee and CGT rates as of 21 Nov 2026 (individual, <=365 days 5%).")
    print(nc.DISCLAIMER)
    if a.out:
        plan["sizing"] = r
        json.dump(plan, open(a.out, "w", encoding="utf-8"), indent=2)
        print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
