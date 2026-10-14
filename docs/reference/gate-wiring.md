# Decision-gate wiring record

This record lists each decision gate, its RDJ class from `src/ravel/data/rdj/policy.json`, and
whether RAVEL's ordinary transition calls `decision_gate.check` (**wired**) or still decides on
its earlier path (**legacy**, with the condition that blocks wiring). The implementation is
`src/ravel/workflow/gate_wiring.py`. On an epoch-two contract `decision_gate.check` runs every
active provider registered for the gate, the `rdj` provider included
(`src/ravel/data/gates/providers.json`). On an older contract it runs no provider: it keeps that
contract's earlier decision, and a gate that has no earlier decision refuses. The action-path
table below lists the paths this record covers; a path it does not list is not gated by it.

## Epoch and custody

- The release intake (`ravel initiate`) stamps `agent_layer_epoch: 2`. It then records the original
  prompt as custody user text and takes the `run_init` input snapshot. The snapshot binds the epoch:
  deleting or changing the key afterwards makes every gate report `gate_inputs_invalid`.
- An epoch-two contract without a `run_init` row binds nothing. This happens when intake fails
  between writing the contract and recording it. Every wired check, the CHECK-IN 1 recorder,
  PHYS-RDJ and the P15 launch check refuse such a run with `run_init_missing`. Start a new run.
- A run without a task contract is refused (`gate_inputs_invalid`). Only an existing contract
  without the epoch key keeps its pre-release decision.
- `validate_task_contract` refuses a contract that pins a `reading` or `request_plan` (only the
  release intake writes them) unless it carries `agent_layer_epoch: 2`.
- RAVEL's own rewrites of a contract before CHECK-IN 1 re-record `run_init` for the rewritten
  contract, which must keep epoch two: `ravel initiate --resolve` (intake resolution) and
  `ravel plan` for a scoped run (`scoped.plan`). A rewrite is refused once the `checkin1` snapshot
  exists, and it never records a first `run_init` for a contract custody did not record. A
  contract amended after CHECK-IN 1 is refused by every gate (Phase B: supersede with re-approval).
- `ravel approve --quote <text>` records the operator's quote as the CHECK-IN 1 response
  (`inputs/checkin1-response.txt`, custody user text), then takes the `checkin1` snapshot. The
  snapshot vouches against the latest `run_init` row. A response file that custody did not record
  is refused, whoever wrote it, and the refusal is logged to the state directory's
  `gate-wiring/refused-responses.jsonl`. A `--scripted` assent is never user text and never
  adopts a file. A later quote (a re-approval) is recorded as operator text, and an `approval` row
  is added to the custody `steering` ledger with the current approval digest. If recording fails
  after the approval is written, retry with `ravel gate-wiring checkin1 --rundir <run> --quote <text>`.
- These recorders act only on epoch-two contracts. Older runs are unchanged.

## Response path and steering

- `ravel gate-wiring respond --rundir <run> --text <user text> [--approve CASE] [--reopen DIGEST]
  [--withdraw CASE:FINDING]` records the user's text and only the decisions the operator names.
  Each decision quotes the recorded text: the case id or the first 12 characters of the action
  digest, or the finding id. Text that does not contain the quote records no decision. A reopen
  names an action that has an `escalate` receipt or a spent per-action case budget.
- `ravel gate-wiring steer --rundir <run> --text <message> --effect note|requirement|scope_change
  [--affects N1,N2] [--span START:END]` records the message in custody under
  `inputs/user-steering/`. It also records the structured record (span, effect, affected nodes) in
  the custody `steering` ledger and mirrors it to `inputs/steering/<n>.json` for reading. A
  `user_requirement` anchor cites the span (`gate_wiring.steering_anchor`). A steering record
  never approves, reopens or withdraws anything and changes no approved byte.
