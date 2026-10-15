# Step 7 — Exclusion (pyhf)  ·  [judgment — script-assisted: the mode table in `docs/workflow/checklists/exclusion-model.md` + what HEPData provides decide; `pyhf_exclude.py` runs it]  · CHECK-IN

Before inference with a constructed signal model and a released patchset, run
`python -m ravel.validation.patch_parity --background <background.json>
--patchset <patchset.json> --produced <workspace.json> --patch-name <name>
--record-id <record> --out <patch-parity.json>`. A mismatch names the channel,
sample and modifier type and exits nonzero. A structural pass does not validate
response sizes, event covariance, efficiencies or statistical coverage.

The [statistics core reference](../../reference/statistics-core.md) documents
the supplied-workspace profile record and binned-yield links. These core APIs
support downstream studies; a profile scan alone is not a CLs exclusion limit.

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Turn the comparison into a 95% CL upper limit on the signal strength µ with **pyhf** — the standard
statistical tool. Never hand-roll the statistical model. Pick the mode by what step 6 produced.

Carry the versioned `limits` object through every pack, scan and plot. Follow `docs/reference/scientific-results.md`: a scan endpoint remains a bound, missing expected slots remain missing, and shape R5 or acceptance comparison authority requires the current artifact-bound certificate. Keep numerical convergence separate from model validation and statistical coverage.

When reproducing a published analysis, follow the [reproduction diagnosis
checklist](../checklists/reproduction-closure.md) before attributing disagreement
to detector simulation. Begin with fixed-workspace numerical and published-signal
closure, then isolate normalization, sampling, truth selection and detector effects.

## Mode A — serialized likelihood (preferred when published)
A `stat_mode=published-likelihood` run pairs the chain's signal patch against the published
background-only workspace BEFORE the limit: run the likelihood↔selection pairing gate (structural
channel/bin-count agreement), which emits `pairing_check.json`:
```bash
$CONDA run -n rivet python scripts/run.py ravel.validation.pairing_check \
  --bkg <bkg_only>.json --patch <signal_patch>.json
#   verdict="pass" iff paired and no mismatches; `validate_run_state.py` enforces this gate
#   (the likelihood-selection-pairing invariant) whenever stat_mode=published-likelihood.
```
Then apply the signal patch to the published background-only workspace and fit:
```bash
$CONDA run -n rivet python scripts/run.py ravel.physics.pyhf_exclude likelihood \
  --bkg <bkg_only>.json --patch <signal_patch>.json \
  --out <rundir>/outputs/pyhf_exclusion --label "<model> vs <analysis>"
```

## Mode B — counting model (no published likelihood)
Build one single-bin counting model per SR from `sr_yields.json` (observed, background±unc, signal);
the limit is quoted from the single most-sensitive SR (best expected CLs) — the standard prescription
when SRs overlap and cannot be combined:
```bash
$CONDA run -n rivet python scripts/run.py ravel.physics.pyhf_exclude counting \
  --srs <rundir>/outputs/sr_yields.json \
  --out <rundir>/outputs/pyhf_exclusion --label "<model> vs <analysis>"
```

Both write `exclusion.json` (observed + expected ±1,2σ limits, the CLs-vs-µ scan) and `exclusion.png`
(CLs vs µ with the 0.05 line and the limit). **The result is the verdict on this model point:
excluded if the observed µ₉₅ < 1, otherwise allowed** — the model under test is typically one the
analysis's authors never considered, so this limit stands on its own.

## Cross-section convention and normalization

Use the pinned offline route with an explicit production basis, collision energy,
masses and `convention: {order, pdf, scale}`:

```bash
ravel xsec lookup --request <rundir>/inputs/xsec-request.json --out <rundir>/outputs/xsec.json
```

The requested order must match what the analysis states.
A charge-summed basis must be requested explicitly with `charge: "sum"`.
`as-published` accepts the table's recorded PDF or scale, including an unknown
published prescription; it does not fill in missing metadata. A missing selected
convention is a gap, and another order or a flat k-factor must not replace it.
Compare the higher-order value with a generator record on the same process,
charge, flavour, mass, energy, branching and generation-cut basis before deriving
k with `cross_sections.k_factor`. A k below one can be physical.

If partner content differs from the table, describe it in `spectrum.decoupling`
and/or `spectrum.state_count` (the latter agrees with request `state_count`). A
nonempty `spectrum_assumption` must state the approximation. Lookup returns both
requested and table descriptions. A published state-rescaling rule remains an
explicit sourced declaration; without such a rule an accepted spectrum assumption
keeps the table's value and does not invent a multiplicity correction.

