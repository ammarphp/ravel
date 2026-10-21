# Supplied native grouped-fill acquisition

`native-group-acquisition` consumes supplied native trace and RAW files; it never
launches a native program. Its task is `{schema_version:1, input, request_sha256}`.
The pinned request contains `schema_version:1`, `operation:"acquire-groups"`,
`contract`, `trace`, `raw_yoda`, `source_evidence`, `event_inputs`,
`execution_evidence`. Each file is pinned by path and SHA256. The existing science
plan, approval, supervised execution and custody review remain required.

The contract declares its source `routine`, `native_analysis_alias`,
`original_source_sha256`, complete `events`, `weight_mapping`, `outputs`,
`reference`, `native_object_inventory`, `same_process_pid`, `native_weight_cap:0`,
`group_rule:"independent_single_subevent"`, `schema_version:2`, and `fill_schema`.
Missing `fill_schema` raises `NativeGroupFillError` with `reason="missing_input"`.
No source roster, namespace suffix, measurement mode, unit conversion or geometry
is selected by a routine identity.

The fill schemas of the three released routines whose fill sites were source-reviewed
ship as descriptors in `src/ravel/data/analysis_assets/group-fills`.
`ravel.physics.shipped_assets.group_fill_contract(routine, rivet_prefix=..., mode=...,
weight_suffixes=...)` binds one to an installed Rivet 4.1.4 prefix: it checks the routine
source and reference bytes against the descriptor's pins, takes edges from that reference,
and returns the `fill_schema`, `outputs`, `reference`, `routine`, `native_analysis_alias`
and `original_source_sha256` members for the run's contract. The native object census
follows from the output tables and the selected weight suffixes; a routine that books other
objects lists them in `extra_native_objects`.

The supplied fill schema has `schema_version:1`, the same `routine` and
`native_analysis_alias`, a pinned `source`, complete dependency `sources`,
`sites`, `outputs`, `rules`, `native_object_paths`, and `study`. Each site specifies
`id`, coordinate `arity` (one or two), exact source `anchor`, occurrence `count`,
and `max_per_event`. Each output supplies its site, native path, id, ordered edges,
reference path, quantity/axis units, source fill weight/fraction, and the grouping
interval when its site has two coordinates. Source fill weight and fraction are
restricted to one; other fill weighting laws must be represented by a
qualified extension rather than silently approximated.

The output list must equal the supplied whole booking list, its edges must match
the pinned reference, and every site must be represented. Source anchors and all
dependency hashes are checked. Relationship rules declare `equal_count`, `implies`
or `ordered` on explicit site lists. No channel-specific relationship is built in.
The exact full native object path population is supplied, including ancillary
objects whose error/status tokens are retained without reinterpretation.

`study` supplies `{study_id, parameter_grid, datasets, output:{stem, formats}}`;
formats choose JSON and/or Markdown. Report filenames follow this supplied stem.
Event identities bind source-file hashes and encounter ordinals. Complete original
weights, trace event order, RAW finite/flow primitives and once-per-event counters
are reconciled in an immutable bounded source snapshot.

Per-fill squared weights and group outer products are separate estimators.
Repeated fills in an event enter one shared vector before the group moment;
signed and zero weights and empty groups remain. Acquisition grants no correlated
subevent collapse qualification, native execution authentication, sparse sampling
calibration or covariance inferred from marginal native errors. Native qualification
uses a separately admitted source-selected job through the ordinary launch guard.
