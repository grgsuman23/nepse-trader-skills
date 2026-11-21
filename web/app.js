import * as E from "./engine.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const npr = (x) => (x < 0 ? "−" : "") + "Rs " + fmt(Math.abs(x), 0);
const sgn = (x, d = 2) => (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d);
const cls = (x) => (x > 0 ? "pos" : x < 0 ? "neg" : "");
const lakh = (x) => fmt(x / 1e5, 1);

const S = { meta: null, scan: null, uni: [], bt: null, stocks: {}, sectors: {}, sort: { k: "t20", d: -1 } };

// ---- storage (per browser) ---------------------------------------------
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch { return false; } },
};
const SETTINGS = [
  ["budget_npr", "Trading budget (Rs)", 1000],
  ["max_loss_per_trade_npr", "Max loss per trade (Rs)", 100],
  ["max_position_pct", "Max per stock (% of budget)", 1],
  ["max_sector_pct", "Max per sector (%)", 1],
  ["min_reward_risk", "Min net reward:risk", 0.1],
  ["cash_buffer_pct", "Cash buffer (%)", 1],
  ["investor_type", "Investor type", null],
];
let OVR = store.get("nepse.cfg", {});
let HOLD = store.get("nepse.holdings", []);
const cfg = () => Object.assign({}, S.meta.config, OVR);
const holdings = () => HOLD.map((h) => { const u = S.uni.find((x) => x.s === h.symbol); return { ...h, last_price: u ? u.c : h.avg_cost }; });

// ---- data ---------------------------------------------------------------
async function getJSON(p) { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json(); }
async function stock(sym) {
  if (!S.stocks[sym]) S.stocks[sym] = await getJSON(`data/stocks/${encodeURIComponent(sym)}.json`);
  return S.stocks[sym];
}

