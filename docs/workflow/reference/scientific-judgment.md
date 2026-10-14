# Ordinary scientific judgment and return to work

CHECK-IN 2 uses the existing physics-review journal. `ravel judgment` connects it
to bounded AgentGraph/Host role calls; it does not introduce another vote, state
engine, approval, scientific runner or retry policy. The science status packet
points here when raw computation awaits review or actually failed.

For successful ordinary science work, supply the actual located check document:

```sh
ravel judgment open --rundir RUN --checks inputs/checks.json
ravel judgment advance --rundir RUN --out NEW_ROLE_DIRECTORY \
  --host-config responses-host.json --model MODEL --reasoning-effort high \
  --max-output-tokens 4096 --max-wall-seconds 120 --claim-scope DECLARED_SCOPE
```

The caller explicitly invokes model dispatch. `advance` creates and consumes at
most three separate one-attempt role graphs, critic then verifier then decider.
Standalone token/wall bounds apply per graph (at most three times those ceilings);
model calls are separate from the approved native-study budget. For an attached
research campaign, pass `--campaign CAMPAIGN --experiment OBSERVED_ID` to
`prepare-role` or `advance`. The immutable role request binds that exact observed
run. Prepared ordinary and failed-diagnostic Graphs also retain that campaign's
original parent-task assignment, when present; no child review completes the
whole parent. Dispatch uses existing `research_cycle.execute_graph(..., prepared=True)`:
its original cumulative calls/tokens/wall reservation and campaign clock include
every role and repeat correction, and stay spent on failure. Consumption refuses
a campaign-bound role run outside that ledger. No resources reset with new roles.
A configured provider
failure leaves review pending, with the original graph failure/cost retained.
No scientific worker or approval is launched. For advisory, nonvoting relay responses, use `prepare-role --external`, existing `agent-graph prepare-external` /
`deliver-external`, then `judgment consume --binding NEW_ROLE_DIRECTORY/binding.json`.
Relay results cannot supply independent votes; use the verified launcher or observed HTTP host
for voting roles. Transport records disclose actual observed versus self-attested execution;
actor declarations are not authentication, and model agreement is not physics.

Each role receives indexed copies of actual data, units, conventions and declared
assumptions. Critic/verifier packets withhold producer headline and other verdicts.
The intervention envelope retains permitted paths/stages/checks, not approval
narrative. Improver/synthesizer receive complete actual public critique outputs,
including the finite assertion audit, rather than only hash references.

Ordinary review automatically prepares an initially unresolved public decision
case for the requested action and its prospectively required checks. Reviewers
freshly assess all its exact claims, material assumptions and support edges.
For a specific contested, novel, high-consequence or unsupported inference,
`prepare-role --case CASE.json` uses the existing bounded decision-case schema;
it withholds all copied support labels and presents exact bound anchors. The
response's case digest, complete node/edge coverage and newly assigned reviewer
must match the current case. Changed claims, links, anchors, model outputs or
source invalidate the dependent judgment. Structural checks do not prove
entailment. Unresolved material action support prevents acceptance and produces
located findings or a stop. The case root must be the requested action: an
unresolved mechanism may motivate an adequately grounded bounded experiment.
Do not require a speculative mechanism to be true before testing it.

A send-back returns a concrete physical objection to an improver. Prepare that
role with a distinct actor and no acceptance scope. Its closed output names
original mutable paths, exact replacement text, affected original stages/checks,
held conditions and a necessary prospective check for each located objection.
`method: direct_verification` binds an indexed independently grounded input/reference
with a located expected value and no invented rivals. `method: discriminating_experiment`
requires at least two genuinely different prospective outcomes. Same/unknown predictions remain useful exploration or replication;
they cannot be labeled an established discriminating contrast. No proposal is an
acceptance vote. The explicit caller prepares only the allowed settings:

```sh
ravel judgment apply-proposal --rundir RUN --binding IMPROVER/binding.json
ravel judgment prepare-role --rundir RUN --out NEW_SKEPTIC --role verifier \
  --actor DECLARED_VERIFIER --proposal-binding IMPROVER/binding.json \
  --model MODEL --reasoning-effort high --max-output-tokens 4096 --max-wall-seconds 120
```

