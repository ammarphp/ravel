# Durable open-question research

Outcome metrics expose `resource_use.resource_vector` with wall hours, CPU hours,
peak RAM, disk footprint, events, model calls, model tokens and queue hours.
Whole-campaign values remain unknown without a complete measurement instrument.
Separate call/stage observations and token subtotals retain their own coverage;
inclusive durations are not added into a campaign total. Total cost and human
intervention counts remain unknown. Machine assent does not identify a human.

An experiment can retain `inputs/method_choice_comparison.json` with
`schema_version: 1`, `kind: method-choice-comparison`, a `method_decision` pin
(path, SHA-256 and size) naming its retained `inputs/method_decision.json`,
`compared_rung`, `native_launches`, `model_calls` and nonempty `evidence`. The
compared rung must be above the selected rung. Metrics retain these comparisons
and expose `avoided_native_launches` and `avoided_model_calls` for the observed
comparison census. Missing comparison counts remain unknown. These counts are
recorded counterfactual comparisons, not measured campaign benefits or actual
provider dispatch. A cheaper rung alone supplies no avoided-call count.

The default open research route preserves the original intake question and lets a charged designer propose the method, rival hypotheses, discriminating tests, source preparation and subsequent actions. The caller supplies the task, available inputs, actual configured Host, review policy and finite resource ceilings. A prewritten experiment DAG is not required. An independently supplied complete scientific context remains a direct route.

## Ordinary entry

### Interference measurement instance

`ravel amplitudes research-parents` lists the interference instance and its component
signatures. `ravel.physics.amplitude_chain.prepare(request, output_dir)` binds an
existing `goal_binding`, the literal original `question`, and pinned `conventions`,
`integration`, `events`, `predictions`, `measurement` and `comparison` documents.
The request has `schema_version: 1`, `kind: interference-research-request` and a
`histogram` naming the supplied RAW output. Pins carry absolute `path`, `sha256`
and `size`. Supply the phase convention, numbered assumptions, interpretation
traps and the signed definition `2 Re(A_fixed* A_scaled)` before integration.

The instance lists conventions, amplitude integration, weighted-event RAW analysis,
binned predictions, sign/size verification, measurement inference, an interference
ablation and delivery. RAW and stored-point documents must have the same hypotheses,
coupling polynomial, units, representation and bins. Supply the same
`coupling_scaling` in both documents so every signed term reaches Rivet as a
named weight. The fitted reference, terms and their complete joint block
covariance come from the Rivet-selected RAW output, including when the event
document declares a shower. Selection or shower migrations may differ from
the stored-point selection. The measurement supplies its
statistic, covariance, scan and domain; its input kind is
`interference-measurement-input`. The comparison has kind `interference-comparator`
and supplies `statistic`, `quantity`, `unit`, `source` and `values`; its statistic
must match the measurement. The likelihood retains the covariance of all stacked
polynomial terms and their cross-covariances, including in the ablation arm.