// ---- tiny SVG chart -----------------------------------------------------
function chart(el, { dates, series, hlines = [], height = 220 }) {
  const W = Math.max(320, Math.round(el.clientWidth || 760)), H = height, P = { l: 4, r: 62, t: 10, b: 22 };
  const all = series.flatMap((s) => s.y.filter((v) => v != null)).concat(hlines.map((h) => h.y));
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
  const n = dates.length, x = (i) => P.l + (i / (n - 1)) * (W - P.l - P.r), y = (v) => P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b);
  const path = (ys) => ys.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + f * (hi - lo));
  const ticks = [0, Math.floor(n / 2), n - 1];
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="price chart">
    ${grid.map((g) => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(g)}" y2="${y(g)}" stroke="var(--line)"/><text x="${W - P.r + 6}" y="${y(g) + 4}" font-size="11" fill="var(--ink-3)">${fmt(g, g > 999 ? 0 : 1)}</text>`).join("")}
    ${ticks.map((i) => `<text x="${x(i)}" y="${H - 6}" font-size="11" fill="var(--ink-3)" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${dates[i]}</text>`).join("")}
    ${hlines.map((h) => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(h.y)}" y2="${y(h.y)}" stroke="${h.color}" stroke-dasharray="5 4" stroke-width="1.5"/><text x="${P.l + 4}" y="${y(h.y) - 4}" font-size="11" font-weight="700" fill="${h.color}" paint-order="stroke" stroke="var(--card)" stroke-width="3">${esc(h.label)}</text>`).join("")}
    ${series.map((s) => `<polyline points="${path(s.y)}" fill="none" stroke="${s.color}" stroke-width="${s.w || 2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round"/>`).join("")}
  </svg>${series.length > 1 || hlines.length ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : ""}`;
}

// ---- views --------------------------------------------------------------
function header() {
  const m = S.meta, age = E.daysBetween(m.as_of, E.nptToday());
  const t = $("#tag"); t.textContent = age <= 4 ? "LIVE-EOD" : "STALE"; t.classList.toggle("stale", age > 4);
  $("#asof").textContent = `Close of ${m.as_of} · ${m.symbols} stocks · built ${m.generated}`;
  $("#foot").innerHTML = `${esc(m.disclaimer)}<br>Data: Aabishkar2/nepse-data and zeutonx/NEPSE-Data on GitHub. Check a price on NEPSE before ordering. · <a href="https://github.com/grgsuman23/nepse-trader-skills">Source</a>`;
}

function today() {
  const m = S.meta, ix = m.index, n = ix.c.length;
  const liq = S.uni.filter((u) => u.liq);
  const above = liq.filter((u) => u.a50).length;
  const adv = liq.filter((u) => u.chg > 0).length, dec = liq.filter((u) => u.chg < 0).length;
  const chg = n > 1 ? 100 * (ix.c[n - 1] / ix.c[n - 2] - 1) : 0;
  $("#mkt").innerHTML = [
    ["NEPSE index", fmt(ix.c[n - 1]), `<span class="${cls(chg)}">${sgn(chg)}%</span>`],
    ["Liquid stocks", liq.length, `${adv} up · ${dec} down`],
    ["Above 50-day avg", `${Math.round(100 * above / Math.max(liq.length, 1))}%`, "of liquid stocks"],
    ["Setup hits", S.scan.hits.length, `on ${m.as_of}`],
  ].map(([k, v, s]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div><div class="muted">${s}</div></div>`).join("");
  const k = Math.max(0, n - 250);
  chart($("#idx-chart"), { dates: ix.d.slice(k), series: [{ y: ix.c.slice(k), color: "var(--blue)", name: "NEPSE index (1 year)" }], height: 180 });
  const f = $("#hit-filter").value;
  const hits = S.scan.hits.filter((h) => !f || h.setup === f);
  $("#hits").innerHTML = hits.length ? hits.map((h) => {
    const r = h.record, rec = r.n ? `<span class="pill ${r.avg_net_pct > 0 ? "green" : "red"}">own record: ${r.n} past · ${r.win_pct}% won · avg ${sgn(r.avg_net_pct)}%</span>` : `<span class="pill amber">no past signals on this stock</span>`;
    return `<button class="hit" data-sym="${esc(h.symbol)}" data-setup="${esc(h.setup)}">
      <div class="row"><b class="sym">${esc(h.symbol)}</b><span class="pill">${esc(h.setup)}</span><span class="spacer"></span><b>${fmt(h.close)}</b><span class="${cls(h.day_chg_pct)}">${sgn(h.day_chg_pct)}%</span></div>
      <div class="row muted"><span>${esc(h.sector)}</span><span class="spacer"></span><span>stop ${fmt(h.stop)} · ${h.target ? "target " + fmt(h.target) : "exit on SMA5"}</span></div>
      <div>${rec}</div></button>`;
  }).join("") : `<div class="empty">No setups fired on the last close.</div>`;
}

