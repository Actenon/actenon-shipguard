"""The Actenon Intent Compiler: grounded evidence -> candidate behavioural contracts.

This module turns the machine-extractable evidence collected by ``sources.py`` into
``BehaviouralLaw`` records. It is a COMPILER, not a judge: it only emits laws whose
relation comes from a reviewed template family and whose grounding is verbatim,
machine-extracted evidence. It never invents a requirement that the evidence does not
state, and it never assigns blocking authority — that is ``authority.py``'s separate,
deterministic decision.

Discovery families (each grounded, each inspectable):

  F1 doc-example executability   documented example calls (README fences, JSDoc ``@example``)
  F2 splitter boundary law       README/JSDoc bullets that state split causes verbatim
  F3 optional-argument law       machine-readable TS signature marks a param optional
  F4 preservation cases          the project's own test I/O pairs (baseline behaviour)
  F5 round-trip pairs            type-inverse export pairs in one module + documented inverse
  F6 idempotence                 documented normalisation/canonicalisation statements
  F7 conservation                documented total-conservation for numeric allocation
  F8 determinism                 same-input stability of a pure function

Template matching over documentation is deliberately CONSERVATIVE: a sentence matches only
when its structure matches the reviewed template (imperative verb + enumerated causes),
the matched text is stored verbatim on the law, and the proposed evidence class is D until
``authority.qualify`` promotes it with recorded reasons. Documentation can therefore
PROPOSE laws but never CERTIFY them (mandate §4.1, §5, §15).
"""
from __future__ import annotations

import re
from typing import Any

from .laws import CLASS_C, CLASS_D, BehaviouralLaw
from .sources import EvidenceBundle, LiteralError, Signature, parse_literal

# -------------------------------------------------------------------------------------------- #
# Reviewed documentation templates (verbatim-structure matches; prose is stored, not guessed)
# -------------------------------------------------------------------------------------------- #
_T_SPLIT_BY_SEPARATORS = re.compile(
    r"(?i)^\s*[-*]\s*splits?\s+[^.]{0,60}?\bby\b\s+(?:the\s+)?(?:splitters?|separators?)\s+"
    r"(?:provided|given|specified)[^.]{0,80}?(?:\(default:\s*(`[^`]*`|'[^']*'|\"[^\"]*\"|\[[^\]]*\])\))?\s*\.?\s*$")
_T_SPLIT_CASE_CHANGE = re.compile(
    r"(?i)^\s*[-*]\s*splits?\s+[^.]{0,40}?\bwhen\b\s+(?:the\s+)?case\s+changes?\s+from\s+lower\s+to\s+upper"
    r"\s+or\s+(?:from\s+)?upper\s+to\s+lower\s*\.?\s*$")
_T_IGNORES_NUMBERS = re.compile(
    r"(?i)^\s*[-*]\s*ignores?\s+(?:numbers?|digits?)\s+(?:for|in)\s+(?:case\s+)?(?:changes?|transitions?)\s*\.?\s*$")
_T_CASE_PRESERVED = re.compile(
    r"(?i)^\s*[-*]\s*case\s+is\s+preserved\b[^.]*\.?\s*$")
_T_IRREVERSIBLE = re.compile(
    r"(?i)^\s*[-*]\s*is\s+(?:an?\s+)?irreversible\b[^.]*\.?\s*$")
_T_NORMALIZES = re.compile(
    r"(?i)^\s*(?:[-*]\s*)?(?:normali[sz](?:es?|ation)|canonicali[sz](?:es?|ation))\b")
_T_ROUND_TRIP = re.compile(
    r"(?i)\b(?:inverse|round[- ]?trip|reversibl)\b")
_T_CONSERVES_TOTAL = re.compile(
    r"(?i)\b(?:conserv\w+|sum\s+(?:of\s+)?(?:parts|shares|slices)\s+(?:is|equals?|must\s+(?:be|equal)))\b[^.]{0,80}?\b(total|amount|sum)\b")

_STRINGISH = re.compile(r"(?i)string|str\b|input|^T$|^T\b|`\w*`")
_ARRAYISH = re.compile(r"(?i)(?:readonly\s+)?(?:string|T)\[\]|Array<|readonly\s+\w+\[\]")


