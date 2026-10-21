# Paper-first routine construction

`ravel agentrivet-construction` connects a complete supplied paper and HEPData
context to the released external AgentRivet role factories, Memory and ReviewLoop,
then to Ravel's existing source, build, event and independent delivery services.
A routine absent from the catalogue needs no prior routine capsule. Existing
source/capsule and runtime-template routes remain available.

This is source buildout. No model, compiler, event run or paper reproduction
was executed while authoring it. The external
AgentRivet repository and GPL license stay separate; its prompt/function bodies
are not bundled in Ravel. Supply an exact complete source census. Pydantic v2 is a direct required host dependency (`pydantic==2.14.0`), matching
the retained full-host identity. The selected Host/runtime must be available; this adapter
loads core, the four role modules, Memory and (for `89903d0`) `build.py` from
admitted buffers, without importing the original provider SDK modules, `utils.py`
or package initialization. It does
not download papers, HEPData, source, credentials or dependencies.

## Compatible upstream commits

The bridge runs the original ReviewLoop, so it accepts only upstream trees whose
loop and Memory it has checked. `ravel.workflow.agentrivet_pins` records the
SHA-256 of every accepted file per commit. Preparation, every later source reload
and `inspect_binding` compare the supplied tree with that record.

| Commit | Status |
|---|---|
| `e4d12ec` (tag `agent-rivet-0.2.0`, 2026-06-18) | Default. Accepted. |
| `cebc8e9` (main, 2026-10-03) | Accepted. Its core, Memory and four role files are byte-identical to the tag. |
| `89903d0` (main, 2026-10-10) | Accepted. Its ReviewLoop compiles each draft and skips both reviews after a failed compile. RAVEL supplies the compile: see "Construction checks". |

Any other tree is refused with the list of accepted commits.

For `89903d0` the core imports `utils` (only for `detect_rivet`) and `build`.
RAVEL loads `build.py` from the admitted bytes and supplies `detect_rivet` itself:
the in-loop compile gate is on exactly when the request declares construction
checks and they are approved. Upstream `utils.py` is never executed. During
`ReviewLoop.run` the module-level `build_routine` is bound to RAVEL's observed
compile check and restored afterwards, so `rivet-build` runs only as a journaled,
approved RAVEL launch. Without declared checks the gate stays off and the loop
behaves like the tag. Memory then holds one draft per iteration and either both
reviews or `None` reviews after a draft whose RAVEL-observed compile failed;
every upstream `BuildResult` must equal RAVEL's record of that compile.

While original upstream code runs (module import, role construction,
`ReviewLoop.run` and repair calls), a guard refuses process starts
(`subprocess`, `os.system`, `os.exec*`, `os.posix_spawn`, `os.fork`), thread
starts, and file or directory creation directly in the working directory. It is
one audit hook installed once per process and scoped to the calling context, so
RAVEL's own provider dispatch and construction checks are unaffected. A refusal
that upstream code catches is still raised when the guarded block ends.

To check a real upstream tree, set `RAVEL_AGENTRIVET_UPSTREAM` to a checkout and
run `tests/unit/test_agentrivet_upstream_control.py`; it is skipped without one.
For `89903d0` it also checks that the original `build_routine` is refused under
the guard and that the bound one returns RAVEL's compile result.

## What each role sees

Each role call presents three things to the model:

- the original system prompt, as the model's instruction, followed by a short
  fixed transport note;
- the original user message, in the `upstream-user-message` input;
- a RAVEL brief, in the `ravel-brief` input.

The upstream source files, `COPYING`, the paper file, the HEPData files and RAVEL's
adapter code stay in custody: their hashes are in the operation contract and are
checked before and after every call, but they are not shown to the model. The
paper reaches the Analyst through the original Analyst prompt.

The brief depends on the role:

| Role | Brief contents |
|---|---|
| Analyst | routine name, HEPData tables with binning, analysis specification, ambiguity record, normalization contract |
| Coder | routine name, Rivet authoring guidance and the `rivet-routine` handbook, review checklist, HEPData tables, analysis specification, ambiguity record, normalization contract, latest check of the draft under revision |
| Code reviewer | routine name, review checklist, HEPData tables, check of the draft under review |
| Physics reviewer | routine name, review checklist, analysis specification, ambiguity record, normalization contract, check of the draft under review |

