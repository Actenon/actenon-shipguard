"""Behavioural laws: machine-checkable statements about required behaviour.

A behavioural law is a statement of what a function or component is required or expected
to do, TOGETHER WITH the evidence that justifies treating it as a requirement. The
evidence hierarchy (mandate §4.1) is explicit on every law:

  A — AUTHORITATIVE      developer-approved contracts, machine-readable API specs,
                         agreed acceptance criteria. May BLOCK within verified scope.
  B — GROUNDED           applicable mathematical/structural properties whose applicability
                         was established independently of the candidate implementation
                         (signature facts, verbatim-documented usage, reviewed qualification).
                         May BLOCK when both the law and its applicability qualify.
  C — PRESERVATION       behaviour of a trusted baseline (the project's own tests at the
                         base revision, approved regression fixtures). A violation is a
                         REGRESSION finding, never a claim that the baseline was correct.
  D — INFERRED           hypotheses from documentation interpretation, naming, comments or
                         patterns. NEVER blocking without recorded qualification or explicit
                         developer approval. A violation is a falsified hypothesis for review.

The predicate itself is NOT free-form code: ``predicate`` must name an entry in the fixed,
reviewed catalogue implemented by ``runner.mjs`` (the same discipline as the v0.1.x
property verifier's INVARIANTS table). A law is DATA that selects a reviewed predicate and
binds it to grounded parameters — so untrusted repo content can configure which checks run,
but can never introduce new executable logic.

Serialisation is validated against ``laws-schema.json`` (versioned; see SCHEMA_VERSION).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import BDE_SCHEMA_VERSION

SCHEMA_VERSION = BDE_SCHEMA_VERSION

# --- evidence classes --------------------------------------------------------------------- #
CLASS_A = "A_AUTHORITATIVE"
CLASS_B = "B_GROUNDED"
CLASS_C = "C_PRESERVATION"
CLASS_D = "D_INFERRED"
EVIDENCE_CLASSES = (CLASS_A, CLASS_B, CLASS_C, CLASS_D)

# --- approval states ---------------------------------------------------------------------- #
APPROVED = "approved"          # developer-approved (class A) — blocking
QUALIFIED = "qualified"        # independently qualified (class B) — blocking per policy
UNAPPROVED = "unapproved"      # proposed, awaiting review — non-blocking
REJECTED = "rejected"
APPROVAL_STATES = (APPROVED, QUALIFIED, UNAPPROVED, REJECTED)

# --- reviewed predicate catalogue (MUST match runner.mjs PREDICATES exactly) -------------- #
PREDICATES = (
    "example_executable",        # documented call must run; documented result must match
    "preservation_case",         # baseline I/O pair must be reproduced exactly
    "optional_args_equivalent",  # f(required...) === f(required..., explicit defaults)
    "split_boundary_justified",  # splitter boundaries only at documented causes
    "round_trip",                # encode(decode(x)) / decode(encode(x)) identity on domain
    "idempotence",               # f(f(x)) === f(x) on domain
    "conservation_sum",          # numeric allocation conserves the total
    "determinism",               # same input -> same output within one execution
    "no_throw",                  # documented-supported inputs never throw
)

# What a grounding source may be (see sources.py).
SOURCE_TYPES = ("readme_section", "jsdoc", "signature", "test_assertion",
                "developer_policy", "approved_contract", "structural_pair", "reference_implementation")


@dataclass
class Grounding:
    """Where the justification for a law comes from — provenance is first-class."""
    source_type: str                       # one of SOURCE_TYPES
    file: str                              # repo-relative path
    line_start: int
    line_end: int
    excerpt: str                           # the verbatim evidence text (<= 400 chars kept)
    sha256: str                            # hash of the whole source file at discovery time
    revision: str                          # git revision the evidence was read from
    extracted: dict[str, Any] = field(default_factory=dict)   # machine-extracted facts

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BehaviouralLaw:
    """One machine-checkable behavioural expectation with full provenance."""
    law_id: str
    statement: str                          # human-readable behavioural statement
    kind: str                               # discovery family, e.g. split_boundary / doc_example
    predicate: str                          # reviewed runner predicate (PREDICATES)
    module: str                             # repo-relative module path
    export: str                             # exported function under test
    params: dict[str, Any]                  # predicate parameters (validated, literal-only)
    domain: dict[str, Any]                  # input domain spec for generated adversarial inputs
    evidence_class: str                     # EVIDENCE_CLASSES
    grounding: Grounding
    approval: str = UNAPPROVED
    confidence: float = 0.0                 # applicability assessment 0..1 (recorded, not blocking)
    limitations: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    counterexample_schema: dict[str, Any] = field(default_factory=dict)
    qualification: dict[str, Any] = field(default_factory=dict)  # recorded D->B promotion evidence
    discovered_by: str = "intent-compiler/1"
    schema_version: int = SCHEMA_VERSION

    # --- construction helpers ------------------------------------------------------------ #
    @staticmethod
    def new_id() -> str:
        return f"bde-law-{uuid.uuid4().hex[:10]}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["grounding"] = self.grounding.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "BehaviouralLaw":
        g = d.pop("grounding")
        return BehaviouralLaw(grounding=Grounding(**g), **d)

    def digest(self) -> str:
        """Content digest over the semantically-loadbearing fields (excludes id/approval so
        approval transitions never change a law's identity)."""
        payload = {k: v for k, v in self.to_dict().items()
                   if k not in ("law_id", "approval", "confidence")}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    # --- authority questions -------------------------------------------------------------- #
    @property
    def is_blocking(self) -> bool:
        """Only A-approved or B-qualified laws may support a blocking verdict."""
        return ((self.evidence_class == CLASS_A and self.approval == APPROVED)
                or (self.evidence_class == CLASS_B and self.approval == QUALIFIED))

    @property
    def status_label(self) -> str:
        if self.evidence_class == CLASS_A:
            return "authoritative"
        if self.evidence_class == CLASS_B:
            return "independently grounded"
        if self.evidence_class == CLASS_C:
            return "preservation"
        return "inferred hypothesis"


# -------------------------------------------------------------------------------------------- #
# Versioned JSON schema for lawpacks + validation (no external dependency, fail-closed)
# -------------------------------------------------------------------------------------------- #
_SCHEMA_PATH = Path(__file__).resolve().parent / "laws-schema.json"

_SCHEMA = {
    "$id": "actenon-shipguard/bde/lawpack/1",
    "type": "object",
    "required": ["schema_version", "module", "laws"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "module": {"type": "string"},
        "git_revision": {"type": "string"},
        "laws": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["law_id", "statement", "kind", "predicate", "module", "export",
                             "params", "domain", "evidence_class", "grounding", "approval"],
                "properties": {
                    "law_id": {"type": "string", "pattern": "^bde-law-[0-9a-f]{10}$"},
                    "statement": {"type": "string", "minLength": 8},
                    "kind": {"type": "string"},
                    "predicate": {"enum": list(PREDICATES)},
                    "module": {"type": "string"},
                    "export": {"type": "string"},
                    "params": {"type": "object"},
                    "domain": {"type": "object"},
                    "evidence_class": {"enum": list(EVIDENCE_CLASSES)},
                    "approval": {"enum": list(APPROVAL_STATES)},
                    "grounding": {
                        "type": "object",
                        "required": ["source_type", "file", "line_start", "line_end",
                                     "excerpt", "sha256", "revision"],
                        "properties": {
                            "source_type": {"enum": list(SOURCE_TYPES)},
                            "file": {"type": "string"},
                            "line_start": {"type": "integer", "minimum": 1},
                            "line_end": {"type": "integer", "minimum": 1},
                            "excerpt": {"type": "string"},
                            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            "revision": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}


def validate_lawpack(pack: dict[str, Any]) -> list[str]:
    """Structural validation of a lawpack. Returns a list of problems (empty == valid).

    Deliberately hand-rolled and fail-closed: no dynamic schema dependency, no ``eval``,
    unknown keys inside ``params``/``domain`` are tolerated (predicates validate their own
    parameters in the runner) but every authority-bearing field is strictly checked, because
    a forged evidence class or predicate name is exactly how untrusted content would try to
    promote itself (mandate §15).
    """
    problems: list[str] = []
    if not isinstance(pack, dict):
        return ["lawpack is not an object"]
    if pack.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(pack.get("module"), str) or not pack["module"]:
        problems.append("module missing")
    laws = pack.get("laws")
    if not isinstance(laws, list):
        problems.append("laws must be an array")
        return problems
    seen_ids: set[str] = set()
    for i, law in enumerate(laws):
        where = f"laws[{i}]"
        if not isinstance(law, dict):
            problems.append(f"{where}: not an object")
            continue
        for key in ("law_id", "statement", "kind", "predicate", "module", "export",
                    "params", "domain", "evidence_class", "grounding", "approval"):
            if key not in law:
                problems.append(f"{where}: missing {key}")
        lid = law.get("law_id", "")
        if not re.fullmatch(r"bde-law-[0-9a-f]{10}", str(lid)):
            problems.append(f"{where}: bad law_id {lid!r}")
        if lid in seen_ids:
            problems.append(f"{where}: duplicate law_id {lid}")
        seen_ids.add(lid)
        if law.get("predicate") not in PREDICATES:
            problems.append(f"{where}: predicate {law.get('predicate')!r} not in reviewed catalogue")
        if law.get("evidence_class") not in EVIDENCE_CLASSES:
            problems.append(f"{where}: bad evidence_class {law.get('evidence_class')!r}")
        if law.get("approval") not in APPROVAL_STATES:
            problems.append(f"{where}: bad approval {law.get('approval')!r}")
        # A law may never claim to be blocking straight from data: class A requires approval
        # 'approved', class B requires 'qualified'. A pack that arrives claiming anything else
        # for A/B is downgraded by the authority engine, but a D/C law claiming APPROVED is a
        # provenance forgery and is rejected outright.
        if law.get("evidence_class") in (CLASS_C, CLASS_D) and law.get("approval") == APPROVED:
            problems.append(f"{where}: class {law.get('evidence_class')} cannot arrive developer-approved")
        g = law.get("grounding")
        if not isinstance(g, dict):
            problems.append(f"{where}: grounding missing")
            continue
        if g.get("source_type") not in SOURCE_TYPES:
            problems.append(f"{where}: bad grounding.source_type {g.get('source_type')!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(g.get("sha256", ""))):
            problems.append(f"{where}: grounding.sha256 must be a file content hash")
        if not isinstance(g.get("line_start"), int) or g.get("line_start", 0) < 1:
            problems.append(f"{where}: grounding.line_start must be >= 1")
        if not str(g.get("revision", "")).strip():
            problems.append(f"{where}: grounding.revision missing (stale-evidence guard)")
    return problems


def write_schema(path: Path | None = None) -> Path:
    """Emit the versioned JSON schema document for external tooling/inspection."""
    p = path or _SCHEMA_PATH
    p.write_text(json.dumps(_SCHEMA, indent=2) + "\n")
    return p


def lawpack_for(module: str, laws: list[BehaviouralLaw], revision: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "module": module, "git_revision": revision,
            "laws": [lw.to_dict() for lw in laws]}