- A `scope_change` holds research choices and screen dispatch with `steering_requires_reapproval`
  until the operator re-approves with `ravel approve --quote`. The hold clears only when the
  custody `steering` ledger has an `approval` row recorded after the steering row and that row's
  approval digest is still the current receipt digest and differs from
  `approval_sha256_at_event`. For a scientific study, whose receipt is written once, the same
  command is an append-only reapproval while steering holds the study: the plan and check-in are
  verified again, the replaced receipt is kept byte for byte under `inputs/science-approvals/`,
  custody records `approval_superseded` and then the `approval` row with its authority, and the
  new receipt is current. Without a hold to reconcile the command is refused (`approval already
  recorded`). An approval that steering would not record (a scripted or delegated one under a
  manual policy or for a signoff step) is refused before anything is written, so a refused
  approval never leaves a receipt behind. The final authority check, the check that CHECK-IN 1
  presents the current policy and still binds the receipt, the archive of the replaced receipt,
  the receipt and its registration are one transaction under the steering lock
  (`gate_wiring.plan_approval_transaction`): a policy recorded while an approval is being written
  either precedes the whole transaction or follows it, and a refused approval or reapproval
  leaves the previous current receipt in place with nothing appended to custody. The operator
  reapproves a held study that was approved by scripted assent with the same command
  (`ravel approve --quote`, not `--scripted`): the new receipt keeps the proposal's mode, the
  scripted receipt stays in the archive, and the custody `approval` row records the operator's
  authority with `proposal_approval_mode: scripted_yes`. A scripted or machine reapproval is still
  refused wherever the policy requires the operator. `ravel run` consults steering before it
  writes the study's attempt token, and the token counts as spent only once the supervisor's
  serialized launch admits it: when steering refuses there, before any process exists, the
  supervisor's attempt record keeps the refusal (`prelaunch_refusal`), the token and its journal
  entry move to `logs/science-attempts/refused/`, and a retry after the resume runs the study.
  A token left by an interrupted run stays spent. A machine approval clears a hold only under
  `bounded_delegated` autonomy when affected nodes, descendants, operations and rungs
  require no mandatory signoff under both the current policy and the policy recorded with the
  event. After a plan approval, the recorded policy is the one in force before the event.
  The steps a reapproval covers are read from the current plan as well as from the event: a
  descendant an amended plan adds below an affected node is covered, and a scientific study's
  stage, operation and rung are always covered.
  Changing, editing or deleting run files alone never clears a hold.
- `steer ... --scope-increase` declares that an instruction enlarges the approved scope. Such an
  event requires plan reapproval whatever its effect; `--within-scope` and `--scope-increase` are
  exclusive.
- Steering custody must exist for dispatch. The custody `steering` ledger of a run location is
  initialized by a `journal_init` row (`gate_wiring.initialize_steering`), written where RAVEL
  creates the directory: `ravel initiate`, a scientific study plan, a research study, a scan plan,
  a graph scope and a transport qualification run. A `run_init` snapshot, a parent binding and an
  earlier steering row count as well. `dispatch_permitted` refuses a location with none of them
  (`steering custody is absent`), and it refuses any file in `inputs/steering` that has no custody
  row behind it (`steering mirrors exist but steering custody is missing`). `bind_steering_child`
  writes the child mirror `inputs/steering/parent-binding.json`, so a renamed or copied child is
  refused instead of being served unbound. `ravel gate-wiring steer init --rundir <run>` is the
  operator's record for a directory prepared by hand. Only the test lock domain serves a location
  that was never initialized, as it serves a machine lease without a stage binding; only the test
  harness or a selftest selects that domain, never a variable, marker file or argument
  (`machine_lease`). Policy
  presentation (`steering_policy`) reads a location without custody as having no policy.