The routine name is the original Memory name that the build's registration probe
requires. Preparation computes it and refuses a name that is not a native
identifier before any role call is charged. The authoring guidance and the
checklist are in `ravel/data/rivet/construction.json`. The checklist covers
lepton dressing, lepton origin, jet inputs, overlap removal, vetoes, fiducial
cuts, missing momentum, frames and pairing, fills per event, normalization,
units, 2-D slices, bookings, projections and weights.

## Prepare the original task

Use scientific intake to retain the original task contract and assignment. Create
an ordinary research campaign with that exact `goal_binding`. Scientific-context
and campaign APIs remain the scheduler and resource authority. Each role call is
an immutable one-call child executed by
`research_cycle.execute_graph(campaign_root, child_graph, spec, host)`.
This boundary also applies when the ordinary executor uses LangGraph. No second
scheduler, native controller or automatic approval is introduced.

The `prepare` request has exactly these fields:

| Field | Meaning |
|---|---|
| `schema_version` | Integer `1` |
| `campaign` | Existing original-goal-bound campaign directory |
| `upstream` | `root` and complete `files` list of `{path, sha256}` relative members |
| `paper` | `{path, sha256}` for the complete nonempty extracted UTF-8 paper text |
| `hepdata` | `context` pin or null; complete explicit `assets` list |
| `construction` | Optional: `analysis_spec`, `hepdata_record`, `normalization` and `checks` (each can be null) |
| `metadata` | Literal `arxiv_id`, `inspire_id`, `collaboration`, `preprint_year`; only `arxiv_id` is required nonnull |
| `provider` | Exact `model`, `reasoning_effort`, `max_calls`, `max_output_tokens`, `max_wall_seconds` |
| `initial_rounds` | Integer 1–3 original ReviewLoop rounds |
| `max_native_repairs` | Integer 0–2 repair triplets, reserved in addition to the initial rounds |
| `review_policy` | Existing ordinary schema-2 scientific review envelope |
| `approval_mode` | Existing ordinary approval mode; it does not itself grant approval |

Include every `.py` under external `agentrivet/`, `pyproject.toml` and `COPYING`.
Other explicit Markdown/source metadata can be retained. Members must be ordinary,
unaliasable files, each ≤1 MiB, complete population ≤64 and aggregate ≤8 MiB.
Paper/context/individual asset/request JSON inputs have an explicit 8 MiB bound.
The normal Host retains its own complete-context ceiling (default 2,000,000
bytes, configurable up to 16,000,000), UTF-8 input admission and response ceiling;
exceeding these refuses rather than presenting a truncated paper. The Analyst's
context holds the complete paper, so callers must budget for it. Binary reference/native inputs require the existing
typed witness/native paths.
There are at most 32 assets. Each asset is `{path, role, input}`: canonical distinct
capsule-relative name, existing source role and `{path, sha256}` input. A HEPData
context has exactly `hepdata_info` (string/null) and `hepdata_map` (object). These
remain source declarations; their scientific meaning requires independent review.

Reserve `max_calls = 1 + 3*(initial_rounds + max_native_repairs)` (4–16), 16–32000
output tokens per call and total wall time between that call count and 7200 s.
Repairs never consume an initial round. The initial Analyst and every prospective
triplet remain in the denominator even if the original loop stops early.
Role-child time ceilings partition the original wall allowance; the deadline
begins with the first actual child and is not reset by native feedback or
reinstantiation. Construction checks, compiler and event attempts consume their
own admitted budgets. The campaign also retains its original cumulative clock
and ceilings.

### Construction inputs

`construction` adds what the original roles lack:

