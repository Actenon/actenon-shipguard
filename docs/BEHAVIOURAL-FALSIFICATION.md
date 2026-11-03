# Behavioural Falsification

> Once a law is justified, how the engine actively tries to break it — and what a violation
> is worth.

## 1. The falsification executor (`bde/runner.mjs`)

One file, one process per lawpack, run by `tsx` against a disposable clone. The lawpack is
**data**: each entry selects a predicate from a fixed, reviewed catalogue and binds literal
parameters. A lawpack can never introduce executable logic, so untrusted repository content
cannot achieve code execution through a law.

| predicate | checks |
|---|---|
| `example_executable` | the documented call runs without throwing; a literal documented result matches (objects subset-match: documentation describes salient fields) |
| `preservation_case` | the baseline I/O pair reproduces exactly (`toEqual`-style deep equality) |
| `optional_args_equivalent` | calling with required args only is supported; with literal defaults, equals the explicit-defaults call |
| `split_boundary_justified` | every output segment boundary occurs at a listed separator or a documented case change; characters preserved |
| `round_trip` / `idempotence` / `conservation_sum` / `determinism` / `no_throw` | the named structural relations on generated domains |

Every law runs in a **worker thread with a wall-clock timeout**; a hung candidate is
terminated and reported as an environment error — never as a behavioural violation.

## 2. Input generation (deterministic, in-domain)

* Seeded `mulberry32` PRNG (same family as the v0.1.x property verifier) — identical inputs
  on every run.
* **Boundary grids** for splitter laws: every string of length ≤ 3 over a core alphabet
  `{lower, upper, digit, punct}` crossed with the separator choices — systematic coverage
  of the boundary space, not luck of the draw.
* Random trials over the law's domain (string alphabets include unicode and punctuation;
  numeric domains include zero and negatives where valid).
* Literal-mode laws (documented examples) execute **the documented call verbatim** — the
  witness is the documentation, not a mutation of it.

Generation stays inside the documented/supported domain: multi-character separator strings
(where upstream revisions genuinely disagree on semantics) are excluded and recorded as a
limitation.

## 3. Counterexample minimisation

Every failing input is delta-debugged: strings shrink by halving and character-dropping,
arrays by item removal, numbers toward 0/1/half. Shrinking re-checks the predicate after
every step, so a shrunk witness is a *proven* failure, not an approximation. Up to three
distinct minimal witnesses are reported per violated law — a digit boundary and a caseless
boundary are different evidence for the same law.

## 4. What a violation proves

* A **class A/B** violation is a `CONFIRMED_CONTRADICTION`: the grounded requirement is
  violated with a reproducible witness.
* A **class C** violation is a `REGRESSION_OBSERVED`: approved baseline behaviour changed.
* A **class D** violation is a `HYPOTHESIS_FALSIFIED`: the declared relation does not hold —
  a software defect **only if** that relation is a valid requirement; review decides.

A metamorphic violation proves only that the declared relation fails. It becomes a defect
claim exactly when the law's justification is strong enough to block — never because the
engine found an input.

## 5. Mutation sensitivity (`bde/mutation.py`)

Eight single-token operators (`===`↔`!==`, `&&`↔`||`, boolean flips, negation drop,
return-void), applied one occurrence at a time in disposable copies of a **known-valid**
implementation, against the same compiled law set:

* a **detected** mutation means the laws noticed a genuine behavioural change;
* a **surviving** mutation is evidence of limited detection sensitivity — never a defect
  claim about the original source;
* mutations that break the module (it no longer imports) are **neutral**, not detections;
* **harmless-refactor controls** (comment, blank line) must trigger zero findings.

Measured on the corpus fix revisions: 14/36 behavioural mutations detected (38.9%),
0 refactor false positives (`benchmarks/bde/results.json`).

## 6. Bounds and honesty

* Sampled inputs are not proofs: "100,000 trials, no violation" is stated as
  `VERIFIED_WITHIN_SCOPE`, never as correctness.
* Trial budgets are fixed per law family (see `strategies.py`); the whole lawpack has a
  wall-clock budget and per-law timeouts.
* Skips are visible: out-of-scope inputs (non-string inputs to a splitter, an omitted
  separators argument whose documented default is not machine-extractable) return `SKIP`
  with a reason, reported in the outcome list.
