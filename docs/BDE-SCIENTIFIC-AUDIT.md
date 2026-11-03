# Scientific-validity audit

Audited source: original PR head `98a7e5e` and the Phase 0 runtime repair `8bc815c`.
This audit has not changed discovery algorithms or rescored an unseen holdout.

## Independence and the original 3/6

Three different claims must remain separate:

| Claim | Finding |
|---|---|
| The discovery call did not receive hand-written acceptance tests | Supported by the harness interface: `_discover` receives the baseline repository, module and revision. |
| Engine development was blind to the target defects | Contradicted by development context: these are the prior v0.2.0 targets; the initial runner already says it matches “definitive upstream semantics”; commit `975560e` changes witness collection and scoring with digit/caseless target distinctions explicitly described. |
| Evaluation used previously unseen targets selected independently after freezing the engine | NOT ESTABLISHED. All six targets and their labelled requirements already existed in the same repository before BDE development. |

The supportable claim is: **on a development corpus of six historical defects,
BDE rediscovered three without supplying their acceptance contracts to its
discovery function, and its own predicates held for those witnesses at the repair
revisions.** This is useful feasibility evidence, not independent generalisation.

The scorer uses the same BDE predicate to assess an upstream repair. That is a
new execution at a different source revision, not an independent semantic oracle.
The materialiser clones full Git history, including future fixes, and stores the
fix revision alongside the baseline. The scorer and engine have the same OS
authority. An honest deterministic collector may ignore these inputs, but the
labels were not inaccessible to the developer agent or executed target code.

## Findings accounting and adjudication

Recount of the committed `benchmarks/bde/results.json`:

| Quantity | Count |
|---|---:|
| Tasks / distinct repositories | 6 / 3 |
| Baseline finding rows | 35 |
| Unique baseline export/input pairs (across revisions) | 12 |
| Rows labelled documentation drift | 24 |
| Unique documentation export/input pairs | 6 |
| Distinct documentation export families | 3 |
| Fix-revision finding rows | 27 |
| Unique fix-revision export/input pairs | 7 |
| Raw mutation attempts / counted importable mutations | 48 / 36 |
| Harmless-refactor controls | 12 |

The six documentation cases are four `isScriptProtocol` strings, one
`normalizeURL` example and one empty-fragment `withFragment` example. Each appears
in both README/JSDoc and across two ufo tasks. I independently executed all six
calls at both baselines and both fix revisions in a network-disabled container.
All recorded discrepancies reproduced. The corresponding source snapshots were
read from exact commits, listed in the evidence manifest.

This establishes documentation/code inconsistency. It does not establish 24
distinct code defects, security vulnerabilities, or developer intent to change
the implementation rather than the documentation. A documentation contradiction
is actionable for review without automatically becoming a protected execution gate.

The three residual scule rows at `9927800` are repeated instances of the
`splitByCase('a-', [])` behaviour. Direct execution returns `['a','-']` there and
`['a-']` at `57cfd15`; the later upstream patch changes the character-case default
and adds a regression test. This supports the later behaviour change. It does not
independently prove that every boundary rule inferred for the older version was
mandatory. Do not call the fix controls clean: they contain 27 labelled rows.

The legacy scorer assigns labels by `export:kind`, without binding the audit to
the exact commit, arguments, expected value or provenance. Any future finding in
that broad family inherits the label. Even a reproduction ERROR can fall through
to that label. “Zero unlabelled findings” therefore is not a false-positive rate.
A valid false-positive-rate denominator needs independently adjudicated negative
opportunities. Finding-level false discovery needs exact-witness adjudication,
deduplication and an explicit uncertain category. Neither denominator is established.

## Authority: demonstrated false confirmations

Synthetic controls, deliberately outside any holdout:

1. `square(value: number, digits = 2)` validates its numeric input. Valid calls
   `square(2)` and `square(3, 1)` return 4 and 9. BDE generates strings for the
   required argument and reports the resulting type error as a confirmed defect.
2. `render(value: string, mode?: string)` returns the value when mode is omitted,
   otherwise appends the mode. Valid calls return `ok` and `ok:wide`. BDE replaces
   a missing default with JSON null and invents equivalence between omission and
   explicit null, which is not in the declared argument type.

Both produce `CONFIRMED_CONTRADICTION`; all four separate valid-domain assertions
pass. Raw source, findings and assertions are preserved. These are invalid laws,
not newly found defects in the control programs.

Relevant implementation:

- `compiler._optional_arg_laws` treats the first optional parameter as the end of
  required arguments and substitutes `None` for a missing default.
- `strategies.execution_for` generates one string argument for optional-argument
  laws regardless of required arity or types.
- `authority.qualify` qualifies all class-B inputs by default. The Q2 second
  extraction establishes signature shape, not the semantic validity of the
  detailed splitter predicate. Two extractions are not independent authorities.
