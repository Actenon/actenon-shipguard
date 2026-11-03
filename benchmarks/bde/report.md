> **Historical development evidence; superseded scientific interpretation.**
> This report describes the original engine and known development corpus. The
> discovery call was not given acceptance tests, but engine development was not
> blind to these target defects. Claims of an independent holdout, zero invalid-law
> false positives, clean fix controls or validated semantic mutation sensitivity
> are not established by these results. The 24 documentation rows are six unique
> export/input pairs; repair revisions contain 27 finding rows. See
> [the scientific audit](../../docs/BDE-SCIENTIFIC-AUDIT.md) for accounting, counterexamples and pre-freeze repairs.
> No results below have been silently rescored or rewritten as unseen evidence.

# BDE Research Benchmark Report

**Engine:** Actenon Behavioural Discovery Engine (intent-compiler/1, runner predicates v1) — commit `e9abf91`+ (see `results.json: engine_commit`).
**Corpus:** the six frozen v0.2.0 historical-defect targets (3 real projects: `unjs/scule`, `unjs/ufo`, `fb55/entities`), re-used as **targets only**.
**Frozen:** `manifest.json` (corpus identity, scoring rubric, audit labels) before the formal run; `results.json` is the raw, as-measured output.

## The defining question

> Can ShipGuard independently discover meaningful defects in real software **without anyone
> hand-authoring the acceptance test that reveals the bug**?

BDE received, for each task: the buggy baseline repository — its source, TypeScript
signatures, README/JSDoc, and its own (defect-blind) test suite. It never received the
v0.2.0 manifest's requirements, contracts, prompts or expected outcomes. The upstream fix
commit was held out and used only by the scorer.

## Track A — natural developer defects (blind discovery, held-out scoring)

| task | project | verdict | the discovered witness |
|---|---|---|---|
| `scule-custom-separator-split` | scule | **DISCOVERED** | `splitByCase('a-', [])` → `['a','-']` — boundary at `-` is neither a listed separator nor a case change (grounded: README `### splitByCase` bullets) |
| `scule-splitbycase-numbers` | scule | **DISCOVERED** | `splitByCase('a1')` → `['a','1']` — a digit boundary is not a documented case change (same grounded law) |
| `ufo-parsefilename-optional-opts` | ufo | **DISCOVERED** | `parseFilename('http://example.com/path/to/filename.ext')` **throws** `TypeError` — the documented single-argument call shape (grounded: README example + JSDoc + signature); 3 distinct witnesses |
| `ufo-withoutbase-leading-slashes` | ufo | MISSED | the protocol-relative-injection property is not machine-extractable from the permitted evidence |
| `ufo-false-prefix-match` | ufo | MISSED | "Ensures the URL starts with base" is semantically ambiguous prose; no defensible law derivable |
| `entities-legacy-attribute-interrupted` | entities | MISSED | the interrupted-legacy-entity edge is deep parser logic; `decodeHTMLAttribute` has no examples/contracts in the permitted evidence |

**3/6 discovered, 3/6 missed, 0 invalid-law false positives.**

### Findings classification (all published)

* `DISCOVERED_DEFECT` — 3 tasks. Each witness fails at the baseline and **passes after the
  upstream fix**, verified by independent re-execution of the exact witness at the fix
  revision (`witness_status_at_fix_revision: PASS` in `results.json`).
* `TRUE_DOC_DRIFT` — 24 findings across the two missed ufo tasks. BDE surfaced **genuine
  documentation-code contradictions in ufo itself**: `isScriptProtocol` (README says `//
  true`, the code returns `false`), `normalizeURL` (`%20` vs `+` encoding drift),
  `withFragment` (empty hash does not remove the fragment, contrary to the README). Audit
  evidence and reproduction commands are frozen in `manifest.json → track_a.audit_evidence`;
  each was verified manually before labelling. These are true findings that are not the
  target defects and are not code defects — they are documentation rot.
* `TRUE_DELAYED_FIX` — at the `scule-splitbycase-numbers` **fix** revision (9927800), the
  boundary law fires on `splitByCase('a-', []) → ['a','-']`: 9927800 splits at caseless
  characters, and upstream 57cfd15 ("assume characters lowercase by default") later changed
  exactly this behaviour. Recorded as a labelled fix-revision finding, not a violation.
* `FALSE_POSITIVE` — **0** on the baselines; the fix-revision positive controls produced
  **0 unlabelled findings** (`positive_control_violations: 0`).

### Why the misses missed (recorded, not excused)

* `withoutBase` leading slashes: the security property ("must not return a protocol-relative
  URL") is real but is stated nowhere in the permitted evidence; deriving it would require
  the engine to *invent* a requirement — exactly what the evidence hierarchy forbids.
* `withBase` false prefix: the README sentence admits both readings; an engine that picked
  one would be guessing.
* `entities`: the defect is an interaction between legacy-entity parsing state and attribute
  mode with no machine-readable contract in the repository.

Discovering these classes needs richer evidence sources (differential references, security
property catalogues, or developer-supplied policies) — tracked as known limitations, not
claimed.

## Track B — mutation sensitivity and false positives (known-valid code)

Subjects: the six upstream **fix** revisions (known-valid). 8 single-token mutation
operators applied one occurrence at a time in disposable copies; 2 provably-harmless
refactor controls (comment, blank line) that must trigger nothing.

| subject | behavioural mutations | detected | refactor FPs |
|---|---|---|---|
| scule (both revisions) | 7 | 4 | 0 |
| ufo utils ×2 | 7 | 4 | 0 |
| scule numbers-fix | 7 | 0 | 0 |
| ufo parse-fix | 3 | 0 | 0 |
| entities decode-fix | 5 | 2 | 0 |
| **total** | **36** | **14 (38.9%)** | **0** |

Interpretation (honest): the compiled law sets detect 38.9% of small semantic mutations.
Two subjects detect 0 — when the compiled laws are example/preservation-shaped, token
flips far from the documented examples go unnoticed. A surviving mutation is **evidence of
limited detection sensitivity**, never a defect claim. Zero refactor false positives means
the laws did not cry wolf on provably-harmless changes.

## Reproduction

```bash
git clone https://github.com/Actenon/actenon-shipguard && cd actenon-shipguard
python3 -m venv .venv && . .venv/bin/activate && pip install '.[dev]'
git clone https://github.com/rossbuckley1990-hash/sentinel-verified.git ../sentinel-verified
cd ../sentinel-verified && git checkout becba502 && npm install && npm run build && cd -
export SHIPGUARD_TSX=$PWD/../sentinel-verified/node_modules/.bin/tsx
python3 benchmarks/bde/harness.py            # re-runs both tracks deterministically
```

Determinism: seeded generation (mulberry32, fixed seeds per law family), fixed trial
budgets, no network, no LLM. `results.json` records the exact engine commit.

## What this benchmark does NOT establish

* It does not establish a general defect-detection rate: 6 tasks from 3 string/URL-library
  projects is a small, homogeneous corpus.
* It does not test live-agent interaction (that is the v0.2.0 benchmark's domain).
* Mutation sensitivity is law-set-specific: richer law catalogues would change it.
* The 24 doc-drift findings were labelled by human audit (commands frozen in the manifest);
  they are not model judgements, but they are also not automatic.
