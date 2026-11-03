# Behavioural Discovery Architecture

> How Actenon ShipGuard discovers justified behavioural expectations in existing software,
> tries to falsify the implementation against them, and produces independently reproducible
> evidence — without anyone hand-authoring the acceptance test that reveals the bug.

## 1. The problem BDE exists for

A developer's ordinary tests encode the behaviour someone already thought to check. The
defects that ship are usually the ones **nobody wrote a test for** — a documented example
that no longer runs, a splitter that started splitting at digits, an optional argument that
crashes when omitted. Traditional review, static analysis and LLM code-judging all *look at
the code*. BDE instead tries to **derive what the code was supposed to do from the project's
own evidence**, turn that into executable checks, and actively search for counterexamples.

```
repository evidence ──► Intent Compiler ──► candidate laws ──► authority policy
 (docs, signatures,       (extraction,         (provenance,       (A/B/C/D classes,
  own tests)               no interpretation     predicates)        qualification)
                                                                      │
 portable evidence ◄── witness/minimisation ◄── falsification ◄── blocking subset
 (manifest + repro)         (delta debugging)     (runner.mjs)        only
```

## 2. Module map (implementation)

| module | responsibility |
|---|---|
| `bde/laws.py` | `BehaviouralLaw` record, evidence classes A/B/C/D, reviewed predicate catalogue, versioned JSON schema + fail-closed validation |
| `bde/sources.py` | grounded evidence collection: safe literal parser, TS signature scanner, README API sections, JSDoc/README examples, test I/O extraction |
| `bde/compiler.py` | the Intent Compiler: 8 discovery families, each emitting laws with verbatim provenance |
| `bde/authority.py` | deterministic qualification policy; the proposer never certifies |
| `bde/strategies.py` | law → executable spec translation (domains, budgets) |
| `bde/runner.mjs` | the falsification executor: fixed predicate catalogue, seeded generation, boundary grids, shrinking, per-law worker isolation |
| `bde/scheduler.py` | bounded deterministic execution driver, stale-evidence guard, status classification |
| `bde/witness.py` | findings as first-class artifacts, portable evidence manifest, standalone reproduction scripts |
| `bde/check.py` | the product workflow (`discover` / `check --base`) in a disposable clone with an untouched-proof fingerprint |
| `bde/report.py` | terminal / JSON / HTML developer output |
| `bde/mutation.py` | controlled mutation-sensitivity probes in disposable copies |

## 3. The discovery families

| family | grounded in | typical law |
|---|---|---|
| F1 doc-example executability | README fences, JSDoc `@example` | "the documented call must run and return the documented result" |
| F2 splitter boundary law | README/JSDoc bullet sentences stating split causes verbatim | "a new segment may only start at a listed separator or a documented case change" |
| F3 optional-argument law | machine-readable TS signature | "calling with the required arguments only must be supported" |
| F4 preservation cases | the project's own passing tests | "the baseline I/O pair must keep holding" |
| F5 round-trip pairs | type-inverse exports + documented inverse | "decode(encode(x)) === x for supported x" |
| F6 idempotence | documented normalisation statements | "f(f(x)) === f(x)" |
| F7 conservation | documented total-conservation for numeric allocation | "sum(parts) === total" |
| F8 determinism | signature + seed examples | "same input → same output" |

Families F5–F8 compile as **hypotheses (class D)** by default in this release; only F1 (with
a second corroborating extraction), F2 (with signature corroboration) and F3 can reach
blocking grade (see `LAW-PROVENANCE-AND-TRUST.md`).

## 4. What the developer runs

```bash
shipguard discover --module src/index.ts --allow-local   # baseline investigation
shipguard check --base origin/main --allow-local         # change-scoped, with regressions
shipguard explain <finding-id>                           # full provenance of one finding
shipguard reproduce <finding-id>                         # re-execute the witness in a fresh clone
shipguard repair <finding-id> --agent codex              # optional agent repair, re-verified
```

`discover`/`check` never modify the repository: a disposable local clone is verified, and
the tracked-content fingerprint of the original is proven equal before/after. Executing
laws means running the project's own module code locally — **advisory** isolation (same OS
user), stated in every report, and gated behind explicit `--allow-local` consent.

## 5. What it honestly is not

* It is not an LLM judging code: this release's discovery is deterministic parsing and
  program analysis (an LLM proposal channel exists in the design but is not wired).
* It is not a general oracle: laws only exist where the repository states behaviour
  machine-extractably; `VERIFIED_WITHIN_SCOPE` reports exactly what was and was not checked.
* It is not a sandbox: a hostile repository's code, if you consent to run it, runs under
  your OS account with a wall-clock timeout — the same boundary Sentinel's local runner has.

## 6. Measured capability (see `benchmarks/bde/report.md`)

Blind on the 6 frozen v0.2.0 historical-defect targets: **3/6 discovered** with minimal
reproducible witnesses, **0 invalid-law false positives**, plus 24 audited-true
documentation-code contradictions in ufo. Mutation sensitivity on known-valid code: 38.9%
of single-token semantic mutations detected; 0 false positives on harmless refactors.
