#!/usr/bin/env python3
"""Is the time machine honest? Calibration check on past signals.

For a sample of historical signals, run the bootstrap using ONLY the bars
before the signal, record its predicted P(target) and P(profit), then see
what really happened. A well-calibrated model's 30% bucket should hit
about 30% of the time.

  python calibrate.py --sample 1500 --paths 1000
"""

import argparse
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "nepse-timemachine"))
import nepse_common as nc  # noqa: E402
import timemachine as tm  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--paths", type=int, default=1000)
    ap.add_argument("--setups", default="breakout20,ma20_reclaim,high52")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args(argv)
    cfg = nc.load_config()
    rng = random.Random(a.seed)
    cands = []
    for sym in nc.universe(cfg):
        bars, _ = nc.load_bars(sym, cfg)
        if len(bars) < 400:
            continue
        ind = nc.compute_indicators(bars)
        for s in a.setups.split(","):
            for i in range(300, len(bars) - 1):
                if bars[i]["date"] >= a.start and nc.liquid(ind, i, cfg) \
                        and nc.SETUPS[s]["fn"](bars, ind, i):
                    cands.append((sym, s, i))
    rng.shuffle(cands)
    cache, rows = {}, []
    for sym, s, i in cands:
        if len(rows) >= a.sample:
            break
        if sym not in cache:
            b, _ = nc.load_bars(sym, cfg)
            cache[sym] = (b, nc.compute_indicators(b))
        bars, ind = cache[sym]
        t = nc.simulate_trade(bars, ind, i + 1, s, cfg)
        if not t or t.get("open"):
            continue
        sp = nc.SETUPS[s]
        plan = {"entry": t["entry"], "stop": t["stop"], "target": t["target"],
                "max_sessions": sp["max_sessions"], "exit_rule": sp["exit"]}
        pred = tm.bootstrap(bars[:i + 1], plan, cfg, a.paths, 250, seed=len(rows))
        rows.append((pred["p_target"], t["reason"] == "target",
                     pred["p_profit_after_costs"], nc.net_return_pct(t, cfg, 100000) > 0))
    print(f"Calibration on {len(rows)} past signals ({a.setups}), "
          f"{a.paths} paths each, using only pre-signal data\n")
    for label, pi, oi in (("P(target)", 0, 1), ("P(profit after costs)", 2, 3)):
        print(f"{label}: predicted bucket -> actual hit rate")
        buckets = {}
        for r in rows:
            k = min(int(r[pi] // 10) * 10, 90)
            buckets.setdefault(k, []).append(r[oi])
        for k in sorted(buckets):
            v = buckets[k]
            print(f"  {k:>2}-{k + 10:<3}%  n={len(v):>4}  actual {100 * sum(v) / len(v):5.1f}%")
        mp = sum(r[pi] for r in rows) / len(rows)
        ma = 100 * sum(r[oi] for r in rows) / len(rows)
        brier = sum((r[pi] / 100 - r[oi]) ** 2 for r in rows) / len(rows)
        base = ma / 100
        brier0 = sum((base - r[oi]) ** 2 for r in rows) / len(rows)
        print(f"  mean predicted {mp:.1f}% vs actual {ma:.1f}% | Brier {brier:.4f} "
              f"(always-guess-average {brier0:.4f}; lower is better)\n")


if __name__ == "__main__":
    main()
