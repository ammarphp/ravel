# Regression fixture — ATLAS-SUSY-2018-06 published likelihood (single point)

Purpose: the `pyhf_exclude.py selftest` case `2018-06-freefit` (CR-005, 2026-08-28) —
the workspace on which pyhf 0.7.6's stock scipy/SLSQP backend SILENTLY returned the
init vector claiming success (free fit -2lnL 302.52 vs the true 271.79, mu_hat==1.0),
because the -2lnL surface has NaN pockets (histosys interpolation drives bins
negative). Committed so the regression runs offline on a fresh clone, in line with the
benchmark's committed-inputs policy (`framework/benchmark/BENCHMARK.md`).

Contents (both re-serialized compact, content-identical to the HEPData originals):
- `BkgOnly.json` — the background-only HistFactory workspace, verbatim.
- `patch_ERJR_300p0_100p0.json` — the single (m_C1N2, m_N1) = (300,100) GeV signal
  patch extracted from `patchset.json` (name `ERJR_300p0_100p0`, 1 of 64 patches;
  only this point is needed, the full patchset is 3.1 MB).

Provenance: HEPData record ins1771533 ("Search for chargino-neutralino production with
mass splittings near the electroweak scale in three-lepton final states in sqrt(s)=13
TeV pp collisions with the ATLAS detector", ATLAS-SUSY-2018-06), resources tab,
"Likelihoods" archive (CC BY 4.0). Fetched 2026-08-28 during the CR-005 routine
certifications (`trial-runs/CR005_c1n2_sample/outputs/hepdata/`, gitignored class).

Ground truth at this point (guarded-MIGRAD, validated vs publication): free-fit
-2lnL = 271.786, mu_hat = 0.2446; mu95_obs/exp = 0.826/0.584 vs the published
sigma95/sigma_theory = 0.828/0.587 (sub-percent). Stock SLSQP gave 1.192/1.193.
