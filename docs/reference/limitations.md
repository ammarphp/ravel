# Known limitations

A [September 2026 correction](../../evidence/audits/2026-09-05-native-fidelity/README.md)
to the eRJR common boost improves SR-low on retained events but still fails the
acceptance threshold. Older three-lepton container parity is historical and no
longer describes that corrected selection. Squark/gluino cutflow differences and
compressed-slepton mass-plane fidelity remain unresolved.


Honest registry of what the pipeline does not yet do (or does approximately). Each entry: the
limitation, its impact, and the plan. The audit (`audit.py`) reads this; closing an item should flip
the corresponding dimension.

Dated investigations are recorded in
[`limitations-triage.md`](../development/limitations-triage.md). Its July census
is historical; the September addendum reopens compressed-slepton attribution,
signal uncertainties and control-region signal modeling with measured evidence.
See the [RRR diagnosis and research program](../research/2026-09-05-rrr-diagnosis-and-research-program.md).

## Physics fidelity
- **Cutflow fidelity is tiered, not perfect (R1).** Acceptance×efficiency is now certified against
  published cutflows (`framework/validation/`, `validate_cutflow.py`) with a tiered + attribution gate;
  driving-SR residuals range from a few % (squark) to ~13% (gluino — attribution CORRECTED
  Session-2/S5: the high-multiplicity excess is TUNE-dominated, A14-vs-Monash moves 13.2%→4.4%,
  not merging; see the shower-tune entry below). Compressed /
  soft-lepton points remain unresolved. The September RRR audit identifies numerical,
  exposure and likelihood-model failures, so the remaining discrepancy cannot yet
  be assigned to an intrinsic fast-simulation or LO floor.
- **Higher-order σ is a flat k-factor, not a recomputation.** (Updated Session 2 — the old "LO
  cross-sections" gap is closed for the benchmark cases: all four carry a verified like-for-like
  WG NLO+NLL/NNLL k in `benchmarks/cases.json`, the ONLY k authority; per-run RESULT.md
  addenda record the σ-source.) Remaining approximation: k is applied flat (no per-SR shape change),
  and k<1 happens for the squark cases (LO-PDF overshoot) — i.e. a bare-LO limit is NOT always
  conservative. Degeneracy/charge conventions of the WG grids are the standing trap
  (`.claude/rules/statistics.md`); the slepton run keeps its documented flat k=1.18.
- **PDF and scale uncertainty bands are NOT propagated to acc×eff or limits.**
  Historical benchmark recipes used a single nominal nn23lo1 PDF and default
  dynamic scale with `use_syst = False`. The compressed-slepton campaigns instead
  include cteq6l1 and nn23nlo configurations; requested options and effective cards
  must be distinguished. These retained single-weight results do not propagate
  PDF-member or renormalization/factorization-scale acceptance variations into
  their limits. The central normalization is corrected with the registry k;
  the WG uncertainty envelope on that central value is not propagated. Full band
  propagation needs `use_syst=True` multiweight LHEs **plus** a multiweight-aware analysis path,
  which conflicts with the current single-weight Rivet invocation and with `lhe_check.py`, which
  deliberately flags multiweight LHEs as a leak risk; the honest resolution (per-weight Rivet runs
  or post-hoc LHE reweighting, then re-locking the gate) is a Phase-2/Session-3 build. Until then,
  retained limits include only the nuisance model actually supplied to each fit;
  there is no calibrated detector/PDF uncertainty band implied by a residual floor.
- **Shower tune: certified runs use Pythia 8.312's default Monash 2013, not ATLAS's A14.** The
  published acc×eff grids we certify against were produced with A14+NNPDF2.3LO (`Tune:pp = 21` in
  this Pythia; default-when-absent = Monash, `Tune:pp = 14`). Measured A/B on the gluino benchmark
  case (same LHE, same seed, 10k events; Session 2/S5): A14 shifts high-jet-multiplicity SR A×ε by
  −8% (5j) to −17% (6jm) vs Monash, moving the driving-SR residual 13.2% → 4.4% and the cert verdict
  WARN → PASS — i.e. most of the gluino case's high-multiplicity *excess* is tune, not physics.
  Certified runs and the benchmark gate deliberately stay Monash until the pipeline-wide tune policy
  (+ re-locks, + interplay with merging) is decided — STILL OPEN post-Session-3; per-experiment
  emulation (A14/CUETP8M1 by era) was adopted for NEW runs only (`docs/development/status.md`). Numbers:
  `docs/research/reviews/shower-decay.md`.
