# RELEASE-EVIDENCE-v0.2.0.md — Actenon ShipGuard

**Milestone: v0.2.0 "developer aspirin" — a real coding agent makes a change, ShipGuard
independently verifies it against a held-out approved contract, and (on contradiction) feeds a
reproducible counterexample back to drive a genuine repair.**

**Release decision: NO-GO for publishing v0.2.0 as the "developer aspirin" milestone.** The branch is
retained, fully tested (128 passing, 0 skipped), and documented. Two mandatory gate conditions are not
satisfied, and the independent real-world benchmark now shows *why* they cannot be satisfied honestly on
this corpus: across 6 frozen real historical defects in 3 independently maintained projects, the live
agent (Claude Code) produced **correct code on all 6, first attempt**. Independent verification agreed
6/6, ordinary tests agreed 6/6, and false accepts were 0 in both arms. So there were **0 detections and
0 repairs** — nothing for the aspirin claim to rest on. I did not weaken a task, hide a requirement,
expand the corpus after seeing results, or substitute a scripted candidate to force a demonstration.

What *is* supported is a narrower claim, kept strictly separate below: on real third-party repositories
ShipGuard runs the project's own tests, obtains an independent content-addressed receipt from a pinned
external verifier, enforces change scope from the real diff, and commits a candidate whose tree is
provably byte-identical to what was verified — 6/6, with every change confined to its allowed file. That
is a **verification** result, not a detection or repair result. See "The two claims, separated".

---

## PUBLISHED: `v0.2.0-preview.1` (verification-only developer preview)

Authorised by the repository owner on 2026-11-02 as a **scoped developer preview**, explicitly *not*
the full developer-aspirin release.

