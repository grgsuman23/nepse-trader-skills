"""Shared core for the NEPSE trader skills.

Pure standard library (Python 3.8+). Everything that encodes a NEPSE rule
lives here so it can be checked and changed in one place:

  * fees()            broker commission slabs, SEBON fee, DP charge, CGT
  * round_lot()       regular-session orders in multiples of 10 units
  * PRICE_LIMIT_PCT   per-stock daily price band (15% since 20 Apr 2026)
  * load_bars()       daily OHLCV from CSV, back-adjusted for bonus/rights
  * indicators        SMA, rolling max/min, Wilder ATR and RSI
  * SETUPS            the scanner's entry rules, used by scan, backtest
                      and the time machine so all three agree

Rates last verified 21 Nov 2026. Rates change: check them before relying on
any rupee figure, and edit config.json rather than this file.
"""

import csv
import datetime as _dt
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DISCLAIMER = ("Rules and simulation on past data, not a prediction or "
              "financial advice. You place every order yourself in TMS.")

NPT = _dt.timezone(_dt.timedelta(hours=5, minutes=45))

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    # where the per-company CSVs live (Aabishkar2/nepse-data layout)
    "data_dir": os.path.join(os.path.expanduser("~"), ".nepse-trader",
                             "nepse-data", "data", "company-wise"),
    # optional NEPSE index CSV (zeutonx/NEPSE-Data layout) for regime filter
    "index_csv": os.path.join(os.path.expanduser("~"), ".nepse-trader",
                              "NEPSE-Data", "data", "market", "indices",
                              "NEPSE_Index.csv"),
    "sectors_csv": os.path.join(ROOT, "data", "sectors.csv"),

    "budget_npr": 500000,           # total trading capital
    "cash_buffer_pct": 5,           # never deploy the last 5%
    "max_position_pct": 20,         # of budget, per stock
    "max_sector_pct": 40,           # of budget, per sector (incl. holdings)
    "max_loss_per_trade_npr": 5000, # rupees lost if the stop is hit
    "min_reward_risk": 1.5,
    "min_avg_turnover_npr": 5000000,   # 20-day average daily turnover
    "max_pct_of_turnover": 10,      # position vs 20-day avg daily turnover
    "lot_size": 10,
    "earliest_sell_session": 2,     # T+2: first session you can sell after buying
    "investor_type": "individual",  # individual | institution

    "fees": {
        # SEBON-approved equity slabs; the rate applies to the WHOLE value
        "commission_slabs": [
            [50000, 0.36],
            [500000, 0.33],
            [2000000, 0.31],
            [10000000, 0.27],
            [None, 0.24]
        ],
        "min_commission_npr": 10.0,
        "sebon_fee_pct": 0.015,
        "dp_charge_npr": 25.0,        # per scrip per trading day
        "dp_on_buy": True,
        "dp_on_sell": True,
        # resident individuals, from 22 Sep 2026
        "cgt_short_pct": 5.0,         # held 365 days or less
        "cgt_long_pct": 3.75,         # held more than 365 days
        "cgt_institution_pct": 10.0   # VERIFY for your entity
    },
    "price_limit_pct": 15.0
}

PRICE_LIMIT_PCT = 15.0  # per-stock daily band since 20 Apr 2026 (was 10%)


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def config_path():
    return os.environ.get("NEPSE_TRADER_CONFIG",
                          os.path.join(ROOT, "config.json"))


def load_config(path=None):
    path = path or config_path()
    cfg = DEFAULT_CONFIG
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = _deep_merge(DEFAULT_CONFIG, json.load(f))
    for k in ("data_dir", "index_csv", "sectors_csv"):
        cfg[k] = os.path.expanduser(os.environ.get("NEPSE_" + k.upper(), cfg[k]))
    return cfg


# --------------------------------------------------------------------------
# Fees and tax
# --------------------------------------------------------------------------

def commission_rate_pct(value, fees_cfg):
    for limit, rate in fees_cfg["commission_slabs"]:
        if limit is None or value <= limit:
            return rate
    return fees_cfg["commission_slabs"][-1][1]


