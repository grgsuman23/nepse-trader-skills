// NEPSE trader engine for the browser - a line-by-line port of
// lib/nepse_common.py (fees, CGT, lots), nepse-exit, nepse-budget,
// nepse-risk and nepse-timemachine. tests/test_web_parity.py checks
// every function here against the Python results.

export const round2 = (x) => Math.round((x + Number.EPSILON) * 100) / 100;
export const roundLot = (n, lot = 10) => Math.floor(n / lot) * lot;

export function commissionRatePct(value, fees) {
  for (const [limit, rate] of fees.commission_slabs) {
    if (limit === null || value <= limit) return rate;
  }
  return fees.commission_slabs[fees.commission_slabs.length - 1][1];
}

export function sideCosts(value, fees, side) {
  if (value <= 0) return { value: 0, commission: 0, sebon: 0, dp: 0, total: 0, commission_rate_pct: 0 };
  const rate = commissionRatePct(value, fees);
  const comm = round2(Math.max(value * rate / 100, fees.min_commission_npr));
  const sebon = round2(value * fees.sebon_fee_pct / 100);
  const dpOn = side === "buy" ? fees.dp_on_buy : fees.dp_on_sell;
  const dp = dpOn ? fees.dp_charge_npr : 0;
  return { value: round2(value), commission: comm, sebon, dp, total: round2(comm + sebon + dp), commission_rate_pct: rate };
}

export function cgtRatePct(cfg, holdingDays) {
  const f = cfg.fees;
  if ((cfg.investor_type || "individual") !== "individual") return f.cgt_institution_pct;
  return holdingDays > 365 ? f.cgt_long_pct : f.cgt_short_pct;
}

export function roundTrip(shares, buyPrice, sellPrice, cfg, holdingDays = 30) {
  const buy = sideCosts(shares * buyPrice, cfg.fees, "buy");
  const sell = sideCosts(shares * sellPrice, cfg.fees, "sell");
  const costBasis = buy.value + buy.total;
  const pre = sell.value - sell.total;
  const gain = pre - costBasis;
  const rate = cgtRatePct(cfg, holdingDays);
  const cgt = gain > 0 ? round2(gain * rate / 100) : 0;
  const net = round2(pre - cgt);
  const pnl = round2(net - costBasis);
  return {
    shares, buy, sell, cost_basis: round2(costBasis), cgt_rate_pct: rate, cgt,
    net_proceeds: net, net_pnl: pnl,
    net_return_pct: costBasis ? Math.round(1e6 * pnl / costBasis) / 1e4 : 0,
    total_charges: round2(buy.total + sell.total + cgt),
  };
}

export function breakEven(shares, buyPrice, cfg) {
  let lo = buyPrice, hi = buyPrice * 1.2;
  for (let k = 0; k < 60; k++) {
    const mid = (lo + hi) / 2;
    if (roundTrip(shares, buyPrice, mid, cfg).net_pnl >= 0) hi = mid; else lo = mid;
  }
  return round2(hi);
}

