"""Accuracy tests for the NEPSE core: fees, lots, adjustment, indicators,
trade simulation and no look-ahead. Run: python -m unittest discover tests"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402

CFG = nc._deep_merge(nc.DEFAULT_CONFIG, {})


def bar(d, o, h, l, c, v=1000.0, pc=None):
    return {"date": d, "open": o, "high": h, "low": l, "close": c,
            "volume": v, "turnover": v * c, "per_change": pc}


def dates(n, start=(2025, 1, 1)):
    import datetime as dt
    d0 = dt.date(*start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


class Fees(unittest.TestCase):
    def test_sharehub_worked_example_buy(self):
        # ShareHub (Oct 2026): 100 shares at Rs 500 -> total Rs 50,212.50
        b = nc.side_costs(100 * 500, CFG["fees"], "buy")
        self.assertEqual(b["commission"], 180.00)
        self.assertEqual(b["sebon"], 7.50)
        self.assertEqual(b["dp"], 25.0)
        self.assertAlmostEqual(b["value"] + b["total"], 50212.50, places=2)

    def test_slab_applies_to_whole_value(self):
        f = CFG["fees"]
        self.assertEqual(nc.commission_rate_pct(50000, f), 0.36)
        self.assertEqual(nc.commission_rate_pct(50001, f), 0.33)
        self.assertEqual(nc.commission_rate_pct(500001, f), 0.31)
        self.assertEqual(nc.commission_rate_pct(2000001, f), 0.27)
        self.assertEqual(nc.commission_rate_pct(10000001, f), 0.24)
        # the known slab quirk: Rs 50,001 pays less commission than Rs 50,000
        self.assertLess(nc.side_costs(50001, f, "buy")["commission"],
                        nc.side_costs(50000, f, "buy")["commission"])

    def test_minimum_commission(self):
        self.assertEqual(nc.side_costs(1000, CFG["fees"], "buy")["commission"], 10.0)

    def test_round_trip_hand_calc(self):
        # 1,000 @ 450 bought, sold @ 560 after 100 days, individual.
        rt = nc.round_trip(1000, 450, 560, CFG, holding_days=100)
        buy = 450000 + 1485 + 67.5 + 25          # 0.33% slab
        sell_charges = 1736 + 84 + 25            # 0.31% slab (500,001-20 lakh)
        self.assertAlmostEqual(rt["sell"]["total"], 1845.0, places=2)  # = ShareHub
        gain = 560000 - sell_charges - buy
        cgt = round(gain * 0.05, 2)
        # ShareHub's Rs 5,330.13 leaves out the Rs 25 buy-side DP charge
        self.assertAlmostEqual(cgt + 25 * 0.05, 5330.13, places=1)
        self.assertAlmostEqual(rt["cost_basis"], buy, places=2)
        self.assertAlmostEqual(rt["cgt"], cgt, places=2)
        self.assertAlmostEqual(rt["net_pnl"], gain - cgt, places=2)

    def test_cgt_long_term_and_losses(self):
        self.assertEqual(nc.cgt_rate_pct(CFG, 366), 3.75)
        self.assertEqual(nc.cgt_rate_pct(CFG, 365), 5.0)
        self.assertEqual(nc.round_trip(100, 500, 450, CFG)["cgt"], 0.0)
        inst = dict(CFG, investor_type="institution")
        self.assertEqual(nc.cgt_rate_pct(inst, 30), 10.0)

    def test_break_even_is_tight(self):
        be = nc.break_even_price(1000, 450, CFG)
        self.assertGreaterEqual(nc.round_trip(1000, 450, be, CFG)["net_pnl"], 0)
        self.assertLess(nc.round_trip(1000, 450, be - 0.02, CFG)["net_pnl"], 0)
        self.assertTrue(452 < be < 454)   # ~0.7% above cost, as ShareHub says

    def test_round_lot(self):
        self.assertEqual(nc.round_lot(57), 50)
        self.assertEqual(nc.round_lot(9), 0)
        self.assertEqual(nc.round_lot(100), 100)


class Adjustment(unittest.TestCase):
    def test_bonus_back_adjusts_history(self):
        # 10% bonus: base resets 1000 -> 909.09; day closes 918.18 (+1%)
        raw = [bar("2025-01-01", 990, 1000, 985, 1000, pc=None),
               bar("2025-01-02", 1000, 1005, 995, 1000, pc=0.0),
               bar("2025-01-03", 910, 920, 905, 918.18, pc=1.0)]
        out, ev = nc.adjust_bars(raw)
        self.assertEqual(len(ev), 1)
        self.assertAlmostEqual(ev[0]["factor"], 1 / 1.1, places=3)
        self.assertAlmostEqual(out[1]["close"], 909.09, places=1)
        self.assertAlmostEqual(out[2]["close"] / out[1]["close"] - 1, 0.01, places=3)
        self.assertEqual(out[2]["close"], 918.18)        # latest bar untouched

    def test_normal_moves_not_adjusted(self):
        raw = [bar("2025-01-01", 100, 101, 99, 100), bar("2025-01-02", 100, 111, 100, 110, pc=10.0)]
        _, ev = nc.adjust_bars(raw)
        self.assertEqual(ev, [])


class Indicators(unittest.TestCase):
    def test_sma_and_max(self):
        xs = [1, 2, 3, 4, 5]
        self.assertEqual(nc.sma(xs, 3), [None, None, 2.0, 3.0, 4.0])
        self.assertEqual(nc.rolling_max(xs, 2), [None, 2, 3, 4, 5])

    def test_rsi_bounds(self):
        up = list(range(1, 40))
        self.assertEqual(nc.rsi(up, 2)[-1], 100.0)
        down = list(range(40, 1, -1))
        self.assertLess(nc.rsi(down, 2)[-1], 1)

    def test_atr_constant_range(self):
        bs = [bar(d, 100, 102, 98, 100) for d in dates(30)]
        self.assertAlmostEqual(nc.atr(bs, 14)[-1], 4.0)


class Simulation(unittest.TestCase):
    SETUP = {"fn": None, "stop_atr": 1.0, "target_r": 2.0, "max_sessions": 10, "exit": "bracket"}

    def series(self, path):
        """flat 100 bars (ATR 4) then the given (o,h,l,c) path."""
        bs = [bar(d, 100, 102, 98, 100) for d in dates(30)]
        ds = dates(30 + len(path))[30:]
        bs += [bar(d, *p) for d, p in zip(ds, path)]
        return bs, nc.compute_indicators(bs)

    def test_target_hit(self):
        # entry 100, ATR 4 -> stop 96, target 108
        bs, ind = self.series([(100, 101, 99, 100), (100, 101, 99, 100),
                               (101, 109, 100, 108)])
        t = nc.simulate_trade(bs, ind, 30, self.SETUP, CFG)
        self.assertEqual(t["reason"], "target")
        self.assertEqual(t["exit"], 108)

    def test_t_plus_2_lock_in(self):
        # crashes on the entry day and day after; cannot sell until session 2,
        # where it opens at 90 -> sold at the 90 open, not at the 96 stop
        bs, ind = self.series([(100, 100, 92, 93), (93, 93, 88, 89),
                               (90, 91, 88, 90)])
        t = nc.simulate_trade(bs, ind, 30, self.SETUP, CFG)
        self.assertEqual(t["reason"], "stop")
        self.assertEqual(t["exit"], 90)
        self.assertEqual(t["sessions"], 2)

    def test_gap_down_fills_at_open(self):
        bs, ind = self.series([(100, 101, 99, 100), (100, 101, 99, 100),
                               (100, 101, 99, 100), (92, 93, 90, 91)])
        t = nc.simulate_trade(bs, ind, 30, self.SETUP, CFG)
        self.assertEqual((t["reason"], t["exit"]), ("stop", 92))

    def test_both_touched_assumes_stop(self):
        bs, ind = self.series([(100, 101, 99, 100), (100, 101, 99, 100),
                               (100, 110, 95, 100)])
        t = nc.simulate_trade(bs, ind, 30, self.SETUP, CFG)
        self.assertEqual(t["reason"], "stop")

    def test_time_exit(self):
        bs, ind = self.series([(100, 101, 99, 100)] * 12)
        t = nc.simulate_trade(bs, ind, 30, self.SETUP, CFG)
        self.assertEqual((t["reason"], t["sessions"]), ("time", 10))

    def test_open_trade_reported_open(self):
        bs, ind = self.series([(100, 101, 99, 100)] * 4)
        self.assertTrue(nc.simulate_trade(bs, ind, 30, self.SETUP, CFG).get("open"))

    def test_locked_upper(self):
        bs = [bar("2025-01-01", 100, 100, 100, 100), bar("2025-01-02", 115, 115, 115, 115)]
        self.assertTrue(nc.locked_upper(bs, 1, CFG))
        bs[1] = bar("2025-01-02", 110, 115, 108, 114)
        self.assertFalse(nc.locked_upper(bs, 1, CFG))


class NoLookAhead(unittest.TestCase):
    def test_signals_ignore_future_bars(self):
        import random
        rng = random.Random(1)
        p = 100.0
        bs = []
        for d in dates(400):
            o = p
            p = max(10, p * (1 + rng.uniform(-0.04, 0.045)))
            bs.append(bar(d, o, max(o, p) * 1.01, min(o, p) * 0.99, p, rng.uniform(500, 3000)))
        ind = nc.compute_indicators(bs)
        for name, sp in nc.SETUPS.items():
            for i in range(270, 380, 7):
                fut = copy.deepcopy(bs)
                for b in fut[i + 1:]:
                    b["close"] *= 3; b["high"] *= 3; b["low"] *= 0.3; b["volume"] *= 9
                ind2 = nc.compute_indicators(fut)
                self.assertEqual(sp["fn"](bs, ind, i), sp["fn"](fut, ind2, i),
                                 f"{name} looked ahead at bar {i}")


if __name__ == "__main__":
    unittest.main()
