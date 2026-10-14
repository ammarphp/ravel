# From a research question to a complete supplied study portfolio

`scientific-delivery` connects primary-resource capture, original-task intake,
literal table delivery, basis-aware portfolio grouping, and existing ordinary
study or publication plans. It uses the common scientific worker and the existing
typed artifact/report and publication contracts. It creates no new renderer,
likelihood, research graph, approval mechanism, or backend runner.

The operation serves a summary question such as a neutral-resonance search survey
and a prospective hypothesis question such as toponium or semi-visible jets.
These can share source/report infrastructure while retaining distinct models,
production channels, widths, energies, branching conventions, interference,
units, and applicability domains. Source preparation does not establish the
answer, discovery completeness, a calibrated constraint, or publication delivery.

## Capture primary resources

Use an exact HEPData record and version. Every table in the returned record needs
an explicit `capture` or `context` disposition. Table IDs, rather than names,
determine filenames, so colliding table-name slugs cannot overwrite one another.
The whole record is retained even when some tables are context only.

Illustration with invented record and table numbers:

```json
{
  "schema_version": 1,
  "record_url": "https://www.hepdata.net/record/ins0000000?format=json",
  "expected_recid": 100000,
  "expected_version": 1,
  "table_dispositions": [
    {"id": 1000000, "state": "capture", "reason": "Requested quantity"}
  ],
  "assets": [],
  "max_total_bytes": 209715200
}
```

This abbreviated example must be expanded to include every actual record table;
it deliberately cannot claim or pass a complete record census as written.
Optional assets declare `id`, `url`, `format`, and `expected_sha256` (a digest or
`null`). Available formats are `text`, `pdf`, `json`, `hepdata_yaml`, and
`hepdata_record_data`. The callable and CLI are:

```python
from ravel.physics.scientific_delivery import acquire
manifest = acquire(request, fresh_directory)
```

```sh
python -m ravel.physics.scientific_delivery acquire acquisition.json --out fresh-capture
```

Acquisition uses the existing verified-TLS HEPData transport, with a 30-second
request timeout. It bounds cumulative reads before collecting the response,
then classifies, hashes, and copies that same byte snapshot. Record/table JSON is
limited to 4 MiB, each additional asset to 16 MiB, and the whole acquisition to
the declared limit of at most 200 MiB. It admits at most 128 record tables and
64 additional assets. Failure retains partial bytes and an acquisition-failure
receipt, and does not publish a success manifest. Network availability, redirects,
and collaboration publication identity still require actual source assessment.

## Describe the supplied portfolio

The task is `{"schema_version":1,"input":"delivery.json","input_sha256":"..."}`.
The input is a closed `scientific-delivery/v1` request with these fields:

| Field | Contents |
|---|---|
| `schema_version`, `kind` | `1`, `scientific-delivery/v1` |
| `parent` | Existing task-completion contract pin and exact assignment ID |
| `questions` | Unique IDs, complete assigned obligation IDs, requested quantity text |
| `discovery` | Dated `as_of`, explicit `scope`, source IDs, complete supplied candidate IDs |
| `resources` | ID to `{pin,format,citation}`; pin has exact path, SHA256, size |
| `acquisition` | Exact primary-resource manifest pin, or `null` |
| `knowledge` | Existing physics-knowledge retrieval request pin, or `null` |
| `studies` | One disposition for every supplied discovery candidate |
| `routes` | Exact existing ordinary v2 study/publication specifications |
| `publication_required` | Boolean; missing publication route remains an open obligation |

All original assignment obligations must map to a question, and all questions
must remain represented by studies. No shortened replacement prompt is generated.
Discovery is a complete **supplied** census; an exhaustive or current literature
survey is not asserted. Resource citation and applicability text remain authored,
source-declared statements requiring scientific review.

Each study has `id`, `question_ids`, `source_ids`, `basis`, `applicability`,
`tables`, and nonempty `limitations`. The closed basis contains:

```json
{
  "model": "HVT A gV=1", "resonance": "Zprime", "spin": 1,
  "decay": "WW", "production": "qqA", "width": "source-defined narrow template",
  "energy_tev": 13, "branching_convention": "sigma times BR(Zprime to WW)",
  "interference": "source-defined treatment", "quantity": "observed upper limit",
  "unit": "pb", "domain": "source-defined search selection and mass support"
}
```

Each field may instead be `null` when unknown. Unknown fields cannot be called
`source_declared` compatibility. Applicability declares a `state` of
`source_declared`, `unresolved`, or `incompatible`, a `reason`, and located
`evidence_ids` from the study's sources. Unknown or incompatible studies stay
separate even when their null fields match. Fully known, source-declared bases
group only on exact equality of all twelve fields. Grouping never authorizes a
common curve, acceptance conversion, statistical combination, or theory covariance.

