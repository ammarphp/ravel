# Known limitations

This page lists what the pipeline does not do, or does only approximately. Each entry gives the
limitation and its impact. The audit (`audit.py`) reads this page; closing an item should flip the
corresponding dimension.

## Physics fidelity
- **Cutflow fidelity is tiered, not perfect (R1).** Acceptance×efficiency is certified against
  published cutflows with `validate_cutflow.py` and a tiered + attribution gate. A residual above
  its tier needs an attributed cause; a remaining discrepancy cannot be assigned to an intrinsic
  fast-simulation or LO floor without evidence.
- **Higher-order σ is a flat k-factor, not a recomputation.** The k-factor is applied flat, with
  no per-SR shape change. A k below one can occur (LO-PDF overshoot), so a bare-LO limit is not
  always conservative. Degeneracy and charge conventions of the cross-section grids are a standing
  trap (`.claude/rules/statistics.md`).
- **PDF and scale uncertainty bands are not propagated to acc×eff or limits.** Single-weight
  generation (`use_syst = False`) carries no PDF-member or renormalization/factorization-scale
  acceptance variation, and the uncertainty envelope on a central k-factor is not propagated.
  Full band propagation needs `use_syst=True` multiweight LHEs plus a multiweight-aware analysis
  path; `lhe_check.py` deliberately flags multiweight LHEs as a leak risk. A limit includes only
  the nuisance model actually supplied to its fit.
- **Shower tune is a declared choice.** Pythia 8.312 defaults to Monash 2013 (`Tune:pp = 14`);
  published acceptance grids are often produced with an experiment tune such as A14
  (`Tune:pp = 21`). High-jet-multiplicity acceptance is tune-sensitive, so record the tune and
  treat a tune mismatch as a candidate cause of a residual.
- **Decay spin correlations / polarization are not modeled in SLHA-table decays.** Pythia decays
  SLHA-table channels by phase space: exact for scalar parents, mild for gluino 3-body decays via
  heavy off-shell squarks, and a real modeling loss for χ̃₁±/χ̃₂⁰ → W/Z + χ̃₁⁰ chains, where the
  W/Z polarization does not reach the lepton angular distributions. Tau spin density from
  SLHA-chain parents is likewise not fully propagated. The fix is MadSpin at LHE level.
  `SpaceShower:rapidityOrder` orders ISR emissions in rapidity and has nothing to do with decay
  spin correlations.
- **Fast detector model (no Geant4).** The Rivet path uses Rivet's smearing functions; the
  SimpleAnalysis path uses a Delphes card. Both are fast approximations to full simulation, and
  their predictive accuracy needs held-out, exclusive-bin validation per analysis. Per-analysis
  cutflow checks have only their recorded point and domain scope.
- **Figure content is checklist-verified.** Layout hygiene is machine-gated
  (`mplhep_style.lint_figure` inside every house renderer fails on legend/annotation occlusion,
  box overlaps and tick collisions). Figure content (the right series, binning and published-form
  fidelity) is verified against `docs/workflow/checklists/plot-criteria.md`, not scored
  automatically. A drawn signal+background curve scaled with `--sig-scale` differs from the
  on-disk LO YODA; the figure label states the normalization.

## Statistical / data
- **Signal uncertainties must be supplied.** A signal patch that contains only the
  signal-strength normfactor omits MC-statistical, detector and theory uncertainties. Per-bin
  `sumw` and `sumw2`, and a justified correlated signal nuisance model, are required for a full
  signal model.
- **Published-grid certification off-node is 1-D, span-limited.** `validate_cutflow.py`
  interpolates the published acc×eff grid linearly along one axis only (fixed-LSP preferred), and
  only across brackets ≤ `--interp-max-span` (default 200 GeV). Sparser regions fall back to a
  flagged nearest node (`NEAREST` in the per-SR `node` field). 2-D interpolation on triangular
  grids is not implemented.
- **Counting model is an approximation.** For analyses without a published likelihood, the per-SR
  single-bin counting model (best-expected SR; uncorrelated constraints in `--combined` mode) does
  not capture SR correlations or the full systematic model. Prefer the published likelihood; for
  the background input prefer the analysis's published CR-fitted b±δb (`rivet_ref_yields.py
  --fitted-bkg`, rank 2.5 in `docs/workflow/checklists/data-acquisition.md`) over the REF
  integral with its uncertainty floor.
- **Likelihood↔selection pairing checks structure, not control-region signal.** A model that
  patches only the signal regions leaves control regions without signal contributions, which can
  strengthen the observed limit. Validated control-region definitions and signal nuisance
  responses are required before a claim of full signal-model reproduction; a successful
  structural pairing check cannot close this limitation.
- **Floored and capped limits are bounds.** Floored/capped µ₉₅ values are tagged
  `quality=floored|capped` and rendered as bounds, never limits.

## Coverage / complexity
- **Complex routines need per-analysis certification.** Recursive-jigsaw and other multi-bin or
  control-region analyses are supported through `docs/workflow/checklists/complex-analysis.md`
  (per-region and cutflow-only handling); each needs its own acceptance certification.
- **Native SimpleAnalysis backend covers a ported set, not all routines.** The VM-free native SA
  backend (the step-8 default) has a shared core (`sa_native_core.py`: primitives, SA
  header-verbatim ID bits and pinned helper semantics), a declarative spec engine for plain
  cut-based routines (`native_sa_generic.py`), and a porting recipe with a mechanical acceptance
  gate (recipe in `docs/workflow/reference/native-pipeline.md`). Unported routines take the
  per-use container fallback, and each port needs its own per-analysis acc×eff certification.
  A missing registered routine module is refused before native planning or dispatch.
  Optional retained solver regressions are reported as not run when their assets are absent.
- **SimpleAnalysis routine availability (container fallback).** Routines live in the `:master`
  container image; an analysis whose `.cxx` is not in that image needs a runtime-add or container
  rebuild (container build rights).

Shape and template fits route to the scoped `shape_fit.py` engine (`stat_mode=shape-fit`), gated
per analysis. Only an unrepresentable fit (unbinned / multi-observable / per-event NN) downgrades to
the named `blocked-shape-fit` refusal + generator-level offer (docs/reference/scope.md §6.1).

## Infrastructure
- **Container path (the legacy SA fallback only) is slow.** When no native port exists, the
  SimpleAnalysis/Delphes chain runs amd64 under podman emulation, strictly sequentially and for
  hours per point. The native backend (the default where it exists) runs one point at a time
  under the machine lease; a `site` backend runs points in parallel on remote slots.
- **HEPData retrieval.** `hepdata-cli download <inspire> -i inspire -f yaml` retrieves the complete
  table set; the likelihood downloads via the open `/record/resource/<id>?view=true` endpoint. No
  browser is required for either.

## Supplied-data adapter boundary

The [scientific-study route](../workflow/reference/scientific-studies.md) transports
signed/multiple weights on existing Rivet inputs and explicit quantity records. This does not
change the generation path's multiweight restrictions. Missing native SimpleAnalysis execution,
conditional covariance assumptions and unvalidated domain extensions remain limits of that route.