// ---- exit plan (nepse-exit) --------------------------------------------
export function planExit(stock, meta, setup, opts = {}) {
  const cfg = meta.config, sp = meta.setups[setup];
  const i = stock.c.length - 1;
  const e = opts.entry ? Number(opts.entry) : stock.c[i];
  const atr = stock.atr[i];
  let stop, how;
  const ss = opts.stop || "atr";
  if (ss === "atr") { stop = e - sp.stop_atr * atr; how = `${sp.stop_atr} x ATR(14) ${atr.toFixed(2)}`; }
  else if (ss === "swing") { const lo = Math.min(...stock.l.slice(-10)); stop = lo * 0.995; how = `0.5% under 10-session low ${lo.toFixed(2)}`; }
  else if (ss.startsWith("pct:")) { const p = Number(ss.slice(4)); stop = e * (1 - p / 100); how = `${p}% below entry`; }
  else if (ss.startsWith("price:")) { stop = Number(ss.slice(6)); how = "fixed price"; }
  else throw new Error("bad stop");
  const risk = e - stop;
  if (!(risk > 0)) throw new Error(`Stop ${stop.toFixed(2)} is not below entry ${e.toFixed(2)}`);
  const tspec = opts.target || (sp.target_r ? `r:${sp.target_r}` : null);
  let target = null, thow = "exit on close above 5-day average (mean reversion)";
  if (tspec && tspec.startsWith("r:")) { const r = Number(tspec.slice(2)); target = e + r * risk; thow = `${r}R`; }
  else if (tspec && tspec.startsWith("price:")) { target = Number(tspec.slice(6)); thow = "fixed price"; }
  const lim = cfg.price_limit_pct;
  const riskPct = 100 * risk / e;
  const warnings = [];
  if (riskPct > lim) warnings.push(`Stop is ${riskPct.toFixed(1)}% away, wider than the ${lim}% daily price limit: it can take 2+ sessions to reach, and a stock locked at the lower limit cannot be sold at all.`);
  if (riskPct < 1) warnings.push("Stop is under 1% away - normal daily noise will hit it.");
  if (atr && risk < 0.75 * atr) warnings.push(`Stop is inside 0.75 x ATR (${atr.toFixed(2)}); expect it to be hit by noise.`);
  warnings.push(`T+2: you cannot sell for ${cfg.earliest_sell_session} sessions after buying. If the stock falls through the stop before then, the real exit is the open of the first session you can sell.`);
  if (target && target > e * (1 + lim / 100) ** 2) warnings.push("Target is more than two full limit-up days away.");
  return {
    symbol: stock.symbol, setup, as_of: stock.d[i], last_close: round2(stock.c[i]), entry: round2(e),
    stop: round2(stop), stop_rule: how, target: target ? round2(target) : null, target_rule: thow,
    exit_rule: opts.target ? "bracket" : sp.exit, max_sessions: sp.max_sessions,
    risk_per_share: round2(risk), risk_pct: round2(riskPct),
    reward_risk: target ? round2((target - e) / risk) : null,
    break_even: breakEven(100, e, cfg), atr14: round2(atr), warnings,
  };
}

// ---- sizing (nepse-budget) ---------------------------------------------
export function invested(holdings) {
  return (holdings || []).reduce((s, h) => s + h.qty * (h.last_price ?? h.avg_cost), 0);
}

export function sizePlan(plan, cfg, holdings, budget) {
  budget = Number(budget || cfg.budget_npr);
  const lot = cfg.lot_size, e = plan.entry, stop = plan.stop, tgt = plan.target;
  const cash = budget * (1 - cfg.cash_buffer_pct / 100) - invested(holdings);
  const posCap = budget * cfg.max_position_pct / 100;
  const lossAt = (n) => -roundTrip(n, e, stop, cfg, 10).net_pnl;
  let n = roundLot(cfg.max_loss_per_trade_npr / (e - stop), lot);
  while (n > 0 && lossAt(n) > cfg.max_loss_per_trade_npr) n -= lot;
  const caps = { risk: n, position: roundLot(posCap / (e * 1.004), lot), cash: roundLot(Math.max(cash, 0) / (e * 1.004), lot) };
  const shares = Math.max(0, Math.min(caps.risk, caps.position, caps.cash));
  const binding = Object.keys(caps).reduce((a, b) => (caps[b] < caps[a] ? b : a));
  const out = { symbol: plan.symbol, shares, binding_cap: binding, caps, budget, cash_available: round2(cash) };
  if (!shares) { out.reason = `Even ${lot} shares breaks the ${binding} cap.`; return out; }
  const buy = sideCosts(shares * e, cfg.fees, "buy");
  const st = roundTrip(shares, e, stop, cfg, 10);
  Object.assign(out, {
    cost_with_fees: round2(buy.value + buy.total), buy_charges: buy,
    position_pct: Math.round(1000 * shares * e / budget) / 10,
    loss_at_stop: st.net_pnl, loss_at_stop_pct: st.net_return_pct, break_even: breakEven(shares, e, cfg),
  });
  if (tgt) {
    const tg = roundTrip(shares, e, tgt, cfg, 30);
    Object.assign(out, {
      gain_at_target: tg.net_pnl, gain_at_target_pct: tg.net_return_pct, cgt_at_target: tg.cgt,
      net_reward_risk: st.net_pnl < 0 ? round2(tg.net_pnl / -st.net_pnl) : null,
    });
  }
  return out;
}

// ---- risk gate (nepse-risk) ---------------------------------------------
const npr = (x) => (x < 0 ? "-" : "") + "Rs " + Math.abs(x).toLocaleString("en-IN", { maximumFractionDigits: 0 });

export function daysBetween(a, b) {
  return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 864e5);
}

export function nptToday() {
  const d = new Date(Date.now() + (5 * 60 + 45) * 6e4);
  return d.toISOString().slice(0, 10);
}