| Field | Meaning |
|---|---|
| `analysis_spec` | `{path, sha256}` of a typed analysis specification (`typed-analysis-spec`, with source spans and field status), or null. Every span is checked against its source by `ravel.workflow.analysis_spec` (sources resolve beside the specification); the checked sources are pinned in the captured construction as `analysis_spec_sources`. Its ambiguous and unspecified fields form the ambiguity record, and a histogram item's `slice` enters the normalization contract. |
| `hepdata_record` | `{path, sha256}` of a HEPData record document, or null. Preparation builds the table map (`dNN-xMM-yKK` identities, labels, bin edges and values), the Analyst's HEPData context from it, and the reference file `<routine>.yoda` as a `reference` asset. Supply either this or `hepdata.context`. |
| `normalization` | List of `{object, basis, unit, slice}` rows, or null to take them from the specification's histogram items. `basis` is `xsec`, `fiducial_N`, `in_range_N`, `bin_width_area_2D` or `raw`; `xsec` and `bin_width_area_2D` need a cross-section `unit`; `bin_width_area_2D` needs its `slice` `{variable, low, high}`. |
| `checks` | Construction checks (below), or null. |

The record document is `{"schema_version": 1, "kind": "hepdata-record", "record":
<URL or null>, "tables": [...]}` with tables in record order, each in the HEPData
submission layout or the table JSON that `hepdata_fetch --tables` retains.
`ravel rivet-hepdata-map build --record <document or fetch directory> --out map.json`
builds the same map; `reference` writes the reference YODA and `verify` checks a
routine source's `book()` calls. A table without contiguous numeric bin edges is
mapped with `edges: null` and must not be booked by identifier; no binning is invented.

### Construction checks

Checks give the roles compiler, registration and sample feedback during
construction:

```json
{"schema_version": 1,
 "runtime": {"rivet_build": "<path>", "rivet": "<path or null>", "python": "<path or null>", "environment": {}},
 "compile": {"max_probes": 4, "timeout_seconds": 120},
 "sample": {"events": {"path": "<HepMC>", "sha256": "<sha>"}, "max_events": 200, "timeout_seconds": 300, "tolerance": 0.02}}
```

`sample` can be null. `environment` names only build variables (`PATH`,
`LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`, `PYTHONPATH`, `CXX` and the like).
`max_probes` is at least `initial_rounds + max_native_repairs` and at most 12; each
draft is checked once. Preparation records each tool's executable identity and
the sample's hash; a change refuses the next check.

Before generation, record the one approval of the declared checks:

```sh
ravel agentrivet-construction approve-checks --request prepared-pin.json --base . --quote "<assent>" [--scripted]
```

`--scripted` is required for a `scripted_yes` request and refused otherwise. The
receipt is never expert or physics review. Generation then reserves the whole
ceiling (`native_attempts = max_probes`; wall time for every compile,
registration and sample run) against the original campaign, once. Each process
start is recorded in the construction's launch journal (`logs/authorization`)
as an authorized event followed by a launched event. Each check runs in a fresh
`checks/probe-NN/` directory with a closed environment:

1. `rivet-build` compiles the draft. The record keeps the compiler output and its
   parsed `{file, line, column, severity, message}` diagnostics.
2. With `python` declared, RAVEL's loader observer checks that the plugin registers
   the routine name.
3. With a sample declared, the routine runs on at most `max_events` events. The
   findings cover missing or non-finite outputs, empty histograms, more fills than
   events, output binning against the record, and each normalization row:
   the final/RAW area ratio must match the contract within `tolerance`; a
   mismatch is labelled unit, slice width, bin width, factor two or unclassified.

The record of each check, plus static `book()` findings against the table map,
goes into the briefs of the reviewers of that draft and of the coder of the next
draft. The checks are construction feedback only. The sealed `routine-build`
study, the full event run and the independent review remain required.

Run from the source checkout or installed CLI:

```sh
ravel agentrivet-construction prepare --request preparation.json --base . --out construction
```

Preparation returns a request pin. Save that **pin object** (not the unpinned
request body) as `prepared-pin.json`. Then:

```sh
ravel agentrivet-construction context --request prepared-pin.json --base .
ravel agentrivet-construction generate --request prepared-pin.json --base . --host-config host.json
```

