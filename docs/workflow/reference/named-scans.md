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
An invalid preferred limit artifact cannot silently fall back to another file.

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
both are checked before any stage is planned. Configured run options are applied or refused;
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