export function gate(plan, stock, meta, holdings, sectors, sizing, today) {
  const cfg = meta.config;
  const i = stock.c.length - 1;
  const sector = stock.sector || "Unknown";
  const sz = sizing || sizePlan(plan, cfg, holdings);
  const block = [], warn = [], ok = [];
  const lim = cfg.price_limit_pct;
  today = today || nptToday();
  const age = daysBetween(stock.d[i], today);
  (age > 4 ? block : ok).push(`Data ${age} days old (last bar ${stock.d[i]})`);
  const t = stock.t.slice(-20);
  const t20 = t.length === 20 ? t.reduce((a, b) => a + b, 0) / 20 : 0;
  const posVal = (sz.shares || 0) * plan.entry;
  if (t20 < cfg.min_avg_turnover_npr) block.push(`Thin: 20-day avg turnover ${npr(t20)} < ${npr(cfg.min_avg_turnover_npr)}`);
  else if (posVal > t20 * cfg.max_pct_of_turnover / 100) block.push(`Position ${npr(posVal)} is over ${cfg.max_pct_of_turnover}% of daily turnover ${npr(t20)}; hard to exit`);
  else ok.push(`Liquidity fine: avg turnover ${npr(t20)}/day`);
  const chg = 100 * (stock.c[i] / stock.c[i - 1] - 1);
  if (chg >= lim - 1.5) block.push(`Up ${chg.toFixed(1)}% today, at/near the +${lim}% limit: chasing a limit-up stock; tomorrow's open is unknowable`);
  else if (chg <= -(lim - 1.5)) block.push(`Down ${chg.toFixed(1)}% today, near the lower limit: possible lock, no buyers to exit into`);
  else ok.push(`Day change ${chg >= 0 ? "+" : ""}${chg.toFixed(1)}% (limit +/-${lim}%)`);
  if (plan.risk_pct > lim) warn.push(`Stop ${plan.risk_pct}% away is beyond one day's ${lim}% limit`);
  if (!sz.shares) block.push("Sizing gives 0 shares: " + (sz.reason || ""));
  else {
    if (-sz.loss_at_stop > cfg.max_loss_per_trade_npr + 1) block.push(`Loss at stop ${npr(-sz.loss_at_stop)} > cap ${npr(cfg.max_loss_per_trade_npr)}`);
    else ok.push(`Loss at stop ${npr(-sz.loss_at_stop)} within cap`);
    const rr = sz.net_reward_risk;
    if (rr !== undefined && rr !== null) (rr < cfg.min_reward_risk ? block : ok).push(`Net reward:risk ${rr} (min ${cfg.min_reward_risk}) after fees & CGT`);
    else warn.push("No fixed target (mean-reversion exit): reward:risk not checkable");
    if (sz.position_pct > cfg.max_position_pct + 0.01) block.push(`Position ${sz.position_pct}% > ${cfg.max_position_pct}% cap`);
  }
  const hs = holdings || [];
  const secVal = hs.filter((h) => sectors[h.symbol.toUpperCase()] === sector)
    .reduce((s, h) => s + h.qty * (h.last_price ?? h.avg_cost), 0) + posVal;
  const secPct = 100 * secVal / cfg.budget_npr;
  (secPct > cfg.max_sector_pct ? block : ok).push(`${sector} exposure would be ${secPct.toFixed(1)}% (cap ${cfg.max_sector_pct}%)`);
  if (hs.some((h) => h.symbol.toUpperCase() === plan.symbol)) warn.push(`You already hold ${plan.symbol}: this adds to it`);
  const rec = meta.record[plan.setup];
  if (rec && rec.avg_net_pct <= 0) warn.push(`Setup '${plan.setup}' averaged ${rec.avg_net_pct > 0 ? "+" : ""}${rec.avg_net_pct}% net per trade across NEPSE in the 2016-26 backtest: it has lost money after costs`);
  const wd = new Date(today + "T00:00:00Z").getUTCDay();
  if (wd === 5 || wd === 6) warn.push("NEPSE is closed Friday and Saturday: order goes in Sunday 11:00");
  warn.push("Check for an upcoming book closure / AGM: the price resets after it");
  return { symbol: plan.symbol, verdict: block.length ? "BLOCK" : "PASS", block, warn, ok, sizing: sz };
}

// ---- time machine (nepse-timemachine) -----------------------------------
export function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

