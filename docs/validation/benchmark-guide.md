# BENCHMARK — the known-answer regression gate (Phase 1)

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
fast-sim+LO carries an intrinsic ~10–20% floor (`KNOWN-LIMITATIONS.md`).

## How to run

```bash
python3 benchmarks/run_benchmark.py --fast    # fast_case only (~7 s) — per-session smoke gate
python3 benchmarks/run_benchmark.py --full    # all cases (~25 s) — the milestone gate
python3 benchmarks/run_benchmark.py --case ins1458270_gluino_1000_100
```

Stdlib-only `python3` from anywhere; the helpers run inside the `rivet` conda env via subprocess
(no activation needed). Exit codes: **0** all gates hold · **1** breach or case error (reasons
printed under the row) · **2** malformed registry/usage. `results.json` is overwritten every run —
the **committed** copy is always the `--full` baseline. `--cases/--out` overrides exist for gate
self-tests (see `.work/selftest/`); they never touch the real registry. (The sibling readiness
tool `scripts/audit.py` does NOT share this overwrite-every-run behavior — it is read-only by
default (`--check`); pass `--write` to deliberately refresh `AUDIT.md`.)

**Gate per case** (breach ⇒ exit 1): A×ε tier ≥ `required.axe_tier` · limit tier ≥
`required.limit_tier` (when set) · pipeline verdict matches published (when `gates.verdict_pipeline`)
· µ₉₅ within 10% of baseline · pyhf best-SR == registered driving SR · provenance clean · registry
self-check (transcribed numbers imply the transcribed verdict).

## Baseline — locked state as of 2026-06-09 Session 2/S1 (history below; relax only via a reviewed commit)