A table declaration contains `source_id`, `expected_rows`,
`expected_axes_sha256`, and `columns`. The axes digest uses the existing canonical
JSON digest of the complete parsed independent-variable blocks. Every dependent
column needs a unique `{index,state,reason}`, with state `deliver` or `context`.
Every delivered column exposes all original rows; context columns retain their
whole source payload. There is no implicit mass window, interpolation, error-law
construction, matrix summation, or marginal-to-covariance synthesis. Source
nulls and `-` remain unknown rather than becoming zero. YAML numeric lexical
tokens and complete errors/qualifiers are preserved. Record/data JSON keeps its
whole original block alongside the exact rectangular view.

Source-declared delivered units must match literal source units. The operation
cannot manufacture a unit from a model label. The generic report accommodates
point, bin, categorical, and multi-axis source coordinates. Publication mass
mapping is narrower: it requires literal one-axis point coordinates in GeV and
cannot relabel histogram edges or category labels as masses.

## Use the ordinary worker and existing report contracts

Supply an ordinary schema2 scientific specification with `mode` equal to
`scientific-delivery`, the task above, the exact original `goal_binding`,
bounded resources, and the normal prospective review policy and correction
contract. This new mode refuses schema1 scientific lifecycle specifications.
The shared worker creates a fresh child destination, and constructs the adapter's
report using the existing reporting branch. Normal planning, approval, execution,
and scientific review remain distinct steps under `docs/workflow/reference/scientific-studies.md`.

The source operation has `validate(task)`, `inputs(task,base)`, and
`run(task,base,fresh_out)` for the existing lifecycle. Ordinary intake parses the
retained source graph; it can therefore do adapter parsing before a worker is
approved. That is source intake, not a governed scientific attempt.

The result retains full sources, complete tables, selected cells, exact basis
groups, candidate dispositions, question bindings, continuation obligations, and
the complete input snapshot. Cell IDs derive from study/resource/column/row
identity. Reports paginate 32 cells at a time through existing
`scientific_artifact` and `scientific_report` selectors, including coordinate,
value/errors, header/qualifiers, and unknown state for every cell. The top-level
report links exact retained page paths; its directory may differ from the
adapter's output directory. Generated page sources, reports, raw copies and route
witnesses are checked before a success portfolio is published.

The graph admits at most 512 files and 200 MiB, the selected population at most
32,768 cells, and the final portfolio at most 32 MiB. Larger requests must be
explicitly partitioned; overflow is refused rather than truncated. A successful
preparation reports `parent_task_complete:false`, `publication_delivered:false`,
`common_basis_physics_qualified:false`, and `statistical_inference:null`.

## Connect actual existing study or publication routes

Each route declares `id`, complete `study_ids`, `role` (`study` or `publication`),
an exact `spec` pin, and `quantity_bindings`. Ordinary study routes use an empty
quantity-binding list. Their complete normal task input graph is captured; an
arbitrary backend payload is not relabeled as a source table. A backend portfolio
must provide a reviewed typed/source mapping or an explicit continuation route.
Failed and unreviewed backend results acquire no acceptance from this operation.

Publication routes must use the existing `published-summary` schema2 adapter and
its figure-target, source, publication-style and runtime contracts. The route's
candidate denominator and original parent question must equal the delivery
request. Its candidate model basis must match the supplied study, and drawn
series need fully known, source-declared applicability. Incompatible domain or
interference declarations cannot share a panel.

Each drawn `mass_gev`, `obs`, `exp`, or `theory` series with any nonnull value needs
one exact mapping:

```json
{
  "study_id": "atlas-hvt-qq", "panel_id": "qq", "curve_id": "atlas-hvt-qq",
  "series": "obs", "source_id": "original-limit-table", "column": 0
}
```

Mass mappings use `column:null`. Full vectors, including excluded display anchors,
must equal the existing manifest after explicit finite decimal-to-binary64 display
projection. No invented sample, resampling, conversion, underflow, or truncation
is admitted. This projection establishes display correspondence, not numerical
precision. Scientific source assumptions and actual publication-runtime/style QA
remain obligations of the existing route. The publication route serves any declared
model, process and experiment set through the requested-summary contract in
[published-search-summary.md](published-search-summary.md).

```python
from ravel.physics.scientific_delivery import plan_route
plan = plan_route(prepared_portfolio, "publication", fresh_ordinary_run)
```

`plan_route` rechecks all captured sources and calls the existing `science.plan`
on the original pinned specification. Copied route files are witnesses, not
silently relocated relative-path specifications. This action creates metadata;
it does not approve, execute, render, or import a previous decision. Existing
physics-knowledge retrieval can supply conflicts and omitted-node context, but
neither retrieval nor this source operation turns an exploratory hypothesis into
a verified applicability statement.

Portable controls exercise fabricated primary transport, complete lexical tables,
incompatible basis partitions, unknown cells, paginated reports, original-parent
guards, exact source-to-publication vectors, actual ordinary metadata planning,
and the shared worker/report route with only execution authority mocked. They
make no live HTTP, native, model, provider, fit, or publication-render calls.

The ordinary delivery input hook requires its outer `goal_binding` to equal the exact inner parent before planning creates a run. A published-summary specification must declare publication role with full joins; a study label cannot bypass those checks. Final report attachment verifies every referenced page source and report pin before publishing either top-level file.
