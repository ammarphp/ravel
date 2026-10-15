# Supplied width-input source packages

Use `width-inputs` to materialize a request-selected, pinned source package, or a
packaged published-table descriptor. The package or descriptor supplies the study
identity, table files, extraction metadata and source population. The request
supplies the mass/width grid, point attachments and output representations.

Submit an ordinary version-2 science specification with mode `width-inputs`,
`goal_binding`, an independent review policy, and task `{input, input_sha256}`:

```bash
ravel plan --rundir <fresh-run> --spec <supplied-science.json>
```

The pinned producer document uses schema 2 and these fields:

| Field | Meaning |
|---|---|
| `goal_binding` | Original task-contract pin and assigned obligation |
| `source_package` | Pin of the explicitly selected package described below |
| `axes` | Ordered positive `mass_GeV` and increasing `width_over_mass` values with no installed upper endpoint |
| `point_inputs` | Sparse attachments; every Cartesian cell still survives |
| `regional_input` | Supplied integer observation/auxiliary law, or explicit null with missing obligations |
| `native_runtime`, `native_fit` | Complete pair of source-bound future fit inputs, or null |
| `review_policy` | Pinned independent ordinary review policy |
| `child_seconds`, `assumptions` | Prospective resource ceiling and scientific premises |
| `output` | Explicit `references`, `recipe`, `specification`, `receipt` and `study` destinations |

Each attachment has `coordinate`, `response`, `generation_request`, and `missing`.
Pins are `{path, sha256}` with a checked `size` when supplied. Paths in a package
resolve relative to that package; attachment paths resolve relative to the
producer. Duplicate or foreign attachments refuse before output creation.

A package has `schema_version: 1`, `sources` (arbitrary source keys to pins),
`submission` (the selected submission source key), `tables`, `analysis`, and
`reference_metadata`. Every submission `data_file` must occur exactly once in
`tables` and `sources`; unused sources or omitted tables refuse. A table mapping
has `id`, `file`, `role`, `axis_header`, `columns`, `quantity`, `unit`, and
`applicability`. Roles are `region` and `limit`. Each ordered column declares its
complete `header` and `qualifiers`. Region tables use contiguous low/high windows;
limit tables use increasing mass samples and an ordered observed/expected pair.
This adapter supports one scalar mass axis and nonnegative reference samples.
It retains complete original payloads and decimal tokens.

`analysis` is the explicit analysis contract in the [mass-width-grid guide](../../reference/mass-width-grid-recipes.md).
`reference_metadata` supplies `schema_version`, `kind`, `energy_tev`, `lumi_fb`,
`uncertainty_law`, `source_discrepancies`, `observations_reconstructed: false`,
`coupling_to_width_or_rate_map: null`, and `source_origin_scope`. Energy and
luminosity must agree with the analysis. Counts and full reference denominators
are derived from the selected files. Study grids need not equal reference-table
mass nodes.

Each of the four materialization outputs declares a safe `filename` and
`format: json` or `json-compact`; filenames must differ. The `study` contract
supplies the downstream result and report representations. The returned
specification goes through ordinary `ravel plan`; preparation never authorizes
its generation or fit descendants.

### Packaged published-table descriptors

`source_package` may instead be `{"descriptor", "directory", "analysis"}`.
`descriptor` names a packaged descriptor (`ravel.physics.width_inputs.descriptor_names()`)
or is an inline descriptor of the same closed shape. A descriptor is a package without
paths: `files` (published file name to sha256), `submission`, `tables`, `reference_metadata`,
`analysis`, `analysis_inputs` and `expect`. `directory` holds the files under their
published names; every digest comes from the descriptor, so a changed byte refuses. The
request's `analysis` supplies what the tables cannot, namely `pdg` and `generation`
(and optional `references` pins). `expect` pins record facts beyond the digests (each
table's DOI, the region window population, the limit mass population); a mismatch refuses.
In a table mapping, a qualifier `value` written as a plain number matches the source
qualifier by numeric value rather than by its literal text.

One descriptor ships: the four regional distributions and the coupling and
cross-section-times-branching-times-acceptance limit tables of the published ATLAS
dijet-plus-photon search (HEPData release, version 1; see the descriptor's `source`), with the exact digests,
ordered headers, region identities, units, applicability and source discrepancies the
earlier source-specific producer carried. The downloaded files are not shipped.

For another release, write a descriptor (or an external package) with its exact pins,
ordered headers/qualifiers, region identities, quantity units, normalization
applicability, discrepancies and missing scientific inputs. Missing package, grid or
output fields raise `MissingInputError` with reason `missing-input` and a field identifier.

Published postfit curves remain references. Never round them into integer
observations or turn marginal bands into joint covariance or auxiliary sampling
laws. A displayed signal scale, omitted unit, branching/acceptance convention or
source discrepancy stays supplied metadata. No width broadening, coupling map,
fit, detector calibration or scientific acceptance is inferred.