# -------------------------------------------------------------------------------------------- #
# F1 — documented example executability
# -------------------------------------------------------------------------------------------- #
def _example_laws(bundle: EvidenceBundle, export: str) -> list[BehaviouralLaw]:
    laws: list[BehaviouralLaw] = []
    for ex in bundle.doc_examples:
        if ex.export != export:
            continue
        if not ex.args and ex.args != []:
            continue
        sha = bundle.module_sha256 if ex.context == "jsdoc" else (bundle.readme_sha256 or bundle.module_sha256)
        g = bundle.grounding(
            source_type="jsdoc" if ex.context == "jsdoc" else "readme_section",
            file=ex.file, line_start=ex.line, line_end=ex.line,
            excerpt=f"{ex.file}:{ex.line} documented call {export}({', '.join(_short(a) for a in ex.args)})",
            sha256=sha,
            extracted={"args": ex.args, "expected_kind": ex.expected_kind, "expected_text": ex.expected_text,
                       "expected_line": ex.expected_line, "context": ex.context})
        params: dict[str, Any] = {"args": ex.args}
        if ex.expected_present and ex.expected_kind in ("literal", "undefined"):
            params["expected"] = ex.expected
            params["expected_kind"] = ex.expected_kind
        elif ex.expected_present and ex.expected_kind == "description":
            params["expected_description"] = ex.expected_text     # recorded, never equality-checked
        statement = (f"A documented call {export}({_short(ex.args)}) must execute without throwing"
                     + (f" and return {ex.expected_text}" if ex.expected_kind in ("literal", "undefined")
                        and ex.expected_present else ""))
        laws.append(BehaviouralLaw(
            law_id=BehaviouralLaw.new_id(), statement=statement, kind="doc_example",
            predicate="example_executable", module=bundle.module, export=export, params=params,
            domain={"args": ex.args}, evidence_class=CLASS_D, grounding=g,
            confidence=0.7 if ex.expected_present else 0.5,
            limitations=(["documented result is prose, not a literal: no equality check is made"]
                         if ex.expected_kind == "description" else []),
            verification={"method": "execute the documented call in a disposable clone (tsx subprocess)"},
            counterexample_schema={"args": "list", "threw": "bool", "returned": "any"},
        ))
    return laws


def _short(v: Any, n: int = 28) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


# -------------------------------------------------------------------------------------------- #
# F2 — splitter boundary law (the boundary-justification family)
# -------------------------------------------------------------------------------------------- #
def _splitter_signature_ok(sig: Signature) -> bool:
    """Applicability corroboration: the machine-readable signature is consistent with a
    splitter — a string-like first parameter and an OPTIONAL trailing parameter (the
    ``splitters`` argument). The primary applicability evidence is the verbatim README
    bullets; this is the second, independent extraction."""
    if not sig.params:
        return False
    p0 = sig.params[0]
    if not _STRINGISH.search(p0.type_text or "string"):
        return False
    if len(sig.params) >= 2:
        if not sig.params[1].optional:
            return False
    return True


def _resolve_default_separators(bundle: EvidenceBundle, sig: Signature,
                                readme_default: list[str] | None) -> tuple[list[str] | None, str]:
    """Resolve the documented default separator list, with provenance of HOW it was obtained.

    Order: (1) the README literal when it parses; (2) a module-level ``const <ID> = <literal>``
    when the optional parameter's default expression is a plain identifier (e.g.
    ``separators = STR_SPLITTERS``) — the constant's literal initializer is machine-extractable
    source; (3) None (unknown) — never guessed. Provenance: 'readme-literal' | 'module-const'
    | 'unknown'.
    """
    if readme_default is not None:
        return readme_default, "readme-literal"
    if len(sig.params) >= 2 and sig.params[1].default_text:
        ident = sig.params[1].default_text.strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", ident):
            m = re.search(r"\bconst\s+" + re.escape(ident) + r"\s*=\s*(\[[^\]]*\])", bundle.module_text)
            if m:
                try:
                    v = parse_literal(m.group(1))
                    if isinstance(v, list):
                        return v, f"module-const:{ident}"
                except LiteralError:
                    pass
    return None, "unknown"


