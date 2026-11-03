# Law Provenance and Trust

> Who is allowed to say "this behaviour is REQUIRED", and how a law earns the right to
> block a change.

## 1. The central rule

**The proposer of a law can never be its certifier.**

Discovery proposes; a separate, deterministic authority policy decides. Nothing a
repository contains — not a comment, not a README sentence, not a test name — can make a law
blocking on its own say-so. This is the difference between a behavioural discovery engine
and an engine that hallucinates requirements and then enforces them.

## 2. The evidence classes

Every `BehaviouralLaw` carries exactly one class (mandate §4.1):

| class | source of justification | may block? | violation means |
|---|---|---|---|
| **A — AUTHORITATIVE** | developer-approved contracts, machine-readable API specs designated as authoritative, agreed acceptance criteria | yes, when `approval=approved` | `CONFIRMED_CONTRADICTION` |
| **B — GROUNDED** | applicable mathematical/structural properties whose applicability was established independently of the implementation (signature facts, verbatim-documented usage, recorded qualification) | yes, when `approval=qualified` | `CONFIRMED_CONTRADICTION` |
| **C — PRESERVATION** | behaviour of a trusted baseline: the project's own passing tests, approved fixtures | no (regression grade) | `REGRESSION_OBSERVED` |
| **D — INFERRED** | documentation interpretation, naming, comments, patterns | no (hypothesis) | `HYPOTHESIS_FALSIFIED` (review) |

A class-C violation is never a claim that the baseline was *correct* — only that the
behaviour changed. A class-D violation is never automatically a defect claim.

## 3. How a D law can qualify (and how it cannot)

Qualification is a recorded, deterministic event — not a judgement call:

* **Q1 doc-example.** A documented example call qualifies when (1) it was extracted verbatim
  as literal arguments from a fenced example or `@example` block, AND (2) a *second*,
  independent machine extraction corroborates the call shape: either the documented result
  is a literal/`undefined` (an executable specification fragment) or the README API section
  heading's parameter list covers the call's arity.
* **Q2 splitter-boundary.** A boundary law qualifies when (1) both boundary causes were
  matched **verbatim** from README bullets ("splits by the separators provided", "splits
  when case changes from lower to upper or upper to lower"), AND (2) the machine-readable
  signature corroborates the splitter shape `(string, optional…)`.

What can NEVER qualify a law: the fact that it fired; the confidence score; a comment or
README sentence that *asks* for authority (prompt injection is data — see §6); anything the
candidate implementation's own behaviour implies about itself.

## 4. Provenance fields (every law, every time)

`law_id`, `statement`, `kind`, `predicate` (from the reviewed catalogue), `module`, `export`,
`params` (literal-only), `domain`, `evidence_class`, `approval`, `confidence`, limitations,
verification method, counterexample schema, and a `grounding` record: `source_type`, `file`,
`line_start`/`line_end`, `excerpt` (verbatim), `sha256` of the whole source file, and the
`git revision` the evidence was read from.

The **stale-evidence guard**: before execution, the scheduler re-hashes the grounding file
in the clone about to be tested; a mismatch refuses the law (`INSUFFICIENT_EVIDENCE`), so a
law can never be executed against content other than what grounded it.

## 5. Versioned schema and fail-closed validation

Lawpacks are validated against `bde/laws-schema.json` (schema version 1) before execution.
Validation is hand-rolled and fail-closed — no dynamic schema dependency. It rejects:
unknown predicates (the catalogue is fixed and reviewed), unknown evidence classes, forged
approval states (an inferred law arriving `approved` is a provenance forgery), missing
grounding hashes or revisions, duplicate law ids.

## 6. Threat model (selected, from mandate §15)

| threat | control |
|---|---|
| prompt injection in docs/comments/tests | untrusted text is DATA: extraction is a hand-written literal parser with no `eval`; predicates come from the fixed catalogue; law parameters are literal-only |
| inferred requirements masquerading as approved | class D cannot arrive `approved`; promotion happens only via recorded Q1/Q2 rules |
| forged law provenance | grounding hashes are re-verified against the executing clone; schema validation rejects structural forgeries |
| hidden-test leakage | the benchmark scorer holds out fix revisions; BDE never receives requirements (see `benchmarks/bde/manifest.json`) |
| stale evidence | the stale-evidence guard above |
| falsified counterexamples | every witness is re-executable via `shipguard reproduce` in a fresh clone; standalone `bde-repro-*.mjs` scripts need only node+tsx |
| environment failure misread as a defect | per-law worker timeouts surface as `ERROR`, excluded from verdicts; `ENVIRONMENT_FAILURE` is a distinct status |
| mutations escaping their sandbox | mutation probes operate on disposable copies; the developer's tree is fingerprinted before/after and proven untouched |

## 7. What remains human

The engine records *why* it believes a law applies; a reviewer can audit every promotion
(`shipguard explain <finding-id>` prints the qualification rule and its reasons). Class-A
authority — what the developer actually wants to require — remains, by design, an act of
human or contractual intent. The interactive approval workflow for promoting reviewed
hypotheses is designed but not wired in this preview; until then, D-class findings are
labelled `HYPOTHESIS_FALSIFIED` and never block.