Run/consume the prepared graph through the same ordinary Host, then prepare a
synthesizer with `--proposal-binding NEW_SKEPTIC/binding.json`. A skeptic reviews
**prepared design adequacy**, not executed repair closure. Only its
`adequate_for_bounded_test` response can reach a fresh decider design review.
`judgment admit-repair --binding DECIDER/binding.json` calls existing
`science.correct` or `physics_review.authorize_correction` with the original
actor, exact prepared bytes, stages, checks and redo envelope. Unresolved or
contradicted proposal evidence grants nothing. The returned phase is
`return_to_work`: use the ordinary already admitted worker route, then reopen
with its fresh successful receipt/checks and correction ID. All inherited
findings require actual pass rechecks and explicit closure by three fresh roles.
A failed correction remains failed and spent. No result or old vote is rewritten.

If a physical change exceeds the original repair envelope or redos are exhausted,
use `judgment research-feedback --rundir RUN --campaign CAMPAIGN --experiment ID`.
It connects that same observed study's actual review to existing
`research_cycle.adjudicate` / `feedback_packet`; the existing bounded
`bound_revision` / `adopt_revision` and complete prospective study APIs provide
a separately admitted experiment. This route retains original evidence, rival
hypotheses, unresolved obligations, premise freshness and resources. It does not
turn a repair recommendation into an executed experiment or approval.

For an actually FAILED stage, use canonical `failed-review intake`, then
`judgment prepare-failed-role --intake INTAKE.json --role critic` and separately
`--role verifier`, with the original source-bound actors and explicit model
bounds. Supply `--campaign CAMPAIGN --experiment OBSERVED_ID` during failed-role
preparation to retain the original parent assignment. Standalone callers execute their existing graphs. For an attached campaign,
execute each pristine graph through `research_cycle.execute_graph` with
`prepared=True` before consuming feedback; its full original role ceiling is
charged even on dispatch failure. The campaign-attached `failed_feedback` callable
requires both exact retained graph reservations and observed usage before it
attaches canonical diagnosis, without a second native debit. CLI `failed-feedback`
exposes the same `--campaign CAMPAIGN --experiment ID --out NEW_FEEDBACK.json`
join; the new feedback file must be outside immutable failed-run history.
`judgment failed-feedback --intake ...
--critic-binding ... --verifier-binding ...` recomputes canonical diagnostic
feedback. Its callable optional campaign attachment joins the already observed,
charged experiment without a second attempt/debit. Infrastructure failure,
scientific unresolved and a successful negative hypothesis remain distinct;
FAILED partial outputs never obtain ordinary acceptance, delivery or reuse.
Fresh mechanisms go through existing feedback and new-study admission.

The Host `scientific-judgment` tool takes a pinned `request_input` with closed
`operation`, `rundir`, `arguments`. It supports status/open/prepare-role/consume/
apply-proposal/admit-repair, only from a separate proposer/designer/executor
caller, never the reviewing role itself. Referenced request/case/binding bytes
must be explicit inputs. It prepares graphs rather than nesting model/native
execution. Normal CLI/Graph dispatch supplies the configured model transport.

Manual declared-actor review remains supported. New connected review and
correction events optionally bind exact model/case/context/call/source artifacts.
Ordinary current delivery/reuse/correction and launch snapshots recheck them;
changes block current authority without modifying immutable historical decisions.
Only current-cycle commitments matter, so an admitted repair can progress and
fresh successor judgments replace applicability rather than erase old history.

Implementation controls establish software transitions and custody. Actual
scientific review quality, independence, physical validity and effectiveness
remain separate empirical questions; they are not prerequisites for completing
this ordinary executable source path.

`advance --improver-actor DISTINCT_ACTOR` also follows a result send-back to one
actual nonvoting improvement call and returns its exact binding and physical
proposal/request. It does not apply the replacement. After explicit preparation,
`advance --proposal-binding IMPROVER/binding.json` drives the separate skeptical
and decider design calls and returns `admit_prepared_correction` or the retained
unresolved design evidence. Admission is still the explicit `admit-repair` call.
An improver may return `scientific_evidence_request` with a concrete request and
no proposal when a useful test requires a new scope. Old findings stay open.

