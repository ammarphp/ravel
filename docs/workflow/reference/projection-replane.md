# Reference — projection (G2c) + replane (G2d)  ·  **BUILT** (`project_limits.py` counting **+ likelihood** + `spectrum_mix.py` + `replane.py` incl. **2-D UL surface**; selftests PASS)

Census-gated OPEN (capability-census §ranked-candidates #3/#4). Spec'd 2026-07-07; counting +
spectrum + fold BUILT the same overnight; the **likelihood projection mode and the fold's 2-D
UL-surface mode landed 2026-07-11** (CR-024/CR-025 updates; first exercised by the
SUSY-2020-04 projection+replane run). Kept as the design + usage reference.

## Projection to higher luminosity (the P7 first half; forum type 4)
**Deliverable:** EXPECTED-ONLY limits/contours at L₂ from a run (or published inputs) at L₁;
labels scream `projection, expected-only, bkg-scaling=<declared>`.
**Counting mode (build first — one hour):** per SR: s→s·f, b→b·f with f=L₂/L₁; δb under a
DECLARED scenario: `stat-limited` δb→δb·√f · `syst-limited` δb→δb·f (relative syst constant) ·
`fixed-relative` δb/b const. Expected UL via the existing `pyhf_exclude.py counting` on the
Asimov (obs:=b). CLI: `project_limits.py counting --srs sr_yields.json --lumi-factor f
--bkg-scaling stat|syst|fixed` → projected s95/µ₉₅ + the scenario table (report ALL three
scenarios; the spread IS the honest band).
**Likelihood mode (BUILT 2026-07-11, CR-024):** the published HistFactory workspace is the
paper's own statistical model; the transform runs on the PATCHED workspace (signal yields are
absolute and scale with f too) and every limit is delegated unchanged to `pyhf_exclude.py
likelihood` (the projected workspace passes as `--bkg` with an EMPTY patch). Per-modifier
handling (documented in the tool docstring): sample data + observations ×f; histosys
`f·(nom + (orig−nom)·g_sys)`; normsys `1+(orig−1)·g_sys`; staterror/shapesys ×`f·g_stat`;
lumi sigmas ×g_sys; normfactor/shapefactor untouched — with `g_sys = {stat: 1/√f, syst: 1,
frozen: 1/f}`, `g_stat = {stat,syst: 1/√f, frozen: 1/f}`. Observations scale as f·data (CR
templates and CR data together ⇒ the profiled background normalizations reproduce the L₁ fit
— the likelihood-mode analog of obs:=b); only the EXPECTED (median+bands) limit is quotable;
the f≠1 "observed" output is a labeled scaled-data proxy, never deliverable.
CLI: `project_limits.py likelihood --bkg bkg_only.json --patchset patchset.json
--all-patches|--patch-name N --lumi-factor f --bkg-scaling all|stat|syst|frozen [--workers N]
--out DIR` → per-point `projection.json`. **Validation gate (ladder R5-analog):** f=1 is a
bit-exact workspace identity (asserted in `--selftest`, plus toy algebra + f=4 scenario
ordering); on real inputs re-run the paper's own grid at f=1 and overlay its published
expected contour + per-point CLs (the SUSY-2020-04 run: 34/34 points, mean |ΔCLs|≈0.001).
Reproducing a published HL-LHC/Run-3 projection point for an analysis that published both
remains the open second half of the gate.

