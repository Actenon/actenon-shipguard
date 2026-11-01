# SECURITY-REMEDIATION-v0.1.2.md — Actenon ShipGuard

**Status: v0.1.2 NOT PUBLISHED.** Per the remediation mandate ("If any P0 issue remains, do not
publish the claimed security fix. Report the blocker and retain the tested implementation
branch"), this work is retained on branch `security-remediation-v0.1.2`. Three P0 findings remain
OPEN and one is PARTIAL. The v0.1.1 release and its evidence history are preserved untouched.

- Starting reference: v0.1.1, commit `96e62eaddcde744f09da0886b76c3463071b03fe`
- Remediation branch HEAD: see `git rev-parse security-remediation-v0.1.2`
- Suite on branch: **20 passed** (`pytest -q`), pinned released Actenon stack, macOS arm64 / py3.14

## Machine-readable remediation matrix

```json
{
  "release": "v0.1.2-candidate",
  "published": false,
  "suite": {"passed": 20, "failed": 0, "command": "pytest -q"},
  "findings": [
    {"id": "P0-auth-binding", "title": "Authorisation binding (intent == executed action)",
     "status": "FIXED", "severity": "P0",
     "repro": "mint proof for total_pence=100; call authorize_and_execute with total_pence=100000000",
     "root_cause": "gate accepted independently-supplied execution args without comparing them to the verified intent",
     "fix": "gate.py enforces exact equality of parameters, resource_id, capability, certified export/module, contract digest and git commit against the VERIFIED intent; execution values derived from the intent; checked before nonce reservation",
     "negative_control": "test_refuse_small_authorisation_reused_for_larger_action; test_refuse_export_substitution_same_module; test_refuse_resource_substitution; test_refuse_module_path_substitution (all assert REFUSE/AUTHORITY/INTENT_MISMATCH, no disbursement, nonce not reserved)",
     "positive_control": "test_allow_correct_code_mediates_real_invocation",
     "evidence": "tests/test_trust_boundary.py", "remaining_limitation": "capability validated against verified intent; per-operation constraint schema still settlement-shaped (see P1-decouple)"},

    {"id": "P0-signing-separation", "title": "Real separation of signing authorities",
     "status": "OPEN", "severity": "P0",
     "repro": "EdgeGate is constructed with issuer_signer: AuthoritySigner, i.e. the enforcer holds the Actenon authority PRIVATE key",
     "root_cause": "the gate both verifies (should be public-key-only) and signs dispatch authorizations/ledger with the issuer key; no separate dispatch-authority role; no signature domain separation",
     "fix": "REQUIRED: enforcer holds only pinned public roots; a separately-scoped dispatch-authority signer (own role/key/policy) signs handoff capabilities; versioned canonical schemas + domain-separation tags per signed object; signer identity validated against a trusted key registry, not caller-supplied",
     "negative_control": "PENDING (enforcer-attempts-to-use-issuer-private-key; cross-domain signature reuse)",
     "positive_control": "PENDING", "evidence": "none yet", "remaining_limitation": "BLOCKER for v0.1.2"},

    {"id": "P0-key-storage", "title": "Private-key storage outside the agent workspace",
     "status": "OPEN", "severity": "P0",
     "repro": "shipguard init writes .shipguard/keys/*.pem (0600) inside the project workspace",
     "root_cause": "0600 does not isolate keys from an agent running as the same OS user with read access to the workspace",
     "fix": "REQUIRED: store issuer/prover keys outside the agent-readable/writable workspace (dedicated restricted service/account or OS isolation); when isolation is unavailable, explicitly REFUSE to claim hostile-agent-resistant key separation",
     "negative_control": "PENDING (workspace agent cannot read/replace/invoke private authority keys)",
     "positive_control": "PENDING", "evidence": "none yet", "remaining_limitation": "BLOCKER for v0.1.2; cooperative local mode cannot currently claim hostile-agent key isolation"},

    {"id": "P0-sentinel-soundness", "title": "Sentinel receipt soundness",
     "status": "PARTIAL", "severity": "P0",
     "repro": "offline demo built content-addressed Sentinel-shaped receipts with preset VERIFIED and a single hardcoded requirementId='valid-ages' unrelated to the settlement contract",
     "root_cause": "synthetic receipts were treated as authoritative; coverage was not validated against the approved contract's requirements",
     "fix": "DONE: removed the bogus 'valid-ages' id; stores emit one check per REAL approved requirement; verifier requires full coverage with matching ids and rejects zero checks, unrelated ids and partial coverage. OPEN: a verifier-authority SIGNATURE over the receipt so a manually-VERIFIED + re-hashed fabrication is rejected (content addressing alone is insufficient); genuine Sentinel execution for the real protected path; synthetic receipts must be labelled fixtures that can never authorise the real path",
     "negative_control": "test_receipt_zero_checks_rejected; test_receipt_unrelated_requirement_id_rejected; test_receipt_incomplete_coverage_rejected; test_refuse_forged_receipt_status (content-address break). PENDING: rehashed-fabrication-with-valid-hash",
     "positive_control": "test_allow_correct_code_mediates_real_invocation",
     "evidence": "tests/test_trust_boundary.py, receipts.py", "remaining_limitation": "anti-fabrication signature + real-Sentinel integration OPEN; BLOCKER for v0.1.2"},

    {"id": "P0-packaging", "title": "Non-editable wheel with bundled resources",
     "status": "OPEN", "severity": "P0",
     "repro": "fixtures/property_verify.mjs resolved via source-tree-relative paths; only `pip install -e .` exercised",
     "root_cause": "runtime fixtures live outside the package and are located by repo-relative path",
     "fix": "REQUIRED: move fixtures + property_verify.mjs + contracts into packaged resources via importlib.resources; build a real wheel; verify install in a fresh non-editable venv from an unrelated cwd (doctor + bundled demo + report); inspect wheel contents; test on Linux + macOS",
     "negative_control": "PENDING (wheel install + demo from unrelated cwd)", "positive_control": "PENDING",
     "evidence": "none yet", "remaining_limitation": "BLOCKER for v0.1.2"},

    {"id": "P1-nonce-reconcile", "title": "Cryptographic nonce reconciliation",
     "status": "FIXED_IMPL_TEST_PARTIAL", "severity": "P1",
     "repro": "reconcile() accepted any evidence with non-empty 'signature'/'established_by' strings",
     "root_cause": "no cryptographic verification of reconciliation evidence",
     "fix": "reconcile() now REQUIRES a verify_evidence callable that must check the signature against an authorised pinned trust root and bind it to the exact nonce+resolution; arbitrary strings rejected; uncertain nonce left unresolved on failure; state transition guarded to RESERVED only",
     "negative_control": "PENDING dedicated test (forged reconciliation signature; wrong effect)",
     "positive_control": "PENDING dedicated test", "evidence": "nonce.py",
     "remaining_limitation": "versioned canonical reconciliation schema + dedicated reconciler trust root + tests still to add"},

    {"id": "P1-toctou-snapshot", "title": "Exact executable snapshot (TOCTOU)",
     "status": "FIXED_IMPL_TEST_PARTIAL", "severity": "P1",
     "repro": "resource hashed code_path then re-read it via a separate tsx import (check/use gap)",
     "root_cause": "the mutable original file was re-read between hashing and execution",
     "fix": "resource reads the certified bytes ONCE, writes an immutable (0444) snapshot from those exact in-memory bytes, re-verifies the snapshot digest, and invokes the snapshot; the original is never re-read before import",
     "negative_control": "PENDING dedicated race test (source-file replacement after hashing; dependency substitution; import-time effects)",
     "positive_control": "test_allow_correct_code_mediates_real_invocation (executes via snapshot)",
     "evidence": "gate.py", "remaining_limitation": "same-OS-account immutability is a documented limit; dependency/import graph not yet snapshotted; restricted execution environment for untrusted code OPEN"},

    {"id": "P1-actionable-refusals", "title": "Structured counterexample in refusals",
     "status": "PARTIAL", "severity": "P1",
     "fix": "orchestrator captures the shrunk minimal counterexample (invariant, input, observed, detail, failing-input count) and feeds it back to the agent; gate refusals carry structured codes/evidence",
     "remaining_limitation": "full structured refusal payload (reproduction command, source+contract identities, bounded/privacy-safe) not yet emitted by the gate itself"},

    {"id": "P1-decouple", "title": "Decouple demo logic from core enforcement",
     "status": "OPEN", "severity": "P1",
     "remaining_limitation": "gate/pipeline still assume the settlement two-int->array shape; a resource-adapter interface + versioned predicate registry are required"},

    {"id": "P1-action-ci", "title": "GitHub Action + CI hardening",
     "status": "OPEN", "severity": "P1",
     "remaining_limitation": "action.yml installs from the consumer cwd (must use $GITHUB_ACTION_PATH / pinned artifact); CI must FAIL when tsx or other mandatory prerequisites are missing (tests currently skip); non-editable wheel build/install tests not added"},

    {"id": "P2-hygiene", "title": "Repository and evidence hygiene",
     "status": "PARTIAL", "severity": "P2",
     "fix": ".gitignore excludes tmp/, keys/, *.pem, nonce dbs; tracked tree confirmed free of private key material",
     "remaining_limitation": "generated public evidence/reports still contain absolute local home-directory paths; should be relative/portable"}
  ]
}
```

## Release gate decision

**NO-GO for v0.1.2.** Open P0 blockers: `P0-signing-separation`, `P0-key-storage`,
`P0-packaging`, and the anti-fabrication half of `P0-sentinel-soundness`. The tested fixes
(P0 auth binding, P0 Sentinel coverage, P1 nonce-crypto, P1 TOCTOU) are committed on the branch
and covered by 20 passing tests, but the mandate forbids publishing a claimed security release
while any P0 remains. No tag, no release, no version bump published.

## What was deliberately NOT claimed

- No complete Claude/Codex repair loop (adapters + orchestrator are scaffolded on this branch but
  not validated end-to-end with a live model; `claude` OAuth is expired in this environment,
  `codex` is authenticated). Not claimed as working.
- No genuine Howdex transfer or Workproof end-to-end attestation.
- No general correctness, no stable v1.0.0, no production-grade unbypassable enforcement.

## Reproduce the branch state

```bash
git clone https://github.com/Actenon/actenon-shipguard && cd actenon-shipguard
git checkout security-remediation-v0.1.2
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q          # 20 passed
```
