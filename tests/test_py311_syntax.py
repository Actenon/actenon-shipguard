"""Python 3.11 syntax compatibility — the project's declared minimum (`target-version = "py311"`).

CI runs 3.11 and 3.12, but development happens on newer interpreters, and a construct that is legal
on 3.12+ can be a SyntaxError on 3.11. That is not hypothetical: a multi-line expression inside an
f-string replacement field (PEP 701, 3.12+) broke `verify (3.11)` on commit 32e987a while passing
locally on 3.14 and passing ruff, whose `target-version` does not check for it.

`ast.parse(..., feature_version=(3, 11))` does NOT catch this class, so the guard inspects the AST
directly: a `FormattedValue` whose span crosses lines means the `{...}` field held a multi-line
expression, which 3.11 rejects. Implicit concatenation of single-line f-strings — the style used
everywhere else here — is unaffected.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("src", "tests", "benchmark")

BROKEN_EXAMPLE = '''a(f"- x **{d.get('n')}** only. "
  f"{('some long text '
     'continued here') if d.get('n') == 'claude' else 'other'} "
  "tail")
'''


def _multiline_fields(src: str) -> list[int]:
    return [n.lineno for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FormattedValue) and n.end_lineno and n.end_lineno > n.lineno]


def test_the_detector_actually_detects_the_construct_it_guards():
    """A guard that cannot fail is not a guard. This is its negative control."""
    assert _multiline_fields(BROKEN_EXAMPLE) == [2]


def test_no_source_uses_a_multiline_fstring_replacement_field():
    offenders: dict[str, list[int]] = {}
    checked = 0
    for d in SOURCE_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            checked += 1
            lines = _multiline_fields(path.read_text())
            if lines:
                offenders[str(path.relative_to(ROOT))] = lines
    assert checked > 20, f"only scanned {checked} files — the guard is not covering the project"
    assert not offenders, (
        f"these f-string replacement fields span multiple lines and are a SyntaxError on Python 3.11 "
        f"(the declared minimum): {offenders}. Hoist the expression into a local variable.")
