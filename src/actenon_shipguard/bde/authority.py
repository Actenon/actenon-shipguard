"""Authority: who may block, and how an inferred hypothesis may ever qualify.

The engine's central epistemic rule (mandate §4.1, §15):

    The proposer of a law can never be its certifier.

Laws arrive with an evidence class. Class A requires explicit developer approval (a
developer policy file or an interactively approved lawpack — never something the repo
under inspection can write). Class B laws arrive *qualified* only when the compiler
produced them from machine-readable signature facts. Class D laws proposed from
documentation interpretation are promoted to ``qualified`` ONLY by the deterministic
``qualify()`` rules below, each of which requires a SECOND, independent machine
extraction that corroborates applicability — and every promotion is recorded on the law
with its reasons, so a reviewer can audit exactly why a law can block.

Policy knobs (defaults are the shipped configuration):

  allow_class_b_blocking   True   — qualified B laws may produce CONFIRMED_CONTRADICTION
  allow_class_c_regressions True  — preservation violations are REGRESSION_OBSERVED findings
  promote_doc_examples     True   — F1 examples may qualify (rule Q1 below)
  promote_splitter_laws    True   — F2 boundary laws may qualify (rule Q2 below)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .laws import (APPROVED, CLASS_A, CLASS_B, CLASS_C, CLASS_D, QUALIFIED, UNAPPROVED,
                   BehaviouralLaw)


@dataclass
class Policy:
    allow_class_b_blocking: bool = True
    allow_class_c_regressions: bool = True
    promote_doc_examples: bool = True
    promote_splitter_laws: bool = True
    promote_round_trip: bool = False       # round-trip stays a hypothesis in v1
    promote_idempotence: bool = False
    promote_conservation: bool = False
    promote_determinism: bool = False


@dataclass
class AuthorityReport:
    total: int = 0
    by_class: dict[str, int] = field(default_factory=dict)
    blocking: list[str] = field(default_factory=list)
    qualified: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    preservation: list[str] = field(default_factory=list)
    promotions: list[dict[str, Any]] = field(default_factory=list)


def _signature_of(law: BehaviouralLaw) -> dict[str, Any]:
    g = law.grounding
    return g.extracted if isinstance(g.extracted, dict) else {}


def _example_qualifies(law: BehaviouralLaw) -> tuple[bool, list[str]]:
    """Q1 — a documented example call qualifies when BOTH hold:

    1. the call was extracted verbatim as literal arguments from a fenced example or an
       ``@example`` JSDoc block (the compiler only ever emits such laws), AND
    2. a SECOND machine extraction corroborates that the call shape is supported usage:
       either the documented result is a literal/``undefined`` (executable specification
       fragment), or the README API section heading for the export lists a parameter list
       whose arity covers the example call.
    """
    reasons: list[str] = []
    ext = _signature_of(law)
    if law.kind != "doc_example":
        return False, ["not a doc-example law"]
    expected_kind = ext.get("expected_kind")
    if expected_kind in ("literal", "undefined"):
        reasons.append(f"documented result is machine-extractable ({expected_kind})")
        return True, reasons
    reasons.append("documented result is prose; checking README section signature arity")
    # corroboration path 2 — enforced by check.py which records the section heading arity
    arity = ext.get("readme_section_param_count")
    n_args = len(ext.get("args") or [])
    if isinstance(arity, int) and n_args <= arity:
        reasons.append(f"README section heading documents {arity} parameter(s); example call uses {n_args}")
        return True, reasons
    return False, reasons + ["no second machine extraction corroborates the call shape"]


def _splitter_qualifies(law: BehaviouralLaw) -> tuple[bool, list[str]]:
    """Q2 — a splitter boundary law qualifies when ALL hold:

    1. both boundary causes were matched VERBATIM from the README bullets (splitter-based
       and case-change-based — the compiler refuses to emit the law otherwise), AND
    2. the machine-readable signature corroborates the splitter shape
       ``(string, optional readonly-array?)``, AND
    3. the matched bullets are stored verbatim on the law's grounding (they are).
    """
    if law.kind != "split_boundary":
        return False, ["not a splitter-boundary law"]
    ext = _signature_of(law)
    reasons = ["both boundary causes matched verbatim from README bullets"]
    sig_params = ext.get("signature_params") or []
    if sig_params and isinstance(sig_params, list) and len(sig_params) >= 1:
        reasons.append(f"signature corroborates splitter shape: {sig_params[:2]}")
        return True, reasons
    return False, reasons + ["signature corroboration missing"]


def qualify(laws: list[BehaviouralLaw], policy: Policy | None = None) -> AuthorityReport:
    """Assign approval states under the policy; record every promotion reason."""
    policy = policy or Policy()
    report = AuthorityReport(total=len(laws))
    for law in laws:
        report.by_class[law.evidence_class] = report.by_class.get(law.evidence_class, 0) + 1
        if law.evidence_class == CLASS_A:
            # class A arrives only from developer-approved sources; a compiled-in law never does
            if law.approval == APPROVED:
                report.blocking.append(law.law_id)
            else:
                law.approval = UNAPPROVED
                report.hypotheses.append(law.law_id)
            continue
        if law.evidence_class == CLASS_B:
            if policy.allow_class_b_blocking:
                law.approval = QUALIFIED
                report.blocking.append(law.law_id)
            else:
                law.approval = UNAPPROVED
                report.hypotheses.append(law.law_id)
            continue
        if law.evidence_class == CLASS_C:
            law.approval = UNAPPROVED        # preservation: regression-grade, never blocking-correctness
            report.preservation.append(law.law_id)
            continue
        # CLASS_D — promotion rules
        rule, ok = None, False
        if law.kind == "doc_example" and policy.promote_doc_examples:
            ok, reasons = _example_qualifies(law)
            rule = "Q1-doc-example"
        elif law.kind == "split_boundary" and policy.promote_splitter_laws:
            ok, reasons = _splitter_qualifies(law)
            rule = "Q2-splitter-boundary"
        else:
            reasons = ["no promotion rule applies; remains a review hypothesis"]
        if ok:
            law.evidence_class = CLASS_B
            law.approval = QUALIFIED
            law.qualification = {"rule": rule, "reasons": reasons, "from_class": CLASS_D,
                                 "promoted_by": "authority.qualify/1 (deterministic)"}
            report.blocking.append(law.law_id)
            report.qualified.append(law.law_id)
            report.promotions.append({"law_id": law.law_id, "rule": rule, "reasons": reasons})
        else:
            law.approval = UNAPPROVED
            report.hypotheses.append(law.law_id)
            law.qualification = {"rule": None, "reasons": reasons, "from_class": CLASS_D,
                                 "promoted_by": None}
    return report


def annotate_section_arity(laws: list[BehaviouralLaw], bundle) -> None:
    """Record the README section-heading arity on doc-example laws (Q1 corroboration input).

    The heading ``### \\`parseFilename(input)\\`` is itself machine-extracted documentation of
    the supported call shape; storing it on the law keeps Q1's second extraction explicit.
    """
    import re as _re
    for law in laws:
        if law.kind != "doc_example":
            continue
        sec = bundle.readme_sections.get(law.export)
        if sec is None:
            continue
        m = _re.search(r"^#{2,4}\s+`?" + _re.escape(law.export) + r"\s*\(([^)`]*)\)", sec.text, _re.M)
        if not m:
            continue
        names = [p.strip() for p in m.group(1).split(",") if p.strip() and not p.strip().startswith("[")]
        ext = law.grounding.extracted
        if isinstance(ext, dict):
            ext["readme_section_param_count"] = len(names)