Bind a registry-derived ledger `sigma.source` to the table ID or sha256 and state
its own order, full PDF label and production basis. Unknown table PDFs are recorded
as `as-published`. The ledger builder preserves hashes for every constituent of a
charge sum; ambiguous table IDs require a hash. `ravel normalization-ledger check
--ledger ledger.json --delivered yields.json` refuses registry convention or basis
mismatches and flags free-text sources as `source_unpinned` for review.

An optional `sigma_alternates: [{order, pdf, value_pb, source}]` list reports other
conventions beside the primary sigma. The check recomputes their bins and integrated
totals with all other ledger factors held fixed, and records their ratio to the
primary. Totals sum listed regions without deduplicating overlap. Preserve these
entries and the check report in delivery; primary delivered numbers remain unchanged.

Record whether the signal template already contains k. If translating an existing
LO limit with `pyhf_exclude.py --sigma-scale <k>`, apply that correction once. The
acceptance×efficiency comparison remains independent of cross-section normalization;
its certification does not establish the table's applicability to another spectrum.
The compatibility `nlo_xsec.py` import delegates to the same offline convention
service. Supply a selected table or correction contract; process names and bare
grids do not define a denominator. See [supplied conventions](../../reference/cross-section-conventions.md)
for exact-node and interpolation policies, provenance pins and typed missing inputs.

## Reaching the real limit (the µ=2 lesson)
The limit must be the true 95% CL crossing — where CLs falls to 0.05. A fixed µ scan (e.g. mapyde's
default 0.1–2.0) can stop before the crossing: if CLs at the top of the grid is still ≫ 0.05, the
model is simply weakly constrained and the limit lies beyond the grid. `pyhf_exclude.py` removes that
truncation — it brackets µ in both directions and refines each observed/expected crossing with
Brent's root solver. A coarse plotting grid alone is insufficient, even when it brackets the
crossing. Unresolved curves retain explicit bound statuses. (For a full-likelihood fit each point is a many-parameter fit;
expect minutes, not seconds.)

## Optimizer robustness (silent-failure guard, automatic)
Published histosys workspaces can carry **NaN pockets** in −2lnL (interpolation drives bins
negative); on such a surface pyhf's stock scipy/SLSQP backend can return its **init vector claiming
success** — a silently wrong limit with obs==exp and no error. `pyhf_exclude.py` therefore runs every
minimization through its `robust_optimizer`: SLSQP first (bit-identical on clean surfaces), and on
ANY distrust signal (NaN evaluated mid-fit, reported failure, non-finite minimum, drifted fixed
parameter) it re-minimizes with NaN-guarded iminuit MIGRAD, **escalates the whole model to
MIGRAD-first**, recomputes any CLs points already scanned, and raises loudly if no valid minimum
exists. Nothing to invoke — read the outcome in `exclusion.json` → `"optimizer"` (`escalated`,
`n_fallback`, `n_nan_flagged`): an escalated Mode-A fit is normal for NaN-pocketed workspaces
whose minimizations trigger the guard. A `RuntimeError` from the guard means the surface is sick —
do NOT fall back to the stock backend to "get a number". Regression: `pyhf_exclude.py selftest`.
The selftest runs synthetic controls. Source likelihood comparisons use
`ravel.physics.pyhf_exclude.check_fit_reference(reference)` with supplied `background`
and `patch` file paths, `expected` rules for `mu_hat` and `twice_nll` (each with `value`,
`atol` and `rtol`), and `output_format` (`json` or `jsonl`). A `context` object carries
the supplied study identity, grid and datasets into the result. Missing inputs raise
`MissingReferenceInput` with reason `missing_reference_input`. A comparison preserves
failed values and input hashes; it grants no scientific acceptance or launch authority.
The package ships one published workspace, its patch and a reference file for this comparison
(`src/ravel/data/fixtures/susy-2018-06/`: `BkgOnly.json`, `patch_ERJR_300p0_100p0.json`,
`reference_fit.json`, whose `background` and `patch` names are relative to its directory).
Published workspaces and the channel maps that join native yields to them are listed in
`src/ravel/data/likelihoods/registry.json`; `sa2json_native --shipped-channel-map <id>`
selects one, and a workspace whose channel set no shipped map covers needs a supplied map.