| Case | A×ε driving | Tier (req) | s95 obs/exp vs S95 | Limit tier (req) | µ₉₅ obs (baseline) | Cert | Notes |
|---|---|---|---|---|---|---|---|
| `ins1458270_squark_800_100` | 2jl @ 2.4% | **Ideal** | 44.6/55.6 vs 44/54 → **1.01/1.03** | **Ideal** | 0.2225 | PASS | CR-fitted bkg + k=0.862 (NLO+NNLL, 8/10 rescale) |
| `ins1676551_c1n2_300_100` | SR3L_Low @ 6.4% | **Good** | n/a (not comparable) | — (informational) | 2.1305 | PASS | counting-vs-combined gap, documented |
| `ins1458270_gluino_1000_100` | 5j @ 13.2% | **Acceptable** | 5.38/8.88 vs 5.4/8.7 → **1.00/1.02** | **Ideal** | 0.0524 | WARN | A×ε deficit = merging (Session-2 target); k=1.915 |
| `ins1458270_squark_merged_800_100` | 2jl @ 3.9% | **Ideal** | 44.6/55.5 → **1.01/1.03** | **Ideal** | 0.2258 | PASS | merging closes 4jt/6j deficits; k=0.855 |
| `ins1458270_gluino_merged_1000_100` | 5j @ 8.1% | **Good** | 5.40/8.95 → **1.00/1.03** | **Ideal** | 0.0550 | PASS | MLM xqcut=250 (scan-chosen); k=1.939; the Session-2 lift |
| `conf2016054_gluino_onestep_1500_60` | — (unscorable) | — | 5.03/6.45 → **0.91/0.98** | **Ideal** | 0.2239 | n/a | S3 census draw; CONF note (no HEPData) → stability-only; cert.engine `none` |
| `ins1452559_dm_axial_850_1` | — (unscorable) | — | 59.7/46.9 → **0.98/0.98** | **Ideal** | 0.3432 | n/a | S3 census; first non-MSSM (imported DMsimp UFO); combined 7-channel; paper not on HEPData |
| `conf2016037_gluino_2step_sleptons_1400_60` | — (unscorable) | — | 4.68/3.80 → **0.92/0.95** | **Ideal** | 0.2970 | n/a | S3 census; **registered against a run-local PATCHED routine** (verified 2-char share defect; policy note in the case + RESULT.md; upstream report pending) |
| `ins2182381_gbb_1900_1` | SR_Gbb_0l_B @ 26.5% | **Acceptable** | n/a (no model-independent S95 table) | — (informational) | 0.176940 | FAIL | S3 census idx8 resume; **the FIRST published-likelihood (Mode A) case** (`pyhf_exclude.py likelihood`, `outputs/likelihood_{B,M,C}/`) — scored here via the counting-mode reconstruction (harness has no `pyhf_mode="likelihood"` hook yet); **registered against a run-local PATCHED routine** (upstream Rivet never shipped this routine's `.onnx` weight file — confirmed absent both locally and in `gitlab.com/hepcedar/rivet/analyses/pluginONNX/`; the removed ONNX branch is causally disjoint from the registered CC family, verified by source read; upstream report pending); axe cert-engine verdict FAIL / benchmark tier Acceptable — consistent 24–27% A×ε excess across all 3 CC regions (`fast-sim-floor`), not reviewed by the step-9 Tier-B panel |

What the baseline says, in one breath: **selection fidelity is publication-grade or better on three
of four cases** (2.4–6.4%; the gluino's 13% is the known un-merged multi-jet deficit, attributed and
gated as the Session-2 improvement target), and **the limit machinery reproduces the published
per-SR limits to 1–3% on every comparable case** now that the counting inputs are the analysis's own
CR-fitted backgrounds and the σ normalization is the verified WG NLO+NNLL value. The original 1.49×
squark residual is preserved as evidence (`outputs/sr_yields.json` vs `sr_yields_fitted.json`): it
was background-INPUT fidelity, not machinery.

## Baseline history (every µ₉₅-stability re-lock maps to exactly one entry + one commit)

- **2026-06-09 S2/1a — gluino onto NLO+NLL σ**: `sigma_scale_k` 1.0 → 1.915 (verified like-for-like:
  HEPi `pp13_gluino_NNLO+NNLL.json` = g̃g̃ with squarks decoupled, exactly our setup; σ=0.385 pb).
  µ₉₅(obs) 0.10029 → **0.05237** (re-lock). A×ε and s95 unchanged (k-free): s95 1.00/1.02 Ideal holds.
- **2026-06-09 S2/1b — squark cases onto CR-fitted backgrounds + verified k (atomic, both cases)**:
  counting inputs switched to `sr_yields_fitted.json` (published fitted b±db, arXiv:1605.03814
  Table 6; observed n verified identical to the REF integration in all 7 SRs) and
  `sigma_scale_k` → 0.862 / 0.855 (10-fold HEPi grid rescaled to our 8-fold degeneracy —
  the earlier "k=1.08" was the flavour-sum trap; k<1 = LO-PDF overshoot, normalization transfer).
  s95 recovery **1.49/1.53 → 1.013/1.030 (squark), 1.013/1.028 (merged)**; limit tier
  Acceptable → **Ideal** (required ratchets with it); µ₉₅(obs) 0.28164 → **0.22254** and
  0.28333 → **0.22580** (re-locks). Driving SR unchanged (2jl). Honest note: the LO-σ limit was
  mildly aggressive, not conservative — RESULT.md addenda in S3.
- **2026-06-09 S2/1c — C1N2 scored mode → combined 2ℓ+3ℓ counting fit** (`inputs.pyhf_mode:
  "combined"`; harness knob + `pyhf_exclude.py --combined`; gate self-tested incl. exit-2 on a bad
  knob value and a correct stability trip pre-re-lock). µ₉₅(obs) 2.1305 → **2.7123** (re-lock; all
  four channels carry the real RJR excesses — the combination honestly accumulates them);
  µ₉₅(exp) 1.06 → **0.976 < 1** — our expected verdict now matches the published expected contour
  (excluded). σ-UL ratio 3.92× → 5.00× (informational, attributed). Adopted at CHECK IN over the
  numerically-flattering single-SR mode, which was closer to 219 fb only by ignoring three
  excess-carrying channels.
- **2026-06-11 S3 — `conf2016054_gluino_onestep_1500_60` registered** (6th case; the census's first
  draw to survive the full AND-gate: cert n/a + oracle PASS + reviewer TRUST-WITH-CAVEATS none
  blacklist + gate green). New `cert.engine: "none"` class for analyses with NO published acc×eff
  (CONF notes — a generality finding); limit accuracy from PDF-transcribed Table 16:
  s95 0.914/0.977 (Ideal, locked); µ₉₅ baseline 0.2239 (k=1.985 NNLOapprox+NNLL). Reviewer
  independently reproduced the limits and audited all 19 transcription rows.
- **2026-06-11 S3 — `ins1452559_dm_axial_850_1` registered** (7th case; the first **non-MSSM** case:
  DMsimp_s_spin1 UFO downloaded + py2→py3 converted through the documented MG5 path). Monojet,
  combined 7-channel exclusive fit (the paper's own structure); s95 recovery **0.978/0.978** (Ideal,
  locked) from arXiv-LaTeX-only ground truth (the paper has NO HEPData record — verified, a
  pre-2016 coverage finding); µ₉₅ baseline 0.3432 (LO — no higher-order grid exists for the
  mediator; conservative). Reviewer reproduced the analytic mediator width to 7 digits and the
  exclusion pyhf-free via the paper's own σ_vis table.
- **2026-06-11 S3 — `conf2016037_gluino_2step_sleptons_1400_60` registered** (8th case): gluino
  2-step via sleptons (1400,730,395,60) vs ATLAS-CONF-2016-037. **The census's routine-defect
  case**: the installed share routine zeroes every SR (verified `idiscard`→`iselect` 2-char defect);
  registered against the run-local patched copy under an explicit, registrar-owned policy precedent
  (reviewer-verified defect + byte-diff audit + pristine share + upstream report pending). µ₉₅
  baseline 0.2970 (k=1.975, exact HEPi node; iseed=21 — the retry seed-reset gotcha,
  reviewer-corrected record); s95 recovery 0.918/0.949 (Ideal). Review: TRUST-WITH-CAVEATS,
  blacklist clear.
- **2026-06-10 S2/S7 — `ins1458270_gluino_merged_1000_100` registered** (5th case; required Good/Ideal,
  µ₉₅ baseline 0.0550, k=1.939 on the matched σ 0.19856 pb). Driving-5j A×ε 1.132 → **1.081**
  (WARN@13.2% → PASS@8.1%); s95 recovery 1.000/1.029. **Attribution corrected in both gluino cases**:
  the high-multiplicity residual is a hard-radiation *excess* (not a merging deficit) — ME merging
  reduces it; the A14 tune variant reduces it further (PASS@7.4%, recorded as evidence; tune policy =
  Session 3). Merging-scale doctrine: measured matched-σ stability scan (plateau 4.4%, xqcut=250=m/4,
  matched/LO −1.2%); qCut 1.5× sensitivity variant WARN@12% documented. The unmerged gluino case
  remains the reference.
- **2026-07-08 (task 7.1) — `ins2182381_gbb_1900_1` registered** (9th case; the registry's **first
  published-likelihood/Mode-A case**): gluino Gbb (1900,1) vs ATLAS_2022_I2182381 (S3 census idx8,
  resumed). `pyhf_exclude.py likelihood --bkg CC_Gbb_{B,M,C}_bkgonly.json --patch
  <our-signal-patch>.json` on all 3 CC regions → µ₉₅(obs, NLO k=2.059) B=0.174/M=0.245/C=0.299, all
  EXCLUDED, driving=B (boosted, best expected). Counting-mode reconstruction of B (this case's
  scored mode, since the harness has no `pyhf_mode="likelihood"` hook) agrees with Mode A to
  **+1.53%(obs)/−4.77%(exp)** — the sharpest direct Mode-A-vs-counting comparison in the registry.
  Blocked most of the session on a REAL upstream gap mis-attributed in the census WORKLOG to a
  "relative-conda-path bug": `ATLAS_2022_I2182381.cc` unconditionally `getONNX()`s in `init()`, but
  upstream Rivet never shipped `ATLAS_2022_I2182381.onnx` (verified absent both locally and via the
  GitLab API tree of `analyses/pluginONNX/`). Registered against a run-local patched copy
  (`config/rivet_patched/ATLAS_2022_I2182381_PATCHED.cc`, share untouched) that removes only the
  ONNX load + the disjoint NN-only `analyze()` block (source-read-verified causally independent of
  the registered CC family — no shared variables, no `vetoEvent` in the removed block); upstream
  report pending, same policy precedent as the `conf2016037` case. Cert needed its own split-table
  adapter too (`config/certify_axe.py`): this analysis publishes acceptance and efficiency as two
  SEPARATE HEPData tables (no combined "acceptance times efficiency" table), unlike
  `validate_cutflow.py`'s built-in regex. axe_tier=Acceptable (driving-SR ratio 1.265; all 3 CC
  regions read 24–27% high — a consistent systematic, `fast-sim-floor`-attributed). Not yet passed
  through the step-9 Tier-B adversarial panel.

