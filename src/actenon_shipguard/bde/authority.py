"""Conservative authority for observable documentation contradictions.

An explicit, machine-readable documented result can qualify a discrepancy check.
Signature shape alone does not establish totality, defaults or boundary semantics.
Inferred properties remain review hypotheses; they cannot approve a repair contract.
Class A requires approval supplied outside the repository under inspection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .laws import APPROVED, CLASS_A, CLASS_B, CLASS_C, CLASS_D, QUALIFIED, UNAPPROVED, BehaviouralLaw


@dataclass
class Policy:
    allow_class_b_blocking: bool = True
    allow_class_c_regressions: bool = True
    promote_doc_examples: bool = True
    promote_splitter_laws: bool = False
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
    """Only an explicit documented literal/undefined result supplies an oracle.

    This establishes a documentation/code discrepancy, not which side must change.
    Two extractions of one document are not independent semantic authorities.
    """
    reasons: list[str] = []
    ext = _signature_of(law)
    if law.kind != "doc_example":
        return False, ["not a doc-example law"]
    expected_kind = ext.get("expected_kind")
    if expected_kind in ("literal", "undefined"):
        reasons.append(f"documented result is machine-extractable ({expected_kind})")
        return True, reasons
    return False, ["only an explicit documented literal result establishes a checkable contradiction"]


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
            ok, reasons = _example_qualifies(law)
            if policy.allow_class_b_blocking and ok:
                law.approval = QUALIFIED
                report.blocking.append(law.law_id)
            else:
                law.evidence_class = CLASS_D
                law.approval = UNAPPROVED
                report.hypotheses.append(law.law_id)
            continue
        if law.evidence_class == CLASS_C:
            if not policy.allow_class_c_regressions:
                law.evidence_class = CLASS_D
            law.approval = UNAPPROVED        # preservation: regression-grade, never blocking-correctness
            report.preservation.append(law.law_id)
            continue
        # CLASS_D — promotion rules
        rule, ok = None, False
        if law.kind == "doc_example" and policy.promote_doc_examples:
            ok, reasons = _example_qualifies(law)
            rule = "Q1-doc-example"
        elif law.kind == "split_boundary":
            reasons = ["signature shape does not independently establish inferred boundary semantics"]
            rule = "Q2-disabled-pending-independent-authority"
        else:
            reasons = ["no promotion rule applies; remains a review hypothesis"]
        if ok and policy.allow_class_b_blocking:
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
    """Record README section-heading arity as descriptive provenance only.

    The heading ``### \\`parseFilename(input)\\`` is itself machine-extracted documentation of
    a call shape; this metadata does not grant execution authority.
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
