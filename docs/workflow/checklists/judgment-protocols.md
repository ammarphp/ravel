# Checklist — judgment protocols  ·  the HOW behind every [judgment] tag

Run the matching protocol before a scientific [judgment] step. The `judgment-protocols` skill routes here.
Protocols compose: source discovery can lead to a trap sweep and basis comparison; a discrepancy uses
anchors and decomposition; delivery includes attacks on the drafted result. Retain the evidence and
unresolved obligations in the run. The examples below are generic illustrations, not execution records.

## P1 — look-first

**WHEN:** preparing, comparing or describing a published figure, table, contour or cutflow.

**DO:** Extract the actual artifact and inspect it. Record axes, scales, units, binning, marker and band
conventions, panels and support in the figure contract before building the counterpart. A caption or a
similar figure does not establish this artifact's grammar. Keep the extraction and inspected-image pins.

**Example:** A sparse lattice and a smooth interpolation can show the same quantities while implying
different coverage. Preserve the published support and label any declared interpolation.

## P2 — basis-manifest

**WHEN:** comparing numbers or curves whose conventions can differ, including a published reference.

**DO:** Write both sides' states summed, perturbative order, PDF, inclusive or selected sample, expected or
observed column, channel combination and normalization. Hold the numerical comparison until the conventions
match, or record an explicit transformation and its resulting manifest. Check an applicable identity and
its tolerance; record a reason when no identity is available. Preserve both original manifests.

**Example:** A selected-sample cross section and an inclusive model cross section need an evidenced
conversion before their normalized limits can be compared.

## P3 — trap-sweep

**WHEN:** routing a new analysis/model pair and before generation.

**DO:** Walk [physics traps](physics-traps.md) and answer every cheap check with evidence. Give each hit
its numbered check-in flag, escalation and named route consequence. Recompute the sweep from those verdicts.
Route from the actual model, observable and selection rather than similarity to an earlier study.

**Example:** An interfering amplitude can require a signed signal contribution and an appropriate shape
model. A positive isolated-bump template does not establish that interpretation.

## P4 — anchor-chain

**WHEN:** a produced cross section, efficiency, yield, fitted value or limit will be used downstream.

**DO:** Obtain an independent scale or limiting-case check before using the number. Record value, anchor,
ratio, tolerance and the action taken. An unexplained ratio outside the stated regime opens P5 before the
dependent claim proceeds. Native completion or optimizer convergence does not replace this check.

For a novel quantity, use independent limits, dimensions, sum rules or a separately derived calculation.
State each check's scope. If the necessary anchor is missing, retain that status and design a bounded
test. Hold the dependent numerical claim while continuing independent hypothesis or preparation work.

**Example:** A fit can converge at an imposed search bound. Check whether the requested crossing is
actually bracketed rather than interpreting the bound as a measured limit.

## P5 — discrepancy-decomposition

**WHEN:** expected agreement fails beyond its stated tolerance.

**DO:** List candidate causes, including conventions, normalization, acceptance, statistics, implementation
and reference decoding. Rank the discriminating tests by cost. Test in that order, correct a confirmed
cause, recompute the residual and repeat. Report the named contributions and unresolved remainder.
A failed test or unresolved cause stays visible; do not allocate more events before testing cheaper explanations.

**Example:** Correcting a normalization mismatch can leave a separate response-model discrepancy.
Report the changed basis and the residual rather than treating the first repair as full agreement.

## P6 — source-ladder

**WHEN:** an efficiency, cutflow, likelihood, model file, setting or other required input is missing.

**DO:** Record each applicable rung in `inputs/resource_census.json`:

1. Publication body and auxiliary material.
2. Public data record, including its resources as well as tables.
3. Public source code and source-author documentation.
4. Compatible recasting databases and routine catalogues.
5. Citing work, including detailed technical studies and theses.
6. The physicist, with the source census and concrete choices.

The `resource-sweep` skill automates the first five source classes, including HEPData resources and
Rivet, SimpleAnalysis, SModelS, CheckMATE and MA5-PAD catalogues. Record an outage, skipped rung or
inaccessible source with that status. Before claiming absence, walk rungs 1–5 or give a typed
not-applicable reason. Never invent the missing input.

