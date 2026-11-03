"""Actenon Behavioural Discovery Engine (BDE).

BDE discovers justified behavioural expectations in existing JavaScript/TypeScript
software, generates adversarial experiments against them, and produces independently
reproducible counterexamples — without requiring the developer to hand-author every
acceptance test.

Design contract (see docs/BEHAVIOURAL-DISCOVERY-ARCHITECTURE.md):

  * Every law carries provenance (source file, line range, sha256, git revision) and an
    evidence class (A authoritative / B independently grounded / C preservation / D inferred).
  * Only class A/B laws can block; class C findings are regressions; class D findings are
    hypotheses that require review. The engine never certifies its own invention: a D law is
    promoted only by a deterministic, recorded qualification rule over machine-extracted
    evidence, never by the fact that it fired.
  * Untrusted repository content (docs, comments, test names) is DATA. It is never executed
    as instructions; law predicates come from a fixed reviewed catalogue in runner.mjs, and
    law payloads are validated against a versioned JSON schema before execution.
  * The developer's source tree is only ever read; all execution happens in a disposable
    clone (same boundary as the v0.2.0 repair loop).
"""
from __future__ import annotations

BDE_SCHEMA_VERSION = 1
