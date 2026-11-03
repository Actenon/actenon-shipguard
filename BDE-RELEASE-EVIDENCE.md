# BDE-RELEASE-EVIDENCE

**Release:** `v0.3.0-preview` (experimental) — Actenon Behavioural Discovery Engine
**Branch:** `bde-discovery-v0.3.0` (based on `v0.2.0` @ 447908c; not merged, not released)
**Scope of claim:** ShipGuard can automatically propose behavioural properties from
repository evidence and execute supported checks against real JavaScript/TypeScript code,
and it independently reproduced three specific historical defects using grounded laws and
minimal inputs.

## 1. The defining experiment (mandate §13)

Frozen corpus: the six `v0.2.0` historical-defect targets (unjs/scule, unjs/ufo,
fb55/entities), **targets only** — BDE never saw the v0.2.0 requirements, contracts,
prompts or expected outcomes. The upstream fix commit was held out for scoring.

| result | count | detail |
|---|---|---|
| **DISCOVERED** (blind) | **3/6** | scule custom-separator split (`splitByCase('a-', [])`), scule numbers (`splitByCase('a1')`), ufo parseFilename (`parseFilename('http://…')` throws TypeError) — each witness passes after the upstream fix, verified by independent re-execution |
| MISSED | 3/6 | ufo withoutBase (security property not in permitted evidence), ufo withBase (ambiguous prose), entities decodeHTMLAttribute (no machine-readable contract) — misses are published with causes, not excused |
| invalid-law false positives | **0** | fix-revision positive controls: 0 unlabelled findings |
| true auxiliary findings | 24 | genuine README/JSDoc↔code contradictions in ufo (isScriptProtocol, normalizeURL, withFragment), each audited with recorded reproduction evidence |

**Raw, as-measured output:** `benchmarks/bde/results.json`; frozen rubric and audit labels:
`benchmarks/bde/manifest.json`; narrative: `benchmarks/bde/report.md`.

## 2. Mutation sensitivity and false positives (Track B)

Known-valid subjects (the six fix revisions), 8 single-token operators, disposable copies:

* behavioural mutations: 36 · detected: **14 (38.9%)** · refactor false positives: **0**
* two subjects detect 0 — when the compiled laws are example-shaped, token flips far from
  the documented examples survive. A surviving mutation is sensitivity evidence, never a
  defect claim.

## 3. Engineering evidence

* **Tests:** 155 passed (135 pre-existing security/trust/adversarial + 20 new BDE tests).
  The v0.1.2 security regression suite is byte-identical and green — no security control
  was weakened. Adversarial BDE tests include prompt-injection resistance, forged-lawpack
  rejection, stale-grounding refusal, hung-candidate→environment-error, read-only proof,
  and mutation isolation.
* **Portability:** the umask-002 file-mode portability bug found during this work is fixed
  at point-of-use (`orchestrator.sync_file_modes_to_index`) — 5 previously
  environment-failing integration tests now pass under any umask.
* **Determinism:** seeded generation, fixed budgets, offline; no LLM inference anywhere in
  the discovery path; no network at run time.
* **Packaging:** `bde/runner.mjs` + `bde/laws-schema.json` ship in the wheel
  (package-data), `shipguard doctor` checks the law schema. CLI stays backward compatible
  (`init/demo/verify/report/run` unchanged).
* **Runtime overhead:** full `discover` on the corpus modules: 1.1–3.1 s per module
  (measured in `results.json`); `check` adds the disposable-clone cost (~1–2 s).

## 4. Known limitations (all user-visible in the product output)

1. **Discovery is evidence-bounded.** Laws exist only where the repository states behaviour
   machine-extractably (documented examples, verbatim splitter semantics, optional-arg
   signatures, the project's own tests). Security properties, ambiguous prose and deep
   parser logic are out of reach without richer evidence — the three misses are exactly this.
2. **Corpus homogeneity.** 6 tasks, 3 string/URL libraries. No claim about detection rates
   on other domains is made or implied.
3. **The signature extractor is a lexical scanner** for common exported-function shapes;
   unusual syntax is skipped and reported, never guessed.
4. **Advisory isolation only.** Law execution runs the repository's own code under the same
   OS user (same boundary as Sentinel's local runner) — consent-gated by `--allow-local`,
   stated in every report. Not a hostile-code sandbox.
5. **Doc-drift findings need human labelling.** The 24 ufo documentation contradictions are
   true findings but were classified by recorded manual audit (commands in the manifest),
   not automatically.
6. **Hypothesis laws never block.** The interactive approval workflow is designed
   (`authority.Policy`) but not wired; D-class violations are reported as
   `HYPOTHESIS_FALSIFIED` for review.
7. **Round-trip / idempotence / conservation / determinism families compile but are not
   promoted** in this preview (policy defaults).

## 5. Release gate decision

**EXPERIMENTAL PREVIEW — do not publish as a stable release.** The three blind discoveries
are real, reproducible and independently verified against upstream fixes, which is enough
to justify an experimental preview and continued investment; a 3/6 blind discovery rate on
a small homogeneous corpus, 38.9% mutation sensitivity, and unwired approval workflows do
not justify broader claims. The public statement remains exactly:

> "ShipGuard can automatically propose behavioural properties and execute supported checks
>  against real JavaScript/TypeScript changes. In a frozen 6-defect corpus it independently
>  reproduced 3 historical defects without receiving their acceptance tests."

It must not be read as: "ShipGuard automatically understands what every program should do",
"inferred properties are automatically true", or any guarantee of zero false positives,
universal bug detection, or production-grade containment.

## 6. Reproduction chain (clean environment)

```bash
git clone https://github.com/Actenon/actenon-shipguard && cd actenon-shipguard
git checkout bde-discovery-v0.3.0
python3 -m venv .venv && . .venv/bin/activate && pip install '.[dev]'
git clone https://github.com/rossbuckley1990-hash/sentinel-verified.git ../sentinel-verified
( cd ../sentinel-verified && git checkout becba502 && npm install && npm run build )
export SHIPGUARD_TSX=$PWD/../sentinel-verified/node_modules/.bin/tsx
python -m pytest -q                                   # 155 expected
python3 benchmarks/bde/harness.py                     # re-runs both tracks deterministically
```

Corpus repositories are cloned on first use from their public upstreams (MIT / BSD-2-Clause)
and pinned by the frozen fix commits; no network is needed after the first run.