**Example:** A data record's resources can contain a likelihood that is absent from its table list.
Check both locations before proposing a counting approximation.

## P7 — conservative-default

**WHEN:** adopting an assumption within the approved scope or a permitted proceed-with-flag decision.

**DO:** Establish the direction of its effect on the requested quantity. For exclusion, choose a weaker
claim when that direction is demonstrated. For measurements, fits and research comparisons, preserve
alternative assumptions and propagate their effect; a smaller number is not automatically conservative.
When the sign is unknown, record it as unknown or propagated rather than infer it.

Implement the choice reversibly with a recorded rollback. Record the numbered check-in flag and `DEVIATIONS.md`
entry, expected sign and size, reversibility, resource effect and supporting justification. A physics-critical
default requires its permitted request, invariant or authoritative-practice basis and current authority.

**Example:** Choosing a lower perturbative order does not by itself establish a weaker exclusion.
Check the relevant normalization and uncertainty before describing its direction.

## P8 — kill-the-result

**WHEN:** drafting a result for final review and delivery.

**DO:** Write three concrete attacks before the verification panel: one on **basis**, one on
**acceptance**, and one on **statistics**. Name the test, observed outcome and evidence for each.
State which attacks remain unresolved. Bind the attack document to the exact plan and drafted result.
The final reviewers receive these obligations; a favorable attack summary does not replace their review.

**Example:** Apparent agreement can come from reusing the reference quantity in the implementation.
Trace the allegedly independent inputs and test the counterpart without that shared result.

---

## Judgment sites under the controller

In a controller-owned run, a judgment call is represented by a typed `decide` step with its declared
triggers, instruction units and required output. The governed step graph dispatches the seat and
verifies the receipt-bound record before adoption. Fixed routes and judgment planning use the
same record and trigger checks where they declare such a decision.

An `operate` step in a judgment plan can carry a closed `operation_task`:
`{"materializer": "science-mode", "task_input": "inputs/task.json", "result_output": "outputs/result.json"}`.
The task input must be a declared run input or an accepted output of a dependency; the result must
be a declared output. Installed registrations cover measurement and authored-analysis
tasks. Supply the native adapter's validated task JSON in that input file and declare every file
its input reader returns. File paths in the native task resolve relative to that task file.
The controller pins the task bytes and installed materializer sources at approval, then checks
current plan identity, accepted input custody, the native task contract and complete declared
file inputs before materializing its fixed launch. The ordinary native signature, executor role,
authority, confinement and output validators still apply. An unregistered task holds; no inline
command or worker-chosen module is admitted, and an operation is never replaced by an author seat.
The authored task adapter runs one fixed Python child inside the enclosing controller capsule,
using the native task's lint, postconditions and failure classifier. Its observation is not a
confinement grant; the enclosing launch receipt supplies that evidence. This registration refuses
`reference_paths` because additional reference withholding needs a distinct capsule policy.
The native operation's applicable normalization, cutflow and other checks still need declared
`check_inputs`; a task's successful process exit does not accept its outputs.

- **The record.** A decide step writes one `judgment-record.v1`: the question; at least two
  options (or the reason only one exists) with predicted consequences; the chosen option and its
  rationale; the protocol evidence its triggers require; reversibility and budget impact. A
  decision without a valid record is refused: the step does not close and nothing that depends on
  it runs.
- **The class.** The controller computes the consequence class from code tables, never from the
  worker. R0 is bookkeeping, naming or ordering. R1 is a reversible choice inside the approved
  scope. R2 is a consequential scientific choice: method, basis, selection or a statistic the
  request allows. R3 is a physics-critical ambiguity, a scope change (a new or dropped
  deliverable, a changed prescribed statistic or boundary), unblinding, spending above a ceiling,
  or adopting a default the request leaves to the physicist. A declared class can raise the
  computed one, never lower it; an unknown action is R3.