| | |
|---|---|
| Tag | `v0.2.0-preview.1` → `89ae549e574765301f7919e701aa5eaacd3a1924` (branch `v0.2.0`) |
| Distribution version | `0.2.0rc1` — "preview" is not a valid PEP 440 pre-release spelling, so the tag keeps the authorised name and the artifacts carry `0.2.0rc1`. pip flags it as a pre-release, so a plain `pip install actenon-shipguard` will not select it |
| Release | <https://github.com/Actenon/actenon-shipguard/releases/tag/v0.2.0-preview.1> (marked pre-release, not a draft) |
| Wheel | `actenon_shipguard-0.2.0rc1-py3-none-any.whl` — sha256 `5a81481042e88fb7fd8927e90f6a898139419bfc225f74230bea5cfb13d3b5fe` |
| Sdist | `actenon_shipguard-0.2.0rc1.tar.gz` — sha256 `f415417eaf66913508f347577f1573a3e3874da050b005ab0f553863f2b15084` |
| Asset integrity | both assets were downloaded back from the release and re-hashed: identical to the local build from the clean tree at `89ae549`, byte for byte |
| CI at this commit | run [41466184892](https://github.com/Actenon/actenon-shipguard/actions/runs/41466184892) — `verify (3.11)` 120 passed / 8 deselected, `verify (3.12)` 120 passed / 8 deselected, `sentinel-integration` 8 passed / 120 deselected; **128 total, 0 skipped**; demo PASS (1 ALLOW / 7 REFUSE); wheel non-editable install + demo from an unrelated cwd OK |

**Claims carried by the release,** and the negatives it states in the same breath: the release body
lists the five supported capabilities (live-agent integration, independent acceptance verification,
approved change-scope enforcement, candidate-to-commit identity checking, evidence reporting within the
tested scope) and then the five things it does **not** claim (demonstrated detection of live-agent
defects, successful live counterexample-driven repair, general correctness, measured reliability
improvement, production-grade hostile-agent containment). The null benchmark result is the headline
section, not a footnote.

**The false-accept distinction is stated explicitly in the release,** because it is the easiest thing
to misread: 0 false accepts were measured on **correct** candidates, which is evidence that
verification does not cry wolf. It is *not* a measured ability to detect **incorrect** candidates —
the live agent never produced one, so detection rate was never exercised and is **unknown**, neither
zero nor high.

**The portable-evidence limitation is stated explicitly in the release:** the committed run records
deliberately omit the original raw Sentinel receipts, because those receipts are content-addressed and
embed absolute machine-local paths (`git.root`, scratch execution directories). Shipping them would
leak local filesystem layout and would not verify on another machine. The portable records carry
receipt hashes, verdicts, requirement outcomes, counterexamples and integrity results — enough to audit
the logic, not enough to re-verify cryptographically offline. Validating the receipts themselves
requires the documented reproduction workflow (`BENCHMARK-REPORT-v0.2.0.md` §8).

**Additional clean-install validation performed for this release** (beyond CI): the wheel *and* the
sdist were each installed non-editably into a fresh venv and exercised from an unrelated working
directory — `--version` reports `0.2.0rc1`, `doctor` reports every pinned dependency `ok`, `demo`
returns PASS with `decision: ALLOW`, and `run --agent offline` reaches `VERIFIED` with real Sentinel
and tree binding `True`. Evidence from those clean runs contains **no** machine-local absolute path.

**Release-history integrity.** No existing tag was moved: `v0.1.0` → `03c4b73`, `v0.1.1` → `96e62ea`,
`v0.1.2` → `f32d1be`, all unchanged and all still published as pre-releases. PR #1 was reconciled
**first**, as instructed: a verification record was posted on the PR before merging, and it was merged
with a **merge commit** (`edeb32e`) rather than squashed or rebased, so `f32d1be` and the `v0.1.2`
tag↔commit correspondence survive intact. `main` is now green (run 41464567752) and matches the
published v0.1.2. Note that `main` still carries the pre-hardening `ci.yml` from `f32d1be`; the
pipefail control and the `sentinel-integration` job arrive on `main` only when the v0.2.0 work is
merged, which is **not** authorised by this preview.

**Still excluded from this release:** Howdex (memory transfer), Workproof (attestation verification),
Apprentice (codebase modelling) and npm distribution. The defect-detection and automatic-repair
benefit remains **not established**; see the Codex benchmark plan below.

---

This supersedes nothing: v0.1.2 (the security-remediation pre-release) remains published and its
controls still pass. v0.1.1 evidence is preserved in [`RELEASE-EVIDENCE.md`](RELEASE-EVIDENCE.md).

---

## Branch + commits

- Baseline: v0.1.2 `f32d1be2693c3e3b37dc010c9d1c279dd1264533` (tag `v0.1.2`, pre-release published).
- Development branch: `v0.2.0` (from the reconciled baseline; `main` untouched at `96e62ea`; PR #1
  for v0.1.2 is ready-for-review and **not** merged).
- Commits on this branch:
  - `43c23bc` docs — reconcile stale README (v0.1.2 released, 31 tests, key-less enforcer; v0.2.0 in dev)
  - `7de7a1e` SECOND — secure agent adapters (remove `--dangerously-skip-permissions`; real Codex auth probe; gate Claude)
  - `69d4dd1` THIRD+FOURTH — real Sentinel acceptance + wired repair-loop CLI
  - `5efb373` FOURTH — repair loop end-to-end + parameterised tasks + CI Sentinel job + live-Codex evidence
  - `e238281` docs — CI green on the exact branch commit; gate condition 10 MET
  - `9945f37` Phase 1 — close the seven evidence-integrity gaps (CI pipefail + negative control, no stale
    receipt reuse, real Sentinel status vocabulary, committed-tree binding, diff-derived change scope,
    portable evidence, accurate ASPIRIN classification)
  - `567ce9c` Phase 2 — safe mode against real developer repositories (project inspection, isolated
    clone, original tree provably untouched)
  - `3757bb9` Phase 3 — frozen real-world benchmark corpus + safe-mode `node_modules` exclusion fix
  - `09b896d`/`b97cc99` Phase 3 — report generated from the artifacts, not hand-transcribed
  - `2b4950f` Phase 3 — **manifest frozen** (sha256 `a380a1b7…`, harness `b97cc99`, clean tree)
  - `4da0bcd` Phase 4 — an exhausted provider is `unavailable`, not a failed repair; corpus-integrity tests
  - `9bbe0f7` Phase 4 — fix `--agent` parsing that silently ran an empty benchmark

Pinned stack (unchanged): `actenon-kernel==1.2.1`, `actenon-protocol==1.4.0`, `actenon-permit==1.4.0`,
`actenon-scan==1.5.0`, `cryptography==44.0.0`. External verifier: **Sentinel** pinned at commit
`becba502c8dbebdd5e52b8ca09122f86e4e37bb3` (github.com/rossbuckley1990-hash/sentinel-verified, v1.0.0),
running its own vitest 5.0.5. Live agents: **Claude Code 2.1.301** (OAuth re-authenticated and probed
before the benchmark run) and **Codex CLI 0.163.0** (authenticated, but its usage limit was exhausted
until 2026-11-08, so the benchmark ran on Claude). Earlier in this milestone Claude's OAuth was
expired and live Claude was honestly disabled; that state was re-tested rather than assumed.

---

## Test suite (128 passing, 0 skipped = 120 core + 8 Sentinel integration)

| file | tests | what it locks in |
|---|---|---|
| `tests/test_trust_boundary.py` | **31** | the v0.1.2 security-remediation controls — **unchanged** (gate condition 8) |
| `tests/test_evidence_integrity.py` | 55 | Phase 1: receipt freshness, content-addressing, candidate identity, scope, tree binding, CI negative controls |
| `tests/test_sentinel.py` | 15 | acceptance logic against the real Sentinel schema + real-CLI integration |
| `tests/test_real_repo_mode.py` | 10 | Phase 2: safe mode on a real repository; the original tree is provably untouched; the clone commits without depending on the host's git identity |
| `tests/test_benchmark_corpus.py` | 9 | Phase 3: the frozen manifest is untampered, schema-legal, and its omissions are auditable |
| `tests/test_adapters.py` | 8 | adapter confinement, and provider exhaustion ≠ repair failure |

**How this maps to CI, and why the numbers differ between jobs.** CI splits the suite by the
`sentinel_integration` marker, so neither job runs all 128:

| CI job | selection | result |
|---|---|---|
| `verify (3.11)`, `verify (3.12)` | `-m "not sentinel_integration"` | **120 passed, 8 deselected** |
| `sentinel-integration` (node 22, clones + builds the pinned Sentinel) | `-m sentinel_integration` | **8 passed, 120 deselected** |

120 + 8 = 128, with **0 skipped** in every job. "Deselected" is not "skipped": a deselected test is
excluded by marker before collection, whereas a skip would mean a test was collected and then did not
run — which is what the anti-silent-skip guard fails the build for. Earlier revisions of this document
quoted 127 (before the git-identity regression test was added) and did not show the per-job split; both
are corrected here.

---

## Reproduce

```bash
git checkout v0.2.0
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

# external verifier + its runtime (Sentinel is not on npm; build the pinned commit)
git clone https://github.com/rossbuckley1990-hash/sentinel-verified.git /tmp/sentinel-verified
( cd /tmp/sentinel-verified && git checkout becba502c8dbebdd5e52b8ca09122f86e4e37bb3 && npm ci && npm run build )
export SHIPGUARD_SENTINEL=/tmp/sentinel-verified/dist/cli.js
export SHIPGUARD_NODE_MODULES=/tmp/sentinel-verified/node_modules
export SHIPGUARD_TSX=/tmp/sentinel-verified/node_modules/.bin/tsx

pytest -q                                   # 128 passed, 0 skipped
pytest -q -m "not sentinel_integration"     # 119 passed, 8 deselected (CI core job)
pytest -q -m sentinel_integration           # 8 passed (real pinned Sentinel CLI)
pytest -q tests/test_trust_boundary.py      # 31 passed — the v0.1.2 controls, unchanged

# the frozen benchmark corpus: re-validate every task, then re-freeze and run the arms
python benchmark/harness.py validate        # 6 tasks, 5 measured conditions each
python benchmark/harness.py freeze          # refuses to write unless every task is valid
claude -p "Reply with the single word OK."  # the provider is probed, never assumed
SHIPGUARD_ENABLE_LIVE_CLAUDE=1 python benchmark/harness.py run --agent claude
python benchmark/harness.py report          # BENCHMARK-REPORT-v0.2.0.md, generated from the artifacts

# the deterministic repair loop with REAL Sentinel (no model calls, no cost):
actenon-shipguard run "Conserve every penny when splitting a whole-pence total across N parties." \
  --agent offline --out /tmp/sg-run --max-attempts 1
# -> VERIFIED; ASPIRIN: ordinary tests GREEN while Sentinel CONTRADICTED an approved requirement

# a REAL live-agent run (consumes Codex tokens; authenticated provider only):
actenon-shipguard run "Fix the settlement allocation so a whole-pence total split across N parties \
never loses or creates a penny." --agent codex --out /tmp/sg-codex --max-attempts 1
```

---

## What was built and independently verified

### SECOND — agent adapters secured (`7de7a1e`)
- `--dangerously-skip-permissions` **removed** from the Claude adapter. Claude now uses supported
  controls: `--permission-mode acceptEdits` + `--allowedTools Read Edit Write` + `--disallowedTools
  Bash WebFetch WebSearch NotebookEdit`. Live Claude is gated behind explicit consent
  (`SHIPGUARD_ENABLE_LIVE_CLAUDE=1`) **and** a bounded auth probe. Claude OAuth is expired here, so
  `available()` returns `unavailable` — it never fabricates a change.
- Codex `available()` performs a **real** auth probe (`codex login status`); the binary being present
  is not treated as authenticated. Codex runs in the supported `workspace-write` sandbox (never
  `--dangerously-bypass-approvals-and-sandbox`), confined to the candidate repo.
- 5 hermetic adapter-safety tests (`tests/test_adapters.py`) lock in: no dangerous flag, supported
  confinement, auth probing, no fabrication, and the offline deterministic label.

### THIRD — real Sentinel is the acceptance authority (`69d4dd1`)
- `sentinel.py` invokes the **real** `sentinel verify --baseline HEAD --contract <held-out> --runner
  local --store <verifier-store> --repo <candidate>` and consumes the **structured receipt** from the
  content-addressed store — never a terminal string.
- `evaluate_receipt` **independently re-derives** acceptance (it does not trust the top-level status):
  supported schema; **exact approved-contract identity** (deep equality of the receipt's embedded
  contract); full git head (40-hex) + `candidateHash`; verifier/toolchain runtime
  (`verifierVersion`/`vitest`/`workerSha256`); mandatory ordinary tests (`baseline-tests`,
  `candidate-tests`, `preserved-tests`) VERIFIED; **every approved requirement covered and VERIFIED**;
  and it collects minimal counterexamples (`args`/`expected`/`observed`). Any CONTRADICTED /
  INCOMPLETE / REVIEW_REQUIRED / ENVIRONMENT_FAILURE blocks acceptance.
- 12 hermetic acceptance-logic tests + 2 real-CLI tests (`tests/test_sentinel.py`). Example real
  receipt: wrong fix → `status=CONTRADICTED`, `candidate-tests=VERIFIED` (ordinary tests green),
  requirement `no-vanishing-penny` CONTRADICTED with counterexample `allocate([100,3])` expected
  `[34,33,33]` observed `[33,33,33]`.
- The offline synthetic receipts (v0.1.2 `pipeline.build_offline_sentinel_store`) remain a **separately
  labelled fixture** and cannot authorise this production path.

### FOURTH — the repair loop + one-command CLI (`69d4dd1`, `5efb373`)
- `actenon-shipguard run "task" --agent codex|claude|offline [--contract C] [--runner local|docker]`
  drives: INTENT → APPROVED_CONTRACT → BASELINE → CODEBASE_MODEL → AGENT_CHANGE → ORDINARY_TESTS →
  INDEPENDENT_CHALLENGE (real Sentinel) → {VERIFIED | COUNTEREXAMPLE → AGENT_REPAIR → re-verify} →
  REVERIFICATION → ATTESTATION_READY. Bounded attempts; every transition recorded; the agent cannot
  promote its own work; a held-out contract digest is re-checked each attempt (tamper guard).
- The approved contract + verifier store live **outside** the candidate repo (held out from the agent).
- `no_change` (agent asked / made no change) is a **distinct** status from `contradicted`.
- Self-contained HTML run report shows the aspirin sequence, the counterexample, per-attempt Sentinel
  verdicts + receipt hashes, and the verification bindings; live vs offline runs are clearly labelled.
- 1 end-to-end loop test with real Sentinel (offline adapter): CONTRADICTED wrong fix → counterexample
  → VERIFIED repair.

---

## Real live-agent runs (Codex, authenticated) — raw results

All three used the **real** Codex CLI in a `workspace-write` sandbox; the agent generated its **own**
change (no prewritten solution was copied); acceptance was decided **only** by real Sentinel against a
held-out approved contract. Evidence (portable, no home paths) is committed under
`evidence/v020-codex-settlement/` and `evidence/v020-codex-proportional/`.

| # | Task (brief given to the agent) | Held-out approved contract | Agent outcome | Sentinel verdict | receipt | candidate git head |
|---|---|---|---|---|---|---|
| 1 | Conserve every penny splitting a whole-pence total across N parties | `settlement-contract.json` | **completed** (125.45s), model wrote largest-remainder ("one extra penny to the first remainder-count parties") | **VERIFIED** (all 4 requirements) | `d927b8e4f616…` | `e66f4758…` |
| 2 | Same, but remainder rule left to "the ledger team's approved rule" | `settlement-strict-contract.json` (remainder to **final** parties) | **no change** (120.57s) — agent **asked**: "should `allocate(10,3)` return `[4,3,3]` or `[3,3,4]`? The repository doesn't specify it." | not run (no candidate) | — | — |
| 3 | Proportional largest-remainder (Hamilton) split by integer weights, ties to lower index | `proportional-contract.json` | **completed** (49.15s), model wrote floor-quota + largest-remainder with tie-to-lower-index | **VERIFIED** (all 3 requirements) | `b0b8c890f9fb…` | `b5abd271…` |

Ordinary (weak) tests passed in every run — e.g. run 3's candidate passed its 3 ordinary vitest tests
while the held-out contract independently confirmed conservation + tie-break + zero-weight behaviour.

**Honest finding.** On well-specified tasks the live agent produced **correct** code that real Sentinel
verified; on an under-specified task it **declined to guess** and asked for the missing rule. Across
these runs the live agent did **not** produce a defect that Sentinel had to contradict, so the
counterexample-driven **live** repair path was not exercised by a live agent. Run 2's clarifying
question is itself a positive safety result (the agent did not silently pick a wrong interpretation).

---

## The defect → contradiction → counterexample → repair → re-verify loop (proven, real Sentinel)

Because the live agent did not defect, the full loop is demonstrated with the **offline deterministic
adapter** (separately labelled `offline-deterministic`, NOT a live model repair) driving **real**
Sentinel, and with the real-Sentinel wrong-fix integration test:

```
INTENT → APPROVED_CONTRACT → BASELINE → CODEBASE_MODEL → AGENT_CHANGE → ORDINARY_TESTS
→ INDEPENDENT_CHALLENGE (Sentinel CONTRADICTED, receipt 92f9ba4b…) → COUNTEREXAMPLE
   requirement no-vanishing-penny: allocate([100,3]) expected [34,33,33] observed [33,33,33]
→ AGENT_REPAIR → ORDINARY_TESTS → INDEPENDENT_CHALLENGE (Sentinel VERIFIED, receipt 1c365181…)
→ REVERIFICATION → ATTESTATION_READY   final_status=verified
```

`ordinary_tests_green_on_defect = True` — the aspirin: the wrong fix passed all 4 ordinary vitest
tests, yet independent Sentinel contradicted two approved requirements with exact counterexamples, and
the repair was independently re-verified. This is reproducible in CI (no model, no cost) via
`pytest -m sentinel_integration` and `actenon-shipguard run --agent offline`.

---

## Clean-installation reproduction (gate condition)

Fresh `python -m build --wheel` from the branch tree → non-editable `pip install` into a fresh venv
(lands in site-packages) → from an **unrelated cwd**, with Sentinel/tsx/node_modules provided via env
(they are external runtime dependencies, like Node itself):

- `actenon-shipguard doctor` → exit 0
- `actenon-shipguard demo --trials 5000` → **PASS** (1 ALLOW + 7 REFUSE), bundled resources only
- `actenon-shipguard run --agent offline --max-attempts 1` → **VERIFIED**, aspirin demonstrated,
  Sentinel receipt `7dc9bce4…`
- New task fixtures (proportional + strict contracts, candidates, tests) are bundled in the wheel.

---

## Historical v0.1.2 security controls (gate condition)

All 31 v0.1.2 trust-boundary tests still pass unchanged (part of the 51). The key-less enforcer,
authorisation binding, Sentinel anti-fabrication attestation, signed nonce reconciliation, TOCTOU
snapshot, and key-storage isolation are unaffected by the v0.2.0 work. `actenon-shipguard demo` still
yields 1 ALLOW + 7 REFUSE.

---

## FIFTH — Apprentice, Howdex, Workproof: **explicitly EXCLUDED from the v0.2.0 claim**

Per the gate ("...or unfinished capabilities are explicitly excluded"), these are **not** wired and
are **not** claimed:

- **Apprentice (MODEL):** `CODEBASE_MODEL` performs a genuine structural scan of the candidate module
  (exported symbols) and reports `apprentice: "not-wired (structural scan only)"`. Apprentice is not
  invoked; a text-only transition is not counted as an integration.
- **Howdex (REMEMBER):** not invoked. No procedural-memory capture, no evidence-qualified promotion,
  and **no held-out fresh-agent transfer experiment** was run. No learning is claimed.
- **Workproof (ATTEST):** not invoked. The loop emits `ATTESTATION_READY` with the verified candidate's
  full git head + Sentinel receipt hash, but no Workproof receipt is produced or independently
  verified. No attestation is claimed.

These remain open work (tasks #23, #24) and are prerequisites for any future claim of a complete
Do→Model→Verify→Remember→Prove chain.

## SEVENTH — independent real-world benchmark: **PERFORMED, with an honest negative result**

Artifacts: [`BENCHMARK-MANIFEST-v0.2.0.json`](BENCHMARK-MANIFEST-v0.2.0.json) (frozen, sha256
`a380a1b7f30756d5af3026a94ec3f33f996d888f6819e048341ab0465c36d6cc`), [`BENCHMARK-RESULTS-v0.2.0.json`](BENCHMARK-RESULTS-v0.2.0.json),
[`BENCHMARK-REPORT-v0.2.0.md`](BENCHMARK-REPORT-v0.2.0.md) (generated from those two files by
`benchmark/harness.py report`, so no number is hand-transcribed).

**Corpus.** 6 tasks across 3 independently maintained permissively-licensed projects — `unjs/scule`
(MIT), `unjs/ufo` (MIT), `fb55/entities` (BSD-2-Clause). Every task is a real upstream defect fix; the
benchmark baseline is that fix commit's **parent**, so the agent faces the project's own genuine
pre-fix state. Acceptance criteria are assertions from the project's own test suite, and every expected
value was measured by executing the real code at both revisions rather than transcribed.

**Frozen before any agent ran**, and the freeze is enforced: `freeze` refuses to write a manifest while
any task fails its gate. Each task had to satisfy five *measured* conditions — baseline CONTRADICTED by
the pinned oracle; the project's own tests pass at that baseline (so they cannot see the defect);
upstream fix VERIFIED; tests pass at the fix; and applying only the upstream source change to the
frozen baseline still passes the baseline's own tests. That last condition is what makes arm A's
"ordinary tests only" rule fair, and it rejected four otherwise-good tasks (see below).

**Arms.** A = ordinary agent + the project's tests only. B = the same + independent Sentinel
verification, no repair. C = the same + ShipGuard's bounded counterexample-driven repair. A and B are
evaluated on one shared session per task, because B adds only a gate and gives the agent no feedback,
so pairing them is correct and running two sessions would add noise to a comparison meant to be paired.

**Agent.** The manifest planned Codex; Codex was authenticated but its usage limit was exhausted until
2026-11-08, so the run used **Claude Code 2.1.301** (re-authenticated, then probed — `acceptEdits`
plus an explicit `Read/Edit/Write` allowlist and a `Bash/WebFetch/WebSearch/NotebookEdit` denylist, no
permission-bypass flag). Corpus, prompts, contracts and oracle are byte-identical to the freeze.

**Measured result (12/12 cells, 2026-11-02T13:43:39Z → 13:53:04Z).**

| metric | value |
|---|---|
| arm A/B sessions | 6 |
| agent produced a change | 6 / 6 |
| ordinary tests green | 6 / 6 |
| independently VERIFIED | **6 / 6** |
| arm A false accepts | **0** |
| arm B false accepts | **0** |
| defects invisible to ordinary tests (aspirin instances) | **0** |
| arm C verified | 6 / 6 |
| arm C verified **after** a repair attempt | **0** |
| committed tree proven byte-identical to the verified candidate | 6 / 6 |
| changes confined to the allowed file | 6 / 6 |
| agent time / verification time (arm C) | 250.8 s / 31.9 s |

**The live agent solved all six real defects correctly on its first attempt.** The projects' own test
suites agreed with the independent oracle on every task, so there was no case where ordinary tests were
green while an approved requirement was violated — nothing for ShipGuard to catch, and no
counterexample to feed back.

This is reported as the outcome. The corpus was **not** expanded to obtain a favourable demonstration,
no task was weakened, no requirement was hidden from the prompt, and no prewritten or scripted
candidate was substituted. Per the mandate, a repair that did not naturally occur is not claimed.

**What the run does establish** is a verification result, not a detection or repair result: the full
pipeline works end to end against a live model on real third-party repositories — isolated clone, real
project tests, real pinned Sentinel, diff-derived scope enforcement, independent verification, and a
committed tree proven byte-identical to what was verified, on 6/6 tasks.

**What it does not establish:** any detection rate, repair rate or reliability improvement (there were
no detections to measure); anything about coding agents in general (one model, six tasks, not sampled
from a population); anything about hostile-agent containment (`local-advisory` runner, same OS
account).

**Candidates rejected during selection — all recorded in the manifest with the measured reason, so the
small corpus cannot be mistaken for cherry-picking.** `unjs/defu` (its real `__proto__`
prototype-pollution fix cannot survive Sentinel's contract parsing: an own `__proto__` data property is
normalised away, so the malicious input never reaches the code and ShipGuard's own integrity layer
correctly refused the receipt); `unjs/ohash` and `josdejong/jsonrepair` (Sentinel runs its **own**
vitest config over every `*.test.*` file, so test files that need a build step made its mandatory
ordinary-test checks CONTRADICTED at both baseline and fix); `unjs/pathe` (a devDependency imported by
source at every usable revision); `destr` (its suite asserts a V8 error string that Node 26 no longer
produces); `marked`, `smol-toml`, `radix3`, `mlly`, `confbox`, `untyped` (suites do not collect under
the pinned vitest with zero installs); `es-toolkit` (whole-suite cost); `remeda`, `hookable`, `exsolve`
(vetting cost / no pure single-export probe / machine-specific return values). Tasks dropped by the
gate: `scule-segment-lowering` (3815767), entities `914e397` and `05af0b3`, and two ufo tasks at 2023–24
revisions.

**A structural finding worth stating plainly:** Sentinel always records a mandatory `preserved-tests`
check that restores the baseline's test files and runs them against the candidate. A change that alters
any behaviour asserted by an existing test therefore can never be VERIFIED, however correct it is. The
class of tasks ShipGuard+Sentinel can verify is exactly the class whose fix **adds** assertions without
changing existing ones — which is also precisely the class where "ordinary tests are green but a real
requirement is violated" can occur. That is a genuine scope limit, not a tuning opportunity.

---

## Release gate evaluation

| # | Mandatory condition | Status |
|---|---|---|
| 1 | Real agent execution demonstrated | **MET** — 12 live Claude sessions on the frozen corpus (6 arm A/B + 6 arm C), all model-generated, plus 3 earlier live Codex runs |
| 2 | Ordinary tests and genuine Sentinel checks both run | **MET** — each project's own vitest suite + real `sentinel verify` at the pinned commit, structured content-addressed receipts |
| 3 | ≥1 real **agent-produced** defect independently contradicted | **NOT MET — measured, not assumed.** Across 6 frozen real-world tasks the live agent produced 0 defects: 6/6 were independently VERIFIED and arm A/arm B false accepts were both 0. No contradiction occurred, so nothing was detected. I did not weaken a task, hide a requirement, or expand the corpus to force one |
| 4 | Counterexample feedback drives a genuine **repair attempt** | **NOT MET with a live agent** — 0 of 6 arm-C runs needed a repair (all verified on attempt 0), so no counterexample was ever fed back. The loop itself is proven with the offline adapter + real Sentinel (`tests/test_sentinel.py::test_offline_repair_loop_end_to_end_with_real_sentinel`), but that is not live-agent evidence |
| 5 | Repaired candidate independently rechecked | **MET** — real Sentinel re-verification; and on all 6 arm-C runs the committed tree was proven byte-identical to the verified candidate (`tree_binding.equivalent` 6/6) |
| 6 | Unsafe agent execution permissions removed | **MET** — `--dangerously-skip-permissions` gone; supported sandbox/permission controls; tested (`tests/test_adapters.py`, 8 tests) |
| 7 | Apprentice/Howdex/Workproof real **or** explicitly excluded | **MET (excluded)** — see FIFTH |
| 8 | Historical v0.1.2 security controls still pass | **MET** — `tests/test_trust_boundary.py` still exactly 31 tests, unchanged, passing within the 128 |
| 9 | Clean installation reproduces the supported workflow | **MET** — wheel → fresh venv → doctor/demo/run from unrelated cwd |
| 10 | CI passes against the exact release commit | **MET** on `59ab439` — run [41460094532](https://github.com/Actenon/actenon-shipguard/actions/runs/41460094532): `verify (3.11)` 120 passed / 8 deselected, `verify (3.12)` 120 passed / 8 deselected, `sentinel-integration` 8 passed / 120 deselected, **0 skipped** in every job, with the pipefail + `${PIPESTATUS[0]}` control in force. An earlier claim of MET on `6d3a6b4`/`e238281` is **withdrawn as a false green** — see below |
| 11 | Every limitation honestly documented | **MET** — this document plus `BENCHMARK-REPORT-v0.2.0.md` §7 and the manifest's measured exclusion reasons |

### The two claims, separated

**Claim 1 — limited verification (SUPPORTED).** On real third-party repositories, ShipGuard can take a
live coding agent's change, run the project's own tests, obtain an independent content-addressed
verification receipt from a pinned external verifier, enforce the change scope from the real diff, and
commit a candidate whose tree is provably byte-identical to what was verified. Measured: 6/6 tasks,
3 independently maintained projects, 0 out-of-scope changes, 0 stale or substituted receipts.

**Claim 2 — the "developer aspirin" (NOT SUPPORTED).** That ShipGuard catches defects ordinary tests
miss and repairs them from counterexample feedback. Measured: **0 detections and 0 repairs**, because
the live agent was correct on all six tasks. Claim 2 is not merely unproven here — this corpus provides
no evidence for it in either direction, since the condition that would exercise it never arose. It must
not be advertised.

**Decision: NO-GO for publishing v0.2.0 as the "developer aspirin" milestone.** Gate conditions 3 and 4
are not satisfied, and they cannot be satisfied honestly on this corpus because the agent did not fail.
I will not fabricate, sandbag, or rig a live-agent defect to force them, and I will not describe the
six successful verifications as a reliability improvement.

A **scoped pre-release of Claim 1 only** was technically eligible: every other condition is met, the
suite is 128 passing / 0 skipped, and the artifacts are independently checkable. It was withheld until
authorised. **On 2026-11-02 the repository owner authorised exactly that scoped preview** — see
"v0.2.0-preview.1" below. Claim 2 remains unauthorised and unreleased.

**What would flip Claim 2 to GO:** a live-agent run on a corpus where the agent *naturally* produces at
least one change that the project's own tests accept while the independent oracle contradicts it, and
where the counterexample then drives a real repair to independent re-verification. The machinery, the
frozen corpus, the gate and the reporting are all built and tested; what is missing is an honest
failure, which is a property of the agent and the task difficulty — not something a code change can
supply. Two concrete paths: (a) re-run when Codex's quota resets on 2026-11-08, since a different model
may fail where Claude did not, and the harness records the agent actually used; (b) extend the corpus
within the measured constraints to harder add-only tasks (larger diffs, multi-file scope, subtler
boundary conditions) — declared and frozen in advance, never after seeing a result.

### CI status and a corrected false green

An earlier revision of this document recorded condition 10 as **MET**, citing CI run `41434542606`
green on commit `6d3a6b4`/`e238281`. **That evidence was wrong and is withdrawn.** The run's own log
contains four adapter-test failures; the step still exited 0 because the workflow used
`pytest … | tee` without `pipefail`, so tee's status became the pipeline's status. The Phase 1
hardening (`set -euo pipefail` plus an explicit `${PIPESTATUS[0]}` assertion, with a negative control
proving it has teeth) is what turned that hidden failure into a red job. In other words: the control
added in Phase 1 immediately caught a false green that had been accepted as release evidence.

The underlying failures were environment dependence in the *tests*, not defects in the product:

- Four adapter tests asserted confinement, consent gating and auth-probe behaviour but never stubbed
  `shutil.which`, so on a runner with no `codex`/`claude` binary `available()` short-circuited to
  "CLI not found" and those assertions never actually exercised the adapter. Fixed by stubbing the
  CLI's presence through one shared helper (`59ab439`).
- Ten safe-mode tests symlinked a shared `node_modules` resolved from a sibling Sentinel checkout
  that does not exist on a runner, so `Path.symlink_to(None)` raised `TypeError`. Fixed with a stub
  directory; tests that actually execute vitest remain marked `sentinel_integration` and still
  require the real prerequisite, so the stub cannot mask a missing one (`59ab439`).
- Separately, `clone_isolated` did not set a git identity in the disposable clone. A clone does not
  inherit the source's local config and a runner has no global identity, so committing the *verified*
  candidate died with exit 128 — safe mode could verify a real repository and then fail at the last
  step. This one was a genuine product bug, fixed in `af92ca7` with a regression test that
  neutralises `HOME`, `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM`, confirmed by negative control.

All three were invisible locally because this machine has the CLIs, the sibling checkout, and a
global git identity. Verified under a faithful simulation of the runner (no sibling `node_modules`,
no `codex`/`claude`): 120 passed, 8 deselected, 0 failed, 0 skipped.

Condition 10 is recorded as MET only against a run that is green on the exact commit being described,
with the run id stated, and only after the pipefail control is in place.

Runs after the fix, all green with **0 skipped** in every job (`verify (3.11)` 120 passed / 8
deselected, `verify (3.12)` 120 passed / 8 deselected, `sentinel-integration` 8 passed / 120
deselected):

| commit | run | content |
|---|---|---|
| `59ab439` | [41460094532](https://github.com/Actenon/actenon-shipguard/actions/runs/41460094532) | last commit changing executable code or tests |
| `751fb54` | 41460468709 | documentation only (this withdrawal) |
| `f0c16a3` | 41460867080 | documentation only (report reproduction steps) — branch tip at the time of writing |

The commit that adds this table is itself documentation-only and re-runs the same workflow; its run id
is reported in the conversation rather than chased into the file, since recording it would require
another commit ad infinitum.

---

## Limitations (honest scope)

- **Local runner is advisory.** `sentinel verify --runner local` executes candidate code under the same
  OS account; it is **not** a security boundary (Sentinel states this; the receipt records it). Isolated
  execution needs `--runner docker` (not used here; Docker is out of scope on this machine).
- **Acceptance is bounded by the approved contract.** Sentinel checks the supplied examples, invariant
  seeds and probes; passing them is **not** a proof of arbitrary correctness. A change that alters
  behaviour outside any approved requirement yields `REVIEW REQUIRED` (correctly not auto-accepted).
- **Hold-out is timing/prompt-based, not cryptographic.** The contract + store are outside the agent
  repo and not referenced in the prompt, and the candidate is materialised before verification; but a
  `workspace-write` sandbox confines **writes**, not all **reads**. True read-isolation needs OS
  sandboxing.
- **Provider availability is probed, never assumed.** At the time of the benchmark run Claude Code was
  authenticated (and ran the benchmark) while Codex was authenticated but usage-limited until
  2026-11-08. Earlier in this milestone the reverse was true. An unavailable or exhausted provider is
  recorded as `unavailable` and the benchmark refuses to run — no model activity is ever fabricated, and
  no offline or scripted candidate is substituted for a live one.
- **Claude's confinement is permission-based, not OS-isolation.** `acceptEdits` plus a `Read/Edit/Write`
  allowlist and a `Bash/WebFetch/WebSearch/NotebookEdit` denylist constrain what the agent may *do*, but
  the file tools are not confined to the candidate directory the way Codex's `workspace-write` sandbox
  confines writes. The held-out contract and receipt store live outside the repository and are never
  referenced in the prompt, but this is prompt/timing hold-out, not read isolation.
- **The benchmark measured one model on six tasks.** No detection rate, repair rate, false-positive
  rate or reliability improvement can be inferred from it, and none is claimed. Agent runs are not
  bit-reproducible; everything around them (corpus, contracts, validation, aggregation, report) is
  deterministic from the pinned commits.
- **Verifiable task class is narrow.** Because Sentinel's mandatory `preserved-tests` check replays the
  baseline's own tests against the candidate, any correct change that alters an existing assertion is
  unverifiable by construction. Behaviour-change and refactor tasks are out of scope for this verifier.
- **Apprentice/Howdex/Workproof are not integrated** (excluded above).
- **External runtime dependencies:** Node, tsx, and a built Sentinel are required for the real
  verification path (`doctor` reports them; CI provisions them). The benchmark additionally needs the
  corpus projects' own suites to collect under the pinned vitest with zero installs.
- **Not claimed:** general correctness, hostile-agent containment, stable v1.0.0, npm/PyPI
  distribution, a complete repair-loop product, any benchmark improvement percentage, or the
  "developer aspirin" framing.
