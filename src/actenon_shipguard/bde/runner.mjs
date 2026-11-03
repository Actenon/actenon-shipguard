// Actenon Behavioural Discovery Engine — law executor (runner.mjs).
//
// Executes compiled behavioural laws against a target module in a DISPOSABLE clone.
//
//   tsx runner.mjs --lawpack <abs.json> --repo <abs path> [--per-law-ms 8000]
//
// DESIGN CONTRACTS
//   * The predicate catalogue below is FIXED and reviewed. A lawpack is DATA that selects a
//     predicate and binds literal parameters; it can never introduce executable logic, so
//     untrusted repository content cannot achieve code execution through a law (mandate §15).
//   * Deterministic: seeded mulberry32 PRNG (same family as the v0.1.x property verifier).
//   * Every law runs in a worker thread with a wall-clock timeout; a hung candidate is
//     terminated and reported as an environment error — never as a behavioural violation.
//   * Every failing input is shrunk (delta debugging over JSON values) to a minimal witness.
//
// Output (stdout, JSON): {module, executed, findings[], law_results[], errors[]}
import { readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve as resolvePath } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isMainThread, parentPort, workerData } from 'node:worker_threads';

const RUNNER_VERSION = 2;

// ---------------------------------------------------------------- seeded determinism -------- //
function mulberry32(seed) {
  let s = seed >>> 0;
  return () => {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------- value helpers -------------- //
const isUpperLetter = (c) => typeof c === 'string' && c.length === 1 && c !== c.toLowerCase() && c === c.toUpperCase();
const isLowerLetter = (c) => typeof c === 'string' && c.length === 1 && c !== c.toUpperCase() && c === c.toLowerCase();
const isDigit = (c) => typeof c === 'string' && c.length === 1 && c >= '0' && c <= '9';

function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a === 'number' && typeof b === 'number' && Number.isNaN(a) && Number.isNaN(b)) return true;
  if (a === null || b === null || a === undefined || b === undefined) return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
    return true;
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    for (const k of ka) if (!deepEqual(a[k], b[k])) return false;
    return true;
  }
  return false;
}

function show(v) {
  if (v === undefined) return '<undefined>';
  try { const s = JSON.stringify(v); return s === undefined ? String(v) : (s.length > 160 ? s.slice(0, 159) + '…' : s); }
  catch { return String(v); }
}

function callFn(fn, args) {
  try { return { threw: false, result: fn(...args) }; }
  catch (e) { return { threw: true, name: e?.constructor?.name, message: String(e?.message ?? e) }; }
}

// ---------------------------------------------------------------- input generation ----------- //
function genString(rnd, spec, i) {
  const alpha = spec.alphabet && spec.alphabet.length ? spec.alphabet : ['a', 'B', '1', '-'];
  const min = spec.min_len ?? 0, max = Math.max(spec.max_len ?? 12, min);
  if (i === 0) return '';
  if (i === 1) return alpha[Math.floor(rnd() * alpha.length)];
  const len = min + Math.floor(rnd() * (max - min + 1));
  let out = '';
  for (let k = 0; k < len; k++) out += alpha[Math.floor(rnd() * alpha.length)];
  return out;
}
function genInt(rnd, spec) { return (spec.min ?? 0) + Math.floor(rnd() * Math.max(1, (spec.max ?? 100) - (spec.min ?? 0) + 1)); }

function generateArgs(rnd, argSpecs, i) {
  return argSpecs.map((spec) => {
    if (spec.kind === 'omit') return undefined;
    if (spec.kind === 'literal') return spec.value;
    if (spec.kind === 'choice') return spec.values[Math.floor(rnd() * spec.values.length)];
    if (spec.kind === 'string') return genString(rnd, spec, i);
    if (spec.kind === 'int') return genInt(rnd, spec);
    return undefined;
  });
}

// exhaustive boundary grid for splitter laws: every string of length <= 3 over the core
// alphabet {lower, upper, digit, punct} crossed with the separator choices — systematic
// coverage of the boundary space, not just luck of the draw.
function boundaryGrid(coreAlpha, sepChoices) {
  const out = [];
  const recur = (prefix) => {
    out.push(prefix);
    if (prefix.length >= 3) return;
    for (const c of coreAlpha) recur(prefix + c);
  };
  recur('');
  const cases = [];
  for (const s of out) {
    cases.push([s]);
    for (const seps of sepChoices) cases.push([s, seps]);
  }
  return cases;
}

