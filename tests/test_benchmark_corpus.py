"""The frozen benchmark corpus is internally consistent, schema-legal and untampered.

These tests are hermetic: they read the committed manifest and never run an agent or the oracle.
Their point is that the corpus cannot drift after the freeze — the manifest carries its own hash,
every contract must satisfy the independent verifier's published schema limits, and the pre-freeze
gate results must all be present and passing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "BENCHMARK-MANIFEST-v0.2.0.json"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="manifest not frozen yet")

# Limits read out of the pinned verifier's own contract schema (sentinel-verified src/schema.ts).
LIMITS = {"approvedBy": 200, "objective": 5000, "req_id": 100, "description": 2000,
          "module": 500, "cases": 100, "args": 20, "requirements": 100, "allowedPaths": 500}
EXPORT_RE = re.compile(r"^[a-zA-Z_$][\w$]*$")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_manifest_hash_recomputes_exactly():
    """The committed manifest is byte-for-byte the object that was hashed at freeze time."""
    m = _manifest()
    recorded = m.pop("manifest_sha256")
    blob = json.dumps(m, indent=2, ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(blob.encode()).hexdigest() == recorded, \
        "the frozen manifest was modified after the freeze"


def test_every_task_passed_every_pre_freeze_condition():
    m = _manifest()
    validations = {v["task"]: v for v in m["pre_freeze_validation"]}
    assert set(validations) == {t["id"] for t in m["tasks"]}, "a task was never validated"
    for tid, v in validations.items():
        assert v["valid"] is True, f"{tid} was frozen despite failing its gate"
        # the defect is real and the project's own tests cannot see it
        assert v["baseline"]["ok"] is False and v["baseline"]["verdict"] == "CONTRADICTED", tid
        assert v["baseline_ordinary_tests"]["passed"] is True, tid
        # the upstream fix satisfies the same oracle
        assert v["fix"]["ok"] is True and v["fix"]["verdict"] == "VERIFIED", tid
        assert v["fix_ordinary_tests"]["passed"] is True, tid
        # and a correct repair does not turn the project's own baseline suite red (arm A fairness)
        assert v["fix_src_only"]["changed"], f"{tid}: the upstream fix changed nothing in scope"
        assert v["fix_src_only"]["ordinary_tests"]["passed"] is True, tid


def test_every_contract_is_within_the_verifiers_published_schema_limits():
    m = _manifest()
    for tid, c in m["contracts"].items():
        assert c["schemaVersion"] == 1
        assert 1 <= len(c["objective"]) <= LIMITS["objective"], tid
        assert 1 <= len(c["approvedBy"]) <= LIMITS["approvedBy"], f"{tid}: approvedBy too long"
        assert 1 <= len(c["requirements"]) <= LIMITS["requirements"], tid
        assert 1 <= len(c.get("allowedPaths") or []) <= LIMITS["allowedPaths"], tid
        kinds = set()
        for r in c["requirements"]:
            assert 1 <= len(r["id"]) <= LIMITS["req_id"], tid
            assert 1 <= len(r["description"]) <= LIMITS["description"], tid
            assert r["kind"] in ("must-change", "must-preserve"), tid
            assert EXPORT_RE.match(r["export"]), f"{tid}: {r['export']!r} is not a valid export name"
            assert 1 <= len(r["cases"]) <= LIMITS["cases"], tid
            assert not r["module"].startswith("/") and ".." not in r["module"].split("/"), tid
            assert len(r["module"]) <= LIMITS["module"], tid
            for case in r["cases"]:
                assert set(case) == {"args", "expected"}, tid
                assert len(case["args"]) <= LIMITS["args"], tid
            kinds.add(r["kind"])
        # a preserve-only contract cannot establish a change objective
        assert "must-change" in kinds, f"{tid}: no must-change requirement"
        for p in c["allowedPaths"]:
            assert not p.startswith("/") and ".." not in p.split("/"), f"{tid}: {p}"


def test_each_task_pins_a_real_upstream_fix_and_a_distinct_baseline():
    m = _manifest()
    for t in m["tasks"]:
        assert t["fix_commit"] and t["fix_subject"], t["id"]
        assert t["project"] in m["projects"], t["id"]
        assert m["projects"][t["project"]]["license"] in ("MIT", "ISC", "BSD-2-Clause",
                                                          "BSD-3-Clause", "Apache-2.0"), t["id"]
        assert t["criteria_source"], f"{t['id']} has no stated provenance for its criteria"
        assert len(t["prompt"]) > 200, f"{t['id']} prompt is too thin to be a fair brief"
        assert t["kind"].startswith("historical-"), t["id"]
        # the frozen contract, not the task record, is what the oracle was validated against
        assert m["contracts"][t["id"]]["allowedPaths"], f"{t['id']} has no change scope"


def test_corpus_spans_at_least_three_independent_projects():
    m = _manifest()
    projects = {t["project"] for t in m["tasks"]}
    assert len(projects) >= 3, f"corpus covers only {sorted(projects)}"
    urls = {m["projects"][p]["url"] for p in projects}
    assert len(urls) == len(projects), "two corpus projects share a repository"


def test_selection_process_records_what_was_rejected_and_why():
    """Omission must be auditable, otherwise a small corpus is indistinguishable from cherry-picking."""
    sp = _manifest()["selection_process"]
    for key in ("method", "projects_considered", "excluded", "measured_corpus_constraints",
                "no_selective_omission", "corpus_size_honesty", "disclosed_extra_cases",
                "ordinary_test_command"):
        assert sp.get(key), f"selection_process is missing {key}"
    assert len(sp["excluded"]) >= 10, "rejected candidates are not enumerated"
    assert all(len(reason) > 40 for reason in sp["excluded"].values()), \
        "an exclusion lacks a substantive measured reason"
    assert any("12-20" in sp["corpus_size_honesty"] or "12–20" in sp["corpus_size_honesty"]
               for _ in [0]), "the shortfall against the requested corpus size is not disclosed"


def test_manifest_leaks_no_machine_local_absolute_path():
    text = MANIFEST.read_text()
    assert str(ROOT) not in text, "the frozen manifest embeds this machine's checkout path"
    assert "/Users/" not in text and "/home/" not in text, "the manifest embeds a home directory"


def test_verifier_and_agent_identity_are_pinned():
    m = _manifest()
    assert re.fullmatch(r"[0-9a-f]{40}", m["verifier"]["pinned_commit"]), "verifier is not pinned"
    assert "not a security boundary" in m["verifier"]["runner"], \
        "the local advisory runner must be labelled as not a security boundary"
    # the recorded note must deny the bypass flag rather than merely mention it
    assert "no --dangerously-skip-permissions" in m["agent"]["note"], \
        "the manifest does not state that the permission bypass flag is absent"
    assert m["agent"]["sandbox"] == "workspace-write"
    assert re.fullmatch(r"[0-9a-f]{40}", m["harness"]["git_head"]), "harness commit is not pinned"
    assert m["harness"]["git_dirty"] is False, "the manifest was frozen from a dirty tree"


def test_arms_are_defined_and_the_a_b_pairing_is_disclosed():
    m = _manifest()
    assert set(m["arms"]) == {"A", "B", "C"}
    assert "one shared agent session" in m["arm_pairing"].lower(), \
        "arms A and B are paired on one session; that must be stated, not implied"


# --------------------------------------------------------------------------- #
# The separate Codex run: gated by date, isolated artifacts, drift-proof corpus
# --------------------------------------------------------------------------- #
def _harness():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sg_bench_harness", ROOT / "benchmark" / "harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_codex_run_cannot_overwrite_the_completed_claude_results():
    H = _harness()
    assert H.RUNS["claude"]["results"] != H.RUNS["codex"]["results"]
    assert H.RUNS["claude"]["report"] != H.RUNS["codex"]["report"]
    assert H.RUNS["codex"]["results"].name.endswith("-codex.json")
    # the completed Claude run is identified as such inside its own artifact
    recorded = json.loads(H.RUNS["claude"]["results"].read_text())
    assert (recorded.get("agent") or {}).get("name") == "claude"


def test_the_codex_run_is_gated_to_its_authorised_date():
    from datetime import date
    H = _harness()
    assert H.RUNS["codex"]["not_before"] == "2026-11-09", \
        "the Codex benchmark was authorised for no earlier than 2026-11-09"
    assert H.RUNS["claude"]["not_before"] is None      # already executed
    if date.today().isoformat() < H.RUNS["codex"]["not_before"]:
        with pytest.raises(SystemExit, match="no earlier than"):
            H.run(agent="codex")


def test_corpus_integrity_detects_a_prompt_edited_after_the_freeze():
    H = _harness()
    manifest = json.loads(MANIFEST.read_text())
    assert H.corpus_integrity(manifest)["ok"] is True, "the live corpus drifted from the freeze"

    task = next(t for t in H.TASKS if t["id"] == "scule-splitbycase-numbers")
    original = task["prompt"]
    try:
        task["prompt"] = original + " Also special-case the digit 3."
        drifted = H.corpus_integrity(manifest)
        assert drifted["ok"] is False
        assert any("prompt differs" in d for d in drifted["drift"]), drifted["drift"]
    finally:
        task["prompt"] = original
    assert H.corpus_integrity(manifest)["ok"] is True


def test_corpus_integrity_detects_a_changed_expected_value():
    H = _harness()
    manifest = json.loads(MANIFEST.read_text())
    task = next(t for t in H.TASKS if t["id"] == "entities-legacy-attribute-interrupted")
    req = task["requirements"][0]
    original = req["cases"][0]["expected"]
    try:
        req["cases"][0]["expected"] = "something-else"
        drifted = H.corpus_integrity(manifest)
        assert drifted["ok"] is False
        assert any("contract differs" in d for d in drifted["drift"]), drifted["drift"]
    finally:
        req["cases"][0]["expected"] = original
    assert H.corpus_integrity(manifest)["ok"] is True


def test_a_dropped_task_is_detected_as_corpus_drift():
    H = _harness()
    manifest = json.loads(MANIFEST.read_text())
    held = H.TASKS.pop()
    try:
        drifted = H.corpus_integrity(manifest)
        assert drifted["ok"] is False
        assert any("missing from the corpus" in d for d in drifted["drift"]), drifted["drift"]
    finally:
        H.TASKS.append(held)
    assert H.corpus_integrity(manifest)["ok"] is True
