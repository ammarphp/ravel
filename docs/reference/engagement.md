# Proportional engagement

The controller computes lean, standard or full engagement when it renders CHECK-IN 1, and
again for a replanned plan when its deviation check-in renders: one decision per scientific
plan, which a resumed or re-polled check-in applies again rather than recomputing. The
decision records the installed policy digest, reviewed facts and their source pointers,
reasons, required seats, correction bound, packet scope and projected usage. The check-in
shows it in an "Engagement" section (tier, each fact with its source and checker, the seat
plan and the projected usage or why it is unknown), including central sessions, calls,
cost and the saving against full. Missing entries and projections that retain full scope
are labelled explicitly. The authority record binds the
decision's digest. The decision's applied view is pinned beside the unchanged scientific
plan; each consumer checks it against the current decision. Planning and its independent
critic run before the decision at their original scope; a plan revised after a decision is
decided as it is bound, before its own review credits any fact.

The tier is the highest requirement across six facts:

Request-only planning supplies method and cost facts through the existing
preparation authors. The controller adopts their declared outputs, checks the
request, original obligations, installed method ladder and exact forecast binding,
and presents the complete records to the plan critic. Accepting credit names the
exact facts and scientific plan. Research children use the same method checks
with their own complete route plan and original scope; parent engagement remains
recorded context. Their approved loop budget prices that own tier, and each
dispatch rechecks the proposal, review credit, applied plan and reservation.

| Fact | Lean | Standard | Full |
|---|---|---|---|
| Claim-bearing deliverables | At most 2 | 3–6 | 7 or more |
| Consequence | R0 or R1 | R2 | R3 |
| Compute | Reuse or a small single point, up to 200 core-hours | Up to 25 points and 2,000 core-hours, or a single full detector simulation | Larger or unknown |
| Novelty | Reviewed validated recipe | Authored implementation | New method or open question |
| Route | Simple fixed routes | Scan, site, chain, document, model inference or fallback judgment | Research or open judgment |
| Special conditions | None | Training, mixed request or judgment child | Unblinding |

A missing or unchecked fact takes its most complex value. Both point count and compute
cost must stay within a class's limits. A cheap method assertion must not override a scan
rung or an effectful plan. Facts that depend on content require exact, current plan-critic
credit. The controller store supplies their custody; a worker must not publish its own credit.

The operator can set `engagement.minimum_tier`. A physicist can raise the tier through
a terminal CHECK-IN 1 authority record. Both act only upwards: a minimum or raise below
the computed or recorded tier has no effect, and an unrecognised tier value is refused.
Environment variables, run-directory files and worker output fields do not select engagement. After
approval, recorded escalations are retained on resume. A projection above the remaining
operator budget requests R3 spending authority; it never buys a cheaper review tier.

Every tier preserves plan review, independent claim review, three written and tested
attacks before the final verdict, consequence review and authority, instruction delivery,
confinement, custody, ledger gates and the sole delivery sink. Inspection and legacy
routes make no new scientific acceptance claim and retain their separate routing contract.

At full engagement, declared reviewers remain separate. At standard, reviews on
claim-producing steps remain, with ordinary critic duties carried by the attacker;
other execution reviews can fold into the next checkpoint. The final verifier carries
critic duties; disagreement with the credited attacker activates a decider. Unknown
or mismatched review evidence also activates that seat. At lean, execution reviews,
integrity and attacks can fold into a fresh final verifier. Every six claims require
another verifier at standard or full.

Research routes use the same checkpoint folding rules. Reviews that produce
declared files retain their separate execution and output custody. Required
scientific tools remain steps at every tier. The source-built saving check covers
every installed route with scientific review at both lean and standard, alongside
the preserved plan, claim, attack, independence and instruction duties.

A fold transfers all source item identities, purpose and protocol duties, manifests,
and cards. The packet and confinement use the union of independence and exposure
constraints. Conflicting actor, forbidden-input or blind requirements keep the seat
separate. Duties whose combined packet exceeds the context budget also remain separate. There is no
truncation. Each source item requires its own verdict and evidence. Same-role reviews
can share one credit only for the exact same subject, duties and constraints.
When the execution review exceeds the independent final verifier's context budget, an already
required final seat of that review's own role can carry it at the same checkpoint,
after the same constraint and packet checks. This transfers duties, not review credit.

