# BENCHMARK — the known-answer regression gate

_The trust warranty behind every novel-model run._ The point of this pipeline is that a physicist
with a hypothetical particle can test it against a published analysis's data — events generated,
analysis routine applied, 95% CLs verdict and the signal-over-data overlay produced — without the
tedious manual days. For a **novel** model there is no ground truth to check against; the only
transferable confidence is *"this pipeline reproduces published known answers within stated,
attributed tolerances."* This benchmark measures exactly that, and the gate guarantees no future
"fix" silently erodes it. **95% CLs exclusion, never 5σ discovery** (`.claude/rules/statistics.md`).

## What it measures (per registered case in `cases.json`)

| # | Metric | What it certifies | Engine |
|---|---|---|---|
| 1 | **A×ε residual** — driving-SR acceptance×efficiency vs the published grid | selection/pipeline fidelity (σ-independent) | `validate_cutflow.py`, or the run-local `certify_axe.py` for ins1676551 |
| 2 | **Limit recovery** — (a) driving-SR `s95` [events] vs the paper's model-independent `S95`; (b) µ₉₅-derived σ-UL vs published model-dependent UL (where published); (c) excluded/allowed verdict vs the published contour; (d) **µ₉₅ stability** vs the locked baseline (regression-vs-self, rtol 10%) | statistical-model + data-input fidelity, decoupled from A×ε | fresh `pyhf_exclude.py counting` every gate run |
| 3 | **Provenance + deliverables** — run artifacts exist and are non-empty (yoda, yields, RESULT.md, the **named overlay figure** a physicist consumes), registry σ/k pins match the run | the result traces to a real run and still carries its physicist-facing outputs | pure-python checks |

Everything is recomputed fresh into `.work/` each run — recorded artifacts are compared against,
never trusted as the score.

## Tier ladders (benchmark scoring — distinct from the cert engines' internal 15/25% tolerances)

| Tier | A×ε: driving-SR \|ratio−1\| | Limit: s95 deviation max(r,1/r)−1 |
|---|---|---|
| **Ideal** | ≤ 5% | ≤ 10% |
| **Good** (publication-grade) | ≤ 10% | ≤ 20% |
| **Acceptable** | ≤ 30% | ≤ 1.0 ("within 2×") |

Community context: MadAnalysis5/SModelS validation conventions tolerate ~10–15% on acc×eff;
fast-sim+LO carries an intrinsic ~10–20% floor (`docs/reference/limitations.md`).

## How to run

```bash
python3 scripts/run.py ravel.validation.benchmark --fast    # fast_case only (~7 s) — per-session smoke gate
python3 scripts/run.py ravel.validation.benchmark --full    # all cases (~25 s) — the milestone gate
python3 scripts/run.py ravel.validation.benchmark --case ins1458270_gluino_1000_100
```

Stdlib-only `python3` from anywhere; the helpers run inside the `rivet` conda env via subprocess
(no activation needed). Exit codes: **0** all gates hold · **1** breach or case error (reasons
printed under the row) · **2** malformed registry/usage. `results.json` is overwritten every run —
the **committed** copy is always the `--full` baseline. `--cases/--out` overrides exist for gate
self-tests (see `.work/selftest/`); they never touch the real registry. (The sibling readiness
tool `scripts/audit.py` does NOT share this overwrite-every-run behavior — it is read-only by
default (`--check`); pass `--write` to deliberately write its report, by default `local-runs/audit.md`.)

**Gate per case** (breach ⇒ exit 1): A×ε tier ≥ `required.axe_tier` · limit tier ≥
`required.limit_tier` (when set) · pipeline verdict matches published (when `gates.verdict_pipeline`)
· µ₉₅ within 10% of baseline · pyhf best-SR == registered driving SR · provenance clean · registry
self-check (transcribed numbers imply the transcribed verdict).

## Baseline — locked state as of 2026-06-09 (history below; relax only via a reviewed commit)

