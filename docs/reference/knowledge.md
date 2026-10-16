# Generated knowledge atlas

RAVEL indexes its scientific operations, scoped workflows, lifecycle stages,
commands, installer groups, validators, computed alarms, handbooks, pitfalls,
traps, protocols, instructions, skills and role declarations in one atlas.
The atlas supports the reading and planning parts of an open scientific research
loop. Its rows identify available source contracts and their evidence boundaries.

Use these commands from a source checkout or an installed package:

```sh
ravel modes list
ravel modes show model-events --json
ravel modes example formula-grid --json
ravel knowledge find "recast a search for a new model" --kind op
ravel knowledge for_node --operation model-events --json
ravel knowledge for_failure --tool MadGraph --failure-class missing-card --json
ravel knowledge plan_check --plan plan.json --json
```

`modes list` projects the science-mode rows from the atlas. `show` returns the
source pins, links, contract vocabulary and validation tier. `example` returns
existing packaged examples or curated examples; it exits with status 1 when
curation has supplied no example. Copy the referenced inputs before using an
example in a run. Example task-schema validation does not authorize execution.

The Python API is `ravel.workflow.knowledge.query(op, **args)`. Queries return
`knowledge-result` records with `results`, `served_ids`, an atlas hash, a result
hash and an omission census. `find` uses BM25 with deterministic identity ties.
Kind filters narrow the search. Results have a 32 KiB default budget;
`--max-bytes` changes it. An oversized argument envelope is refused.

`for_node` follows the operation's handbooks, checks, traps, tools, documents and
role links. `plan_check` reports missing handbooks, examples, role cards and
requested validation tiers for each node. An absent operation remains an explicit
gap. Failure queries return relevant source knowledge and state that the dedicated
failure-router registry supplies authoritative classification. `coverage`,
`constants`, `xsec` and `conventions` report a missing store until their query
adapters are installed. They return no inferred physics values. Run-bound
restrictions, role gating, served logs and MCP serving belong to the query broker.
Workers use its broker action.

Regenerate the committed atlas after changes to indexed sources:

```sh
python -B -m ravel.workflow.knowledge_atlas --write
python -B -m ravel.validation.check_knowledge --structural
python -B -m ravel.validation.check_knowledge
```

Generation parses declarations and source syntax without executing scientific
adapters or native tools. The structural gate checks source drift, completeness,
uniqueness, schemas, links, mode adapters, worker destinations, documentation and
inverse handbook mappings. The default gate also requires every science card's
`use_when` and a passing offline example. Missing operation curation fails that gate.
The structural option reports those gaps as advisories; it does not establish
complete operation-card acceptance. Source deletion or a newly registered mode
without a descriptor fails the structural gate.

Each source pin uses a repository-relative path and SHA-256. Hand-written
operation curation can change only `use_when`, `do_not_use_when` and `examples`.
`operation_signatures.json`, premise and role files are read when present.
Descriptor terms remain `declared_vocabulary` until typed signatures exist.
Typed signatures also declare operations that are not science modes. Each
becomes an operation row with its implementing module and review checks:

| Operation | Implementation |
|---|---|
| `acquire-published` | `ravel.workflow.resource_census`, the resource sweep over published records |
| `analysis-lifecycle` | `ravel.workflow.workflow_state`, the route-a-run lifecycle stage |
| `lifecycle-routine-recast` | `ravel.workflow.workflow_state`, the routine-recast stage |
| `lifecycle-scan-aggregation` | `ravel.workflow.scan_orchestrator`, the scan-aggregation stage |
| `lifecycle-shape-fit` | `ravel.physics.shape_fit`, the shape-fit stage |
| `lifecycle-summary-overlay` | `ravel.plotting.summary_overlay`, the summary-overlay stage |
| `lifecycle-workspace-limit` | `ravel.physics.pyhf_exclude`, the published-workspace-limit stage |
| `grid-recipe` | `ravel.workflow.grid_recipe`, a parameter grid from declared axes given as data |
| `table-bin-edges` | `ravel.physics.table_bin_edges`, binned values from a table that states contiguous intervals |