function stocksView() {
  const q = $("#s-q").value.trim().toUpperCase(), sec = $("#s-sec").value, liq = $("#s-liq").value;
  const { k, d } = S.sort;
  const rows = S.uni.filter((u) => (!q || u.s.includes(q)) && (!sec || u.sec === sec) && (!liq || u.liq))
    .sort((a, b) => ((a[k] ?? -1e18) > (b[k] ?? -1e18) ? d : -d));
  const cols = [["s", "Stock", "l"], ["c", "Close"], ["chg", "Chg%"], ["t20", "T/O lakh"], ["rsi14", "RSI14", "hide-sm"], ["h52p", "vs 52w hi"], ["atrp", "ATR%", "hide-sm"]];
  $("#stocks").innerHTML = `<thead><tr>${cols.map(([c, n, l]) => `<th class="sort ${l || ""}" data-k="${c}">${n}${k === c ? (d > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}<th class="l hide-sm">Trend</th></tr></thead><tbody>${rows.map((u) =>
    `<tr class="click" data-sym="${esc(u.s)}"><td><b>${esc(u.s)}</b> ${u.hits.map((h) => `<span class="pill">${esc(h)}</span>`).join("")}<div class="muted">${esc(u.sec)}</div></td><td>${fmt(u.c)}</td><td class="${cls(u.chg)}">${sgn(u.chg)}</td><td>${lakh(u.t20)}</td><td class="hide-sm">${fmt(u.rsi14, 0)}</td><td class="${cls(u.h52p)}">${u.h52p == null ? "–" : sgn(u.h52p, 1) + "%"}</td><td class="hide-sm">${fmt(u.atrp, 1)}</td><td class="l hide-sm">${u.a200 == null ? "" : u.a200 ? '<span class="pill green">above 200d</span>' : '<span class="pill red">below 200d</span>'}</td></tr>`).join("")}</tbody>`;
}

function accuracy() {
  const b = S.bt;
  if (!b) { $("#bt").innerHTML = `<tbody><tr><td class="empty">Backtest not built yet.</td></tr></tbody>`; return; }
  $("#bt-meta").textContent = `${b.symbols} equities · ${b.period[0]} to ${b.last_trade_exit} · split at ${b.split} · net of ${b.costs} on a Rs ${fmt(b.notional_npr, 0)} position.`;
  const verdict = (v) => {
    const A = v.all.signal, L = v.late.signal, e = v.all.edge_pp, se = Math.hypot(A.se_pct || 0, v.all.random.se_pct || 0);
    if (A.avg_net_pct > 0 && L.avg_net_pct > (L.se_pct || 0)) return ["green", "Profitable after costs"];
    if (A.avg_net_pct > 0) return ["amber", "Profitable before 2023, near zero since"];
    if (e > 2 * se && v.early.edge_pp > 0 && v.late.edge_pp > 0) return ["amber", "Beats random entries, but still loses money"];
    return ["red", "No edge: loses money, no better than random"];
  };
  $("#bt").outerHTML = `<div id="bt" class="grid two">${Object.entries(b.setups).map(([s, v]) => {
    const [col, txt] = verdict(v);
    const row = (p, name) => { const st = v[p].signal; return st.trades ? `<tr><td class="l">${name}</td><td>${fmt(st.trades, 0)}</td><td>${fmt(st.win_rate_pct, 0)}%</td><td class="${cls(st.avg_net_pct)}">${sgn(st.avg_net_pct)}%</td><td class="${cls(v[p].edge_pp)}">${sgn(v[p].edge_pp)}</td></tr>` : ""; };
    return `<div class="stat"><div class="row"><b>${esc(s)}</b><span class="pill ${col}">${txt}</span></div><div class="muted">${esc(v.about)}</div>
      <table style="margin-top:6px"><thead><tr><th class="l">Period</th><th>Trades</th><th>Won</th><th>Avg net</th><th>Edge</th></tr></thead><tbody>${row("all", "2016–26")}${row("early", "before " + b.split.slice(0, 4))}${row("late", b.split.slice(0, 4) + " on")}</tbody></table>
      <div class="muted">Random entries: ${sgn(v.all.random.avg_net_pct)}% · SE ±${fmt(v.all.signal.se_pct)}</div></div>`;
  }).join("")}</div>`;
  const years = [...new Set(Object.values(b.setups).flatMap((v) => Object.keys(v.by_year)))].sort();
  $("#bt-year").innerHTML = `<thead><tr><th class="l">Setup</th>${years.map((y) => `<th>${y}</th>`).join("")}</tr></thead><tbody>${Object.entries(b.setups).map(([s, v]) =>
    `<tr><td>${esc(s)}</td>${years.map((y) => { const r = v.by_year[y]; return r ? `<td class="${cls(r.avg)}" title="${r.n} trades, ${r.win}% won">${sgn(r.avg, 1)}</td>` : "<td>–</td>"; }).join("")}</tr>`).join("")}</tbody>`;
  const c = S.meta.calibration;
  $("#calib").innerHTML = `<div class="stats"><div class="stat"><div class="k">Profit after costs: predicted</div><div class="v">${c.p_profit_pred}%</div><div class="muted">actual ${c.p_profit_actual}%</div></div><div class="stat"><div class="k">Target hit: predicted</div><div class="v">${c.p_target_pred}%</div><div class="muted">actual ${c.p_target_actual}%</div></div></div><p class="muted">Tested on 1,500 past signals using only data before each signal. ${esc(c.note)}</p>`;
}

function fees() {
  const c = cfg(), n = Number($("#f-n").value), b = Number($("#f-b").value), s = Number($("#f-s").value), d = Number($("#f-d").value);
  if (!(n > 0 && b > 0 && s > 0)) { $("#f-out").innerHTML = ""; return; }
  const r = E.roundTrip(n, b, s, c, d), be = E.breakEven(n, b, c);
  const side = (x, nm) => `<tr><td>${nm}</td><td>${npr(x.value)}</td><td>${x.commission_rate_pct}% · ${npr(x.commission)}</td><td>${fmt(x.sebon)}</td><td>${fmt(x.dp, 0)}</td><td><b>${npr(x.total)}</b></td></tr>`;
  $("#f-out").innerHTML = `<div class="scroll"><table><thead><tr><th class="l">Side</th><th>Value</th><th>Commission</th><th>SEBON</th><th>DP</th><th>Charges</th></tr></thead><tbody>${side(r.buy, "Buy")}${side(r.sell, "Sell")}</tbody></table></div>
  <div class="stats" style="margin-top:12px"><div class="stat"><div class="k">CGT ${r.cgt_rate_pct}%</div><div class="v">${npr(r.cgt)}</div></div><div class="stat"><div class="k">Net profit</div><div class="v ${cls(r.net_pnl)}">${npr(r.net_pnl)}</div><div class="muted">${sgn(r.net_return_pct)}%</div></div><div class="stat"><div class="k">All charges + tax</div><div class="v">${npr(r.total_charges)}</div></div><div class="stat"><div class="k">Break-even sell</div><div class="v">${fmt(be)}</div><div class="muted">${sgn(100 * (be / b - 1))}% above buy</div></div></div>
  ${n % c.lot_size ? `<p class="note" style="margin-top:10px">${n} isn't a multiple of ${c.lot_size}: regular-session orders must be in lots of ${c.lot_size}.</p>` : ""}`;
  const f = c.fees;
  $("#f-rates").innerHTML = `<table><tbody>${f.commission_slabs.map(([lim, r], i) => `<tr><td>${i ? "Above Rs " + fmt(f.commission_slabs[i - 1][0], 0) : "Up to"} ${lim ? (i ? "to " : "") + "Rs " + fmt(lim, 0) : ""}</td><td>${r}%</td></tr>`).join("")}<tr><td>Minimum commission</td><td>Rs ${f.min_commission_npr}</td></tr><tr><td>SEBON fee</td><td>${f.sebon_fee_pct}%</td></tr><tr><td>DP charge (per scrip per day, each side)</td><td>Rs ${f.dp_charge_npr}</td></tr><tr><td>CGT, individual, held ≤365 days</td><td>${f.cgt_short_pct}%</td></tr><tr><td>CGT, individual, held &gt;365 days</td><td>${f.cgt_long_pct}%</td></tr><tr><td>Daily price limit</td><td>±${c.price_limit_pct}%</td></tr></tbody></table><p class="muted">Rates verified 21 Nov 2026. The slab rate applies to the whole trade value, not just the part above each threshold.</p>`;
}

// ---- plan ---------------------------------------------------------------
let planTimer = null;
const schedulePlan = () => { clearTimeout(planTimer); planTimer = setTimeout(plan, 150); };

async function plan() {
  const sym = $("#p-sym").value.trim().toUpperCase();
  const err = $("#p-error"), out = $("#p-out");
  err.style.display = "none";
  if (!sym) { out.style.display = "none"; return; }
  if (!S.uni.find((u) => u.s === sym)) { err.textContent = `${sym} isn't in the equity list.`; err.style.display = "block"; out.style.display = "none"; return; }
  const st = await stock(sym), c = cfg(), meta = { ...S.meta, config: c };
  const setup = $("#p-setup").value, stopR = $("#p-stop").value, tR = $("#p-tgt").value;
  const opts = { entry: $("#p-entry").value || null };
  if (stopR === "pct" || stopR === "price") opts.stop = `${stopR}:${$("#p-stopv").value}`; else opts.stop = stopR;
  if (tR) opts.target = `${tR}:${$("#p-tgtv").value}`;
  let p;
  try {
    if ((stopR === "pct" || stopR === "price") && !$("#p-stopv").value) throw new Error("Enter the stop % or price.");
    if (tR && !$("#p-tgtv").value) throw new Error("Enter the target R or price.");
    p = E.planExit(st, meta, setup, opts);
  } catch (e) { err.textContent = e.message; err.style.display = "block"; out.style.display = "none"; return; }
  out.style.display = "block";
  $("#p-title").textContent = `${sym} · ${setup}`;
  $("#p-sector").textContent = st.sector || "—";
  const k = Math.max(0, st.c.length - 120);
  const hl = [{ y: p.entry, color: "var(--blue)", label: "entry " + fmt(p.entry) }, { y: p.stop, color: "var(--red)", label: "stop " + fmt(p.stop) }];
  if (p.target) hl.push({ y: p.target, color: "var(--green)", label: "target " + fmt(p.target) });
  chart($("#p-chart"), { dates: st.d.slice(k), series: [{ y: st.c.slice(k), color: "var(--ink)", name: "Close", w: 2 }, { y: st.sma50.slice(k), color: "var(--blue)", name: "50-day avg", w: 1.5, dash: "4 3" }], hlines: hl });
  $("#p-levels").innerHTML = [["Entry", fmt(p.entry), `last close ${fmt(p.last_close)}`], ["Stop", fmt(p.stop), `−${p.risk_pct}% · ${p.stop_rule}`], ["Target", p.target ? fmt(p.target) : "SMA5 exit", p.target_rule], ["Time stop", `${p.max_sessions} sessions`, `R:R ${p.reward_risk ?? "n/a"}`], ["Break-even", fmt(p.break_even), "fees both sides"]]
    .map(([a, v, s]) => `<div class="stat"><div class="k">${a}</div><div class="v">${v}</div><div class="muted">${esc(s)}</div></div>`).join("");
  $("#p-warn").innerHTML = p.warnings.map((w) => `<li class="w">${esc(w)}</li>`).join("");

  const hs = holdings(), sz = E.sizePlan(p, c, hs);
  if (!sz.shares) $("#p-size").innerHTML = `<div class="verdict block">No trade</div><p>${esc(sz.reason)}</p>`;
  else {
    const b = sz.buy_charges;
    $("#p-size").innerHTML = `<div class="stats"><div class="stat"><div class="k">Buy</div><div class="v">${sz.shares} shares</div><div class="muted">${sz.position_pct}% of budget</div></div><div class="stat"><div class="k">Cost incl. charges</div><div class="v">${npr(sz.cost_with_fees)}</div></div><div class="stat"><div class="k">If stopped</div><div class="v neg">${npr(sz.loss_at_stop)}</div><div class="muted">${sgn(sz.loss_at_stop_pct)}%</div></div>${sz.gain_at_target !== undefined ? `<div class="stat"><div class="k">If target</div><div class="v pos">${npr(sz.gain_at_target)}</div><div class="muted">${sgn(sz.gain_at_target_pct)}% · net R:R ${sz.net_reward_risk}</div></div>` : ""}</div>
    <p class="muted">Caps in shares: risk ${sz.caps.risk} · position ${sz.caps.position} · cash ${sz.caps.cash}. The binding cap is <b>${sz.binding_cap}</b>. Buy charges: commission ${b.commission_rate_pct}% ${npr(b.commission)}, SEBON ${fmt(b.sebon)}, DP ${b.dp}.${sz.cgt_at_target !== undefined ? ` CGT at target: ${npr(sz.cgt_at_target)}.` : ""}</p>`;
  }
  const g = E.gate(p, st, meta, hs, S.sectors, sz);
  $("#p-gate").innerHTML = `<div class="verdict ${g.verdict === "PASS" ? "pass" : "block"}">${g.verdict === "PASS" ? "✓ PASS" : "✕ BLOCK"}</div><ul class="checks">${g.block.map((x) => `<li class="b">${esc(x)}</li>`).join("")}${g.warn.map((x) => `<li class="w">${esc(x)}</li>`).join("")}${g.ok.map((x) => `<li class="o">${esc(x)}</li>`).join("")}</ul>`;

  const tm = E.bootstrap(st, p, c, { paths: 10000 });
  const rec = st.records?.[setup];
  const seg = [["p_target", "var(--green)", "Target"], ["p_signal_exit", "var(--blue)", "SMA5 exit"], ["p_time", "var(--ink-3)", "Time-out"], ["p_stop", "var(--red)", "Stop"]].filter(([key]) => tm[key] > 0);
  $("#p-tm").innerHTML = `<div class="bar">${seg.map(([key, col]) => `<span style="width:${tm[key]}%;background:${col}"></span>`).join("")}</div><div class="legend">${seg.map(([key, col, n]) => `<span><i style="background:${col}"></i>${n} ${tm[key]}%</span>`).join("")}</div>
  <div class="stats" style="margin-top:12px"><div class="stat"><div class="k">Profit after costs</div><div class="v">${tm.p_profit_after_costs}%</div><div class="muted">of ${fmt(tm.paths, 0)} paths</div></div><div class="stat"><div class="k">Expected net</div><div class="v ${cls(tm.expected_net_pct)}">${sgn(tm.expected_net_pct)}%</div><div class="muted">5–95%: ${sgn(tm.p5_net_pct)} to ${sgn(tm.p95_net_pct)}</div></div><div class="stat"><div class="k">This stock, past ${esc(setup)}</div><div class="v">${rec?.n ? rec.win_pct + "% won" : "–"}</div><div class="muted">${rec?.n ? `${rec.n} trades · avg ${sgn(rec.avg_net_pct)}%` : "no past signals"}</div></div></div>
  <p class="muted">Paths are built from this stock's last ${tm.lookback_sessions} real sessions, with its trend removed, the ±${c.price_limit_pct}% limit applied and no sale before T+${c.earliest_sell_session}. Treat the result as typical odds for this kind of trade: tests showed it doesn't rank individual trades.</p>`;

  $("#p-ticket").innerHTML = g.verdict === "PASS" && sz.shares
    ? `<pre class="ticket" id="tk">${esc(E.ticketText(p, g, c))}</pre><div class="row" style="margin-top:8px"><button class="btn small" id="copy">Copy ticket</button><span class="muted">Type it into TMS yourself. Nothing here places orders.</span></div>`
    : `<p class="muted">No ticket while the risk gate blocks this trade. Change the plan or your limits instead of overriding the gate.</p>`;
  $("#copy")?.addEventListener("click", () => navigator.clipboard?.writeText($("#tk").textContent).then(() => ($("#copy").textContent = "Copied ✓")));
}

function openPlan(sym, setup) {
  $("#p-sym").value = sym;
  if (setup) $("#p-setup").value = setup;
  show("plan"); plan();
}

// ---- settings -----------------------------------------------------------
function settingsView() {
  const c = cfg();
  $("#set-form").innerHTML = SETTINGS.map(([k, n, step]) => step === null
    ? `<div><label for="set-${k}">${n}</label><select id="set-${k}"><option value="individual"${c[k] === "individual" ? " selected" : ""}>Resident individual</option><option value="institution"${c[k] !== "individual" ? " selected" : ""}>Institution (10% CGT; verify)</option></select></div>`
    : `<div><label for="set-${k}">${n}</label><input id="set-${k}" type="number" step="${step}" value="${c[k]}" inputmode="decimal"></div>`).join("");
  const hs = holdings();
  $("#h-table").innerHTML = hs.length ? `<thead><tr><th class="l">Stock</th><th>Qty</th><th>Avg cost</th><th>Last</th><th>Value</th><th></th></tr></thead><tbody>${hs.map((h, i) => `<tr><td>${esc(h.symbol)}<div class="muted">${esc(S.sectors[h.symbol] || "")}</div></td><td>${h.qty}</td><td>${fmt(h.avg_cost)}</td><td>${fmt(h.last_price)}</td><td>${npr(h.qty * h.last_price)}</td><td><button class="btn ghost small" data-del="${i}">Remove</button></td></tr>`).join("")}</tbody>` : `<tbody><tr><td class="empty">No holdings added.</td></tr></tbody>`;
}

// ---- wiring -------------------------------------------------------------
function show(v) {
  document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.view === v));
  document.querySelectorAll("section.view").forEach((s) => s.classList.toggle("on", s.id === "v-" + v));
  if (location.hash !== "#" + v) history.replaceState(null, "", "#" + v);
  window.scrollTo(0, 0);
}

