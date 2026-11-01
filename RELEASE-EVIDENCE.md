# RELEASE-EVIDENCE.md — Actenon ShipGuard v0.1.1 (pre-release)

Every headline claim below links to inspectable evidence or is marked **BLOCKER** with the
exact reproducible reason. Nothing here is inferred from a string in stdout.

## Release gate decision

**NO-GO for stable v1.0.0.** This is a truthful **v0.1.0 pre-release**. The protected-execution
trust boundary (mandate §6) is implemented and adversarially tested; the real coding-agent repair
loop, memory transfer, attestation verification, benchmarks, CI execution and npm distribution are
**not** complete and are listed as blockers below. Per the mandate, v1.0.0 is withheld because a
supported developer workflow (real-agent edit→challenge→repair→reverify) is not yet demonstrated
and npm publication is not done.

## 1. Repository identity

- Foundation experiment (preserved, unmodified): `rossbuckley1990-hash/one-action-kernel`
  starting commit **`8cc95c48d9a4839481095bc0fd194192ad1533b2`**.
- Product repository: `Actenon/actenon-shipguard` (created fresh; no existing repo/package overwritten).
- Release history: `v0.1.0` (commit `03c4b73`) shipped with a CI workflow-YAML bug; fixed on `main`
  at `0254639`. This pre-release is **`v0.1.1`** (CI green). No tag was force-moved or release
  silently replaced — the version was bumped forward instead.

## 2. Pinned dependency identities (no moving main branches)

| Component | Pinned identity | How verified |
|---|---|---|
| actenon-kernel | `==1.2.1` (PyPI release) | `pip show`; fusion APIs smoke-tested against it |
| actenon-protocol | `==1.4.0` | `pip show` |
| actenon-permit | `==1.4.0` | `pip show` |
| actenon-scan | `==1.5.0` | `pip show` |
| cryptography | `==44.0.0` | `pip show` |
| sentinel-verified | commit `becba502c8dbebdd5e52b8ca09122f86e4e37bb3` (v1.0.0) | `git rev-parse HEAD` |

**Compatibility finding (acted on):** the released `actenon-kernel==1.2.1` `PCCBMinter.mint` has
**no `extensions` parameter** and `VerifierSDK` has no `effect_protector` (those exist only in the
unreleased candidate `1.3.0`). ShipGuard therefore binds the correctness certificate through the
**action `constraints`**, which the signed `action_hash` already covers. Empirically verified:
tampering the bound digest yields `PROOF_INVALID`. Replay protection is implemented natively
(`nonce.py`) rather than depending on the candidate-only `effect_protector`.

## 3. Tested installation command

```bash
python3 -m venv .venvs/release && . .venvs/release/bin/activate
pip install -e .            # resolves the pinned stack above
actenon-shipguard doctor    # -> all [ok]; pinned versions printed; claude+codex detected
```
Result: package imports (`actenon_shipguard 0.1.0`), `doctor` reports all dependencies present.

## 4–5. Working local-development + deterministic demonstration commands

```bash
actenon-shipguard demo --out evidence/shipguard-demo --trials 200000
```
Result: **DEMO RESULT: PASS** — 1 ALLOW + 7 REFUSE (raw below). Evidence:
`evidence/shipguard-demo/demo-summary.json`, self-contained offline HTML
`evidence/shipguard-demo/shipguard-report.html`.

## 6. Real coding-agent execution evidence — **BLOCKER**

`claude` (2.1.301) and `codex` (0.163.0) CLIs are installed and detected by `doctor`, but the
real-agent repair loop (task → genuine model edit → ordinary tests → independent challenge →
counterexample → repair → reverify) is **not wired** in v0.1.0. `actenon-shipguard run --agent
claude|codex` exits 2 with an honest "not wired" message rather than simulating success. The
`offline` deterministic mode is separately labelled and is what `demo` exercises.

## 7. Concrete defects caught after ordinary tests passed — **YES**

