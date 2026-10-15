# Published likelihood — ATLAS-SUSY-2018-06 three-lepton search (one signal point)

Two uses. It is the regression workspace for the optimizer guard in `pyhf_exclude.py`: the
workspace on which pyhf 0.7.6's stock scipy/SLSQP backend silently returned the initial vector
claiming success (free fit -2lnL 302.52 against the true 271.79, mu_hat == 1.0), because the
-2lnL surface has NaN pockets (histosys interpolation drives bins negative). It is also the
shipped background workspace that the channel map
`src/ravel/data/likelihoods/channel_maps/susy-2018-06-three-lepton.json` connects a native
yield file to (registry entry `susy-2018-06-three-lepton`).

Contents (both re-serialized compact, content-identical to the HEPData originals):
- `BkgOnly.json` — the background-only HistFactory workspace, verbatim (four single-bin
  channels: `CRlow_cuts`, `CRISR_cuts`, `SRlow_cuts`, `SRISR_cuts`; POI `mu_SIG`).
- `patch_ERJR_300p0_100p0.json` — the single (m_C1N2, m_N1) = (300, 100) GeV signal patch
  extracted from `patchset.json` (name `ERJR_300p0_100p0`, 1 of 64 patches; only this point is
  needed, the full patchset is 3.1 MB).

Provenance: HEPData record ins1771533 ("Search for chargino-neutralino production with mass
splittings near the electroweak scale in three-lepton final states in sqrt(s)=13 TeV pp
collisions with the ATLAS detector", ATLAS-SUSY-2018-06), resources tab, "Likelihoods" archive
(CC BY 4.0). Fetched 2026-08-28.

Ground truth at this point (guarded MIGRAD, validated against the publication): free-fit
-2lnL = 271.786, mu_hat = 0.2446; mu95 obs/exp = 0.826/0.584 against the published
sigma95/sigma_theory = 0.828/0.587 (sub-percent). The stock SLSQP backend gave 1.192/1.193.
The same numbers are shipped as `reference_fit.json` for `pyhf_exclude.py check_fit_reference`.