Every registered mode has a signature. `python -m ravel.validation.signature_conformance`
checks that each entry resolves to its implementation, uses known artifact kinds with
witnesses and carries no paper or benchmark identifier. Another package proposes rows with
`--entries FILE`. A passing signature declares shape, not scientific validity.

### Quantity contracts on composition edges

Structural witnesses remain useful for shape checking. Rate, exposure, yield,
template and inference consumers also declare `require.quantity`. This contract
compares explicit scientific metadata; it does not certify the supplied facts.
Old artifacts and receipts remain readable. Missing descriptors or properties
become located `quantity_obligation` CHECK-IN flags on consumers that require them.
No unit, factor, selection or weight convention is filled in automatically.

An artifact can carry this optional `quantity` object; a plan edge carries the
same supplied facts under `require.quantity`:

```json
{
  "kind": "event_count",
  "unit": "events",
  "normalization": {
    "per_luminosity": false,
    "per_bin_width": false,
    "per_event": false
  },
  "included_factors": [
    {"name": "decay_mode", "kind": "branching_fraction", "value": 0.4,
     "source": "supplied:decay-table"}
  ],
  "weight_convention": "signed",
  "selection": "fiducial-a",
  "model_point": {"model": "model-a", "mass": 80},
  "bin_ids": ["region-a:0", "region-a:1"],
  "exposure": {"id": "sample-a", "revision": "revision-a"}
}
```

The kind vocabulary is `cross_section`, `differential_cross_section`,
`event_count`, `efficiency`, `acceptance_efficiency`, `luminosity`,
`sample_exposure`, `statistical_model` and `inference`. Units are literal and
include their scale: `pb`, `fb`, `nb`, `events`, `1`, or a stated differential
unit such as `pb/GeV`. The existing weighted-event scale convention has 1 pb =
1000 fb = 0.001 nb. An edge comparing pb with fb is refused even though an
explicit conversion operation could relate them. The descriptor never rescales
numbers or derives a conversion from an axis label.

The three normalization booleans say whether the values are per unit luminosity,
per bin width, or per event. Integrated absolute yields declare all three false.
A cross section, including a differential one, is a rate per unit integrated
luminosity and declares `per_luminosity` true; an event count declares it false.
A flag contradicting the kind is refused.
The existing binned-value validator checks representation, unit, bin identity,
moments and covariance; its normalization and statistical-domain checks remain
in force. A descriptor contradicting the artifact's unit, representation or
producer bin identities is refused. A normalized shape cannot enter the existing
absolute-yield statistics interface by changing its descriptor.

Each included factor has a unique name, kind (`branching_fraction`,
`filter_efficiency`, `k_factor`), finite value and literal source locator. A
missing source is an obligation. Repeating a name refuses double application,
even if the second entry claims another source. An explicit empty list declares
that none of these factors is included. Weight conventions are `signed`,
`absolute` or `unweighted`; changing a producer's signed convention to absolute
is a contradiction. `selection` is the supplied fiducial or selection identity;
`model_point` retains the supplied model identity and coordinates. Neither is
inferred from filenames.

Consumers use partial exact requirements and a `required` list of field paths:

```json
{"quantity": {
  "required": ["included_factors", "weight_convention", "selection", "model_point",
               "bin_ids", "exposure.id", "exposure.revision"],
  "kind": "event_count", "unit": "events",
  "normalization": {"per_luminosity": false, "per_bin_width": false, "per_event": false}
}}
```

A missing property produces an obligation with its edge location, field and
expected value. A contradiction produces `quantity_incompatible`, including the
field, observed value and expected value. An edge annotation cannot override a
producer declaration. Absence and explicit false or an empty factor list are
distinct. Requirements never use `_require_ok`'s permissive missing-property
behavior for scientific metadata.