The `arm-a-rounding` candidate (`Math.round` allocation) passes all 4 ordinary vitest tests green
yet violates conservation of pennies. property-verify (200,070 inputs) returns **VIOLATED** with a
shrunk minimal counterexample; the gate refuses it (`CORRECTNESS/NOT_VERIFIED`) despite a *valid*
Actenon authority proof. Evidence: `evidence/shipguard-demo/demo-summary.json` scenario 2.

## 8. Real repair attempt + independently checked outcome — **BLOCKER**

Depends on §6 (real-agent loop). The deterministic offline mode uses prewritten candidates
(preserved as a regression fixture per mandate §7), not a live model repair.

## 9. Howdex learning + held-out transfer — **BLOCKER**

Not implemented in v0.1.0. No scripted Howdex success logs are claimed (the earlier experiment's
scripted traces are explicitly not carried forward as evidence).

## 10. Independently validated Workproof receipts — **BLOCKER**

Not implemented in v0.1.0. `workproof verify` exists in the toolchain but is not yet wired with
correct policy + full git identities + separate-process verification + negative controls.

## 11. Actenon protected-execution results + bypass tests — **YES**

Raw `demo` matrix (200k trials):
```
1 correct fix (authorised + class-verified)      -> ALLOW   [OK/AUTHORISED_AND_CORRECT]
2 wrong fix, green tests, valid authority        -> REFUSE  [CORRECTNESS/NOT_VERIFIED]
3 certified for B, executed bytes swapped to A   -> REFUSE  [CORRECTNESS/CODE_ARTIFACT_MISMATCH]
4 blind replay of the committed disbursement     -> REFUSE  [REPLAY/NONCE_REUSED]
5a crash mid-effect (nonce reserved, no record)  -> REFUSE  [EXECUTION/EFFECT_UNCERTAIN]
5b blind retry of uncertain outcome              -> REFUSE  [REPLAY/UNCERTAIN_OUTCOME]
6 certificate signed by untrusted prover key     -> REFUSE  [CORRECTNESS/CERT_UNTRUSTED]
7 direct resource call without gate authorization-> REFUSED (no side effect)
```
The ALLOW is a real mediated invocation (tsx imports the certified artifact and calls
`allocate(1000000,3)`; record shows `conserved: true`). Bypass (scenario 7) raises
`PermissionError` and writes no side effect.

## 12. Adversarial test results — **PARTIAL (13 of the 28-case matrix)**

```bash
pytest tests/test_trust_boundary.py -q   # -> 13 passed
```
Passing: mediated invocation, bypass refusal, forged receipt (content-address break), contract
substitution, stale receipt / source drift, code replacement after certification, untrusted prover
key, authority-proof tamper, replay, concurrent nonce (8 threads → exactly 1 winner), crash with
uncertain outcome, blind-retry refusal, nonce durability across restart.
**Remaining matrix cases (§13 items 3, 10, 11, 15, 16, 20–23, 25–28) are BLOCKERS** (refactor
equivalence, dependency-change review, hidden-input access, Howdex promotion, stale procedure,
unsupported language, agent CLI unavailable, missing dependency, interrupted/resumed session,
fresh-clone, fixture tamper).

## 13. CI results — **GREEN (executed on GitHub)**