def _splitter_laws(bundle: EvidenceBundle, sig: Signature) -> list[BehaviouralLaw]:
    export = sig.export
    section = bundle.readme_sections.get(export)
    if section is None:
        return []
    lines = [ln.strip() for ln in section.text.splitlines() if ln.strip().startswith(("-", "*"))]
    causes: list[str] = []
    readme_default: list[str] | None = None
    digits_ignored = False
    case_preserved = False
    matched: list[tuple[int, str]] = []
    for ln in lines:
        m = _T_SPLIT_BY_SEPARATORS.match(ln)
        if m:
            causes.append("listed_separator")
            if m.group(1):
                try:
                    v = parse_literal(m.group(1).strip("`"))
                    if isinstance(v, list):
                        readme_default = v
                except LiteralError:
                    pass            # malformed documented literal: fall through to const resolution
            matched.append((section.line_start + _line_index(section.text, ln), ln))
            continue
        if _T_SPLIT_CASE_CHANGE.match(ln):
            causes.append("case_change")
            matched.append((section.line_start + _line_index(section.text, ln), ln))
            continue
        if _T_IGNORES_NUMBERS.match(ln):
            digits_ignored = True
            matched.append((section.line_start + _line_index(section.text, ln), ln))
            continue
        if _T_CASE_PRESERVED.match(ln):
            case_preserved = True
            matched.append((section.line_start + _line_index(section.text, ln), ln))
    if not {"listed_separator", "case_change"} <= set(causes):
        return []          # both structural causes must be documented verbatim, else no law
    if not _splitter_signature_ok(sig):
        return []
    default_sep, default_provenance = _resolve_default_separators(bundle, sig, readme_default)
    first_line, first_text = matched[0]
    g = bundle.grounding(
        source_type="readme_section", file=bundle.readme_file or "README.md",
        line_start=first_line, line_end=section.line_end,
        excerpt="\n".join(t for _, t in matched)[:400], sha256=bundle.readme_sha256 or "",
        extracted={"causes": causes, "default_separators": default_sep,
                   "default_separators_provenance": default_provenance,
                   "digits_ignored": digits_ignored, "case_preserved": case_preserved,
                   "signature_params": [(p.name, p.optional, p.type_text) for p in sig.params]})
    params: dict[str, Any] = {
        "boundary_kinds": ["listed_separator", "case_change"],
        "separators_param_index": 1 if len(sig.params) >= 2 else None,
        "default_separators": default_sep,
        "digits_ignored": digits_ignored,
        "chars_preserved": case_preserved or True,
    }
    statement = (f"{export} may only start a new segment at a listed separator character or at a "
                 f"documented case change (lower→upper or the upper-run→lower rule); "
                 + ("numbers/digits never cause a split; " if digits_ignored else "")
                 + "all other input characters must be preserved in order")
    law = BehaviouralLaw(
        law_id=BehaviouralLaw.new_id(), statement=statement, kind="split_boundary",
        predicate="split_boundary_justified", module=bundle.module, export=export, params=params,
        domain={"string": {"alphabet": ["a", "b", "A", "B", "z", "Z", "1", "9", "-", "_", ".", "/", " ", "é", "Ω"],
                            "min_len": 0, "max_len": 24},
                 "separators": {"choices": [["_"], ["-"], [".", "/"], []], "omit": True},
                 "trials": 400, "seed": 20261103},
        evidence_class=CLASS_D, grounding=g, confidence=0.65,
        limitations=["boundary justification checks the documented causes only; exotic documented "
                     "behaviour outside the README section is out of scope",
                     "the upper-run→lower rule encodes the standard word-splitting semantics of a "
                     "'case change from upper to lower'"],
        verification={"method": "generated strings + separator lists; boundary-position justification "
                                "checked against the input"},
        counterexample_schema={"args": "list", "unjustified_boundary": "int", "segment_before": "str",
                               "segment_after": "str", "boundary_char": "str"},
    )
    # default-separator equivalence: the documented default literal must behave as the implicit default
    laws = [law]
    if default_sep:
        g2 = bundle.grounding(
            source_type="readme_section", file=bundle.readme_file or "README.md",
            line_start=first_line, line_end=section.line_end,
            excerpt=first_text[:400], sha256=bundle.readme_sha256 or "",
            extracted={"default_separators": default_sep})
        laws.append(BehaviouralLaw(
            law_id=BehaviouralLaw.new_id(),
            statement=f"{export}(s) must behave identically to {export}(s, {default_sep!r}) — the "
                      f"documented default separator list",
            kind="split_default_equivalence", predicate="optional_args_equivalent",
            module=bundle.module, export=export,
            params={"n_required": 1, "defaults": [default_sep], "check": "deep_equal"},
            domain={"string": {"alphabet": ["a", "B", "1", "-", "_", ".", "/"], "min_len": 0, "max_len": 20},
                    "trials": 200, "seed": 20261103},
            evidence_class=CLASS_D, grounding=g2, confidence=0.6,
            limitations=["only the documented default literal is checked"],
            verification={"method": "call both forms on generated strings, compare deeply"},
            counterexample_schema={"args": "list", "with_default": "any", "without_default": "any"},
        ))
    return laws


