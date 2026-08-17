# Step 4B results — collect the yields + signal patch

This branch produces the analysis inputs; the 95% CL limit itself is computed in `../steps/07-exclude.md`.

**Extract the per-stage numbers + the exclusion inputs (under `<RUN>/output/`):**
```bash
cd trial-runs/<your-run-folder>/output

# MadGraph cross-section (LO)
grep -iE "Cross-section :" ../logs/madgraph.log | tail -1

# SimpleAnalysis total acceptance + nonzero signal regions
awk -F, 'NR==1||$2+0>0{print}' <selection>.txt | head
```
Keep the background-only likelihood (`…/share/mapyde/likelihoods/<name>_bkgonly.json`) and the
`sa2json` **signal patch** (`<analysis>_patch.json`) — these are the inputs to step 7.

**Compute the limit in step 7, not via mapyde's muscan.** mapyde's `muscan` uses a *fixed* µ grid
(e.g. 0.1–2.0); if CLs at its ceiling is still ≫ 0.05 the limit was not resolved (it lies beyond the
grid, not "= the ceiling"). Use `pyhf_exclude.py likelihood`, which brackets µ with no ceiling:
```bash
$CONDA run -n rivet python ../../_infrastructure/pyhf_exclude.py likelihood \
  --bkg <bkgonly>.json --patch <analysis>_patch.json --out pyhf_exclusion
```
`exclusion.json` gives the observed/expected µ₉₅; **µ₉₅ < 1 ⇒ excluded**.

**Record the run** (fill `<RUN>/RESULT.md` per `trial-runs/README.md`): per-stage PASS/timing, config,
the cross-section/acceptance, the µ₉₅ from step 7, and a sanity comparison to the target analysis's
own published reference (not a different analysis's limits).

**Next:** `../steps/07-exclude.md` → report the path, µ₉₅, and verdict.
