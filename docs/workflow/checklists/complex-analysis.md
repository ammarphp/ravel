# Checklist — complex analyses (multi-bin / control-region / jigsaw)  ·  [judgment]

Complexity is **never** a reason to skip an analysis — the searches most sensitive to new physics are
usually the complex ones. Each kind of complexity maps onto a part of the pipeline that already
handles it; nothing about a complex routine forces exclusion from scope.

| Complexity | Where it is handled |
|---|---|
| intricate per-event reconstruction (recursive jigsaw, BDT/NN scores, aplanarity, m_T2) | **inside the routine** — Rivet/SimpleAnalysis compute it; the pipeline just runs the routine, no special handling |
| many signal-region bins | step 6: `rivet_ref_yields.py` with one spec entry per bin (scalar-counter routines only — it hard-errors on cutflow-only routines, which use the run-local adapter path below); step 7: one pyhf channel per bin |
| control regions + a background fit | the **published likelihood** carries the CRs + the CR→SR constraint; `pyhf_exclude.py likelihood` uses it directly |
| correlated systematics across regions | the published likelihood (full covariance); or a simplified likelihood built from the **covariance table** (now fetchable via `hepdata_fetch.py --tables`) |

## Full CR+SR likelihood analyses (the cleanest complex case)
When the analysis publishes a full pyhf likelihood, even a many-region model needs no simplification.
A compressed-electroweak search, for example, can carry **dozens of channels** — several **control
regions** (diboson, top, tau) plus many **signal-region bins** (flavour × m_T2 × MET) — all combined,
with the CR-constrained background and the cross-region correlations held inside the workspace. Run it
with `pyhf_exclude.py likelihood` on the patched workspace and it reaches the true crossing; the pipeline
simplifies nothing. (A filled worked example, with the numbers, lives in the pedagogical guide.)

## When there is no published likelihood
Build a per-SR/per-bin model from the analysis's own numbers:
- the bundled REF (Rivet) or the fetched HEPData tables give observed + background per bin;
- `pyhf_exclude.py counting` quotes the single most-sensitive bin (the standard prescription when the
  per-bin correlations are unknown); with the **covariance table** a multi-bin simplified likelihood
  can be built instead. State which was used (`exclusion-model.md`).

## Recursive-jigsaw / cutflow-only routines (the EWK counterpart to the m_eff path)
Some routines (e.g. 2–3 lepton recursive-jigsaw EWK searches) compute their discriminants **inside** the
routine and are **`SINGLEWEIGHT NOTREENTRY`** + **cutflow-only**. Resolve the routine with
`routine_fetch.py --query <code>` and check `rivet --show-analysis` for the flags. These change the data
path — they do **not** follow the `rivet_ref_yields.py` per-bin path:
- **Run single-weight**: `rivet --skip-weights`, one YODA, never reentrant-merge (`docs/workflow/steps/04-analyze.md`).
- **No scalar SR counters / no distributions** — the routine books only `Cutflow` objects. Per-SR
  **A×ε = last/first cutflow bin** (normalisation-invariant under the routine's `normalizeFirst`);
  signal yield = A×ε·σ·L.
- **No per-SR (obs,bkg) yield table** — integrate the bundled REF **distribution** tables into the
  channel regions for observed + background, and build the counting model on those.
- **acc×eff certification** uses the published acc×eff **grids** (2-D in the mass plane).
  `validate_cutflow.py` now does the grid lookup natively: exact node when one exists, else a 1-D
  linear interpolation along one axis at fixed other coordinate (fixed-LSP along the splitting axis
  preferred; brackets wider than `--interp-max-span` are not trusted), else a **flagged** nearest
  node — the per-SR `node` field in its output records which path was used; inspect any `NEAREST`
  row, since on a coarse/edge grid it compares against the wrong mass-splitting and can flip the
  verdict.
The **cutflow reader is now native**: pass `validate_cutflow.py --sr-reader cutflow` (or `auto`, which
detects per-SR whether the YODA object is a scalar counter or a cutflow histogram and dispatches
accordingly) — it reads the cutflow last/first-bin acc×eff directly into the same tiered-verdict JSON
schema, so a cutflow-only routine **no longer needs a run-local SR adapter** (the counter path stays
bit-identical). The only part that can still need a run-local shim is the *published-grid description
matcher* (`published_axe()`) when a routine's HEPData table descriptions / SR-name conventions don't
match its patterns — `docs/workflow/reference/example-rivet-ewk-path.md` is the worked shape to follow.