export function relBars(stock, lookback = 250) {
  const n = stock.c.length, start = Math.max(1, n - lookback);
  const rel = [];
  for (let k = start; k < n; k++) {
    const pc = stock.c[k - 1];
    rel.push([stock.o[k] / pc, stock.h[k] / pc, stock.l[k] / pc, stock.c[k] / pc]);
  }
  return rel;
}

export function bootstrap(stock, plan, cfg, { paths = 10000, lookback = 250, seed = 11, demean = true, rel = null } = {}) {
  const lim = cfg.price_limit_pct / 100;
  rel = rel || relBars(stock, lookback);
  if (rel.length < 60) throw new Error("Need at least 60 sessions of history");
  if (demean) {
    const m = Math.exp(rel.reduce((s, r) => s + Math.log(r[3]), 0) / rel.length);
    rel = rel.map(([o, h, l, c]) => [o / m, h / m, l / m, c / m]);
  }
  const R = rng(seed), cap = (x) => Math.min(Math.max(x, 1 - lim), 1 + lim);
  const e = plan.entry, stop = plan.stop, tgt = plan.target;
  const nMax = plan.max_sessions, first = cfg.earliest_sell_session, sma5 = plan.exit_rule === "close_above_sma5";
  const seedCloses = stock.c.slice(-4);
  const res = { target: 0, stop: 0, time: 0, signal: 0 }, exits = [];
  for (let p = 0; p < paths; p++) {
    let pc = e; const closes = seedCloses.slice(); let out = null;
    for (let j = 0; j <= nMax; j++) {
      let [o, h, l, c] = rel[Math.floor(R() * rel.length)];
      if (j === 0) { h = cap(h / o); l = cap(l / o); c = cap(c / o); o = 1; }
      o = pc * cap(o); h = pc * cap(h); l = pc * cap(l); c = pc * cap(c);
      closes.push(c);
      if (j >= first) {
        if (j === first && o <= stop) { out = ["stop", o]; break; }
        if (l <= stop) { out = ["stop", Math.min(o, stop)]; break; }
        if (tgt && h >= tgt) { out = ["target", Math.max(o, tgt)]; break; }
        if (sma5) { const s5 = closes.slice(-5).reduce((a, b) => a + b, 0) / 5; if (c > s5) { out = ["signal", c]; break; } }
      }
      pc = c;
    }
    if (!out) out = ["time", pc];
    res[out[0]]++; exits.push(out[1]);
  }
  const shares = Math.max(cfg.lot_size, roundLot(100000 / e, cfg.lot_size));
  const nets = exits.map((x) => roundTrip(shares, e, x, cfg, 15).net_return_pct).sort((a, b) => a - b);
  const pct = (x) => Math.round(1000 * x / paths) / 10;
  return {
    paths, lookback_sessions: rel.length, p_target: pct(res.target), p_stop: pct(res.stop),
    p_time: pct(res.time), p_signal_exit: pct(res.signal),
    p_profit_after_costs: pct(nets.filter((x) => x > 0).length),
    expected_net_pct: round2(nets.reduce((a, b) => a + b, 0) / paths),
    p5_net_pct: round2(nets[Math.floor(0.05 * paths)]), p95_net_pct: round2(nets[Math.floor(0.95 * paths)]),
  };
}

export function ticketText(plan, g, cfg) {
  const sz = g.sizing, lim = cfg.price_limit_pct;
  return [
    "TMS BUY TICKET - enter manually",
    `Symbol       : ${plan.symbol}`,
    "Side         : BUY",
    `Quantity     : ${sz.shares} (multiple of ${cfg.lot_size})`,
    "Order type   : LIMIT, day order",
    `Limit price  : ${plan.entry.toFixed(2)} (last close ${plan.last_close})`,
    `Est. cost    : ${npr(sz.cost_with_fees)} incl. charges`,
    `Stop         : ${plan.stop.toFixed(2)}  -> sell if broken`,
    `Target       : ${plan.target ?? "close > 5-day avg"}`,
    `Time stop    : sell after ${plan.max_sessions} sessions if neither hit`,
    `Earliest sale: T+${cfg.earliest_sell_session} (shares must reach your demat)`,
    `Max loss     : ${npr(-sz.loss_at_stop)} after fees`,
    `Risk gate    : ${g.verdict}`,
    `Note: TMS rejects prices outside +/-${lim}% of previous close.`,
  ].join("\n");
}
