#!/usr/bin/env python3
"""nepse-ticket: a plain order ticket to type into TMS yourself.

Nothing here connects to TMS or places an order. It refuses to write a
ticket unless the risk gate passes (override with --i-accept-block).

  python ticket.py --plan plan.json [--portfolio portfolio.json]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "nepse-risk"))
import nepse_common as nc  # noqa: E402
import check as risk  # noqa: E402


def ticket_text(plan, gate_result, cfg):
    sz = gate_result["sizing"]
    lim = cfg.get("price_limit_pct", nc.PRICE_LIMIT_PCT)
    lines = [
        "=" * 52,
        f" TMS BUY TICKET - enter manually   ({nc.now_npt()})",
        "=" * 52,
        f" Symbol      : {plan['symbol']}",
        f" Side        : BUY",
        f" Quantity    : {sz['shares']}  (multiple of {cfg['lot_size']})",
        f" Order type  : LIMIT, day order",
        f" Limit price : {plan['entry']:.2f}  (last close {plan['last_close']})",
        f" Est. cost   : {nc.fmt_npr(sz['cost_with_fees'])} incl. charges",
        "-" * 52,
        f" Stop        : {plan['stop']:.2f}  -> sell if a close/low breaks it",
        f" Target      : {plan['target'] if plan.get('target') else 'close > 5-day avg'}",
        f" Time stop   : sell after {plan['max_sessions']} sessions if neither hit",
        f" Earliest sale: T+{cfg['earliest_sell_session']} (shares must reach your demat)",
        f" Max loss    : {nc.fmt_npr(-sz['loss_at_stop'])} after fees",
        "-" * 52,
        f" Risk gate   : {gate_result['verdict']}",
        " Notes: TMS rejects prices outside the day's band "
        f"(+/-{lim:.0f}% of previous close) and outside the continuous-session "
        "band around the last traded price. If your TMS has no stop-loss order "
        "type, set a price alert or check the stop at every close.",
        "=" * 52,
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--portfolio", default="")
    ap.add_argument("--i-accept-block", action="store_true")
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    plan = json.load(open(a.plan, encoding="utf-8"))
    pf = json.load(open(a.portfolio, encoding="utf-8")) if a.portfolio else None
    g = risk.gate(plan, cfg, pf)
    if g["verdict"] != "PASS" and not a.i_accept_block:
        print("Risk gate BLOCKED this trade; no ticket written:")
        for x in g["block"]:
            print("  - " + x)
        sys.exit(2)
    if not g["sizing"].get("shares"):
        sys.exit("Sizing gives 0 shares; no ticket.")
    print(ticket_text(plan, g, cfg))
    print("Type this into TMS yourself only if you still want it. " + nc.DISCLAIMER)


if __name__ == "__main__":
    main()