- A directory is never new merely because its mirrors are absent. When `initialize_steering`
  starts a journal, and when a child is bound, the directory gets an identity record,
  `run-identity.json`, and custody binds that identity to the location
  (`rdj_custody.bind_new_run`, which calls `bind_run`). The record grants nothing and custody
  stays keyed by the location. A transport qualification directory is the exception: it must
  stay empty until its probe passes, so it gets its journal and no identity record. Journal rows also record the location and the sha256 of the
  documents that state the run: the task contract, a study plan and a graph specification.
  Before `initialize_steering` starts a journal at a location without one, it reconciles the
  directory with the custody that already exists on the machine and refuses when the directory
  carries the identity of a run bound at another location; an identity custody never bound; or,
  without an identity record, the task contract (for a study or a graph without one, the plan or
  graph specification) or recorded steering text of a run custody knows at another location. The
  refusal names the recorded location and records nothing, so a copy or a renamed directory keeps
  being refused and the pause, veto or parent binding of the original stays in force. A run is
  served only at its recorded location: return the directory there (a run whose task contract
  names a bound `run_id` is moved with `rdj_custody.relocate`). `steer init` at the recorded
  location stays idempotent and keeps every control. Two limits: a directory that holds no
  identity record, no such document and no steering text cannot be told from a new one; and an
  older directory whose task contract is byte-identical to that of a run custody knows elsewhere
  is refused even when it is a different run, which then needs a new run directory. When the
  custody store of the machine itself was lost, an identity record names a run custody no longer
  knows and the command refuses it; the operator removes `run-identity.json`, and the command
  then reconciles the directory by its documents and steering text like any directory without
  one.
- In-process work admitted under steering (a graph node, a host working window) is identified by
  an admission lock its process holds, not by its process id. The record in custody names the
  lock; the kernel releases it when the process ends, so a killed process, an unreaped one and a
  reused process id all read as ended. Ended records are removed from the custody file under the
  admission-record lock when the records are read or changed.
- A pause refuses every new launch and queued submission under both `on_pause` modes. The worker
  stop record `agent-work/stop.json` names its mode. Under `drain` an attempt already admitted
  (a running supervisor, an open host working window) finishes its broker work, including its
  final outputs and self-checks; only a call that starts native work is refused, and reattaching
  to a started attempt does not end it. Under `cancel`, and for a stop record without a mode or one
  that cannot be read, every broker call is refused (`stop_requested`) and supervisors are told to
  stop. A drain never replaces a cancellation already in force.
- A pause is durable in three steps: the steering row (dispatch is refused from here), a
  `pause_intent` row recording each stop marker it will write and what that marker replaces, and,
  after the markers, a `pause_execution` row pinning them. Every marker names its pause. If the
  process dies between these steps, `steer state` reports the pause as `requested`, and the
  acknowledged resume restores exactly the markers that pause wrote; an earlier stop it replaced
  returns and a later independent stop stays in force.
- The host gate classifies `ravel gate-wiring respond|steer|checkin1` (and the
  `python -m ravel.workflow.gate_wiring` form) as `approve_plan`, so agent sessions are denied them
  as they are denied `ravel approve`. `ravel gate-wiring cost` is read-only.
- Transport: these commands run as the operator's OS user. The operator path is not separated
  from agent sessions, so this is same-user transport. Authority `unknown` is
  same-user text and is treated as the operator's: any process of that user that calls the
  recorders or writes the custody ledger directly can record it. The host gate denies the command
  forms to agent sessions it governs; the steering ledger is not resistant to the operator's own
  user, and nothing in it attests a human identity. The R2/R3 wiring states
  that, and every R3 gate also requires a recorded human approval (below).

## Gates

`gate_wiring.GATE_WIRING` holds this table; a test keeps the two equal. A wired R2/R3 gate is
decided by `gate_wiring.require_delegated` on a **delegated** epoch-two run. On an undelegated
epoch-two run the operator runs the command, and that command is the human decision, so those
transitions keep their existing checks. A pre-release run keeps its old decision. An epoch-two run
whose contract changed after `run_init`, or that has no `run_init` row, is refused.

