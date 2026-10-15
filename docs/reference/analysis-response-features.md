# Supplied analysis instrumentation and response features

`analysis-response-features` prepares reversible source instrumentation and consumes
retained native traces. Both operations require a selected instrumentation package;
the engine holds no routine, classifier roster, score binning or study population. The
released six-b routine's package ships as data in `src/ravel/data/analysis_assets/six-b`
(source, six classifier models, reference YODA, support sources, `descriptor.json`,
`contracts.json`); `ravel.physics.shipped_assets.six_b_prepare_input(directory)` writes the
bound `prepare-input.json` and returns the `prepare-source` task.
Native compilation and event processing use the existing approved `analyze`
`routine-build` and `rivet-built` operations and their method-decision admission.
This adapter performs neither launch nor inference.

The task is `{schema_version:1, operation, input, input_sha256}`. The operation is
`prepare-source` or `consume-traces`. File pins are `{path, sha256}`. A missing
instrumentation package raises `ResponseInputError` with `reason="missing_input"`.
Use the ordinary schema-2 science plan, approval, supervised worker and review.

The preparation document supplies `schema_version`, `instrumentation`, `source`,
`info`, `reference`, `models`, `contracts` and `dependencies`. `instrumentation`
pins a JSON package with these fields:

| Field | Supplied contract |
|---|---|
| `schema_version` | 1 |
| `routine`, `instrumented_routine` | Original and observed source identities |
| `instrumentation` | `{schema_version:1, source_sha256, edits}`; each edit has nonempty `old`, `new`, positive integer `count` |
| `trace` | Prefix, exact source header, identity phase, complete event paths, classifiers, destinations and normalization phase |
| `models` | Asset key to `{filename, contract}`; all model bytes and contracts must agree |
| `final_histograms` | Complete supplied output namespace, for every original weight |
| `build` | Safe `compile_unit`, `output` basenames and compiler `flags` |
| `runtime_version`, `analysis_options` | Exact native producer configuration |
| `normalization_scale` | Positive source normalization factor, supplied with its scientific basis |
| `beam_pdg`, `beam_energy_gev` | Source applicability domain |
| `coordinate_fields` | Axis names mapped to literal field paths in each retained producer task |
| `limitations` | Source-specific scientific limitations |
| `study` | `{study_id, parameter_grid, datasets, output:{stem, formats}}`; formats select `json` and/or `markdown` |

Every edit checks its forward occurrence count, its inverse occurrence count and
full original-byte recovery. The source capsule preserves selected reference and
model bytes and marks observed source metadata unvalidated. Use
`native_build_draft(prepared, runtime)`, seal through the ordinary build service,
and obtain approval before execution. `native_event_task(..., descriptor=...)`
composes the existing uncapped-weight task; it creates no execution identity.

Classifier contracts are a dictionary selected by the manifest's contract keys.
The existing `source-classifier-feature-contract/v2` service rebinds source excerpts,
model bytes, tensor metadata, feature order, scalar arithmetic and output width.
Model identity and selection never follow a filename convention. All models in the
manifest must have supplied contracts, including models inactive on a given event.

Each event path supplies `{id, phases, checks, allocation}`. A phase is
`{phase, min, max}`. Exactly one complete phase path must match every event.
The identity phase must equal the separately supplied original event/weight census.
Classifier entries supply `id`, `contract`, `select`, `features_phase`,
`input_phase`, `output_phase`. The consumer checks actual inputs against declared
source arithmetic and retains the full native output vector before allocations.
Checks and allocations use bounded data expressions: `literal`, `path`, or
`{op, args}`. Supported operations are comparisons, boolean combinations,
arithmetic, length, float32 cast, conditional choice, supplied score-bin labels,
and bounded `map`, `all_items`, `any_items`, `sum_items` expressions over complete
object lists. Collection expressions bind the current `item` in the data context.
A per-expression operation budget refuses excess work without truncating objects.
Expressions cannot import code or launch programs. No selection is inferred from
an analysis identity; the selected source package must state every required check.

Consumption supplies `schema_version`, `instrumentation`, `prepared`, `events`,
`metadata`, `contracts`, `anchors`, `axes`, `reference_point`, `nominal_weight`,
`normalization_tolerance`. Every anchor has `point`, `trace`, `producer_task`,
`build_reuse`, `loader` pins. Coordinates must match actual retained producer
configuration fields, and the ordinary response accumulator validates the complete
axis/anchor population. Build, plugin, source capsule, libraries, interpreter,
loader, command, environment and output population are rechecked. Native work
remains under the original execution guard.

All original signed and zero weights, subevents, group identities and per-weight
normalization observations remain. Shared-group marks are summed before their
outer products. Recorded native factors apply a conditional linear covariance
map; they establish neither native marginal-error equivalence nor a sampling law.
There are no fitted efficiencies, reconstruction substitutes or likelihoods here.

Source and log files remain bounded at 64 MiB, complete populations at 20,000
subevents, and emitted members at 320 MiB. The existing joint accumulator's work
and coordinate bounds remain enforced; excess work refuses without truncating the
population. Intended output bytes are committed before writing and checked again
at completion and reporting. Source-format checks do not establish native observer
noninterference, classifier inference accuracy, calibration or physics validity.