Signatures can also declare `quantity_relations` between incoming slots. An
`equal` rule names `slots` and `fields` that must agree where both inputs state
them, including shared properties of partial objects. Only the consuming slot's
own requirements create missing-field obligations. A published background-only
workspace needs no signal model point or signal selection. If both inputs state
a model point, conflicting shared coordinates are refused. Ordered `bin_ids` bind a
signal template to the likelihood's exact bin order; equal dimensions alone do
not suffice. A shared sample `exposure.id` and `exposure.revision` bind all
regional contributions to the same production revision, so an updated signal
contribution with a stale control contribution is refused. Complete signal
quantities also carry `regional_exposures`, a nonempty mapping from each supplied
region identity to its sample `id` and `revision`. Every entry must agree with
the shared exposure; missing entry properties remain obligations. This catches
stale control contributions within a single complete template. The consumer
requires this mapping but its source must establish completeness. Optional `group_by`
field paths scope equality, for example by model point and sample identity;
distinct model points do not acquire a false shared-exposure requirement.
A `disjoint` rule on `auxiliary_information` rejects overlapping information
identities across constraints, including duplicate identities in one artifact.
Sharing a nuisance parameter is allowed; reusing its auxiliary observation as
independent information is refused. These identities must be supplied from the
statistical construction, not invented by the composition checker.

`signature_conformance.edge_report(..., artifact=document)` checks an actual
artifact against both endpoint declarations and returns `errors` and structured
`obligations`. `edge_errors` returns only contradictions; callers presenting a
plan must also retain obligations. `validate_request_plan.check` and `flags` use
the same checker; their optional `artifacts={edge_id: document}` argument checks
actual edge documents and cross-input relations. Without documents the check
compares declared plan facts only. It neither authenticates source bytes nor
proves that a numerical producer honored its declarations. Existing custody,
approval, domain and physics-certification gates keep those responsibilities.

The shared binned-value builder accepts `quantity` as supplied metadata;
`from_quantity(..., descriptor=...)` explicitly attaches it when projecting
weighted moments. This projection, regional yield templates, event production,
generated event transport, columnar histograms and cutflows, and signal-template contracts declare `signed`
because they retain weights or supplied values without taking their magnitudes.
Here `signed` describes sign preservation even for an entirely positive sample;
it does not assert that negative events occurred. These known producer contracts
also declare the convention in operation signatures. An undeclared producer
leaves a located weight obligation at a consumer that requires it; absence alone
does not refuse composition. Search and measurement projections preserve
present metadata.
Partition merging already requires equality of nonadditive metadata and therefore
refuses quantities with different conventions.

A review term in a signature resolves first through the alias map
`REVIEW_TERM_CHECKS` in `knowledge_atlas.py` (term to implementing check), then to a
source-declared check of the same name. A term with neither gets a
`check:review/<term>` row with status `declared_term` and the summary "no implementing
check linked". That row is a named term, not a check, and queries report it as missing.

Operation tiers require explicit qualification evidence and default to
`registered`. Registration alone supplies no native or physics qualification.

`qualification.json` carries one row for every pinned tool-census entry. Its
historical statuses map executed entries to `qualified`, failed executions and
installed-only entries to `built_but_unqualified`, source-only and proposed
entries to `not_installed`, and refused entries to `excluded`. The row's scope
states that the source census reports historical evidence. This mapping does not
inspect the current machine or certify a new scientific result. Every descriptor
tool resolves to an installer declaration or an explicit `not_installed` row.

The symbolic rows identify the current routes: FeynRules and SARAH for model
sources and derivation; FeynArts for amplitude construction; FeynCalc and
Mathematica for symbolic evaluation; FeynGraph for diagram enumeration;
HEPTAPOD/Diagrammatica for symbolic code construction; pySecDec and FORM for
finite integrals. The operation descriptors and adapter pins define their scope.
SMEFT appears in EFT running, matching, observable and fit descriptors; model
sources and generation remain separate operations with their own admission.

The six schemas in `src/ravel/data/knowledge/schema/` define atlas entries, query
results, bundle indices, premises, lessons and outcomes. Each store keeps its own
records. The atlas indexes their declarations when they are present.

## Lessons, exclusions and outcomes

`src/ravel/workflow/lesson_store.py` holds the episodic stores. Shipped lessons live in
`src/ravel/data/knowledge/lessons/` and are reviewed by developers. Project lessons live in
`.ravel/knowledge/lessons/`. Both stores are empty until real runs produce tickets.

