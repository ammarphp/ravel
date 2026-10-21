# Supplied named scans and card recipes

A scan repeats an admitted operation over supplied finite named coordinates. The request
sets the dimensionality, datasets, requested quantities and output format. Planning and
rendering do not authorize compute. Native launch retains the method-decision record,
CHECK-IN 1 approval, source commitments and supervised stage graph.

## Scan contract

Validate the supplied JSON against `src/ravel/data/templates/scan.schema.json`.
Every required field is supplied; the schema has no physics defaults.

| Field | Meaning |
|---|---|
| `schema_version` | `2` |
| `name` | Requester's study identity; carried unchanged into the manifest and results |
| `axes` | Ordered list of `{name, values}`; distinct finite numeric values |
| `max_points` | Resource ceiling for the complete Cartesian domain |
| `points` | If supplied, an explicit unique subset of complete named coordinates in that domain |
| `template_toml` | Selected resolved configuration; relative paths start at the contract directory |
| `subst` | Supplied TOML `section.key` address to axis-name map; a bare key must be unique |
| `run_root`, `run_prefix` | Supplied location and filesystem-safe prefix for point directories |
| `datasets` | Explicit nonempty population of objects with unique `id` values and supplied metadata |
| `quantities` | Nonempty list of `{name, source, field}`; source is a relative point artifact, field is a dotted JSON object path |
| `output` | `{format, path}`; `format` is `json` or `csv`, path is relative to the scan directory |
| `model`, `analysis_id` | Supplied native adapter identities when dispatch is requested |

Axes can describe masses, couplings, widths or any other finite numeric parameters.
No daughter-mass relation, positivity domain or exclusion threshold is inferred.
Declare physical relations in the selected model recipe or supply the corresponding
coordinates. Repeated TOML keys need section-qualified addresses; absent or ambiguous
bindings are refused before any point directory is written.

```bash
python -m ravel.workflow.scan_orchestrator plan /path/to/contract.json --dry-run
python -m ravel.workflow.scan_orchestrator plan /path/to/contract.json
python -m ravel.workflow.scan_orchestrator launch /path/to/scan-directory --backend native --write-plans
```

Inspect each point's saved native proposal and its source inputs. Obtain actual approval
for the contracted compute before adding `--go`. A native adapter must support the
selected process, detector and statistic; arbitrary axes do not grant new native support.
Container dispatch remains a dry diagnostic until its execution adapter binds approval.

```bash
python -m ravel.workflow.scan_orchestrator status /path/to/scan-directory
python -m ravel.workflow.scan_orchestrator assemble /path/to/scan-directory
```

The manifest contains the supplied axes, datasets, quantities, output specification,
coordinates and resolved point directories. Dataset objects describe the supplied
population; this orchestrator does not resolve or rewrite event datasets. The selected
point configuration must bind those sources for execution.

Aggregation preserves point order, missing-point coverage, invalid-source reasons and
source fingerprints. CSV columns are the point tag, supplied axes and requested quantities;
its `.metadata.json` sidecar retains the full result and custody. JSON writes the full
result directly. A quantity from an inference artifact also retains typed limit status,
brackets and eligibility. Review and execution-custody checks apply before harvesting.
An invalid preferred limit artifact must not silently fall back to another file.

Use a renderer whose declared axes and quantity schema match the result. Supply plot
labels, comparison sources, projection and output names. A mass-plane renderer is only
applicable when those supplied coordinates have that meaning. Keep normalization
operations explicit and source-bound; named scans refuse the former implicit normalization
switch. Preserve missing points, bounds and unverified roots in comparisons.

## Card recipe

The retained `ravel.physics.prepare_native_slepton` module now renders general supplied
recipes. Validate against `src/ravel/data/templates/card_recipe.schema.json`.
The module selects no installed model, process, parameter point, PDF or generation cut.

A recipe supplies `param_template`, `run_template`, `process_card`, `launch_template`,
`parameters`, `bindings` and `run_controls`. Relative source paths start at the recipe file.
Process sources contain model imports, definitions and process expressions; output and
launch commands belong in the selected launch template.

Each binding has `parameter` and either `placeholder`, or `block` plus integer `indices`.
A placeholder must occur in the source. A block address must occur exactly once. A `DECAY`
address with one particle index edits its width; decay branches remain untouched unless
supplied in the selected source. Repeated binding addresses, missing parameters and
unresolved placeholders are refused. Non-edited card bytes, including decay rows and
comments, are preserved.

Run controls explicitly include `nevents`, `iseed`, `ebeam1`, `ebeam2`, `pdlabel`, `ickkw`
and `use_syst`. Every supplied control must match exactly one run-card assignment. A PDF
identifier, matching scheme, cut or correction is never guessed. The native unmerged
adapter additionally refuses active merging settings and systematic weights until an
appropriate qualified adapter is selected.

