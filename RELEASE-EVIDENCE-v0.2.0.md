# RELEASE-EVIDENCE-v0.2.0.md — Actenon ShipGuard

**Milestone: v0.2.0 "developer aspirin" — a real coding agent makes a change, ShipGuard
independently verifies it against a held-out approved contract, and (on contradiction) feeds a
reproducible counterexample back to drive a genuine repair.**

**Release decision: NO-GO for publishing v0.2.0.** The branch is retained, fully tested, and
documented. One mandatory release-gate condition is **not** satisfied honestly: *a live
agent-produced defect independently contradicted, driving a live counterexample-based repair.*
The live agent (Codex, ChatGPT-authenticated) produced **correct** implementations on every
well-specified task tested — which real Sentinel independently **VERIFIED** — and, on an
under-specified task, correctly **asked for clarification instead of guessing**. I did not
fabricate, sandbag, or rig a defect to force the gate. See "Release gate" below.

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

Pinned stack (unchanged): `actenon-kernel==1.2.1`, `actenon-protocol==1.4.0`, `actenon-permit==1.4.0`,
`actenon-scan==1.5.0`, `cryptography==44.0.0`. External verifier: **Sentinel** pinned at commit
`becba502c8dbebdd5e52b8ca09122f86e4e37bb3` (github.com/rossbuckley1990-hash/sentinel-verified, v1.0.0).
Live agent: **Codex CLI 0.163.0** (authenticated, "Logged in using ChatGPT"). **Claude Code 2.1.301
OAuth is EXPIRED** in this environment → live Claude is disabled (see SECOND).

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

pytest -q                                   # 51 passed (36 core + 15 Sentinel)
pytest -q -m "not sentinel_integration"     # 48 passed, 3 deselected (core job)
pytest -q -m sentinel_integration           # 3 passed (real Sentinel CLI)

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

## SEVENTH — independent benchmark: **NOT performed**

No multi-codebase, held-out-acceptance benchmark comparing ordinary vs ShipGuard-assisted execution was
run. No defect-detection rate, repair rate, false-positive rate, token or time comparison is claimed.
The three live-Codex runs above are illustrative single-task results, **not** a benchmark. Constructing
a harder, multi-codebase task corpus is the natural path to exercising (and measuring) the live-agent
defect→repair path that this NO-GO turns on.

---

## Release gate evaluation

| # | Mandatory condition | Status |
|---|---|---|
| 1 | Real agent execution demonstrated | **MET** — 3 live Codex runs, model-generated changes |
| 2 | Ordinary tests and genuine Sentinel checks both run | **MET** — vitest + real `sentinel verify`, structured receipts |
| 3 | ≥1 real **agent-produced** defect independently contradicted | **NOT MET** — live agent produced correct code; contradiction shown only on fixture defects (real Sentinel) |
| 4 | Counterexample feedback drives a genuine **repair attempt** | **PARTIAL** — proven with the offline adapter + real Sentinel; **not** with a live agent (no live defect to repair) |
| 5 | Repaired candidate independently rechecked | **MET** — real Sentinel re-verification (offline loop + live correct fixes) |
| 6 | Unsafe agent execution permissions removed | **MET** — `--dangerously-skip-permissions` gone; supported sandbox/permission controls; tested |
| 7 | Apprentice/Howdex/Workproof real **or** explicitly excluded | **MET (excluded)** — see FIFTH |
| 8 | Historical v0.1.2 security controls still pass | **MET** — 31 tests unchanged within the 51 |
| 9 | Clean installation reproduces the supported workflow | **MET** — wheel → fresh venv → doctor/demo/run from unrelated cwd |
| 10 | CI passes against the exact release commit | **PENDING** — branch push + CI (core + sentinel-integration jobs) |
| 11 | Every limitation honestly documented | **MET** — this document |

**Decision: NO-GO for publishing v0.2.0.** Conditions 3 and 4 are not satisfied with a live agent, and
I will not fabricate or rig a live-agent defect to force them. The tested branch is retained. This is
the disciplined outcome the mandate prescribes when a mandatory gate is unmet.

**What would flip this to GO:** a genuine live-agent run on a task hard enough (or a benchmark corpus
broad enough) that the agent's **own** first attempt is contradicted by real Sentinel and the
counterexample drives a real repair to independent re-verification — plus CI green on the exact commit.
The machinery to do this is built and tested; the missing piece is an honest live-agent defect, which
needs a harder task corpus (SEVENTH), not a code change.

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
- **Live Claude is disabled** (expired OAuth + unvalidated confinement); live Codex is authenticated.
  No model activity is ever fabricated when a provider is unavailable.
- **Apprentice/Howdex/Workproof are not integrated** (excluded above).
- **External runtime dependencies:** Node, tsx, and a built Sentinel are required for the real
  verification path (`doctor` reports them; CI provisions them).
- **Not claimed:** general correctness, hostile-agent containment, stable v1.0.0, npm/PyPI
  distribution, a complete repair-loop product, or any benchmark improvement percentage.
