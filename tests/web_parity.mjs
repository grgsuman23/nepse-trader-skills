// Runs web/engine.js on vectors written by test_web_parity.py and prints
// the results as JSON for the Python side to compare.
import { readFileSync } from "node:fs";
import * as E from "../web/engine.js";

const v = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = { fees: [], cases: [] };
for (const [n, b, s, d] of v.fees) out.fees.push(E.roundTrip(n, b, s, v.meta.config, d));
for (const c of v.cases) {
  const plan = E.planExit(c.stock, v.meta, c.setup, c.opts);
  const sz = E.sizePlan(plan, v.meta.config, c.holdings);
  const g = E.gate(plan, c.stock, v.meta, c.holdings, v.sectors, sz, c.today);
  const tm = E.bootstrap(c.stock, plan, v.meta.config, { paths: 20000, seed: 3 });
  out.cases.push({ plan, sz, verdict: g.verdict, nblock: g.block.length, tm });
}
console.log(JSON.stringify(out));