- **What each class requires before its effect.** R0 is recorded. R1 is recorded and reported at
  the next check-in. R2 needs independent RDJ critic-seat credit on the exact record. R3 also
  needs current authenticated authority for the chosen action. The controller's terminal response
  is recorded as unattested and grants no effects by itself; a worker must not supply operator authority.
- **The four site modes** map onto the classes: manual is R3 authority; delegated is R2
  independent review; script-assisted is an `operate` step that runs the named tool;
  proceed-with-flag is R1 with a P7 conservative-default record and a deviation entry.
- **Protocols as structured output.** A trigger names the evidence the record must carry: P1 a
  figure-grammar record; P2 two basis manifests, the transformation and the identity check; P3 the
  trap-sweep record; P4 number, anchor and ratio rows; P5 the decomposition table; P6 the
  source-ladder rows; P7 the default record; P8 the three attacks. A method escalation also
  carries its method-decision record, and a stage recovery its local diagnosis and recipe-search
  record. The schemas require these fields and `controller.judgment.protocols` checks specified
  relations: manifest equality, anchor ratios, trap-sweep reconstruction, test cost order, ladder
  status and attack-axis coverage. These checks establish the record's structure and those coded
  relations. They do not establish that every claim is attached to the actual scientific inputs,
  that an asserted image inspection occurred, or that the evidence supports the chosen method.
  Current-subject custody and the required reviewers must establish the applicable support.
- **Asking.** Questions and R3 calls go through the authority service with their current pins and
  effect bounds. The terminal records an answer without attesting a person. In an
  unattended run the operator is notified once and ready independent branches can continue. When the operator's
  wait bound passes, the controller takes the recorded conservative default (P7, labelled) if the
  operator's policy allows it; otherwise that branch stays held. A default that differs from the
  recorded choice overturns that choice, and its branch stays held; the default for an R3 step
  that has no record is not to run it. When nothing can proceed, the run ends in a qualified
  delivery.