// ---------------------------------------------------------------- shrinking (delta debugging) - //
function shrinkValue(value, stillFails) {
  if (typeof value === 'string' && value.length > 1) {
    // try '', single chars, halves, then char-dropping
    for (const cand of ['', value[0], value.slice(0, Math.ceil(value.length / 2))]) {
      if (cand !== value && cand.length < value.length && stillFails(cand)) return cand;
    }
    let cur = value;
    for (let i = 0; i < cur.length && cur.length > 1; i++) {
      const cand = cur.slice(0, i) + cur.slice(i + 1);
      if (cand !== cur && stillFails(cand)) { cur = cand; i = -1; }
    }
    return cur;
  }
  if (typeof value === 'number' && value !== 0) {
    for (const cand of [0, 1, value > 0 ? Math.floor(value / 2) : Math.ceil(value / 2)]) {
      if (stillFails(cand)) return cand;
    }
    return value;
  }
  if (Array.isArray(value) && value.length > 0) {
    for (let i = value.length - 1; i >= 0; i--) {
      const cand = value.slice(0, i).concat(value.slice(i + 1));
      if (stillFails(cand)) return shrinkValue(cand, stillFails);
    }
    return value;
  }
  return value;
}

function shrinkArgs(args, check) {
  const fails = (a) => { const r = check(a); return r && !r.ok; };
  if (!fails(args)) return { args, shrunk: false };
  let cur = args.slice();
  for (let i = 0; i < cur.length; i++) {
    const before = cur[i];
    const after = shrinkValue(before, (v) => fails(cur.slice(0, i).concat([v], cur.slice(i + 1))));
    cur = cur.slice(0, i).concat([after], cur.slice(i + 1));
    if (after !== before) i = -1;                       // restart: earlier positions may shrink further
  }
  return { args: cur, shrunk: true };
}

// ---------------------------------------------------------------- predicates ------------------ //
// Each predicate: (fn, args, params) -> {ok, detail?, kind?, observed?, expected?}
function subsetMatches(expected, observed, path = '') {
  // Documentation objects describe SALIENT fields; extra fields in the observed result are
  // not a contradiction. Scalars and arrays are compared exactly.
  if (expected === null || typeof expected !== 'object' || Array.isArray(expected)) {
    return { ok: deepEqual(expected, observed), path };
  }
  if (observed === null || typeof observed !== 'object' || Array.isArray(observed)) {
    return { ok: false, path };
  }
  for (const k of Object.keys(expected)) {
    if (!(k in observed)) return { ok: false, path: path ? `${path}.${k}` : k };
    const r = subsetMatches(expected[k], observed[k], path ? `${path}.${k}` : k);
    if (!r.ok) return r;
  }
  return { ok: true };
}