## Reading the honesty flags in `exclusion.json`
- `at_poi_cap` — the doubling bracket reached the µ cap (often mere **granularity**: the +2σ band
  chased the cap while the median crossed far below). NOT by itself "the limit is capped".
- `median_at_cap` — the MEDIAN expected CLs never crossed 0.05 in the scan: the reported
  median limit IS the scan ceiling. Only this flag justifies drawing a ">cap" arrow.
- `at_mu_floor` — hyper-excluded below the scan floor; the value is a bound, not a limit.
- `band_degenerate` — the five expected quantiles span < 1.5× (healthy qtilde bands span
  ~2.5–4×): the band is unusable; quote the result as a bound only.

## Make the limit trustworthy (intrinsic rigor)
A µ₉₅ is only as good as its inputs, and there is usually no published result for this model to lean
on. Ensure rigor at the source:
- the statistical model is the analysis's own (its published likelihood, or its observed+background
  per SR), paired with the matching selection (`docs/workflow/checklists/data-acquisition.md`);
- the signal cross-section carries its higher-order normalisation (NLO+NLL where available), not bare
  LO (`docs/workflow/checklists/generation-settings.md`);
- the signal yield comes from a pipeline whose acceptance×efficiency was validated once, on a
  benchmark the authors *did* publish, to a stated tolerance — see `docs/workflow/checklists/validation.md`. That
  one-time check certifies the routine; new model points then inherit it.

A counting model on a single SR with a floored background uncertainty is an approximation of the full
likelihood; quote it as such, and prefer the published likelihood when one exists.

**Enforced (D12/G14):** `validate_run_state.py`'s `certify-before-limit` invariant hard-BLOCKS any
limit-shipping run (incl. a scan) whose acc×eff cert verdict is FAIL — or that carries **no**
discoverable cert at all — before `exclusion.json`/`scan.json`/the result-pack ships. Only a PASS/WARN
cert may feed a limit; the analysis STAGE merely WARNs on a FAIL cert (records the pointer), but this
invariant is the hard block. A complete scan's per-point `scan.json` attestation does **not** waive the
cert: the aggregator must carry a discoverable (aggregate or per-point) acc×eff cert — otherwise the
scan hard-FAILs.

**Plausibility emitter (D14):** the moment `sr_yields.json` and `exclusion.json` both exist and BEFORE
the limit ships, emit `python3 scripts/run.py ravel.validation.sr_plausibility --rundir <rundir>` (add
`--sigma-ref-fb F --lumi-fb F` to also band the driving-SR acc×eff — catches the "956% acc×eff" defect
class). It writes `outputs/sr_plausibility.json` with an EARNED `verdict ∈ {plausible, implausible}`
(never defaults to plausible) over four analysis→statistics sanity checks — ≥1 non-trivial SR carries
signal, µ₉₅ finite and off the floor/ceiling, `excluded_obs == (µ₉₅ < 1.0)`, and the optional
driving-SR acc×eff band — exit 1 on `implausible`. This is a plausibility-domain artifact with its own
`input_fingerprint`; it is deliberately NOT a `provenance.py`-verified lifecycle artifact.

**Plausibility FOLD (D14, enforced):** `validate_run_state.py`'s `check_statistics` reads that
`sr_plausibility.json` for single-point limit modes (`exclusion.json`/`shape_fit.json`; scan mode is
attested per-point elsewhere) and folds an `implausible` verdict into a **hard statistics FAIL** — so an
all-zero-yield run can no longer ship a vacuous "not excluded". It also FAILs a `shape_fit.json` whose
`excluded_obs` contradicts `mu95_obs < 1.0`. A MISSING `sr_plausibility.json` is INFO (advisory, never
gating); a `plausible` verdict is a PASS check. Run `sr_plausibility.py` before the limit ships so the
gate has the artifact to fold.

## Sensitivity-only studies (no observed-data claim — the expected-only recipe)
When the deliverable is a SENSITIVITY comparison (tagger what-ifs, particle-level AD studies,
projections), do NOT force a pyhf observed limit: quote the expected discrimination (S/√B on
the discriminating observable, or expected-CLs with the observed column suppressed), label
everything **expected-only**, and pack with `result_pack.py --stat-mode
sensitivity-expected-only` (`none-survey` for pure surveys). The 95%-CLs-never-discovery rule
still governs the wording.

