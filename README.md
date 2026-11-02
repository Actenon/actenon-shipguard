# Actenon ShipGuard

> **Your AI agent says it's done. ShipGuard checks before it ships.**

An AI coding agent can produce a change that passes the tests it ran while violating an
important requirement. ShipGuard exists for that specific failure: **an agent's declaration
of success must never substitute for independent evidence that the change satisfies its
approved requirements** — and, for explicitly protected operations, a consequential action
must not execute without authority *and* verified correctness.

Two pre-releases are published, and they claim **different things**.

**`v0.1.2`** — the security-remediation pre-release: the protected-execution trust boundary is
complete and adversarially tested (31 tests, still passing byte-identical inside the current 128), the
enforcer holds **no signing key**, and the wheel installs non-editably and runs from an unrelated cwd.
PR #1 was merged to `main` with a **merge commit** on 2026-11-02, so `main` now matches that published
tag; the tag itself was not moved and its history was not rewritten.

**`v0.2.0-preview.1`** (distribution version `0.2.0rc1`) — a **scoped verification-only developer
preview**. What it claims, and what it deliberately does not:

| Claimed (measured) | **Not** claimed |
|---|---|
| Real coding-agent integration — a live model makes the change | Demonstrated detection of live-agent defects |
| Independent acceptance verification by a pinned external oracle | Successful live counterexample-driven repair |
| Approved change-scope enforcement from the real diff | General correctness |
| Candidate-to-commit identity checking (committed tree proven byte-identical to the verified candidate) | Any measured reliability improvement |
| Evidence reporting within the tested scope | Production-grade hostile-agent containment |

**The benchmark result is null and is reported prominently, not buried.** Across 6 frozen real
historical defects in 3 independently maintained projects, Claude Code produced a correct fix on all 6
at its first attempt. Independent verification agreed 6/6 and each project's own suite agreed 6/6, so
there were **0 additional defects detected and 0 repairs performed**. See
[`BENCHMARK-REPORT-v0.2.0.md`](BENCHMARK-REPORT-v0.2.0.md) and
[`RELEASE-EVIDENCE-v0.2.0.md`](RELEASE-EVIDENCE-v0.2.0.md).

Read that result carefully, because the two halves are easy to conflate:

- **0 false accepts on correct candidates** is what was measured. The oracle never rejected a change
  that was actually right — useful evidence that verification does not cry wolf.
- That is **not** a measured ability to detect *incorrect* candidates. No incorrect candidate was ever
  produced by the live agent, so detection rate was never exercised and is **unknown**, not zero and
  not high. The only contradictions observed in this milestone came from seeded fixture defects and
  from the corpus's own pre-fix baselines, not from live-agent output.

**Validating this yourself requires the reproduction workflow.** The committed run records are
portable: they deliberately do **not** contain the original raw Sentinel receipts, because those
receipts are content-addressed and embed absolute machine-local paths (`git.root` and the scratch
execution directories). Shipping them would leak local filesystem layout and would not verify anywhere
else. The portable records keep the receipt hashes, verdicts, requirement outcomes, counterexamples and
integrity results — enough to audit the *logic*, not enough to re-verify cryptographically offline. To
check the receipts themselves, run the documented reproduction workflow in
[`BENCHMARK-REPORT-v0.2.0.md`](BENCHMARK-REPORT-v0.2.0.md) §8, which rebuilds the pinned oracle and
regenerates receipts locally.

Memory transfer, attestation verification and npm distribution remain **explicit release blockers**,
tracked in [`RELEASE-EVIDENCE.md`](RELEASE-EVIDENCE.md) and
[`SECURITY-REMEDIATION-v0.1.2.md`](SECURITY-REMEDIATION-v0.1.2.md). Do not mistake the recorded
PASS output for a v1.0 security guarantee.

---

## What it does (today, in this pre-release)

ShipGuard gates a consequential action behind **two independent signed authorities**:

```
                 ┌─ AUTHORITY  ── Actenon PCCB proof (ed25519): audience · time · action-hash · single-use nonce
consequential    │
action ──────────┤              correctness certificate bound INTO the signed action constraints
                 └─ CORRECTNESS ─ independent ed25519 prover: property-verify (whole bug class, 200k
                                  inputs, counterexample shrinking) + structured Sentinel receipt
```

Rule enforced: **no valid proof AND no verified correctness certificate → no execution.**
The verified artifact is the artifact that actually executes (mediated invocation, hash-bound),
and a dispatched action cannot be blindly replayed (durable atomic nonce).

### The four separated parties (the trust boundary)

| Party | Holds | Can |
|---|---|---|
| Authority issuer | Actenon proof signing key | mint PCCB proofs (no dispatch/handoff capability — the enforcer re-verifies the original evidence) |
| Correctness prover | certificate signing key | sign correctness certificates |
| Enforcer (gate/resource) | **only pinned public trust roots** | verify + invoke certified code; **cannot sign** |
| Requester (coding agent) | **no key** | request; **cannot forge** a cert, proof or authorization |

Trust roots are pinned externally (`trust-roots.json`, RFC 7638 thumbprints). A certificate
carries only the prover's `key_id` — never its public key — so an agent cannot substitute a
self-generated key.

## Install

Python 3.11+, Node (for the bundled TypeScript property verifier). Dependencies are **pinned
to released versions** (no moving upstream main):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .            # actenon-kernel==1.2.1, actenon-protocol==1.4.0,
                         # actenon-permit==1.4.0, actenon-scan==1.5.0, cryptography==44.0.0