The supplied launch template contains exactly one each of `{{PROCESS}}`, `{{PARAM_CARD}}`
and `{{RUN_CARD}}`; `{{SEED}}` is substituted when supplied. It defines the generation
settings and prompt protocol, including the process output path. Bare absolute parameter
and run-card paths must retain their positional order for the selected generator protocol.
Rendering preserves that selected template's bytes except for substitutions.

```bash
python -m ravel.physics.prepare_native_slepton --recipe /path/to/recipe.json --rundir /path/to/run
```

This writes prepared cards and source fingerprints; it starts no tool and claims no runtime
consumption. Shower configuration continues through the existing typed translation routine,
which preserves explicit controls or refuses conflicts. Use the supervised native plan to
bind the actual shower, detector, analysis, normalization and likelihood inputs.

For native preparation, supply `[ravel.native.rendering]` with `parameters`, `bindings`,
`run_controls` and explicit `expected_masses`, and bind all four source paths plus
`pythia_card` under `[ravel.native.inputs]`. The plan's count, seed and beam energies must
agree with any duplicate recipe controls. Each `expected_masses` entry must equal the rendered card's
`MASS` value, and the declared model's produced parents must be heavier than its LSP;
both are checked before any stage is declared. Configured run options are applied or refused;
no configured cut is silently omitted. The recipe's selected launch template reaches the
effective-card manifest and its hash-bound downstream stages.

## Migration and qualification

Previously populated templates are replaced by parameter-free schemas. Select the original
model/process/card sources externally and declare their values and bindings in a recipe.
Migrate old coordinate pairs or mass-difference grids into explicitly named coordinates;
no old relation is inferred. Older supplied manifests remain readable for numerical limit
transport, without granting approval or certification to their artifacts.

Before relying on a migrated recipe, compare all effective-card bytes using supplied
sources and qualification criteria. Then qualify native execution through an approved
bounded job, with supplied references, exposure, time and disk budgets. Synthetic rendering
and aggregation checks establish software behavior; native execution and physics validity
need their own evidence.

## Prepared-study allocation grids