def _line_index(section_text: str, line: str) -> int:
    for i, ln in enumerate(section_text.splitlines()):
        if ln.strip() == line:
            return i
    return 0


# -------------------------------------------------------------------------------------------- #
# F3 — optional-argument law (signature-grounded)
# -------------------------------------------------------------------------------------------- #
def _optional_arg_laws(bundle: EvidenceBundle, sig: Signature) -> list[BehaviouralLaw]:
    laws: list[BehaviouralLaw] = []
    # 'required arity' = position of the first optional parameter: the function documents
    # (via the machine-readable signature) that it is callable with every prefix of arguments
    # up to that point.
    first_optional = next((i for i, p in enumerate(sig.params) if p.optional), len(sig.params))
    n_required = first_optional
    optional_tail = sig.params[first_optional:]
    if not optional_tail or n_required < 0:
        return laws
    literal_defaults: list[Any] = []
    default_omissions: list[bool] = []
    all_literal = True
    for p in optional_tail:
        default_omissions.append(p.default_text is None or p.default_text.strip() == "undefined")
        if p.default_text is None:
            literal_defaults.append(None)
            continue
        try:
            literal_defaults.append(parse_literal(p.default_text))
        except LiteralError:
            all_literal = False
            literal_defaults.append(None)
    g = bundle.grounding(
        source_type="signature", file=bundle.module, line_start=sig.line_start, line_end=sig.line_end,
        excerpt=f"export function {sig.export}({', '.join(p.name + ('?' if p.optional else '') for p in sig.params)})",
        sha256=bundle.module_sha256,
        extracted={"params": [(p.name, p.optional, p.default_text, p.type_text) for p in sig.params],
                   "n_required": n_required})
    params: dict[str, Any] = {"n_required": n_required, "defaults": literal_defaults if all_literal else None,
                              "default_omissions": default_omissions,
                              "check": "no_throw_and_equal"}
    laws.append(BehaviouralLaw(
        law_id=BehaviouralLaw.new_id(),
        statement=(f"{sig.export} declares its trailing parameter(s) optional in the machine-readable "
                   f"signature, so calling it with only the required arguments must be supported"),
        kind="optional_args", predicate="optional_args_equivalent",
        module=bundle.module, export=sig.export, params=params,
        domain={"trials": 200, "seed": 20261103,
                "required_types": [p.type_text for p in sig.params[:n_required]]},
        evidence_class=CLASS_D, grounding=g, confidence=0.75,
        limitations=["a signature does not establish totality or equivalence on generated inputs; requires review",
                     "equivalence is compared deeply; non-literal default expressions fall back to a "
                     "no-throw check on the required-arguments call"],
        verification={"method": "call with required args only (must not throw); when defaults are literal, "
                                "compare against the call with explicit defaults"},
        counterexample_schema={"args": "list", "threw": "bool", "with_defaults": "any", "without_defaults": "any"},
    ))
    return laws


# -------------------------------------------------------------------------------------------- #
# F4 — preservation cases (the project's own tests)
# -------------------------------------------------------------------------------------------- #
def _preservation_laws(bundle: EvidenceBundle, export: str, cap: int = 40) -> list[BehaviouralLaw]:
    laws: list[BehaviouralLaw] = []
    for pair in bundle.test_pairs.get(export, [])[:cap]:
        sha = bundle.test_files.get(pair.file, bundle.module_sha256)
        g = bundle.grounding(
            source_type="test_assertion", file=pair.file, line_start=pair.line, line_end=pair.line,
            excerpt=f"{pair.file}:{pair.line} expect({export}(...)).{pair.matcher}(...)",
            sha256=sha,
            extracted={"args": pair.args, "expected": pair.expected, "matcher": pair.matcher})
        laws.append(BehaviouralLaw(
            law_id=BehaviouralLaw.new_id(),
            statement=f"{export}({_short(pair.args)}) must keep returning {_short(pair.expected)} — "
                      f"the project's own passing baseline",
            kind="preservation_case", predicate="preservation_case",
            module=bundle.module, export=export,
            params={"args": pair.args, "expected": pair.expected, "matcher": pair.matcher},
            domain={"args": pair.args}, evidence_class=CLASS_C, grounding=g, confidence=0.9,
            limitations=["baseline behaviour is preserved behaviour, not verified-correct behaviour"],
            verification={"method": "replay the extracted I/O pair in a disposable clone"},
            counterexample_schema={"args": "list", "expected": "any", "observed": "any"},
        ))
    return laws