| Case | A×ε driving | Tier (req) | s95 obs/exp vs S95 | Limit tier (req) | µ₉₅ obs (baseline) | Cert | Notes |
|---|---|---|---|---|---|---|---|
| `ins1458270_squark_800_100` | 2jl @ 2.4% | **Ideal** | 44.6/55.6 vs 44/54 → **1.01/1.03** | **Ideal** | 0.2225 | PASS | CR-fitted bkg + k=0.862 (NLO+NNLL, 8/10 rescale) |
| `ins1676551_c1n2_300_100` | SR3L_Low @ 6.4% | **Good** | n/a (not comparable) | — (informational) | 2.1305 | PASS | counting-vs-combined gap, documented |
| `ins1458270_gluino_1000_100` | 5j @ 13.2% | **Acceptable** | 5.38/8.88 vs 5.4/8.7 → **1.00/1.02** | **Ideal** | 0.0524 | WARN | A×ε deficit = merging (improvement target); k=1.915 |
| `ins1458270_squark_merged_800_100` | 2jl @ 3.9% | **Ideal** | 44.6/55.5 → **1.01/1.03** | **Ideal** | 0.2258 | PASS | merging closes 4jt/6j deficits; k=0.855 |
| `ins1458270_gluino_merged_1000_100` | 5j @ 8.1% | **Good** | 5.40/8.95 → **1.00/1.03** | **Ideal** | 0.0550 | PASS | MLM xqcut=250 (scan-chosen); k=1.939; the merged lift |
| `conf2016054_gluino_onestep_1500_60` | — (unscorable) | — | 5.03/6.45 → **0.91/0.98** | **Ideal** | 0.2239 | n/a | drawn from a seeded survey of searches; CONF note (no HEPData) → stability-only; cert.engine `none` |
| `ins1452559_dm_axial_850_1` | — (unscorable) | — | 59.7/46.9 → **0.98/0.98** | **Ideal** | 0.3432 | n/a | seeded survey; first non-MSSM (imported DMsimp UFO); combined 7-channel; paper not on HEPData |
| `conf2016037_gluino_2step_sleptons_1400_60` | — (unscorable) | — | 4.68/3.80 → **0.92/0.95** | **Ideal** | 0.2970 | n/a | seeded survey; **registered against a run-local PATCHED routine** (verified 2-char share defect; policy note in the case + RESULT.md; upstream report pending) |
| `ins2182381_gbb_1900_1` | SR_Gbb_0l_B @ 26.5% | **Acceptable** | n/a (no model-independent S95 table) | — (informational) | 0.176940 | FAIL | **the FIRST published-likelihood (Mode A) case** (`pyhf_exclude.py likelihood`, `outputs/likelihood_{B,M,C}/`) — scored here via the counting-mode reconstruction (harness has no `pyhf_mode="likelihood"` hook yet); **registered against a run-local PATCHED routine** (upstream Rivet never shipped this routine's `.onnx` weight file — confirmed absent both locally and in `gitlab.com/hepcedar/rivet/analyses/pluginONNX/`; the removed ONNX branch is causally disjoint from the registered CC family, verified by source read; upstream report pending); axe cert-engine verdict FAIL / benchmark tier Acceptable — consistent 24–27% A×ε excess across all 3 CC regions (`fast-sim-floor`), not reviewed by the step-9 Tier-B panel |

What the baseline says, in one breath: **selection fidelity is publication-grade or better on three
of four cases** (2.4–6.4%; the gluino's 13% is the known un-merged multi-jet deficit, attributed and
gated as the improvement target), and **the limit machinery reproduces the published
per-SR limits to 1–3% on every comparable case** now that the counting inputs are the analysis's own
CR-fitted backgrounds and the σ normalization is the verified WG NLO+NNLL value. The original 1.49×
squark residual is preserved as evidence (`outputs/sr_yields.json` vs `sr_yields_fitted.json`): it
was background-INPUT fidelity, not machinery.

## Baseline history (every µ₉₅-stability re-lock maps to one registry change)

- `ins1458270_gluino_1000_100`: σ normalized to NLO+NNLL (`sigma_scale_k` 1.0 → 1.915, HEPi
  g̃g̃ with squarks decoupled, σ = 0.385 pb); µ₉₅(obs) 0.10029 → **0.05237**; A×ε and s95 unchanged.
- `ins1458270_squark_800_100` and `ins1458270_squark_merged_800_100`: counting inputs moved to the
  published CR-fitted backgrounds (arXiv:1605.03814 Table 6) with verified k = 0.862 / 0.855; s95
  recovery 1.49/1.53 → **1.013/1.030** and **1.013/1.028**; limit tier Acceptable → **Ideal**;
  µ₉₅(obs) 0.28164 → **0.22254** and 0.28333 → **0.22580**. The LO-σ limit had been mildly
  aggressive, not conservative.
- `ins1676551_c1n2_300_100`: scored as the combined 2ℓ+3ℓ counting fit; µ₉₅(obs) 2.1305 →
  **2.7123**, µ₉₅(exp) 1.06 → **0.976**, so the expected verdict matches the published expected
  contour; the single-SR mode was closer to 219 fb only by ignoring three excess-carrying channels.
- `ins1458270_gluino_merged_1000_100`: MLM-merged (xqcut = 250, scan-chosen), k = 1.939; driving-5j
  A×ε 1.132 → **1.081** (PASS at 8.1%); s95 recovery 1.000/1.029. The high-multiplicity residual is
  a hard-radiation excess, not a merging deficit.
- `conf2016054_gluino_onestep_1500_60`: the first case with no published acc×eff (`cert.engine:
  "none"`); limit accuracy from the PDF-transcribed Table 16, s95 **0.914/0.977**; µ₉₅ baseline 0.2239.
- `ins1452559_dm_axial_850_1`: the first non-MSSM case (DMsimp UFO); combined 7-channel fit; s95
  **0.978/0.978** from arXiv-LaTeX-only ground truth; µ₉₅ baseline 0.3432 (LO).
- `conf2016037_gluino_2step_sleptons_1400_60`: registered against a run-local patched routine (the
  installed routine zeroes every SR through a two-character `idiscard`→`iselect` defect; the
  shared copy is untouched; upstream report pending); s95 **0.918/0.949**; µ₉₅ baseline 0.2970.
- `ins2182381_gbb_1900_1`: the first published-likelihood (Mode A) case; µ₉₅(obs, NLO k = 2.059)
  B = 0.174 / M = 0.245 / C = 0.299, all excluded. It is gated through the counting-mode
  reconstruction of region B, which agrees with Mode A to **+1.53% (obs) / −4.77% (exp)**. It is
  registered against a run-local patched routine because upstream Rivet ships no `.onnx` weight file
  for it (the removed ONNX block is causally disjoint from the registered CC family); its
  certification uses a split-table adapter; A×ε tier Acceptable (all three CC regions read 24–27%
  high, `fast-sim-floor`).

## Per-case caveats (honest accounting)

- **C1N2 limit is NOT accuracy-gated against the published number.** Scored mode =
  the combined 2ℓ+3ℓ counting fit: µ₉₅(obs)=2.71 → σ-UL ≈ 1096 fb vs the published combined-fit
  219 fb (5.0×). Causes: no public likelihood (their CR-constrained fit absorbs excesses our
  counting model cannot), and **all four** distribution-backed channels carry the real RJR data
  excesses (n/b: 19/8.4, 11/2.7, 20/10.3, 12/3.9) — a simultaneous fit honestly accumulates them
  (single-best-SR gave 2.13/3.92× only by ignoring three excess channels; kept as the certified-run
  artifact for comparison). The sensitivity win: µ₉₅(exp)=0.98 < 1, so our **expected verdict now
  matches the published expected contour** (excluded). The published observed verdict is recovered
  via the registry self-check (σ_NLO 404 fb > 219 fb); regression protection = µ₉₅-stability gate.
  A public likelihood is the path to a true accuracy metric here.
- **k-factor authority**: `cases.json` `sigma_scale_k` is the ONLY k source (C1N2: 1.29, pinned
  against the run's `exclusion.json`). The C1N2 run's on-disk `nlo_xsec.json` records the unphysical
  single-charge k=0.421 — never read k from run dirs (`.claude/rules/statistics.md`).
- **ins1458270 publishes no per-point σ-UL grids** (HEPData Tables 11–28 are contour curves) — hence
  the s95-vs-S95 events-level metric, transcribed from the paper's Table 6 (arXiv:1605.03814).
- **Squark cases are LO** (k=1.0): the exclusion is conservative; A×ε and s95 are σ-convention-free.
- **Merged case has no figure** (it was a merging demo) — its deliverables check covers RESULT.md +
  cert only; no merged overlay is produced.
- **`ins2182381_gbb_1900_1` (Gbb, Mode A) has no figure either** (no per-SR yield overlay produced
  for it — `plots.md`'s cutflow-only convention calls for one; same disclosed-gap pattern as
  the merged case). More load-bearing: **the benchmark runner (`ravel.validation.benchmark`) has no `pyhf_mode="likelihood"` hook**
  — its `run_pyhf()` step always calls `pyhf_exclude.py counting`, so this case is gated on the
  counting-mode reconstruction of the driving SR, not a fresh re-derivation of the Mode-A likelihood
  every `--case` run. The Mode-A numbers (this run's actual headline; `outputs/likelihood_{B,M,C}/`)
  are frozen, once-verified artifacts, not re-verified by the automated gate. A real
  `pyhf_mode="likelihood"` extension (bkg+patch paths per case) is not implemented.

## Adding a case

Register the run in `cases.json` with: identity + masses + σ_LO + k + lumi + SR list + driving SR;
`cert.engine` (`validate_cutflow` if the analysis's HEPData acc×eff tables match its grid regex,
else a run-local adapter emitting the same JSON schema); **transcribed published ground truth with
sources cited** (per-SR S95 from the paper's model-independent table if comparable, σ-UL grid value
if published, contour verdicts at the node); `required` tiers null until measured, then locked to
the first baseline; provenance `require_files` including the named overlay figure. Run
`--case <id>`, eyeball, lock, commit registry+results together.

## Running the gate from a clone

`--fast` runs from the bundled squark case. `--full` and other `--case` runs need the original
run records, which this repository does not include; a missing input is reported as a
provenance/preflight reason, not a crash. Read the committed `results.json` (the locked `--full`
baseline) and the baseline table above as the gate's recorded evidence.