function wire() {
  document.querySelectorAll("nav.tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  document.querySelectorAll("[data-goto]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); show(a.dataset.goto); }));
  $("#hit-filter").addEventListener("change", today);
  $("#hits").addEventListener("click", (e) => { const r = e.target.closest("[data-sym]"); if (r) openPlan(r.dataset.sym, r.dataset.setup); });
  $("#stocks").addEventListener("click", (e) => {
    const th = e.target.closest("th[data-k]");
    if (th) { const k = th.dataset.k; S.sort = { k, d: S.sort.k === k ? -S.sort.d : k === "s" ? 1 : -1 }; return stocksView(); }
    const r = e.target.closest("tr[data-sym]"); if (r) openPlan(r.dataset.sym, (S.uni.find((u) => u.s === r.dataset.sym)?.hits || [])[0]);
  });
  ["#s-q", "#s-sec", "#s-liq"].forEach((id) => $(id).addEventListener("input", stocksView));
  ["#p-sym", "#p-setup", "#p-entry", "#p-stopv", "#p-tgtv"].forEach((id) => $(id).addEventListener("input", schedulePlan));
  $("#p-stop").addEventListener("change", () => { $("#p-stopv").disabled = !["pct", "price"].includes($("#p-stop").value); schedulePlan(); });
  $("#p-tgt").addEventListener("change", () => { $("#p-tgtv").disabled = !$("#p-tgt").value; schedulePlan(); });
  ["#f-n", "#f-b", "#f-s", "#f-d"].forEach((id) => $(id).addEventListener("input", fees));
  $("#set-save").addEventListener("click", () => {
    const o = {};
    for (const [k, , step] of SETTINGS) { const v = $("#set-" + k).value; o[k] = step === null ? v : Number(v); }
    OVR = o; $("#set-msg").textContent = store.set("nepse.cfg", o) ? "Saved." : "Couldn't save in this browser; using for this visit.";
    fees();
  });
  $("#set-reset").addEventListener("click", () => { OVR = {}; store.set("nepse.cfg", {}); settingsView(); fees(); $("#set-msg").textContent = "Defaults restored."; });
  $("#h-add").addEventListener("click", () => {
    const s = $("#h-sym").value.trim().toUpperCase(), q = Number($("#h-qty").value), c = Number($("#h-cost").value);
    if (!s || !(q > 0) || !(c > 0)) return;
    HOLD = HOLD.filter((h) => h.symbol !== s).concat([{ symbol: s, qty: q, avg_cost: c }]);
    store.set("nepse.holdings", HOLD); ["#h-sym", "#h-qty", "#h-cost"].forEach((id) => ($(id).value = "")); settingsView();
  });
  $("#h-table").addEventListener("click", (e) => { const b = e.target.closest("[data-del]"); if (b) { HOLD.splice(Number(b.dataset.del), 1); store.set("nepse.holdings", HOLD); settingsView(); } });
}

