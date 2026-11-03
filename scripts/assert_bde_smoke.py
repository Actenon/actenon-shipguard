"""Require real BDE execution and account for every law in the CLI smoke fixture."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def check(directory: Path) -> None:
    evidence = json.loads((directory / "bde-evidence.json").read_text())
    laws = json.loads((directory / "bde-laws.json").read_text())["laws"]
    summary = evidence["summary"]
    assert summary["overall_status"] == "CONFIRMED_CONTRADICTION", summary
    assert summary["laws_executed"] > 0 and summary["laws_errored"] == 0, summary
    outcomes = evidence["law_outcomes"]
    by_id = {o["law_id"]: o for o in outcomes}
    assert len(by_id) == len(outcomes) == len(laws), outcomes
    assert set(by_id) == {law["law_id"] for law in laws}
    for law in laws:
        outcome = by_id[law["law_id"]]
        if outcome["status"] == "SKIP":
            # Determinism is inapplicable when the example throws. This is an
            # explicitly reported optional hypothesis, never a mandatory check.
            assert law["evidence_class"] == "D_INFERRED" and law["approval"] == "unapproved", law
            assert outcome["detail"], outcome
        else:
            assert outcome["status"] in ("PASS", "FAIL") and outcome["trials"] > 0, outcome
    assert any(f["kind"] == "documented_call_threw" for f in evidence["findings"])


if __name__ == "__main__":
    check(Path(sys.argv[1]))