Connected requests parse the exact bounded authenticated byte buffer, never a
second pathname read. Transient changed/restored input cannot alter the operation
or case that the caller actually pinned.
# Full-scale failed-stage contexts

Failed-role preparation automatically supplies a bounded material view backed by the complete immutable intake when its custody census exceeds the initial context bound. See [failed-stage evidence presentation](failed-stage-review.md) for exact page IDs, authenticated reads and `--evidence-pages` fresh-context continuation. Initial task/source/assumptions, actual failure and all missing obligations remain visible. A one-call role has no automatic evidence tools; the coordinator chooses further pages and prepares a fresh bounded Graph under the existing campaign accounting. This is diagnostic presentation, never acceptance or automatic redo.


## Retained successful-study review

`prepare-role --retained-study` explicitly continues **review only** for one
immutable initial schema-2 study with one successful authorized attempt and a
pending initial cycle. The old framework must remain complete and byte-identical;
its original plan, approval, stage receipt, runtime capsule, input/output/log
populations, journal and sole launch are replayed from their commitments. The old
package is never imported. The new role request separately pins the current
review machinery. This flag cannot launch, reopen or correct work, widen the
policy, overwrite a decided role, bless changed inputs or requalify old runtime.
It is not available for improver/campaign/repair-design calls.

A caller may supply an exact `--case CASE.json` with bounded authenticated stage
extracts and fresh custody observations as located anchors. Keep the full source
record and catalogue: a snapshot commitment is distinct from a fresh SHA pass,
ending identities and continuous historical tool consumption. Additional pages
can be supplied as newly bound anchors in another explicitly charged role. Never
rewrite an old model response or declare a continuing actor fresh.

Each role's `supporting_artifacts` can contain one closed `role_context` descriptor
binding the raw manifest SHA, canonical manifest digest and exact original cycle
ID/digest. It authenticates every indexed copy and complete membership in the
same final observation. The 512 outer-support ceiling remains unchanged; context
limits remain 10,000 members, 16 MiB manifest, 64 MiB/file and 256 MiB total.
Legitimate zero-byte copies pass only when they are exact current-cycle SOURCE
inputs captured at size zero under the original policy. Role/control documents
must still be nonempty. Large or binary evidence remains committed and explicitly
omitted from the bounded initial presentation, with existing indexed/page access.
The model is not claimed to have read every committed byte.

A result role may return `scientific_evidence_request` with null verdict/scope/
proposal/proposal verdict, no findings/closes, a complete unresolved public audit
and a located request in `summary`. Consumption verifies it but appends no vote:
the same cycle remains pending and the actual call stays spent. Use a separately
allocated fresh role context to present requested retained evidence. For
`scientific_review`, only accept names a permitted scope or closes findings;
send_back/stop require scope null and closes empty. Send-back findings retain a
nonempty original allowed recomputation stage list; evidence-only requests do
not invent a native redo.

Public flat role records remain unchanged for command/external transport.
Responses Structured Outputs requires an object root without anyOf, so the Host
places the conditional schema under the single `public_record` property and
unwraps exactly that field before applying the same public validator. Missing or
extra wrappers and invalid decisions still refuse; nonconditional schemas keep
their original transport shape. No provider compatibility is inferred from pure
inert request/parser controls.


### Transport acceptance

Before accepting a critic, verifier or synthesizer vote, recompute the receipt's attestation.
Every relay response is `self_attested`, even with a schema-3 declaration digest; it is advisory
and cannot supply independent judgment. Use a verified launcher receipt or observed HTTP transport
for independent roles. `transport_attested_cli` remains an observation with a verified label.
Explicit `allow_control` software controls and nonvoting context requests retain their existing
behavior. See [transport receipts and executable binding](../../reference/transports.md).
Role requests may carry `role_requires.tools` (default `none`); the session receipt records and
checks that policy against effective tools. Role cards do not yet supply this policy automatically.
## Mandatory review points for epoch-two contracts

Contracts with `agent_layer_epoch: 2` use `review_points.derive(facts)` to compute
review obligations from plan operations, claim lineage and authored artifacts.
The intake seam is `_facts(rundir)`, which reads `inputs/task_contract.json` and
its pinned request plan. A declared claim kind cannot remove a computed-basis
obligation. Existing legacy contracts retain their decisions only under the
epoch/snapshot rules below, except that `unblind` and `spend_above_ceiling` have no older decision and refuse.

