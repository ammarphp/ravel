# Interrogation — statistics (Session 2, 2026-06-09)

_Defects → fixes → **measured** before/after against `run_benchmark.py`. Gate state at stage close:
`--full` exit 0, 4/4 green (commits 2b8410d, 1997226, b407f6e + the robustness-pack commit)._

## Defects found (diagnosis agent + [Opus] verification; agent over-claims corrected)

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| STAT-D1 | crit | `pyhf_exclude.py` counting loop | s=0 SR (C1N2 SR2L-ISR) ran the bracket to the poi cap and recorded µ=128 ceilings in `per_sr` — a ceiling is not a limit. _Agent's "weakens the observed limit 2.7×" was WRONG (best_sr is by best expected; a zero-signal SR is never best — headline unaffected)._ | **FIXED**: s≤0 SRs skipped with reason; `at_poi_cap`/`cls_monotonic` flags added |
| STAT-D5 | major | `rivet_ref_yields.py:74` | Uniform 15% bkg-uncertainty floor: inflates big SRs (2jl ±44 vs published fitted ±24) and the raw quad-sum underestimates small SRs (6jt ±0.57 vs ±1.2) — the direct cause of the squark s95 1.49× residual | **FIXED** via `--fitted-bkg` (published CR-fitted b±db preferred; source recorded per SR) |
| k-trap | major | k-factor sourcing | Previously measured squark "k=1.08" was the flavour-sum trap: HEPi grid = **10-fold** degenerate q̃q̃* (grid metadata: "~u,~d,~c,~s,~b mass degenerate", gluino decoupled); our sample is 8-fold | **FIXED**: like-for-like k = 0.328×(8/10)/0.3044 = **0.862** (squark), 0.2624/0.307 = **0.855** (merged), gluino **1.915** (grid = g̃g̃ squarks-decoupled, exact match) |
| C1N2 model | major | single-best-SR counting vs published 2ℓ+3ℓ combination | Single-SR mode understates the model mismatch by ignoring three excess-carrying channels | **FIXED**: `--combined` simultaneous 4-channel fit; adopted as scored mode (CHECK IN) |
| STAT-D2 | major | `_cross()` linear interpolation | Assumes monotone-decreasing CLs; no validation. **Measured side-finding**: grid-interpolated crossing carries ~2% bias vs the exact bisected root (2jl fitted: 0.1918 vs 0.1878 LO) — deterministic, absorbed by the 10% stability rtol | **FIXED** (warning flags); bias documented here |
| STAT-D3 | major | counting model at low counts | Gaussian-constraint strain at b<5 / db/b>0.5 / n<5 not flagged | **FIXED**: `low_count_flags` metadata per SR |
| STAT-D7 | minor | bracket poi cap | Cap-hit reported as if a limit | **FIXED**: `at_poi_cap` flag + stderr warning |
| STAT-D4 | minor | exclusion.json schema | No `is_best`, skip reasons, mode notes | **FIXED** (lite) |
| pyhf/numpy | minor | pyhf 0.7.6 toybased + numpy≥2 | `expected_pvalues` calls `np.percentile(interpolation=)` (renamed `method=`) → toybased hypotest crashes | documented; workaround = `ToyCalculator` API directly (KNOWN-LIMITATIONS) |
| STAT-D6 | major | `validate_cutflow.py` nearest-node grid lookup | Verdict-flip risk on coarse grids (C1N2 needed 1-D interpolation via its run-local adapter) | **DEFERRED to S4** (analysis stage owns the cert engine generalization; regression-free requirement noted) |

## Fixes applied — measured before/after (the gate is the referee)

| Fix | Before | After | Evidence |
|---|---|---|---|
| 1a gluino NLO+NNLL k=1.915 | µ₉₅ 0.10029; s95 1.00/1.02 | µ₉₅ **0.05237** (re-lock); s95 1.00/1.02 **unchanged** (k-free, as predicted) | commit 2b8410d |
| 1b squark fitted-bkg + k=0.862 | s95 **1.49/1.53** (Acceptable); µ₉₅ 0.28164 | s95 **1.013/1.030** (**Ideal**, required ratcheted); µ₉₅ 0.22254 (re-lock) | commit 1997226 |
| 1b merged fitted-bkg + k=0.855 | s95 1.49/1.53; µ₉₅ 0.28333 | s95 **1.013/1.028** (Ideal); µ₉₅ 0.22580 (re-lock) | commit 1997226 |
| 1c combined C1N2 | µ₉₅ obs 2.1305 / exp 1.06; σ-UL 3.92× | obs **2.7123** (all 4 channels carry the real RJR excesses — honest accumulation) / exp **0.976 < 1 → expected verdict now matches the published expected contour**; σ-UL 5.00× informational | commit b407f6e; gate self-test incl. exit-2 knob + correct stability trip pre-re-lock |
| robustness pack | s=0 SR → µ=128 in per_sr; no honesty flags | skipped+flagged; **--full bit-identical** (acceptance test) | robustness commit |
| 1d toys spot-check | — | CLs(4000 toys) = **0.0467** at the asymptotic µ95 (0.050) — consistent within MC error; mild over-coverage; asymptotics certified for the driving-SR regime | scratch, recorded here |

**The headline physics result**: with the analysis's own CR-fitted backgrounds and the verified WG
σ_NLO+NNLL, the counting machinery reproduces the published per-SR S95 to **1–3% on every comparable
case** (squark 1.013/1.030, merged 1.013/1.028, gluino 0.997/1.020). The Session-1 squark 1.49×
residual is fully explained as background-INPUT fidelity (pre-fit-MC + floor), not machinery — the
original inputs are preserved in `sr_yields.json` beside the fitted variants as evidence.

Honest correction recorded: k<1 for the squark cases means the old LO limit was mildly **aggressive**
(LO-PDF overshoot), not "conservative" as the run RESULT.md claimed — addenda land in S3.

## Deferred (with why)

- **Signal-MC-stat in the model** (staterror on s): tail SRs are report-only in the cert tiers and
  contribute O(1%) to combined sensitivity; proper fix is a Phase-2 model upgrade. KNOWN-LIMITATIONS.
- **validate_cutflow grid interpolation**: owned by S4 (cert engine; must be regression-free on
  exact-node cases).
- **pyhf upgrade** (0.7.6→0.8.x would fix the numpy toybased clash): an env-pin change touching every
  helper — out of Session-2 scope; documented.
- **Floor redesign** (threshold-aware floor): superseded by fitted-bkg adoption where published;
  the floor remains the fallback for analyses without published fitted backgrounds (documented in
  the helper docstring).