actenon-shipguard doctor # environment diagnostics
```

## Use

```bash
actenon-shipguard init                 # bootstrap pinned trust roots + shipguard.json
actenon-shipguard demo                 # deterministic offline protected-execution matrix
actenon-shipguard demo --open          # ... and open the self-contained HTML evidence report
actenon-shipguard verify --cert C --trust-roots R   # independently verify a certificate
actenon-shipguard report --out DIR --open            # render the HTML report
```

`actenon-shipguard run "task" --agent codex|claude|offline [--contract C]` (the real coding-agent
repair loop) ships in **`v0.2.0-preview.1`**: it drives a real agent change, runs the project's own
tests, and uses the **real Sentinel verifier** (structured, content-addressed receipts) as the
independent acceptance authority, feeding a reproducible counterexample back to drive a bounded repair.
The loop refuses to run without a real authenticated provider — an exhausted quota is recorded as
`unavailable`, never as a repair failure, and no offline or scripted candidate is substituted.

**The full "developer aspirin" release is still NO-GO.** The independent real-world benchmark ran 6
frozen historical defects across 3 third-party projects against a live agent, and the agent was
**correct on all 6 first attempt**: 0 detections, 0 repairs, 0 false accepts in either arm. The
verification pipeline worked end to end (6/6 independently verified, every committed tree proven
byte-identical to the verified candidate, every change inside its allowed file), but that is a
*verification* result and gives no support to a "catches the defects your tests miss" claim, so that
claim is not made and the preview is scoped accordingly. See
[`BENCHMARK-REPORT-v0.2.0.md`](BENCHMARK-REPORT-v0.2.0.md) and
[`RELEASE-EVIDENCE-v0.2.0.md`](RELEASE-EVIDENCE-v0.2.0.md). On **v0.1.2**, `run` still reports
"not wired" rather than faking success.

### What `demo` proves (real, measured)

```
1 correct fix (authorised + class-verified)      -> ALLOW   [OK/AUTHORISED_AND_CORRECT]
2 wrong fix, green tests, valid authority        -> REFUSE  [CORRECTNESS/NOT_VERIFIED]
3 certified for B, executed bytes swapped to A   -> REFUSE  [CORRECTNESS/CODE_ARTIFACT_MISMATCH]
4 blind replay of the committed disbursement     -> REFUSE  [REPLAY/NONCE_REUSED]
5a crash mid-effect (nonce reserved, no record)  -> REFUSE  [EXECUTION/EFFECT_UNCERTAIN]
5b blind retry of uncertain outcome              -> REFUSE  [REPLAY/UNCERTAIN_OUTCOME]
6 certificate signed by untrusted prover key     -> REFUSE  [CORRECTNESS/CERT_UNTRUSTED]
7 enforcer key-less + tampered proof refused     -> REFUSE  [ENFORCEMENT/KEYLESS_ENFORCER]
```

The ALLOW in scenario 1 is a **real mediated invocation**: `tsx` imports the exact certified
`settle.ts` and calls `allocate(1000000, 3)`; the disbursement record is produced by that call
(`conserved: true`), not written synthetically.

## Tests

```bash
pip install '.[dev]' && pytest -q     # 31 adversarial trust-boundary tests
```

Covering: mediated invocation, bypass refusal, forged receipt, contract substitution, stale
receipt, code replacement, untrusted signing key, authority-proof tamper, replay, concurrent
nonce claim (exactly one winner), crash-with-uncertain-outcome, blind-retry refusal, nonce
durability across restart, **intent-equality authorisation binding** (small-auth-reused-for-larger,
export/resource/module substitution), **key-less enforcer** (no signing key held; tampered proof
refused at the only execute path), **cross-domain signature rejection**, **Sentinel receipt
coverage + anti-fabrication** (zero/unrelated/partial checks; refabricated-and-rehashed receipt),
**signed nonce reconciliation** (forged signer, wrong effect, no caller callback, fail-closed),
and **key-storage isolation** (no private key in the workspace; isolated mode fails closed).

## Modes (honest capability status)

- **Mode C — protected consequential execution: implemented + adversarially tested** (this pre-release).
  A *cooperative local* boundary: it proves an action cannot traverse the configured gate without
  policy, but it is **not** an unbypassable OS sandbox — a rogue agent that refuses to call the gate
  is not stopped by it. Hard containment needs Actenon airlock Protected Mode + containers.
- **Mode A — local development repair loop: shipped in `v0.2.0-preview.1`, scoped to verification
  only.** Real Sentinel is the acceptance authority. Provider availability is probed at run time,
  never assumed: the benchmark ran on **live Claude Code** (`acceptEdits` + a file-only tool allowlist,
  no permission-bypass flag) after Codex's usage limit was exhausted; an unavailable provider is
  recorded as `unavailable` and the run refuses to proceed rather than fabricating model activity.
  The **defect-detection and automatic-repair benefit is not established**: the benchmark produced 0
  detections and 0 repairs because the agent was already correct on all 6 tasks (see
  `BENCHMARK-REPORT-v0.2.0.md`, `RELEASE-EVIDENCE-v0.2.0.md`). Testing of that claim continues.
- **Mode B — PR protection / GitHub Actions: scaffolded, not validated** (workflow present, unrun).

## Relationship to the ecosystem

ShipGuard **orchestrates**; it does not duplicate Actenon primitives. Actenon Scan = DISCOVER,
Kernel/Permit = AUTHORISE, Airlock = ENFORCE, Sentinel + property verification = CHALLENGE,
Apprentice = MODEL, Howdex = REMEMBER, Workproof = ATTEST. The reproducible integration
experiment that preceded this product is
[`rossbuckley1990-hash/one-action-kernel`](https://github.com/rossbuckley1990-hash/one-action-kernel).

## License

Apache-2.0. See [LICENSE](LICENSE).