- **Decay spin correlations / polarization are not modeled in SLHA-table decays.** Pythia decays
  SLHA-table channels by phase space: exactly correct for scalar parents (q̃ → q χ̃₁⁰ — a scalar has
  no spin to correlate); mild for gluino 3-body via heavy off-shell squarks; a **real modeling loss**
  for χ̃₁±/χ̃₂⁰ → W/Z + χ̃₁⁰ chains, where the W/Z polarization is NOT propagated into the lepton
  angular distributions (affects lepton pT/angular acceptance; secondary to the attributed fast-sim
  floor at the certified C1N2 point, Δm=200 with on-shell bosons). Tau spin-density from SLHA-chain
  parents is likewise not fully propagated (few-% effect on leptonic-tau contributions to lepton
  SRs). Proper fix: **MadSpin at LHE level** (Session-3 candidate). (Correction of a Wave-1 diagnosis
  note: `SpaceShower:rapidityOrder` orders ISR emissions in rapidity — it has nothing to do with
  decay spin correlations, and `Check:rapidityOrder` does not exist.)
- **Fast detector model (no Geant4).** The **Rivet path** uses **Rivet's smearing functions**; the
  **SimpleAnalysis path** uses the **Delphes** card — two different fast approximations to full
  simulation (the Rivet path is a deliberate divergence from the reference paper's Delphes chain).
  The RRR-derived Delphes path does include soft-lepton tuning, but its predictive
  accuracy still needs held-out, exclusive-bin validation. Current evidence does
  not establish detector modeling as the dominant cause of the compressed-plane
  residual. Per-analysis cutflow checks have only their recorded point/domain scope.

- **R6 visual fidelity is TWO-TIER since 2026-07-07 (CR-016): layout hygiene is now
  MACHINE-GATED** (`mplhep_style.lint_figure` inside every house renderer — legend/annotation
  occlusion, box overlaps, tick collisions fail loud at save); figure CONTENT (right series,
  binning, published-form fidelity) remains checklist-verified pending the figure-spec + critique
  loop (roadmap C13/M4b). The original entry follows for the content half:
  The registered overlay figures
  are produced in the shared mplhep house style (`src/ravel/plotting/mplhep_style.py`) and
  eyeball-verified against `docs/workflow/checklists/plot-criteria.md`; the benchmark's provenance gate
  checks only path + non-empty size, so figure *content* could regress silently. The drawn
  signal+background curve is scaled to the registry k-factor (`--sig-scale`) while the on-disk YODA
  stays LO — the figure label states the normalization. The C1N2 run's overlay is produced by a
  run-local script kept as the certified-run record; it predates the house-style upgrade (frameless
  legend, an annotation that collides with the ATLAS label). → plan: Phase-2 R6 visual-fidelity
  scoring of the overlay itself (`docs/validation/benchmark-guide.md` hooks).

## Statistical / data
- **Signal uncertainties are absent from the retained compressed native patches.**
  All 156 audited patches contain only the signal-strength normfactor. A previous
  estimate that this was confined to harmless tail bins is unsupported for these
  campaigns: some CR004 patches have only three selected events. Per-bin `sumw`
  and `sumw2`, and a justified correlated signal nuisance model, remain required.
  At one ATLAS 150/130 GeV benchmark, removing all published signal nuisance
  modifiers strengthens the observed limit by about 5.4%; this does not isolate
  MC uncertainty from the other signal uncertainties. See the
  [controlled refits](../../evidence/audits/2026-09-05-rrr-refits/README.md).
- **Published-grid certification off-node is 1-D, span-limited.** `validate_cutflow.py` interpolates
  the published acc×eff grid linearly along ONE axis only (fixed-LSP preferred), and only across
  brackets ≤ `--interp-max-span` (default 200 GeV); sparser regions fall back to a **flagged**
  nearest node (`NEAREST` in the per-SR `node` field). Known instance: the ins1458270 gluino grid
  has NO (1000,100) node — the certified 13.2% residual is measured against (1000,0), i.e. splitting
  1000 vs our 900 (flagged since Session 2/S4; a registry-notes correction is an open item). A 2-D
  interpolation on the triangular grids is the Phase-2 upgrade.
- **Counting model is an approximation.** For analyses without a published likelihood, the per-SR
  single-bin counting model (best-expected SR; uncorrelated constraints in `--combined` mode) does
  not capture SR correlations or the full systematic model. Prefer the published likelihood; for the
  background input prefer the analysis's **published CR-fitted b±δb** (`rivet_ref_yields.py
  --fitted-bkg`, rank 2.5 in `docs/workflow/checklists/data-acquisition.md`) over the REF integral with
  its uncertainty floor — that input difference alone was the squark cases' 1.49×→1.01 per-SR s95
  recovery.
- **Likelihood↔selection pairing checks structure, not negligible control-region signal.**
  The retained compressed chain patches the signal regions and leaves six control
  regions without signal contributions. At the published ATLAS 150/130 GeV anchor,
  removing control-region signal from the already nuisance-stripped signal model
  strengthens the observed limit by a further approximately 8.7%. Combined signal
  nuisance and control-region omissions strengthen it by about 13.7%. This is one
  controlled benchmark, not a global correction. The current native selection
  needs validated control-region definitions and signal nuisance responses before
  a claim of full signal-model reproduction. A successful structural pairing check
  cannot close this limitation.

- **Result-quality fixes land via the CHANGES-REGISTRY** (`docs/development/change-registry.md`):
  the pyhf µ-floor on hyper-excluded points (CR-001) and the native prep dropping
  `[madgraph.run.options]` (CR-002) were both FIXED 2026-07-06; every native sample generated
  before that date used ineffective requested generator options; the audited original
  scan retained the generator's effective `ptj=20` setting. CR004 also changed the
  effective cut, so its PDF comparison is confounded. Floored/capped
  µ₉₅ values are tagged `quality=floored|capped` and rendered as bounds, never limits.

## Coverage / complexity
- **Complex routines: demonstrated, not yet broad.** The recursive-jigsaw EWK search
  `ATLAS_2018_I1676551` has a historical end-to-end, cutflow-only PASS record.
  The September corrected selection still fails acceptance, so that older record
  does not certify its current fidelity. `docs/workflow/checklists/complex-analysis.md`
  documents the per-region / cutflow-only handling.
  Breadth across more multi-bin / control-region analyses is the remaining work (Session 3).
- **Native SimpleAnalysis backend covers a PORTED SET, not all routines (CR-005 generalized
  2026-08-16).** The VM-free native SA — the step-8 DEFAULT — now has a shared core
  (`sa_native_core.py`, primitives + SA header-verbatim ID bits + pinned helper semantics), three
  historically oracle-compared routines (EwkCompressed2018 141/141 ·
  ZeroLeptonDiscovery2018 10/10 · EwkThreeLeptonERJR2018 9/9 on shared inputs).
  The old eRJR parity record predates the corrected boost and does not describe
  the current selection. The backend also has a declarative
  spec engine for plain cut-based routines (`native_sa_generic.py`), and a proven ~half-session
  porting recipe with a mechanical acceptance gate (`cr005_validate.py`; recipe in
  `docs/workflow/reference/native-pipeline.md`). Remaining honest gaps: unported routines still take
  the per-use container fallback; the two new ports carry the bit-for-bit code validation but not
  yet their per-analysis acc×eff certifications or µ95 anchors (named follow-ups, registry
  CR-005).
- **SimpleAnalysis routine availability (container fallback).** Routines live in the `:master`
  container image; an analysis whose `.cxx` is not in that image needs a runtime-add or container
  rebuild (container build rights).

<!-- CAPABILITY-STATUS:SHAPEFIT:BEGIN (auto-generated by scripts/gen_status.py from
     benchmarks/capabilities.json — DO NOT EDIT inside these markers) -->
~40% of the search population (8/20, pre-registered census) is shape/template-fit; these route to the scoped `shape_fit.py` engine (`stat_mode=shape-fit`), R5-gated per analysis. Only an unrepresentable fit (unbinned / multi-observable / per-event NN) downgrades to the named `blocked-shape-fit` refusal + generator-level offer (PRODUCT-CONTRACT §6.1). Matrix: P4 partial, G2b built.
<!-- CAPABILITY-STATUS:SHAPEFIT:END -->

## Infrastructure
- **MadAnalysis5 built; CheckMATE2 compiled but runtime-blocked by a Pythia ABI conflict.**
  **MA5** 1.11.1 is built from source (`ma5 -sf`) — a working second cross-check engine.
  **CheckMATE2**'s C++ **compiles** (564 objects), but it has **no working runtime** (the contradiction
  with older records that said "binary not built" resolves to: the engine compiles, the usable
  binary is blocked — see below). The build needed, in order: autotools (conda-installed — absent on host);
  a **Delphes source-layout shim** (`checkmate2/delphes_shim/` mapping `external/{ExRootAnalysis,fastjet}`
  + `classes/modules/lib` into the conda env, since conda ships headers under `include/`, not the
  source tree); `-Wno-c++11-narrowing` (gcc-vs-clang); **Pythia 8.244** in a dedicated `py82` env (the
  conda 8.312 removed `Info::errorMsg`, which CheckMATE uses — it supports only the 8.2 series); a
  full-path Pythia link + `install_name_tool` repoint (recast's 8.312 shadowed py82's 8.244). The
  **remaining blocker** is fundamental: recast's conda **`libDelphes` was built against Pythia 8.312**
  (it needs `Pythia8::WeightsBase`, an 8.3 class), but CheckMATE's `fritz` needs 8.244 — the two Pythias
  cannot coexist in one process. **The clean remediation** is a Pythia-free `libDelphes` built against
  the same stack, then re-point the shim → relink; attempted from Delphes-`master`, which hit a separate
  header/ROOT-dictionary mismatch vs the conda ROOT (`out-of-line definition … does not match any
  declaration` in `DelphesHepMC2Reader`). **Bounded remaining path:** build a *pinned* Delphes release
  (e.g. 3.5.0) against the `py82` Pythia + conda ROOT, or a Pythia-8.2-consistent conda Delphes. The
  Python driver additionally needs `future`/`scipy`/`pyhf`/`setuptools` on the host's Python 3.14.
  This is a packaging/version-pinning task, not a code defect — the engine itself is built. **Cross-check coverage (R7) does not depend on this:** SModelS (working:
  r_obs=8.07 vs our 1/µ₉₅≈10 on ATLAS-SUSY-2015-06) **+** MadAnalysis5 are two independent engines;
  CheckMATE is the third, redundant one.
- **Recursive-jigsaw EWK search — historical implementation milestone, fidelity reopened.**
  The corrected September retained-event selection still fails the acceptance threshold,
  as described at the top of this page. The earlier C1N2→WZ (300,100) run on
  `ATLAS_2018_I1676551` recorded a historical cutflow-only PASS; it surfaced and fixed a
  real EWKino NLO charge-state issue (`nlo_xsec.py` now guards k<1) and the MASS/MSOFT/MODSEL card trap
  (`docs/workflow/checklists/model-cards.md`).
- **Container path (the legacy SA fallback only) is slow.** When no native port exists, the
  SimpleAnalysis/Delphes chain runs amd64 under podman emulation: ~9 h/point and strictly
  sequential. The native backend (the default where it exists) is ~30–50 min/point, parallel.

## Resolved this pass (kept for provenance)
- Full HEPData tables ARE programmatically retrievable: `hepdata-cli download <inspire> -i inspire -f yaml`
  pulls the complete table set past the Cloudflare `/download/` 403; the likelihood downloads via the
  open `/record/resource/<id>?view=true` endpoint. The browser is not required for either.
