"""v0.2.0 benchmark harness — frozen corpus, three execution arms, honest measurement.

Design rules enforced here (mandate Phase 3/4):
  * Tasks come from REAL projects at PINNED revisions and REAL historical fix commits. The baseline
    is the fix commit's parent, so the defect is the project's own genuine defect.
  * Acceptance criteria are the project's OWN real test assertions introduced by that fix — never
    invented to make an agent fail, and nothing essential is withheld from the prompt.
  * The manifest is FROZEN (hashed) before any experimental agent runs.
  * Each arm gets a fresh clone and a fresh agent session; every outcome is recorded, including
    first-try successes, no-change, refusals, timeouts and environment failures.
  * Ground truth is evaluated independently with the real Sentinel verifier against the frozen
    contract for ALL arms, so an initially correct solution is never counted as a failure.

Usage:
    python benchmark/harness.py validate    # check every contract: baseline CONTRADICTED, fix VERIFIED
    python benchmark/harness.py freeze      # write BENCHMARK-MANIFEST-v0.2.0.json
    python benchmark/harness.py run         # execute the three arms, write BENCHMARK-RESULTS-v0.2.0.json
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from actenon_shipguard.adapters.base import git_diff  # noqa: E402
from actenon_shipguard.adapters.codex import CodexAdapter  # noqa: E402
from actenon_shipguard.orchestrator import (  # noqa: E402
    _commit_candidate,
    _feedback,
    _portable,
    exclude_node_modules,
    is_detected_defect,
    repo_fingerprint,
    run_ordinary_tests,
    run_sentinel_challenge,
    validate_change_scope,
)
from actenon_shipguard.sentinel import bind_committed_tree, find_sentinel  # noqa: E402


def _default_node_modules() -> Path:
    """A checkout of the pinned Sentinel provides vitest/tsx; no benchmark-time installs."""
    for cand in (REPO_ROOT.parent / "sentinel-verified" / "node_modules",
                 Path("/tmp/sentinel-verified/node_modules")):
        if (cand / "vitest").exists():
            return cand
    return Path("/tmp/sentinel-verified/node_modules")


CACHE = Path(os.environ.get("SHIPGUARD_BENCH_CACHE", "/tmp/sg-bench-cache"))
NODE_MODULES = Path(os.environ.get("SHIPGUARD_NODE_MODULES") or _default_node_modules())
MANIFEST = REPO_ROOT / "BENCHMARK-MANIFEST-v0.2.0.json"
RESULTS = REPO_ROOT / "BENCHMARK-RESULTS-v0.2.0.json"

PROJECTS = {
    "scule": {
        "url": "https://github.com/unjs/scule.git",
        "license": "MIT", "language": "TypeScript (ESM)", "module": "src/index.ts",
        "test_command": "vitest run", "deps": [],
    },
    "ufo": {
        "url": "https://github.com/unjs/ufo.git",
        "license": "MIT", "language": "TypeScript (ESM)", "module": "src/utils.ts",
        "test_command": "vitest run", "deps": [],
    },
    "entities": {
        "url": "https://github.com/fb55/entities.git",
        "license": "BSD-2-Clause", "language": "TypeScript (ESM)", "module": "src/decode.ts",
        "test_command": "vitest run", "deps": [],
        "test_scope_note": ("The upstream `test` script is `npm run test:vi && npm run lint`; only the "
                            "vitest half is behavioural, so the lint step is dropped from the "
                            "COMMAND. No test file was edited"),
    },
}


def task_module(task: dict) -> str:
    """The module the agent may edit and that Sentinel imports for the checks."""
    return task.get("module") or PROJECTS[task["project"]]["module"]


def task_export(task: dict) -> str:
    """Primary export named in the prompt; a task may constrain several exports."""
    reqs = task.get("requirements") or [{}]
    return reqs[0].get("export", "default")


def task_allowed(task: dict) -> list[str]:
    return task.get("allowed_paths") or [task_module(task)]


def _req(rid: str, kind: str, description: str, module: str, export: str, cases: list) -> dict:
    return {"id": rid, "kind": kind, "description": description, "module": module,
            "export": export, "cases": [{"args": a, "expected": e} for a, e in cases]}


# ------------------------------------------------------------------------------------------- #
# FROZEN TASK CORPUS
#
# Each task is a REAL historical change in a REAL permissively-licensed project (MIT, or ISC for
# jsonrepair). `fix_commit` is the upstream commit that fixed the defect; the benchmark baseline is
# its parent, so the agent faces the project's genuine pre-fix state. Acceptance criteria are
# assertions from the project's own test suite at the fix commit, and every expected value was
# measured by executing the real code at both revisions.
# ------------------------------------------------------------------------------------------- #
TASKS: list[dict[str, Any]] = [
    {
        "id": "scule-custom-separator-split",
        "project": "scule",
        "fix_commit": "57cfd15",
        "fix_subject": "fix(isUppercase): assume characters lowercase by default (#71)",
        "kind": "historical-defect",
        "module": "src/index.ts",
        "allowed_paths": ["src/index.ts"],
        "prompt": (
            "In this project, splitByCase(str, separators) splits a string into words at case "
            "boundaries and at the given separator characters. Characters whose case cannot be "
            "determined (for example digits and punctuation such as '-') must be treated as "
            "lowercase by default, so they never start a new segment on their own. With the custom "
            "separator list ['_'], an input like 'new-name-value' contains no separators and no case "
            "boundary, so it must come back as the single segment ['new-name-value']. Fix the "
            "case-detection default. Edit only src/index.ts."),
        "criteria_source": "upstream test/scule.test.ts at 57cfd15",
        "requirements": [
            _req("custom-separator-no-split", "must-change",
                 "A string with no listed separator and no case boundary is a single segment",
                 "src/index.ts", "splitByCase",
                 [(["new-name-value", ["_"]], ["new-name-value"])]),
            _req("preserve-default-splitting", "must-preserve",
                 "Default splitting behaviour is unchanged",
                 "src/index.ts", "splitByCase",
                 [(["FooBARb"], ["Foo", "BA", "Rb"]), (["FOO_BAR"], ["FOO", "BAR"])]),
        ],
    },
    {
        "id": "ufo-withoutbase-leading-slashes",
        "project": "ufo",
        "fix_commit": "5cd9e67",
        "fix_subject": "fix(withoutBase): collapse leading slashes (#335)",
        "kind": "historical-defect",
        "prompt": (
            "In this project, withoutBase(input, base) strips a base path from an input path. After "
            "stripping, any run of leading slashes in the remainder must collapse to a single "
            "leading slash. Without this, an input such as '/legacy//evil.com' with base '/legacy' "
            "yields '//evil.com', which browsers treat as a protocol-relative URL and is a URL "
            "injection risk. Fix withoutBase so the result never begins with multiple slashes. "
            "Edit only src/utils.ts."),
        "criteria_source": "upstream test/base.test.ts at 5cd9e67",
        "requirements": [
            _req("collapse-leading-slashes", "must-change",
                 "withoutBase collapses leading slashes so a protocol-relative URL cannot be produced",
                 "src/utils.ts", "withoutBase",
                 [(["/legacy//evil.com", "/legacy"], "/evil.com"),
                  (["/legacy//evil.com", "/legacy/"], "/evil.com"),
                  (["/legacy///evil.com", "/legacy"], "/evil.com"),
                  (["/legacy//", "/legacy"], "/")]),
        ],
    },
    {
        "id": "ufo-false-prefix-match",
        "project": "ufo",
        "fix_commit": "eb29945",
        "fix_subject": "fix(withBase, withoutBase): prevent false prefix matches (#313)",
        "kind": "historical-defect",
        "prompt": (
            "In this project, withBase(input, base) and withoutBase(input, base) must only treat the "
            "base as a path prefix at a real path-segment boundary. A base of '/admin' or '/admin/' "
            "must NOT match an input such as '/admin-dashboard', because 'admin-dashboard' is a "
            "different path segment. Fix both functions so prefix matching is segment-aware: "
            "withBase('/admin-dashboard', '/admin/') should give '/admin/admin-dashboard', and "
            "withoutBase('/admin-dashboard', '/admin/') should leave the input unchanged. Edit only "
            "src/utils.ts."),
        "criteria_source": "upstream test/base.test.ts at eb29945",
        "requirements": [
            _req("withbase-segment-boundary", "must-change",
                 "withBase only skips a base that matches whole path segments",
                 "src/utils.ts", "withBase",
                 [(["/admin-dashboard", "/admin/"], "/admin/admin-dashboard"),
                  (["/admin/admin-dashboard", "/admin/"], "/admin/admin-dashboard"),
                  (["/admin-dashboard", "/admin"], "/admin/admin-dashboard")]),
            _req("withoutbase-segment-boundary", "must-change",
                 "withoutBase only strips a base that matches whole path segments",
                 "src/utils.ts", "withoutBase",
                 [(["/admin/dashboard", "/admin/"], "/dashboard"),
                  (["/admin-dashboard", "/admin/"], "/admin-dashboard"),
                  (["/admin/admin-dashboard", "/admin/"], "/admin-dashboard")]),
        ],
    },
    {
        "id": "scule-splitbycase-numbers",
        "project": "scule",
        "fix_commit": "9927800",
        "fix_subject": "fix: ignore case changes for numbers",
        "kind": "historical-defect",
        "module": "src/index.ts",
        "allowed_paths": ["src/index.ts"],
        "prompt": (
            "In this project `splitByCase(str)` splits a string at the default separators "
            "('-', '_', '/', '.') and at case transitions (lower->upper and upper->lower). Digits "
            "have no case, so a digit must NOT be treated as a case transition: 'foo123-bar' must "
            "split into ['foo123', 'bar'] and not break the digits away from the letters around "
            "them. Fix the splitting so numbers are ignored for case changes, while the existing "
            "splitting of letters is unchanged. Edit only src/index.ts."),
        "criteria_source": "upstream test/scule.test.ts at 9927800",
        "requirements": [
            _req("digits-are-not-case-changes", "must-change",
                 "splitByCase does not split at a digit boundary",
                 "src/index.ts", "splitByCase",
                 [(["foo123-bar"], ["foo123", "bar"])]),
            _req("preserve-letter-splitting", "must-preserve",
                 "Existing letter-case and separator splitting is unchanged",
                 "src/index.ts", "splitByCase",
                 [(["FOOBar"], ["FOO", "Bar"]),
                  (["foo--bar-Baz"], ["foo", "", "bar", "Baz"]),
                  (["FooBarBaz"], ["Foo", "Bar", "Baz"])]),
        ],
    },
    {
        "id": "ufo-parsefilename-optional-opts",
        "project": "ufo",
        "fix_commit": "7959de5",
        "fix_subject": "fix(parseFilename): use optional chaining to access `opts.strict` (#284)",
        "kind": "historical-defect",
        "module": "src/parse.ts",
        "allowed_paths": ["src/parse.ts"],
        "prompt": (
            "In this project `parseFilename(input, opts)` extracts the last path segment of a URL. "
            "The second argument is OPTIONAL and is documented as optional in the README, but today "
            "calling `parseFilename('/path/to/filename.ext')` with no second argument throws "
            "`TypeError: Cannot destructure property 'strict' of 'undefined'`, because the parameter "
            "is destructured unconditionally. Fix parseFilename so omitting `opts` behaves exactly "
            "like passing a non-strict options object (the plain filename is returned, including a "
            "leading dot for hidden files), while an explicitly supplied `opts.strict` keeps its "
            "current meaning. Edit only src/parse.ts."),
        "criteria_source": ("upstream test/parse.test.ts at 7959de5 (the added one-argument case), plus "
                            "two further one-argument inputs exercising the same documented rule, "
                            "disclosed here rather than hidden"),
        "requirements": [
            _req("opts-is-optional", "must-change",
                 "parseFilename works when the options argument is omitted",
                 "src/parse.ts", "parseFilename",
                 [(["/path/to/filename.ext"], "filename.ext"),
                  (["/path/to/.hidden-file"], ".hidden-file"),
                  (["https://example.com/a/b.tar.gz"], "b.tar.gz")]),
            _req("preserve-explicit-opts", "must-preserve",
                 "An explicitly supplied options object keeps its current behaviour",
                 "src/parse.ts", "parseFilename",
                 [(["/path/to/dir/../filename.ext", True], "filename.ext"),
                  (["/path/to/filename.ext", {}], "filename.ext"),
                  (["/path/to/filename.ext", {"strict": False}], "filename.ext")]),
        ],
    },
    {
        "id": "entities-legacy-attribute-interrupted",
        "project": "entities",
        "fix_commit": "cec1fd8",
        "fix_subject": "fix(decode): fix legacy entities in attributes regression (#2213)",
        "kind": "historical-defect",
        "module": "src/decode.ts",
        "allowed_paths": ["src/decode.ts"],
        "approved_by": "upstream src/decode.spec.ts at cec1fd8 (issues #2208/#2213)",
        "prompt": (
            "In this project `decodeHTMLAttribute(text)` decodes HTML entities inside an ATTRIBUTE "
            "value, following the HTML standard. In attribute mode a legacy (semicolon-less) entity "
            "such as `&not` must NOT be decoded when the match is interrupted by descending into a "
            "longer entity name: in `&notin\\0;` and `&notin<` the decoder matches `&not` and then "
            "descends into `&notin`, and per the standard that descent invalidates the legacy match "
            "in attribute mode, so the text must be left exactly as it is. Today it is wrongly "
            "decoded to '¬in\\0;' and '¬in<'. Fix decodeHTMLAttribute so an interrupted legacy match "
            "is not committed in attribute mode, while every other decoding behaviour is unchanged "
            "— in particular `&not;` still decodes to '¬', `&notin;` to '∉', `&notP` and `&not3` "
            "stay literal, and `&not` in TEXT mode still decodes. Edit only src/decode.ts."),
        "criteria_source": ("upstream src/decode.spec.ts at cec1fd8 — the fix added 42 lines and "
                            "removed none, so every expected value below is an assertion the project "
                            "itself introduced, measured by executing the real code at both revisions"),
        "requirements": [
            _req("interrupted-legacy-match-not-committed", "must-change",
                 "A legacy entity match interrupted by descending into a longer entity is not decoded "
                 "in attribute mode",
                 "src/decode.ts", "decodeHTMLAttribute",
                 [(["&notin\x00;"], "&notin\x00;"),
                  (["&notin<"], "&notin<")]),
            _req("preserve-attribute-decoding", "must-preserve",
                 "Every other attribute-mode decoding behaviour is unchanged",
                 "src/decode.ts", "decodeHTMLAttribute",
                 [(["&notP"], "&notP"),
                  (["&not3"], "&not3"),
                  (["&not;"], "\u00ac"),
                  (["&notin;"], "\u2209"),
                  (["&amp;"], "&"),
                  (["&lt;"], "<"),
                  (["&amp"], "&"),
                  (["a &not b"], "a \u00ac b")]),
        ],
    },
]


# ------------------------------------------------------------------------------------------- #
# Corpus materialisation
# ------------------------------------------------------------------------------------------- #
def _sh(cmd: list[str], cwd: Path | None = None, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                          check=check, **kw)


def ensure_cache(verbose: bool = True) -> dict[str, Path]:
    """Clone each project once into the cache at full depth (pinned revisions are resolved from it)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name, spec in PROJECTS.items():
        dest = CACHE / name
        if not (dest / ".git").exists():
            if verbose:
                print(f"  cloning {name} …", flush=True)
            _sh(["git", "clone", "--quiet", spec["url"], str(dest)])
        out[name] = dest
    return out


