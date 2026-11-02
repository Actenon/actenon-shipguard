# Actenon ShipGuard

> **Your AI agent says it's done. ShipGuard checks before it ships.**

An AI coding agent can produce a change that passes the tests it ran while violating an
important requirement. ShipGuard exists for that specific failure: **an agent's declaration
of success must never substitute for independent evidence that the change satisfies its
approved requirements** — and, for explicitly protected operations, a consequential action
must not execute without authority *and* verified correctness.

The **v0.1.2 security-remediation pre-release** is published: the protected-execution trust
boundary is complete and adversarially tested (31 tests), the enforcer holds **no signing key**,
and the wheel installs non-editably and runs from an unrelated cwd. **v0.2.0 (the real
coding-agent repair loop) is in development** on the `v0.2.0` branch. The real-agent loop,
memory transfer, attestation verification, benchmarks and npm distribution remain **explicit
release blockers** tracked in [`RELEASE-EVIDENCE.md`](RELEASE-EVIDENCE.md) and
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

`actenon-shipguard run "task" --agent claude|codex` (the real coding-agent repair loop) is
**not wired in v0.1.2** — it reports this honestly rather than faking success. It is the
primary deliverable of the in-development **v0.2.0**.

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
- **Mode A — local development repair loop: blocked** (real Claude/Codex adapter not wired).
- **Mode B — PR protection / GitHub Actions: scaffolded, not validated** (workflow present, unrun).

## Relationship to the ecosystem

ShipGuard **orchestrates**; it does not duplicate Actenon primitives. Actenon Scan = DISCOVER,
Kernel/Permit = AUTHORISE, Airlock = ENFORCE, Sentinel + property verification = CHALLENGE,
Apprentice = MODEL, Howdex = REMEMBER, Workproof = ATTEST. The reproducible integration
experiment that preceded this product is
[`rossbuckley1990-hash/one-action-kernel`](https://github.com/rossbuckley1990-hash/one-action-kernel).

## License

Apache-2.0. See [LICENSE](LICENSE).