Inspect remaining work with `ravel review pending --rundir RUN --json`.
The stable result includes `parallel_group`, `depends_on`, `ready` and the exact
missing role counts. Completed roles are omitted on resume. The first-pass
critic and specialists share a group; the verifier waits for the complete group,
and the decider waits for the critic and verifier. The `review.points` graph owns actual
worker dispatch: `ravel review run --rundir RUN --at checkin2:C1` (`dispatch` is the same
command) runs the points at one `when.at`. Each round re-derives `pending`, so a rerun
or a new `--attempt` dispatches only the missing role counts. Dependent reviewers receive
the findings of the points they wait on, never a verdict. An A finding stops at
`rca.ticket`, which is recorded as skipped until it is registered. With a human approver
the graph pauses for `checkin2_response`; answer with `--respond FILE`. The gate after it
refuses unless the response pins this run's `science.approve` record. Epoch-two runs of
`research-orchestrate` delegate their review here.

`decision_gate.check(rundir, gate, action)` only reads evidence. It neither writes
receipts nor starts processes. Errors include `pins`, the missing evidence IDs.
The packaged provider registry declares mandatory providers by gate and scope;
a missing mandatory provider returns `provider_inactive`. Consumers must refuse
before mutation when this list is nonempty. Approval must retain the derived
points in its policy; gate checks rederive them from current pinned inputs.
The gate APIs are available independently of lifecycle call-site integration.

`review deliver --rundir RUN --request REVIEW.json` inspects a proposed delivery.
An `accept` without required worker receipts is refused. An explicitly declared
human approver with an approval ID is disclosed as `human_manual`; this label
neither authorizes execution nor replaces the ordinary recorded human approval.
The legacy `review` subcommand retains its original interface, with the epoch-two
receipt check before a direct accept. A relay is `self_attested`;
`transport_attested_cli` is accepted only as the execution observation supplied
by the verified transport adapter. Local records do not independently authenticate
people, providers or scientific truth.

Agent fan-outs must declare workers with disjoint relative `write_set` paths,
pinned inputs and separate receipt IDs. The join must be `computed_comparison`
or `reviewed_selection` with a receipt ID. A `single_worker` arm or estimate must
have the same `budget_cap`. Concatenation, model-written merges, overlapping paths
and unpinned input sets refuse. Native partition plans remain backend operations.
The dispatcher must recheck `parallel_safety(node)` against actual workspace paths
and pin bytes before starting workers.

Tuning parameters to observed-data agreement produces a calibration point.
CHECK-IN 2 requires an R2-or-higher RDJ authorization, whose authenticated case
has `decision_point.tuning.class: calibration`, and declared `non_overlap` or
`added_uncertainty`. `checkin3_section(rundir)` lists these choices for CHECK-IN 3.
An observed-statistic node additionally needs an R3 unblind receipt with human
approval before launch; the `unblind` gate requires one even when no plan node
declares an observed statistic. RDJ authorizes exact action digests; loose receipt JSON
never substitutes for its custody and journal validation.

Acceptance and integrity actions supply `outputs`, each with a byte-bound
`artifact {path, sha256}` and `requirement_ids`. Every original requirement must
map to an output and retain valid prompt spans. Open criticism holds a gate only
when its receipt, failed code check, or pending typed request resolves against
current evidence. An unsupported opinion is not a blocking finding.

`run_ceilings.checkin_section(rundir)` supplies the CHECK-IN 1 section. The
`inputs/agent_ceilings.json` record defaults to six workers, 72 invocations for
analysis or 120 for research, three investigations, producer/reviewer wall limits
of 2700/1200 seconds, and one native job. Every selected API-billed transport needs
a USD cap. The check-in owner must display and fingerprint this record. Dispatch
calls `charge(rundir, kind, n)` before starting workers, HTTP calls, map items or
RDJ roles; charges append under a file lock. Concurrency and wall limits remain
dispatcher obligations. Changed ceilings require a new CHECK-IN 1 response.

