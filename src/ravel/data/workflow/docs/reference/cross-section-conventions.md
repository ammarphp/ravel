# Supplied cross-section conventions and production bases

The cross-section service accepts pinned published tables and explicitly selected,
provenance-bound calculation tables. It executes no generator or network job when
looking up a supplied table. Calculation and reference qualification remain
separate admitted work. No local calculation denominator is installed as a default.

Use `ravel xsec supplied --request <contract.json> --out <result>` for a selected
calculation table or a batch, and `ravel xsec correct --request <correction.json>
--out <result>` for a like-for-like correction. The existing `ravel xsec lookup`
accepts an individual supplied table request too. The `nlo_xsec` import delegates
to this service; bare process names and bare numerical grids receive
`missing_cross_section_input`. No process name establishes a perturbative order.

## Selected tables

A version-1 individual request contains `basis`, `sqrt_s_GeV`, `masses`,
`convention` (`order`, `pdf`, `scale`), `charge` and `state_count`. The last two
are explicit and can be null when the basis has no such multiplicity. Its
`table` selects:

- `path` and `sha256`: exact JSON bytes with a `data` object of nested numerical
  coordinate keys and leaves containing positive `xsec_pb` values;
- `parameters`: distinct dimension names in nesting order, matching `masses`;
- `interpolation`: `exact`, `linear` or `loglog`;
- `provenance`: nonempty `kind`, `reference` and `justification` describing the
  supplied source, its calculation conventions and its applicability.

Supplied tables must name the actual PDF and scale; `as-published` is resolved
only by the pinned-table registry. Paths are relative to the request or
transformation contract. Table coordinates
are positive finite values. Missing nodes, empty corners, duplicate numerical
coordinates, changed bytes and extrapolation are refused. Interpolation uses a
complete enclosing rectangle in every declared dimension. Relative uncertainties
are interpolated linearly; missing uncertainties stay unknown. The calculation's
integration precision and physical applicability must be qualified independently.
Changing a table's state count requires supplying its corresponding calculation;
this path never infers a multiplicity rescaling.

A `cross-section-batch` contract adds `study_id`, an explicit `datasets` population,
`output_format` (`json` or `jsonl`) and `points`, each with a distinct `tag` and
individual `request`. Any finite supplied parameter population uses the same
loader. JSON contains the metadata and point list; JSONL carries one point per
line with the supplied metadata. This is a serialization choice, not a figure
layout. The prospective science-mode input census pins every selected table.

## Correction policies

A correction contains `numerator`, `denominator`, `interpolation` and a nonempty
`justification`. Both records must match in basis, collision energy, parameter
coordinates, charge and state count. Orders, PDF sets and scales remain explicit
on each side. Neither the service nor the caller imposes a process-specific
numerical window on the ratio.

`ratio-of-lookups` divides the selected cross sections. `ratio-linear` computes
ratios at common nodes of two supplied tables and interpolates that ratio in the
parameter coordinates. It needs a complete common enclosing rectangle and never
falls back to another policy. The reported effective numerator is the chosen
ratio times the selected denominator; both original lookup records and the common
nodes are retained. A smooth-ratio approximation must be justified by the supplied
contract; a software identity check does not establish that approximation.

## Normalization and rebasing

Apply a correction to an existing assembly with:

```bash
python scripts/run.py ravel.workflow.scan_orchestrator assemble <scandir> \
  --normalization-contract <contract.json> --out <result>
```

A `cross-section-renormalization` contract has the batch metadata above. Each
point has `tag`, `parameters`, `correction`, `replaced_kfactor` and
`application_justification`. The replaced factor must match the actual source
normalization at that point. Its applicability to the sample, including any
representative-state or inclusive-to-filtered approximation, must be justified.
The service applies `mu_scale = replaced_kfactor / correction.k_factor` and
scales `sigma_ref_fb` inversely. Thus `mu95 * sigma_ref_fb` is invariant, including
expected quantiles and numerical brackets. Different source factors are allowed
at different points. The result preserves the original artifact and exact inputs
in `normalization_change`; there is no rounding of physics values.

Use a production-basis transformation when comparing different denominators:

```bash
python scripts/run.py ravel.workflow.scan_orchestrator rebase <scandir> \
  --transformation <contract.json> --out <result>
```

A `production-transformation` contract has the same batch metadata. Every point
supplies `parameters`, `source` and `target` cross-section requests,
`shape_justification`, and complete `components`. Each component names `id`,
`source_states`, `target_states`, `source_yield_fraction`, `response_ratio` and
`justification`. Source yield fractions must sum to one, state populations must
be disjoint and match the declared counts, and an omitted target contribution
must have zero response ratio. A zero source contribution cannot establish a
nonzero target response. Unknown contamination or acceptance must not be replaced
by zero without a supplied, justified assumption. This transformation assumes
unchanged accepted shapes; otherwise the signal template and inference need
recomputation through the admitted workflow.

Let `S` be the source cross section, `T` the target cross section, `f_i` the
fraction of accepted source yield from component i, and `r_i` its target yield
per unit total cross section divided by its source yield per unit total cross
section. Then `R = sum(f_i * r_i)`, `mu_target = mu_source * S / (T * R)`, and
`sigma_ref_fb = 1000 * T`. An inclusive-versus-filtered transformation can supply
its acceptance ratio through `r_i`; no factor, state population or contamination
assumption is implicit. The source cross section must agree with the actual row
normalization, and collision energy must not change. Every point coordinate must
match the source row, either in its `parameters` mapping or its named fields.
A supplied `coordinate_bindings` mapping can name a different source field;
missing source coordinates are refused rather than inferred from the table.

Every point is validated on a copy before the population is changed. Partial
mutation, repeat transformations and mismatched populations are refused. Missing
transformation inputs carry `missing_production_transformation`. Numerical root,
bound and eligibility semantics are preserved, and exclusion status is recomputed.
The result records `model_basis`, exact source and target records, component
accounting, justifications and the selected contract hash. The requested format
controls the resulting JSON or JSONL file; downstream readers must support the
chosen format. A general comparator and independent supplied-reference
qualification establish numerical fidelity separately from these algebra checks.
