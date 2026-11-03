# BDE Quickstart

From zero to a reproduced behavioural defect in about five minutes.

## 0. Prerequisites

* Python 3.11+, Node 20+ (for `tsx`)
* a Git repository containing a JavaScript/TypeScript package (ESM) whose target module
  exports deterministic functions

## 1. Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .                       # actenon-shipguard (BDE ships inside the package)
shipguard doctor                    # tsx is the one tool BDE needs; see below if MISSING
```

If `tsx` is missing, either `npm i -g tsx`, or clone the pinned verifier bundle that CI
uses and point ShipGuard at it:

```bash
git clone https://github.com/rossbuckley1990-hash/sentinel-verified.git ../sentinel-verified
cd ../sentinel-verified && git checkout becba502 && npm install && cd -
export SHIPGUARD_TSX=$PWD/../sentinel-verified/node_modules/.bin/tsx
```

## 2. Discover behavioural laws in a repository (read-only until you consent)

```bash
cd /path/to/your-repo
shipguard discover                      # compiles + classifies laws, executes nothing
shipguard discover --allow-local        # ALSO executes them (see the consent note below)
```

`--allow-local` is your explicit consent for ShipGuard to run your repository's own module
code in a local subprocess (advisory isolation — same OS user, wall-clock timeouts; not a
sandbox) inside a disposable clone. Your working tree is only read: the run records a
tracked-content fingerprint and proves it unchanged.

What you get:

```
ACTENON SHIPGUARD — BEHAVIOURAL DISCOVERY
Mode      : discover
Module    : src/index.ts
Laws      : 22 discovered · 16 blocking-grade · 6 hypotheses (review) · 0 preservation
Executed  : 22 laws — 17 passed · 3 violated · 0 errored (3950 ms)

[CONFIRMED_CONTRADICTION]  bde-602de21f06
  Law      : A documented call parseFilename(...) must execute without throwing
  Grounding: README.md:107 (readme_section)
  Export   : parseFilename   Input: ["http://example.com/path/to/filename.ext"]
  Evidence : documented call threw TypeError: Cannot destructure property 'strict' ...
  Repro    : shipguard reproduce bde-602de21f06

CONFIRMED_CONTRADICTION — 3 grounded law(s) violated with reproducible witnesses.
Source repo untouched: True
Evidence  : .shipguard-bde
```

Evidence lands in `.shipguard-bde/`: `bde-evidence.json` (portable manifest),
`bde-laws.json` (every law with full provenance), `bde-report.html`,
`bde-repro-<finding>.mjs` (standalone reproduction scripts), `bde-result.json`.

## 3. Check a change before you push it

```bash
# edit something...
shipguard check --base origin/main --allow-local
```

`check` targets only the behaviour related to the diff, and additionally compiles
**preservation laws from the base revision's own tests** — a contradiction there is a
`REGRESSION_OBSERVED` finding. Uncommitted edits are carried into the disposable clone
(the uncommitted work *is* the candidate).

Exit codes: `0` no blocking finding · `1` confirmed contradiction / regression ·
`2` environment or usage error.

## 4. Audit and reproduce a finding

```bash
shipguard explain bde-602de21f06           # full provenance: rule, grounding, hashes, limits
shipguard reproduce bde-602de21f06         # re-executes the SAME predicate in a FRESH clone
cd .shipguard-bde && tsx bde-repro-bde-602de21f06.mjs   # standalone, no ShipGuard needed
```

## 5. Repair (optional — the agent never grades itself)

```bash
shipguard repair bde-602de21f06 --agent codex    # or claude
```

Builds a bounded repair task from the finding (law + witness + provenance), drives the real
agent inside a disposable clone, then re-verifies with the real Sentinel verifier using a
contract derived from the violated law — held out from the agent. The final status is
decided by the independent verifier, never by the agent's statement.

## 6. Reading an honest negative result

When no law fires you will see `VERIFIED_WITHIN_SCOPE` **plus** exactly what was not
checked (hypothesis laws, errored laws, out-of-scope inputs) and the standing limitations.
The engine never concludes "the software is correct".

## 7. Try the defining experiment yourself

The frozen research benchmark re-runs blind discovery over six real historical defects:

```bash
python3 benchmarks/bde/harness.py        # deterministic; needs the sentinel-verified checkout
```

Results and their honest misses: `benchmarks/bde/report.md`.
