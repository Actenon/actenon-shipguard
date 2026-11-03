# Actenon ShipGuard v0.2.0 — real-world benchmark report

Generated from `BENCHMARK-MANIFEST-v0.2.0.json` (sha256 `a380a1b7f30756d5af3026a94ec3f33f996d888f6819e048341ab0465c36d6cc`) and `BENCHMARK-RESULTS-v0.2.0.json` by `benchmark/harness.py report claude`. Every number below is read from those artifacts; none is transcribed by hand.

- Run window: 2026-11-02T13:43:39.012699Z → 2026-11-02T13:53:04.739819Z
- Harness that RAN this benchmark: `benchmark/harness.py` sha256 `af6c49d6f938d5851805271d2ddd9c7697382eecf54a3fbf047a79cd39976157` at git `9bbe0f76a7cba467fad75763484bd23b96b5c6d1` (repo dirty=True — the release-evidence document was being edited while the run executed; the harness file itself was committed)
- Harness that VALIDATED and froze the corpus: `benchmark/harness.py` sha256 `77e282682ff2d405c38f3e8eeebd7d56a8a354279e30ee51257434fdbe5d4b21` at git `b97cc9914d9f84f89f920586a3ef786a77d608ba` (dirty=False)
- Independent oracle: sentinel-verified pinned at `becba502c8dbebdd5e52b8ca09122f86e4e37bb3`, runner `local (advisory, same OS account — not a security boundary)`, vitest 5.0.5
- Agent that actually ran: **claude** (mode `live`, availability probe: claude CLI present, authenticated, and live execution consented)
  - The manifest planned `codex`. That provider was authenticated but its usage limit was exhausted (recorded as `unavailable`, never as a repair failure), so the run used `claude`. The corpus, prompts, contracts and oracle are byte-identical to the freeze; only the model differs, and that is disclosed here rather than buried.
- Agent confinement: sandbox/permission controls per the adapter (no --dangerously-skip-permissions; no bypass flag); no permission-bypass flag is used by any adapter
- Python 3.14.6; dependencies supplied by `sibling pinned sentinel-verified checkout` — no benchmark-time install

## 0. Bottom line

**The live agent solved all 6 frozen tasks correctly on its first attempt.** The independent oracle VERIFIED 6 of 6; the projects' own test suites agreed on every one, so arm A falsely accepted 0 change(s) and arm B falsely accepted 0.

Consequently **no aspirin instance occurred and no counterexample-driven repair was exercised**: there was no case where ordinary tests were green while an independently established requirement was violated, so there was nothing for ShipGuard to catch and nothing to feed back. This is the measured outcome. The corpus was not expanded, no task was weakened, no requirement was hidden, and no prewritten or scripted candidate was substituted to manufacture a repair demonstration.

What the run *does* establish: on six real historical defects in three independently maintained projects, the full pipeline worked end to end against a live model — 6 of 6 arm-C candidates were independently VERIFIED and every committed tree was proven byte-identical to the verified candidate (tree binding equivalent on 6 of 6), with all changes confined to their allowed file. That is a verification result, not a detection or repair result, and it is reported as such.

## 1. Question asked

Establish whether ShipGuard catches and repairs real coding-agent defects across independent real-world tasks.

This report answers a narrower, measurable version of that question: across a frozen corpus of real historical defects in real permissively-licensed projects, how often did a live coding agent produce a change that the project's own tests accepted while an independently established requirement was still violated — and did ShipGuard's counterexample feedback produce a genuine repair when that happened?

## 2. Corpus

6 tasks across 3 projects: `entities`, `scule`, `ufo`.