| Gate | Class | Status | Transition, or the condition that blocks wiring |
|---|---|---|---|
| `failed_stage_feedback` | R1 | wired | scientific_judgment.failed_feedback, research_coordinator_decisions.diagnose, research-cycle diagnostic-feedback |
| `research_choice` | R1 | wired | scientific_judgment.research_feedback, research-cycle adjudicate; research_orchestrator calls it before every adjudication |
| `launch` | R0-R2 | wired | launch_authorization: dry and smoke screens through P15, full and scan at R2 on delegated runs; production_executor.launch_errors |
| `approve_plan` | R2 | wired | workflow_state.record_delegated_approval on delegated runs; lifecycle.drive and review.points gate nodes |
| `checkin2_accept` | R2 | wired | workflow_state.record_delegated_go on delegated runs; review_points.accept_checkin2; lifecycle.drive and review.points gate nodes |
| `correction` | R2 | legacy | ravel science-correct admits a correction under physics_review's own bounded approval; no correction action exists for an RDJ case to pin outside the review.points gate node |
| `deviation` | R2 | legacy | no transition records a deviation decision; recipe_ledger consumes the deviation authorizing receipt directly |
| `delivery` | R3 | wired | result_pack on delegated runs, plus a recorded human approval (same-user transport) |
| `final_task` | R3 | legacy | decided only on the review.points CHECK-IN 3 and ml_study gate nodes; verify_pack's final check is physics_review's |
| `report_integrity` | R3 | legacy | decided only on the review.points gate node; no ordinary report transition exists |
| `export` | R3 | wired | submission_export.export on delegated runs, plus a recorded human approval (same-user transport) |
| `unblind` | R3 | legacy | decided only on the ml_study unblind gate node and ml_crossfit; epoch-one contracts are refused |
| `spend_above_ceiling` | R3 | wired | check through require_delegated and the ml_study spend gate node; run_ceilings.charge refuses any charge above the recorded ceiling, which only a custody-recorded CHECK-IN 1 response raises |

### R2/R3 conditions

- In place: the epoch contract and custody-registered receipts, worker-receipt registration, the
  executor with stage-receipt and module-origin registration and the comparison producer, role
  cards, and the trusted response path (this record).
- The operator path (`--host-config`, receipt registration) is not separated from agent sessions.
  R2/R3 transport is therefore **same-user transport**.
  Every R3 gate also needs a recorded human approval of the case that authorizes its action. That
  approval is a `ravel gate-wiring respond --approve CASE` row in custody, read from the receipt
  `rdj_loop.authorizing_receipt` returns. Without it the wired check refuses with
  `r3_human_approval_missing`. Steering text never supplies it.
- Actions: `bulk_action` (full and scan launch, R2, the plan node of the held lease),
  `plan_action` (delegated CHECK-IN 1), `checkin2_action` (delegated CHECK-IN 2 GO, every file the GO
  binds), `delivery_action` (delivered claims without the stamped enforcement record),
  `export_action` (request bytes and delivered claims) and `spend_action` (invocations and the
  ceilings record). A proposer opens the RDJ case on the action built with `write=True`.
- `spend_above_ceiling` positive path: the operator's CHECK-IN 1 response that raises the ceiling
  is custody-recorded (`ravel approve --quote`). An R3 RDJ case on `spend_action` is authorized
  only after the operator's recorded approval, because the gate is irreversible. The decision
  gate and `require_delegated` then pass.

## Action paths that reach compute or delivery

