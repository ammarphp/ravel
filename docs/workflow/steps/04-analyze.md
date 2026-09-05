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

→ **DEFAULT: the native VM-free backend** — no podman, no container, no x86 emulation. See
`docs/workflow/reference/native-pipeline.md`. For EwkCompressed2018 / slepton-bino it runs the WHOLE chain
(MadGraph → Pythia8 → DelphesHepMC3 → native SimpleAnalysis → sa2json → pyhf) **natively** in
**~30–50 min full-chain per point** (the MadGraph stage itself is minutes; see step 8's compute
reality); `scan_orchestrator.py launch --backend native` (step 8) drives it
across a grid, and `run-pipeline-native.sh` runs a single point. **This is the path for this analysis.**

→ **LEGACY FALLBACK (unported analyses only): the container path.** `docs/workflow/analysis-simpleanalysis/` runs
SimpleAnalysis in the ATLAS x86 container under `mapyde` + a podman VM (~9 h/point under emulation,
strictly sequential; the VM is provisioned per-use and torn down after — see
`docs/workflow/reference/native-pipeline.md` §oracle). Use ONLY when the chosen analysis is neither in the
native PORTED SET — `EwkCompressed2018` (141/141 bit-for-bit), `ZeroLeptonDiscovery2018` (10/10),
`EwkThreeLeptonERJR2018` (9/9); `native_simpleanalysis.py --routine <Name>` — nor expressible as
a `native_sa_generic.py` declarative spec. Porting the next routine is a ~half-session recipe
(`docs/workflow/reference/native-pipeline.md` §porting, CR-005): transcribe on `sa_native_core`, then the
bit-for-bit oracle gate (`src/ravel/validation/validate_native_parity.py`). Either path leaves the per-SR yields + (when
published) the signal patch in `<rundir>/outputs/`, consumed by step 6/7.

## Option C — NO routine exists (custom particle-level; declared, never improvised)
When step 2's resolution (incl. the `route-analysis` skill's re-query loop) finds neither a
Rivet nor a SimpleAnalysis routine, the supported path is a **custom particle-level analysis**:
reproduce the paper's selection from its text in a run-local `build/*.py|*.cc` (the sources are
TRACKED — they regenerate everything), on truth-level objects (`detector_mode=particle-level`).
Every output carries the **particle-level-proxy** fidelity label (`docs/reference/scope.md` §5) and
the no-routine caps are CHECK-IN-1 flags: no detector model, no published acc×eff cert, no
exclusion of record — sensitivity statements only (`stat_mode=sensitivity-expected-only`).
When the custom selection instead runs on **Delphes fast-sim output** (a stock ATLAS/CMS card,
e.g. a τ_h+MET recast), declare `detector_mode=delphes-custom-uncertified` (CR-134,
PRODUCT-CONTRACT §2) — NOT particle-level, and never buried in an assumptions note: the route
gate WARNs with the no-exclusion-of-record obligation, CHECK-IN 1 must surface the uncertified
status (`validate_checkin` FAILs otherwise), and the upgrade path is per-SR acc×eff
certification against the analysis's published anchors (trap T10; `certify` skill).

## Option D — EFFICIENCY-MAP FOLDING (no detector simulation; `docs/workflow/reference/effmap-folding.md`)
Fold PUBLISHED efficiency maps over the model point instead of simulating reconstruction:
- **D1 (BUILT, SUSY-shaped):** SModelS folds published per-SR A×ε grids —
  `reinterpret_db.py --data-select efficiencyMap` (reinterp env) → per-analysis r_obs/r_exp +
  best SR. Live-verified 2026-07-07. Try D1 BEFORE Option C when no routine exists and the model
  decomposes into simplified-model topologies.
- **D2 (BUILT; `effmap_fold.py`, selftest 5/5; reader + statistics-half validated on
  ATLAS-SUSY-2016-06; truth-event-maker = named last mile):** per-object efficiency maps from
  HEPData resources (the LLP/displaced standard — trap T2's route; vanilla Delphes silently fails
  those objects). Build plan + validation gate in the reference doc.

## Option E — SHAPE/TEMPLATE FIT (`shape-fit`; the scoped engine, Option B)
When the analysis's result is a binned **shape / bump / template fit** (dijet/dilepton/diphoton
invariant-mass, template morphs — trap T-shape), the counting/likelihood machinery cannot
reproduce it, but the scoped engine `shape_fit.py` can: generate the signal at particle level →
build the invariant-mass distribution → the engine refits the paper's own background shape (a
chosen family × a flexible polynomial transfer function) + the signal template and brackets the
CLs limit (details at step 7, `.claude/rules/statistics.md`). **Two per-analysis gates
(PRODUCT-CONTRACT §6.1, non-negotiable):** REPRESENTABILITY (binned 1-D fits only; unbinned/
multi-observable/NN fits downgrade to `blocked-shape-fit`) and **R5** — no limit ships until the
engine reproduces the paper's OWN published fit within tolerance (`shape_fit.py` prints the gate;
R5-validated on ins2813982, CR-027). Until R5 closes, the generator-level shape comparison +
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
