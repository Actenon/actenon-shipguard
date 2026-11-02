"""Strategy selection: one compiled law -> one executable lawpack entry.

The runner's ``gen`` block is derived ONLY from the law's ``domain`` (which the compiler
built from grounded evidence) and the reviewed predicate's requirements. No law-specific
code exists on this path — the same translation serves every project.
"""
from __future__ import annotations

from typing import Any

from .laws import BehaviouralLaw

_STD_ALPHABET = ["a", "b", "B", "z", "Z", "1", "9", "-", "_", ".", "/", " ", "é", "Ω"]


def _stringish(type_text: str | None) -> bool:
    t = (type_text or "").lower()
    return any(k in t for k in ("string", "input", "str", "`t`", "t extends", "template")) or t in ("t", "")


def _arg_spec_from_type(type_text: str | None, domain_string: dict[str, Any] | None) -> dict[str, Any]:
    t = (type_text or "").strip()
    if t and not _stringish(t) and ("number" in t.lower() or t in ("number",)):
        return {"kind": "int", "min": 0, "max": 100}
    sd = domain_string or {}
    return {"kind": "string", "alphabet": sd.get("alphabet") or _STD_ALPHABET,
            "min_len": sd.get("min_len", 0), "max_len": sd.get("max_len", 16)}


def execution_for(law: BehaviouralLaw) -> dict[str, Any] | None:
    """Translate a law into a runner entry; None when the law is not executable as compiled."""
    p, d = law.params, law.domain or {}
    entry: dict[str, Any] = {"law_id": law.law_id, "predicate": law.predicate, "export": law.export,
                             "params": dict(p)}
    if law.predicate in ("example_executable", "preservation_case", "determinism", "no_throw"):
        if not isinstance(d.get("args"), list):
            return None
        # Literal-mode laws: the DOCUMENTED call is the witness. Shrinking the arguments of a
        # documented example while keeping its expected result would manufacture a different
        # (undocumented) claim — so the original arguments are preserved verbatim.
        entry["gen"] = {"mode": "literal", "args": d["args"], "shrink": False}
        if law.predicate == "determinism":
            entry["params"] = {**p}
        return entry

    if law.predicate == "optional_args_equivalent":
        sd = d.get("string") or {}
        specs = [_arg_spec_from_type(None, sd)]
        entry["gen"] = {"mode": "generated", "arg_specs": specs, "trials": d.get("trials", 200),
                        "seed": d.get("seed", 1234567)}
        return entry

    if law.predicate == "split_boundary_justified":
        sd = d.get("string") or {}
        sep = d.get("separators") or {}
        choices = [list(c) for c in (sep.get("choices") or [])]
        specs = [{"kind": "string", "alphabet": sd.get("alphabet") or _STD_ALPHABET,
                  "min_len": sd.get("min_len", 0), "max_len": sd.get("max_len", 20)}]
        if p.get("separators_param_index") is not None:
            specs.append({"kind": "choice", "values": ([None] + choices) if sep.get("omit", True) else choices})
        entry["gen"] = {
            "mode": "generated", "arg_specs": specs, "trials": d.get("trials", 400),
            "seed": d.get("seed", 1234567),
            "grid": {"core_alphabet": ["a", "A", "1", "-"],
                     "separator_choices": choices or [[]]},
        }
        return entry

    if law.predicate == "round_trip":
        sd = d.get("string") or {}
        entry["gen"] = {"mode": "generated",
                        "arg_specs": [{"kind": "string", "alphabet": sd.get("alphabet") or _STD_ALPHABET,
                                        "min_len": sd.get("min_len", 0), "max_len": sd.get("max_len", 16)}],
                        "trials": d.get("trials", 300), "seed": d.get("seed", 1234567)}
        return entry

    if law.predicate == "idempotence":
        sd = d.get("string") or {}
        entry["gen"] = {"mode": "generated",
                        "arg_specs": [{"kind": "string", "alphabet": sd.get("alphabet") or _STD_ALPHABET,
                                        "min_len": sd.get("min_len", 0), "max_len": sd.get("max_len", 18)}],
                        "trials": d.get("trials", 200), "seed": d.get("seed", 1234567)}
        return entry

    if law.predicate == "conservation_sum":
        nm, np_ = d.get("numbers") or {}, d.get("parts") or {}
        entry["gen"] = {"mode": "generated",
                        "arg_specs": [{"kind": "int", "min": nm.get("min", 0), "max": nm.get("max", 10000)},
                                        {"kind": "int", "min": np_.get("min", 1), "max": np_.get("max", 12)}],
                        "trials": d.get("trials", 300), "seed": d.get("seed", 1234567)}
        return entry
    return None