The public Python functions in `ravel.workflow.agentrivet_construction` accept the
same pin objects. `AgentHost` tools `agentrivet-prepare` and `agentrivet-context`
accept `request_input`, and preparation also requires `output_directory`. Bind
all `input_pins(request, base)` as actual Graph inputs. These deterministic tools
prepare/inspect only; they do not nest a model or native dispatch. Generation is
an explicit ordinary operation using the configured Host. Credentials remain in
the Host's selected environment variable, outside request/context/result files.

## Autonomous coordinator operation

`research_tools.routine_operations()` publishes the source-bound action catalogue.
After the ordinary research decision Graph returns, the coordinator can call
`research_tools.routine_workflow(campaign, choice_pin, output_dir, host,
max_wall_seconds=...)`. It builds the deterministic preparation Graph itself,
then invokes the original role loop through charged one-call Graphs. The planner
need not receive a prewritten generation Graph or an existing catalogue routine.
Call this operation outside an executing campaign Graph, after that Graph releases its campaign lock.

The choice is an authenticated JSON document, with either exactly
`{"kind":"paper-first","request":<complete-preparation-request-pin>}` or
`{"kind":"existing-source","specification":<ordinary-specification-pin>}`.
The outer coordinator `choice_pin` has `path`, `sha256` and `size`, as other
research-tool choices do. Nested construction/source pins have `path` and
`sha256`; the final `completion` pin keeps the public task-completion API’s
original `path`, `sha256`, `size` contract. Existing-source reuse preserves the original assignment and makes no
new generation calls. A fresh handoff returns the generated ordinary source
specification; the coordinator admits it through the existing portfolio/lifecycle
and uses normal approvals, worker execution and review.

For subsequent observed outcomes, `research_tools.routine_step(campaign,
selection_pin, base_dir=..., host=..., output_dir=...)` accepts a size-bound
selection document with exactly `action` and `arguments`. Its actions are
`prepare-build`, `prepare-events`, `repair` and `close`; argument envelopes are
the same complete envelopes described below. The Host is required only for a
repair triplet; fresh output directories are required for build/event preparation.
This hook returns evidence to the original assignment and does not manufacture
native execution, review votes or whole-task closure. The stateful research
coordinator's routing/checkpoint implementation is a separate source join;
this connector retains the public `research_cycle.execute_graph` boundary.

## Generation, build and complete events

The first call uses the original Analyst prompt builder on the complete paper and
HEPData context. Original Coder, CodeReviewer and PhysicsReviewer factories share
one bounded provider. Original initial stopping rules are retained. The original
Memory-derived routine name must be a valid native identifier; supply the literal
source metadata needed for that name. This adapter does not rewrite an arXiv ID,
collaboration or publication identifier to obtain a compilable name. Upstream
reviews are advisory producer annotations and carry no Ravel scientific-review
vote. Raw C++ is returned in a `text` JSON field and original structured output
schemas are adapted to the existing finite Host schema.

The selected draft is the upstream-accepted draft; otherwise the last draft whose
RAVEL-observed compile (and registration, when probed) passed; otherwise the last
draft. The generation result records the selection, and the source request names
it when it is not the last draft. `construction-evidence.json` lists every draft's
check record, the selected draft's check and bookings, the review checklist, the
ambiguity record and the normalization contract. `prepare-events` adds it to the
event study's grounding, so the independent reviewers read it.

Generation retains complete raw Memory, C++ and role transcripts/call receipts,
and emits a parent-bound ordinary `analyze/agentrivet-source` specification. Plan,
verify, obtain the applicable recorded approval and execute that specification
through the existing scientific lifecycle. An ambiguous/failed role outcome keeps
its charge and blocks repeat dispatch. Initial generation is not reinitialized.
Cached upstream Memory prefixes are not admitted by this fresh-generation route.

`prepare-build` takes an envelope with `request`, `generation`, `source_rundir`,
`reviewed_capsule`, `closure`, `runtime`, `workload` pins and the complete `probe` object. It
requires the actual current successful ordinary source result, unchanged generated
specification, every source/domain review obligation and complete transitive
source/runtime closure. A new routine can supply:

```json
{"schema_version": 1, "kind": "agentrivet-runtime-declaration", "runtime": {}}
```