def _prepare(repo: Path, project: str) -> None:
    """Make the project runnable with zero installs and preserve its REAL test suite.

    `node --test <the project's own test file>` is the ordinary-test command. The upstream `test`
    script also runs a linter (xo) and type tests (tsd), which are not behavioural tests and would
    require extra devDependencies; excluding them is recorded in the manifest.
    """
    spec = PROJECTS[project]
    pkg_path = repo / "package.json"
    pkg = json.loads(pkg_path.read_text())
    pkg.setdefault("scripts", {})["test"] = spec.get("test_command", "node --test test.js")
    pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    if spec["deps"]:                                   # e.g. humanize-string imports decamelize
        nm = repo / "node_modules"
        nm.mkdir(exist_ok=True)
        for dep in spec["deps"]:
            src = CACHE / dep
            if (src / "package.json").exists():
                target = nm / dep
                if not target.exists():
                    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".git", "node_modules"))
    if not (repo / "node_modules").exists():
        (repo / "node_modules").symlink_to(NODE_MODULES, target_is_directory=True)
    # node_modules must never enter the Git baseline: Sentinel snapshots tracked files and rejects an
    # unsupported node_modules entry. `.git/info/exclude` is used rather than editing the project's
    # own .gitignore, so no corpus file is modified — and a bare pattern is required because the
    # `node_modules/` form several upstream .gitignore files use does NOT match a symlink.
    exclude_node_modules(repo)


