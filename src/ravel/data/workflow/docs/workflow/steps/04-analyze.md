# Step 4 — Analyze  ·  [judgment] choose · [agent] run

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Run the analysis's selection on the showered events. Two routine types are supported; pick the one
the target analysis provides (`docs/workflow/checklists/choosing-routine.md`). Both apply the analysis selection and
feed the same exclusion in step 7, but they handle **detector effects differently**: the Rivet routine
applies **Rivet's own smearing functions** (no Delphes); SimpleAnalysis consumes **Delphes**-reconstructed
objects (the reference paper's chain). Neither is full Geant4 — see `docs/reference/limitations.md`.

**Run the detector-fidelity gate first (step 3.5, `docs/workflow/checklists/detector-fidelity.md`).** Because the two
paths model the detector differently, the detector model must be *verified/matched* before its yields
are trusted — an un-matched soft-object efficiency biases every SR's acc×eff before the selection runs.
The gate is path-specific: **verify** the Rivet routine's smearing (era-appropriate), or **match** the
Delphes card to the analysis's published performance **then certify** the per-SR acc×eff. Do this once
per routine + detector setup, alongside the cutflow certification (`docs/workflow/checklists/validation.md` §B).

## Option A — Rivet routine (native; ATLAS + CMS; default)
A Rivet routine reads HepMC directly, applies the selection + smearing, and fills observables
(distributions and/or signal-region counts) into a YODA file. It also bundles the published
reference data, so steps 5–7 need no download for the core case.

```bash
$CONDA run -n rivet bash -c "cd <rundir>/build && rivet -a <RIVET_ID> <out.hepmc> -o analysis.yoda"
```
**Verify:** the log prints `Cross-section = … pb` and `Histograms written …`; then
```bash
$CONDA run -n rivet yodals <rundir>/build/analysis.yoda | grep '^/'
```
should list the routine's observables (and SR counters). Keep `analysis.yoda` in `<rundir>/outputs/`.

### Single-weight / non-reentrant routines ([judgment — script-assisted: `rivet --show-analysis` decides; check this first])
Some routines (many recursive-jigsaw / multivariate EWK searches) are **`SINGLEWEIGHT`** and
**`NOTREENTRY`**. Detect it before running (don't assume from the analysis type):
```bash
$CONDA run -n rivet rivet --show-analysis <RIVET_ID> | grep -E "Status|Reentrant"
#   Status: VALIDATED NOTREENTRY SINGLEWEIGHT   ->  the two flags below apply
```
- **SINGLEWEIGHT** → run with **`--skip-weights`** (Rivet 4; the older `--no-multiweight` does **not**
  exist and errors out). The log must print *"Only using nominal weight: variation weights will be
  ignored"*. Generate single-weight events upstream too (`use_syst=False`); getting this wrong silently
  corrupts the yields.
  ```bash
  $CONDA run -n rivet bash -c "cd <rundir>/build && rivet -a <RIVET_ID> --skip-weights <out.hepmc> -o analysis.yoda"
  ```
- **NOTREENTRY** → produce **one** YODA from one run; do **not** `rivet-merge`/`yodamerge` multiple
  runs (reentrant merging is invalid for these). Need more stats → more events in the single run.
- **Verify single-weight integrity** (3 checks): the LHE body has no per-event `<rwgt>`/`<wgt>` tags,
  the HepMC carries exactly one weight per event, and Rivet logged the "nominal weight" line.
  The LHE-side check is automated: `src/ravel/validation/lhe_check.py <lhe>` (run pre-shower,
  `docs/workflow/steps/03-generate.md`) flags multiweight tags and mixed weight signs — a multiweight LHE in a
  single-weight pipeline silently corrupts yields unless `--skip-weights` is used and the events are
  regenerated with `use_syst=False`.

### Cutflow-only routines (no scalar SR counters / no m_eff REF)
Some routines book only `Cutflow` objects (e.g. the EWK jigsaw books 8 cutflows, no `book(_h, dNN)`
distributions and no scalar `/routine/<SR>` counters). For these the bundled-REF + `rivet_ref_yields.py`
path does **not** apply (`docs/workflow/checklists/complex-analysis.md`; the script detects the case and exits
nonzero rather than emitting NaN yields): the per-SR **A×ε is the last/first bin of each cutflow**
(normalisation-invariant under the routine's `normalizeFirst`), and obs/bkg come from integrating the
bundled REF **distribution** tables, not a per-SR yield table. See
`docs/workflow/reference/example-rivet-ewk-path.md`.

## Option B — SimpleAnalysis routine (ATLAS/CMS SR ntuples)
SimpleAnalysis is the SR-yield framework many SUSY analyses publish a routine for. It reads a
detector-level (Delphes) input and writes per-SR yields; `sa2json` turns those into a signal patch for a
published pyhf likelihood.

→ **Native backend:** select a supplied analysis package with a compatible routine interface
and current qualification evidence. Follow `docs/workflow/reference/native-pipeline.md`;
`native_simpleanalysis.py --analysis-package <manifest> --execution-plan <approved-plan>` is
one supervised frontend for counting and two-pass selections. No selection is an installed
default. Inspect the selected package's source, cuts, overlaps, normalization conventions and
qualification scope before admitting yields or inference.

A declarative `native_sa_generic.py` contract supplies object selections, regions and luminosity.
Unsupported observables require source development and qualification. If an upstream executable
interface is required, discover it from supplied source metadata and prepare it through the same
method-decision and compute-admission workflow. Outputs and populations come from the request;
engineering checks alone do not establish experimental acceptance.

## Option C — NO routine exists (custom particle-level; declared, never improvised)
When step 2's resolution (incl. the `route-analysis` skill's re-query loop) finds neither a
Rivet nor a SimpleAnalysis routine, the supported path is a **custom particle-level analysis**:
reproduce the paper's selection from its text in a run-local `build/*.py|*.cc` (the sources are
TRACKED — they regenerate everything), on truth-level objects (`detector_mode=particle-level`).
Every output carries the **particle-level-proxy** fidelity label (`docs/reference/scope.md` §5) and
the no-routine caps are CHECK-IN-1 flags: no detector model, no published acc×eff cert, no
exclusion of record — sensitivity statements only (`stat_mode=sensitivity-expected-only`).
When the custom selection instead runs on **Delphes fast-sim output** (a stock ATLAS/CMS card,
e.g. a τ_h+MET recast), declare `detector_mode=delphes-custom-uncertified` — NOT particle-level, and never buried in an assumptions note: the route
gate WARNs with the no-exclusion-of-record obligation, CHECK-IN 1 must surface the uncertified
status (`validate_checkin` FAILs otherwise), and the upgrade path is per-SR acc×eff
certification against the analysis's published anchors (trap T10; `certify` skill).

Write the custom selection as a declared recipe and run it with the `columnar-analysis` science
mode (`docs/reference/columnar-analysis.md`). It reads Delphes, ntuple and LHE files, applies
published object efficiencies before the selection, and delivers histograms, cutflows and
provenance that step 7 and `ravel fill-template` read. Record the paper's definitions first in a
typed analysis specification; planning then refuses open ambiguities that move yields and checks
that the recipe implements every specified item. Only a step that no recipe can express goes to
the governed `authored-analysis` step (`docs/reference/authored-analysis.md`).

## Option D — EFFICIENCY-MAP FOLDING (no detector simulation; `docs/workflow/reference/effmap-folding.md`)
Fold PUBLISHED efficiency maps over the model point instead of simulating reconstruction:
- **D1 (source-bound SModelS 3.1.1 portfolio):** `ravel model-portfolio plan` preserves the
  supplied complete model, pins its runtime/database and requires a version 2 review policy.
  Default `--data-types all` retains efficiency maps, upper limits and native within-analysis
  combinations, with expected-sensitive selection and native coverage. Use
  `--data-types efficiencyMap` only for an explicitly restricted per-SR map fold.
  Executed evidence defines validation scope. Try D1 BEFORE Option C when no routine exists and the model
  decomposes into simplified-model topologies.
- **D2 (`effmap_fold.py`; the reader and the statistics half are validated, the truth-event maker
  is not built):** per-object efficiency maps from
  HEPData resources (the LLP/displaced standard — trap T2's route; vanilla Delphes silently fails
  those objects). Build plan + validation gate in the reference doc.

## Option E — SHAPE/TEMPLATE FIT (`shape-fit`; the scoped engine)
When the analysis's result is a binned **shape / bump / template fit** (dijet/dilepton/diphoton
invariant-mass, template morphs — trap T-shape), the counting/likelihood machinery cannot
reproduce it, but the scoped engine `shape_fit.py` can: generate the signal at particle level →
build the invariant-mass distribution → the engine refits the paper's own background shape (a
chosen family × a flexible polynomial transfer function) + the signal template and brackets the
CLs limit (details at step 7, `.claude/rules/statistics.md`). **Two per-analysis gates
(non-negotiable):** REPRESENTABILITY (binned 1-D fits only; unbinned/
multi-observable/NN fits downgrade to `blocked-shape-fit`) and **R5** — no limit ships until the
engine reproduces the paper's OWN published fit within tolerance (`shape_fit.py` prints the gate;
validated on one published fit). Until R5 closes, the generator-level shape comparison +
`sensitivity-expected-only` is the shippable offer.

## Which to use
- The analysis ships a **Rivet** routine → Option A (fast, native, plots-vs-data built in).
- The analysis ships a **SimpleAnalysis** routine and/or a **serialized pyhf likelihood** → Option B
  (the SR yields map onto the published likelihood for the strongest limit).
- **Long-lived/displaced objects (trap T2), or no routine + SUSY-cascade topologies** → Option D
  (folding) — for T2 it is the ONLY faithful route; for no-routine SUSY it beats Option C on
  rigor (published A×ε, expected limits).
- **The result is a binned shape/bump/template fit** → Option E (`shape_fit.py`), R5-gated.
- No routine, not foldable, not a shape fit → Option C (declared particle-level).
- Some analyses have several; record which you used and why (the trap-sweep output justifies it).

**Next:** `docs/workflow/steps/05-visualize.md`
