# Step 6 — Acquire the analysis's data + likelihood  ·  [judgment] / [agent]

## On the controller

On a controller run this step is plan step `acquire.data`: an `acquire` step (operation `acquire-published`) that
runs `ravel.workflow.hepdata_fetch` for the record the route analysis names (`hepdata_record`), through the governed
acquisition path, and writes `outputs/hepdata/hepdata_manifest.json`. The route adapter refuses a manifest that
names no table and no likelihood. The step needs no compute rung, so it can run while the smoke rung is reviewed.
When the run's environment profile records no network egress, the plan runs this step with `--offline
--offline-mirror <mirror>` instead: the record is read from the site mirror's offline fixture
(`<mirror>/hepdata/ins<digits>/`), a missing copy fails the step with no network attempt, and
`parameters.source_mode` records the switch. The controller admits that form only under such a profile.

On a run the controller does not own, the host follows the procedure below as before; such a run's
results read NOT GOVERNED, and the controller refuses its legacy commands for a controller-owned run.

## Procedure

The controller acquisition uses the registered `resource_census --fetch-published-data` entry, which preserves
the data reader's source restrictions and completeness checks. Acquisition is a trusted controller action;
scientific launches and workers retain their network restrictions. The adopted data manifest embeds each
acquired member's relative path, digest and exact bytes in `acquired_members`, so tables and likelihoods remain
available after only declared outputs cross custody. Nonzero acquisition, symlinks and output beyond the
approved byte ceiling refuse adoption.

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

The exclusion (step 7) needs the analysis's own statistical inputs: ideally its published likelihood;
otherwise the observed counts + SM background per signal region. These live in different places, and
not all are reachable the same way. The order below reflects what actually works (tested on this host).

For offline software controls, use `hepdata_fetch --offline-fixture <directory>`
with `--tables` and/or `--download-likelihood`. This reads only captured local
JSON and refuses missing members without network fallback. `--offline` also
refuses remote-source arguments. The layout and statistics handoff are in the
[statistics core reference](../../reference/statistics-core.md). Synthetic
fixtures establish software behavior, not published-data acquisition evidence.

## 6.1 Published likelihood — programmatic, no browser (preferred)
If the analysis published a serialized likelihood, it is the
strongest input and it downloads directly. The HEPData JSON API (`?format=json`) lists the record's
`resources`, and the resource endpoint `/record/resource/<id>?view=true` is open (unlike the bulk/
table `/download/` paths, which return 403):
```bash
$CONDA run -n rivet python scripts/run.py ravel.workflow.hepdata_fetch \
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
$CONDA run -n rivet python scripts/run.py ravel.physics.rivet_ref_yields \
  --signal <rundir>/outputs/<sig>.yoda \
  --ref <…>/envs/rivet/share/Rivet/<RIVET_ID>.yoda.gz \
  --spec <rundir>/inputs/sr_spec.json --out <rundir>/outputs/sr_yields.json
```
`sr_spec.json` ([judgment — proceed-with-flag]: copy a same-routine sibling's map when one exists, flag it) maps each SR to its REF table + cut threshold + routine counter, read from the
routine `.cc` (`book(_hMeff_*, N,1,1)` → table `dNN`; the `m_eff` cut → threshold). See
`docs/workflow/checklists/data-acquisition.md`. Only some search routines bundle this aligned data — confirm at
routine-selection time (`docs/workflow/checklists/choosing-routine.md`).

**Background b±δb upgrade — published fitted SR backgrounds (rank 2.5, between the complete tables
and the bundled REF):** when the analysis's results table publishes per-SR **CR-fitted** backgrounds
(e.g. its Table 6: fitted b±δb per SR), prefer them over the REF integral+floor — transcribe to JSON
and pass `rivet_ref_yields.py --fitted-bkg FITTED.json`. The observed n still comes from the REF
integration and **must be cross-checked identical** to it (the script prints both); the analysis's
own background estimate is what makes the counting limit reproduce the published per-SR S95.

## 6.3b No HEPData record at all — the digitized-anchor DEGRADED mode (declare it)
Some analyses (esp. preliminary/CONF results) publish no machine-readable tables. The honest
fallback: digitize the needed curve/points off the published figure (note the tool + figure +
date in the run's provenance), declare the result's fidelity label **degraded-anchor**
(`docs/reference/scope.md` §5) in `result.json` qualifications[] AND the check-in, and treat the
digitization uncertainty as a stated systematic. Never present a digitized anchor as HEPData.

## 6.4 Published reference results for a scan comparison (when the plan declares one)
When the plan compares a scan (step 8) with a published result, the reference boundaries and
per-point values usually come from HEPData — fetch the complete tables and let the classifier flag
them (general, any analysis):
```bash
$CONDA run -n reinterp python scripts/run.py ravel.workflow.hepdata_fetch \
  --inspire insNNNN --out <rundir>/outputs/hepdata --tables
#   (-n reinterp: hepdata-cli lives ONLY in the reinterp env; any other env auto-falls back to
#    the open /record/data/<recid>/<table_id>/<version> endpoint — same verification, manifest
#    records tables_route)
#   classifies every table; the classified kind + local yaml path live under the manifest's
#   `table_files` key (the top-level `tables` key is names/descriptions only, no kind, no path).
#   Two kinds a limit comparison commonly uses, read from hepdata_manifest.json → table_files[].kind/.file:
#     kind="exclusion-contour" → a limit BOUNDARY over the published axes
#     kind="limit"             → per-point upper limits on the published lattice
```
**Pick tables consistent with the declared figure target.** The manifest's `figure_index` groups
table names by the published figure they belong to ("Figure N …"); the run's figure contract
(`<rundir>/inputs/figure_target.json`, declared in step 2 — `docs/workflow/checklists/figure-contract.md`) names
the figure this run reproduces. Choose the contour/limit tables **from that figure's group**
(`hepdata_manifest.json` → `figure_index[<declared figure id>]`) so the exclusion inputs and the
declared figure are the same published result — a contour table from a different figure than the
declared target is a wrong-figure reproduction even if the physics keywords match.

**[judgment] judgement — pick the table(s) for YOUR model.** A record often has one boundary and
limit set *per model or scenario* and per role (observed vs expected). Choose the ones whose
description matches the model and axes under test, and record why. Note the units from the table
qualifiers and convert so both sides of the comparison use the same units and the same model-rate
basis. For a limit plane, supply the selected numerical records and their literal coordinate
definitions in `scan_contour.py --plot-spec <plot-spec.json>` as described in the
[declarative figure contract](../checklists/figure-contract.md#declarative-scan-plots).
Reference layers pin the matching observed/expected quantity and production basis;
residual layers supply the reference unit, normalization multiplier and exact-match tolerance.
No implicit coordinate conversion or reference interpolation occurs. Other reference forms
(curves along one axis, intervals) go into a `parameter_plane` specification as `references`.

**Outputs for step 7:** a bkg-only likelihood (6.1) or `sr_yields.json` (6.2/6.3).
**Outputs for step 8:** the reference tables the plan's comparison declares (6.4).
**Next:** `docs/workflow/steps/07-exclude.md` (per-point limit) → `docs/workflow/steps/08-scan.md` (when the request asks for a scan).