def materialize(task: dict, work: Path, *, at: str) -> Path:
    """Create a disposable repo for a task at `at` ('baseline' = fix_commit^, or 'fix')."""
    caches = ensure_cache(verbose=False)
    src = caches[task["project"]]
    dest = work / f"{task['id']}-{at}-{uuid.uuid4().hex[:6]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _sh(["git", "clone", "--quiet", "--no-hardlinks", str(src), str(dest)])
    rev = f"{task['fix_commit']}^" if at == "baseline" else task["fix_commit"]
    _sh(["git", "checkout", "--quiet", rev], cwd=dest)
    _sh(["git", "config", "user.email", "bench@shipguard.local"], cwd=dest)
    _sh(["git", "config", "user.name", "shipguard-bench"], cwd=dest)
    _prepare(dest, task["project"])
    # Commit the harness scaffolding so the agent's diff is only its own change.
    _sh(["git", "add", "-A"], cwd=dest)
    _sh(["git", "-c", "commit.gpgsign=false", "commit", "-qm", f"benchmark scaffold ({at})"], cwd=dest)
    return dest


def approved_by(task: dict) -> str:
    """Sentinel's contract schema caps `approvedBy` at 200 characters (measured: exit 2, zod too_big).

    The full provenance stays in the task record's `criteria_source` and in the manifest; the
    contract carries a short form so the oracle accepts it unchanged.
    """
    short = task.get("approved_by") or task["criteria_source"]
    if len(short) > 200:
        short = short[:197].rstrip() + "..."
    return short


def contract_for(task: dict) -> dict:
    return {"schemaVersion": 1,
            "objective": f"{task['project']}: {task['fix_subject']}"[:200],
            "approvedBy": approved_by(task),
            "allowedPaths": task_allowed(task),
            "requirements": task["requirements"]}


def validate_task(task: dict, work: Path, sentinel: list[str]) -> dict:
    """Pre-freeze gate. A task joins the corpus only if ALL of these hold:

      1. the real pre-fix baseline is CONTRADICTED by the independent oracle;
      2. the project's own ordinary tests PASS at that baseline (so the tests cannot see the defect);
      3. the real upstream fix is VERIFIED by the same oracle;
      4. the ordinary tests PASS at the upstream fix revision; and
      5. applying ONLY the upstream source change to the baseline (leaving the baseline's own test
         files untouched) still passes the ordinary tests — the aspirin property, measured rather
         than assumed: green tests, real defect, and a correct repair does not turn them red.
    """
    out: dict[str, Any] = {"task": task["id"]}
    contract = work / f"{task['id']}-contract.json"
    contract.write_text(json.dumps(contract_for(task), ensure_ascii=False))
    for at, expect_ok in (("baseline", False), ("fix", True)):
        repo = materialize(task, work, at=at)
        v = run_sentinel_challenge(sentinel, repo, contract, work / f"store-{task['id']}-{at}",
                                   runner="local", attempt_id=f"{at}-{uuid.uuid4().hex[:6]}")
        out[at] = {"verdict": v["verdict"], "ok": v["ok"], "receipt": v["receipt_hash"],
                   "requirements": v["requirements"], "reasons": v["reasons"][:5],
                   "counterexample": v["counterexample"], "integrity": v.get("integrity")}
        tests = run_ordinary_tests(repo)
        out[f"{at}_ordinary_tests"] = tests
        shutil.rmtree(repo, ignore_errors=True)

    # (5) baseline tests + upstream source fix, with the baseline's own test files untouched.
    repo = materialize(task, work, at="baseline")
    _sh(["git", "checkout", task["fix_commit"], "--", *task_allowed(task)], cwd=repo, check=False)
    _sh(["git", "reset", "--quiet"], cwd=repo, check=False)   # unstage so git_diff sees the change
    applied, _ = git_diff(repo)
    out["fix_src_only"] = {"changed": applied, "ordinary_tests": run_ordinary_tests(repo) if applied else {}}
    shutil.rmtree(repo, ignore_errors=True)

    out["valid"] = (out["baseline"]["ok"] is False
                    and out["fix"]["ok"] is True
                    and out["baseline_ordinary_tests"]["passed"] is True
                    and out["fix_ordinary_tests"]["passed"] is True
                    and bool(out["fix_src_only"]["changed"])
                    and out["fix_src_only"]["ordinary_tests"].get("passed") is True)
    return out


