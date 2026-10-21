# Supplied columnar query and quantity contracts

`dataset-query-quantities` connects supplied dataset, query, observable and presentation
contracts to the ordinary scientific-study lifecycle. It uses the ServiceX
FileList/Query interfaces or supplied native ROOT/Parquet returns, then checks
the complete returned population and grouped quantities. Inspection records the supplied
contracts; execution uses the scientific readers and credentials declared for the study.

Use the scientific-study intake in `docs/workflow/start.md`. The task is exactly
`{"config":{"path":"...","sha256":"...","size":123}}`. The configuration
and every consumed document use digest-and-size pins and closed schemas.
`ravel.physics.dataset_query_quantities.specification(task, source=..., assumptions=...,
actors=..., max_seconds=...)` produces an ordinary unapproved schema-2
specification. Supply the actual proposer, executor, physics critic, skeptical
verifier and decider. Declared actor names do not authenticate their identities.

The supplied schema-1 analysis has `task_id` (an arbitrary label),
`source_question` (a supplied source pin), `observables`, `weight_names`,
`weight_semantics`, `scale_factor_semantics`, `source_filter`, `sampling_law`,
`event_domain`, `dataset_components` and `presentation`. Each observable supplies
its own quantity axes, bins, representation and normalization. There is no
installed study roster, identity admission rule or observable-count expectation.
The query and analysis sources remain independently pinned; changing a label
must not change their selection or provenance checks.

`event_domain` has the complete `datasets` identifier list and an explicit
`prefix`, either null or `{"events": N, "source": PIN}`. It must equal the
supplied dataset contract's population and prefix. Applying a prefix requires
complete known source exposure and unique source entries, ordered by declared
member then source entry. The complete source exposure is required for the
full prefix. Rejected selections and zero-object events retain their proper
prefix denominator; incomplete native returns refuse.

`dataset_components` explicitly requests per-dataset contributions. They retain
shared-event/group covariance and one full-population normalization denominator;
component errors must not be summed as independent uncertainties.
`presentation` independently supplies `plot_kind` (`histogram`, `dataset_stack`
or `none`) and unique `formats` (`png`, `pdf`). A stack requires supplied
components, but component accounting can accompany a histogram. `none` requires
an empty format list and delivers tables. No identity chooses a prefix, grouping
or plot. Missing required inputs raise `MissingColumnarInput`.

`ravel dataset-query-quantities population --analysis analysis.json` displays the supplied
analysis population. `ravel dataset-query-quantities context --task task.json --output
fresh-context.json` performs source-only inspection. The Host tool
`dataset-query-quantities-context` binds its exact dependencies through Graph context
checks. Execution remains the approved science route, existing fresh child and
native supervisor, with no new direct launch path.

The specification admits one attempt, zero automatic redos and the
`dataset-query-quantities-delivery` scope with only the delivery action. Integrity, complete
population and weighted-quantity checks still require ordinary reviews. Reports
contain complete JSON/Markdown quantities and the explicitly requested PNG/PDF
figures. Native output, a context packet and synthetic figures grant neither
scientific acceptance nor broader authority. Service behavior, source-query
meaning and normalization applicability require independent qualification.

## Native source interface and custody

The configuration selects `query_and_analyze`, `analyze_returned_native_files`
or `observe_existing_remote_request`. It binds dataset and analysis documents,
a reviewed executable Python bundle and entry file, interpreter, site roots,
complete runtime-tree manifests, package versions, operation-specific service
or return declarations, and finite time, RAM, output, row and group-product
bounds. A supplied source bundle is executable code and requires source review.
The entry exposes:

- `query(dataset, analysis)`: the supplied FuncADL query for the ServiceX client.
- `correspondence(paths, dataset, analysis)`: a complete source-bound return manifest.
- `analyze(tables, files, dataset, analysis)`: all event records with `event_id`,
  `group_id`, `member_id`, `source_entry`, explicit `selected`, named signed
  `weights`, and every observable's `fills`.

Datasets bind unsigned member URIs, explicit source exposure or null, membership
authority, filter and member ordering. Return manifests bind the full dataset
digest, member exposure and many-to-many native-file correspondence. The worker
checks actual Parquet/ROOT row counts and connected source/return components.
JSON masquerading as native data, absent members and inconsistent counts refuse.
Native row counts establish returned exposure, not source identity, source order
or query correctness. Complete member/entry correspondence remains a reviewed
source premise; it requires the declared original source ordering and population.

A remote submission exception retains ambiguous state and prohibits automatic
duplicate submission. Existing-request observation requires the previous intent
and query identity and never submits a query. Cancellation acknowledgement and
independently observed terminal status are distinct; remote containment requires an independently observed terminal remote state. Public
contexts export only whitelisted request/status/count observations. Credentials
are referenced and resolved at the isolated native boundary. Complete runtime
membership and byte checks happen before and after consumption; they are finite
checkpoint observations, not continuous filesystem locks.

## Service endpoint and credential: yours to supply

RAVEL ships no ServiceX endpoint, no token and no `servicex.yaml`, and it never reads one from
your home or analysis directory. `query_and_analyze` and `observe_existing_remote_request` take
both from the `service` block of the configuration you supply:

- `endpoint`: the HTTPS URL of a ServiceX deployment you are entitled to use (required).
- `credential_reference`: `{"kind": "environment", "name": "YOUR_TOKEN_VARIABLE"}` names the
  environment variable that holds your access token, or `null` for an endpoint that needs none.
  The token is read at the isolated native boundary and is never written to a report.
- `codegen`, `result_format` and `cancel_if_failed`: the query code generator, the `root` or
  `parquet` return format, and whether a failed request is cancelled.

The worker writes a private, non-secret client configuration from these fields for each run.
A configuration whose `service` is absent or names no endpoint is refused before anything is
dispatched with `MissingServiceEndpoint`, which says what to supply. A named variable that is
unset in the worker's environment refuses the run with the same reference missing.
`analyze_returned_native_files` needs no endpoint or credential: it checks native files you
already hold and has no `service` block (`"service": null`).

## Quantities and presentation

Signed variations, group cancellations, bins, flows and denominator moments are
retained by the quantity engine. Event-common weights are broadcast to fills;
object fills are not treated as independent events. Raw cross-observable moments
remain available, while cross-observable normalized covariance is explicitly
unprojected. `upstream_per_fill_diagonal` records individual-fill squared weights
separately from shared-event covariance. Raw unweighted means and fills/event
metrics have an explicit selected-event or source-prefix denominator; empty
means remain unknown. The conditional group law does not establish detector,
scale-factor, theory or integration uncertainty qualification. Physical unit
conversions and normalization must be explicit and reviewed in the supplied
quantity contract.

Component delivery retains full bins, flows, marginal covariance and shared
full-population denominators, including in-range normalization. Its raw flow is
full-population custody, rather than a per-component flow. Represented products
are charged against the same finite budget. The renderer uses total grouped
covariance for stack error bars, preserves signed components with separate
positive and negative baselines, and records central-value aggregation roundoff.
It retains actual bin geometry, gaps and source units without rebinning or
rescaling. Requested PDF figures are vector graphics and PNG figures use 220 dpi;
layout lint, `iris-plot-contract.json` and report links describe their content.
Matplotlib and mplhep are required toolchain dependencies.