const PREDICATES = {
  example_executable(fn, args, params) {
    const c = callFn(fn, args);
    if (c.threw) return { ok: false, kind: 'documented_call_threw', detail: `documented call threw ${c.name}: ${c.message}`, observed: `threw ${c.name}: ${c.message}` };
    if (params.expected_kind === 'undefined') {
      if (c.result !== undefined) return { ok: false, kind: 'documented_result_mismatch', detail: `documented result is undefined, observed ${show(c.result)}`, observed: c.result, expected: undefined };
      return { ok: true };
    }
    if ('expected' in params) {
      const exp = params.expected;
      if (exp !== null && typeof exp === 'object' && !Array.isArray(exp)) {
        const m = subsetMatches(exp, c.result);
        if (!m.ok) return { ok: false, kind: 'documented_result_mismatch', detail: `documented field ${m.path} = ${show(exp[m.path.split('.').pop()])}, observed ${show(c.result && typeof c.result === 'object' ? c.result[m.path.split('.').pop()] : c.result)}`, observed: c.result, expected: exp };
      } else if (!deepEqual(c.result, exp)) {
        return { ok: false, kind: 'documented_result_mismatch', detail: `documented result ${show(exp)}, observed ${show(c.result)}`, observed: c.result, expected: exp };
      }
    }
    return { ok: true, observed: c.result };
  },

  preservation_case(fn, args, params) {
    const c = callFn(fn, args);
    if (c.threw) return { ok: false, kind: 'baseline_pair_threw', detail: `baseline pair threw ${c.name}: ${c.message}`, observed: `threw ${c.name}: ${c.message}`, expected: params.expected };
    if (!deepEqual(c.result, params.expected)) {
      return { ok: false, kind: 'baseline_pair_mismatch', detail: `baseline expected ${show(params.expected)}, observed ${show(c.result)} (${params.matcher})`, observed: c.result, expected: params.expected };
    }
    return { ok: true };
  },

  optional_args_equivalent(fn, args, params, ctx) {
    // args arrive generated for the REQUIRED arity; compare f(req...) with f(req..., defaults)
    const req = args.slice(0, params.n_required);
    const cReq = callFn(fn, req);
    if (cReq.threw) return { ok: false, kind: 'optional_call_threw', detail: `calling with required arguments only threw ${cReq.name}: ${cReq.message}`, observed: `threw ${cReq.name}: ${cReq.message}` };
    if (params.defaults && params.check === 'deep_equal') {
      const full = req.concat(params.defaults);
      const cFull = callFn(fn, full);
      if (cFull.threw) return { ok: false, kind: 'explicit_default_call_threw', detail: `explicit-defaults call threw ${cFull.name}: ${cFull.message}` };
      if (!deepEqual(cReq.result, cFull.result)) return { ok: false, kind: 'optional_default_mismatch', detail: `without optional args returned ${show(cReq.result)}, with documented defaults returned ${show(cFull.result)}`, observed: cReq.result, expected: cFull.result };
    }
    if (params.defaults && params.check === 'no_throw_and_equal') {
      const full = req.concat(params.defaults);
      const cFull = callFn(fn, full);
      if (!cFull.threw && !deepEqual(cReq.result, cFull.result)) {
        return { ok: false, kind: 'optional_default_mismatch', detail: `without optional args returned ${show(cReq.result)}, with literal defaults returned ${show(cFull.result)}`, observed: cReq.result, expected: cFull.result };
      }
    }
    return { ok: true };
  },

  split_boundary_justified(fn, args, params) {
    const str = args[0];
    if (typeof str !== 'string') return { ok: true };                 // non-string inputs: out of scope
    // When the separators argument is absent, the check needs the documented default. If the
    // default could not be extracted (missing/malformed documentation), the case is OUT OF
    // SCOPE rather than guessed (a guessed empty default would manufacture false violations).
    const hasSepArg = args.length > 1 && Array.isArray(args[1]);
    if (!hasSepArg && !Array.isArray(params.default_separators) && params.separators_param_index != null) {
      return { ok: true, skipped: 'separators argument omitted and the documented default is not machine-extractable' };
    }
    const separators = hasSepArg ? args[1] : (params.default_separators || []);
    // 'listed separator characters' = every character appearing in the provided separator
    // strings (the documented default is a list of single characters; the generated domain
    // only produces single-character separators, where array- and string-membership agree).
    const sepSet = new Set();
    for (const sep of separators) {
      for (const ch of String(sep)) sepSet.add(ch);
    }
    const c = callFn(fn, args);
    if (c.threw) return { ok: false, kind: 'splitter_threw', detail: `splitter threw ${c.name}: ${c.message}`, observed: `threw ${c.name}: ${c.message}` };
    const result = c.result;
    if (!Array.isArray(result)) return { ok: false, kind: 'splitter_not_array', detail: `splitter must return an array; observed ${show(result)}`, observed: result };
    if (!result.every((s) => typeof s === 'string')) return { ok: false, kind: 'splitter_segments_not_strings', detail: `segments must be strings`, observed: result };

    // character preservation: concatenation === input minus listed separators
    let residual = '';
    const origin = [];
    for (let i = 0; i < str.length; i++) {
      if (sepSet.has(str[i])) continue;
      residual += str[i];
      origin.push(i);
    }
    const joined = result.join('');
    if (params.chars_preserved !== false && joined !== residual) {
      return { ok: false, kind: 'chars_not_preserved', detail: `output characters ${show(joined)} != input minus separators ${show(residual)}`, observed: joined, expected: residual };
    }

    // boundary justification (encodes the documented causes; matches the definitive upstream
    // semantics: a rising edge needs the previous char to be definitively NOT uppercase and NOT
    // a digit — digits are tri-state 'unknown' and never trigger a case edge)
    let offset = 0;
    for (let k = 0; k < result.length - 1; k++) {
      const seg = result[k];
      const next = result[k + 1];
      offset += seg.length;
      if (seg === '' || next === '') continue;
      const rIdx = offset;
      if (rIdx <= 0 || rIdx >= residual.length) continue;
      const oIdx = origin[rIdx];
      const ch = str[oIdx];
      const prevCh = oIdx > 0 ? str[oIdx - 1] : null;
      const nextCh = oIdx + 1 < str.length ? str[oIdx + 1] : null;
      let justified = false;
      if (prevCh !== null && sepSet.has(prevCh)) justified = true;                                     // at a listed separator
      if (isUpperLetter(ch) && prevCh !== null && !isUpperLetter(prevCh) && !isDigit(prevCh)) justified = true;  // rising edge after lower/caseless
      if (isUpperLetter(ch) && nextCh !== null && !isUpperLetter(nextCh) && !isDigit(nextCh)) justified = true;  // falling-edge outcome (upper starting the final run)
      // 'ignores numbers for case changes' is enforced STRUCTURALLY: a digit is never an
      // uppercase letter, so it can never justify a boundary via a case change. A digit that
      // starts a segment right after a consumed separator is separator-caused and legitimate.
      if (!justified) {
        return {
          ok: false, kind: 'unjustified_boundary',
          detail: `boundary before input index ${oIdx}: "${seg}" | "${next}" — the character ${JSON.stringify(ch)} after ${JSON.stringify(prevCh)} is neither a listed separator (${show(separators)}) nor a documented case change`,
          observed: result, boundary_index: oIdx, boundary_char: ch, segment_before: seg, segment_after: next,
        };
      }
    }
    return { ok: true };
  },

  round_trip(fn, args, params, ctx) {
    const fwd = ctx.mod[params.forward];
    if (typeof fwd !== 'function') return { ok: true, skipped: `export ${params.forward} unavailable` };
    const a = callFn(fwd, args);
    if (a.threw) return { ok: true, skipped: 'forward call threw on this input (out of supported domain)' };
    const b = callFn(fn, [a.result]);
    if (b.threw) return { ok: false, kind: 'inverse_threw', detail: `${params.inverse}(${params.forward}(x)) threw ${b.name}: ${b.message}`, observed: `threw ${b.name}: ${b.message}` };
    if (!deepEqual(b.result, args[0])) return { ok: false, kind: 'round_trip_mismatch', detail: `${params.inverse}(${params.forward}(x)) returned ${show(b.result)}, expected ${show(args[0])}`, observed: b.result, expected: args[0] };
    return { ok: true };
  },

  idempotence(fn, args) {
    const once = callFn(fn, args);
    if (once.threw) return { ok: true, skipped: 'threw on this input (out of domain)' };
    const twice = callFn(fn, [once.result]);
    if (twice.threw) return { ok: false, kind: 'second_application_threw', detail: `f(f(x)) threw ${twice.name}: ${twice.message}`, observed: `threw ${twice.name}: ${twice.message}` };
    if (!deepEqual(once.result, twice.result)) return { ok: false, kind: 'not_idempotent', detail: `f(x) = ${show(once.result)} but f(f(x)) = ${show(twice.result)}`, observed: twice.result, expected: once.result };
    return { ok: true };
  },

  conservation_sum(fn, args, params) {
    const total = args[params.total_index ?? 0];
    const c = callFn(fn, args);
    if (c.threw) return { ok: true, skipped: `threw on this input (${c.name})` };
    if (!Array.isArray(c.result)) return { ok: false, kind: 'allocation_not_array', detail: `allocation must return an array; observed ${show(c.result)}`, observed: c.result };
    const sum = c.result.reduce((x, y) => x + y, 0);
    if (sum !== total) return { ok: false, kind: 'total_not_conserved', detail: `sum(parts)=${sum} must equal total=${total}`, observed: sum, expected: total };
    return { ok: true };
  },

  determinism(fn, args) {
    const a = callFn(fn, args);
    const b = callFn(fn, args);
    if (a.threw || b.threw) return { ok: true, skipped: 'threw on this input' };
    if (!deepEqual(a.result, b.result)) return { ok: false, kind: 'nondeterministic', detail: `same input produced ${show(a.result)} then ${show(b.result)}`, observed: b.result, expected: a.result };
    return { ok: true };
  },

  no_throw(fn, args) {
    const c = callFn(fn, args);
    if (c.threw) return { ok: false, kind: 'threw', detail: `threw ${c.name}: ${c.message}`, observed: `threw ${c.name}: ${c.message}` };
    return { ok: true };
  },
};

