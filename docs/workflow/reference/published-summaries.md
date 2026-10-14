# Supplied published-limit summaries

The proposed `published-summary` scientific mode delivers a supplied census, common-basis
manifest, complete source identities, a required PNG/PDF figure and CHECK-IN 2. It reuses
`summary_audit` and `summary_overlay`. It performs no literature search, event generation,
acceptance calculation, likelihood, statistical combination or new limit.

The ordinary task is closed:

```json
{"schema_version":1,"input":"summary-contract.json","input_sha256":"<64 lowercase hex>"}
```

The input contract has kind `published-limit-summary/v1`, exact pinned `survey` and `manifest`,
a finite explicit `source_assets` map, one `candidate_sources` entry per candidate (identity,
declared full mass range, collision energy and source IDs), the digest of each complete
`resolved` series, collision `energy_tev`, a declared mass `window` with an explicit inclusive
or exclusive upper boundary, and short `census_scope` and `precision_scope` statements.

Each source pin is exactly `{path,sha256}`. Paths resolve relative to the contract. They must
be ordinary unlinked stable files. JSON documents are at most 1 MiB, individual evidence files
4 MiB and the total source graph 32 MiB. The adapter enumerates this explicit graph during
intake. A pinned wrapper does not implicitly authenticate undeclared referenced files.
Opaque PDFs/figures retain custody but still require a scientific source reader.

All resolved series retain positive finite values or explicit nulls. Mass coordinates are
positive and strictly increasing; series lengths and hashes are exact. Every retained curve's
full endpoints must agree with the census. Out-of-range exclusion must actually be outside
the requested window. Plotting roles/dispositions must agree and all eight existing audit
rules must pass. Declared gaps must equal intervals with no retained curve in this supplied
census; this is not an exhaustive claim about all current searches.

The renderer receives a separate window view. Full source arrays, out-of-window values and
unavailable expected/theory entries remain in the result. A null-only visible series has no
legend entry. No theory outside the requested window is extrapolated. Connecting retained
plot points does not add a numerical interpolation sample. The public adapter always uses
the plot-lint gate; the legacy renderer CLI's explicit `--no-lint` option is separate.

For a half-open window, an exact supplied point at the upper boundary may serve as a display
clipping anchor when there are selected samples below it. It is listed separately in
`render_manifest.excluded_boundary_anchors` and remains `in_requested_window=false` in the
complete series. No sample beyond the boundary or invented interpolated value is used.
The plot annotation states this distinction. Line endpoints indicate retained sample
support; they do not measure the end of a search's sensitivity.

Use version 2 of the ordinary scientific specification with a prospective review policy.
The mode refuses legacy version 1 authority. The existing worker supplies a fresh
`outputs/attempt-1/published-summary` child directory; the adapter refuses existing outputs.
Source byte identities are checked again after rendering. Missing required PNG/PDF/census/
manifest/audit/report files refuse delivery. Failed partials are retained.

The supported claim is `source_bound_published_summary_delivery`. Independent review must
assess the actual source figure/table, production/spin/width and sigma×BR conventions, all
candidate dispositions, digitization accuracy, legend/gap statements and complete actual
output. A machine PASS does not certify physical applicability, current census completeness
or model exclusion. New data/curve conversions require new declared source inputs and review.

From an accepted source epoch, the ordinary lifecycle is:

```sh
ravel plan --rundir summary-study --spec science-spec.json
ravel approve --rundir summary-study --quote 'The actual assent to this exact proposal'
ravel run --rundir summary-study
```

The recovered HVT summary preparation has no new ordinary approval or worker result. It keeps the
historical digitized numbers and uses a derived metadata artifact to correct the stale 200 GeV
HVT census/gap to 250 GeV. The reacquired paper's generic 200 GeV abstract range includes other
models; its HVT quark-annihilation result begins at 250 GeV. The five retained historical
candidates do not establish a complete current ATLAS/CMS search survey. The historical saved
audit, figures and benchmark `partial` status remain unchanged.

The private V2 successor additionally records primary-reader corrections to historical
annotations and CMS figure version names. Its retained theory array has an unvalidated
model association: the old Model A label and inter-paper theory agreement are not identity
evidence. The numerical values stay unchanged; no theory is displayed below 500 GeV and no
Model B reassociation is inferred. Expected curves from different datasets are not treated
as statistically redundant, and older observed limits need not lie above newer limits.