# ------------------------------------------------------------------------------------------- #
# Arms
# ------------------------------------------------------------------------------------------- #
ARMS = {
    "A": "ordinary Codex + the project's own tests only (no independent verification)",
    "B": "same Codex configuration + independent Sentinel verification, no automatic repair",
    "C": "same Codex configuration + ShipGuard bounded counterexample-driven repair",
}
ARM_PAIRING = (
    "Arms A and B are evaluated on ONE shared agent session per task, recorded as arm 'AB'. Arm B "
    "adds only a verification GATE and gives the agent no feedback, so by construction the agent's "
    "behaviour in A and B is identical; running two sessions would double the cost and add "
    "independent sampling noise to a comparison that is meant to be paired. Each AB record "
    "therefore carries both decision rules — arm_A_decision (accept iff the project's own tests "
    "pass) and arm_B_decision (accept iff the independent oracle verifies) — applied to the same "
    "measured output, plus ground_truth_correct from the oracle. Arm C is a separate session "
    "because it feeds counterexamples back to the agent."
)


def _common(task: dict, work: Path) -> tuple[Path, Path]:
    contract = work / f"{task['id']}-contract.json"
    if not contract.exists():
        contract.write_text(json.dumps(contract_for(task), ensure_ascii=False))
    return contract, work / f"store-{task['id']}"


