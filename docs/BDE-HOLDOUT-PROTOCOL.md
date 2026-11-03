# Preregistered independent evaluation protocol — ENGINE FROZEN / TASKS NOT YET SELECTED

Engine 137a68005dc85c765fbd02280268f539a6131001 is frozen after green remote CI.
The adjacent engine-freeze.json commits source, wheel and runtime identities.
No holdout targets have been selected at registration. This protocol is not a result.

## Custody and freeze

1. Resolve the demonstrated authority, reproduction and repair-contract defects.
   Run all mandatory tests, packaged execution and containment controls. Preserve
   existing negative controls and every original failing case.
2. Create a signed or independently witnessed freeze record containing the engine
   commit, clean-tree status, source-tree SHA-256, wheel SHA-256, JS lockfile,
   runtime/container digest, evaluator/harness hash, policy configuration and
   model configuration. Record the freeze time before any new target selection.
3. A separate evaluator selects tasks in a separate account or container volume.
   Labels, fix revisions, upstream regression tests and hidden inputs never enter
   the developer-agent filesystem or BDE's mounts. A separate directory under
   the same unrestricted account is insufficient. Test access denial explicitly.
4. Give each developer run a source snapshot with only its baseline files and
   existing tests. Initialise a new single-commit Git repository; do not include
   upstream history, remotes, branches, benchmark names or future fix metadata.
   Bind opaque IDs to private provenance in the evaluator store.
5. Commit hashes of the private task manifest and oracle bundle before execution.
   Reveal results only after all frozen runs and independent scoring finish.
   Any discovery-algorithm change creates a new version and requires fresh unseen
   tasks for a new blind claim; the first evaluation stays published as measured.

## Selection and eligibility

Select at least **20 new real historical JS/TS defects across five behaviour
families**, from independently sourced repositories. Exclude all previously used
or surveyed ShipGuard targets from the independent claim, not just the six admitted
legacy tasks. The existing v0.2.0 manifest lists the surveyed repositories.

Use a precommitted, mechanically reproducible sampling rule within the evaluator's
candidate list. Record all candidates, exclusions and ordering. Confirm public
issue/commit provenance independently of BDE. No inclusion criterion may depend
on BDE detecting the defect. Document licensing and build requirements.

For every eligible defect, the original baseline tests must pass under a faithful,
pinned environment; the private oracle must fail on the baseline and pass with the
upstream source repair. Preserve baseline tests unchanged when testing the repair.
Record build/lint/typecheck separately if they are outside the declared test scope.
Environment failures are reported rather than fixed by deleting tests or replacing
the project's testing tool with an incompatible shared version.

Avoid equating “fixed this defect” with “globally valid”. Record unrelated findings
on both revisions. Include independently adjudicated clean/negative tasks to measure
false alarms; target at least one negative control per defect. Categories may include
parsing/serialization, numeric calculations, collections, paths/URLs and stateful or
asynchronous behaviour. Unsupported categories remain in coverage accounting.

## Matched arms

| Arm | Available product support |
|---|---|
| A | Real Codex with normal code inspection and testing abilities |
| B | Same Codex plus Sentinel with independently approved, supported criteria |
| C | Same Codex plus frozen BDE discovery; no test disclosing the target defect |
| D | Same Codex plus BDE, separate ground-truth verification and applicable ShipGuard protected execution |

Keep initial snapshots, neutral task prompts, exact model/effort, general tools and
time/token budgets identical. Product-specific affordances are the treatment.
Randomise arm ordering per task with a committed seed. Record unsupported Sentinel
contracts or protected operations as unsupported; do not quietly exclude those tasks.
Disclose any information advantage from approved criteria in B.

Resource ceiling: 300 seconds of agent wall time per task/arm, at most two
agent invocations. All arms use Codex 0.163.0, gpt-6-astra, xhigh effort and the
same offline tool/permission profile. No hard token cap is claimed: the CLI
reports actual usage at turn completion, so tokens are measured. Product
preprocessing and independent grading time are recorded separately and included
in end-to-end cost. Arm order uses seed 20261103. The same final candidate-sealing
and grading procedure applies to every arm.
Capture complete structured events, prompts, tool calls, model identity, timestamps,
usage and exit status. Preserve first-attempt successes as successes. Do not choose
bad attempts to manufacture a repair story.

The neutral task must not name the historical defect or reveal hidden inputs.
In C/D, actual frozen BDE findings and witnesses may drive repairs. The agent may
write its own tests but cannot modify original tests, hidden tests, evaluator
criteria, the BDE distribution or approval records. Violations invalidate that run.

## Independent verification and metrics

