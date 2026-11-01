// Relational-invariant property verifier with delta-debugging shrink.
// Deterministic (seeded), no eval, no LLM. Catches a whole BUG CLASS, not examples.
//
// Usage: tsx property-verify.mjs --module <abs path.ts> --contract <abs path.json>
// Exit: 0 = VERIFIED (all invariants hold) · 1 = VIOLATED (counterexample found)
import { readFileSync } from 'node:fs';
import { resolve as resolvePath } from 'node:path';
import { pathToFileURL } from 'node:url';

const argv = process.argv.slice(2);
const opt = (name) => { const i = argv.indexOf('--' + name); return i >= 0 ? argv[i + 1] : undefined; };
const modulePath = opt('module');
const contractPath = opt('contract');
if (!modulePath || !contractPath) {
  console.error('usage: property-verify --module <path.ts> --contract <path.json>');
  process.exit(2);
}
const spec = JSON.parse(readFileSync(resolvePath(contractPath), 'utf8'));
const mod = await import(pathToFileURL(resolvePath(modulePath)).href);
const fn = mod[spec.export];
if (typeof fn !== 'function') { console.error(`export ${spec.export} is not a function`); process.exit(2); }

// Seeded PRNG (mulberry32) -> fully reproducible trials.
let _s = (spec.seed ?? 1234567) >>> 0;
const rnd = () => { _s |= 0; _s = (_s + 0x6D2B79F5) | 0; let t = Math.imul(_s ^ (_s >>> 15), 1 | _s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const randInt = (min, max) => min + Math.floor(rnd() * (max - min + 1));

const sum = (r) => (Array.isArray(r) ? r.reduce((x, y) => x + y, 0) : NaN);

// Named invariant predicates: (args, result, fn) -> {ok, detail}. No arbitrary code.
const INVARIANTS = {
  conservation: (a, r) => ({ ok: Array.isArray(r) && sum(r) === a[0], detail: `sum(parts)=${sum(r)} must equal total=${a[0]} (no penny created or destroyed)` }),
  length: (a, r) => ({ ok: Array.isArray(r) && r.length === a[1], detail: `must return exactly parties=${a[1]} parts, got ${Array.isArray(r) ? r.length : 'non-array'}` }),
  non_negative: (a, r) => ({ ok: Array.isArray(r) && r.every((x) => Number.isInteger(x) && x >= 0), detail: `every part must be a non-negative integer` }),
  fair_spread: (a, r) => ({ ok: Array.isArray(r) && r.length > 0 && (Math.max(...r) - Math.min(...r)) <= 1, detail: `parts must differ by at most 1 (largest-remainder fairness)` }),
  deterministic: (a, r) => ({ ok: JSON.stringify(fn(...a)) === JSON.stringify(r), detail: `repeated calls with the same input must be identical` }),
};

function call(a) {
  try { return { threw: false, result: fn(...a) }; }
  catch (e) { return { threw: true, result: null, detail: `threw ${e.constructor?.name}: ${e.message}` }; }
}
function check(inv, a) {
  const c = call(a);
  if (c.threw) return { ok: false, detail: c.detail, result: null };
  const res = INVARIANTS[inv](a, c.result, fn);
  return { ok: res.ok, detail: res.detail, result: c.result };
}

// Delta-debugging shrink: minimise [total, parties] while the same invariant still fails.
function shrink(inv, a) {
  let [t, p] = a; let changed = true, guard = 0;
  while (changed && guard++ < 300) {
    changed = false;
    for (const np of [1, Math.floor(p / 2), p - 1].filter((x) => x >= 1 && x < p)) {
      if (!check(inv, [t, np]).ok) { p = np; changed = true; break; }
    }
    if (changed) continue;
    for (const nt of [0, 1, Math.floor(t / 2), t - 1].filter((x) => x >= 0 && x < t)) {
      if (!check(inv, [nt, p]).ok) { t = nt; changed = true; break; }
    }
  }
  return [t, p];
}

const [d0, d1] = spec.argDomain;
const report = { module: spec.module, export: spec.export, seed: spec.seed, invariants: spec.invariants, trials: 0, verdict: null, violations: [] };
const seen = new Map(); // invariant -> {count, firstArgs}

function run(a) {
  report.trials++;
  for (const inv of spec.invariants) {
    const res = check(inv, a);
    if (!res.ok) {
      const e = seen.get(inv) || { count: 0, firstArgs: a, firstResult: res.result, detail: res.detail };
      e.count++; seen.set(inv, e);
    }
  }
}

// 1. exhaustive small grid (deterministic core cases)
for (const t of spec.exhaustiveSmallGrid[d0.name]) for (const p of spec.exhaustiveSmallGrid[d1.name]) run([t, p]);
// 2. seeded randomized trials across the full domain
for (let i = 0; i < spec.trials; i++) run([randInt(d0.min, d0.max), randInt(d1.min, d1.max)]);

// shrink one minimal counterexample per violated invariant
for (const [inv, e] of seen) {
  const minimal = shrink(inv, e.firstArgs);
  const m = check(inv, minimal);
  report.violations.push({ invariant: inv, failing_inputs: e.count, first_args: e.firstArgs, first_result: e.firstResult, minimal_args: minimal, minimal_result: m.result, detail: m.detail });
}

report.verdict = report.violations.length === 0 ? 'VERIFIED' : 'VIOLATED';
console.log(JSON.stringify(report, null, 2));
process.exit(report.verdict === 'VERIFIED' ? 0 : 1);
