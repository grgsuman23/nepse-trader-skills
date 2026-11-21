"""Pipeline tests on synthetic data: exit plan, sizing caps, risk gate,
ticket refusal and time machine sanity. Run: python -m unittest discover tests"""

import datetime as dt
import os
import random
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for p in ("lib", "nepse-exit", "nepse-budget", "nepse-risk", "nepse-ticket", "nepse-timemachine"):
    sys.path.insert(0, os.path.join(ROOT, p))
import nepse_common as nc  # noqa: E402
import exit as ex  # noqa: E402
import size as sz  # noqa: E402
import check as rk  # noqa: E402
import ticket as tk  # noqa: E402
import timemachine as tm  # noqa: E402

CFG = nc._deep_merge(nc.DEFAULT_CONFIG, {"sectors_csv": os.path.join(ROOT, "data", "sectors.csv")})
TODAY = dt.date(2026, 11, 21)


def make_bars(n=400, last_chg=0.01, turnover=2e7, seed=3):
    rng = random.Random(seed)
    d0 = TODAY - dt.timedelta(days=n)
    p, out = 500.0, []
    for k in range(n):
        o = p
        p *= 1 + rng.uniform(-0.02, 0.021)
        out.append({"date": (d0 + dt.timedelta(days=k)).isoformat(), "open": o,
                    "high": max(o, p) * 1.01, "low": min(o, p) * 0.99, "close": p,
                    "volume": turnover / p, "turnover": turnover})
    out[-1]["close"] = out[-2]["close"] * (1 + last_chg)
    out[-1]["high"] = max(out[-1]["high"], out[-1]["close"])
    return out


class Pipeline(unittest.TestCase):
    def plan(self, bars, **kw):
        return ex.plan_exit("NABIL", CFG, "breakout20", bars=bars, **kw)

    def test_exit_levels(self):
        bars = make_bars()
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:2")
        self.assertAlmostEqual(p["stop"], p["entry"] * 0.95, delta=0.02)
        self.assertAlmostEqual(p["target"], p["entry"] + 2 * (p["entry"] - p["stop"]), delta=0.05)
        self.assertGreater(p["break_even"], p["entry"])

    def test_wide_stop_warns_about_limit(self):
        p = self.plan(make_bars(), stop_spec="pct:20")
        self.assertTrue(any("daily price limit" in w for w in p["warnings"]))

    def test_size_respects_every_cap_and_lots(self):
        p = self.plan(make_bars(), stop_spec="pct:5", target_spec="r:3")
        r = sz.size_plan(p, CFG)
        self.assertEqual(r["shares"] % 10, 0)
        self.assertLessEqual(-r["loss_at_stop"], CFG["max_loss_per_trade_npr"])
        self.assertLessEqual(r["shares"] * p["entry"], CFG["budget_npr"] * CFG["max_position_pct"] / 100)
        # adding 10 more shares would break the binding cap
        self.assertIn(r["binding_cap"], ("risk", "position", "cash"))

    def test_cash_cap_with_holdings(self):
        p = self.plan(make_bars(), stop_spec="pct:5", target_spec="r:3")
        pf = {"holdings": [{"symbol": "NICA", "qty": 1000, "avg_cost": 470}]}
        r = sz.size_plan(p, CFG, pf)
        self.assertEqual(r["binding_cap"], "cash")
        self.assertLessEqual(r["shares"] * p["entry"] * 1.004,
                             CFG["budget_npr"] * 0.95 - 470000 + 1)

    def test_gate_passes_clean_trade(self):
        bars = make_bars()
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:3")
        g = rk.gate(p, CFG, None, bars=bars, today=TODAY)
        self.assertEqual(g["verdict"], "PASS", g["block"])

    def test_gate_blocks_limit_up_chase(self):
        bars = make_bars(last_chg=0.15)
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:3")
        g = rk.gate(p, CFG, None, bars=bars, today=TODAY)
        self.assertEqual(g["verdict"], "BLOCK")
        self.assertTrue(any("limit" in b for b in g["block"]))

    def test_gate_blocks_thin_and_stale_and_low_rr(self):
        bars = make_bars(turnover=1e6)
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:1")
        g = rk.gate(p, CFG, None, bars=bars, today=TODAY + dt.timedelta(days=10))
        text = " ".join(g["block"])
        for word in ("Thin", "days old", "reward:risk"):
            self.assertIn(word, text)

    def test_gate_blocks_sector_concentration(self):
        bars = make_bars()
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:3")
        pf = {"holdings": [{"symbol": "NICA", "qty": 300, "avg_cost": 500},
                           {"symbol": "SANIMA", "qty": 300, "avg_cost": 300}]}
        g = rk.gate(p, dict(CFG, budget_npr=1000000, max_sector_pct=25), pf, bars=bars, today=TODAY)
        self.assertTrue(any("Commercial Banks exposure" in b for b in g["block"]))

    def test_ticket_text(self):
        bars = make_bars()
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:3")
        g = rk.gate(p, CFG, None, bars=bars, today=TODAY)
        t = tk.ticket_text(p, g, CFG)
        self.assertIn("enter manually", t)
        self.assertIn(f"Quantity    : {g['sizing']['shares']}", t)

    def test_timemachine_probabilities(self):
        bars = make_bars(600)
        p = self.plan(bars, stop_spec="pct:5", target_spec="r:2")
        b = tm.bootstrap(bars, p, CFG, paths=3000, seed=1)
        self.assertAlmostEqual(b["p_target"] + b["p_stop"] + b["p_time"] + b["p_signal_exit"], 100, delta=0.3)
        # zero drift, symmetric-ish noise, 2R target: stop should be likelier
        self.assertGreater(b["p_stop"], b["p_target"])
        self.assertLessEqual(b["p5_net_pct"], b["expected_net_pct"])
        self.assertLessEqual(b["expected_net_pct"], b["p95_net_pct"])


if __name__ == "__main__":
    unittest.main()
