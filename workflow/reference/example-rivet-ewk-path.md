# Walkthrough — the Rivet EWK path (an electroweakino / cutflow / single-weight search)

A filled-in shape of `WORKFLOW.md` for a leptonic electroweak search whose Rivet routine is
**`SINGLEWEIGHT NOTREENTRY`** and **cutflow-only** (e.g. a recursive-jigsaw C1N2→WZ search). This is the
EWK counterpart to the colored m_eff path (`example-rivet-path.md`); the differences are where the
silent foot-guns live. Replace the bracketed values.

| Step | What you do |
|---|---|
| 2 routine | `routine_fetch.py --query "[code/Inspire]"` → the Rivet id; **check `--show-analysis` for `SINGLEWEIGHT`/`Reentrant: false`** (`steps/04-analyze.md`) |
| 2 model | an electroweakino simplified model (wino C1/N2 + bino LSP → WZ); card per the **EWKino section** of `checklists/model-cards.md` — set `MSOFT` M1/M2 (not just `MASS`), decouple μ, **include `MODSEL`**, force C1→WN1 / N2→ZN1 |
| 3 generate | `p p > x1+ n2` / `add p p > x1- n2` at the routine's √s; **no merging** (lepton-based). **Verify the LHE particle mass == the intended mass** and that the shower makes leptons, *before* trusting the run (the MASS-block-vs-MSOFT trap) |
| 4 analyze | `rivet -a [ID] --skip-weights …` (single YODA; **never** reentrant-merge). Confirm the "Only using nominal weight" log line |
| 5 visualize | cutflow-only → no differential overlay; build the **per-SR yield overlay** (data + bkg band + s+b in mplhep style) — the valid publication figure for a counting search (`plot-criteria.md`) |
| 6 data | A×ε per SR = **last/first cutflow bin** (normalisation-invariant); obs + SM bkg by **integrating the bundled REF distribution tables** into the channel regions (no per-SR yield table exists); `nlo_xsec.py --process wino-c1n2` (**single-charge** file — match a single-charge LO; expect k≈1.3) |
| 7 exclude | `pyhf_exclude.py counting --sigma-scale [k]` on the distribution-backed channel regions → µ₉₅ |
| cert | A×ε vs the published acc×eff **grids** (2-D in M_LSP–M_NLSP); **interpolate** along the splitting axis — nearest-node on a coarse/edge grid can flip the verdict. Driving SR (the 3-lepton SR for WZ) sets the tier |

The result is a real limit even when the point sits at the analysis's sensitivity boundary (expected
µ₉₅ ≈ 1): the *expected* limit is the apples-to-apples comparison to the published contour; an observed
limit pulled up by a data excess in one SR is the analysis's own observed fluctuation, not a pipeline
fault. Cross-check the verdict with SModelS (`reinterpret_db.py --proc "1000023 1000024"`).

**The traps this path has that the colored path does not** (each silently corrupts results if missed):
the `MASS`-block-vs-`MSOFT` override + missing `MODSEL` (wrong mass / no decays); `--skip-weights` for
single-weight routines (the colored m_eff routines are reentrant/multi-weight); cutflow-only A×ε
(last/first bin, not a scalar counter); the single-charge NLO file; and grid interpolation for the cert.