// ---------------------------------------------------------------- law execution (worker side) -- //
async function executeLaw(law, modulePath, tsImport) {
  const mod = await tsImport(pathToFileURL(resolvePath(modulePath)).href, import.meta.url);
  const fn = mod[law.export];
  if (typeof fn !== 'function') return { law_id: law.law_id, status: 'ERROR', detail: `export ${law.export} is not a function`, trials: 0 };
  const pred = PREDICATES[law.predicate];
  if (!pred) return { law_id: law.law_id, status: 'ERROR', detail: `unknown predicate ${law.predicate}`, trials: 0 };

  const gen = law.gen || {};
  const check = (args) => pred(fn, args, law.params || {}, { mod });

  // literal-mode laws (examples / preservation / determinism seeds)
  if (gen.mode === 'literal') {
    const r = check(gen.args);
    if (r && r.ok) return { law_id: law.law_id, status: r.skipped ? 'SKIP' : 'PASS', detail: r.skipped, trials: 1 };
    let minimal = gen.args, shrunk = false;
    if (gen.shrink !== false) {
      const s = shrinkArgs(gen.args, check);
      minimal = s.args; shrunk = s.shrunk;
    }
    const m = check(minimal);
    const finding = {
      law_id: law.law_id, predicate: law.predicate, export: law.export,
      args: minimal, original_args: gen.args, shrunk,
      kind: m?.kind || r?.kind, detail: (m && m.detail) || r.detail,
      observed: m ? m.observed : undefined, expected: m ? m.expected : r.expected,
      boundary_index: m ? m.boundary_index : r.boundary_index,
      boundary_char: m ? m.boundary_char : r.boundary_char,
      segment_before: m ? m.segment_before : r.segment_before,
      segment_after: m ? m.segment_after : r.segment_after,
      first_failing_trial: 0,
    };
    return { law_id: law.law_id, status: 'FAIL', trials: 1, shrunk, finding, findings: [finding] };
  }

  // generated-mode laws: collect up to MAX_WITNESSES DISTINCT failing inputs — different
  // witnesses are different evidence for the same violated law (e.g. a digit boundary and
  // a caseless-char boundary), and each is minimised independently.
  const MAX_WITNESSES = 3;
  const witnesses = [];
  const rnd = mulberry32(gen.seed ?? 1234567);
  const trials = gen.trials ?? 200;
  let executed = 0;
  let cases = [];
  if (gen.grid) {
    cases = boundaryGrid(gen.grid.core_alphabet, gen.grid.separator_choices || [[]]);
  }
  for (let i = 0; i < trials; i++) {
    cases.push(generateArgs(rnd, gen.arg_specs, i));
  }
  for (const args of cases) {
    executed++;
    const r = check(args);
    if (r && !r.ok && !r.skipped) {
      const s = shrinkArgs(args, check);
      const m = check(s.args);
      witnesses.push({
        law_id: law.law_id, predicate: law.predicate, export: law.export,
        args: s.args, original_args: args, shrunk: s.shrunk,
        kind: r.kind, detail: (m && m.detail) || r.detail,
        observed: m ? m.observed : r.observed, expected: m ? m.expected : r.expected,
        boundary_index: m ? m.boundary_index : r.boundary_index,
        boundary_char: m ? m.boundary_char : r.boundary_char,
        segment_before: m ? m.segment_before : r.segment_before,
        segment_after: m ? m.segment_after : r.segment_after,
        first_failing_trial: executed,
      });
      if (witnesses.length >= MAX_WITNESSES) break;
    }
  }
  if (witnesses.length > 0) {
    return { law_id: law.law_id, status: 'FAIL', trials: executed, shrunk: witnesses[0].shrunk,
             finding: witnesses[0], findings: witnesses };
  }
  return { law_id: law.law_id, status: 'PASS', trials: executed };
}