After each candidate is sealed, the evaluator verifies source identity and applies
the original tests and separately controlled oracle. The developer agent does not
grade itself. BDE laws are proposals; a reviewer or external contract grants any
execution authority. Exact witness reproduction is distinct from repair verification.

Record per task and per arm:

- Exact repository/commit and provenance in the private manifest; source and
  dependency hashes in public opaque-ID records.
- Baseline commands, results, test counts, skipped tests and environment failures.
- Every discovered law, its authority, applicability and execution status.
- Raw finding rows plus deduplicated commit/export/input/predicate identities;
  exact-witness reproduction, label and adjudicator rationale.
- True target defects, auxiliary code defects, documentation inconsistencies,
  invalid laws, unresolved findings, misses, unsupported cases and failures.
- Candidate patch and hash; first-attempt and final independent outcomes.
- Detection latency, total wall/CPU time, peak memory, tokens, actual or explicitly
  unavailable cost, and measured developer adjudication time.

Primary comparisons are paired detection and repair outcomes on the same tasks.
Report both intention-to-evaluate denominators (all sampled eligible tasks) and
supported-task rates, with uncertainty and repository/family stratification.
False approval means a gate accepts an independently failing candidate. False
alarm means an asserted mandatory defect is independently adjudicated invalid.
Report a false-discovery fraction separately from the false-positive rate on
negative opportunities. Unresolved labels stay visible and get sensitivity bounds.
Do not calculate a zero rate by excluding everything that received a convenient label.

## Protected execution and containment

Run a separate, deterministic refusal matrix: invalid proof, changed source,
changed operation parameters, unauthorised actor, wrong action/resource, expired
authority and replayed nonce. Preserve both allowed controls and refused attempts.
Do not combine security refusals with behavioural detection statistics.

The untrusted-code runner must use no network by default; no host credentials,
Docker socket or evaluator mounts; a non-root UID; dropped capabilities;
no-new-privileges; read-only engine/source mounts; bounded writable tmpfs; and
process, memory, CPU, wall-time and output limits. An external supervisor must kill
the entire process tree and cap captured output. Test each restriction with negative
probes, including a child process that outlives its parent, memory exhaustion,
output flooding, network attempts and writes to protected paths. Missing containment
must fail closed, including reproduction and mutation paths.

These controls reduce host exposure. They do not make software verification an
unbypassable security boundary or prove immunity from a container-runtime exploit.

## Developer journey and decision

Choose the final real-project journey from the already completed evaluation using
a precommitted rule (for example, first qualifying task in selection order). Preserve
its passing baseline tests, actual grounded discovery, exact witness, real Codex
trace, candidate patch, original-test results, independent oracle result, source
identity and any applicable gate receipt. If no task qualifies, record
**NOT ESTABLISHED** rather than constructing a substitute demonstration.

GO requires credible incremental value and satisfied assurance controls, not a
predetermined demonstration score. Any false approval caused by invalid authority,
oracle leakage, unauthorised law promotion or failed containment is a blocker.
Report uncertainty, costs and review burden even when detection improves. A small
sample can justify continued research without establishing production readiness.

## Registered execution details

A separate evaluator chooses a candidate inventory using public upstream repair
provenance after this engine freeze. It commits the inventory hash and selection
order before BDE execution, then admits the first four eligible historical defects
in each of at least five behaviour strata. All eligibility failures remain in the
manifest. Exclude the 33 previously surveyed packages listed in the legacy manifest.
No selection or replacement depends on BDE output. Pair each admitted baseline with
its source-only upstream repair as a negative control for that target defect;
other findings on a repaired revision are adjudicated separately, never assumed false.

An independent organisation and model-training non-exposure are NOT ESTABLISHED.
A separate evaluator agent provides task/label custody; the frozen engine developer
and repair agents receive only baseline snapshots with no history or repair labels.
The evaluator's private volume is never mounted by BDE or developer containers.
Codex uses a restrictive filesystem profile, no shell network, disabled web search,
no approvals and no Docker socket; real negative probes are preserved.

The neutral task asks for grounded defect review/repair within the declared public
module scope without naming the target defect. A may use normal inspection and
testing. B additionally receives independently approved supported criteria and
Sentinel. C receives actual frozen BDE discovery artifacts. D receives the same
BDE artifacts plus independent verification and an applicable protected gate.
Unsupported B/D capabilities remain explicit, not simulated as another arm.

The first eligible successful C/D task in registered selection order is the
developer-journey candidate. If none qualifies, the journey is NOT ESTABLISHED.
Raw outputs, errors, exclusions, timeouts and successful first attempts are retained.
Infrastructure-only harness corrections will be separately versioned and disclosed;
no discovery algorithm changes are allowed for this evaluation.