## Measurement routines (not searches)
If the routine is a **measurement** (not a search), the exclusion route is Contur instead:
```bash
$CONDA run -n rivet bash -c "cd <rundir>/build && contur analysis.yoda -c config.dat -o contur_out"
```
`config.dat` needs `[signal]`,`[uncertainties]`,`[models]`,`[calculations]`,`[theory_predictions]`
(adapt `…/share/contur/tests/sources/custom_config.dat`). Contur targets measurements; it has no
likelihood for most searches.

## The RESULT-PACK — emit `result.json` (the run's machine-checkable headline)
Once the limit is in hand, assemble the run's **RESULT-PACK headline**: a thin, versioned `result.json`
that is the run's self-describing answer. It POINTS at (does not re-store) `sr_yields.json` /
`exclusion.json` / `provenance.json` / the cert json, and carries the headline + verdict fields a reader
(the benchmark gate, the audit) would otherwise reconstruct from scattered JSON + provenance prose:
driving SR, µ₉₅ obs/exp + the 5-entry expected band, driving-SR s95, best SR, the σ reference + k-factor,
the cert verdict + A×ε tier, the fidelity verdict, and the µ₉₅-stability anchor. It REQUIRES two enums —
`stat_mode` and `detector_mode` — so a counting vs likelihood vs stability-only run, and a Rivet vs
SimpleAnalysis/Delphes vs particle-level path, are explicit rather than buried in prose:
```bash
$CONDA run -n rivet python scripts/run.py ravel.workflow.result_pack \
  --rundir <rundir> \
  --stat-mode <published-likelihood|simplified-likelihood|best-sr-counting|combined-counting|stability-only|blocked-shape-fit> \
  --detector-mode <rivet-smearing|simpleanalysis-delphes|particle-level> \
  --m-parent <M> --m-lsp <M> --lumi-fb <L> \
  --normalization-ledger <rundir-relative ledger> \   # required when SR yields are delivered
  --limitations '<key>:<text> | <key2>:<text2>'      # keyed, separator '|' (or ';' before a key:)
#   → <rundir>/result.json  + <rundir>/figures.json  (schema_version=1)
```
The pack normalizes the on-disk conventions (the run's own `outputs/cutflow_cert.json`;
bracketed pyhf channel names `SR3L[SR3L_Low]`; an absent /
stub / populated plots `INDEX.md`) into ONE shape, and fails loud if a required source artifact is
missing. Pick `stat_mode` by the mode used above (a single-best-SR counting limit is `best-sr-counting`;
a multi-SR counting combination is `combined-counting`; no-HEPData stability-only registrations are
`stability-only`). When the on-disk `exclusion.json` is NOT the scored headline (e.g. a single-SR
artifact kept while the scored mode is the combined fit), declare the scored structure in `stat_mode` and
key the discrepancy in `--limitations` (the pack reports the on-disk artifact faithfully).

Record the limit (observed + expected µ₉₅, the mode used, and the verdict for this model point) in the
run's `RESULT.md` — which is the **human narrative GENERATED-FROM / cross-checked against `result.json`**
(the numbers in the prose are the numbers in the pack). When this point IS the run's deliverable
(no step-8 scan follows), the final check-in is the **RESULTS DECK** (`docs/workflow/checklists/check-ins.md`),
sent only after the step-9 verification panel (`docs/workflow/steps/09-verify.md`) with its verdict + findings
appended verbatim. If a scan follows, report the point briefly and continue to `docs/workflow/steps/08-scan.md`.

### Conditional profiles from retained amplitude events

For a prescribed cached differential objective, supply an ordinary
`differential-likelihood` task whose input document declares
`operation: cached-profile`. Follow the [continuous cached-fit contract](../../reference/amplitude-reweighting.md#continuous-fits-on-retained-blocks)
for source binning, fiducial definitions, continuous hypothesis bindings,
experimental and MC covariance policy, auxiliaries, independent starts and
resource bounds. Obtain the usual CHECK-IN approval before execution. Set
`retain_pairings: true` when producing a cache that must replay a
hypothesis-dependent pairing estimator. A Gram-only cache cannot reconstruct
those amplitudes. Use the separate polynomial handoff for Rivet-selected terms.
Inspect all failed/unissued fits and retained cross-state covariance before
interpreting profiles. Conditional objective differences alone do not establish
an exclusion limit or a calibrated interval. The optional RooFit bridge needs
its supplied native runtime and separate execution qualification.