async function init() {
  try {
    [S.meta, S.scan, S.uni] = await Promise.all([getJSON("data/meta.json"), getJSON("data/scan.json"), getJSON("data/universe.json")]);
  } catch (e) {
    $("#asof").textContent = "Couldn't load data: " + e.message; $("#tag").textContent = "ERROR"; $("#tag").classList.add("stale"); return;
  }
  S.sectors = Object.fromEntries(S.uni.map((u) => [u.s, u.sec]));
  const setups = Object.keys(S.meta.setups);
  $("#p-setup").innerHTML = setups.map((s) => `<option value="${s}">${s} — ${esc(S.meta.setups[s].about)}</option>`).join("");
  $("#hit-filter").innerHTML += setups.map((s) => `<option value="${s}">${s}</option>`).join("");
  $("#sym-list").innerHTML = S.uni.map((u) => `<option value="${esc(u.s)}">`).join("");
  $("#s-sec").innerHTML += S.meta.sectors.map((s) => `<option>${esc(s)}</option>`).join("");
  header(); wire(); today(); stocksView(); fees(); settingsView();
  getJSON("data/backtest.json").then((b) => { S.bt = b; accuracy(); }).catch(() => accuracy());
  const route = () => { const v = location.hash.slice(1); if (["today", "plan", "stocks", "accuracy", "fees", "settings"].includes(v)) show(v); };
  window.addEventListener("hashchange", route);
  route();
}
init();