Claims, attack items and their complete actor constraints are set before any fold
is probed. The installed renderer appends every folded manifest's catalogue units;
unknown or changed units refuse. Every folded duty is inline and requires the same
checklist acknowledgement as the seat's own duties. Folded context follows packet scope.
The rendered step replaces repeated inline duty text with its unit id, digest and
manifest index, and prints folded manifests and cards by digest because their units
are delivered separately. Repeated review context is printed once and referenced by
JSON pointer. Source-seat and citation-array references and duplicate parameter items resolve within the
same rendered step. Item identities, checks and bindings remain intact; stored reviewer
items and verdict validation retain their complete original contract. Dispatch rebuilds
and compares the entire packet, including these references and its unchanged output schema.

Lean packets defer optional context units to logged retrieval. Every duty, the full
card and must-read knowledge stay inline. Planning packet scope remains fixed.

A packet's budget is the input window of the models that can serve its seat: the smallest
`context_tokens` less `max_output_tokens` that the model catalogue declares for the seat's
candidate models in the run's frozen preferences (the card tier, and the cheap tier for a
`cheap_ok` card). A candidate without a declared window takes the smallest window the
catalogue declares, and the packet records that basis. The capability catalogue appears in
the packet as an index of entry ids and cost classes; its complete rows are pinned data
shards. When the mandatory part would exceed the budget, the largest step-specification
values move by reference to pinned `packet-reference-*.json` inputs with their digest, size
and leading excerpt, retained in the controller's packet record. Only a mandatory core that
still exceeds the budget refuses the step (`packet_budget_exceeded`, with its remedy); a packet
is never truncated, and preflight refuses a selected model whose context window is smaller than the complete packet.
Correction bounds are one, two and three rounds at lean, standard and full. A finding
consumes the bound in force when it occurred; escalation does not reset that count.

Persistent validation failure, an uncredited or blocking review, a discrepancy or an
anomaly raises engagement by one tier. New R2 choices require at least standard and
an independent decision case. New R3 choices require full and authority. A second
successful mechanical retry adds explicit review seats on that step, including when
ordinary tier rules would fold them into a checkpoint. A session costing more than
twice its expectation is recorded and notified without changing engagement. Escalation
re-reviews the triggering subject, affects undispatched work and never lowers a tier.
Seat additions are reported R1 events with a separate digest from the scientific plan.

For scans, each point still needs its governed launch receipt. Review selects
`ceil(sqrt(N))` points at standard or `ceil(2*sqrt(N))` at full, deterministically from
the scientific plan digest, plus every anomalous point. Missing receipts, duplicate
points, outside-population receipts and missing sampled reviews remain explicit holes.
The final seats also review the assembled deliverables.

## Usage evidence

At each wave join and delivery, the monitor joins dispatch, observation and instruction
receipts by node or step, seat and attempt. It checks:

1. Each dispatch has exactly one unique session with reported usage.
2. Input tokens, including cache, reach 80% of the delivered packet estimate.
3. Each session makes a model call; a producer returning a final record makes at least two.
4. At four or more sessions, no session supplies over half the model calls.
5. Independent broker requests equal session calls plus transport-recorded retries.
   When broker tokens are available, they agree within 1%. The count comes only from an
   independent counter the trusted composition installs (a harness or site broker that sees
   every model request outside the workers). None is installed by default: the check then
   records the broker as missing, and accepted delivery stays missing.

The governed step keeps each session's exact seat identity, packet size and the
transport's own meter. The input split (uncached input, cache writes, cache reads) is read
from the supervisor's digest-pinned capture of the transport's output and kept only when it
is complete and matches the transport's totals; nothing is inferred for a part the
transport did not report. A wave join that finds a floor failure on a completed session
raises engagement and holds every later wave with the reason `orchestration_evidence_missing`;
the run then ends with a qualified receipt that names the breach.

Unknown usage never counts as zero or completed evidence. Budget settlements corroborate
observations and must not replace them. Missing sessions, reused sessions and unattributed
observations fail the structural floor. A floor failure or missing usage on a completed
session holds the next wave and prevents accepted delivery. An attempt that ended without
completing (failed, voided or ambiguous) is still checked and its gaps prevent acceptance,
but its own failure path handles the step, so it does not hold later waves. An attempt the
transport refused before its session existed consumed nothing; it is listed as released and
is not a session. Unknown evidence also prevents acceptance; an missing projection or an
unreported price is labelled but does not hold a wave. Receipts retain all checks
and labels, including `ENGAGEMENT BELOW FLOOR`, `ENGAGEMENT ABOVE CEILING` and `USAGE UNKNOWN`.
A stale delivery check must not authorize new dispatches, a changed decision or a later
escalation, including a step-only raise that leaves the run tier unchanged.