| Path | Decision | Status and reason |
|---|---|---|
| `scientific_judgment.failed_feedback`, `research_coordinator_decisions.diagnose`, `ravel research-cycle diagnostic-feedback` | `failed_stage_feedback` | gated |
| `scientific_judgment.research_feedback`, `ravel research-cycle adjudicate` | `research_choice` | gated |
| `research_orchestrator` `coordinate.adjudicate` node and `open_research` review branch | `research_choice` | gated: `gate_wiring.require_research_choice` before each adjudication |
| `launch_authorization.authorized_popen`, reached from `ravel stage` and `ravel run` (scientific, scoped and native stages), and `ravel scan launch` | `launch` | gated on a delegated epoch-two run: a dry or smoke rung through P15, a full or scan rung through the R2 launch gate, which includes the executor provider (the node's worker receipt or host waiver). Undelegated runs keep the approval and review checks of the launch authorization |
| `stage_supervisor` bare branch (no approval record, no plan and no active review) | none | legacy: a run with no CHECK-IN 1 record. The supervisor launches without authorization only when nothing names a plan. A planned node launches through `production_executor.launch_stage`, which calls the launch gate |
| `science.py` v1 runs | none | legacy: science runs use their own plan approval (`_capture_science`); no epoch-two contract exists for them |
| `ravel approve`, `workflow_state.py approve` | approval | CLI path records CHECK-IN 1 custody; the direct `workflow_state` form does not. Both are denied to agent sessions by the host gate (`approve_plan`) |
| `workflow_state.py delegated-approve` | `approve_plan` | gated (R2): `require_delegated` on `plan_action` before any approval byte is written. The plan pre-authorization also runs PHYS-RDJ for agent-inferred critical fields. It takes no `checkin1` snapshot, so the wired gates keep comparing against `run_init` |
| `workflow_state.py delegated-go` | `checkin2_accept` | gated (R2): `require_delegated` on `checkin2_action` before the GO record is written |
| `scientific_judgment.advance` | review points | an epoch-two run delegates to the `review.points` graph (`graphs.review.orchestrated`), whose gate nodes call the decision gate; older runs keep the research-orchestrator review |
| `ravel gate-wiring respond`, `steer`, `checkin1` | operator text and decisions | host gate `approve_plan`, denied to agent sessions |
| `route_prompt.py --out` | contract production | listed legacy: it writes a contract with no epoch and no pinned reading or plan, so the gates keep their pre-release decision for it. It warns on stderr and names `ravel initiate` as the release intake |
| `ravel result-pack` | `delivery` | gated (R3) on a delegated epoch-two run: `delegated_errors` on `delivery_action`, plus the recorded human approval. The result records `host_authored_nodes` |
| `ravel export-submission` | `export` | gated (R3) on a delegated epoch-two run: `require_delegated` on `export_action`, plus the recorded human approval |

## PHYS-RDJ, impossible fixtures and cost

- `gate_wiring.physics_value_errors(run, value)`: on a delegated epoch-two run, an `agent_inferred`
  physics-critical value needs an authorizing RDJ receipt (default gate `approve_plan`) for exactly
  that value (`gate-actions/physics_value/<sha>.json`). The receipt's case must hold at least one
  externally verified anchor. The epoch and the delegation come from `review_points._facts`, which
  refuses a contract that differs from `run_init`. A run whose facts cannot be read is refused.
  Values from the user, a publication or a tool output, and noncritical values, are outside this
  check. The production caller is `scientific_autonomy.plan_preauthorization`. Every agent-inferred
  critical plan field there is refused unless the check passes on an epoch-two run.
- `gate_wiring.register_impossible_fixture(run, id, reason)` declares, from a library caller,
  that no honest path passes the run's gates. A wired check or a PHYS-RDJ check that passes on
  such a run is refused with `impossible_fixture_pass` and recorded in the state directory's
  `gate-wiring/gaming-events.jsonl`.
- `ravel gate-wiring cost --rundir <run>` reports RDJ model calls from the custody role
  ledger and tokens and cost from registered worker receipts that still verify. Calls with
  unreported usage are counted, not estimated. It also reports per-case outcomes and budget state.
  A spent budget gives the `escalate` outcome.

## Gates still decided on their earlier path

`correction` (`physics_review`), `deviation` (`recipe_ledger`), `unblind` (`ml_study`,
`ml_crossfit`), `report_integrity` and `final_task` are decided on their earlier path outside the
graph gate nodes listed above. The impossible-fixture, gaming-event and refused-response records
are kept under the state directory's `gate-wiring/` and name their run directory.