## Per-case caveats (honest accounting)

- **C1N2 limit is NOT accuracy-gated against the published number.** Scored mode (since S2/1c) =
  the combined 2ℓ+3ℓ counting fit: µ₉₅(obs)=2.71 → σ-UL ≈ 1096 fb vs the published combined-fit
  219 fb (5.0×). Causes: no public likelihood (their CR-constrained fit absorbs excesses our
  counting model cannot), and **all four** distribution-backed channels carry the real RJR data
  excesses (n/b: 19/8.4, 11/2.7, 20/10.3, 12/3.9) — a simultaneous fit honestly accumulates them
  (single-best-SR gave 2.13/3.92× only by ignoring three excess channels; kept as the certified-run
  artifact for comparison). The sensitivity win: µ₉₅(exp)=0.98 < 1, so our **expected verdict now
  matches the published expected contour** (excluded). The published observed verdict is recovered
  via the registry self-check (σ_NLO 404 fb > 219 fb); regression protection = µ₉₅-stability gate.
  A public likelihood is the Phase-2 path to a true accuracy metric here.
- **k-factor authority**: `cases.json` `sigma_scale_k` is the ONLY k source (C1N2: 1.29, pinned
  against the run's `exclusion.json`). The C1N2 run's on-disk `nlo_xsec.json` records the unphysical
  single-charge k=0.421 — never read k from run dirs (`.claude/rules/statistics.md`).
- **ins1458270 publishes no per-point σ-UL grids** (HEPData Tables 11–28 are contour curves) — hence
  the s95-vs-S95 events-level metric, transcribed from the paper's Table 6 (arXiv:1605.03814, LaTeX
  source on disk in the gluino run's `outputs/published/`).
- **Squark cases are LO** (k=1.0): the exclusion is conservative; A×ε and s95 are σ-convention-free.
- **Merged case has no figure** (it was a merging demo) — its deliverables check covers RESULT.md +
  cert only; producing the merged overlay is an open item.
- **`ins2182381_gbb_1900_1` (Gbb, Mode A) has no figure either** (no per-SR yield overlay produced
  this session — `plots.md`'s cutflow-only convention calls for one; same disclosed-gap pattern as
  the merged case). More load-bearing: **`run_benchmark.py` has no `pyhf_mode="likelihood"` hook**
  — its `run_pyhf()` step always calls `pyhf_exclude.py counting`, so this case is gated on the
  counting-mode reconstruction of the driving SR, not a fresh re-derivation of the Mode-A likelihood
  every `--case` run. The Mode-A numbers (this run's actual headline; `outputs/likelihood_{B,M,C}/`)
  are frozen, once-verified artifacts, not re-verified by the automated gate. A real
  `pyhf_mode="likelihood"` extension (bkg+patch paths per case) is the natural Phase-2 follow-up.

## Adding a case (Session 3+)

Register the run in `cases.json` with: identity + masses + σ_LO + k + lumi + SR list + driving SR;
`cert.engine` (`validate_cutflow` if the analysis's HEPData acc×eff tables match its grid regex,
else a run-local adapter emitting the same JSON schema); **transcribed published ground truth with
sources cited** (per-SR S95 from the paper's model-independent table if comparable, σ-UL grid value
if published, contour verdicts at the node); `required` tiers null until measured, then locked to
the first baseline; provenance `require_files` including the named overlay figure. Run
`--case <id>`, eyeball, lock, commit registry+results together.

## Fresh clone / distribution

**Dev repo: the minimal cert-input subset is TRACKED** (2026-07-06, audit A3-01): the 6 signal
`.yoda` files + the 2 HEPData table dirs `cases.json` needs (~1.3 MB, force-added past the
heavy-intermediate ignore rules) — a fresh dev clone runs `--fast`/`--full` with zero MC and
zero network. If you regenerate one of these inputs, re-add it with `git add -f` (the ignore
rules still cover the class). A missing artifact still fails as a clean provenance/preflight
reason, not a crash.

**Public distribution: the gate is RECORDED EVIDENCE, not a runnable check.** The dist ships no
`trial-runs/2026-*` run dirs by policy (`docs/development/distribution.md`), so `cases.json`'s inputs
are absent there by design: read the committed `results.json` (the locked `--full` baseline)
plus this file's baseline table as the gate's evidence. Re-running the gate requires the dev
repo (or regenerating the certified runs per their RESULT.md recipes — hours of MC).

## Phase 2 hooks (DESIGN.md)

Relative-L² distance on the discriminating distribution (not just SR yields) · normalization-vs-shape
split · **R6 visual-fidelity scoring of the overlay itself** (the figure a physicist trusts at a
glance) · per-analysis end-to-end wall-clock (the "days → hours" efficiency claim becomes measured,
not asserted) · LLM-judge provenance audit of run logs · `--publication` gate (all ≥ Good, ≥50%
Ideal) · public-likelihood/combined statistical models where the experiments release them.