def side_costs(value, fees_cfg, side):
    """Commission + SEBON + DP for one side ('buy' or 'sell') of a trade."""
    if value <= 0:
        return {"value": 0.0, "commission": 0.0, "sebon": 0.0, "dp": 0.0,
                "total": 0.0, "commission_rate_pct": 0.0}
    rate = commission_rate_pct(value, fees_cfg)
    comm = max(value * rate / 100.0, fees_cfg["min_commission_npr"])
    sebon = value * fees_cfg["sebon_fee_pct"] / 100.0
    dp_flag = fees_cfg["dp_on_buy"] if side == "buy" else fees_cfg["dp_on_sell"]
    dp = fees_cfg["dp_charge_npr"] if dp_flag else 0.0
    comm, sebon = round(comm, 2), round(sebon, 2)
    return {"value": round(value, 2), "commission": comm, "sebon": sebon,
            "dp": dp, "total": round(comm + sebon + dp, 2),
            "commission_rate_pct": rate}


def cgt_rate_pct(cfg, holding_days):
    f = cfg["fees"]
    if cfg.get("investor_type", "individual") != "individual":
        return f["cgt_institution_pct"]
    return f["cgt_long_pct"] if holding_days > 365 else f["cgt_short_pct"]


def round_trip(shares, buy_price, sell_price, cfg, holding_days=30):
    """Full cost of buying and selling `shares`. CGT is on the gain after
    all buy- and sell-side charges (how NEPSE brokers compute WACC gain)."""
    f = cfg["fees"]
    buy = side_costs(shares * buy_price, f, "buy")
    sell = side_costs(shares * sell_price, f, "sell")
    cost_basis = buy["value"] + buy["total"]
    proceeds_pre_tax = sell["value"] - sell["total"]
    gain = proceeds_pre_tax - cost_basis
    rate = cgt_rate_pct(cfg, holding_days)
    cgt = round(gain * rate / 100.0, 2) if gain > 0 else 0.0
    net = round(proceeds_pre_tax - cgt, 2)
    pnl = round(net - cost_basis, 2)
    return {"shares": shares, "buy": buy, "sell": sell,
            "cost_basis": round(cost_basis, 2), "cgt_rate_pct": rate,
            "cgt": cgt, "net_proceeds": net, "net_pnl": pnl,
            "net_return_pct": round(100.0 * pnl / cost_basis, 4) if cost_basis else 0.0,
            "total_charges": round(buy["total"] + sell["total"] + cgt, 2)}


def break_even_price(shares, buy_price, cfg):
    """Lowest sell price that returns at least the full cost basis."""
    lo, hi = buy_price, buy_price * 1.2
    for _ in range(60):
        mid = (lo + hi) / 2
        if round_trip(shares, buy_price, mid, cfg)["net_pnl"] >= 0:
            hi = mid
        else:
            lo = mid
    return round(hi, 2)


def round_lot(shares, lot=10):
    return int(shares // lot) * lot


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def load_sectors(cfg):
    out = {}
    p = cfg["sectors_csv"]
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["symbol"].strip().upper()] = r["sector"].strip()
    return out


def universe(cfg):
    """Listed equities that have a price file. Debentures, mutual funds,
    bonds and promoter shares are left out because they are not in the
    equity sector map."""
    sectors = load_sectors(cfg)
    have = set()
    if os.path.isdir(cfg["data_dir"]):
        have = {n[:-4].upper() for n in os.listdir(cfg["data_dir"])
                if n.endswith(".csv")}
    return sorted(s for s in sectors if s in have)


ADJ_THRESHOLD_PP = 2.0   # gap between reported % change and close/close