// ---------------------------------------------------------------- worker bootstrap ------------ //
if (!isMainThread && parentPort) {
  const { law, modulePath, tsxApi } = workerData;
  try {
    // CLI loader hooks do not reliably propagate to workers. Import through tsx's
    // public API in THIS worker; Node 22 native stripping can otherwise hide the bug.
    const { tsImport } = await import(tsxApi);
    const result = await executeLaw(law, modulePath, tsImport);
    parentPort.postMessage({ ok: true, result });
  } catch (e) {
    parentPort.postMessage({ ok: false, error: `${e?.code || e?.constructor?.name}: ${e?.message}` });
  }
}

// ---------------------------------------------------------------- main orchestration ---------- //
async function main() {
  const argv = process.argv.slice(2);
  const opt = (name) => { const i = argv.indexOf('--' + name); return i >= 0 ? argv[i + 1] : undefined; };
  const lawpackPath = opt('lawpack');
  const repo = opt('repo');
  const tsxCli = opt('tsx');
  const perLawMs = Number(opt('per-law-ms') || 10000);
  if (!lawpackPath || !repo || !tsxCli) {
    console.error('usage: tsx runner.mjs --tsx <tsx-cli-path> --lawpack <path.json> --repo <path> [--per-law-ms N]');
    process.exit(2);
  }
  const pack = JSON.parse(readFileSync(resolvePath(lawpackPath), 'utf8'));
  // Resolve from the configured CLI installation, never from target node_modules.
  // This works for global installs, .bin symlinks and installed Python wheels.
  const tsxApi = pathToFileURL(createRequire(realpathSync(tsxCli)).resolve('tsx/esm/api')).href;
  const modulePath = resolvePath(repo, pack.module);
  const out = { module: pack.module, runner_version: RUNNER_VERSION, executed: 0, findings: [], law_results: [], errors: [] };

  const { Worker } = await import('node:worker_threads');
  for (const law of pack.laws || []) {
    const started = Date.now();
    const result = await new Promise((resolve) => {
      let settled = false;
      const settle = (v) => { if (!settled) { settled = true; clearTimeout(timer); resolve(v); } };
      const w = new Worker(new URL(import.meta.url), { workerData: { law, modulePath, tsxApi } });
      const timer = setTimeout(() => { try { w.terminate(); } catch { /* already gone */ } }, perLawMs);
      w.on('message', (m) => { try { w.terminate(); } catch { /* already gone */ } settle(m); });
      w.on('error', (e) => {
        try { w.terminate(); } catch { /* already gone */ }
        settle({ ok: false, error: `${e?.constructor?.name}: ${e?.message}` });
      });
      // terminate() (timeout) or a crash surfaces as an exit without any message
      w.on('exit', (code) => settle({ ok: false, error: `worker exited with code ${code} (wall-clock timeout or crash)` }));
    });
    const duration = Date.now() - started;
    if (!result.ok) {
      out.law_results.push({ law_id: law.law_id, predicate: law.predicate, status: 'ERROR', detail: result.error, duration_ms: duration });
      out.errors.push({ law_id: law.law_id, error: result.error });
      continue;
    }
    const r = result.result;
    out.law_results.push({ law_id: law.law_id, predicate: law.predicate, status: r.status, trials: r.trials, detail: r.detail, shrunk: r.shrunk, duration_ms: duration });
    if (r.status === 'PASS' || r.status === 'FAIL') out.executed++;
    if (r.status === 'ERROR') out.errors.push({ law_id: law.law_id, error: r.detail });
    for (const fl of (r.findings || (r.finding ? [r.finding] : []))) {
      out.findings.push(fl);
    }
  }
  process.stdout.write(JSON.stringify(out, null, 2));
  process.exit(out.errors.length > 0 ? 2 : out.findings.length > 0 ? 1 : 0);
}

if (isMainThread) {
  main().catch((e) => { console.error(String(e?.stack || e)); process.exit(2); });
}