- A signature allowing omission does not prove the function is total for every
  generated value. Documented preconditions and thrown errors need interpretation.
- `allow_class_b_blocking=False` is not checked when Q1/Q2 promote class-D laws;
  `allow_class_c_regressions` is declared but not applied in qualification.

Required remediation before a freeze: unsupported domains remain hypotheses or
abstentions, omission is distinct from null, applicability is checked independently,
and inferred laws cannot acquire execution authority through the engine's own label.
Documented literal examples can remain useful discrepancy checks without implying
that the implementation must change.

## Scheduler, execution and witnesses

Phase 0 corrects worker loading and exposes law errors, but other limitations remain:

- `build_lawpack` only checks a grounding hash if the named file exists. Missing
  grounding is not refused there. `run_lawpack` trusts supplied execution entries
  and does not itself validate the full evidence schema or reject missing outcomes.
- Generated cases can be counted as passing trials even when every predicate call
  reports out of scope. The three-witness limit does not deduplicate minimized
  inputs, explaining repeated finding rows.
- Calls are synchronous; promises are not awaited. Async behaviour is unsupported
  and should be reported explicitly rather than assessed as returned objects.
- Shrinking does not always preserve domain constraints or a particular failure
  reason, and `shrunk: true` does not prove minimality. Minimality needs a declared
  reduction relation and rechecking of the exact minimized input.
- Evidence hashes the target module and grounding but does not bind all transitive
  sources, dependency lockfiles, runtime identity or the complete executable law.
- A standalone script was executed on a known documented-result mismatch. It
  printed different expected/observed arrays and exited **0**. It is an observation
  script, not an independent pass/fail verifier for general law predicates.
- `cmd_reproduce` executes the law's full generation strategy, without replacing it
  with the recorded witness or checking the recorded source identity. Another
  failing input can therefore support its “REPRODUCED” message.

## Repair and protected authority

`cmd_repair` constructs a Sentinel contract whose `expectedNot` is the text
`the documented failure (...)`. Returning a value unequal to that explanatory
string does not prove the behavioural law. A correct Sentinel implementation
cannot strengthen a contract that does not express the required outcome.

The same function writes `approvedBy: BDE grounded law (...)` without independent
developer approval, including for evidence containing an inferred law. A distinct
verifier process is not independent authority over the requirement. The protected
gate must consume independently approved, source-bound outcomes, not this contract.

The Codex adapter captures tails of stdout/stderr rather than complete structured
agent events and usage. It does not currently pin model, effort and a token budget
for the proposed four-arm comparison. No live agent session was run for this audit;
no prior or scripted repair is being presented as a new Codex result.

## Mutation adequacy

14/36 is the measured fraction of the harness's importable token substitutions
that triggered a previously nonfailing law. It is not yet a validated semantic
mutation score. `str.find` can change comments, literals, unreachable code or
equivalent behaviour; importing does not prove a semantic mutant. The two ufo
subjects also repeat much of the same code and probes.

“Known-valid fixes” include 12 failing laws on each ufo utils subject and one
failing scule law. The harness excludes already failing laws, so their further
damage is not measured. ERROR/SKIP outcomes are not comprehensively accounted for;
refactor errors can be treated as absence of a new finding. Two whitespace/comment
controls per subject are weak evidence about false alarms on meaningful refactors.
Use syntax-aware mutation, independently verified non-equivalence, negative-domain
controls and explicit execution failures before generalising this score.

## Remediation before the unseen freeze

The findings above describe the audited original engine. The pre-freeze revision:

- preserves omission versus null, generates only supported declared scalar domains,
  keeps signature and splitter inferences as hypotheses, and honours blocking policy;
- requires grounding files and a complete, unique set of runner outcomes;
- records all-skipped generated laws and async functions as unsupported, deduplicates
  witnesses and gives compiled laws stable content-derived IDs;
- binds evidence to tracked source contents, executable lawpack and runtime image;
- reproduces the exact recorded input and refuses source changes; standalone literal
  discrepancy scripts return a failing exit code, while relational scripts identify
  themselves as observations rather than claiming independent verification;
- removes self-approved BDE repair contracts and requires an external approved contract;
- adds the opt-in, digest-pinned Docker backend and mandatory negative containment tests.

These repairs were developed using the existing development corpus and synthetic
controls, before selecting any new holdout targets. The old 3/6 result is retained
as development evidence; it has not been relabelled as an independent evaluation.

Remaining limits: lexical extraction and synchronous supported functions only;
shrinking is heuristic, not a proof of global minimality; dependencies outside
tracked contents are not fully content-addressed; mutation adequacy is unchanged.
Repository source, including comments and documentation, is untrusted evidence.
A documented contradiction warrants review, not automatic approval to change it.

Phase 0 is remotely green at `8bc815c`, run 41706606243. Independent generalisation,
incremental agent value and a new-project repair journey remain NOT ESTABLISHED
until the frozen evaluation is actually run and independently scored.
