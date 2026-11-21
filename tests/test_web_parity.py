"""The web app's engine.js must give the same answers as the Python skills.
Skipped when Node.js is not installed."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for p in ("lib", "nepse-exit", "nepse-budget", "nepse-risk", "nepse-timemachine"):
    sys.path.insert(0, os.path.join(ROOT, p))
import nepse_common as nc  # noqa: E402
import exit as ex  # noqa: E402
import size as sz  # noqa: E402
import check as rk  # noqa: E402
import timemachine as tm  # noqa: E402
from test_pipeline import make_bars, TODAY, CFG  # noqa: E402


def stock_json(sym, bars, sector):
    ind = nc.compute_indicators(bars)
    tail = bars[-300:]
    k0 = len(bars) - len(tail)
    r = lambda x: None if x is None else round(x, 2)  # noqa: E731
    return {"symbol": sym, "sector": sector, "d": [b["date"] for b in tail],
            "o": [r(b["open"]) for b in tail], "h": [r(b["high"]) for b in tail],
            "l": [r(b["low"]) for b in tail], "c": [r(b["close"]) for b in tail],
            "v": [round(b["volume"]) for b in tail], "t": [round(b["turnover"]) for b in tail],
            "atr": [r(x) for x in ind["atr14"][k0:]]}


def round_bars(bars):
    return [dict(b, open=round(b["open"], 2), high=round(b["high"], 2),
                 low=round(b["low"], 2), close=round(b["close"], 2),
                 turnover=round(b["turnover"])) for b in bars]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class WebParity(unittest.TestCase):
    def test_engine_matches_python(self):
        cfg = CFG
        sectors = nc.load_sectors(cfg)
        meta = {"config": {k: v for k, v in cfg.items() if not k.endswith(("_dir", "_csv"))},
                "setups": {k: {kk: vv for kk, vv in v.items() if kk != "fn"} for k, v in nc.SETUPS.items()},
                "record": nc.BACKTEST_RECORD}
        holdings = [{"symbol": "NICA", "qty": 100, "avg_cost": 480},
                    {"symbol": "CHCL", "qty": 200, "avg_cost": 420, "last_price": 450}]
        fees = [[100, 500, 520, 10], [1000, 450, 560, 100], [10, 300, 250, 5],
                [5000, 1200, 1500, 400], [20000, 600, 700, 30], [123450 // 10 * 10, 101.5, 99.1, 20]]
        cases, py = [], []
        specs = [("NABIL", "breakout20", {}, 0.01, 2e7, 3),
                 ("NICA", "high52", {"stop": "pct:6", "target": "r:2.5"}, 0.02, 3e7, 4),
                 ("CHCL", "rsi2_pullback", {}, -0.01, 8e6, 5),
                 ("UPPER", "breakout20", {"stop": "swing"}, 0.149, 4e7, 6),
                 ("THIN", "ma20_reclaim", {"stop": "pct:4", "target": "r:3"}, 0.0, 1e6, 7)]
        for sym, setup, opts, chg, turn, seed in specs:
            bars = round_bars(make_bars(400, chg, turn, seed))
            sj = stock_json(sym, bars, sectors.get(sym, ""))
            cases.append({"stock": sj, "setup": setup, "opts": opts, "holdings": holdings,
                          "today": TODAY.isoformat()})
            plan = ex.plan_exit(sym, cfg, setup, opts.get("entry"), opts.get("stop", "atr"),
                                opts.get("target"), bars=bars)
            s = sz.size_plan(plan, cfg, {"holdings": holdings})
            g = rk.gate(plan, cfg, {"holdings": holdings}, bars=bars, today=TODAY)
            b = tm.bootstrap(bars, plan, cfg, paths=20000, seed=3)
            py.append({"plan": plan, "sz": s, "g": g, "tm": b})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"meta": meta, "sectors": sectors, "fees": fees, "cases": cases}, f)
        r = subprocess.run(["node", os.path.join(ROOT, "tests", "web_parity.mjs"), f.name],
                           capture_output=True, text=True)
        os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        js = json.loads(r.stdout)

        for vec, j in zip(fees, js["fees"]):
            p = nc.round_trip(*vec[:3], cfg, holding_days=vec[3])
            for k in ("cost_basis", "cgt", "net_proceeds", "net_pnl", "total_charges"):
                self.assertAlmostEqual(p[k], j[k], delta=0.011, msg=f"fees {vec} {k}")
            self.assertAlmostEqual(p["buy"]["commission"], j["buy"]["commission"], delta=0.011)

        for (sym, *_), p, j in zip(specs, py, js["cases"]):
            for k in ("entry", "stop", "target", "risk_pct", "reward_risk", "break_even", "atr14"):
                self.assertAlmostEqual(p["plan"][k] or 0, j["plan"][k] or 0, delta=0.011, msg=f"{sym} plan {k}")
            self.assertEqual(p["plan"]["exit_rule"], j["plan"]["exit_rule"], sym)
            self.assertEqual(len(p["plan"]["warnings"]), len(j["plan"]["warnings"]), sym)
            for k in ("shares", "binding_cap"):
                self.assertEqual(p["sz"][k], j["sz"][k], f"{sym} size {k}")
            for k in ("loss_at_stop", "gain_at_target", "cost_with_fees", "net_reward_risk", "break_even"):
                if k in p["sz"]:
                    # a 0.005 tie in target/stop rounding moves rupee totals by shares x 0.01
                    tol = 0.011 + 0.0101 * p["sz"]["shares"] if k in ("gain_at_target", "loss_at_stop") else 0.011
                    self.assertAlmostEqual(p["sz"][k] or 0, j["sz"][k] or 0, delta=tol, msg=f"{sym} size {k}")
            self.assertEqual(p["g"]["verdict"], j["verdict"], f"{sym} gate {p['g']['block']}")
            self.assertEqual(len(p["g"]["block"]), j["nblock"], f"{sym} gate blocks")
            # different RNGs: same distribution within sampling error
            for k in ("p_target", "p_stop", "p_time", "p_profit_after_costs"):
                self.assertAlmostEqual(p["tm"][k], j["tm"][k], delta=2.5, msg=f"{sym} tm {k}")
            self.assertAlmostEqual(p["tm"]["expected_net_pct"], j["tm"]["expected_net_pct"], delta=0.35)


if __name__ == "__main__":
    unittest.main()