`.github/workflows/ci.yml` ran on push to `main`: run
[41354658157](https://github.com/Actenon/actenon-shipguard/actions/runs/41354658157) — **success**
on `ubuntu-latest`, matrix Python 3.11 (26s) + 3.12 (28s). Steps: pinned `pip install -e '.[dev]'`,
global `tsx`, `actenon-shipguard doctor`, `pytest -q` (13 passed), and the offline demo (ALLOW
verdict confirmed). Only non-blocking annotations (Node 20 deprecation; ubuntu-latest migration).
The initial `v0.1.0` tag predates a workflow-YAML fix; CI is green from commit `0254639` (v0.1.1).
The consumable GitHub Action (`action.yml`) is committed but has **not** been exercised as a
third-party action — that validation remains a blocker.

## 14. Fresh-install reproduction — **PARTIAL (Linux CI + macOS local)**

Reproduced from a fresh checkout on GitHub-hosted `ubuntu-latest` (CI run 41354658157, Python 3.11
+ 3.12) and locally in a clean pinned venv on Apple Silicon macOS (Python 3.14.6). A
from-the-published-PyPI/npm-package reproduction remains a **BLOCKER** (not yet distributed).

## 15. Benchmark measurements — **BLOCKER**

The aspirin benchmark (ordinary agent vs +independent verification vs full ShipGuard, across
multiple independently-labelled projects, held-out cases) is **not run**. No superiority claim is
made. The only measurement produced is the single settlement fixture (deliberately not 20
variations of it).

## 16. Known limitations

- **Cooperative local boundary, not an unbypassable sandbox.** The gate enforces where it is
  installed; a rogue agent that refuses to call it is not stopped. Hard containment requires
  Actenon airlock Protected Mode + containers (Docker), deliberately out of scope here.
- **Local asymmetric signer.** Real ed25519 with separated authorities and externally pinned trust
  roots, but single-host. Production custody (KMS/HSM, `/.well-known/actenon/keys.json` serving,
  key rotation ceremonies) is documented in `trust.py` but not deployed.
- **Sampled ≠ proof.** 200,070 inputs with shrinking is strong evidence over the declared
  invariants, not exhaustive mathematical correctness.
- **Offline demo Sentinel receipt** is a faithful locally-built content-addressed store, not a live
  `sentinel verify` run; the real Sentinel integration belongs to `run` mode (blocker §6).
- **Scope:** deterministic JS/TS functions with JSON I/O + declared properties only.

## 17. Outstanding release blockers (v1.0.0 gate)

1. Real Claude/Codex repair loop wired + tested (§6, §8).
2. Howdex real traces + held-out transfer benchmark (§9).
3. Workproof independent verification with negative controls (§10).
4. Full 28-case adversarial matrix (§12).
5. GitHub Action (`action.yml`) validated as a consumed action (the CI workflow itself is green, §13).
6. Multi-project aspirin benchmark with held-out cases (§15).
7. Zero-friction polyglot onboarding (bundle Sentinel + tsx; no manual venvs) and cross-platform
   fresh-install reproduction (§14).
8. Distribution: PyPI and/or npm `@actenon/shipguard`.

## 18. Honest go/no-go

**NO-GO for v1.0.0. Ship v0.1.1 pre-release.** The mandatory trust-boundary work (§6 A–E) is
complete and adversarially validated, and CI is green on a fresh Linux checkout (Python 3.11 +
3.12); the developer-facing real-agent product, memory/attestation integration, benchmarks, full
adversarial matrix and package distribution are not. Publishing v1.0.0 now would overstate the
evidence.

## Distribution / naming verification (per mandate §1)

- `Actenon/actenon-shipguard`: did not exist; created fresh (no overwrite). GitHub auth: admin of
  the `Actenon` org.
- npm `@actenon/shipguard`: name **available**; unscoped `shipguard` is **TAKEN (v1.2.1)** so the
  scoped name is mandatory. npm auth: `npm whoami` → `actenon` (scope owner), token stored only in
  user-level `~/.npmrc`, `.gitignore`-guarded, confirmed absent from the repo.
- **npm publication is a BLOCKER**: the v0.1.0 package is Python (pip-installable `actenon-shipguard`);
  the Node `@actenon/shipguard` wrapper is not built. No claim is made that `npx @actenon/shipguard`
  works. Publication will follow a real `npm publish --dry-run` + post-publish registry test.

## Reproduce

```bash
git clone https://github.com/Actenon/actenon-shipguard && cd actenon-shipguard
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q                                   # 13 passed
actenon-shipguard doctor                    # all [ok]
actenon-shipguard demo --trials 200000      # DEMO RESULT: PASS
```
