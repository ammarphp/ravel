# Checklist — acquiring the analysis's data + likelihood  ·  [judgment] / [agent]

Goal (step 6): the analysis's own statistical inputs for step 7 — a published likelihood if one
exists, else observed + SM background per signal region. What is reachable depends on the endpoint
(tested on this host):

| Source | Reachable how | Gives | Notes |
|---|---|---|---|
| HEPData **resource** endpoint `/record/resource/<id>?view=true` | **open** (urllib / `pyhf.contrib`) | the published **likelihood** archive | preserves the supplied likelihood structure |
| HEPData **complete tables** (the full-table route) | **`hepdata-cli`** (open; bypasses the `/download/` 403), auto-falling back to the **open internal endpoint** `/record/data/<recid>/<table_id>/<version>` (recid + table ids + version from the record JSON) when hepdata-cli is missing or blocked | every numeric table — SR yields, **cutflows/acceptance×eff**, covariance, and (for step 8) the **`exclusion-contour`** boundary + the per-point **`limit`** (σ-UL) grid | `hepdata_fetch.py --tables` classifies each (kind in the manifest); tested, no browser; BOTH routes verify the download (cli: submission.yaml parses + data_files present; fallback: every listed table lands with non-empty `values[]`) + exit nonzero on a partial fetch; the manifest records `tables_route`. For the step-8 contour comparison deliverable, pick the `exclusion-contour` + `limit` tables for YOUR model (one set per simplified model) — see `docs/workflow/steps/06-acquire-data.md` §6.4 → `scan_contour.py --plot-spec <plot-spec.json>` ([supplied reference layers](figure-contract.md#declarative-scan-plots)) |
| published **fitted SR backgrounds** (the analysis results table, e.g. its Table 6: CR-fitted b±δb per SR) | transcribe from the paper (arXiv LaTeX/PDF on disk) | the analysis's **own** background estimate per SR — the preferred counting-model b±δb | feed via `rivet_ref_yields.py --fitted-bkg`; observed n **must be cross-checked identical** to the REF integration |
| Rivet **bundled REF** | local file | observed + SM background per bin → counting | offline copy; only some search routines bundle it |
| HEPData table `/download/` web pages | 403 (Cloudflare) → browser | — | superseded by `hepdata-cli` + the `/record/data` fallback; browser not needed |

Quick combined fetch (likelihood + complete tables):
```bash
$CONDA run -n reinterp python scripts/run.py ravel.workflow.hepdata_fetch \
  --inspire insNNNN --out <rundir>/outputs/hepdata --download-likelihood --tables
```

## 1. Published likelihood (preferred) — programmatic
```bash
$CONDA run -n rivet python scripts/run.py ravel.workflow.hepdata_fetch \
  --routine <RIVET_ID> --out <rundir>/outputs/hepdata --download-likelihood
```
The JSON API (`?format=json`) lists `record.resources`; the helper finds the likelihood (file_type
`HistFactory`/`pyhf`) and downloads+extracts the bkg-only workspace via the open resource endpoint.
Pair it with a signal patch built from your model (SimpleAnalysis → `sa2json`) in step 7. The
mapyde-bundled likelihoods (`…/share/mapyde/likelihoods/`) are a curated offline copy.

## 2. No likelihood — per-SR counts from Rivet's bundled REF
```bash
$CONDA run -n rivet python scripts/run.py ravel.physics.rivet_ref_yields \
  --signal <rundir>/outputs/<sig>.yoda \
  --ref <…>/envs/rivet/share/Rivet/<RIVET_ID>.yoda.gz \
  --spec <rundir>/inputs/sr_spec.json --out <rundir>/outputs/sr_yields.json
```
**Write `sr_spec.json` from the routine `.cc`** ([judgment]) — one entry per SR:
- `ref_table`: from `book(_hMeff_<SR>, N,1,1)` → table `dNN-x01` (the SR's distribution).
- `threshold_gev`: the SR's final kinematic cut (e.g. the `m_eff(incl) > …` in `fillnext(...)`).
- `counter`: the routine's SR counter name (e.g. `2jl`).
- `data_y` / `bkg_y`: which y-series is observed vs background — confirm by reading the REF (data is
  integer with zero error; background carries an uncertainty).

The script integrates the REF above each threshold → (observed, background ± unc), pairs it with the
signal counter, and prints a cross-check (`xcheck`) that must match the counter — **enforced**:
|xcheck/signal − 1| > `--xcheck-tol` (default 10%) exits nonzero, because a drift means the spec's
threshold no longer matches the routine's actual cut (re-derive `sr_spec.json` from the routine `.cc`
whenever the routine/Rivet version changes — the spec is a frozen copy of the routine's cuts, not an
independent truth). It also hard-errors on **cutflow-only** routines (no scalar counters — use the
run-local adapter path, `docs/workflow/reference/example-rivet-ewk-path.md`) and on a zero REF background
integral (threshold beyond the REF range). Background uncertainty: per-bin REF errors are partially
correlated, so the quadrature sum understates the inclusive-SR systematic — the script floors the
relative SR uncertainty at `--bkg-rel-floor` (default 0.15); a published inclusive-region uncertainty
is better when available (REF error bars are also symmetrised via `errAvg`).

**Preferred b±δb — the published fitted SR backgrounds** (rank 2.5 in the table above). When the
analysis's results table publishes per-SR **CR-fitted** backgrounds, transcribe them into a small
JSON (`{"<sr>": {"b":…, "db":…}, "_source": "<citation>"}`) and pass
`rivet_ref_yields.py --fitted-bkg FITTED.json`: the fitted values replace the integrated b/δb (the
analysis's own background estimate beats the pre-fit-MC REF integral + floor — this is exactly the
input difference that turns a ~1.5× per-SR s95 recovery into ~1.0×). The observed n is unaffected,
and **must be cross-checked identical to the REF integration** (the script prints both); a mismatch
means the SR↔table mapping is wrong. The output records which source was used per SR.

For a **SimpleAnalysis** routine the per-SR yields come from the run ntuple; `sa2json` produced the
signal patch in step 4, which goes with the bkg-only likelihood from step 1.