| task | project | licence | upstream fix | baseline | kind | criteria source |
|---|---|---|---|---|---|---|
| `scule-custom-separator-split` | scule | MIT | `57cfd15` fix(isUppercase): assume characters lowercase by default (#71) | `57cfd15^` | historical-defect | upstream test/scule.test.ts at 57cfd15 |
| `ufo-withoutbase-leading-slashes` | ufo | MIT | `5cd9e67` fix(withoutBase): collapse leading slashes (#335) | `5cd9e67^` | historical-defect | upstream test/base.test.ts at 5cd9e67 |
| `ufo-false-prefix-match` | ufo | MIT | `eb29945` fix(withBase, withoutBase): prevent false prefix matches (#313) | `eb29945^` | historical-defect | upstream test/base.test.ts at eb29945 |
| `scule-splitbycase-numbers` | scule | MIT | `9927800` fix: ignore case changes for numbers | `9927800^` | historical-defect | upstream test/scule.test.ts at 9927800 |
| `ufo-parsefilename-optional-opts` | ufo | MIT | `7959de5` fix(parseFilename): use optional chaining to access `opts.strict` (#284) | `7959de5^` | historical-defect | upstream test/parse.test.ts at 7959de5 (the added one-argument case), plus two further one-argument inputs exercising the same documented rule, disclosed here rather than hidden |
| `entities-legacy-attribute-interrupted` | entities | BSD-2-Clause | `cec1fd8` fix(decode): fix legacy entities in attributes regression (#2213) | `cec1fd8^` | historical-defect | upstream src/decode.spec.ts at cec1fd8 — the fix added 42 lines and removed none, so every expected value below is an assertion the project itself introduced, measured by executing the real code at both revisions |

Every task's baseline is the parent of a real upstream fix commit, so the defect is the project's own historical defect rather than one written for this benchmark. Acceptance criteria are assertions from the project's own test suite at that fix commit, and every expected value was measured by executing the real code at both revisions.

### 2.1 Pre-freeze gate (measured before any agent ran)

| task | baseline verdict | fix verdict | tests @baseline | tests @fix | tests @fix-src-only | valid |
|---|---|---|---|---|---|---|
| `scule-custom-separator-split` | CONTRADICTED | VERIFIED | True | True | True | **True** |
| `ufo-withoutbase-leading-slashes` | CONTRADICTED | VERIFIED | True | True | True | **True** |
| `ufo-false-prefix-match` | CONTRADICTED | VERIFIED | True | True | True | **True** |
| `scule-splitbycase-numbers` | CONTRADICTED | VERIFIED | True | True | True | **True** |
| `ufo-parsefilename-optional-opts` | CONTRADICTED | VERIFIED | True | True | True | **True** |
| `entities-legacy-attribute-interrupted` | CONTRADICTED | VERIFIED | True | True | True | **True** |

Condition 5 (`fix-src-only`) applies the upstream source change alone to the frozen baseline, leaving the baseline's own test files untouched. It proves two things at once: the project's suite cannot see the defect, and a correct repair does not turn that suite red — which is what makes arm A's decision rule fair. Sentinel enforces the same property independently through its mandatory `preserved-tests` check.

### 2.2 What was excluded, and why

The corpus is smaller than the 12-20 tasks originally requested. The mandate asked for roughly 12-20 tasks across at least three projects. This corpus is 6 tasks across 3 projects (scule 2, ufo 3, entities 1). It is smaller than requested because the measured constraints above are restrictive and no task was admitted that failed the pre-freeze gate; the excluded candidates are listed with reasons so the shortfall cannot be confused with cherry-picking. The corpus was NOT expanded after seeing any agent result.

Candidates rejected during selection, each with the measured reason:

- **camelcase** — vetted and suitable but excluded for scope: ~150 lines of subtle Unicode regex logic, too large to prepare and validate reliably here
- **pretty-bytes/parse-ms/titleize/escape-string-regexp/indent-string/strip-ansi/plur/to-milliseconds/is-fullwidth-code-point** — test scripts require ava (extra devDependencies) — excluded to keep the ordinary-test signal dependency-free
- **ms** — TypeScript + jest with 11 devDependencies — excluded for install weight
- **pathe** — MIT, pure path functions and good fix history, but EXCLUDED after direct measurement: at every revision that carries a usable fix (7534c0c, e78663c, 1492827) src/_path.ts imports `zeptomatch`, which the project declares only as a devDependency, so the whole suite fails to collect (`Cannot find package 'zeptomatch'`) under the pinned zero-install node_modules. Only HEAD is green, because the glob import was later moved into src/_glob.ts — and HEAD has no unfixed defect to benchmark. An earlier attempt also hit a different failure: at the older revisions the source layout differs from HEAD, so the probed module did not exist in Sentinel's baseline snapshot (ENVIRONMENT FAILURE / ERR_MODULE_NOT_FOUND). Excluded rather than patched, to keep each task's module path and dependency set faithful to its revision
- **destr** — MIT, zero deps, and `destr(str)` is an ideal pure probe target with three real defect fixes (639a5df surrounding whitespace, f9c78d4 escape-char fast path, d9ba16d decimals/scientific notation). EXCLUDED after direct measurement: at all three revisions and their parents the suite fails to collect under the pinned vitest 5.0.5 (destr was on vitest ^0.34 then), while at HEAD — where the suite is green — the history contains no behavioural fix, only dependency churn
- **bytes** — clone/package metadata did not expose a usable test script
- **defu** — MIT + vitest and a genuine prototype-pollution fix (3942bfb) were found, but the task was DROPPED at the pre-freeze gate because the defect cannot be expressed in Sentinel's contract format. Measured directly: Sentinel parses the approved contract with a schema validator that reconstructs each object, so an own `__proto__` data property in a case argument is normalised away — the contract written to disk contains `{"__proto__":{"isAdmin":true}}` while the receipt's stored contract object contains `{}`. The malicious input therefore never reaches defu, the check passed for the wrong reason, and ShipGuard's own integrity layer correctly refused the receipt ('receipt contract does not deep-equal the approved contract'). defu's other real hardening fix (11ba022) needs `Object.prototype` mutation, which a pure JSON-argument probe also cannot express. Excluded rather than re-expressed as an artificial requirement
- **jsonrepair** — ISC licence, zero runtime deps, pure `jsonrepair(str) -> str`, and two ideal add-only defect fixes were found and measured (ca329f7 zero-width spaces, 8d1754c trailing-comma strips the parent's comma). EXCLUDED after direct measurement: Sentinel does NOT run the project's test script — src/verifier.ts writes its own vitest config (include `**/*.{test,spec}.{js,ts,...}`) and runs vitest itself, so jsonrepair's test-lib/cli.test.js is always collected. That file spawns the built CLI from lib/, which does not exist without a build step, so Sentinel's mandatory baseline-tests/candidate-tests/preserved-tests checks were CONTRADICTED at BOTH the baseline and the upstream fix. Narrowing the package.json test script cannot help, because Sentinel ignores it. Deleting or editing that test file to make the oracle pass is exactly what the mandate forbids, so the project was dropped
- **ohash** — MIT + vitest and a clean pure `diff(a, b)` defect (a5004f7, falsy primitives) were found and the criteria were measured, but the task was DROPPED at the pre-freeze gate for the same structural reason as jsonrepair: Sentinel runs its own vitest over every `*.test.*` file, and ohash's test/serialize.test.ts, test/hash.test.ts and test/bundle.test.ts import through src/index.ts, which self-references the `ohash/crypto` subpath export that only resolves against built output. Those three files fail to collect with zero installs, so Sentinel's mandatory ordinary-test checks were CONTRADICTED at both the baseline and the fix
- **hookable** — MIT + vitest and green with zero installs, but the API is `createHooks()` returning a stateful registry, not a single pure exported function that a JSON-argument probe can call
- **exsolve** — MIT + vitest and green with zero installs, but the exported resolvers return absolute filesystem paths, so the oracle's expected values would be machine-specific rather than portable
- **confbox** — MIT + vitest, but 1 test file fails to collect under the pinned vitest with zero installs
- **untyped** — MIT + vitest, but all 6 test files fail to collect under the pinned vitest with zero installs
- **remeda** — MIT + vitest, but package.json declares no license/test fields at the surveyed revision and the repo is large; excluded for vetting cost
- **es-toolkit** — MIT + vitest with many suitable single-function fixes, but `vitest run` executes the whole multi-thousand-test suite (including coverage) per attempt; excluded to keep the ordinary-test signal fast enough to run once per arm per task
- **radix3** — MIT + vitest, but the pinned vitest run reported 7 collection errors without the project's own devDependencies, and the router API needs a constructed router rather than a single pure exported function
- **mlly** — MIT, but the pinned vitest collected no tests without the project's own vitest configuration/devDependencies
- **marked** — MIT and zero runtime deps, but the project does not use vitest (all 6 test files fail to collect under the pinned vitest)
- **smol-toml** — BSD-3-Clause and zero runtime deps, but all 11 test files fail to collect under the pinned vitest with zero installs

Individual tasks dropped after the project was accepted:

- **914e397 fix(escape): escape `<` and `>` in attribute values (#2398)** — A genuinely security-relevant defect — `escapeAttribute` left `<`/`>` unescaped, so '<img src=x onerror=alert(1)>' survived escaping — and the criteria were measured. DROPPED because the upstream fix also CHANGED an existing assertion (escape.spec.ts expected '<a &quot; attr > ...' and now expects '&lt;a &quot; attr &gt; ...'). Gate condition 5 measured the consequence: applying only the source fix to the frozen baseline makes the baseline's own suite fail, so arm A would reject a correct repair
- **05af0b3 fix(decode): skip Windows-1252 C1 remap for XML numeric references (#2347)** — DROPPED for the same measured reason: src/index.spec.ts changed an existing astralSpecial expectation from '\u{20AC}' to '\u{80}'
- **00913aa / d97b64f (streaming decode fixes)** — Purely additive tests and green suites, but the behaviour lives behind the stateful `EntityDecoder` class (startEntity/write/end), which a single-call JSON-argument probe cannot exercise

Tasks dropped by the pre-freeze gate:

- **scule-segment-lowering (3815767)** — DROPPED by pre-freeze gate condition 5, measured: applying only the upstream source fix to the frozen baseline makes the baseline's OWN suite fail — test/scule.test.ts asserted `pascalCase('FooBARb') === 'FooBARb'` and the fix changes that expectation to 'FooBaRb'. A correct repair would therefore turn arm A's ordinary tests red, and the mandate forbids counting an initially correct solution as a failure. This is a documented behaviour change, not a defect invisible to the project's tests
- **ufo-trailing-slash-in-query (6cd1fcd) and ufo-parseurl-protocol-case (768210a)** — Criteria were measured and both are real defects with clean discriminators, but at those 2023/2024 revisions ufo's suite does not run under the pinned vitest 5.0.5, so Sentinel's mandatory ordinary-test checks reported ENVIRONMENT FAILURE at both baseline and fix. ufo revisions from 2025 onward (13 test files) are green, so the ufo tasks were re-selected from that window

Measured constraints that shaped the corpus:

- Sentinel executes the ordinary tests itself, with its OWN vitest configuration (src/verifier.ts writes include `**/*.{test,spec}.{js,ts,mjs,cjs,mts,cts,jsx,tsx}`, environment node, testTimeout 5000, maxWorkers 1) using the pinned installation's vitest 5.0.5, and it ignores the project's `test` script and vitest config. So every file matching that glob must pass at the baseline revision with zero installs; a project needing a build step or an undeclared runtime dependency cannot be benchmarked at all. This biases the corpus toward recent revisions and is the single largest reason candidates were dropped (jsonrepair, ohash, pathe, destr).
- Sentinel probes call ONE exported function with JSON arguments and compare a JSON-serialisable return, so criteria must be expressible that way. Own `__proto__` keys are normalised away by contract parsing, and `undefined`/`Infinity` returns are not representable, so such cases were excluded from the criteria. `approvedBy` is capped at 200 characters by Sentinel's schema (measured: exit 2 with a zod `too_big` error), so the contract carries a short provenance string and the full provenance stays in this manifest.
- STRUCTURAL FINDING: Sentinel always records a mandatory `preserved-tests` check, which restores the BASELINE's test and control files into a third copy and runs them against the candidate source. A change that alters any behaviour asserted by an existing test therefore can never be VERIFIED, however correct it is. ShipGuard's gate condition 5 measures the same property independently. The corpus is consequently restricted to fixes whose upstream commit ADDS assertions without changing existing ones — which is also exactly the condition that makes arm A's 'ordinary tests only' decision rule fair. Behaviour-change tasks (entities 914e397 and 05af0b3, scule 3815767) are outside what this verifier can accept, and are recorded as dropped rather than forced through.

Disclosure: Some requirement cases are NOT verbatim upstream assertions but additional inputs exercising the same documented rule, so that a task whose upstream fix added only one or two discriminating assertions cannot be satisfied by special-casing those inputs. They are named in the affected task's criteria_source: ufo-parsefilename-optional-opts adds two further one-argument inputs ('/path/to/.hidden-file', 'https://example.com/a/b.tar.gz') plus explicit-opts preserves. Every expected value was measured by executing the real code at the fix revision, never transcribed by hand. Nothing essential is withheld from any prompt and no extra requirement is imposed.

## 3. Arms

- **Arm A** — ordinary Codex + the project's own tests only (no independent verification)
- **Arm B** — same Codex configuration + independent Sentinel verification, no automatic repair
- **Arm C** — same Codex configuration + ShipGuard bounded counterexample-driven repair

Arms A and B are evaluated on ONE shared agent session per task, recorded as arm 'AB'. Arm B adds only a verification GATE and gives the agent no feedback, so by construction the agent's behaviour in A and B is identical; running two sessions would double the cost and add independent sampling noise to a comparison that is meant to be paired. Each AB record therefore carries both decision rules — arm_A_decision (accept iff the project's own tests pass) and arm_B_decision (accept iff the independent oracle verifies) — applied to the same measured output, plus ground_truth_correct from the oracle. Arm C is a separate session because it feeds counterexamples back to the agent.

## 4. Results

### 4.1 Arms A/B — one shared agent session per task, two decision rules

| task | agent outcome | files changed | diff lines | ordinary tests | independent verdict | arm A decision | arm B decision | actually correct |
|---|---|---|---|---|---|---|---|---|
| `scule-custom-separator-split` | completed | 1 | 13 | True | VERIFIED | accept | accept | True |
| `ufo-withoutbase-leading-slashes` | completed | 1 | 14 | True | VERIFIED | accept | accept | True |
| `ufo-false-prefix-match` | completed | 1 | 37 | True | VERIFIED | accept | accept | True |
| `scule-splitbycase-numbers` | completed | 1 | 33 | True | VERIFIED | accept | accept | True |
| `ufo-parsefilename-optional-opts` | completed | 1 | 19 | True | VERIFIED | accept | accept | True |
| `entities-legacy-attribute-interrupted` | completed | 1 | 72 | True | VERIFIED | accept | accept | True |

### 4.2 Arm C — ShipGuard bounded counterexample-driven repair

| task | attempts | agent outcomes | ordinary tests | verdicts | final status | repair attempts used | tree binding | agent s | verify s |
|---|---|---|---|---|---|---|---|---|---|
| `scule-custom-separator-split` | 1 | completed | True | VERIFIED | verified | 0 | True | 38.83 | 2.42 |
| `ufo-withoutbase-leading-slashes` | 1 | completed | True | VERIFIED | verified | 0 | True | 42.49 | 6.37 |
| `ufo-false-prefix-match` | 1 | completed | True | VERIFIED | verified | 0 | True | 22.78 | 6.6 |
| `scule-splitbycase-numbers` | 1 | completed | True | VERIFIED | verified | 0 | True | 42.81 | 2.41 |
| `ufo-parsefilename-optional-opts` | 1 | completed | True | VERIFIED | verified | 0 | True | 23.54 | 6.64 |
| `entities-legacy-attribute-interrupted` | 1 | completed | True | VERIFIED | verified | 0 | True | 80.31 | 7.41 |

### 4.3 Aggregate

```json
{
  "arm_AB": {
    "agent_made_a_change": 6,
    "arm_A_accepted": {
      "count": 6,
      "n": 6,
      "rate": 1.0
    },
    "arm_A_false_accepts": 0,
    "arm_B_accepted": {
      "count": 6,
      "n": 6,
      "rate": 1.0
    },
    "arm_B_false_accepts": 0,
    "defects_invisible_to_ordinary_tests": 0,
    "false_accept_task_ids": [],
    "independently_correct": 6,
    "ordinarily_green": 6,
    "provider_unavailable": 0,
    "sessions": 6
  },
  "arm_C": {
    "agent_seconds_total": 250.76,
    "aspirin_on_first_attempt": 0,
    "contradicted_after_budget": 0,
    "repaired_task_ids": [],
    "sessions": 6,
    "statuses": [
      "verified"
    ],
    "tree_binding_equivalent": 6,
    "verification_seconds_total": 31.85,
    "verified": 6,
    "verified_after_repair": 0
  },
  "projects": [
    "entities",
    "scule",
    "ufo"
  ],
  "tasks_in_corpus": 6
}
```

## 5. The aspirin instances

**No aspirin instance occurred in arms A/B.** Across the frozen corpus the agent never produced a change that the project's own tests accepted while the independent oracle contradicted it. That is a real result, not a missing one: it means the ordinary-test signal was sufficient on these tasks, and it is reported without expanding the corpus to manufacture a demonstration.

## 6. Live repair evidence

**No natural live-agent repair occurred.** Either the agent's first attempt was already verified, or no contradiction arose to feed back. Per the mandate this is reported as the outcome; the corpus was not expanded and no prewritten candidate was substituted to produce a demonstration.

## 7. What this benchmark does and does not establish

Established by measurement:

- A frozen corpus of 6 real historical defects across 3 independently maintained projects, each validated in both directions (baseline contradicted, upstream fix verified) before any agent ran.
- On 0 of 6 arms-A/B sessions the project's own tests were green while the independent oracle contradicted the agent's change.
- Arm A (tests only) would have falsely accepted 0 change(s); arm B (independent verification) falsely accepted 0.
- Arm C reached `verified` on 6 of 6 tasks, of which 0 required at least one repair attempt.

NOT established:

- No statistical reliability claim. The corpus is small and was not sampled from a population of real agent tasks; rates are descriptive counts, not estimates with confidence intervals.
- No comparison against a second coding agent. This run used **claude** only. Codex CLI was authenticated but its usage limit was exhausted until 2026-11-08, so no cross-model comparison was possible; that state was recorded as provider `unavailable`, never as an agent failure. A single model on a small corpus cannot support any claim about coding agents in general.
- No hostile-agent containment claim. The runner is `local-advisory` under the same OS account, which Sentinel itself states is not a security boundary.
- No claim about tasks whose correct fix changes an existing assertion. Sentinel's mandatory `preserved-tests` check makes such changes unverifiable by construction, so that whole class is out of scope — see §2.2.
- No general correctness claim, and no stable v1.0.0.

## 8. Reproduction

```sh
# 1. pinned independent oracle (Sentinel is not on npm; build the exact commit)
git clone https://github.com/rossbuckley1990-hash/sentinel-verified.git
cd sentinel-verified && git checkout becba502c8dbebdd5e52b8ca09122f86e4e37bb3 && npm ci && npm run build && cd ..
export SHIPGUARD_SENTINEL=$PWD/sentinel-verified/dist/cli.js
export SHIPGUARD_TSX=$PWD/sentinel-verified/node_modules/.bin/tsx
export SHIPGUARD_NODE_MODULES=$PWD/sentinel-verified/node_modules

# 2. ShipGuard's own suite — 128 passed, 0 skipped (all three vars above are required,
#    otherwise the sentinel_integration tests skip and CI fails the run for it)
pip install -e '.[dev]'
pytest -q -rs

# 3. re-validate the corpus against the frozen gate, then re-freeze
python benchmark/harness.py validate
python benchmark/harness.py freeze   # refuses to write unless every task passes all 5 conditions

# 4. run the arms with a LIVE agent — the harness probes the provider first and refuses to
#    run at all if it is missing, unauthenticated or quota-exhausted
claude -p 'Reply with the single word OK.'   # or: codex login status
SHIPGUARD_ENABLE_LIVE_CLAUDE=1 python benchmark/harness.py run --agent claude
# python benchmark/harness.py run --agent codex   # when that provider's quota is available

# 5. regenerate this document from the artifacts
python benchmark/harness.py report
```

Agent runs are not bit-reproducible: a live model is queried once per session. Everything else — corpus selection, contracts, validation, aggregation and this document — is deterministic from the pinned commits.