# -------------------------------------------------------------------------------------------- #
# F5-F7 — round-trip / idempotence / conservation (documented-statement families)
# -------------------------------------------------------------------------------------------- #
def _round_trip_laws(bundle: EvidenceBundle) -> list[BehaviouralLaw]:
    """Type-inverse export pairs in the same module, proposed only when docs state the inverse."""
    laws: list[BehaviouralLaw] = []
    sigs = {s.export: s for s in bundle.signatures}
    readme = bundle.readme_sections
    for enc_name, dec_name in (("encode", "decode"), ("stringify", "parse"), ("serialize", "deserialize")):
        cands = [(a, b) for a in sigs for b in sigs
                 if a.startswith(enc_name) and b.startswith(dec_name) and a != b]
        for a, b in cands:
            sa, sb = sigs[a], sigs[b]
            sec_b = readme.get(b)
            if sec_b is None or not _T_ROUND_TRIP.search(sec_b.text):
                continue          # applicability needs the documented inverse statement
            g = bundle.grounding(
                source_type="structural_pair", file=bundle.module, line_start=sb.line_start,
                line_end=sb.line_end,
                excerpt=f"{a}: {sa.return_type} / {b}: {sb.return_type} + README inverse statement",
                sha256=bundle.module_sha256,
                extracted={"encode": a, "decode": b})
            laws.append(BehaviouralLaw(
                law_id=BehaviouralLaw.new_id(),
                statement=f"{b}({a}(x)) must return x for supported x — documented inverse pair",
                kind="round_trip", predicate="round_trip",
                module=bundle.module, export=b,
                params={"forward": a, "inverse": b},
                domain={"string": {"alphabet": ["a", "B", "1", "&", ";", "#", " ", "é", "<", ">", '"', "'"],
                                    "min_len": 0, "max_len": 16}, "trials": 300, "seed": 20261103},
                evidence_class=CLASS_D, grounding=g, confidence=0.45,
                limitations=["round-trip holds only for SUPPORTED values; a violation is a falsified "
                             "hypothesis for review, not automatically a defect"],
                verification={"method": "generate strings, apply forward then inverse, compare"},
                counterexample_schema={"input": "any", "encoded": "any", "decoded": "any"},
            ))
    return laws


def _idempotence_laws(bundle: EvidenceBundle) -> list[BehaviouralLaw]:
    laws: list[BehaviouralLaw] = []
    for sig in bundle.signatures:
        sec = bundle.readme_sections.get(sig.export)
        if sec is None:
            continue
        hit = next((ln for ln in sec.text.splitlines() if _T_NORMALIZES.match(ln.strip())), None)
        if hit is None:
            continue
        g = bundle.grounding(
            source_type="readme_section", file=bundle.readme_file or "README.md",
            line_start=sec.line_start, line_end=sec.line_end, excerpt=hit.strip()[:400],
            sha256=bundle.readme_sha256 or "",
            extracted={"sentence": hit.strip()})
        laws.append(BehaviouralLaw(
            law_id=BehaviouralLaw.new_id(),
            statement=f"{sig.export} normalises its input, so applying it twice must equal applying "
                      f"it once (canonical form is a fixed point)",
            kind="idempotence", predicate="idempotence", module=bundle.module, export=sig.export,
            params={},
            domain={"string": {"alphabet": ["a", "B", "1", "-", "/", ":", "é"], "min_len": 0, "max_len": 18},
                    "trials": 200, "seed": 20261103},
            evidence_class=CLASS_D, grounding=g, confidence=0.35,
            limitations=["normalisation statements are interpreted; violations are hypotheses"],
            verification={"method": "compare f(f(x)) with f(x) on generated inputs"},
            counterexample_schema={"input": "any", "once": "any", "twice": "any"},
        ))
    return laws


