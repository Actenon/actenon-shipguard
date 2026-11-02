# Actenon ShipGuard v0.2.0 — cross-run comparison

Generated from the per-run artifacts by `benchmark/harness.py compare`. Frozen corpus: `BENCHMARK-MANIFEST-v0.2.0.json` sha256 `a380a1b7f30756d5af3026a94ec3f33f996d888f6819e048341ab0465c36d6cc`.

## Runs compared

| run | artifact | status | window | agent availability |
|---|---|---|---|---|
| `claude` | `BENCHMARK-RESULTS-v0.2.0.json` | 12 cells recorded | 2026-11-02T13:43:39.012699Z → 2026-11-02T13:53:04.739819Z | claude CLI present, authenticated, and live execution consented |

## Corpus identity

All runs used the same frozen manifest: **True**.
- `claude`: manifest sha256 `a380a1b7f30756d5af3026a9…` — the Claude run predates run-time corpus-integrity checking, so its identity rests on the manifest hash alone

## Headline numbers

| metric | `claude` |
|---|---|
| sessions (arms A/B) | 6 |
| agent produced a change | 6 |
| independently VERIFIED | 6 |
| arm A false accepts | 0 |
| arm B false accepts | 0 |
| aspirin instances (green tests + real defect) | 0 |
| provider unavailable sessions | 0 |
| arm C verified | 6 |
| arm C verified AFTER a repair | 0 |
| committed tree byte-identical | 6 |
| arm C agent seconds | 250.76 |
| arm C verification seconds | 31.85 |

## Per-task outcome

| task | `claude` verdict / correct |
|---|---|
| `scule-custom-separator-split` | VERIFIED / True |
| `ufo-withoutbase-leading-slashes` | VERIFIED / True |
| `ufo-false-prefix-match` | VERIFIED / True |
| `scule-splitbycase-numbers` | VERIFIED / True |
| `ufo-parsefilename-optional-opts` | VERIFIED / True |
| `entities-legacy-attribute-interrupted` | VERIFIED / True |

## Why these runs are NOT directly comparable

Stated explicitly, as authorised, so the table above is not read as a model bake-off:

- **Different models.** Each run used a different coding agent, with different training, different default reasoning effort and different tool-confinement mechanisms (Codex: `--sandbox workspace-write`; Claude: `acceptEdits` plus a file-only tool allowlist). A difference in outcome is not attributable to the model alone.
- **Different execution dates.** The runs are days apart. Both providers are hosted services that can change underneath us; neither run pins a model snapshot, only a CLI version.
- **Different environments.** Different working directories, different machine load, and a different provider quota state. The oracle, corpus, contracts and prompts are identical; the execution context is not.
- **Sampling.** One session per task per arm. There is no repetition, so no variance estimate and no confidence interval. A single correct or incorrect outcome per task is an observation, not a rate.
- **Ceiling effect.** If both agents solve all six tasks, the corpus cannot discriminate between them, and 'both scored 6/6' carries no information about which is better. That is a property of the corpus, not a finding about the models.

## What a comparison here can and cannot support

Can support: whether the pipeline reproduced its verification behaviour across two different live providers on the same frozen corpus; whether either provider produced a defect that the ordinary tests missed; whether either needed a counterexample-driven repair.

Cannot support: any claim that one model is better than the other, any detection or repair rate, any reliability improvement, or any generalisation beyond these six tasks.

## Next evaluation (separate, prospectively frozen)

A larger corpus across more repositories must be selected, validated and frozen **before** any agent runs on it, under its own manifest name, and must not be built by extending this one after seeing these results. The measured constraints that shaped this corpus are recorded in `selection_process.measured_corpus_constraints` and apply unchanged: the pinned oracle runs its own vitest over every `*.test.*` file with zero installs, probes call one exported function with JSON arguments, and its mandatory `preserved-tests` replay means a correct fix that alters an existing assertion can never be VERIFIED.

