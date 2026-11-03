"""Check compatibility with the actual minimum interpreter, including PEP 701.

FormattedValue locations differ across Python versions and do not reliably describe
replacement fields. Nor does feature_version emulate every older tokenizer rule.
Compile (without importing or executing) all project sources using Python 3.11.
CI provisions that interpreter in every matrix job; absence is a failure, not a skip.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("src", "tests", "benchmark", "benchmarks", "scripts")

# Preserve the exact regression that originally motivated this guard.
BROKEN_EXAMPLE = '''a(f"- x **{d.get('n')}** only. "
  f"{('some long text '
     'continued here') if d.get('n') == 'claude' else 'other'} "
  "tail")
'''

COMPILER = '''
import json, sys
assert sys.version_info[:2] == (3, 11), sys.version
errors = {}
for filename, source in json.load(sys.stdin).items():
    try:
        compile(source, filename, 'exec')
    except SyntaxError as e:
        errors[filename] = {'line': e.lineno, 'message': e.msg}
print(json.dumps(errors))
'''


def _compile311(sources: dict[str, str]) -> dict:
    python = os.environ.get("SHIPGUARD_PYTHON311") or (
        sys.executable if sys.version_info[:2] == (3, 11) else shutil.which("python3.11"))
    assert python, "Python 3.11 is required for the compatibility guard; set SHIPGUARD_PYTHON311"
    proc = subprocess.run([python, "-I", "-c", COMPILER], input=json.dumps(sources),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"Python 3.11 compatibility compiler failed: {proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("source", [BROKEN_EXAMPLE, 'type Alias = int', 's = f"{d["x"]}"'])
def test_the_detector_actually_detects_the_construct_it_guards(source):
    assert "negative.py" in _compile311({"negative.py": source})


def test_valid_multiline_and_concatenated_fstrings_are_accepted():
    sources = {
        "concat.py": 's = (f"{x}"\n f"{y}")',
        "triple.py": 's = f"""{(1 +\n 2)}"""',
    }
    assert _compile311(sources) == {}


def test_all_source_compiles_on_python311():
    sources = {str(p.relative_to(ROOT)): p.read_text()
               for d in SOURCE_DIRS for p in sorted((ROOT / d).rglob("*.py"))}
    assert len(sources) > 20, f"only scanned {len(sources)} files"
    assert not (errors := _compile311(sources)), errors
