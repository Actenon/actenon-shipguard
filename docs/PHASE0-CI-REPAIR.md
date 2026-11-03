# Phase 0: reproduce and repair the remote failures

Starting revision: `98a7e5ef3c67f999a69ee810b8e7c4d96baf4e6f`.
Original runs: [41549855750](https://github.com/Actenon/actenon-shipguard/actions/runs/41549855750),
[41549807121](https://github.com/Actenon/actenon-shipguard/actions/runs/41549807121).
Both ran Node 20.20.2. Python 3.12 had four BDE failures; Python 3.11 had those
four plus two syntax-guard failures. Both Sentinel integration jobs passed.
Matrix fail-fast cancellation did not mean the 3.11 tests passed.

## Reproduced cause

At the starting revision, each worker reported `TypeError: Unknown file extension
".ts"` for the target module. All six laws errored; none executed. The tsx CLI's
ESM hook was not active in the worker performing the dynamic import.

The controlled comparison used Node 20.20.2 and 22.23.4, tsx 4.20.6, Python
3.11.15 and 3.12.13 on macOS arm64. Node 22 passed only because native type
stripping loaded these particular fixtures. With `NODE_OPTIONS=--no-experimental-strip-types`,
Node 22 reproduced the same six errors. Upgrading CI alone would have masked the bug.
The original CI installed unpinned tsx; its exact installed version was not logged
and is NOT ESTABLISHED. The comparison is therefore not a byte-identical CI environment.

Separately, the Python syntax guard tried to parse a deliberately Python-3.12-only
snippet with 3.11 and crashed. On valid sources, 3.11's `FormattedValue` locations
span entire implicitly concatenated f-strings and produced false positives. These
were guard defects, not hundreds of incompatible production expressions.

## Repairs and controls

- Resolve the public `tsx/esm/api` from the configured CLI installation and call
  `tsImport` inside each worker. Do not resolve the loader from target dependencies.
- Preserve the failing behavioural assertions. Add successful and deliberately
  wrong-result controls for `.ts`, `.mts`, `.cts`, transitive imports and enums
  (which native strip-only loading cannot execute).
- Require the hang test to report the actual wall-clock timeout, preventing an
  import failure from accidentally satisfying the timeout negative control.
- Report law import failures as `ENVIRONMENT_FAILURE`; retain error details in
  terminal notes and evidence JSON. Count only PASS/FAIL laws as executed.
- Replace AST location guessing with non-executing compilation by an actual 3.11
  interpreter in every CI job. Preserve the original invalid snippet and add valid
  multiline/concatenated f-string controls plus other 3.12-only syntax controls.
  Scan both `benchmark` and `benchmarks`, as well as source, tests and scripts.
- Run the Python 3.11/3.12 × Node 20/22 matrix without fail-fast; pin Node and tsx.
  Mandatory pytest skips remain fatal. Run BDE from the non-editable wheel outside
  the source directory, and upload the execution evidence.

The smoke fixture has an optional, unapproved determinism hypothesis that is
inapplicable when its call throws. The smoke checker requires an explicit reason
for that skip and refuses skipped qualified laws, missing outcomes or law errors.
The smoke fixture is synthetic and establishes runtime integration, not discovery
of a previously unseen real defect.

## Local evidence

| Python | Node | Before (BDE + syntax tests) | After (full core suite) |
|---|---|---|---|
| 3.11.15 | 20.20.2 | 6 failed, 16 passed | 154 passed, 8 deselected |
| 3.12.13 | 20.20.2 | 4 failed, 18 passed | 154 passed, 8 deselected |
| 3.11.15 | 22.23.4 | 2 failed, 20 passed | 154 passed, 8 deselected |
| 3.12.13 | 22.23.4 | 22 passed | 154 passed, 8 deselected |

No pytest skips in the repaired matrix. The eight deselected tests belong to the
separate real-Sentinel integration job. Node 22 with native stripping disabled:
24 BDE tests passed. CLI smoke, non-editable wheel BDE smoke, offline demo and
wheel demo passed on Python 3.11 / Node 20. `ruff` and `git diff --check` passed.
Machine-readable baseline, errors and repaired matrix: `evidence/phase0/`.

Remote validation is recorded below. No merge, release or product-value claim is
authorised by these runtime checks.

## Remote verification

Commit `8bc815cb3586374ff8672bd2f20366fbb71a7666` passed all five jobs in
[GitHub Actions run 41706606243](https://github.com/Actenon/actenon-shipguard/actions/runs/41706606243):
four Python 3.11/3.12 × Node 20.20.2/22.23.4 jobs (including CLI smoke and
non-editable wheel execution), plus the real Sentinel integration job.
