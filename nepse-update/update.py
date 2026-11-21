#!/usr/bin/env python3
"""nepse-update: download or refresh the free NEPSE end-of-day data.

Sources (public GitHub datasets, updated by their owners most trading days):
  * Aabishkar2/nepse-data  - per-company daily OHLCV, ~370 companies
  * zeutonx/NEPSE-Data     - NEPSE and sub-indices (only the index folder
                             is checked out)
Both are third-party; this script only reads their CSV files.

  python update.py            # clone on first run, pull afterwards
  python update.py --status   # show how fresh the data is
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import nepse_common as nc  # noqa: E402

REPOS = {
    "nepse-data": ("https://github.com/Aabishkar2/nepse-data.git", ["data/company-wise"]),
    "NEPSE-Data": ("https://github.com/zeutonx/NEPSE-Data.git", ["data/market/indices"]),
}


def git(args, cwd=None):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout.strip()


def sync(base):
    os.makedirs(base, exist_ok=True)
    for name, (url, paths) in REPOS.items():
        d = os.path.join(base, name)
        if not os.path.isdir(os.path.join(d, ".git")):
            print(f"Cloning {url} (sparse: {', '.join(paths)}) ...")
            git(["clone", "--depth", "1", "--filter=blob:none", "--sparse", url, d])
            git(["sparse-checkout", "set"] + paths, cwd=d)
        else:
            print(f"Updating {name} ...")
            git(["pull", "--depth", "1", "--ff-only"], cwd=d)
        print(f"  {name}: last commit {git(['log', '-1', '--format=%cd', '--date=short'], cwd=d)}")


def status(cfg):
    syms = nc.universe(cfg)
    if not syms:
        print(f"No data in {cfg['data_dir']}. Run: python update.py")
        return
    bars, _ = nc.load_bars("NABIL" if "NABIL" in syms else syms[0], cfg)
    age = nc.data_age_days(bars)
    tag = "FRESH" if age <= 4 else "STALE"
    print(f"[{tag}] {len(syms)} equities; latest bar {bars[-1]['date']} "
          f"({age} days old, checked {nc.now_npt()})")
    idx = nc.load_index(cfg)
    print(f"NEPSE index: {idx[-1]['date']} close {idx[-1]['close']:.2f}" if idx
          else "NEPSE index file missing (regime filter unavailable)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--base", default=os.path.join(os.path.expanduser("~"), ".nepse-trader"))
    a = ap.parse_args()
    cfg = nc.load_config()
    if not a.status:
        try:
            sync(a.base)
        except (RuntimeError, FileNotFoundError) as e:
            sys.exit(f"Update failed: {e}\nCheck your internet connection and that git is installed.")
    status(cfg)


if __name__ == "__main__":
    main()
