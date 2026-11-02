# Changelog

All notable changes to Actenon ShipGuard. This project adheres to semantic versioning.

## [0.1.2] - 2026-11-01 — security remediation pre-release

Scoped to the P0/P1 trust-boundary + packaging remediation. Does NOT add the real-agent product.
See `SECURITY-REMEDIATION-v0.1.2.md` for the machine-readable matrix. Suite: 31 passed (macOS +
Linux CI py3.11/3.12).

### Security (P0)
- **Authorisation binding** — executed parameters/resource/capability/export/module/contract-digest/
  git-commit must exactly equal the verified intent; values derived from the intent; refused before
  any side effect. Negative controls incl. small-auth-reused-for-larger-action.
- **Signing-authority separation** — the enforcer holds ONLY pinned public trust roots and NO private
  key (Option A): the protected boundary independently verifies the original PCCB + certificate +
  exact code + nonce; no forgeable handoff capability. Authority identity resolved from authenticated
  proof data. Versioned domain separation for cert/reconciliation/receipt-attestation signatures.
- **Key storage** — private keys live OUTSIDE the project workspace; `init` refuses a workspace
  `--keys-dir`; `--enforcement isolated` fails closed without external KMS/HSM/service custody.
- **Sentinel receipt soundness** — full approved-requirement coverage with matching ids (rejects zero
  checks / unrelated ids / partial coverage) PLUS an isolated verifier-authority attestation, so a
  manually-VERIFIED and consistently re-hashed receipt is rejected.
- **Packaging** — fixtures + JS verifier bundled into the wheel; non-editable install verified from an
  unrelated cwd (doctor + demo PASS on bundled resources only).

### Security (P1)
- **Nonce reconciliation** — trusted internally-configured verifier over pinned reconciliation roots
  and canonical versioned statements; no caller callback; fails closed (nonce stays uncertain).
- **TOCTOU** — executes an immutable snapshot written from the exact hashed bytes.
- **CI/Action** — action installs from `$GITHUB_ACTION_PATH` with an allowlisted command; CI builds +
  clean-installs the wheel and fails if tsx is missing or any test skips.

## [0.1.1] - 2026-11-01 — pre-release

### Fixed
- CI workflow YAML parsed incorrectly (a plain `run:` scalar contained `: `), causing a
  workflow-file failure. Now a block scalar.
- Tests resolve `tsx` portably (PATH / `SHIPGUARD_TSX` / lab fallback) so a fresh checkout with
  globally-installed tsx works; they skip cleanly when tsx is absent.

### Verified
- GitHub Actions CI **green** on `ubuntu-latest`, matrix Python 3.11 + 3.12 (run 41354658157):
  pinned install, `doctor`, 13 adversarial tests, and the offline demo all pass — a genuine
  fresh-install reproduction on Linux.

## [0.1.0] - 2026-11-01 — pre-release

First pre-release. **Not** a stable v1.0.0 — see `RELEASE-EVIDENCE.md` for the release-gate
decision and explicit blockers.

### Added (complete + adversarially tested)
- Protected-execution trust boundary (mandate §6 A–E):
  - **Mediated invocation** — the consequential action executes the exact certified artifact via a
    signed gate authorization; no synthetic record, no unprotected alternate path; direct resource
    calls without authorization are refused.
  - **Structured Sentinel receipt verification** — content-addressed receipts re-verified against
    the approved contract, exact candidate source, full git identity, verifier identity and every
    recorded check; forged / substituted / stale evidence rejected. No console-text parsing.
  - **Separated signing authorities + externally pinned trust roots** — authority issuer,
    correctness prover, enforcer (public keys only) and requester (no key) are distinct; RFC 7638
    thumbprint pinning rejects key substitution; rotation-ready.
  - **Durable atomic nonce store** (SQLite/WAL) — crash-, restart- and concurrency-safe; uncertain
    outcomes are exposed and refuse blind retry; reconciliation requires signed evidence.
  - **Exact execution identity** — proofs/certs bind full git SHA, code-artifact digest, contract
    digest, verifier identity and replay nonce.
- Real ed25519 authority signing on the **pinned released** Actenon stack (`actenon-kernel==1.2.1`),
  binding correctness through signed action constraints (the released minter has no `extensions`).
- `actenon-shipguard` CLI: `init`, `demo`, `verify`, `report`, `doctor`, `run` (real-agent mode
  honestly reports it is not yet wired).
- Self-contained offline HTML evidence report; machine-readable `demo-summary.json`.
- 13 adversarial trust-boundary tests; deterministic offline demo (1 ALLOW + 7 REFUSE).
- Pinned dependencies; `pyproject.toml` packaging; CI workflow; GitHub Action; Apache-2.0.

### Blocked / not included (v1.0.0 gate)
- Real Claude/Codex repair loop; Howdex real traces + held-out transfer; Workproof independent
  verification; full 28-case adversarial matrix; CI executed on GitHub; multi-project aspirin
  benchmark; zero-friction polyglot onboarding; PyPI/npm distribution.

[0.1.0]: https://github.com/Actenon/actenon-shipguard/releases/tag/v0.1.0