Use `ravel study-grid` when each point/scenario already has an ordinary study specification
and run directory. This bridge uses the batch-allocation launcher directly and does not
route through the native scan adapter. It adds no generator, model or analysis defaults.
Prepare the supplied cells, retain the actual delegated approval and budget, then follow
[finite allocation grids](../../reference/batch-allocations.md#finite-grids-of-prepared-studies)
for the manifest and `submit`, `status`, `resume`, `harvest` commands. No compute starts
without the ordinary approvals. Reconcile coverage and scientific result eligibility before
drawing conclusions from a harvested grid.

The harvest retains all declared axes and scenarios, every attempted or untouched cell,
result paths and SHA-256 digests. Aggregation can read each cell's `values` by supplied
quantity name; preserve its `status` and original attempts. A `completed` allocation is an
agent-exit observation, not physics certification. Missing or failed cells remain holes.

The parameter-plane renderer accepts a panel grid with `study_grid` naming the harvest:

```json
{
  "grid": {
    "study_grid": "/path/to/grid-state/harvest.json",
    "scenario": "baseline",
    "x": "first_coordinate",
    "y": "second_coordinate",
    "surfaces": {"observed": "requested_quantity"},
    "level": 1.0,
    "excluded": "below"
  }
}
```

Supply the full figure's natural-language `axes` labels, units and scales as usual, then
render through `ravel figure plane --spec ... --out ...`. The surface name,
threshold and excluded side above are illustrative declarations; choose them for the
contracted quantity. No exclusion interpretation is inferred by the grid bridge.
Select exactly two numeric axes and one scenario. For higher-dimensional grids, supply
`fixed: {"other_coordinate": value}` for every remaining axis. `bands` can bind
`expected_1sigma` or `expected_2sigma` to `{low, high}` quantity names. Numeric axes must
increase for plotting. Categorical axes remain available in the harvest for supplied
aggregation or another renderer.

The plotting reader rechecks each used artifact digest and dotted field against the
harvest. It masks absent or unsuccessful cells and disables contour corner filling around
holes; it never estimates missing values. The source receipt records the selected scenario,
fixed coordinates and missing-cell coverage. Preserve those holes in comparisons and
report the complete declared population alongside results.

## Per-point setting overrides

Use an override for an explicitly diagnosed regime change, such as a threshold,
width, integration failure or weight pathology. Keep the original grid and failed
attempts. Never delete a troublesome point or fill a failed cell by interpolation.
An override changes that point's receipt identity; its coordinate tag stays stable.

The parent approval must bind a `point_override_scope` object in one of its approved
JSON input files. It has `context_sha256` and `fields`. Obtain the context with
`scan_orchestrator.override_context(manifest)` or `study_grid.override_context(grid)`
before approval. A field uses a JSON pointer into the parsed point TOML or study
JSON, for example `/settings/accuracy`. Its rule has an explicit `values` list and
`physics: true|false`. Mark a change to the physical prescription as physics;
a numerical repair can be classified separately only in the approved scope.
There is no automatic classification from a field's name. The context binds the
original axes, population, input locations and bytes, and requested quantities.

Supply an override JSON record with these fields:

- `changes`: nonempty pointer-to-value replacements of existing declared fields;
  dictionary and indexed list fields are supported. Overlapping replacements,
  additions, nonfinite values and unchanged values are refused.
- `reason`: the regime reason, retained verbatim as the harvest's `regime` column.
- `diagnostics`: nonempty `{path, sha256}` evidence pins with absolute file paths.
- `approval`: `{rundir, route, rung, approval_files}` referencing a verified existing
  compute approval. Use the parent run's delegated scope, separately from the
  point's executable proposal. A planning-only approval must not authorize a repair.
- `amendment`, when needed: another approval reference whose approved input has
  `point_override_amendment: {context_sha256, point_id, changes, physics_fields}` for exactly this
  point and change set. Out-of-scope values require this amendment. Undeclared
  fields are conservatively treated as physics changes.
- `comparison`, for physics changes: `{neighbour_id, default, override, assessment}`.
  Both arms are pinned JSON records with `{point_id, changes, result}`. `point_id`
  names one adjacent successful default neighbour in the same scenario; `changes`
  is `{}` for the default arm and the exact change map for the override arm.
  `result` pins the arm's actual result file. Run both arms under ordinary approved
  execution, record their comparison and assessment, and supply their existing
  evidence. Admission does not generate a comparison or claim its scientific validity.

Use the ordinary commands:

```bash
python scripts/run.py ravel.workflow.scan_orchestrator override <scandir> \
  --point <tag> --record <override.json>
ravel study-grid override --manifest <grid.json> --grid-dir <grid-state> \
  --cell <cell-id> --record <override.json>
```

Admission freezes verified diagnostic and comparison bytes in a content-addressed
evidence archive, preserving their original paths in `source_evidence`. Retry logs
can then change without erasing the evidence that triggered the repair.

Native scans write a separate effective TOML and an archived receipt, preserving
the original configuration. Each override receipt selects a separate
`attempts/<receipt-sha256>/output/`, executable proposal under that attempt's
`inputs/`, and stage logs under `logs/attempts/<receipt-sha256>/`.
The approval input census recognizes these supervised logs as produced inputs. The default `output/` and saved
proposal remain intact. `attempt_history` retains the default and override
identities, including their output directories; harvest reads the directory
selected by the point identity and never falls back to another attempt.
`launch --resume` reuses the effective configuration and attempt.
Write and admit the revised executable proposal through the ordinary native
workflow; exact-plan, compute-rung, resource and source checks still apply.
Delegated approval can cover an in-scope repair without another operator decision;
an override receipt itself never substitutes for execution authorization. Keep the
parent scope approval stable when admitting the point's revised executable proposal.
Native executable plans and stage input identities include the override receipt.
Native reports carry `point_receipt_sha256` and `quantity_outputs`, an explicit
list of produced quantity files with their absolute paths and SHA-256 hashes.
The native report stage declares these files as inputs. Harvest accepts a native
quantity only when its selected attempt's report lists the file and its hash
matches. A missing report, unlisted file, missing file or hash mismatch produces
an explicit failed cell. Older native reports without this manifest require a
new approved execution; a receipt alone must not authenticate an output.

Study grids write a separate effective study specification and retain it in the
ledger. The cell's agent argv must contain its absolute `study_spec` path as an
argument or the literal `{study_spec}` token. Dispatch replaces that argument with
the effective file, pins it in the allocation request, and rechecks it before the
remote agent starts. The agent receives `RAVEL_POINT_SETTINGS` and
`RAVEL_POINT_RECEIPT_SHA256`. Overridden JSON quantity outputs must carry
`point_receipt_sha256` with that value, or the producer must supply
`outputs/point-override-result.json` containing that receipt and
`artifacts: {"relative/source": "sha256"}` for every harvested artifact. This
sidecar also supports binary outputs. Harvest treats missing or stale receipts as
holes even when the allocation completed. The agent must use this supplied specification through the
ordinary study preparation and approval route. A running or ambiguous allocation
must not be overridden. After a terminal failure use `resume --supersede <cell-id>`;
the new attempt reuses the stored override, keeps the previous attempt and consumes
the existing grid budget. A proposed repair never relabels an earlier result.

Harvest JSON carries `overridden`, `regime`, `receipt_sha256` and the complete
`override` record. Native CSV includes status and regime columns and explicit empty
rows for holes, with full provenance in its metadata sidecar. Native JSON retains
`point_population`, including missing points. Both plot paths mark overridden
points with open orange diamonds; the study-grid plot also labels the regime.
Plot receipts preserve the marked population. Missing values remain masked; lines,
bands and contours must not bridge declared holes.