The hookless provider checks generation-like files across the run against the
existing authorization journal and retained approval fingerprints. Exact files
and confined output-directory descendants are accepted. Unchanged external input
snapshots are excluded; ROOT classification uses stage-producer provenance.
Missing authorization records remain refusals.

### Review points (§5): epoch, custody and approved obligations

`review_points._facts` is the single epoch reader. The contract must exist and
parse as an object. A present epoch is exactly integer `1` or `2` (neither strings
nor booleans). A custody `run_init` snapshot binds the contract bytes, including
its epoch: deleting the key or replacing the contract refuses with
`gate_inputs_invalid`. Only an existing legacy contract with absent/integer-one
epoch and no conflicting snapshot retains its pre-release decision. RDJ is not
consulted for legacy runs; `unblind` and `spend_above_ceiling` still refuse there.
Release intake writes portable reading and request-plan pins, then stamps integer two.
If no draft plan can be produced, intake refuses before creating a run; it cannot
silently create a legacy run. Scoped planning projects the pinned plan, claims, coverage and
ambiguities into CHECK-IN 1. Mandatory release validation and the
`run_init` snapshot producer belong to the lifecycle wiring. Epoch two requires a confined, byte-pinned
`request_plan`; an unpinned `inputs/plan.json` is not a fallback.

`review_points.approve(rundir)` retains `derived_points_sha256` and each subject
digest in `inputs/review_points_approval.json`. The ordinary CHECK-IN 1 approval
writer calls it before fingerprinting; its delegated variant does too. The policy
and ceilings record enter that fingerprint. Other approval/transition owners must
call the same seam before sealing their own approval. Gates rederive obligations
and refuse `obligations_changed` after adding/removing a calibration row or its
separation declaration. If a pin fails first, refusal-only diagnostics also name
changed subjects/obligations; they never credit unpinned evidence.

Worker receipts count only when custody registers their exact relative path and
current SHA-256. The worker dispatcher owns registration and the verified label. Receipts are
versioned by `schema_version`. Version 1 is the original field set and stays valid, byte for
byte, for its original use. It earns no review credit; the advisory is
`receipt_predates_review_subject`. A review dispatch carries `parent.review_subject`, so the
dispatcher writes version 2: version 1 plus `review_subject` (`scope` and `sha256`), bound by
the transcript's receipt digest. The dispatcher registers each version-2 receipt with the label
the transport's own verification produced. Credit needs a confined `final_record.path` with
matching bytes and a `review_subject` equal to `review_points.review_subject(facts, point)`:
the scope (`claim:<id>`, `node:<id>` or `plan`) and `subject_digest(facts, point)`, the
canonical JSON of the point ID and current claim, plan node, or whole-plan subject. Reusing a
point ID does not preserve a review after its subject changes. `pending()` reports
unregistered/invalid/stale receipts as advisory; unregistered ones carry `receipt_unregistered`.

Labels are `transport_attested`, `host_attested`, `self_attested`, `human_manual`.
`transport_attested_cli` is an execution mode, never a label. Label calculation
uses `decision_case.label_for` capped at the custody registration's verified
strength, as in RDJ. A version-2 dispatcher receipt has no execution mode and takes
the registration's verified label. Without a verified registration every mode is self-attested.
Receipt-body `execution_mode` and `attestation` cannot increase authority.
`human_manual` worker bodies remain self-attested until a system-owned human
provenance producer binds the actual human review to its point and receipt. Voting, specialist and producer counts
exclude every self-attested receipt, including in human-led runs. The pending
projection and `checkin3_section.review_receipts` include `independent: false`;
a disclosure returned by `review deliver` is not independent review evidence.
Relays and `control_only` voting observations remain inadmissible to scientific
judgment even with `allow_control=True`. That switch permits nonvoting diagnostic,
context and evidence work only; it cannot append an ordinary acceptance vote.
Ordinary science-v2 opening/status validates the science route before attempting
a generic task-contract read.