def run_arm_no_repair(task: dict, work: Path, arm: str, sentinel, agent_timeout: int) -> dict:
    """Arms A and B: one fresh agent session, no verification feedback, no repair."""
    contract, store = _common(task, work)
    repo = materialize(task, work, at="baseline")
    before = repo_fingerprint(repo)
    adapter = CodexAdapter()
    t0 = time.time()
    res = adapter.propose(task=task["prompt"], repo=repo, attempt=0, feedback=None,
                          timeout=agent_timeout, target_file=task_module(task),
                          export=task_export(task))
    agent_s = round(time.time() - t0, 2)
    tests = run_ordinary_tests(repo)
    changed, diff = git_diff(repo)
    challenge = run_sentinel_challenge(sentinel, repo, contract, store, runner="local",
                                       attempt_id=f"{arm}-{uuid.uuid4().hex[:6]}")
    head = _sh(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    out = {
        "arm": arm, "task": task["id"], "project": task["project"],
        "agent": {"outcome": res.outcome, "duration_s": res.duration_s, "changed_files": res.changed_files,
                  "statement": (res.statement or "")[:600], "error": res.error,
                  "tokens": (res.raw or {}).get("tokens"), "mode": res.mode},
        "wallclock_s": agent_s,
        "ordinary_tests": tests,
        "independent_verification": {k: challenge.get(k) for k in
                                     ("ok", "verdict", "receipt_hash", "requirements",
                                      "counterexample", "reasons", "attempt_id")},
        # What a developer using ONLY the project's tests would conclude (arm A's decision rule).
        "arm_A_decision": "accept" if tests.get("passed") else "reject",
        # Arm B's decision rule: accept only on independent verification.
        "arm_B_decision": "accept" if challenge.get("ok") else "reject",
        "ground_truth_correct": bool(challenge.get("ok")),
        "baseline_head": before["head"], "candidate_head": head,
        "diff_lines": len(diff.splitlines()),
    }
    shutil.rmtree(repo, ignore_errors=True)
    return out


def run_arm_repair(task: dict, work: Path, sentinel, agent_timeout: int, max_attempts: int = 1) -> dict:
    """Arm C: ShipGuard's bounded counterexample-driven repair loop on a REAL project baseline."""
    contract, store = _common(task, work)
    out_dir = work / f"arm-C-{task['id']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return _repair_loop(task, work, contract, store, sentinel, agent_timeout, max_attempts, out_dir)


def _repair_loop(task, work, contract, store, sentinel, agent_timeout, max_attempts, out_dir) -> dict:
    """verify -> authentic counterexample -> fresh repair attempt -> independent re-verification.

    Uses the project's genuine pre-fix state as the baseline, so any contradiction is a real
    agent-produced defect against the project's own approved criteria.
    """
    repo = materialize(task, work, at="baseline")
    adapter = CodexAdapter()
    allowed = task_allowed(task)
    export = task_export(task)
    attempts: list[dict] = []
    cx = None
    final: dict[str, Any] = {"status": "unverified"}
    agent_seconds = 0.0
    verify_seconds = 0.0
    for attempt in range(max_attempts + 1):
        t0 = time.time()
        res = adapter.propose(task=task["prompt"], repo=repo, attempt=attempt,
                              feedback=(_feedback(cx) if cx else None), timeout=agent_timeout,
                              target_file=task_module(task), export=export)
        agent_seconds += round(time.time() - t0, 2)
        rec: dict[str, Any] = {"attempt": attempt, "agent": {
            "outcome": res.outcome, "duration_s": res.duration_s, "changed_files": res.changed_files,
            "statement": (res.statement or "")[:600], "error": res.error,
            "tokens": (res.raw or {}).get("tokens")}}

        if res.outcome in ("unavailable", "interrupted") or not res.made_change:
            rec["status"] = res.outcome if res.outcome != "failed" else "no_change"
            attempts.append(rec)
            final = {"status": {"unavailable": "environment_failure",
                                "interrupted": "interrupted"}.get(res.outcome, "no_change")}
            break

        scope = validate_change_scope(repo, allowed)
        rec["scope"] = scope
        if not scope["clean"]:
            attempts.append(rec)
            final = {"status": "review_required", "reason": f"out-of-scope change: {scope}"}
            break

        tests = run_ordinary_tests(repo)
        rec["ordinary_tests"] = tests
        attempt_id = f"C-{attempt}-{uuid.uuid4().hex[:6]}"
        t1 = time.time()
        challenge = run_sentinel_challenge(sentinel, repo, contract, store, runner="local",
                                          attempt_id=attempt_id)
        verify_seconds += round(time.time() - t1, 2)
        rec["verification"] = {k: challenge.get(k) for k in
                               ("ok", "verdict", "receipt_hash", "requirements", "counterexample",
                                "reasons", "attempt_id", "integrity")}
        if attempt == 0 and is_detected_defect(tests.get("passed"), challenge):
            final["aspirin"] = True

        if challenge.get("ok"):
            head = _commit_candidate(repo, f"verified change (attempt {attempt})", allowed)
            binding = bind_committed_tree(store=store / f"attempt-{attempt_id}",
                                          receipt_hash=challenge.get("receipt_hash"),
                                          repo=repo, commit=head)
            rec["committed_head"] = head
            rec["tree_binding"] = binding
            attempts.append(rec)
            final = {"status": "verified" if binding.get("equivalent") else "review_required",
                     "repair_attempts_used": attempt,
                     "tree_binding_equivalent": binding.get("equivalent")}
            break

        cx = challenge.get("counterexample")
        rec["status"] = challenge.get("verdict")
        attempts.append(rec)
        if challenge.get("verdict") == "ENVIRONMENT_FAILURE":
            final = {"status": "environment_failure", "reasons": challenge.get("reasons")}
            break
        if challenge.get("verdict") != "CONTRADICTED":
            final = {"status": "review_required" if challenge.get("verdict") == "REVIEW REQUIRED"
                     else "unverified", "verdict": challenge.get("verdict"),
                     "reasons": challenge.get("reasons")}
            break
    else:
        final = {"status": "contradicted", "repair_attempts_used": max_attempts,
                 "note": "bounded attempts exhausted; defect NOT repaired"}

    last = next((a["verification"] for a in reversed(attempts) if "verification" in a), {})
    head = _sh(["git", "rev-parse", "HEAD"], cwd=repo, check=False).stdout.strip()
    out = {"arm": "C", "task": task["id"], "project": task["project"], "attempts": attempts,
           "final": final, "agent_seconds": round(agent_seconds, 2),
           "verification_seconds": round(verify_seconds, 2),
           "independent_verification": {k: last.get(k) for k in
                                        ("ok", "verdict", "receipt_hash", "requirements",
                                         "counterexample")},
           "ground_truth_correct": final.get("status") == "verified",
           "candidate_head": head}
    (out_dir / "arm-C-record.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    shutil.rmtree(repo, ignore_errors=True)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _vitest_version() -> str:
    try:
        return json.loads((NODE_MODULES / "vitest" / "package.json").read_text()).get("version", "unknown")
    except Exception:
        return "unknown"


def freeze(verbose: bool = True) -> dict:
    """Validate every contract, then write the FROZEN manifest before any experimental agent run."""
    work = Path("/tmp/sg-bench-validate")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    sentinel = find_sentinel()
    if sentinel is None:
        raise SystemExit("sentinel CLI not found (set SHIPGUARD_SENTINEL)")
    validations = []
    for task in TASKS:
        if verbose:
            print(f"  validating {task['id']} …", flush=True)
        v = validate_task(task, work, sentinel)
        validations.append(v)
        if verbose:
            print(f"    baseline={v['baseline']['verdict']} (ordinary tests "
                  f"{'PASS' if v['baseline_ordinary_tests']['passed'] else 'FAIL'})  "
                  f"fix={v['fix']['verdict']} (ordinary tests "
                  f"{'PASS' if v['fix_ordinary_tests']['passed'] else 'FAIL'})  "
                  f"fix-src-only tests "
                  f"{'PASS' if v['fix_src_only']['ordinary_tests'].get('passed') else 'FAIL'}  "
                  f"valid={v['valid']}", flush=True)
    if not all(v["valid"] for v in validations):
        bad = [v["task"] for v in validations if not v["valid"]]
        raise SystemExit(f"refusing to freeze: {len(bad)} task(s) failed the pre-freeze gate: {bad}")
    manifest = {
        "schema": "shipguard/benchmark-manifest/v1",
        "frozen_at": _now(),
        "purpose": "Establish whether ShipGuard catches and repairs real coding-agent defects "
                   "across independent real-world tasks.",
        "selection_process": {
            "method": ("Cloned real permissively-licensed npm packages; surveyed their Git history for "
                       "genuine bug-fix commits; took each commit's PARENT as the benchmark baseline "
                       "so the defect is the project's own historical defect. Acceptance criteria are "
                       "assertions from the project's own test suite at the fix commit, measured "
                       "directly by executing the real code at both revisions rather than transcribed "
                       "by hand. No requirement was invented to make an agent fail and no essential "
                       "specification detail was withheld from the prompt."),
            "projects_considered": ["camelcase", "decamelize", "humanize-string", "leven",
                                    "pretty-bytes", "parse-ms", "titleize", "escape-string-regexp",
                                    "indent-string", "strip-ansi", "plur", "to-milliseconds",
                                    "is-fullwidth-code-point", "ms", "bytes", "pathe", "destr",
                                    "defu", "remeda", "es-toolkit", "radix3", "mlly", "ohash",
                                    "hookable", "exsolve", "confbox", "untyped", "jsonrepair",
                                    "marked", "smol-toml", "entities", "scule", "ufo"],
            "excluded": {
                "camelcase": "vetted and suitable but excluded for scope: ~150 lines of subtle "
                             "Unicode regex logic, too large to prepare and validate reliably here",
                "pretty-bytes/parse-ms/titleize/escape-string-regexp/indent-string/strip-ansi/plur/"
                "to-milliseconds/is-fullwidth-code-point": "test scripts require ava (extra "
                                                           "devDependencies) — excluded to keep the "
                                                           "ordinary-test signal dependency-free",
                "ms": "TypeScript + jest with 11 devDependencies — excluded for install weight",
                "pathe": ("MIT, pure path functions and good fix history, but EXCLUDED after direct "
                          "measurement: at every revision that carries a usable fix (7534c0c, "
                          "e78663c, 1492827) src/_path.ts imports `zeptomatch`, which the project "
                          "declares only as a devDependency, so the whole suite fails to collect "
                          "(`Cannot find package 'zeptomatch'`) under the pinned zero-install "
                          "node_modules. Only HEAD is green, because the glob import was later moved "
                          "into src/_glob.ts — and HEAD has no unfixed defect to benchmark. An "
                          "earlier attempt also hit a different failure: at the older revisions the "
                          "source layout differs from HEAD, so the probed module did not exist in "
                          "Sentinel's baseline snapshot (ENVIRONMENT FAILURE / "
                          "ERR_MODULE_NOT_FOUND). Excluded rather than patched, to keep each task's "
                          "module path and dependency set faithful to its revision"),
                "destr": ("MIT, zero deps, and `destr(str)` is an ideal pure probe target with three "
                          "real defect fixes (639a5df surrounding whitespace, f9c78d4 escape-char "
                          "fast path, d9ba16d decimals/scientific notation). EXCLUDED after direct "
                          "measurement: at all three revisions and their parents the suite fails to "
                          "collect under the pinned vitest 5.0.5 (destr was on vitest ^0.34 then), "
                          "while at HEAD — where the suite is green — the history contains no "
                          "behavioural fix, only dependency churn"),
                "bytes": "clone/package metadata did not expose a usable test script",
                "defu": ("MIT + vitest and a genuine prototype-pollution fix (3942bfb) were found, but "
                         "the task was DROPPED at the pre-freeze gate because the defect cannot be "
                         "expressed in Sentinel's contract format. Measured directly: Sentinel parses "
                         "the approved contract with a schema validator that reconstructs each object, "
                         "so an own `__proto__` data property in a case argument is normalised away — "
                         "the contract written to disk contains "
                         "`{\"__proto__\":{\"isAdmin\":true}}` while the receipt's stored contract "
                         "object contains `{}`. The malicious input therefore never reaches defu, the "
                         "check passed for the wrong reason, and ShipGuard's own integrity layer "
                         "correctly refused the receipt ('receipt contract does not deep-equal the "
                         "approved contract'). defu's other real hardening fix (11ba022) needs "
                         "`Object.prototype` mutation, which a pure JSON-argument probe also cannot "
                         "express. Excluded rather than re-expressed as an artificial requirement"),
                "jsonrepair": ("ISC licence, zero runtime deps, pure `jsonrepair(str) -> str`, and two "
                               "ideal add-only defect fixes were found and measured (ca329f7 zero-width "
                               "spaces, 8d1754c trailing-comma strips the parent's comma). EXCLUDED "
                               "after direct measurement: Sentinel does NOT run the project's test "
                               "script — src/verifier.ts writes its own vitest config "
                               "(include `**/*.{test,spec}.{js,ts,...}`) and runs vitest itself, so "
                               "jsonrepair's test-lib/cli.test.js is always collected. That file "
                               "spawns the built CLI from lib/, which does not exist without a build "
                               "step, so Sentinel's mandatory baseline-tests/candidate-tests/"
                               "preserved-tests checks were CONTRADICTED at BOTH the baseline and the "
                               "upstream fix. Narrowing the package.json test script cannot help, "
                               "because Sentinel ignores it. Deleting or editing that test file to "
                               "make the oracle pass is exactly what the mandate forbids, so the "
                               "project was dropped"),
                "ohash": ("MIT + vitest and a clean pure `diff(a, b)` defect (a5004f7, falsy "
                          "primitives) were found and the criteria were measured, but the task was "
                          "DROPPED at the pre-freeze gate for the same structural reason as "
                          "jsonrepair: Sentinel runs its own vitest over every `*.test.*` file, and "
                          "ohash's test/serialize.test.ts, test/hash.test.ts and test/bundle.test.ts "
                          "import through src/index.ts, which self-references the `ohash/crypto` "
                          "subpath export that only resolves against built output. Those three files "
                          "fail to collect with zero installs, so Sentinel's mandatory ordinary-test "
                          "checks were CONTRADICTED at both the baseline and the fix"),
                "hookable": "MIT + vitest and green with zero installs, but the API is "
                            "`createHooks()` returning a stateful registry, not a single pure "
                            "exported function that a JSON-argument probe can call",
                "exsolve": "MIT + vitest and green with zero installs, but the exported resolvers "
                           "return absolute filesystem paths, so the oracle's expected values would "
                           "be machine-specific rather than portable",
                "confbox": "MIT + vitest, but 1 test file fails to collect under the pinned vitest "
                           "with zero installs",
                "untyped": "MIT + vitest, but all 6 test files fail to collect under the pinned "
                           "vitest with zero installs",
                "remeda": "MIT + vitest, but package.json declares no license/test fields at the "
                          "surveyed revision and the repo is large; excluded for vetting cost",
                "es-toolkit": "MIT + vitest with many suitable single-function fixes, but `vitest run` "
                              "executes the whole multi-thousand-test suite (including coverage) per "
                              "attempt; excluded to keep the ordinary-test signal fast enough to run "
                              "once per arm per task",
                "radix3": "MIT + vitest, but the pinned vitest run reported 7 collection errors "
                          "without the project's own devDependencies, and the router API needs a "
                          "constructed router rather than a single pure exported function",
                "mlly": "MIT, but the pinned vitest collected no tests without the project's own "
                        "vitest configuration/devDependencies",
                "marked": "MIT and zero runtime deps, but the project does not use vitest (all 6 "
                          "test files fail to collect under the pinned vitest)",
                "smol-toml": "BSD-3-Clause and zero runtime deps, but all 11 test files fail to "
                             "collect under the pinned vitest with zero installs",
            },
            "entities_tasks_dropped": {
                "914e397 fix(escape): escape `<` and `>` in attribute values (#2398)": (
                    "A genuinely security-relevant defect — `escapeAttribute` left `<`/`>` unescaped, "
                    "so '<img src=x onerror=alert(1)>' survived escaping — and the criteria were "
                    "measured. DROPPED because the upstream fix also CHANGED an existing assertion "
                    "(escape.spec.ts expected '<a &quot; attr > ...' and now expects "
                    "'&lt;a &quot; attr &gt; ...'). Gate condition 5 measured the consequence: "
                    "applying only the source fix to the frozen baseline makes the baseline's own "
                    "suite fail, so arm A would reject a correct repair"),
                "05af0b3 fix(decode): skip Windows-1252 C1 remap for XML numeric references (#2347)":
                    "DROPPED for the same measured reason: src/index.spec.ts changed an existing "
                    "astralSpecial expectation from '\\u{20AC}' to '\\u{80}'",
                "00913aa / d97b64f (streaming decode fixes)":
                    "Purely additive tests and green suites, but the behaviour lives behind the "
                    "stateful `EntityDecoder` class (startEntity/write/end), which a single-call "
                    "JSON-argument probe cannot exercise",
            },
            "tasks_dropped_by_the_gate": {
                "scule-segment-lowering (3815767)": (
                    "DROPPED by pre-freeze gate condition 5, measured: applying only the upstream "
                    "source fix to the frozen baseline makes the baseline's OWN suite fail — "
                    "test/scule.test.ts asserted `pascalCase('FooBARb') === 'FooBARb'` and the fix "
                    "changes that expectation to 'FooBaRb'. A correct repair would therefore turn "
                    "arm A's ordinary tests red, and the mandate forbids counting an initially "
                    "correct solution as a failure. This is a documented behaviour change, not a "
                    "defect invisible to the project's tests"),
                "ufo-trailing-slash-in-query (6cd1fcd) and ufo-parseurl-protocol-case (768210a)": (
                    "Criteria were measured and both are real defects with clean discriminators, but "
                    "at those 2023/2024 revisions ufo's suite does not run under the pinned vitest "
                    "5.0.5, so Sentinel's mandatory ordinary-test checks reported ENVIRONMENT "
                    "FAILURE at both baseline and fix. ufo revisions from 2025 onward (13 test "
                    "files) are green, so the ufo tasks were re-selected from that window"),
            },
            "measured_corpus_constraints": [
                "Sentinel executes the ordinary tests itself, with its OWN vitest configuration "
                "(src/verifier.ts writes include `**/*.{test,spec}.{js,ts,mjs,cjs,mts,cts,jsx,tsx}`, "
                "environment node, testTimeout 5000, maxWorkers 1) using the pinned installation's "
                "vitest 5.0.5, and it ignores the project's `test` script and vitest config. So every "
                "file matching that glob must pass at the baseline revision with zero installs; a "
                "project needing a build step or an undeclared runtime dependency cannot be "
                "benchmarked at all. This biases the corpus toward recent revisions and is the single "
                "largest reason candidates were dropped (jsonrepair, ohash, pathe, destr).",
                "Sentinel probes call ONE exported function with JSON arguments and compare a "
                "JSON-serialisable return, so criteria must be expressible that way. Own `__proto__` "
                "keys are normalised away by contract parsing, and `undefined`/`Infinity` returns are "
                "not representable, so such cases were excluded from the criteria. `approvedBy` is "
                "capped at 200 characters by Sentinel's schema (measured: exit 2 with a zod "
                "`too_big` error), so the contract carries a short provenance string and the full "
                "provenance stays in this manifest.",
                "STRUCTURAL FINDING: Sentinel always records a mandatory `preserved-tests` check, "
                "which restores the BASELINE's test and control files into a third copy and runs them "
                "against the candidate source. A change that alters any behaviour asserted by an "
                "existing test therefore can never be VERIFIED, however correct it is. ShipGuard's "
                "gate condition 5 measures the same property independently. The corpus is "
                "consequently restricted to fixes whose upstream commit ADDS assertions without "
                "changing existing ones — which is also exactly the condition that makes arm A's "
                "'ordinary tests only' decision rule fair. Behaviour-change tasks (entities 914e397 "
                "and 05af0b3, scule 3815767) are outside what this verifier can accept, and are "
                "recorded as dropped rather than forced through.",
            ],
            "ordinary_test_command": ("Each project's own real vitest suite, unmodified, run as "
                                      "`vitest run` for all three projects. Upstream `test` scripts "
                                      "also run `pnpm lint` / typecheck / coverage, which are not "
                                      "behavioural tests and need extra devDependencies; excluding "
                                      "those steps is recorded here. No test file was edited, "
                                      "deleted or weakened. Note that this command is what ARMS A "
                                      "and the harness report; Sentinel's own oracle runs its own "
                                      "vitest configuration independently (see "
                                      "measured_corpus_constraints). vitest itself is supplied by "
                                      "the pinned Sentinel installation's node_modules, so no "
                                      "benchmark-time install occurs."),
            "sentinel_capability_constraint": ("An earlier candidate set (decamelize, "
                                               "humanize-string, leven) was DROPPED because their "
                                               "tests use node:test/ava: Sentinel reported 'No tests "
                                               "executed; an empty suite is not verification' "
                                               "(UNVERIFIED) even though the requirement checks "
                                               "passed. Recorded so the selection is not mistaken "
                                               "for cherry-picking; see measured_corpus_constraints "
                                               "for the full set of constraints actually measured."),
            "disclosed_extra_cases": ("Some requirement cases are NOT verbatim upstream assertions "
                                      "but additional inputs exercising the same documented rule, so "
                                      "that a task whose upstream fix added only one or two "
                                      "discriminating assertions cannot be satisfied by "
                                      "special-casing those inputs. They are named in the affected "
                                      "task's criteria_source: ufo-parsefilename-optional-opts adds "
                                      "two further one-argument inputs ('/path/to/.hidden-file', "
                                      "'https://example.com/a/b.tar.gz') plus explicit-opts "
                                      "preserves. Every expected value was measured by executing the "
                                      "real code at the fix revision, never transcribed by hand. "
                                      "Nothing essential is withheld from any prompt and no extra "
                                      "requirement is imposed."),
            "no_selective_omission": "Every task in this manifest is run in every arm; results are "
                                     "reported for all of them, including first-try successes. "
                                     "Candidates and tasks that FAILED vetting or the pre-freeze "
                                     "gate (defu, ohash, jsonrepair, pathe, destr, marked, "
                                     "smol-toml, scule-segment-lowering, the two older ufo "
                                     "revisions, and two entities fixes) are recorded above with the "
                                     "measured reason rather than silently dropped, and `freeze` "
                                     "refuses to write a manifest while any task is invalid.",
            "corpus_size_honesty": ("The mandate asked for roughly 12-20 tasks across at least three "
                                    "projects. This corpus is 6 tasks across 3 projects (scule 2, "
                                    "ufo 3, entities 1). It is smaller than requested because the "
                                    "measured constraints above are restrictive and no task was "
                                    "admitted that failed the pre-freeze gate; the excluded "
                                    "candidates are listed with reasons so the shortfall cannot be "
                                    "confused with cherry-picking. The corpus was NOT expanded after "
                                    "seeing any agent result."),
        },
        "verifier": {"name": "sentinel-verified",
                     "pinned_commit": "becba502c8dbebdd5e52b8ca09122f86e4e37bb3",
                     "runner": "local (advisory, same OS account — not a security boundary)"},
        "harness": {
            "path": "benchmark/harness.py",
            "sha256": hashlib.sha256((REPO_ROOT / "benchmark" / "harness.py").read_bytes()).hexdigest(),
            "git_head": _sh(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=False).stdout.strip(),
            "git_dirty": bool(_sh(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                                 check=False).stdout.strip()),
            "node_modules_source": ("SHIPGUARD_NODE_MODULES" if os.environ.get("SHIPGUARD_NODE_MODULES")
                                    else "sibling pinned sentinel-verified checkout"),
            "vitest_version": _vitest_version(),
            "python": sys.version.split()[0],
        },
        "agent": {"name": "codex", "sandbox": "workspace-write",
                  "auth": "ChatGPT (verified via `codex login status`)",
                  "note": "no --dangerously-skip-permissions; no bypass flag"},
        "arms": ARMS,
        "arm_pairing": ARM_PAIRING,
        "projects": PROJECTS,
        "tasks": [{k: v for k, v in t.items()} for t in TASKS],
        "contracts": {t["id"]: contract_for(t) for t in TASKS},
        "pre_freeze_validation": validations,
    }
    blob = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
    manifest["manifest_sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    if verbose:
        print(f"\nfroze {MANIFEST.name}: {len(TASKS)} tasks across {len(PROJECTS)} projects; "
              f"all contracts valid: {all(v['valid'] for v in validations)}")
        print(f"manifest_sha256: {manifest['manifest_sha256']}")
    return manifest


def _portable_results(payload: Any) -> Any:
    """Scrub machine-local absolute paths so the published artifact is portable (mandate P1.6)."""
    if isinstance(payload, dict):
        return {k: _portable_results(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_portable_results(v) for v in payload]
    if isinstance(payload, str):
        return _portable(payload)
    return payload


def summarize(results: list[dict]) -> dict:
    """Aggregate the paired arms into the metrics the report must state, without reinterpreting."""
    ab = [r for r in results if r.get("arm") == "AB"]
    c = [r for r in results if r.get("arm") == "C"]

    def _rate(rows: list[dict], key: str, value: str) -> dict:
        n = len(rows)
        hit = sum(1 for r in rows if r.get(key) == value)
        return {"n": n, "count": hit, "rate": round(hit / n, 4) if n else None}

    # A defect the ordinary tests could not see, found by the independent oracle.
    aspirin_ab = [r for r in ab if (r.get("ordinary_tests") or {}).get("passed") is True
                  and r.get("ground_truth_correct") is False]
    aspirin_c0 = [r for r in c for a in r.get("attempts", [])[:1]
                  if (a.get("ordinary_tests") or {}).get("passed") is True
                  and (a.get("verification") or {}).get("ok") is False]
    false_accept_a = [r for r in ab if r.get("arm_A_decision") == "accept"
                      and r.get("ground_truth_correct") is False]
    false_accept_b = [r for r in ab if r.get("arm_B_decision") == "accept"
                      and r.get("ground_truth_correct") is False]
    repaired = [r for r in c if (r.get("final") or {}).get("status") == "verified"
                and (r.get("final") or {}).get("repair_attempts_used", 0) >= 1]
    return {
        "tasks_in_corpus": len(TASKS),
        "projects": sorted({t["project"] for t in TASKS}),
        "arm_AB": {
            "sessions": len(ab),
            "agent_made_a_change": sum(1 for r in ab
                                       if (r.get("agent") or {}).get("outcome") == "completed"),
            "ordinarily_green": sum(1 for r in ab
                                    if (r.get("ordinary_tests") or {}).get("passed") is True),
            "independently_correct": sum(1 for r in ab if r.get("ground_truth_correct") is True),
            "arm_A_accepted": _rate(ab, "arm_A_decision", "accept"),
            "arm_B_accepted": _rate(ab, "arm_B_decision", "accept"),
            "arm_A_false_accepts": len(false_accept_a),
            "arm_B_false_accepts": len(false_accept_b),
            "defects_invisible_to_ordinary_tests": len(aspirin_ab),
            "false_accept_task_ids": sorted({r["task"] for r in false_accept_a}),
        },
        "arm_C": {
            "sessions": len(c),
            "verified": sum(1 for r in c if (r.get("final") or {}).get("status") == "verified"),
            "verified_after_repair": len(repaired),
            "repaired_task_ids": sorted({r["task"] for r in repaired}),
            "contradicted_after_budget": sum(1 for r in c
                                             if (r.get("final") or {}).get("status") == "contradicted"),
            "aspirin_on_first_attempt": len(aspirin_c0),
            "tree_binding_equivalent": sum(1 for r in c
                                           if (r.get("final") or {}).get("tree_binding_equivalent")),
            "statuses": sorted({(r.get("final") or {}).get("status") for r in c}),
            "agent_seconds_total": round(sum(r.get("agent_seconds", 0) for r in c), 2),
            "verification_seconds_total": round(sum(r.get("verification_seconds", 0) for r in c), 2),
        },
    }


def run(agent_timeout: int = 420, only: list[str] | None = None,
        arms: tuple[str, ...] = ("AB", "C")) -> dict:
    """Execute the frozen corpus. Writes RESULTS incrementally so a crash loses nothing."""
    if not MANIFEST.exists():
        raise SystemExit("manifest not frozen — run `freeze` first")
    manifest = json.loads(MANIFEST.read_text())
    work = Path("/tmp/sg-bench-run")
    work.mkdir(parents=True, exist_ok=True)
    sentinel = find_sentinel()
    if sentinel is None:
        raise SystemExit("sentinel CLI not found (set SHIPGUARD_SENTINEL)")
    tasks = [t for t in TASKS if not only or t["id"] in only]

    results: list[dict] = []
    started = _now()
    if RESULTS.exists():                              # resume: never silently re-run a completed cell
        prior = json.loads(RESULTS.read_text()).get("results", [])
        done = {(r["task"], r["arm"]) for r in prior}
        results.extend(prior)
        started = json.loads(RESULTS.read_text()).get("started_at", started)
    else:
        done = set()

    def _flush() -> None:
        RESULTS.write_text(json.dumps(_portable_results({
            "schema": "shipguard/benchmark-results/v1",
            "started_at": started, "finished_at": _now(),
            "manifest_sha256": manifest.get("manifest_sha256"),
            "arms": ARMS, "arm_pairing": ARM_PAIRING,
            "agent": manifest.get("agent"), "verifier": manifest.get("verifier"),
            "summary": summarize(results), "results": results}),
            indent=2, ensure_ascii=False) + "\n")

    for task in tasks:
        for arm in arms:
            if (task["id"], arm) in done:
                print(f"[{arm}] {task['id']} — already recorded, skipping", flush=True)
                continue
            print(f"[{arm}] {task['id']} …", flush=True)
            if arm == "AB":
                r = run_arm_no_repair(task, work, "AB", sentinel, agent_timeout)
            elif arm == "C":
                r = run_arm_repair(task, work, sentinel, agent_timeout)
            else:
                raise SystemExit(f"unknown arm {arm!r} (use AB and/or C)")
            r["recorded_at"] = _now()
            results.append(r)
            fin = r.get("final") or {}
            print(f"    -> agent={(r.get('agent') or {}).get('outcome')} "
                  f"tests={(r.get('ordinary_tests') or {}).get('passed')} "
                  f"sentinel={(r.get('independent_verification') or {}).get('verdict')} "
                  f"status={fin.get('status')} A={r.get('arm_A_decision')} "
                  f"B={r.get('arm_B_decision')} correct={r.get('ground_truth_correct')}", flush=True)
            _flush()
    _flush()
    return {"results": results, "summary": summarize(results)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    rest = [a for a in sys.argv[2:] if not a.startswith("-")]
    if cmd == "validate":
        w = Path("/tmp/sg-bench-validate")
        shutil.rmtree(w, ignore_errors=True)
        w.mkdir(parents=True)
        s = find_sentinel()
        for t in TASKS:
            v = validate_task(t, w, s)
            print(f"{t['id']:38s} baseline={v['baseline']['verdict']:18s} "
                  f"fix={v['fix']['verdict']:10s} tests@baseline="
                  f"{v['baseline_ordinary_tests']['passed']} tests@fix="
                  f"{v['fix_ordinary_tests']['passed']} tests@fix-src-only="
                  f"{v['fix_src_only']['ordinary_tests'].get('passed')} valid={v['valid']}", flush=True)
    elif cmd == "freeze":
        freeze()
    elif cmd == "run":
        arms = tuple(a.upper() for a in rest if a.upper() in ("AB", "C")) or ("AB", "C")
        out = run(only=[a for a in rest if a.upper() not in ("AB", "C")] or None, arms=arms)
        print(json.dumps(out["summary"], indent=2))
    elif cmd == "summarize":
        print(json.dumps(summarize(json.loads(RESULTS.read_text())["results"]), indent=2))
    else:
        raise SystemExit(f"unknown command {cmd!r}")
