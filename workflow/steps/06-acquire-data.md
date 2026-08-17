# Step 6 — Acquire the analysis's data + likelihood  ·  [judgment] / [agent]
`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda` — every `$CONDA` below.

The exclusion (step 7) needs the analysis's own statistical inputs: ideally its published likelihood;
otherwise the observed counts + SM background per signal region. These live in different places, and
not all are reachable the same way. The order below reflects what actually works (tested on this host).

## 6.1 Published likelihood — programmatic, no browser (preferred)
If the analysis published a serialized likelihood (increasingly standard for ATLAS SUSY), it is the
strongest input and it downloads directly. The HEPData JSON API (`?format=json`) lists the record's
`resources`, and the resource endpoint `/record/resource/<id>?view=true` is open (unlike the bulk/
table `/download/` paths, which return 403):
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/hepdata_fetch.py \
  --routine <RIVET_ID>  --out <rundir>/outputs/hepdata  --download-likelihood
```
This writes `hepdata_manifest.json` (tables + resources) and, when a likelihood is published, fetches
and extracts the background-only workspace(s) via `pyhf.contrib.utils.download`. Pair it in step 7
with a signal patch built from your model (SimpleAnalysis → `sa2json`). The mapyde-bundled likelihoods
(`…/share/mapyde/likelihoods/`) are a curated offline copy of the same.

## 6.2 No likelihood — per-SR counts from bundled reference data
Older searches publish no likelihood. If the routine is a **Rivet** search routine, its bundled REF
carries the published distributions — `y01` = observed data, `y02` = SM background (with uncertainty).
Turn them into per-SR counting inputs:
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/rivet_ref_yields.py \
  --signal <rundir>/outputs/<sig>.yoda \
  --ref <…>/envs/rivet/share/Rivet/<RIVET_ID>.yoda.gz \
  --spec <rundir>/inputs/sr_spec.json --out <rundir>/outputs/sr_yields.json
```
`sr_spec.json` ([judgment — proceed-with-flag]: copy a same-routine sibling's map when one exists, flag it) maps each SR to its REF table + cut threshold + routine counter, read from the
routine `.cc` (`book(_hMeff_*, N,1,1)` → table `dNN`; the `m_eff` cut → threshold). See
`checklists/data-acquisition.md`. Only some search routines bundle this aligned data — confirm at
routine-selection time (`checklists/choosing-routine.md`).

**Background b±δb upgrade — published fitted SR backgrounds (rank 2.5, between the complete tables
and the bundled REF):** when the analysis's results table publishes per-SR **CR-fitted** backgrounds
(e.g. its Table 6: fitted b±δb per SR), prefer them over the REF integral+floor — transcribe to JSON
and pass `rivet_ref_yields.py --fitted-bkg FITTED.json`. The observed n still comes from the REF
integration and **must be cross-checked identical** to it (the script prints both); the analysis's
own background estimate is what makes the counting limit reproduce the published per-SR S95.

## 6.3 Neither bundled nor a likelihood — other sources ([judgment] judgement)
When the analysis has no published likelihood and the routine bundles no aligned data, the SR yields
must come from elsewhere:
- a **reinterpretation database** that digitised this analysis — the HEPData `resources` often list
  SModelS / MadAnalysis 5 / CheckMATE entries (with efficiency maps + observed/background);
- the **published tables** themselves, which on HEPData sit behind the blocked `/download/` path —
  retrieve those numbers with the **Chrome MCP** (`mcp__Claude_in_Chrome__navigate`) if the browser is
  connected (verify first), saving under `<rundir>/outputs/`. This route is a genuine last resort and
  has not been exercised here — treat it as untested and record exactly what was taken and from where.

## 6.3b No HEPData record at all — the digitized-anchor DEGRADED mode (declare it)
Some analyses (esp. preliminary/CONF results) publish no machine-readable tables. The honest
fallback: digitize the needed curve/points off the published figure (note the tool + figure +
date in the run's provenance), declare the result's fidelity label **degraded-anchor**
(`PRODUCT-CONTRACT.md` §5) in `result.json` limitations[] AND the check-in, and treat the
digitization uncertainty as a stated systematic. Never present a digitized anchor as HEPData.

## 6.4 The published exclusion CONTOUR + per-point limit (needed for the step-8 contour deliverable)
A scan→contour reproduction (step 8, RRR Fig 3) compares **against the experiment's published result**:
the mapyde contour overlaid on the **published exclusion contour**, plus the **(mapyde−ATLAS)/ATLAS**
relative-difference map. Both come from HEPData — fetch the complete tables and let the classifier flag
them (general, any analysis):
```bash
$CONDA run -n reinterp python trial-runs/_infrastructure/hepdata_fetch.py \
  --inspire insNNNN --out <rundir>/outputs/hepdata --tables
#   (-n reinterp: hepdata-cli lives ONLY in the reinterp env — the rivet env fails this step)
#   classifies every table; the classified kind + local yaml path live under the manifest's
#   `table_files` key (the top-level `tables` key is names/descriptions only, no kind, no path).
#   The two kinds the contour needs, read from hepdata_manifest.json → table_files[].kind/.file:
#     kind="exclusion-contour" → the limit BOUNDARY in the mass plane (often named "...exclusion sensitivity")
#     kind="limit"             → the per-point σ upper-limit GRID (often "...upper cross-section limits")
```
**Pick tables consistent with the declared figure target.** The manifest's `figure_index` groups
table names by the published figure they belong to ("Figure N …"); the run's figure contract
(`<rundir>/inputs/figure_target.json`, declared in step 2 — `checklists/figure-contract.md`) names
the figure this run reproduces. Choose the contour/limit tables **from that figure's group**
(`hepdata_manifest.json` → `figure_index[<declared figure id>]`) so the exclusion inputs and the
declared figure are the same published result — a contour table from a different figure than the
declared target is a wrong-figure reproduction even if the physics keywords match.

**[judgment] judgement — pick the table(s) for YOUR model.** A record has one contour/limit set *per
simplified model* (slepton vs wino-bino vs higgsino; LH/RH; observed vs expected). Choose the ones that
match the model under test — e.g. for slepton-bino: the slepton "exclusion sensitivity" boundary (the
`exclusion-contour` table whose description says *direct slepton production*) and the slepton "upper
cross-section limits" grid (the `limit` table for *direct slepton scenarios*, a 2-D `(m, Δm) → σ_UL`
table). Note the σ-UL units (fb vs pb) from the table qualifiers — step 8 needs mapyde and ATLAS in the
same units. Feed both to `scan_contour.py`: `--atlas-contour observed=<…contour>.yaml` (the overlay) and
`--atlas-limit <…UL>.yaml` (the difference map). The contour boundary is a polyline `(m → Δm)`; the σ-UL
grid is `(m, Δm) → σ_UL` — `scan_contour.py` reads both HEPData layouts.

**Outputs for step 7:** a bkg-only likelihood (6.1) or `sr_yields.json` (6.2/6.3).
**Outputs for step 8:** the published `exclusion-contour` + per-point `limit` YAMLs (6.4).
**Next:** `steps/07-exclude.md` (per-point limit) → `steps/08-scan.md` (the contour vs ATLAS).