- **The judgment route.** A request that no route spec covers is declared the same way. The planner
  frames it (objective, deliverables with acceptance criteria, constraints, unknowns, numbered
  assumptions, boundaries) and a plan critic reviews the frame. The planner decomposes it into
  typed steps, the controller classes each call, and exact-subject RDJ critic-seat review covers
  its R2 and R3 calls before
  CHECK-IN 1 approves the plan. Replans are bounded (three unless the operator sets another bound)
  and a scope-changing replan needs renewed authority. Before the final review a fresh worker that
  is neither the planner nor a producer writes the three P8 attacks; they become the final
  reviewers' must_check items. An unmatched request retains its original obligations and receives
  judgment planning. A missing task materializer, child-route binding, physical input or native
  executor can still hold execution and dependent synthesis. Planning preserves the question;
  successful execution requires the actual operation binding and evidence. See the
  [operation contracts](../../reference/scope.md#scientific-interfaces).

Machine decisions are labelled as machine decisions. Neither a protocol nor a machine approval
establishes expert human review. Escalate missing required expertise and decisions outside the
delegation.

**Runs the controller does not own.** A session that drives a run with the legacy commands keeps
the earlier procedure. Manual mode escalates unresolved scientific judgments to the physicist. An
explicit delegation recorded through `docs/workflow/start.md` uses the authorized scientific
reviewers and coordinator within the declared scope, resources and correction bounds. CI2 and CI3
review remain independent. Such results are labelled NOT GOVERNED.

The remaining command examples describe the lower-level graph and scientific-review interfaces.
Controller-owned runs retain their controller state, authority and sole delivery sink; an applicable
legacy command refuses ownership rather than replacing that path.

## Finding classification and bounded repair

New review findings use `findings.v2`; it also accepts unchanged version 1 documents.
Version 1 findings remain unclassified and retain their prior routing. For a defect,
`classification` contains `kind: defect`, the reviewed `artifact_sha256`, one `target`
step or node, and `rework_evidence` explaining why its repair changes the result.
For a qualification it contains `kind: limitation`, the reviewed `artifact_sha256`, and
`claims` with each `claim_id`, `effect` (`bounds` or `invalidates`) and `bound` (or
`unbounded`). Severity and evidence authority remain separate from classification.

`ravel agent-graph rework --graph <graph> --findings <document> --reason <reason>`
repairs exactly the named defect nodes and their descendants. `--nodes` must match
those targets if supplied. Qualifications enter the retained qualification census and
claim disposition without spending rework budget, even when the budget is exhausted.
The old `--nodes` interface is reserved for legacy unclassified/manual repairs.
Repeated objections against unchanged artifact bytes do not spend another repair.
Scientific findings use the same classification fields alongside their located
journal evidence; a defect names its owning execution stage or a domain-mapped phase node.

Use `ravel review --rundir <run> reclassify --request <json>` for an open journal finding: the declared
decider supplies a reason and replacement classification; the original vote and
classification remain in the hash-chained journal. Reclassification grants no new
execution authority. A qualification-only send-back does not authorize correction;
the decider must explicitly accept a permitted supported scope before delivery.
A decider send-back must carry a defect, and no reclassification can leave an
acceptance carrying a defect or a decider send-back without one.
Acceptance can carry qualifications. Each bounded affected claim must be qualified
or withdrawn; invalidated or unbounded claims are withdrawn. The actual manuscript
claim census and its visible reasons must retain these effects. Honest withdrawal
of a headline claim permits delivery of the negative result without regeneration.
Research methodology status and its census handoff include these journal qualifications.

Journal defect targets must name an allowed owning stage when submitted as well as
when reclassified. Each review policy claim scope can explicitly list `claim_ids`;
without that field its own scope identifier is the claim identifier. A qualification
must name a claim in this policy census. Historical unbound findings remain readable
but must not pass delivery as if their scope had been established.

For every delivery route with retained qualifications, the accepting decider supplies
one existing full claim-disposition package (`plan`, `rows`, `value`, `evidence`)
among its pinned `supporting_artifacts`. Its literal final prose must retain every
required qualification or withdrawal. The journal retains the bounded package bytes
so live, detached and retained review checks can enforce the same rule. In ordinary
role orchestration the package can be an explicit source-bound case anchor, which
is forwarded to review support. A generated summary does not replace this witness.
The accepted scope must not contain a withdrawn or unresolved claim; a separate
diagnostic scope can still deliver a supported negative result after headline withdrawal.

## Progress, bounded endings and unattended waits

A redo must change the cited artifact bytes or the affected check result. The review
journal compares the retained evidence/check values across correction cycles; changed
settings, a new attempt identifier and a restated finding are not progress. After two
consecutive unchanged redos, status supplies a `limitation_candidate` with the original
finding and correction history for the decider. It does not reclassify the finding or
accept a claim. The existing stricter refusal of a repeated classified defect on the
same bytes remains. Repeated refused graph requests also retain a decider handoff,
without invalidating nodes again or consuming model calls.

Use `ravel status --rundir "$RUN"` to read per-stage redo counts, the last accepted
review-cycle timestamp, elapsed seconds and any human wait. No accepted progress is
reported as unknown, rather than as the time of a failed attempt. A wait states
`WAITING FOR A HUMAN since <time>: <reason>, <what is needed>`; repeated reads preserve
the start time. A recorded escalation blocks later acceptance/compute use of that
cycle; historical receipts remain intact.

An explicitly configured local notification command is optional:

```sh
ravel status --rundir "$RUN" --notification-command '["local-notifier"]'
```

The command receives two additional arguments: the run path and a one-line reason.
It runs without a shell, inherited stdin or default network action. It receives no
request text, findings or scientific data. Each explicit invocation can notify once;
status records the current notification state. Run approval requires its own check-in.

When bounds are exhausted or the review escalates, produce a qualified ending:

```sh
ravel task-completion qualified --rundir "$RUN"
```

This writes `outputs/completion/qualified-delivery.json`, a located boundary record
and an appended `DEVIATIONS.md` entry. Every original obligation is stated as
`satisfied`, `negative`, `partial` or `blocked`. The optional `--request` is an existing
completion request: its contributions must pass the ordinary current child-evidence
and review checks. Without such a request the conservative ending marks every
obligation blocked. It preserves unresolved findings and qualification candidates.
Qualification-affected claims are withdrawn through the shared disposition contract.
An optional `--claim-package` supplies the existing plan/rows/value/evidence document
shape; every declared claim must be withdrawn with its literal final scope and reason.
No new scientific claim is adopted by this fallback.

A valid delegation is labelled `machine-produced under delegation`; otherwise the
artifact is a machine-produced status summary. Neither label authenticates a human
or approves anything new. The ordinary final-delivery and execution gates remain
closed. Escalation and exhausted defect-review or correction-failure mutations
automatically attempt this ending after committing the journal event. Exhaustion
includes the two-unchanged-redo bound even when numerical redo capacity remains.
That bound keeps the existing decider route; reporting does not reclassify a
finding, spend another redo, add an escalation or declare a human wait.
Their responses include `qualified_ending` with `recorded` or `unavailable` status
and a repair reason when missing; the review CLI exits unsuccessfully for an
missing report. Reporting failure preserves the terminal event and its refusal.
An identical escalation retries reporting without adding another journal event.
The publication lock is acquired before observing the report's source custody,
which is checked again immediately before final publication. Failed publication
restores prior reporting bytes where they still match this attempt; separate edits
are preserved and an incomplete restoration is reported. This is not a transaction
across arbitrary concurrent writers or a crash-atomic update of multiple files.
Status remains observational; use the explicit command above for an older terminal
journal or to supply an existing completion request. Upstream execution consumers
must retain the returned reporting metadata to expose a publication failure.

## Evidence obligations and exploration

An RDJ node can declare a nonempty `evidence_obligations` list of required anchor
kinds. A branch closes when externally verified evidence of each required kind
supports its obligated node; it need not reach the class's minimum depth. Untyped
branches retain their minimum-depth rule. The maximum depth, edge reviews, unknowns,
common-source checks, alternatives and transport requirements still apply. Low
confidence or weak reviewed support requires additional distinct sources for each
kind. Identical content counts once across paths, producer receipts and acquisition
routes; copying evidence must not discharge an additional-evidence requirement or
hide shared support across claims. Different bytes alone do not prove independent
scientific provenance. Contradictory external evidence keeps a typed branch held until resolved.
The highest risk class still needs a tool-output or measurement anchor on each path.

Retrieved evidence must join an authenticated acquisition receipt, exact content
bytes and a UTF-8 excerpt at declared byte offsets. Practice authority additionally
requires a separately pinned, independently supplied `scientific-practice-reference`
descriptor joining the exact source identity, full content digest and a policy source
category. A citation or proposer-authored category is not authority. Provenance and
source type do not prove applicability; reviewers still judge the claim.

A bounded unfamiliar choice can use an explicit exploration-only RDJ case. The
supplied `rdj-exploration-contract` binds the exact `research_choice` /
`screening_choice` action digest, hypothesis, question, expected outputs, stop
condition and finite broker/model bounds under current policy. Set the action's
`authorization_scope` to `exploration_only` and pass the independent contract pin to
`open_case`. Every reviewer sees that contract. The receipt authorizes the selection
only, explicitly denies execution and scientific acceptance, and retains the full
risk class and its reviews. It must not be reused for launch, promotion or delivery,
and does not establish the route as accepted practice. Executing any experiment
still needs the ordinary execution authorization and resource accounting.

Current same-gate decision reuse revalidates the action, evidence, class, scope and
policy and spends no additional model calls. An accepted route whose source evidence
changed no longer suppresses the novelty trigger. Supplied action pins must identify
the same current subjects as the accepted case; another path with identical content
does not inherit its review. An explicitly changed route requires review even when
both routes already have the highest risk class. Existing callers that supply only
the action digest retain their current case-custody checks.

Cross-gate reuse is explicit and bounded. Before the source review, supply an
independent `rdj-review-scope` input with `schema_version: 1`, a scope and regime,
canonical `compatible_gates`, the exact action (`kind`, `summary`, `digest`, `pins`)
and nonempty `semantic_inputs` pins to independently supplied JSON. Pass that pin
as `review_scope` to `open_case`; all reviewers see the complete compatible gate set,
semantic content, input hashes and actual policy/card contracts. A later
`open_case(..., review_scope=pin, reuse_from=receipt_id)` creates its own scoped case.

Only equal effective gate obligations, unchanged decision/evidence/regime/input
digests, the same proposer and a clean accepted bundle permit reuse. Original
transport outputs and source authority are reverified. The shipped `delivery` and
`final_task` review contracts form a compatible pair; each still runs its own ordinary
execution, completion and human-approval checks. Human approval does not transfer.
Changed context, risk, policy, cards or typed obligations removes reused verdicts
and requires current review. Legacy, exploratory, revised or finding-bearing bundles
receive no cross-gate review credit. The new receipt records its source lineage;
the old receipt never gains another gate.

Cost policy records absolute cost, declared budget fraction, irreversibility and
scientific consequence separately. The existing positive-spend risk floor is
preserved. A budget number or fraction alone does not prove authorization and never
lowers risk. The fractional threshold remains unset pending an owner decision.

## Executable reviewer checks

A tightening rubric overlay can add `executable_checks` for named reviewer roles.
Each check binds an existing permitted document-validator identifier, an exact
run-relative subject pin, an optional producer broker-receipt pin and whether a
distinct method is required. The review approval binds these obligations. Removing
or changing them after approval refuses review credit.

Credit requires the reviewer's own broker execution against the dispatcher-pinned,
unredacted subject in its review packet. The current input and result bytes must
match their receipts. Missing, failed, inconclusive or empty checks do not earn
credit. A later check of the same subject that raises, or broken later worker
custody, must not retain credit from an earlier pass. Completed checks identify their
subject through normalized input pins, including equivalent path spellings.
A later validator exception without a subject pin also holds credit when its
argument digest differs: the digest alone must not exclude another spelling of the
same path. A completed check with a pinned different subject leaves prior credit intact.
A declaration or self-reported check is insufficient. Existing review
requirements remain in effect when no overlay is selected.

The receipt report separates actor independence from authenticated callable
identity. It records `same_callable`, `distinct_callable` or `unknown` by comparing
the registered module and function in producer and reviewer executions on the same
subject. A different callable does not prove an independent scientific method;
`scientific_independence_proven` remains false. `method_independence` stays
`unverified` until an authenticated checker contract establishes an independent
computation of the same quantity. The current registry supplies no such relationship,
so `require_distinct_method` remains an open requirement. Producer diagnostics require
one current matching subject input and one correctly identified, substantive passed
output. A passed label with material findings must not earn reviewer credit.
These checks  use existing
document validators. The existing `review.normalization_recompute` check independently
recomputes the scalar yield from supplied cross section, luminosity, branching fraction,
correction factor and efficiency; a wrong yield or missing input refuses credit.
This checks arithmetic, not the applicability of those inputs or event-level closure.
It does not authorize native execution. The registered likelihood comparison can
compare supplied frozen-point values through the same packet and broker path; this
does not authenticate their producing engines or independently recompute a model.
Specialist point credit needs its consumer to enforce these rubric obligations.
Run-only cut checks still need a transitive-source contract before they can satisfy
an executable document obligation. Independent model recomputation and verified
method relationships remain separate integration work.

## Selectable investigation team

A graph can opt into `team_shape.policy = investigator_consult_reviewer`, naming one
investigator node, non-voting consultations (each with its specialty), and one blind
reviewer for each declared consequential subject. The policy censuses every agent,
requires the reviewer to depend on its subject, and refuses hidden agent populations
or a changed team arm during revision. Its ordinary graph budgets and fresh-context
review transport checks remain active. Omission selects the existing team behavior.

This is an advisory investigation-scheduling policy. It does not delete or
replace the mandatory reviewers required by a scientific decision gate. Graph
completion remains separate from scientific acceptance and execution authority.