def _conservation_laws(bundle: EvidenceBundle) -> list[BehaviouralLaw]:
    """Numeric allocation: (number, number) -> number[] documented to conserve the total."""
    laws: list[BehaviouralLaw] = []
    for sig in bundle.signatures:
        if len(sig.params) < 2:
            continue
        p0, p1 = sig.params[0], sig.params[1]
        rt = sig.return_type or ""
        if not (re.search(r"number", p0.type_text or "") and re.search(r"number", p1.type_text or "")
                and re.search(r"number\s*\[\]|Array\s*<\s*number\s*>", rt)):
            continue
        sec = bundle.readme_sections.get(sig.export)
        if sec is None or not _T_CONSERVES_TOTAL.search(sec.text):
            continue
        hit = next(ln for ln in sec.text.splitlines() if _T_CONSERVES_TOTAL.search(ln))
        g = bundle.grounding(
            source_type="readme_section", file=bundle.readme_file or "README.md",
            line_start=sec.line_start, line_end=sec.line_end, excerpt=hit.strip()[:400],
            sha256=bundle.readme_sha256 or "",
            extracted={"sentence": hit.strip(), "signature": f"{p0.name},{p1.name} -> {rt}"})
        laws.append(BehaviouralLaw(
            law_id=BehaviouralLaw.new_id(),
            statement=f"{sig.export} splits a total across parts and the parts must sum back to the "
                      f"total (no unit created or destroyed)",
            kind="conservation_sum", predicate="conservation_sum", module=bundle.module, export=sig.export,
            params={"total_index": 0, "parts_index": 1},
            domain={"numbers": {"min": 0, "max": 10_000}, "parts": {"min": 1, "max": 12},
                    "trials": 300, "seed": 20261103},
            evidence_class=CLASS_D, grounding=g, confidence=0.55,
            limitations=["conservation is checked exactly for integer totals in the generated domain"],
            verification={"method": "generate (total, parts), compare sum(parts) with total"},
            counterexample_schema={"args": "list", "total": "number", "sum_returned": "number"},
        ))
    return laws


# -------------------------------------------------------------------------------------------- #
# F8 — determinism (hypothesis-grade)
# -------------------------------------------------------------------------------------------- #
def _determinism_laws(bundle: EvidenceBundle, export: str) -> list[BehaviouralLaw]:
    sigs = {s.export: s for s in bundle.signatures}
    sig = sigs.get(export)
    if sig is None:
        return []
    g = bundle.grounding(
        source_type="signature", file=bundle.module, line_start=sig.line_start, line_end=sig.line_end,
        excerpt=f"export function {sig.export}(...) — pure-utility signature",
        sha256=bundle.module_sha256, extracted={"export": export})
    seed_args = None
    for ex in bundle.doc_examples:
        if ex.args:
            seed_args = ex.args
            break
    if seed_args is None:
        for p in bundle.test_pairs.get(export, []):
            seed_args = p.args
            break
    if seed_args is None:
        return []
    return [BehaviouralLaw(
        law_id=BehaviouralLaw.new_id(),
        statement=f"{export} is a pure utility: the same input must produce the same output within a run",
        kind="determinism", predicate="determinism", module=bundle.module, export=export,
        params={"seed_args": seed_args, "repeats": 3},
        domain={"args": seed_args}, evidence_class=CLASS_D, grounding=g, confidence=0.3,
        limitations=["a violation may indicate intentional nondeterminism; hypothesis only"],
        verification={"method": "call twice with identical args, compare deeply"},
        counterexample_schema={"args": "list", "first": "any", "second": "any"},
    )]


# -------------------------------------------------------------------------------------------- #
# The compiler entry point
# -------------------------------------------------------------------------------------------- #
def compile_laws(bundle: EvidenceBundle, *, exports_of_interest: list[str] | None = None,
                 include_preservation: bool = True, max_laws: int = 400) -> list[BehaviouralLaw]:
    """Compile candidate behavioural laws from the collected evidence.

    ``include_preservation=False`` is used when the baseline itself is under investigation
    (discovery mode): preservation cases PASS on the baseline by construction and add noise,
    so discovery focuses on non-baseline evidence. In ``check`` (change) mode preservation is
    the regression backbone and is included.
    """
    laws: list[BehaviouralLaw] = []
    exports = exports_of_interest or [s.export for s in bundle.signatures]
    for sig in bundle.signatures:
        if sig.export not in exports:
            continue
        laws += _example_laws(bundle, sig.export)
        laws += _splitter_laws(bundle, sig)
        laws += _optional_arg_laws(bundle, sig)
        if include_preservation:
            laws += _preservation_laws(bundle, sig.export)
        laws += _determinism_laws(bundle, sig.export)
    laws += _round_trip_laws(bundle)
    laws += _idempotence_laws(bundle)
    laws += _conservation_laws(bundle)
    # dedupe by digest (same law discovered from two readings keeps ONE identity)
    seen: dict[str, BehaviouralLaw] = {}
    for law in laws:
        d = law.digest()
        law.law_id = f"bde-law-{d[:10]}"
        if d not in seen:
            seen[d] = law
    out = list(seen.values())
    return out[:max_laws]