The empty runtime above is a schema sketch and is refused. Supply all real
`tools`, `artifacts` and `environment` required by `routine-build`; the builder
seals those exact identities against this new reviewed source. A legacy sealed
`rivet-plugin` runtime template is also accepted. No old capsule, execution
identity, probe arguments, acceptance or approval is transferred.

`prepare-events` takes `request`, `generation`, `build_rundir`, `event_task`,
`histogram_mapping` and a pinned `workload`. Actual current successful `routine-build` delivery, complete
build-plan/receipt and generated source identity are required. The existing
`rivet-built` consumer retains the supplied complete event population, signed
weights/group correlations, raw histograms/counters, units, normalization and
runtime/metadata requirements. The mapping lists every original Analyst histogram
in original order as `{index, path}`, with unique native paths present among the
full event observables. Additional counters/observables stay in the event task.
This structural mapping does not establish semantic paper or HEPData equivalence.

Both `prepare-build` and `prepare-events` require a `workload` path/SHA pin.
Its original document is exactly:

```json
{"schema_version":1,"kind":"agentrivet-ordinary-workload","operation":"events","construction_request":{"path":"<original-construction-request>","sha256":"<original-sha>"},"max_seconds":900}
```

Use `operation: "build"` for a build. The example ceiling is a schema example,
not a runtime estimate or permission to spend 900 seconds. Supply the actual
prospective **whole ordinary study** ceiling, including worker/native/custody
work. It must fit the unchanged original campaign's remaining cumulative wall
and native-attempt budget and its original elapsed deadline. Preparation does
not debit, renew or approve those resources: the existing ordinary experiment
admission must separately reserve a cost that contains this exact ceiling.
The role-provider wall allowance must not authorize native work. The unchanged
adapters' inner admission bounds must also fit the declared whole ceiling.

Event transport resolves only typed filesystem operands against the caller's
original `base_dir`: event/metadata/runtime files, grounding, native source
excerpts, centrality preload plus original output, and lineage/evaluation pins.
Native YODA object paths, operands, units, weights, bins and all population stay
literal. Complete original input identities are observed before and after
preparation and enumerated in `source_inputs`; the ordinary emitted spec resolves
the same files from its own parent. Original pinned nested lineage/evaluation
records are never rewritten. Exact operation grounding already present is kept
once; conflicting identities, source aliases and duplicate original resolved
inputs still refuse.

Each preparation writes a distinct ordinary specification. Use normal plan,
verify, approval and run commands; source preparation must not launch the native
job. Native success does not close the original paper task.

## Feedback and independent delivery

`repair` takes `request`, `generation` and `feedback` pins plus the same Host.
The feedback is either a canonical `failed_stage_diagnostic_intake` authenticated
by the existing retained-failure verifier, or exactly:

```json
{"kind":"agentrivet-current-review-send-back","rundir":"<actual-event-run>","claim_scope":"<current-scope>","summary":"<public proposed revision focus>"}
```

The latter must match the actual current scientific send-back and successful
ordinary event/source custody. The original generated source must be an input to
the relevant ordinary attempt.

Repair sends the original coder RAVEL's revision request: the routine name, the
analysis summary, the selected draft and the feedback as text. For a failed
stage this is the decoded stdout and stderr of the retained build or event logs,
with compiler diagnostics; for a send-back it is the summary and the unresolved
findings. The coder also gets its brief. The two original reviews follow; with
the compile gate on, they are skipped as upstream does when RAVEL's check of the
new draft fails. Repair preserves the old raw outputs, removes any earlier
upstream accepted marker from the new Memory, and must not rerun the Analyst,
renew the budget, replace a superseded predecessor or inherit a scientific vote.
Exhaustion leaves the task open.

`close` takes `request`, `generation` and a size-bound `completion` pin
(`path`, `sha256`, `size`), preserving the public gate’s exact original input. It verifies the exact
selected built routine in a current successful ordinary event outcome and then
calls public `task_completion.require_final`. Complete original obligations,
independent child reviews, original-parent report and CI3 authority remain the
public gate's responsibility. Upstream approval, a compile result, agreement with
one plot or this connector's presence must not substitute for that gate. Returned
`parent_task_accepted` reflects that public acceptance; `physics_validated` remains
false because this wrapper is not a physics certification service.