## Replane (the P7 second half; forum type 3)
**Deliverable:** published simplified-model limits re-expressed in a different parameter plane
(e.g. Fig-3 exclusion → µ–M₂ under M₁=M₂, tanβ=50).
**SUSY slice — spectrum leg BUILT WITH SELFTEST (2026-07-07):**
`src/ravel/physics/spectrum_mix.py` — per target-plane point, TREE-LEVEL neutralino
(4×4, signed eigh masses) + chargino (2×2 SVD) masses AND wino/bino/higgsino compositions.
Single point: `spectrum_mix.py --m1 250 --m2 250 --mu 300 --tanb 50 [--json [out]]`; replane
grid (the P7 plane): `spectrum_mix.py --plane mu:M2 --m1eqm2 --tanb 50
--grid "mu=100:500:50,M2=100:500:50" --json out.json` (run in the rivet env). `--selftest`
(18 checks, exit 0 = PASS): pure-bino/wino/higgsino decoupling limits (masses 1%, purity >99%),
gauge-eigenstate unitarity traces (1e-6), and the T3 point M1=M2=250, µ=300, tanβ=50 → light
states MIXED, no composition >90% (N1 = 0.15/0.50/0.35 bino/wino/higgsino; C1 wino ≤0.79;
N2 = the exact photino, cW²/sW²) — the trap-catalogue claim validated with numbers
(selftest evidence recorded in the dev repo's overnight-roadmap records). TREE-LEVEL ONLY:
loop corrections shift masses O(few GeV) and the intra-multiplet splitting is entirely
loop-level — a production replane quotes SPheno/SuSpect when mass precision matters
(DECLARE which). Compositions feed the fold. **The fold half is BUILT (CR-025, 2026-07-07):**
`src/ravel/physics/replane.py fold` does the DIRECT fold of ONE published limit —
per target-plane point it takes the spectrum_mix state (mass + composition; charginos use the
U/V mixing-matrix average), predicts a composition-weighted σ×BR from pure-state σ(mass)
references (winos ~3× higgsinos at equal mass), log-interpolates the published UL at that mass,
and computes r = σ×BR/σ_UL (excluded where r≥1) → `replane.json` + a lint-gated r-map with the
r=1 contour in the new plane. `--selftest` PASS (round-trip identity / monotonicity / composition
weighting / log-interp); demo'd on a 36-point µ–M₂ grid.
```bash
<conda> run -n rivet python scripts/run.py ravel.physics.spectrum_mix --plane mu:M2 --m1eqm2 \
    --tanb 50 --grid "mu=150:400:50,M2=150:400:50" --json plane.json
<conda> run -n rivet python scripts/run.py ravel.physics.replane fold --grid plane.json \
    --ul-curve <published_UL.json> --sigma-model <model.json> --target-state C1 --out DIR
```
**2-D UL-surface mode (BUILT 2026-07-11, CR-025 follow-on):** compressed-spectrum searches
limit σ vs BOTH a mass and a splitting — give `--ul-curve` a JSON with a `dm` list
(`{mass:[…], dm:[…], sigma_ul_fb:[…]}`, one triplet per published grid point) and the fold
evaluates the surface at each target-plane point's OWN (mass, dm): dm = m(C1)−m(N1) from the
spectrum point (tree) plus the optional `--dm-extra-curve {mass, value}` additive term (e.g.
the one-loop intra-multiplet splitting, absent at tree level and DOMINANT for heavy gauginos
— declare its formula; worked module: the SUSY-2020-04 run's `build/higgsino_dm.py`,
anchored to the paper's own pure-higgsino curve at 1.2%). Interpolation is
triangulated-linear in (mass, dm) on log(UL) with a ~1e-6·range hull-edge snap guard
(published grid corners sit exactly on the hull; tree+loop sums carry float noise); a point
OUTSIDE the hull is `covered: false` (r null — NOT excluded, NOT allowed; drawn first-class
per T4). Selftest: planar round-trip r≡1 (interior + snapped corner) + hull honesty.
For "which published analyses exclude this point" (many analyses, database-driven), use the
SModelS fold instead: `reinterpret_db.py --data-select efficiencyMap` (Option D1). Trap T3 is the
whole game: the target plane usually BREAKS the published purity assumption — the per-point
composition reweights σ (done); its effect on **A×ε** is NOT re-simulated by the fold (stamped as
a caveat) and must be bounded or escalated (eval subject #7 caught exactly this; its writeup is
the acceptance test).
**Validation gate:** round-trip the paper's own plane (transform → invert) reproduces the
published contour; one published replane comparison where the literature has one (pMSSM
reinterpretation papers).
**Non-SUSY replanes:** stay [judgment]-escalation territory (census: only the ~14-analysis EXOT
slice folds); the honest offer is the summary-plot track on the nearest published planes.

## Wiring already in place tonight
`task_contract` task_modes `projection`/`reinterpret` route to intake correctly (ROUTING-EVALS
#3/#7 PASS); step-4 Option D1 (the fold) is live; this spec + `docs/workflow/checklists/summary-plot.md` are the
execution surface the builds drop into. Registry: CR-024 (projection) / CR-025 (replane)
registered OPEN; CR-023 is the summary-plot track itself.