An optional request `born_comparison` declares `rtol`, `atol`,
`covariance_rtol` and `covariance_atol`, all finite and nonnegative. Defaults are
respectively `1e-8`, `1e-15`, `1e-7` and `1e-20`, recorded as defaults in the
diagnostic. The prediction stage pins `born-rivet-diagnostic.json` and
`rivet-likelihood-input.json`. Residuals outside tolerance are retained with
`gate: false`; they do not block a selected-stage study. RAW stream, bin,
exposure, normalization and covariance integrity still refuse malformed input.
Delivery records `fitted_prediction`, `fitted_terms` and `fitted_stage` separately
from the Born `prediction` and stored-amplitude sign witness. Its selected-stage
provenance records the declared shower state and attempted-draw normalization.
See the [polynomial handoff](../../reference/amplitude-reweighting.md#coupling-polynomials)
for several-coupling fragments and the existing scan adapter's scope.

`amplitude_chain.run(parent_pin, runners=ordinary_study_runners)` requires runners
for its integration and `weighted-events` stages. Each runner takes
`(stage, *, base_dir, output_dir, goal_binding)`, preserves that assignment and uses
the ordinary approved study and execution-backend services. It returns the component
result and materializes the component's pinned outputs in `output_dir`. Missing
runners hold the stage. Instance preparation grants no CHECK-IN 1 approval,
execution lease or scientific acceptance. Synthetic controls inject inert backends.
Python inference runs the supplied statistic; an exclusion without a prescribed
statistic requires the ordinary likelihood's 95% CLs toy configuration.

Every stage retains an operation, signature and receipt with input and output pins.
The sign witness uses opposite signs of the scaled amplitude and checks each bin
and both flows. Signed `binned_values` delivery uses the yield hub. Completed
receipts are verified on resume; an unreceipted effect requires reconciliation.
Resume Gram integration through its original schedule. A generator survey uses
the existing `model-events` `integration_checkpoint` contract, preserving the
same-run seed lineage and original reservation; the produced events then reach
`event-production` through its existing generation-receipt interface.

Delivery retains our inference, the supplied comparator, the reproduced reference
and the ablation. Its nine scientific methodology stages remain pending until
their actual role reviews run through the research coordinator below. Mock chain
completion establishes operation connectivity and algebraic consistency only.

### Required research stages

`prepare` binds `src/ravel/data/research/protocol-default.json`. The campaign retains the binding in
`<campaign>/research/protocol.json` and its immutable state history. Typed research, method-study,
anomaly-search and method-performance parents also acquire the protocol through direct
cycle creation. An absent protocol, changed evaluator or missing stage artifact blocks the
governed operation. Legacy cycles without a research parent retain their original contract.

The stages run in this order: limitation census, ideas, baseline, screen, validation,
critique experiments, acceptance, meta-review and integrity. Each stage declares its roles,
required inputs, outputs and review-round limit in data. Every stage needs its complete
report and actual role receipts. A stage marked `not_applicable` needs a reason and the
same role review. The two initial idea streams run in one Graph with two workers and
separate source contexts. Neither receives the other's proposal before both finish.

Before experiments, use `research-protocol preregister` to bind a
`research-preregistration` record with approximations and an expected effect. Pin applicable
limit-setting, likelihood-building and cutflow-comparison evaluators; record a reason for
each inapplicable evaluator in `evaluator_not_applicable`. The baseline report retains
three columns: our result, our reproduction and the published result. Each available
column carries its quantity, unit, uncertainty and source. An unavailable column says why.

Screens name their subset and omitted regimes. Promote, discard and engineer decisions
carry RDJ receipts; promotion and selection require R2, other screen decisions R1.
Engineering names its mutable paths. Validation retains withheld cells, ordered evolution
rounds and its success/round stopping rule. Selection uses reviewed dominance. Register
critique findings with `research-protocol register-concerns`: each finding points to a
complete ordinary experiment declaration. Its result closes the concern only after the
ordinary experiment and scientific review complete.

An accepted mechanism claim requires an ablation arm without the mechanism, fixed generic
controls and explicit attribution by the ablation critic. Novelty orders ideas; it cannot
accept a result. Open findings remain exploratory until an R3 decision and independent
review. Meta-review and integrity retain source-bound receipts for re-execution, reference
checks and paper-versus-code alignment. The shared world digest carries current reviewed
results, their scopes, unresolved experiments and discarded directions between decisions.

For keyless work, set the runtime adapter to `external`. Draft the stage report from actual
sources and results, then run:

```sh
ravel research-protocol methodology-status --cycle campaign
ravel research-protocol stage-run --cycle campaign --request stage-request.json
```

`stage-request.json` contains `artifact` (the report PIN), a fresh `output_dir`, and `settings`
with `model`, `reasoning_effort`, `adapter: "external"`, `max_output_tokens` and
`max_wall_seconds`. The returned Graph uses the existing `agent-graph prepare-external`
and `deliver-external` route. Deliver each role from its fresh context, then repeat the same
`stage-run` request. An outstanding delivery stays pending. It grants no acceptance.
Programmatic hosts use `run_protocol_stage`; preparation and adoption are also exposed as
`stage-prepare` and `stage-complete`. Calls retain the campaign's cumulative ledger and clock.

Named stage roles currently run as critic/verifier Graph packets. A dedicated role worker
can take the same stage role IDs and input/output requirements. `research_protocol.gate_errors`
answers the `research_choice` decision gate; it reads the protocol and never dispatches.
These software controls do not qualify native tools, scientific results or research
effectiveness.

`intake.execution_handoff(contract_pin, base_dir=...)` names the default `research_orchestrator.prepare_open` and `open_research` APIs for research, method-study and anomaly-search parents. Reproduction, reinterpretation, scan, survey, summary-plot, projection and missing-routine parents take the analysis intake and CHECK-IN 1; the [route table](../start.md#which-route-a-request-takes) sets the order. A host may still open this coordinator for them, and each retains its original scientific mode, complete original obligations, figures, statistical requirements and check-in gates. Calculations and named operations keep their intake-planner route, including the validated literal short path. Scoped generation-only and likelihood-only operations do not acquire this whole-goal coordinator. Preparation is an intermediate result; it grants no compute or original-task acceptance. The route table for calculations, research and challenges is in [intake and challenges](../../reference/intake-and-challenges.md).

```python
from ravel.workflow import research_orchestrator
request_pin = research_orchestrator.prepare_open(
    parent_contract_pin, preparation_directory, base_dir=original_input_directory,
    campaign=campaign_settings, runtime=model_settings, evidence=source_inputs,
    candidate_modes=None, review=review_settings, max_decisions=decision_limit,
)
result = research_orchestrator.open_research(
    campaign_directory, request_pin, campaign_directory / "coordinator", host=actual_host,
)
```

`campaign` has `id`, `budget` (`calls`, `output_tokens`, `wall_seconds`, `native_attempts`), `max_experiments`, `exploration_every`, `required_experiments` and `premises`. `runtime` has the exact `model`, `reasoning_effort`, configured `adapter`, `max_output_tokens` and `max_wall_seconds`. `review` has `arguments` for the existing scientific judgment API and `allow_control`; control-only transport is never a scientific reviewer. Each evidence row is `{pin, purpose}` with a complete absolute `path/sha256/size` pin and purpose `model_context`, `execution_dependency` or `withheld_evaluation`. Withheld evaluators do not enter designer inputs. `candidate_modes=None` selects all actual source-present ordinary operations; source presence establishes neither installed readiness nor physics validity.

The CLI exposes the same preparation and continuation:

```sh
ravel research-orchestrate prepare --parent-contract task_contract.json --settings research-settings.json --out prepared-research
ravel research-orchestrate run --cycle original-campaign --request prepared-research/request.json --out original-campaign/coordinator --host-config host.json
```

Repeat the same `run` invocation to resume the original state after the ordinary blocker is resolved. Never replace the campaign or renew an expired checkpoint. The existing explicit blueprint/choice route is `research-orchestrate explicit`; `research_tools.plan_workflow` delegates its real preparation/materialization/admission/selection pipeline to the same framework.

### Engines

`run --engine graph` runs the same nodes as the registered `research.loop` graph on the graph
substrate, with the campaign as its scope root. `run --engine legacy` keeps the earlier state
machine. Without `--engine`, `run` uses the graph engine only while the kept parity record is
current; a coordinator directory stays on the engine that started it.

The parity record (`src/ravel/data/graphs/parity/research-loop.json`) is computed, not written by
hand. Run the parity tests in `tests/unit/test_research_loop_graph.py` with
`RAVEL_PARITY_RESULTS=<file>`, then run `ravel research-orchestrate parity --write --results <file>`.
The record binds the registered loop graph, its child graphs and the loop's implementation
files, and carries each fixture's run-relative snapshot digests from both engines plus its own
digest. `ravel research-orchestrate parity` checks the digest, recomputes equality from the two
snapshot digests, and reports the record as lapsed when any binding changed.

`--engine graph` (and `respond`) without a current parity record is refused. Pass
`--experimental-engine` to run it anyway; every outcome then carries
`engine_label: experimental-engine` and `parity_passed: false`.

The literature scout/source, manuscript build/section and research loop/stage builders
have exact `registered_graph` entries in `src/ravel/data/agents/sanctioned.json`. Each entry names
the builder from `src/ravel/data/graphs/registry.json` and a synthetic instance for the G8 walk.
Research role dispatch uses `graph_substrate.execute_role_graph`; existing legacy
checkpoints pause through `graph_substrate.legacy_pause`. These shared calls preserve
the research service's arguments, results, exceptions and delivery receipts.
After changing a call site, regenerate `call_sites.json` with
`python -m ravel.validation.check_agent_paths census --write`, regenerate the knowledge
atlas with `python -m ravel.workflow.knowledge_atlas --write`, and run
`ravel release check --gate G8 --mode block_new`. Remove obsolete baseline rows; never
add a row. `block_new` requires a current census with zero new and zero stale entries.
The full `empty` gate also requires the remaining baseline and runtime-tripwire work
to be complete. Changes to the research implementation require fresh dual-engine
parity results before the graph engine remains the default.

On the graph engine:

- A `protocol-stage` action runs the `research.stage` subgraph. It writes the same stage files as
  the legacy runner and is committed as that turn's coordinator effect.
- A wait for an outside effect (role delivery, approval, a required stage) is an `external_delivery`
  interrupt. Answer it with `research-orchestrate respond --responses <file>`, a JSON object of
  interrupt ids to `{"response": {"path", "sha256"}}`. The `research_choice` gate then re-derives
  authority from files, and the waiting node re-enters. A response approves nothing.
- A failed or refused action is committed as an `action_failed` observation, and the next
  decision turn sees it. Any other failure ends in a typed status (`decision_required`, `hold`),
  never a refused run.
- `ravel graph stop --scope-root <campaign> --reason <why>` (or `research-orchestrate stop`)
  drains at a step boundary: running effects finish and receipt, and nothing new is dispatched.
  Continue with `run --clear-stop`. `--now` also drains every incomplete child agent Graph and
  terminates only registered process groups. `all_gone` is true only when those groups are gone
  and no runner still holds the loop or a child scope; `running` lists the scopes still held.

Each stage role takes its model from a `runtime.roles` row, then the first model of its card
tier's `runtime.tiers` entry, then the single runtime. A `runtime.tiers` entry is one row or a
list of rows. The tier a role needs comes from its card. The tier a model serves is the best tier
whose `runtime.tiers` entry lists it; the single runtime model serves judgment. A role row cannot
declare a tier. A judgment-tier card on a model listed only under a lower tier, or not listed, is
refused before dispatch.

At R2 and above (screen, validate, acceptance), each critic is checked against its proposer with
`transport_registry.check_distinct_families` before dispatch, on every adapter including
host-delivered ones. A shared family is refused, and so is a family RAVEL cannot read from the
model identifier. Before `complete_stage`, both engines repeat the check on the models the
stage's roles were observed on. Distinct-family critics need per-role stage models, so an R2 stage
whose roles need different models holds with `awaits_prepare_stage_role_models` until
`research_protocol.prepare_stage` accepts `role_models`.

## Decisions, effects and scientific meaning

Before experiments, a real designer produces the complete typed scientific context and maps every original obligation to quantities, method, source and unresolved criteria. Methods, figures, software, comparisons and notes remain in that map. The initial planning-status census cannot substitute for measurable scientific evidence. Fresh critic and verifier contexts inspect the method with actual Host presentation receipts; missing mandatory material or an unsupported method sends it back. Separate citation-led and speculative idea requests receive no peer idea response. Later turns receive the complete current evidence, negative outcomes, unresolved criticism, parent obligations and cumulative resource ledger.

Source preparation invokes the existing allowlisted Host tools through ordinary campaign-charged Graphs. A model can emit prospectively authored JSON configurations only with actual presented source attribution. Those bytes retain configuration provenance; they are not retrieved efficiencies, calibration, covariance, cross sections or observations. Exact prepared output identities and the complete tool result enter a later design turn. Missing inputs are retained actual preparation failures rather than successful empty assets.

The next action can prepare an ordinary experiment, run the actual affordable selection, review it, diagnose an actual failed attempt, revise a premise or hypothesis, prepare source material, invoke a composed routine/manuscript/knowledge service, or deliver progress. Ordinary scientific execution uses the existing plan, CHECK-IN 1 approval, admission, worker, native process custody and observation. Delegated machine approval remains distinct from independent physicist judgment. An unresolved approval, lease, external role delivery or native effect interrupts the coordinator; a resume payload does not approve it.

An ordinary repeat uses `invoke(None)` to re-enter the paused node without supplying an interrupt response. The node checks the actual original approval, worker state or role receipt again. It remains paused while that predicate is unmet. Current review state is checked before and after a review pause; a framework checkpoint or supplied routing response never replaces the ordinary receipt. The retained first installed-runtime batch exposed the earlier automatic-None response defect; its failure remains separate from this unexecuted source repair.

LangGraph owns routing and SQLite checkpoint history. Canonical Graph calls, campaign resource reservations, immutable action commitments, review journals, study receipts and task-completion records own effect truth and authority. Effects run after the selecting Graph releases its campaign lock. On reentry, known effects are reconstructed from those services; an unknown started effect is held rather than repeated. A terminal checkpoint cannot skip the public return's current-source/effect checks. Original `research_cycle.synthesize`, scientific report final gates and `task_completion.require_final` are unchanged. Progress retains every failed/open/inconclusive experiment and the complete parent denominator; checkpoint completion cannot discharge an original question.

## Domain services and scientific job DAGs

The finite service catalogue resolves only located public source functions. Paper-first routine construction and explicit source reuse use `research_tools.routine_workflow`/`routine_step`; manuscript authoring/review/build/finalization uses `manuscript_production`; structural proposals use `research_tools.prepare_model_proposals`. These neighboring packages must be included as exact reviewed additive joins before their actions are available. Their source packages, current controls and native/scientific prerequisites remain separate. No moving donor is imported to make an unavailable action look supported.

The finite catalogue includes source-defined argument and return contracts. Manuscript author returns the writer binding; collect returns the complete package and its package pin. Build returns an ordinary plan, not a completed build receipt. Review retains the complete preparation envelope but executes its nested ordinary role binding. Consume and finalization use those ordinary role bindings, with a real observed campaign experiment/rundir association. Finalization still requires actual independent roles, current PDF build, CI3 and whole-parent acceptance; preparation cannot substitute for any gate.

Original execution-only and withheld inputs stay in complete authenticated custody. If a proposed experiment needs them, its first action materializes the exact study and the existing adapter's full exposure inventory without admitting an experiment. The inventory, configuration and prepared-experiment commitment enter a new charged designer turn; private bodies do not. That turn selects the committed prepared experiment, and the unchanged exposure/model-input admission rules check the full population. A guessed future-study hash, missing inventory, changed private bytes or private content in the model packet refuses.

Method reviews use supported model parameters and actual input/packet subject identities. Both indexed and wholly inline role contexts receive explicit presentation observations from actual Host request content; the observation states presentation rather than asserting model reading. Premise revisions bind their authenticated selecting decision and before-state to the existing immutable campaign event. If an effect checkpoint is interrupted after that commit, reentry reconstructs that exact event instead of revising twice; a different decision or unresolved effect is held.

Ntuple inventory preparation, root-stream and site-workflow remain ordinary operations; reproducible Snakemake scientific job DAGs are complementary to agent coordination. Imported AgentRivet ReviewLoop internals and actual native generators/fits/benchmark Runners remain original services. Stateless Host transports and deadline/cancellation loops remain in Host; no wholesale LangChain migration is claimed.

## Required runtime and honest limits

The full host dependency projection requires LangGraph 1.2.14, SQLite checkpoint saver 3.1.1, checkpoint 4.2.0 and LangChain Core 1.6.7. Pydantic 2.14.0 is the shared direct schema dependency. There is no in-memory persistence fallback. Local SQLite uses synchronous checkpoints and one directory-scoped invocation owner. Exact released wheel metadata/source was inspected independently; the older cached Git source is not asserted identical to the pinned release. Root installation and actual fresh-process controls are still required for this source packet.

Existing caps remain prospective admission rules: ordinary Graph 128 inputs, 256 nodes, 10,000 calls and 86,400-second declared wall ceiling; campaign 128 immutable revisions, 32 experiments and 64 hypotheses; a new open request admits 1–64 decisions and at most 32 initial evidence pins. Complete decision material is limited to 1.5 MB and ordinary declaration JSON to 2 MB. Large/binary material uses existing explicitly prepared pages; inventory hashes provide custody, never content-reading credit. If a complete context cannot fit, the operation refuses; it does not truncate obligations or negative evidence. `continue_campaign` currently caps a newly admitted continuation at 3,600 seconds, an existing long-science integration limitation recorded separately for repair. None of these limits licenses renewal of an expired original deadline.

No author test, framework import, model/provider call, native execution, installation, benchmark run or scientific qualification was performed for this packet. The included controls are executable software proposals for root-supervised runs.


A prepared experiment enters a fresh charged designer turn as its actual complete source pin. Admission authenticates the pin's bytes and size, then matches canonical path and hash against the ordinary Graph input records, which carry an input ID rather than size. A copied or replaced preparation cannot substitute for the one original campaign-committed preparation.

Input exposure uses the same complete ordinary scientific and research-tool context dependency closure as the canonical campaign admission. It includes the original tool bundle, API request/context, blueprint and their source files. A worker-only or withheld input stays custody-bound and classified in the complete exposure inventory; its bytes do not enter the model packet. Public source dependencies must actually be ordinary model inputs. The exposure inventory, task/input preparation, model response and software checkpoint confer no scientific acceptance, compute approval or original-task completion.


### Complete typed progress and human rendering

`research_cycle.progress_synthesis(..., render_text=True)` returns the complete current scientific and operational census and a bounded human narrative by default. The narrative preserves every scientific obligation, quantity, experiment, observation, failed/open result, hypothesis, premise and staged protocol. The existing outcome-metrics summary names unknown provider, cost and correctness measurements. Complete operational call receipts, source pins, events, historical reservations, timing and boundaries remain in the same typed delivery; the narrative identifies their exact fields rather than serializing them a second time. Keep that typed companion when distributing the narrative. A hash or inventory never supplies source-reading credit or acceptance.

The coordinator alone requests `render_text=False` when preparing its ordinary decision context. It receives the same complete census without `report_text`, under the unchanged complete-core and actual Host presentation limits. Human progress retains the existing128KB text ceiling and refuses if its full scientific narrative exceeds it. This changes representation, not the original task, full evidence population, operational ledger, compute allowance or final-report gate.


## Typed charged services

Every ordinary model/tool node enters `langchain_service.ChargedService` before the actual `AgentHost.execute` dispatch. Its required LangChain Core 1.6.7 `RunnableLambda` carries the shared strict Pydantic node/request and result schemas. `get_input_schema`, `get_output_schema` and `config_schema` expose those contracts for framework callers. Invocation accepts the complete current node/request envelope, not messages alone. It authenticates the canonical running attempt, generation, dependencies, Host identity, input artifacts and original Graph deadline. A snapshot or framework schema supplies no authority by itself.

The finite configuration accepts `tags` (at most 16 nonempty strings of at most 80 characters) and `configurable.local_trace` (a Boolean, default true). Source-owned local callbacks retain start/end hashes and run identities in the existing attempt's `service_observation`; they retain no prompt, result body or endpoint credentials. A fresh Python context isolates inherited callback variables. Enabled ambient tracing, debug output and global callback hooks refuse before dispatch; arbitrary callback/metadata configuration is not accepted. This boundary governs this service's framework callbacks, not a configured external provider's own egress or arbitrary trusted Python code.

The adapter passes the Host's original complete JSON result through unchanged, including structured values, model/usage/endpoint identities and actual visual-presentation delivery fields. Before each effect it rechecks the exact consumed envelope and current source; the original `Control.call` still reserves calls/tokens, invokes the original effect and commits its raw result or failed/ambiguous outcome. The same check runs immediately after reservation and before the effect. Host HTTP/command cancellation, cleanup, local-only policy and scientific approval/review gates are unchanged.

Each service instance has one synchronous invocation. Batch, stream, framework retries and effect fallbacks are refused. Known outcomes resume through canonical Graph receipts; unknown effects remain held for explicit reconciliation. The existing framework scheduler can still retry a source-authorized failed generation according to its original rules; the service does not retry a transport or unknown effect. Direct external role preparation remains its separate sealed-delivery route.

The focused controls are software proposals covering a real tiny quantity Host operation, opaque structured/vision fields, source/attempt changes, local callbacks, typed schemas, and ambiguous dispatch. No framework import, test, model/provider call or scientific qualification was performed by the source author for this packet.

## Native model agent loop

`ravel.transports.ravel_loop.RavelLoop` builds a graph-substrate subgraph around
`RavelTransportChatModel` and a trusted `Broker`. The transport registry's
`ravel.workflow.transports.ravel_loop` path re-exports that implementation.
The loop accepts a scope root, an exact instance and parent domain path, worker
budgets, the final JSON schema and explicit tool schemas. `build()` returns an
embeddable compiled subgraph; `run(prompt)` uses the substrate scope lock and SQLite
saver for standalone software qualification. The graph-registry factory `build(ctx)`
consumes `ctx.extras['ravel_loop']` and returns a `StateGraph` builder for substrate
compilation; its scope, version and instance must match the loop binding.
Worker provisioning, protected input closure, role
admission and host-written session receipts remain the dispatcher's duties.
The current argv worker launcher does not automatically choose this in-process
adapter. Its consumer must supply the broker and sealed prompt, use the subgraph,
and validate and publish the returned final record through worker finish.

The chat adapter requires an explicit nonsecret sender identity and request
binding. Its sender receives the complete provider body, a socket timeout and an
optional per-call cost cap, and returns `{body, http_status}`. It implements no
credential discovery or provider SDK. `provider_tools` renders and parses
`anthropic`, `gemini`, `chat_completions` and `responses` turns, preserving function
call IDs and matched tool results. A declared streaming sender must assemble the
complete delivery or raise; a lost sent stream leaves an ambiguous ledger effect
and cannot silently retry. Streaming is opt-in through `streaming_declared` and
`stream_enabled`; current transport declarations do not supply that qualification.

For text-only producers and judgment roles, set `text_protocol=True`. Each turn
must contain exactly one JSON object `{"action":"tool_name","args":{}}`.
Malformed JSON, duplicate keys, multiple actions, unknown tools and invalid
arguments receive typed action receipts and consume a turn. `submit_final` is a
local schema-validated return action. It executes no broker tool and has no
scientific acceptance authority. Supply the actual producer or judgment schema.
When typed toolbelt schemas are unavailable, `tools=None` projects the trusted
broker action list. Provider-safe names map back to the exact registered action;
collisions refuse construction. The generic argument object retains the broker
handler's validation obligation. Explicit schemas and `tool_actions` mappings
replace this temporary seam when the generated toolbelt is available.

Budgets use `max_turns`, `max_wall_seconds`, `max_broker_calls`, `max_cost_usd`
and optional `max_steps` (default: broker-call bound). Each protocol action,
including refusals and final submission, increments the recorded step count.
After the step ceiling, further work actions refuse and remaining admitted model
turns request final submission. The final return is allowed without another work
action. The turn or wall ceiling ends the loop with a stop receipt. A cost-capped
sender requires an explicit `max_cost_per_turn_usd` reservation; an unpriced sender
refuses before dispatch. Reservations must fit the remaining cost ceiling. Unknown
reported cost or a reservation overrun stops further work. The sender must enforce
its per-call cap; software cannot reconstruct missing provider billing evidence.

Model effects live at `.../turn:<n>/model` and broker effects at
`.../turn:<n>/tool`. The merged effect ledger commits each outcome before the
framework checkpoint. A checkpoint gap reuses the committed outcome; a started
effect without an outcome requires reconciliation. Turn receipts keep wire request
and response digests, raw provider usage, HTTP status and parsed public messages.
Action and stop receipts have immutable outcome pins because ledger reuse metadata
may change. Resume revalidates ledger outcomes and checkpoint references, including
completed checkpoints. Shared `langchain_guard` checks tracing, callback classes,
debug, verbose, host and request identities around calls in a fresh Context.
Framework retries, fallbacks, batches and stream-as-retry are refused.

The focused synthetic suites are `tests/unit/test_ravel_loop.py` and
`tests/unit/test_ravel_chat_model.py`. Passing these controls establishes software
behavior; live transport, billing, OS isolation and scientific qualification remain
separate evidence.

## Fresh ordinary approval in the open-question coordinator

The coordinator validates the complete current unapproved plan before requesting CHECK-IN 1 for a newly prepared study. Only genuinely absent approval selects that request or the existing authenticated delegated plan-approval route. An existing receipt, including a broken symlink, is not replaced. After the request or an ordinary retry, the original approval verifier must still accept the actual current receipt before scientific dispatch. A checkpoint, resume payload, scripted assent and physicist review have distinct meanings; no retry supplies compute authority. Changed or missing scientific inputs refuse before a new approval request.


## Fresh checks of an executed method

The coordinator catalogue exposes `replication-prepare`, `replication-design` and
`replication-comparison`. They use `fresh_replication.prepare_replication_request`,
`design_prepared` and `prepare_comparison` with the existing campaign, ordinary
science worker, independent role journals and numerical comparison. Preparation
writes a pinned prospective request and leaves the research head unchanged; the
separate design action admits the exact issued experiment under the original
protocol and resource budget. CHECK-IN 1, worker admission and scientific review
remain subsequent ordinary actions.

```python
from ravel.workflow import fresh_replication
prepared = fresh_replication.prepare_replication_request(
    campaign_directory, current_integrity_request_pin, method_id,
    fresh_request_directory, check_contract_pin=source_check_contract_pin,
)
fresh_replication.design_prepared(
    campaign_directory, prepared["request"], experiment_id=fresh_experiment_id,
)
# Existing prepare_experiment, approval, admitted run, observe and actual roles
# operate on that fresh experiment. Then prepare its ordinary comparison:
comparison = fresh_replication.prepare_comparison(
    campaign_directory, prepared["request"], fresh_comparison_directory,
)
```

The current integrity request binds the actual complete quantitative report,
original campaign context and every selected method operation's current stage
receipt. The check contract declares `faithful_reexecution`,
`independent_reference` or `objection_test`; all original operations and ordered
cells; exact original/prospective state and representation locations; a pinned
fixed-rule tolerance/error law; source-declared reference quality and point
population; prospective one-attempt studies, comparison template, costs and
review scope. A faithful replay preserves the complete original study and inputs,
not only a matching central value. Different bounds, auxiliary laws, grouping,
interpolation or normalization require a separately stated source-supported test.

An original population location descends the actual original study/result
custody. Its complete entry IDs fix the comparison denominator. Failed reruns,
missing results, unaccepted roles, unavailable references and unknown error laws
remain explicit unknown operands. The worker reconstructs fresh values from the
exact current run, attempt, result and scoped review; an old receipt or a caller
repinning edited outcome JSON cannot become fresh verification. Duplicate point
payloads and labels do not supply statistical independence. Supplied deterministic
or interval laws retain their stated applicability; no coverage or physics proof
is inferred.

Ordinary `research_protocol.prepare_host_request(..., operation="replication",
presentation="indexed")` and `operation="replication-comparison"` expose the same
preparations as charged Host tools. One authenticated inventory retains complete
operational custody while keeping the existing 128 Graph-input and scientific
operand bounds. The inventory says `content_read_by_reviewer=false`; source hashes
are custody, not read credit. Scientific comparison still uses the existing
`research-comparison` worker with its complete cell roster and ordinary reviews.
The optional `replication_request` field binds that producer and actual execution
lineage; it grants no authority by itself. Original failures, full parent task and
unknown source/oracle quality survive every preparation and comparison.

The check contract may declare `custody_limits` with `max_files`, `max_bytes`
and `max_metadata_bytes`. These bound one complete original/fresh operational
union, including ending checks. The existing default is 4,096 files, 16 GiB
and 2,000,000 bytes per metadata document; the supported explicit ceilings are
20,000 files, 16 GiB and 16 MiB. A larger source census requires an explicit
compatible policy and remains held if it exceeds that policy. These limits
change neither scientific text/presentation allowances nor approval. Failed
execution inputs and partial outputs stay in the complete retained census.

A classified original or fresh study gives the new comparison its own complete input-exposure manifest. The producer retains the inherited authenticated tool context, rechecks all original/fresh classifications, and keeps the strictest non-model purpose for identical payloads. New outcome/request/operational bytes are execution-only. The existing binder and exact-study/complete-input/model-presentation guards verify the new manifest; an original-study manifest cannot substitute for it. Intended emitted bytes are committed before binding and rechecked at ending. No source classification, OS blinding, scientific review or execution authority is inferred from comparison preparation.


## Complete quantitative predictive checks

A quantitative experiment uses `observable={schema_version:2, kind:"quantitative", contract:pin3}` and null categorical predictions for **every** declared hypothesis. Its ordinary scientific specification carries `quantitative_check={contract:pin3, resources:pin3}` before plan and approval. Both binding paths are absolute; nested sources resolve at the contract's parent. The supplied contract retains the original goal and experiment, current premises, full coordinate/hypothesis/test population, quantity definitions, dimensions, units, support, normalization, noise and nuisance assumptions, exposure clusters, numerical method and source pins. Records must match those definitions in the exact declared order. Source authentication establishes custody rather than distributional validity.

The public consumer is `ravel.workflow.quantitative_predictive_checks`. Its `guidance` and `inputs` APIs prepare the complete original source and resource census. `evaluate(binding, actual_result_pin, base_dir=..., producer_success=...)` evaluates an actual result; `separation(binding, base_dir=...)` is a prospective comparison without observations. Fixed raw-count Poisson deviance/KL and one predeclared count threshold retain support boundaries and achieved size/power. The scalar upper-tail calculation also reports its model-relative point probability. Full known Gaussian residual covariance retains all cross terms and product units, using coordinate equilibration and Cholesky solves. Unknown noise supports raw differences only. Same-data fits, estimated covariance, Asimov values, adaptive selection and missing calibration retain their distinct unresolved reference-test scopes. No chi-square law is attached to a multibin Poisson deviance.

A cheap prospective calculation can use the existing charged Host tool:

```json
{"action":"quantitative-predictive","parameters":{"request_input":"binding"}}
```

The binding JSON and **all** prediction, law, numerical, objective and allocation sources must be normal authenticated Graph inputs. This route has the declared default resource limits, at most256MiB checking allocation, and a wall allocation within the configured Host timeout. It makes no model call. Larger complete correlated calculations use ordinary `ravel plan`, `ravel approve` and `ravel run` with `mode:"quantitative-predictive"` and `task={schema_version:1,binding:{contract:pin3,resources:pin3}}`; its normal review policy, goal and original execution budget still apply. The full Python installer already supplies the required NumPy1.26.4 and SciPy1.14.1. The numerical contract additionally binds the selected actual module/extension sources; an installed version string alone does not attest them.

`research_cycle.bind_quantitative_selection(root, experiment_id, graph_root=..., node_id=...)` consumes an actual campaign-charged tool result. Alternatively `rundir=...` consumes an already charged, observed successful ordinary quantitative operation under the same goal and binding. The coordinator's `preparation-tool` and `predictive-selection` actions invoke these existing paths. `select` performs no calculation: it uses committed current selection evidence only after ordinary eligibility. A supplied objective may request directed Poisson KL, common-covariance Gaussian distance, or the achieved power of an admitted scalar threshold. Missing objectives, incompatible law/population/objective scopes and unknown metrics retain the categorical/cost ordering. KL, distance, zero cost and a model's preference supply no universal utility or calibrated information gain.

The resource JSON is `quantitative_resource_allocation/v1`, with `limits`, `wall_seconds` and `max_rss_mib`. `default_resources()` declares defaults of64 coordinates,256 sources,8MiB per source,64MiB unique source bytes,4×64² matrix elements,64³×16 work units,16 hypothesis pairs and16 finite states; these are configurable resource defaults, not physics-schema ceilings. A raised contract limit cannot raise its effective allocation. Ordinary prospective approval may admit a larger full population within the original campaign and process budget. Oversized populations remain intact with a `pending_resources` obligation; cells and correlated blocks are never truncated or split as independent.

The worker emits complete `quantitative-check.json`/`.md` companions for an attached check; a prospective ordinary operation emits its complete `result.json` and `<output>/quantitative-report.md`. Original result/source/intended-output commitments are checked again at common publication. `observe`, feedback, protocol status and progress preserve these diagnostics and every failure or unissued member. Quantitative delivery is evidence for critique, additional evidence requests and premise/candidate revision. Independent judgment, applicability, whole-goal completion and publication gates remain unchanged. No new native simulation or statistical fit is implied by this source implementation.


## Scientific actions and context identifiers

Initial routing and recovery suggestions use the scientific action rather than a benchmark name. An explicit opaque `Benchmark label:`, `Suite name:` or corresponding task/source/context/provenance ID row can annotate a request without selecting a method. The full original prompt and evidence remain in the contract and actual Host context. Arbitrary colon prefixes and scientific conditions are retained. A claimed identifier containing a scientific action, unit, constraint or ambiguous content remains unresolved until a grounded Host interpretation binds the whole original request. Renaming context does not authorize execution or acceptance.

Ordinary `ravel initiate` and refreshed status expose the source-bound whole-goal handoff for applicable scientific parents. `research-orchestrate prepare` consumes that exact original contract and assignment with caller-declared runtime, evidence purposes, review policy and finite campaign ceilings. Preparation creates no approval, model call, native attempt or scientific result. Existing reproduction figures and analysis gates remain required; coordinator access supplies no exemption.


Scientific approximation, level/only, protection, representation and precision qualifiers inside a claimed identifier row remain visible and unresolved for grounded interpretation. They are never erased as metadata. A source-bound resolved particle/truth/generator-level or no-detector reproduction retains that approximation and the full task. Explicit requested surveys keep their survey operation when their subject concerns constraints; using existing survey results to constrain a model remains a distinct interpretation request. Neither gives compute authority.

### Computed research boundaries

The [research protocol contract](research-protocols.md#confirmation-register-and-mandatory-protocols)
defines mandatory P01–P17 binding, prospective selection and confirmation,
receipt-computed stops, the hypothesis register, operator yields and allocation.
Use `research_protocol.commit_selection` before confirmation and the evaluator's
`reserve_confirmation` seam before opening withheld results. Claims retain N,
selection receipts and selected confirmation results, including a null funnel.
Screen launch requires the exact R1 receipt recorded by `authorize_screen`.
`bind_allocation` binds current queue recommendations after protecting validation
and confirmation. These functions grant no execution or scientific authority.

## Governed worker dispatch

Code-authored `agent` and `map` nodes use `ravel.workflow.agent_worker`; their
`parameters` contain only `rundir` and the versioned worker `spec`. Transport
launch descriptors come from a trusted adapter, never artifact or board prose.
`ravel work dispatch --rundir RUN --spec SPEC.json` materializes pinned inputs and
starts a durable supervisor. `ravel work status --rundir RUN` verifies receipt and
output bytes. Synchronous dispatch and launch, including receipt reuse, wait for
terminal process custody, verified child-group disappearance and supervisor-group
exit. Receipt publication alone does not signal cleanup. Cleanup has a 15-second
wait bound after receipt observation; an unverified cleanup or an expired launch
observation deadline raises `TimeoutError` with reattachment/reconciliation guidance,
preserving custody and preventing a second launch. `wait=False` remains asynchronous.
For an asynchronous worker, use the product process registry's `child_pgid` to
observe child registration; a child-authored file can precede that publication.
`ravel work stop --rundir RUN` contacts registered supervisors and
waits up to ten seconds for their process groups as well as their children;
unverified disappearance returns `verified_gone=False`. Kernel `stop --now`
also checks worker groups whose public registry entry already says exited,
because terminal child custody can precede supervisor shutdown. An ambiguous worker requires
`ravel work reconcile --rundir RUN --node NODE --attempt N --evidence PIN.json
--reason REASON`; the evidence file contains a run-relative path and its SHA256.

The worker refuses execution if the OS confinement probe cannot confirm denied
run/custody reads, denied writes outside outputs and scratch, and denied IP
networking. The transport adapter must provide `prepare_launch(rundir, spec,
workspace)` before live CLI dispatch is available. Model-loop and MCP consumers
use the same `Broker.call` / `socket_call` implementation through the
`ravel.workflow.tool_broker` seam. Trusted action providers register handlers with
`Broker.register`; protected-path providers add guards before handler invocation.
Native handlers require an admitted lease callback. A busy lease is a receipted
hold; it grants no native launch.

Worker knowledge calls use registered `knowledge.<op>` actions, or
`knowledge query` with `{"op": "show", "args": {"id": "doc:synthetic"}}`.
The role's existing allowlist must grant the action. The supervisor constructs
`knowledge_broker.create(rundir, workspace, role=role_id, **broker_options)`;
it retains broker dispatch, budgets, replay and receipt custody. The result is
a pinned JSON output with a run ID, node, attempt, role and source-policy hash.
The receipt's derivation is `retrieval`. Worker arguments cannot choose an
atlas file, a different run, an external plan file or a lower retrieval floor.
Use inline `plan_check` objects. Unbound terminal queries retain their existing
behavior; this provider does not install an MCP server.

`inputs/task_contract.json` (or the root `task_contract.json`) supplies
`forbidden_sources`. Conflicting copies and malformed policies refuse access.
`source_policy.matches(rows, source)` consumes source paths, quantities,
classes and identifiers. Input-root globs use POSIX components: `*` stays in
one component and `**` spans zero or more components. A scoped extraction ban
withholds matching quantities while retaining definitions with other declared
quantities from the same source. Source/quantity metadata must accompany the
supplied pin; retrieval does not infer quantity identities from file contents.
The whole canonical row, including paths, scope, origin and evidence, enters
`source_policy.digest(rows)`. Supervisor descriptor path bans still apply.

Before copying supplied files, worker materialization calls
`knowledge_broker.filter_inputs(rundir, workspace, spec)`. It tests both the
original source pin and the destination alias and retains the alias metadata
in supervisor custody. A later copy under that alias cannot grant broker read
access. Path globs also match case-folded names, and a pin whose content digest
equals a glob-withheld run file is withheld under any other name, including a
copy, a hard link or a live-workspace path. Bundle providers call `SourceBoundBroker.filter_sources(items,
surface="bundle")` before opening members; inventories use
`surface="inventory"`. The returned first list is the permitted membership,
and the second contains content-free omission records with refusal receipts.
This filtering seam is available to bundle builders; it does not create a
bundle builder. Filtering must run in the trusted dispatcher before worker
execution, since its source-check action is temporarily granted for receipting.

Direct requests for withheld knowledge and blocked reads return
`forbidden_source`, naming the policy and violated-row hashes. Broader retrieval
answers omit withheld content and carry a content-free `withheld` census in
their pinned receipt output. Filtering precedes ranking and limits. Reviewer,
critic and verifier roles receive no lessons. Bound queries append IDs,
digests and refusals to `<rundir>/knowledge/served.jsonl` and a supervisor custody ledger;
replayed calls reuse the original receipt without a second served entry.
Changed source restrictions require rebinding. Output hashes and byte bounds
are recomputed after binding and filtering. These are software restrictions,
not qualification of a retrieved scientific result.

Live workspaces sit outside the run tree, under `$RAVEL_WORK_ROOT/<run digest>/<node>/<attempt>`
(default: `work/` under `RAVEL_STATE_DIR`). Pins keep the logical path
`agent-work/<node>/<attempt>/...`, which resolves to the live workspace. When a
receipt is written, its receipt, transcript, final record, outputs, scratch and
broker receipts are copied into the run's `agent-work/` for run readers. Every
reader of a durable receipt verifies that projection and rewrites absent or torn
files, so a crash during publication is repaired before a receipt is returned.
A worker is voided only when one of its declared protected inputs changes: its
input pins, work order and role packet, hashed at their sources. Ledger,
supervisor, graph-root and unrelated run writes do not void it.
The broker opens every path from the workspace descriptor without following
symlinks and matches forbidden sources against the normalized path. Its repeat
detector digests `outputs/` only, walked by descriptor; scratch writes are not a
state change. A broker call whose custody receipt landed before its state pin
adopts that receipt on replay. Declared sandbox read roots may only narrow the
tool runtime paths. The macOS profile grants metadata reads only on ancestor
directory entries and the readable roots. The denial probe reads, and must be
refused, the worker's custody record and ledgers, the state store, the run tree,
a peer workspace and each protected graph root's state, checkpoints, call
receipts and effect store. Descriptor `pass_env_names` reach the supervisor and
child; their values are never recorded, and `user_configuration_loaded` is
computed from the read roots and passed names.

Critic, verifier, RDJ critic and RDJ verifier worker roles are blind. A blind
worker node needs a role packet whose role matches its worker role card, and no
raw inputs or work order. The dispatcher copies the verified packet (manifest and
indexed artifacts) into `inputs/packet/`; nothing else of the producer reaches the
workspace, and the blind worker's broker allowlist is `read` and `write`.

`agent` and `map` nodes and every `Control.call` delegate to
`effect_ledger.delegate` under `<graph root>/effects`. External delivery,
reconciliation, release and worker recovery close the ledger effect before the
call receipt and graph state record the outcome. A host call that raises after
dispatch began, including a failed receipt, ledger-outcome or checkpoint write,
stays ambiguous and needs explicit reconciliation. Only an exception with
`not_dispatched` (`effect_ledger.NotDispatched`) or an
`agent_graph.ReceiptedFailure` carrying a durable failure receipt closes the call
as failed, and the graph then retries under a new attempt. A failed
reconciliation cannot close an effect the ledger records as completed. A worker
reservation that was never dispatched refunds its node attempt and call.

Agent-node worker receipts carry the ledger effect's `identity_sha256` and
cancellation `epoch`; the supervisor writes a downstream document under
`<graph root>/effects/downstream/worker/`, and the registered `worker_receipt`
validator closes a crashed effect from the custody receipt without a second
dispatch. `graph_nodes.agent` builds the same worker effect for substrate graphs.
`execute` holds the substrate scope runner on `<graph root>/effects`: a second
runner is refused, the runner epoch is stamped into each reservation, and
`ravel graph stop --scope-root <graph root>/effects` drains dispatch until a run
with `clear_stop=True`. `ravel graph stop --now` on the run terminates the
supervisor group and the child group registered as `child_pid`/`child_pgid`; the
supervisor handles SIGTERM by stopping its child and writing an ambiguous
receipt. `tests/unit/test_worker_pair_suite.py` runs the legacy agent-graph and
worker substrate tests together, runs the worker, broker and sandbox tests,
names the adversarial tests the merge depends on, and fails on any skip other than
`sandbox-blocked` on a host without a sandbox launcher.

Worker receipts carry computed `outcome`, `recovery`, `graph`, `framework_step`
and `rdj` fields. Required outputs and work-order self-check receipts determine
completion; findings do not assign labels. Missing outputs on a completion claim
are counted per worker and model cell. Final records use a code-owned schema:
`producer.v1` is a JSON object with a boolean `completed`; `reviewer.v1` adds a
`disposition` (`supported`, `not_supported`, `request_evidence` or `inconclusive`)
and `findings` with non-empty `summary` strings. An undeclared schema is refused
before materialization. A map declares an `all` or `quorum:n` join, optional
`max_item_attempts` (default 3) and `workers` (default 1, at most 16); any
ambiguous member keeps the join ambiguous. Output credit
is confined to declared regular files under `outputs/`. Transcript rows use the
agent-audit record shape; their receipt link hashes the receipt projection without
its transcript member, avoiding a circular file hash. A transport adapter must
supply actual prompt-turn audit evidence before transcript completeness can be
claimed; the core records the dispatch request and discloses unreported usage.

The hypothesis board binds the initial phase with `agent_worker.bind_season` before launch.
Sealed peer reads are denied even when participant attestation is unavailable;
independence labels require distinct sessions from custody-registered transport
receipts with confirmed isolation. Board actors come from the trusted binding.
Artifact and post bytes remain data. Run the bounded software control with
`python -m ravel.validation.check_authority_boundary`; it covers broker admission
and receipt projection. Downstream gates and work-order producers must separately
verify their typed inputs. These software controls grant no scientific approval.