Findings use RDJ's `materiality`, `evidence_class`, `evidence_locators` vocabulary.
Legacy `severity/new_receipt/code_check/evidence_request` records are adapted.
A `new_receipt` needs a current custody-registered stage from a recognized
producer; a `code_check` needs `rdj_loop.critic_basis == "verified"`; a pending
request remains blocking until `rdj_loop.evidence_request_answered` verifies its
item as done with externally verified resolution pins. A missing, deleted,
withdrawn or merely edited queue item cannot clear a registered finding. RDJ and
review points share this resolution rule. A file path posing as a code check,
ghost new receipt, self-declared failure or opinion is advisory. Role cards are resolved by
`role_registry.load(role_id)` from the role registry, including its aliases and registry defaults.
Only blocking points demand dispatchable role cards; advisory roles are exposed
as `review_transport_advisory`, never gate refusals.

### Decision gate (§6): scoped actions and wiring conditions

An action carries the RDJ `kind`, exact `digest` and `pins`, with optional
`node_id`, `claim_id`, `scope`, `floor`, outputs and resource demands. `floor` is
one of R0–R3 and can only raise RDJ's computed class. Review points pass their
class via `floor` and consume exactly `rdj_loop.authorizing_receipt`'s current,
replayed receipt and case. Calibration class and human approver must belong to
that same authorization; an older receipt never supplements a current one.

`node_id` narrows obligations only at `launch` and `failed_stage_feedback`.
At a claim gate an unknown node returns `action_scope_invalid`; a known node
cannot remove calibration or unblind obligations. `checkin2_accept` may name a
`claim_id` to accept that claim without waiting for other claims; omission means
all claims. `delivery`, `final_task` and `export` always recheck every claim and
calibration row, regardless of `claim_id` or `node_id`.

Launching an observed-statistic node requires **two cases**: an authorization for
the `launch` action and a separate R3 `unblind` authorization with a recorded
case-specific human approval. Open that `unblind` case for the launch action
itself: the same kind, pins and digest, not an action of kind `unblind`. The row-17
receipt does not replace the launch receipt. Calibration row 16 requires an R2-or-higher `tuning_change` case whose
tuning class is `calibration`, plus declared non-overlap or added uncertainty.
At actual CHECK-IN 2 acceptance call `review_points.accept_checkin2(rundir, action)`
(or `ravel review accept --rundir <run> --request <exact-action.json>`). It checks
the decision gate and records the action, plan pin, point subjects and accepted
calibration receipt IDs/digests in custody's `review_acceptances` ledger.
Downstream row-16 checks replay that accepted tuning action with its own kind and
digest through `authorizing_receipt`; the delivery action still needs its own RDJ
authorization. Mere gate inspection is read-only and records no acceptance.
Missing acceptance, changed plan/subject or stale authorization refuses delivery.
Every actual acceptance transition must call this seam.

A `checkin1_response` ceiling record is effective only when its current bytes are
in the CHECK-IN 1 approval fingerprint, a vouched custody `checkin1` snapshot
entry, or byte-identical ceiling JSON recorded as `checkin1_response` user text.
Snapshot entries listed in `unvouched` or `ravel_written` never vouch for ceilings.
The response producer records the original received JSON, not an agent's copy.
An unbound response falls back to defaults and reports `ceiling:checkin1_response`.
`spend_above_ceiling` needs a recorded raise of the exhausted invocation limit,
recorded after the ledger reached its old limit; charges retain time and the
then-effective ceiling. Missing temporal evidence refuses. The ceilings provider
passing does not supply the separate R3 RDJ/human authorization.

Raw-launch auditing scans the whole run for event formats, including YODA, LHCO,
STDHEP and HepMC3, excluding unchanged custody-snapshotted external inputs.
Declared output directories cover their confined descendants. ROOT files owned
by nongenerator stages are histogram/container outputs; generator-owned or
unbound ROOT files require approval-bound launches.

R0/R1 wiring still requires the lifecycle snapshot/transition producers, dispatcher
receipt registration, the role registry/cards and the work executor. A missing executor must
report `provider_inactive` with `provider:executor`. Same-user custody is a
software boundary, not OS isolation; host configuration authority remains with
the operator path. R2/R3 CHECK-IN 2 additionally requires the `comparison`
provider whenever derived points require a comparison or certificate. Its
registry row is deliberately inactive, so these runs report `provider_inactive`
until the producer and validator land. This does not add that provider to R0/R1
wiring. `tests/integration/test_decision_control_merged.py` is the shared
acceptance test across transports, RDJ and review points;
its software receipts do not establish scientific validity.