def adjust_bars(raw):
    """Back-adjust OHLC for bonus / rights / cash-dividend base resets.

    NEPSE resets a stock's base price after book closure. The CSV's
    per_change is measured against that adjusted base, so when it disagrees
    with close/prev_close by more than ADJ_THRESHOLD_PP the ratio between
    the two is the adjustment factor for every earlier bar.
    Returns (bars, events)."""
    n = len(raw)
    factors = [1.0] * n
    events = []
    for i in range(1, n):
        pc, c0, c1 = raw[i]["per_change"], raw[i - 1]["close"], raw[i]["close"]
        if pc is None or not c0:
            continue
        actual = (c1 / c0 - 1) * 100
        if abs(actual - pc) > ADJ_THRESHOLD_PP:
            base = c1 / (1 + pc / 100.0)
            f = base / c0
            if 0.2 < f < 1.5:
                factors[i] = f
                events.append({"date": raw[i]["date"], "factor": round(f, 4),
                               "reported_pct": pc, "raw_pct": round(actual, 2)})
    cum = 1.0
    out = [None] * n
    for i in range(n - 1, -1, -1):
        b = raw[i]
        out[i] = {"date": b["date"],
                  "open": b["open"] * cum, "high": b["high"] * cum,
                  "low": b["low"] * cum, "close": b["close"] * cum,
                  "volume": b["volume"] / cum if cum else b["volume"],
                  "turnover": b["turnover"],
                  "raw_close": b["close"], "adj": cum}
        cum *= factors[i]
    return out, events


def load_bars(symbol, cfg, adjusted=True):
    path = os.path.join(cfg["data_dir"], symbol.upper() + ".csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No price file for {symbol} at {path}. "
                                "Run nepse-update first.")
    raw = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            o, h, l, c = (_f(r.get(k)) for k in ("open", "high", "low", "close"))
            if not c or c <= 0:
                continue
            o = o if o and o > 0 else c
            h = max(x for x in (h, o, c) if x)
            l = min(x for x in (l, o, c) if x and x > 0)
            raw.append({"date": r["published_date"][:10], "open": o, "high": h,
                        "low": l, "close": c,
                        "per_change": _f(r.get("per_change")),
                        "volume": _f(r.get("traded_quantity")) or 0.0,
                        "turnover": _f(r.get("traded_amount")) or 0.0})
    raw.sort(key=lambda b: b["date"])
    # drop duplicate dates (keep last)
    dedup = {}
    for b in raw:
        dedup[b["date"]] = b
    raw = [dedup[d] for d in sorted(dedup)]
    if not adjusted:
        return raw, []
    return adjust_bars(raw)


def load_index(cfg):
    p = cfg["index_csv"]
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            c = _f(r.get("close"))
            if c:
                out.append({"date": r["date"][:10], "close": c})
    out.sort(key=lambda b: b["date"])
    return out


def data_age_days(bars, today=None):
    today = today or _dt.datetime.now(NPT).date()
    last = _dt.date.fromisoformat(bars[-1]["date"])
    return (today - last).days


# --------------------------------------------------------------------------
# Indicators (all causal: value at i uses bars 0..i only)
# --------------------------------------------------------------------------

def sma(xs, n):
    out = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rolling_max(xs, n):
    return [max(xs[i - n + 1:i + 1]) if i >= n - 1 else None
            for i in range(len(xs))]


def rolling_min(xs, n):
    return [min(xs[i - n + 1:i + 1]) if i >= n - 1 else None
            for i in range(len(xs))]


def atr(bars, n=14):
    out = [None] * len(bars)
    trs = []
    prev = None
    for i, b in enumerate(bars):
        tr = b["high"] - b["low"] if prev is None else max(
            b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev))
        trs.append(tr)
        prev = b["close"]
        if i == n - 1:
            out[i] = sum(trs) / n
        elif i >= n:
            out[i] = (out[i - 1] * (n - 1) + tr) / n
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def compute_indicators(bars):
    c = [b["close"] for b in bars]
    h = [b["high"] for b in bars]
    v = [b["volume"] for b in bars]
    t = [b["turnover"] for b in bars]
    ind = {
        "sma5": sma(c, 5), "sma20": sma(c, 20), "sma50": sma(c, 50),
        "sma100": sma(c, 100), "sma200": sma(c, 200),
        "hh20": rolling_max(h, 20), "hh250": rolling_max(h, 250),
        "vol20": sma(v, 20), "turn20": sma(t, 20),
        "atr14": atr(bars, 14), "rsi2": rsi(c, 2), "rsi14": rsi(c, 14),
    }
    return ind