Statistical flags are separate: completed-run calls or input below half the expected low,
or any dimension above 1.5 times the expected high, produce notification and labels.
They do not establish review quality. A partial wave is never compared with the whole
run's expected low. Unknown prices are disclosed; prices in calibration are a fixed
accounting reference, not a claim about current provider pricing.

## Building and integration

Run `python scripts/maintenance/build_engagement_envelopes.py` after changing route
specs, instruction catalogues, role cards, method ladders, calibration or the builder.
`--check` compares exact generated bytes and source membership. It builds every producer
and seat packet through the instruction interface, for each route and tier, including
folded duties and possible card-declared consult sessions. The high projection includes
two complete retries. Conditional seats and consults are excluded from hard minimums
and the low projection; the central and high projections reserve their possible use.
These ranges are design projections and need external
calibration before interpreting statistical deviations as measured performance.

A checkout without controller route specs writes an explicit `unavailable` inventory,
not a zero-cost successful envelope. The integration owner must regenerate it after
installing peers. Runtime decisions without a matching envelope retain unknown usage
and must not earn accepted delivery through this component.

Public APIs are `decide(store, state)`, `apply(plan, decision)`, `observe(store, event)`,
`check_envelope(store, stage, broker=None)`, `receipt_section(store)` and `tier(store)`.
Stages are `wave` and `deliver`. `effective_decision` projects the monotone escalation
history for subsequent work. `gate_errors` adds checks to the existing ledger gates; it
never replaces them. `policy.review_errors` validates per-item and attack structure.
The binding store owns record timestamps and hash chaining; no worker clock is accepted.

The controller's run graph takes the decision, pins the applied view, sends each wave's
outcomes to `observe` and checks the envelope at every wave join; the governed step records
each seat's usage, packet scope and folded-duty rows from their own records. Unit and
integrated controls establish software behavior only; live operation requires its own evidence.

## Independent provider records

Controller composition registers its own transport accounting counter through
`register_broker_counter`. Each launched session contributes the usage in the provider
result captured by the supervisor outside worker write roots. Records retain uncached
input, cache writes, cache reads, output, session identity and the capture digest.
Worker final records and attributed observation totals never supply independent counts.
Missing provider records, incomplete cache splits, unknown request counts, changed
captures and missing receipts remain unknown and prevent accepted delivery. Provider
acceptance evidence requires a complete population split for the selected format.
The delivery gate rechecks the provider records before reusing an earlier good check.
These accounting controls establish no scientific validity or whole-run acceptance.

## Operator compute policy

`ravel operator set --compute-policy '{"mode":"bounded"}'` selects the default
fixed-envelope policy. `generous` uses the operator's standing cost grant within
the configured resource envelope. `adaptive` admits a larger proposed compute
rung within that envelope when a completed continuation decision justifies its
expected gain using adopted result evidence. Each admission retains the frozen
grant, exact plan and step, allocation and decision source receipts. The
pre-dispatch cost gate rechecks those records against the current reservation.

Configure resource amounts with `--budget KEY=VALUE` and the model mix with
`--agent-preferences`; its existing `tier_models` selects the models for each
engagement tier. `--budget cost_usd=null` grants an open monetary envelope. Each
effect retains its finite watchdog and declared resource allocation. Cost
projections and charged usage stay visible for every policy. Resource overages
retain the R3 projection and the existing operator-ceiling enforcement.

For adaptive admission, an earlier completed step produces a declared JSON
artifact. The acting step names it in `parameters.compute_justification`. The
JSON contains `schema_version: 1`, `kind: "compute-justification"`,
`plan_sha256`, `step_sha256`, `decision: "continue"`, substantive `expected_gain`
and `cost_justification`, and distinct `evidence_artifacts` naming completed
adopted result outputs. The decision's own custody includes those consumed
artifacts. The controller binds the decision and every result receipt into its
protected admission record, then rechecks their bytes before dispatch. The
existing action, review and approval gates govern the selected computation.

The operator policy freezes at intake alongside budgets and model preferences.
Child mode inheritance carries these settings through the existing narrowing
contract; the child's own plan and priced rung determine its work.
