# SECURITY-REMEDIATION-v0.1.2.md — Actenon ShipGuard

**Status: all five P0 findings FIXED and covered by negative controls. 31 tests pass on macOS
(arm64, py3.14) and on Linux CI (py3.11 + py3.12). v0.1.2 is a scoped SECURITY-remediation
pre-release — it does NOT claim a Claude/Codex repair loop, Howdex transfer, Workproof attestation,
general correctness, or unbypassable enforcement.**

- Starting reference: v0.1.1 `96e62eaddcde744f09da0886b76c3463071b03fe`
- Remediation branch: `security-remediation-v0.1.2` (PR #1, draft)
- Fix commits: `50c5668` (auth binding + TOCTOU + nonce) → `0e93653` (signing separation) →
  `68d4420` (Sentinel anti-fabrication) → `a48ac18` (key isolation) → `8b5f3ae` (packaging)
- Pinned stack: actenon-kernel==1.2.1, actenon-protocol==1.4.0, actenon-permit==1.4.0,
  actenon-scan==1.5.0, cryptography==44.0.0 (released PyPI, no moving main)

## Reproduce

```bash
git clone https://github.com/Actenon/actenon-shipguard && cd actenon-shipguard
git checkout security-remediation-v0.1.2
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]' && npm install -g tsx
pytest -q                                   # 31 passed
actenon-shipguard demo --trials 200000      # PASS (1 ALLOW + 7 REFUSE)
# packaging gate:
python -m build --wheel && python -m venv /tmp/w && /tmp/w/bin/pip install dist/*.whl
cd /tmp && SHIPGUARD_TSX="$(command -v tsx)" /tmp/w/bin/actenon-shipguard demo --trials 5000
```

## Machine-readable remediation matrix

```json
{
  "release": "v0.1.2",
  "scope": "security remediation (P0/P1 trust boundary + packaging); NOT the real-agent product",
  "suite": {"passed": 31, "failed": 0, "skipped": 0, "command": "pytest -q",
            "platforms": ["macOS arm64 py3.14 (local)", "ubuntu-latest py3.11+py3.12 (CI)"]},
  "findings": [
    {"id": "P0-auth-binding", "status": "FIXED",
     "fix": "gate enforces exact equality of parameters/resource/capability/export/module/contract-digest/git-commit against the VERIFIED intent; execution values derived from the intent; checked before nonce reservation",
     "negative_controls": ["small auth (1e6) reused for 1e8 action -> INTENT_MISMATCH", "export substitution", "resource substitution", "module substitution"],
     "positive_control": "test_allow_correct_code_mediates_real_invocation",
     "asserts_no_side_effect": true},
    {"id": "P0-signing-separation", "status": "FIXED",
     "fix": "Option A (smallest attack surface): enforcer/ProtectedResource hold ONLY pinned public trust roots and NO private key; the boundary independently verifies the original PCCB + certificate + exact code + nonce before executing; verify_and_execute is the only route to the effect (no forgeable handoff capability). Authority identity resolved from authenticated proof data (pccb.signature.key_id) and pinned. Versioned domain separation (correctness-cert/v1, reconciliation/v1, receipt-attestation/v1).",
     "negative_controls": ["enforcer holds_signing_key()==False", "tampered proof presented directly to the resource -> refused", "cross-domain signature replay -> rejected", "certificate signed by unpinned key -> CERT_UNTRUSTED"],
     "positive_control": "test_allow_correct_code_mediates_real_invocation",
     "asserts_no_side_effect": true,
     "remaining_limitation": "ledger is tamper-EVIDENT via hash chain, not unforgeable-signed (enforcer has no key by design); a separate audit authority would be needed for signed audit"},
    {"id": "P0-key-storage", "status": "FIXED",
     "fix": "init writes private keys OUTSIDE the project workspace (default ~/.config/actenon-shipguard/keys, 0600); only public trust-roots.json lands in the workspace; --keys-dir inside the workspace is refused; --enforcement isolated FAILS CLOSED without external KMS/HSM/service custody",
     "negative_controls": ["no *.pem in workspace after init (4 keys external)", "keys-dir inside workspace -> exit 2", "isolated mode without custody -> exit 2, no keys minted"],
     "remaining_limitation": "cooperative-local is ADVISORY: a same-OS-user agent could still read an external 0600 dir. True hostile-agent resistance needs OS-level isolation (restricted service account / container / KMS-HSM), which is NOT claimed and fails closed when requested"},
    {"id": "P0-sentinel-soundness", "status": "FIXED",
     "fix": "removed bogus requirementId='valid-ages'; one check per REAL approved requirement; verifier requires full coverage with matching ids (rejects zero checks, unrelated ids, partial coverage); PLUS a domain-separated verifier-authority attestation (isolated ROLE_VERIFIER) so a manually-VERIFIED + consistently RE-HASHED receipt is rejected (content-addressing alone is insufficient)",
     "negative_controls": ["zero checks", "unrelated requirement id", "partial coverage (1 check for N requirements)", "forged status (content-address break)", "refabricated + consistently rehashed receipt -> FABRICATION", "synthetic receipt with no attestation on trusted path -> rejected"],
     "positive_control": "test_allow_correct_code_mediates_real_invocation",
     "remaining_limitation": "the offline demo signs a LABELLED demo verifier attestation (verifier-format fixture). Genuine `sentinel verify` execution + isolated verifier signing for the real protected path is an integration-mode item, not yet wired"},
    {"id": "P0-packaging", "status": "FIXED",
     "fix": "fixtures + property_verify.mjs moved into the package (_bundled/) and shipped via [tool.setuptools.package-data]; all path references use the installed package dir, not repo-relative paths",
     "negative_controls": ["wheel inspected: all bundled resources present", "non-editable install in a fresh venv", "doctor + demo PASS from an unrelated cwd (/tmp) using only bundled resources"],
     "remaining_limitation": "Node + tsx is an external runtime dependency (doctor checks it; CI installs it; provisioned via PATH or SHIPGUARD_TSX). Zero-friction Node provisioning is a separate onboarding item"},
    {"id": "P1-nonce-reconcile", "status": "FIXED",
     "fix": "reconcile() uses a trusted, internally-configured ReconciliationVerifier over PINNED reconciliation roots and canonical versioned statements binding nonce/pccb/effect/resource/resolution/outcome/policy/freshness; NO caller callback (lambda:True cannot be injected); fails closed (nonce stays uncertain)",
     "negative_controls": ["forged/unknown signer", "wrong effect id", "no-callback injection (arbitrary evidence)", "unavailable verifier", "cross-domain signature"],
     "positive_control": "test_reconciliation_valid_signed_evidence_resolves"},
    {"id": "P1-toctou-snapshot", "status": "FIXED",
     "fix": "resource reads certified bytes ONCE, writes an immutable 0444 snapshot from those exact in-memory bytes, re-verifies the snapshot digest, and executes the snapshot; the mutable original is never re-read before import",
     "negative_controls": ["code replaced after certification -> CODE_ARTIFACT_MISMATCH", "snapshot digest re-check"],
     "positive_control": "test_allow_correct_code_mediates_real_invocation (executes via snapshot)",
     "remaining_limitation": "same-OS-account immutability is a documented limit; dependency/import-graph snapshotting and a restricted execution environment for untrusted module-init side effects remain open (P1-exact-snapshot follow-ups)"},
    {"id": "P1-action-ci", "status": "FIXED",
     "fix": "action.yml installs from $GITHUB_ACTION_PATH (not the consumer cwd) and allowlists commands via env vars (no shell interpolation of untrusted input; trials validated numeric); CI builds+installs the wheel non-editably and runs the demo from an unrelated cwd; CI FAILS if tsx is missing or any test skips",
     "remaining_limitation": "the action runs the deterministic demo as an install/smoke check; it is NOT yet a real PR correctness gate against the consumer's approved contract + exact PR head SHA"},
    {"id": "P1-actionable-refusals", "status": "PARTIAL",
     "fix": "the orchestrator captures the shrunk minimal counterexample (invariant/input/observed/detail/failing-count) and feeds it back to the agent; gate refusals carry structured codes + evidence",
     "remaining_limitation": "full structured refusal payload (reproduction command, bounded/privacy-safe) not yet emitted by the gate itself"},
    {"id": "P1-decouple", "status": "OPEN",
     "remaining_limitation": "gate/pipeline still assume the settlement two-int->array shape; a resource-adapter interface + versioned predicate registry are required"},
    {"id": "P2-hygiene", "status": "PARTIAL",
     "fix": ".gitignore excludes tmp/, keys/, *.pem, nonce dbs; tracked tree confirmed free of private key material; fixtures moved into the package",
     "remaining_limitation": "generated public evidence/reports may still contain absolute local paths; should be made relative/portable"}
  ]
}
```

## Release gate decision

**GO for a scoped v0.1.2 pre-release**, conditional on CI green against the exact release commit.
All P0 findings are fixed with negative controls that assert no side effect; the deterministic demo
and the non-editable-wheel install both pass from an unrelated cwd.

This release is **scoped to the security remediation**. It explicitly does NOT include or claim:
the real Claude/Codex repair loop (adapters/orchestrator are scaffolded, not validated end-to-end;
`claude` OAuth is expired in this environment, `codex` is authenticated), Howdex transfer, Workproof
end-to-end attestation, the multi-project aspirin benchmark, npm/PyPI distribution, general
correctness, stable v1.0.0, or production-grade unbypassable enforcement.

## Trust boundary summary (what is and is not enforced)

- Enforced (tested): a consequential action executes only if the Actenon authority proof verifies
  under a pinned root, the correctness certificate verifies under a separate pinned root with full
  Sentinel requirement coverage + an isolated verifier attestation, the executed values exactly equal
  the verified intent, the exact certified bytes run from an immutable snapshot, and the nonce is
  freshly reserved. The enforcer holds no signing key. Forged/substituted/stale/rehashed/replayed/
  bypass attempts are refused with no side effect.
- NOT enforced (documented): hostile-agent-resistant key isolation on a single OS user (cooperative
  local mode is advisory and fails closed for `isolated`); containment of untrusted module-import
  side effects; exactly-once external effect under all crashes (uncertain outcomes are exposed and
  require signed reconciliation, never blind-retried).