# --------------------------------------------------------------------------
# Setups. signal(i) uses only data up to and including bar i (the close).
# The trade is entered at bar i+1's open.
# --------------------------------------------------------------------------

def _ok(*xs):
    return all(x is not None for x in xs)


def sig_breakout20(b, ind, i):
    """Close above the prior 20-day high on 1.5x volume, in an uptrend."""
    if i < 60:
        return False
    hh, v20, s50 = ind["hh20"][i - 1], ind["vol20"][i - 1], ind["sma50"][i]
    if not _ok(hh, v20, s50) or v20 <= 0:
        return False
    return (b[i]["close"] > hh and b[i]["volume"] >= 1.5 * v20
            and b[i]["close"] > s50)


def sig_ma20_reclaim(b, ind, i):
    """Close back above the 20-day average while the 50-day is rising."""
    if i < 70:
        return False
    s20, s20p, s50, s50p = (ind["sma20"][i], ind["sma20"][i - 1],
                            ind["sma50"][i], ind["sma50"][i - 10])
    if not _ok(s20, s20p, s50, s50p):
        return False
    return (b[i - 1]["close"] < s20p and b[i]["close"] > s20
            and s50 > s50p and b[i]["close"] > s50)


def sig_rsi2_pullback(b, ind, i):
    """2-day RSI under 10 in a stock above its 200-day average."""
    r, s200 = ind["rsi2"][i], ind["sma200"][i]
    if not _ok(r, s200):
        return False
    return r < 10 and b[i]["close"] > s200


def sig_high52(b, ind, i):
    """New 52-week (250-session) closing high on above-average volume."""
    if i < 260:
        return False
    hh, v20 = ind["hh250"][i - 1], ind["vol20"][i - 1]
    if not _ok(hh, v20) or v20 <= 0:
        return False
    return b[i]["close"] > hh and b[i]["volume"] >= 1.2 * v20


SETUPS = {
    "breakout20": {"fn": sig_breakout20, "stop_atr": 1.5, "target_r": 2.0,
                   "max_sessions": 15, "exit": "bracket",
                   "about": "20-day breakout on 1.5x volume above the 50-day"},
    "ma20_reclaim": {"fn": sig_ma20_reclaim, "stop_atr": 1.5, "target_r": 2.0,
                     "max_sessions": 15, "exit": "bracket",
                     "about": "reclaim of the 20-day average, 50-day rising"},
    "rsi2_pullback": {"fn": sig_rsi2_pullback, "stop_atr": 2.0, "target_r": None,
                      "max_sessions": 10, "exit": "close_above_sma5",
                      "about": "RSI(2) < 10 above the 200-day (mean reversion)"},
    "high52": {"fn": sig_high52, "stop_atr": 2.0, "target_r": 2.0,
               "max_sessions": 20, "exit": "bracket",
               "about": "new 52-week high on 1.2x volume"},
}


# Market-wide backtest record, 2016-01-01 to 2026-11-20, net of all costs
# (docs/ACCURACY.md). Re-run nepse-backtest to refresh.
BACKTEST_RECORD = {
    "breakout20": {"avg_net_pct": -0.85, "edge_vs_random_pp": -0.14},
    "ma20_reclaim": {"avg_net_pct": -1.26, "edge_vs_random_pp": -0.56},
    "rsi2_pullback": {"avg_net_pct": -0.72, "edge_vs_random_pp": 0.36},
    "high52": {"avg_net_pct": 0.69, "edge_vs_random_pp": 1.15},
}


def liquid(ind, i, cfg):
    t = ind["turn20"][i]
    return t is not None and t >= cfg["min_avg_turnover_npr"]


def regime_ok(index_by_date, date, index_sma):
    """True when NEPSE index close is above its 50-day average on `date`."""
    v = index_sma.get(date)
    c = index_by_date.get(date)
    return v is None or c is None or c > v


