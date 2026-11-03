"""Grounded evidence collection (mandate §5: the input side of the Intent Compiler).

Collects ONLY machine-extractable evidence from the repository under inspection:

  * exported-function signatures (deterministic extractor; documented limitation below)
  * JSDoc blocks adjacent to exports (verbatim text, line ranges, hashes)
  * README API sections per export (verbatim bullets/examples)
  * documented example calls with expected results (JSDoc ``@example`` and README fences)
  * the project's own test assertions (I/O pairs) — Class C preservation evidence
  * package facts (name, type, test script)

SECURITY: everything extracted from the repository is DATA. The literal parser below is
hand-written and evaluates NOTHING — no ``eval``, no ``new Function``, no identifier
resolution. A prompt-injection payload inside a comment or README can at worst become an
excerpt string attached to a law; it can never execute (mandate §15). Law predicates are
selected from a fixed catalogue, and law parameters are literal-only values produced here.

Deterministic parser limitation (recorded on every signature law): the signature extractor
is a lexical scanner for the COMMON exported-function shapes (function declarations,
overloads, arrow-function consts) rather than a full TypeScript parse. When the TypeScript
compiler is available in the inspected repo's node_modules it is used preferentially (see
``ts_probe.mjs``); otherwise the scanner result is flagged ``extractor: "regex-fallback"``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .intake import read_evidence


# -------------------------------------------------------------------------------------------- #
# Safe literal parser (JSON-superset, no evaluation)
# -------------------------------------------------------------------------------------------- #
class LiteralError(ValueError):
    pass


class _Lit:
    """Recursive-descent parser for JS *literals* only. Anything else is an error."""

    def __init__(self, text: str) -> None:
        self.t = text
        self.i = 0

    def _ws(self) -> None:
        while self.i < len(self.t):
            c = self.t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "/" and self.t[self.i + 1:self.i + 2] == "/":      # line comment
                nl = self.t.find("\n", self.i)
                self.i = len(self.t) if nl < 0 else nl
            elif c == "/" and self.t[self.i + 1:self.i + 2] == "*":      # block comment
                end = self.t.find("*/", self.i + 2)
                if end < 0:
                    raise LiteralError("unterminated block comment")
                self.i = end + 2
            else:
                return

    def parse(self) -> Any:
        self._ws()
        v = self._value()
        self._ws()
        if self.i != len(self.t):
            raise LiteralError(f"trailing input at {self.i}: {self.t[self.i:self.i + 24]!r}")
        return v

    def _value(self) -> Any:
        self._ws()
        if self.i >= len(self.t):
            raise LiteralError("unexpected end of input")
        c = self.t[self.i]
        if c in "\"'`":
            return self._string()
        if c == "[":
            return self._array()
        if c == "{":
            return self._object()
        if c == "-" or c.isdigit() or (c == "." and self.i + 1 < len(self.t) and self.t[self.i + 1].isdigit()):
            return self._number()
        m = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", self.t[self.i:])
        if not m:
            raise LiteralError(f"unexpected character {c!r} at {self.i}")
        word = m.group(0)
        self.i += len(word)
        if word == "true":
            return True
        if word == "false":
            return False
        if word in ("null", "undefined"):
            return None
        if word in ("NaN", "Infinity"):
            return float(word)
        raise LiteralError(f"identifier {word!r} is not a literal (no evaluation, ever)")

    def _string(self) -> str:
        quote = self.t[self.i]
        self.i += 1
        out: list[str] = []
        while self.i < len(self.t):
            c = self.t[self.i]
            if c == quote:
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                if self.i >= len(self.t):
                    break
                e = self.t[self.i]
                simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0",
                          "\\": "\\", "'": "'", '"': '"', "`": "`", "/": "/"}
                if e in simple:
                    out.append(simple[e])
                    self.i += 1
                elif e == "u":
                    hex4 = self.t[self.i + 1:self.i + 5]
                    if len(hex4) == 4 and all(h in "0123456789abcdefABCDEF" for h in hex4):
                        out.append(chr(int(hex4, 16)))
                        self.i += 5
                    else:
                        raise LiteralError("bad \\u escape")
                elif e == "x":
                    hex2 = self.t[self.i + 1:self.i + 3]
                    if len(hex2) == 2 and all(h in "0123456789abcdefABCDEF" for h in hex2):
                        out.append(chr(int(hex2, 16)))
                        self.i += 3
                    else:
                        raise LiteralError("bad \\x escape")
                elif e == "\n":                       # line continuation
                    self.i += 1
                else:
                    out.append(e)
                    self.i += 1
            elif c == "$" and self.i + 1 < len(self.t) and self.t[self.i + 1] == "{":
                raise LiteralError("template interpolation is not a literal")
            else:
                out.append(c)
                self.i += 1
        raise LiteralError("unterminated string")

    def _number(self) -> float | int:
        m = re.match(r"0[xX][0-9a-fA-F]+|-?\d+\.?\d*(?:[eE][+-]?\d+)?|-?\.\d+", self.t[self.i:])
        if not m:
            raise LiteralError("bad number")
        tok = m.group(0)
        self.i += len(tok)
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", tok):
            return int(tok, 16)
        if any(ch in tok for ch in ".eE") :
            return float(tok)
        return int(tok)

    def _array(self) -> list[Any]:
        self.i += 1                       # consume [
        out: list[Any] = []
        self._ws()
        if self.i < len(self.t) and self.t[self.i] == "]":
            self.i += 1
            return out
        while True:
            out.append(self._value())
            self._ws()
            if self.i < len(self.t) and self.t[self.i] == ",":
                self.i += 1
                self._ws()
                if self.i < len(self.t) and self.t[self.i] == "]":   # trailing comma
                    self.i += 1
                    return out
                continue
            if self.i < len(self.t) and self.t[self.i] == "]":
                self.i += 1
                return out
            raise LiteralError(f"expected , or ] at {self.i}")

    def _object(self) -> dict[str, Any]:
        self.i += 1                       # consume {
        out: dict[str, Any] = {}
        self._ws()
        if self.i < len(self.t) and self.t[self.i] == "}":
            self.i += 1
            return out
        while True:
            self._ws()
            c = self.t[self.i]
            if c in "\"'`":
                key = self._string()
            else:
                m = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", self.t[self.i:])
                if not m:
                    raise LiteralError(f"bad object key at {self.i}")
                key = m.group(0)
                self.i += len(key)
            self._ws()
            if self.i < len(self.t) and self.t[self.i] == ":":
                self.i += 1
                out[str(key)] = self._value()
            else:                          # shorthand `{ strict }` — value undefined
                out[str(key)] = None
            self._ws()
            if self.i < len(self.t) and self.t[self.i] == ",":
                self.i += 1
                self._ws()
                if self.i < len(self.t) and self.t[self.i] == "}":
                    self.i += 1
                    return out
                continue
            if self.i < len(self.t) and self.t[self.i] == "}":
                self.i += 1
                return out
            raise LiteralError(f"expected , or }} at {self.i}")


def parse_literal(text: str) -> Any:
    """Parse a JS literal into plain Python data. Raises LiteralError on anything else."""
    return _Lit(text).parse()


_CALL_RE_CACHE: dict[str, re.Pattern] = {}


def _call_regex(name: str, qualifiers: tuple[str, ...]) -> re.Pattern:
    """Regex finding ``name(…)`` or ``<qualifier>.name(…)`` call sites (qualifiers are the
    package's own name(s), so unrelated method calls like ``foo.name(...)`` never match)."""
    key = f"{name}|{qualifiers}"
    if key in _CALL_RE_CACHE:
        return _CALL_RE_CACHE[key]
    esc = re.escape(name)
    qual = "" if not qualifiers else ("(?:" + "|".join(re.escape(q) for q in qualifiers) + r")\s*\.\s*")
    name_alt = "(?:" + qual + esc + "|" + esc + ")" if qualifiers else esc
    pat = re.compile(
        r"(?:^|[^\w$])(?:const|let|var)\s+[\w$]+\s*=\s*(?:await\s+)?" + name_alt + r"\s*\("
        r"|(?:^|[^\w$.])(?:await\s+)?" + name_alt + r"\s*\(")
    _CALL_RE_CACHE[key] = pat
    return pat


def parse_call(text: str, name: str, qualifiers: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Parse ``name(<literal args>)`` (or ``pkg.name(...)``) from one line of documentation.

    Returns ``{"args": [...], "span": (start, end)}`` or None when the line does not contain
    such a call. Accepts an optional ``const x =`` / ``await`` prefix and a trailing ``;``.
    Argument list is parsed with the no-eval literal parser, so a doc line can never smuggle
    executable code.
    """
    m = _call_regex(name, qualifiers).search(text)
    if not m:
        return None
    open_idx = m.end() - 1
    depth = 0
    j = open_idx
    while j < len(text):
        cj = text[j]
        if cj in "\"'`":
            # skip a string literal starting at j; j ends just past its closing quote
            k = j + 1
            while k < len(text):
                if text[k] == "\\":
                    k += 2
                    continue
                if text[k] == cj:
                    break
                k += 1
            if k >= len(text):
                return None                     # unterminated string
            j = k + 1
            continue
        if cj in "([{":
            depth += 1
        elif cj in ")]}":
            depth -= 1
            if depth == 0:
                args_text = text[open_idx + 1:j]
                try:
                    args = _parse_args(args_text)
                except LiteralError:
                    return None
                return {"args": args, "span": (m.start(), j + 1)}
        j += 1
    return None


def _parse_args(args_text: str) -> list[Any]:
    args_text = args_text.strip()
    if not args_text:
        return []
    parts = _split_top(args_text)
    return [parse_literal(p.strip()) for p in parts]


def _split_top(text: str) -> list[str]:
    parts, depth, cur, i = [], 0, [], 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            cur.append(c)
            i += 1
            while i < len(text):
                cur.append(text[i])
                if text[i] == "\\" and i + 1 < len(text):
                    cur.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == c:
                    i += 1
                    break
                i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


# -------------------------------------------------------------------------------------------- #
# Signatures
# -------------------------------------------------------------------------------------------- #
@dataclass
class Param:
    name: str                    # identifier or "{…}" destructuring pattern
    optional: bool               # `?` marker or default value present
    default_text: str | None     # verbatim default expression text (e.g. `""`, `STR_SPLITTERS`)
    type_text: str | None        # verbatim type annotation text
    destructured: bool


@dataclass
class Signature:
    export: str
    params: list[Param]
    return_type: str | None
    line_start: int              # 1-based line of the `export` keyword
    line_end: int                # 1-based line of the parameter-list close paren
    jsdoc: str | None            # verbatim JSDoc text (without /** */) or None
    jsdoc_lines: tuple[int, int] | None
    extractor: str = "regex-scanner"


def _balanced(text: str, start: int, open_ch: str = "(", close_ch: str = ")") -> int:
    """Index just past the balanced close, or -1."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            k = i + 1
            while k < len(text):
                if text[k] == "\\":
                    k += 2
                    continue
                if text[k] == c:
                    break
                k += 1
            i = k + 1
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def extract_signatures(module_text: str) -> list[Signature]:
    """Extract exported function signatures from a TS/ESM module body.

    Handles: ``export function name<Gen>(params): Ret {`` (and overload declarations ending
    with ``;``), ``export async function``, and ``export const name = (params) => Ret {``.
    Only the IMPLEMENTATION signature (with a body) is kept for overloads when both exist;
    an overload-only export is kept with ``return_type`` from the declaration.
    """
    sigs: list[Signature] = []
    seen: dict[str, Signature] = {}
    for m in re.finditer(r"^export\s+(?:async\s+)?(?:function\s*\*?\s*|const\s+)([A-Za-z_$][\w$]*)"
                         r"(\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>)?", module_text, re.M):
        name = m.group(1)
        after = module_text[m.end():]
        # find the parameter list: next '(' at depth 0 (skip generic <...>)
        i = 0
        params_open = -1
        while i < len(after):
            c = after[i]
            if c == "<":
                close = _balanced(after, i, "<", ">")
                i = close if close > 0 else len(after)
                continue
            if c == "(":
                params_open = i
                break
            if c in ";=\n{":
                break
            i += 1
        if params_open < 0:
            continue
        close = _balanced(after, params_open)
        if close < 0:
            continue
        params_text = after[params_open + 1:close - 1]
        rest = after[close:]
        # return type: text between ':' and the body '{' or ';' (or '=>')
        return_type = None
        rm = re.match(r"\s*:\s*([^;=]{1,200}?)(?=\s*(?:\{|;|=>))", rest, re.S)
        if rm:
            return_type = rm.group(1).strip()
        params = _parse_params(params_text)
        line_start = _line_of(module_text, m.start())
        line_end = _line_of(module_text, m.start() + close)
        # JSDoc immediately preceding the export keyword
        jsdoc, jsdoc_lines = _preceding_jsdoc(module_text, m.start())
        sig = Signature(export=name, params=params, return_type=return_type,
                        line_start=line_start, line_end=line_end, jsdoc=jsdoc, jsdoc_lines=jsdoc_lines)
        # prefer the implementation signature (one with a body) over an overload declaration
        has_body = bool(re.match(r"\s*(?::[^;=]*)?\{", rest, re.S))
        if name in seen:
            if has_body and not seen[name]._has_body_flag:   # noqa: SLF001
                seen[name] = sig
                sig._has_body_flag = True                    # type: ignore[attr-defined]
        else:
            sig._has_body_flag = has_body                    # type: ignore[attr-defined]
            seen[name] = sig
    sigs = list(seen.values())
    for s in sigs:
        del s._has_body_flag                                  # type: ignore[attr-defined]
    return sigs


def _parse_params(params_text: str) -> list[Param]:
    params: list[Param] = []
    if not params_text.strip():
        return params
    for part in _split_top(params_text):
        part = part.strip()
        if not part:
            continue
        # name: identifier, destructuring pattern, or rest
        nm = re.match(r"(\{[^{}]*\}|\[[^\[\]]*\]|\.\.\.[\w$]+|[\w$]+)", part)
        if not nm:
            continue
        name_tok = nm.group(1)
        destructured = name_tok.startswith("{") or name_tok.startswith("[")
        rest_part = part[nm.end():].lstrip()
        optional = rest_part.startswith("?")
        rest_part = rest_part[1:].lstrip() if optional else rest_part
        default_text = None
        type_text = None
        if rest_part.startswith(":"):
            annot = rest_part[1:]
            eq = _find_top_level_eq(annot)
            if eq >= 0:
                type_text = annot[:eq].strip() or None
                default_text = annot[eq + 1:].strip() or None
            else:
                type_text = annot.strip() or None
        elif rest_part.startswith("="):
            default_text = rest_part[1:].strip() or None
        if default_text is not None:
            optional = True
        params.append(Param(name=name_tok, optional=optional, default_text=default_text,
                            type_text=type_text, destructured=destructured))
    return params


def _find_top_level_eq(text: str) -> int:
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            k = i + 1
            while k < len(text):
                if text[k] == "\\":
                    k += 2
                    continue
                if text[k] == c:
                    break
                k += 1
            i = k + 1
            continue
        if c in "([{<":
            depth += 1
        elif c in ")]}>":
            depth -= 1
        elif c == "=" and depth == 0 and (i + 1 >= len(text) or text[i + 1] != "=" and text[i + 1] != ">"):
            if i > 0 and text[i - 1] in "<>!":
                i += 1
                continue
            return i
        i += 1
    return -1


def _preceding_jsdoc(text: str, export_index: int) -> tuple[str | None, tuple[int, int] | None]:
    before = text[:export_index].rstrip()
    if not before.endswith("*/"):
        return None, None
    close = len(before)
    open_idx = before.rfind("/**")
    if open_idx < 0:
        return None, None
    doc = before[open_idx + 3:close - 2]
    return doc, (_line_of(text, open_idx), _line_of(text, close))


# -------------------------------------------------------------------------------------------- #
# README API sections + documented examples + test pairs
# -------------------------------------------------------------------------------------------- #
@dataclass
class DocSection:
    file: str
    export: str
    line_start: int
    line_end: int
    text: str


@dataclass
class DocExample:
    file: str
    line: int                       # 1-based line of the example call
    export: str = ""               # the export the example was extracted FOR
    args: list[Any] = None          # type: ignore[assignment]
    expected: Any = None            # documented expected value when literal (else None)
    expected_present: bool = False  # a result IS documented (maybe as a prose description)
    expected_kind: str | None = None   # "literal" | "undefined" | "description"
    expected_text: str | None = None   # verbatim documented result text
    expected_line: int | None = None
    context: str = "readme"


@dataclass
class TestPair:
    file: str
    line: int
    args: list[Any]
    expected: Any
    matcher: str                     # toEqual | toBe | toStrictEqual | toMatchObject


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def extract_readme_sections(readme_text: str, exports: list[str]) -> dict[str, DocSection]:
    """Map ``export -> README API section`` for ``### \\`export(…)\\`` style headings."""
    out: dict[str, DocSection] = {}
    lines = readme_text.splitlines()
    heading_re = re.compile(r"^#{2,4}\s+`?([A-Za-z_$][\w$]*)\s*(?:\([^)]*\))?`?\s*$")
    for idx, line in enumerate(lines):
        m = heading_re.match(line)
        if not m or m.group(1) not in exports:
            continue
        end = len(lines)
        for j in range(idx + 1, len(lines)):
            if re.match(r"^#{1,4}\s", lines[j]):
                end = j
                break
        out[m.group(1)] = DocSection(file="", export=m.group(1), line_start=idx + 1, line_end=end,
                                     text="\n".join(lines[idx:end]))
    return out


_EXPECTED_RE = re.compile(r"^\s*(?://|#)\s*(?:->|=>|Result(?:s)?:|Returns?|returns?)\s*(.+?)\s*$")


def extract_doc_examples(text: str, export: str, *, file: str, context: str,
                         base_line: int = 1, qualifiers: tuple[str, ...] = ()) -> list[DocExample]:
    """Extract ``export(<literal args>)`` calls plus a documented expected result.

    Recognised result forms (the line directly ABOVE the call, or directly below when the
    call is a statement):
      ``// -> value``   ``// => value``   ``// Result: value``   ``// Returns value``
    and the trailing-comment form ``export(...); // -> value``.

    Only LITERAL results (numbers, strings, arrays, objects, ``true``/``false``/``null``/
    ``undefined``) support an equality check. A non-literal description such as
    ``// Result: filename.ext`` is kept verbatim as ``expected_kind="description"`` — the
    engine never guesses an equality relation from prose.
    """
    lines = text.splitlines()
    examples: list[DocExample] = []
    for idx, raw in enumerate(lines):
        call = parse_call(raw, export, qualifiers)
        if call is None:
            continue
        line_no = base_line + idx
        present, kind, value, vtext, vline = False, None, None, None, None
        # trailing comment on the same line: an explicit marker form, or a BARE comment that
        # parses as a literal (``// "value"``) — prose never parses as a literal, so it is
        # safely ignored rather than guessed.
        tail = raw[call["span"][1]:].strip()
        tm = re.match(r"^(?:;|,)?\s*(?://|#)\s*(?:->|=>|Result(?:s)?:|Returns?)\s*(.+?)\s*;?\s*$", tail)
        if tm:
            present, kind, value, vtext = _classify_expected(tm.group(1))
            vline = line_no
        if not present:
            bm = re.match(r"^(?:;|,)?\s*(?://|#)\s*(.+?)\s*;?\s*$", tail)
            if bm and _parses_as_literal(bm.group(1)):
                present, kind, value, vtext = _classify_expected(bm.group(1))
                vline = line_no
        if not present and idx > 0:
            pm = _EXPECTED_RE.match(lines[idx - 1])
            if pm:
                present, kind, value, vtext = _classify_expected(pm.group(1))
                vline = line_no - 1
        if not present and idx + 1 < len(lines):
            nm = _EXPECTED_RE.match(lines[idx + 1])
            if nm:
                present, kind, value, vtext = _classify_expected(nm.group(1))
                vline = line_no + 1
        examples.append(DocExample(file=file, line=line_no, export=export, args=call["args"], expected=value,
                                   expected_present=present, expected_kind=kind, expected_text=vtext,
                                   expected_line=vline, context=context))
    return examples


def _parses_as_literal(text: str) -> bool:
    try:
        parse_literal(text.strip().rstrip(";").strip())
        return True
    except LiteralError:
        return False


def _classify_expected(text: str) -> tuple[bool, str | None, Any, str | None]:
    """(present, kind, value, verbatim-text) for a documented result."""
    t = text.strip().rstrip(";").strip()
    if t == "undefined":
        return True, "undefined", None, t
    if t == "null":
        return True, "literal", None, t
    if t:
        try:
            return True, "literal", parse_literal(t), t
        except LiteralError:
            return True, "description", None, t[:120]
    return False, None, None, None


_MATCHER_RE_TMPL = (r"expect\(\s*(?:{qual})?{name}\s*\((.*?)\)\s*\)\s*\.\s*"
                    r"(toEqual|toBe|toStrictEqual|toMatchObject)\s*\(\s*(.*?)\s*\)\s*;?")


def extract_test_pairs(test_text: str, export: str, *, file: str,
                        qualifiers: tuple[str, ...] = ()) -> list[TestPair]:
    """Extract ``expect(export(<args>)).toEqual(<expected>)`` pairs from vitest/jest source."""
    pairs: list[TestPair] = []
    qual = ("(?:" + "|".join(re.escape(q) for q in qualifiers) + r")\s*\.\s*") if qualifiers else ""
    qual_opt = ("(?:" + qual + r")?") if qual else ""
    pat = re.compile(_MATCHER_RE_TMPL.format(name=re.escape(export), qual=qual_opt), re.S)
    for m in pat.finditer(test_text):
        args_text, matcher, expected_text = m.group(1), m.group(2), m.group(3)
        try:
            args = _parse_args(args_text)
            expected = parse_literal(expected_text)
        except LiteralError:
            continue
        pairs.append(TestPair(file=file, line=_line_of(test_text, m.start()), args=args,
                              expected=expected, matcher=matcher))
    return pairs


# ------------------------------------------------------------------------------------------------- #
# test.each / it.each data tables: rows are literal I/O pairs, columns map via the callback params
# ------------------------------------------------------------------------------------------------- #
_EACH_RE_TMPL = r"(?:^|\n)\s*(?:test|it)\s*\.\s*each\s*\("
_IDENT_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def extract_each_tables(test_text: str, export: str, *, file: str,
                        qualifiers: tuple[str, ...] = ()) -> list[TestPair]:
    """Extract I/O pairs from ``test.each([[…]])`` tables whose callback calls ``export``.

    Supported shapes (both must hold, else the table is skipped — never guessed):
      * the ``.each`` argument is a LITERAL array of rows (arrays or single values),
      * the callback body contains ``expect(export(<args>)).<matcher>(<expected>)`` where each
        argument/expected is either a literal or a callback parameter identifier.
    Column identifiers resolve through the callback's parameter list; a row shorter than the
    parameter list supplies ``undefined`` for the missing trailing columns (the common
    optional-column pattern). This is extraction, not interpretation: pairs are emitted only
    when the row actually binds every argument expression.
    """
    pairs: list[TestPair] = []
    qual = ("(?:" + "|".join(re.escape(q) for q in qualifiers) + r")\s*\.\s*") if qualifiers else ""
    qual_opt = ("(?:" + qual + r")?") if qual else ""
    expect_pat = re.compile(
        r"expect\(\s*" + qual_opt + re.escape(export) + r"\s*\(([^)]*?)\)\s*\)\s*\.\s*"
        r"(toEqual|toBe|toStrictEqual|toMatchObject)\s*\(\s*([^;]*?)\s*\)", re.S)
    for m in re.finditer(_EACH_RE_TMPL, test_text):
        open_idx = m.end() - 1
        close = _balanced(test_text, open_idx)
        if close < 0:
            continue
        table_text = test_text[open_idx + 1:close - 1]
        try:
            rows = parse_literal(table_text)
        except LiteralError:
            continue
        if not isinstance(rows, list):
            continue
        # callback: `("%s => %s", (input, expected, custom?) => { body })` — TS optional
        # markers (`param?`) are tolerated and stripped.
        rest = test_text[close:close + 6000]
        cm = re.search(r"\(\s*((?:[\w$]+\??\s*,\s*)*[\w$]+\??\s*?)\)\s*=>\s*\{", rest)
        if not cm:
            continue
        param_names = [p.strip().rstrip("?") for p in cm.group(1).split(",") if p.strip()]
        body = rest[cm.end():cm.end() + 6000]
        col_index = {name: i for i, name in enumerate(param_names)}

        def resolve(expr: str, row: list[Any]) -> tuple[bool, Any, bool]:
            """-> (usable, value, present) — present=False for an absent trailing column."""
            expr = expr.strip()
            if not expr or expr == "undefined":
                return True, None, True
            if _IDENT_RE.match(expr):
                idx = col_index.get(expr)
                if idx is None:
                    return False, None, True
                if idx >= len(row):
                    return True, None, False         # optional trailing column absent in this row
                return True, row[idx], True
            try:
                return True, parse_literal(expr), True
            except LiteralError:
                return False, None, True

        # ALL expect branches (the common ``if (extra) expect(f(x, extra)) else expect(f(x))``
        # shape); a row uses the first branch whose column references are all PRESENT.
        branches: list[tuple[list[str], str, str]] = []
        for em in expect_pat.finditer(body):
            arg_exprs = [a.strip() for a in _split_top(em.group(1))] if em.group(1).strip() else []
            branches.append((arg_exprs, em.group(2), em.group(3).strip()))
        if not branches:
            continue

        for row in rows:
            if not isinstance(row, list):
                row = [row]
            chosen = None
            for arg_exprs, matcher, expected_expr in branches:
                ok = True
                trial: list[Any] = []
                for expr in arg_exprs:
                    usable, val, present = resolve(expr, row)
                    if not usable or not present:
                        ok = False
                        break
                    trial.append(val)
                if ok:
                    usable, expected, _ = resolve(expected_expr, row)
                    if usable:
                        chosen = (trial, matcher, expected)
                    break
            if chosen:
                args, matcher, expected = chosen
                pairs.append(TestPair(file=file, line=_line_of(test_text, m.start()), args=args,
                                      expected=expected, matcher=matcher))
    return pairs


# ------------------------------------------------------------------------------------------------- #
# Object-literal tables: `const tests = { input: expected }` + `for (const input in tests)` loop
# ------------------------------------------------------------------------------------------------- #
_OBJ_TABLE_TMPL = (r"const\s+(\w+)\s*=\s*\{")


def extract_object_tables(test_text: str, export: str, *, file: str,
                          qualifiers: tuple[str, ...] = ()) -> list[TestPair]:
    """Extract I/O pairs from ``const t = { input: expected }`` + ``for (const k in t)`` tables.

    The classic vitest loop shape. Emitted only when the loop body contains exactly
    ``expect(export(<key>)).<matcher>(<table>[<key>])`` — extraction, never interpretation.
    """
    pairs: list[TestPair] = []
    qual = ("(?:" + "|".join(re.escape(q) for q in qualifiers) + r")\s*\.\s*") if qualifiers else ""
    qual_opt = ("(?:" + qual + r")?") if qual else ""
    for m in re.finditer(_OBJ_TABLE_TMPL, test_text):
        open_idx = m.end() - 1
        close = _balanced(test_text, open_idx, "{", "}")
        if close < 0:
            continue
        table_var = m.group(1)
        table_text = test_text[open_idx + 1:close - 1]
        try:
            table = parse_literal("{" + table_text + "}")
        except LiteralError:
            continue
        if not isinstance(table, dict):
            continue
        rest = test_text[close:close + 3000]
        fm = re.search(r"for\s*\(\s*const\s+(\w+)\s+in\s+" + re.escape(table_var) + r"\s*\)", rest)
        if not fm:
            continue
        key_var = fm.group(1)
        em = re.search(r"expect\(\s*" + qual_opt + re.escape(export) + r"\s*\(\s*" + re.escape(key_var)
                       + r"\s*\)\s*\)\s*\.\s*(toEqual|toBe|toStrictEqual|toMatchObject)\s*\(\s*"
                       + re.escape(table_var) + r"\[\s*" + re.escape(key_var) + r"\s*\]\s*\)", rest)
        if not em:
            continue
        matcher = em.group(1)
        for key, expected in table.items():
            pairs.append(TestPair(file=file, line=_line_of(test_text, m.start()), args=[key],
                                  expected=expected, matcher=matcher))
    return pairs


# -------------------------------------------------------------------------------------------- #
# The evidence bundle
# -------------------------------------------------------------------------------------------- #
@dataclass
class EvidenceBundle:
    """Everything the compiler is allowed to see for one module."""
    repo: Path
    module: str
    revision: str
    module_text: str
    module_sha256: str
    signatures: list[Signature] = field(default_factory=list)
    readme_sections: dict[str, DocSection] = field(default_factory=dict)
    readme_file: str | None = None
    readme_sha256: str | None = None
    doc_examples: list[DocExample] = field(default_factory=list)
    test_pairs: dict[str, list[TestPair]] = field(default_factory=dict)   # export -> pairs
    test_files: dict[str, str] = field(default_factory=dict)             # file -> sha256
    package: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def grounding(self, source_type: str, file: str, line_start: int, line_end: int,
                  excerpt: str, sha256: str, extracted: dict[str, Any] | None = None):
        from .laws import Grounding
        return Grounding(source_type=source_type, file=file, line_start=line_start,
                         line_end=line_end, excerpt=excerpt[:400], sha256=sha256,
                         revision=self.revision, extracted=extracted or {})


def find_test_files(repo: Path, module: str, *, package_name: str = "",
                    export_names: list[str] | None = None, cap: int = 8) -> list[Path]:
    """Test files related to a module.

    Match order (deterministic, capped): same-basename ``*.test.*``/``*.spec.*`` anywhere,
    package-named test files (``test/scule.test.ts``), ``test|tests`` files whose content
    references one of the module's exports, and ``test/**/*<stem>*``. node_modules is always
    excluded. Content-reference matching is EXTRACTION SCOPING ONLY — a test file that mentions
    the export is evidence; what is extracted from it is still literal-only.
    """
    mod = Path(module)
    stem = mod.stem
    pkg = package_name.split("/")[-1] if package_name else ""
    patterns = [f"**/{stem}.test.*", f"**/{stem}.spec.*"]
    if pkg:
        patterns += [f"**/{pkg}.test.*", f"**/{pkg}.spec.*", f"test/{pkg}.test.*", f"tests/{pkg}.test.*"]
    patterns += [f"test/**/*{stem}*"]
    found: dict[Path, None] = {}
    for pat in patterns:
        for p in repo.glob(pat):
            if p.is_file() and "node_modules" not in p.parts and p.suffix in (".ts", ".tsx", ".js", ".mjs", ".cts", ".mts"):
                found[p] = None
    # content-reference fallback: test dirs mentioning one of the module's exports
    if len(found) < cap and export_names:
        for d in ("test", "tests", "src"):
            base = repo / d
            if not base.is_dir() or "node_modules" in base.parts:
                continue
            for p in sorted(base.rglob("*.test.*")) + sorted(base.rglob("*.spec.*")):
                if p in found or "node_modules" in p.parts or not p.is_file():
                    continue
                if len(found) >= cap:
                    break
                try:
                    if p.stat().st_size > 262_144:
                        continue
                    text = read_evidence(repo, p.relative_to(repo))
                except OSError:
                    continue
                if any(re.search(rf"\b{re.escape(e)}\s*\(", text) for e in export_names):
                    found[p] = None
    return sorted(found)[:cap]


def _jsdoc_strip(text: str) -> str:
    """Normalise JSDoc body lines: drop the leading `` * `` continuation markers."""
    out = []
    for line in text.splitlines():
        out.append(re.sub(r"^\s*\*\s?", "", line))
    return "\n".join(out)


def collect(repo: Path, module: str, revision: str, *, exports_of_interest: list[str] | None = None) -> EvidenceBundle:
    """Collect the grounded evidence for one module of a repository."""
    repo = Path(repo)
    text = read_evidence(repo, module)
    bundle = EvidenceBundle(repo=repo, module=module, revision=revision, module_text=text,
                            module_sha256=_sha256(text))
    bundle.signatures = extract_signatures(text)
    exports = exports_of_interest or [s.export for s in bundle.signatures]

    pkg_path = repo / "package.json"
    if pkg_path.exists() or pkg_path.is_symlink():
        import json
        try:
            bundle.package = json.loads(read_evidence(repo, "package.json"))
        except json.JSONDecodeError:
            bundle.notes.append("package.json is not valid JSON")
    pkg_name = str(bundle.package.get("name") or "")
    qualifiers = tuple(q for q in (pkg_name, pkg_name.split("/")[-1] if "/" in pkg_name else "") if q)

    readme = None
    for cand in ("README.md", "readme.md", "Readme.md", "README.MD"):
        if (repo / cand).exists() or (repo / cand).is_symlink():
            readme = repo / cand
            break
    if readme is not None:
        rtext = read_evidence(repo, readme.relative_to(repo))
        bundle.readme_file = readme.name
        bundle.readme_sha256 = _sha256(rtext)
        bundle.readme_sections = extract_readme_sections(rtext, exports)
        for export in exports:
            for ex in extract_doc_examples(rtext, export, file=readme.name, context="readme",
                                           qualifiers=qualifiers):
                bundle.doc_examples.append(ex)
    else:
        bundle.notes.append("no README found")

    # JSDoc example blocks adjacent to the exported functions (module-internal documentation)
    for sig in bundle.signatures:
        if sig.export not in exports or not sig.jsdoc:
            continue
        if not ("@example" in sig.jsdoc or "**Example:" in sig.jsdoc or "```" in sig.jsdoc):
            continue
        stripped = _jsdoc_strip(sig.jsdoc)
        for ex in extract_doc_examples(stripped, sig.export, file=module, context="jsdoc",
                                       base_line=(sig.jsdoc_lines[0] if sig.jsdoc_lines else 1),
                                       qualifiers=qualifiers):
            bundle.doc_examples.append(ex)

    for tf in find_test_files(repo, module, package_name=pkg_name,
                              export_names=[s.export for s in bundle.signatures]):
        ttext = read_evidence(repo, tf.relative_to(repo))
        rel = str(tf.relative_to(repo))
        bundle.test_files[rel] = _sha256(ttext)
        for export in exports:
            pairs = extract_test_pairs(ttext, export, file=rel, qualifiers=qualifiers)
            pairs += extract_each_tables(ttext, export, file=rel, qualifiers=qualifiers)
            pairs += extract_object_tables(ttext, export, file=rel, qualifiers=qualifiers)
            if pairs:
                bundle.test_pairs.setdefault(export, []).extend(pairs)
    return bundle