- **Writer and do-not-learn gate.** `write_candidate` records new candidates only. It refuses
  a lesson that fails the `knowledge_lessons` record rules or lacks `evidence.origin`
  (request digest and run id). It also refuses a lesson that rests only on reviewer verdicts
  or model prose, or that carries a withheld identifier or number the harness supplies. A
  trigger that fires on more than 30% of retained runs is refused. So is text that weakens a
  check, trap, gate or threshold under the protected-path rule. Without that rule the gate
  refuses every lesson.
- **Lifecycle.** `to_trial` needs recurrence in two runs or a reviewed RCA ticket with a
  receipt. `promote` needs a trial record and a held-out paired replay. The replay must gain on
  one declared metric and harm none. The confirming check must fail before the fix and pass
  after it, and a clean control must pass. Harm revokes the lesson. `apply_versions` makes a
  lesson dormant when its pinned versions are no longer current. `check_knowledge` applies
  `promotion_errors` to the shipped store.
- **Serving gate.** `served_lessons` and `bundle_items` decide what a role card receives at a
  node whose run facts fire the trigger:
  - Candidates go only to RCA investigators and the consult for the lesson's tool.
  - A trial lesson appears only on the "with" side of a paired arm.
  - At most three promoted lessons are served; the rest are omitted as `procedural_cap`.
  - Reviewer cards receive nothing.
- **Benchmark arms.** `load_lessons` reads the local store `live`, `frozen` from an
  `export_snapshot` (which drops harness-excluded ids, runs or requests) or `disabled`.
  `record_store_state` writes the mode and snapshot digest into the run.
- **Exclusions** (`lesson_store_exclusions.py`). A negative result is recorded as one of four
  kinds:
  - `prediction_mismatch`;
  - `rejected_in_scope`, which needs a complete refutation signature with comparator,
    sensitivity and counterexample receipts;
  - `execution_failure`;
  - `untested`.

  Only `rejected_in_scope` becomes an exclusion. Reopening triggers are typed predicates.
  Reopening creates a request, not support. A re-proposal must state what differs from the
  signature.
- **Outcomes** (`lesson_store_outcomes.py`). `write_outcome` records one row per completed
  task from receipts: run and request digest, operation, analysis, implementation, basis,
  certification tier, structural key, result pins, discrepancies and metrics.
  `prior_outcomes` returns earlier rows with the same structural key. Neither declares novelty.

The `lesson-distiller` role card is in `src/ravel/data/lessons/lesson-distiller.card.json`. It
drafts candidates from closed tickets and never proposes another status.

## Reinterpretation ranks and Higgs reference-data registration

`ravel.workflow.recast_route.rank_routes` reads the packaged backend census on every
call and preserves all routes, reasons, missing-tool fixes and the census hash. Ranking
uses basis/family compatibility, exact metadata matches, historical qualification and
mapping count, with backend ID as a deterministic tie breaker. Mapping counts do not
measure executed physics coverage. Caller-supplied doctor observations label readiness;
without them, historical installation evidence never becomes current machine readiness.

The separate `data/knowledge/higgs/SOURCE.json` registration is an acquisition hold,
not a physics-value table. Its URLs and expected filenames are source locators supplied
by the design, not fetched or verified in this checkout. Local documentation has no
byte-size estimate; the explicitly labelled planning allowance needs owner verification.
The hold records what approved source extraction would make possible. Neither this
registration nor the schema provides Higgs physics values or an `xsec` query adapter.

`load_higgs_source()` and `load_higgs_tables(directory)` in
`ravel.validation.constants_manifest` read local files only. An installed registration
must name `table: {path, sha256}` and nonempty `source_files: [{path, sha256, url}]`.
Paths are ordinary local basenames. The table must satisfy
`data/knowledge/higgs/schema.json`; citation `source_file` and `locator` must resolve to
one of the pinned primary sources. Each `citation_key` resolves in the table's
`citations` mapping. Rows declare an absolute asymmetric envelope around
`reference_value`; a value outside it fails. Ratios refer to two row IDs with identical
units and a positive denominator, and are recomputed within a declared absolute
tolerance. Synthetic tables are test-only and require explicit `allow_synthetic=True`;
they are never used by the doctor as installed physics data.

These checks establish a numerical and provenance contract, not validation of source
extraction or scientific applicability. The operational handoff is in
[Step 1](../workflow/steps/01-environment.md).