def index_regime(cfg):
    idx = load_index(cfg)
    closes = [b["close"] for b in idx]
    s = sma(closes, 50)
    return ({b["date"]: b["close"] for b in idx},
            {b["date"]: s[i] for i, b in enumerate(idx) if s[i] is not None})


# --------------------------------------------------------------------------
# Trade simulation shared by backtest and time machine
# --------------------------------------------------------------------------

def simulate_trade(bars, ind, entry_i, setup, cfg, entry_price=None,
                   stop=None, target=None):
    """Simulate one long trade entered at bars[entry_i] open.

    Fills: stop at min(open, stop) on a gap down, target at max(open, target)
    on a gap up; if both are touched on one bar the stop is assumed first.
    No sale is possible before session entry_i + earliest_sell_session (T+2);
    if the stop was breached while locked in, the position is sold at the
    open of the first allowed session."""
    sp = SETUPS[setup] if isinstance(setup, str) else setup
    n = len(bars)
    if entry_i >= n:
        return None
    e = entry_price if entry_price is not None else bars[entry_i]["open"]
    a = ind["atr14"][entry_i - 1] if entry_i > 0 else None
    if stop is None:
        if a is None:
            return None
        stop = e - sp["stop_atr"] * a
    risk = e - stop
    if risk <= 0:
        return None
    if target is None and sp.get("target_r"):
        target = e + sp["target_r"] * risk
    first_sell = entry_i + int(cfg.get("earliest_sell_session", 2))
    last = min(n - 1, entry_i + sp["max_sessions"])
    if first_sell > n - 1:
        return {"open": True}
    for j in range(first_sell, last + 1):
        bj = bars[j]
        if j == first_sell and bj["open"] <= stop:
            return _res(e, bj["open"], "stop", entry_i, j, bars, stop, target)
        if bj["low"] <= stop:
            return _res(e, min(bj["open"], stop), "stop", entry_i, j, bars, stop, target)
        if target is not None and bj["high"] >= target:
            return _res(e, max(bj["open"], target), "target", entry_i, j, bars, stop, target)
        if sp["exit"] == "close_above_sma5":
            s5 = ind["sma5"][j]
            if s5 is not None and bj["close"] > s5:
                return _res(e, bj["close"], "signal", entry_i, j, bars, stop, target)
    if last < entry_i + sp["max_sessions"]:
        return {"open": True}
    return _res(e, bars[last]["close"], "time", entry_i, last, bars, stop, target)


def _res(e, x, why, i, j, bars, stop, target):
    d0 = _dt.date.fromisoformat(bars[i]["date"])
    d1 = _dt.date.fromisoformat(bars[j]["date"])
    return {"entry": e, "exit": x, "reason": why, "entry_i": i, "exit_i": j,
            "entry_date": bars[i]["date"], "exit_date": bars[j]["date"],
            "sessions": j - i, "days": (d1 - d0).days,
            "stop": stop, "target": target,
            "gross_pct": 100.0 * (x / e - 1)}


def net_return_pct(trade, cfg, notional):
    """Net % after fees and CGT for a trade of `notional` rupees.
    Uses adjusted prices; shares are whole lots at the entry price."""
    lot = cfg.get("lot_size", 10)
    shares = max(lot, round_lot(notional / trade["entry"], lot))
    rt = round_trip(shares, trade["entry"], trade["exit"], cfg,
                    holding_days=trade["days"])
    return rt["net_return_pct"]


def locked_upper(bars, i, cfg):
    """True when bar i opened at the upper limit and never traded below it,
    so a buy order would not have filled."""
    if i == 0:
        return False
    pc = bars[i - 1]["close"]
    lim = cfg.get("price_limit_pct", PRICE_LIMIT_PCT) / 100.0
    b = bars[i]
    # pre-Apr-2026 bars had a 10% band; treat either as locked
    return b["low"] >= pc * (1 + min(lim, 0.10) - 0.005) and b["high"] == b["low"]


def fmt_npr(x):
    s = f"{abs(x):,.2f}"
    return ("-" if x < 0 else "") + "Rs " + s


def now_npt():
    return _dt.datetime.now(NPT).strftime("%Y-%m-%d %H:%M NPT")
