# Scientific review and controlled correction

Use this cycle at CHECK-IN 2 and at consequential changes to a physics recipe, statistical model,
or custom cutflow. Review actual executed settings and measured evidence before committing more
compute. The accepted scope names the permitted actions; a diagnostic result and a reproduced
reference are different claims.

## Exploration and result review

An unproven hypothesis can justify a useful experiment. Do not require prior
literature support or demonstrated efficacy merely to propose testing it. At the
exploration stage, turn criticism into a competing explanation, improved candidate
or discriminating experiment with explicit possible outcomes. Separate absent
evidence from an observed contradiction. Novel and speculative directions belong
in the research program, with concrete resource bounds and an executable method.

CHECK-IN 2 reviews what the executed evidence supports. A hypothesis can fail
while the experiment succeeds as an informative diagnostic. Limit claims to the
observations; preserve rejected and unresolved explanations for subsequent work.
An unknown needed for a claimed conclusion can block that conclusion without
blocking a separately admitted experiment designed to investigate the unknown.
The exploratory role is specified in `research-explorer`; its recommendations
do not replace the distinct critic, verifier and decider on actual results.

## Roles and evidence

| Role | Receives | Must return |
|---|---|---|
| Critic | Published definition, effective settings, measured outputs, exposure, channels, precision; producer verdict blinded | Located defects or explicit acceptance of a named scope; no speculative defect without an evidence request |
| Improvement agent | Concrete findings, approved intervention envelope, frozen rejected evidence | Minimal proposed correction, affected stages, held-fixed quantities, discriminating prediction and stopping rule |
| Skeptical verifier | Findings, admitted change, new receipts and outputs; improvement agent's favorable conclusion blinded | Whether every material objection is actually closed; new objections remain visible |
| Synthesizer / physics decider | All original findings, repair evidence, independent verdicts and unresolved assumptions | Accept named scope, admit a bounded correction, stop, or request evidence; never vote away an unresolved objection |

Use fresh contexts. The critic, verifier and decider must have distinct declared actor IDs and differ
from proposer/executor. Actor strings attest separation; they do not authenticate who actually ran.
The improvement agent is the proposer/executor, not a fourth acceptance vote. Initial acceptance
requires all three reviewing roles; an improvement pass is necessary when an objection requires repair.

A journal vote is the bound response of an actually dispatched scientific role
(`scientific_judgment.consume`). Independent credit is computed by `review_independence.decide`, in
addition to ordinary receipt, subject and output validation: the evidence must show a context
different from every author and other review seat, no inherited transcript, a RAVEL-built projected
packet, permitted exposure, packet-only access (or disabled tools) and unchanged output. By default it
is what RAVEL's dispatchers recorded while dispatching the role (`review_dispatch`): a supervised,
sandbox-confirmed worker launch or the graph runner's record of an observed fresh model request without
tools. Unknown identity, author-context review, shared-workspace access, control transports and
declared-name submissions are advice. Advice is retained under `review-advice/`; it never enters the
journal, must not close objections, admit a repair or satisfy independent review seats. Human
authorization is separate. Historical records remain readable; current admission rechecks authority.
See [scientific judgment](scientific-judgment.md#independent-credit).

`ravel review-context create --rundir RUN --role critic --out NEW_DIRECTORY` creates an immutable
role packet. Roles are `critic`, `improver`, `verifier`, `synthesizer`. Its reader exposes only listed
artifacts. Retain the returned manifest digest outside the packet and require it when reading.
This reader is **not an operating-system sandbox**. The orchestrator must provide only this packet,
with no inherited producer narrative or unrestricted filesystem/browser tools. File contents can
still reveal context; inspect projections and use counterbalanced prose controls when evaluating blinding.
Critic/verifier projections also withhold classifications and interpretive reasons from the known
diagnostic and decision-case reports, and reviewer/assumption dispositions from claim-graph inputs.
They retain measurements, public assertions, artifact identities and specific evidence requests.
For scientific-study cycles, critic/verifier packets withhold the original proposal, plan and approval
narrative and expose the actual execution task and copied inputs. Attempt results retain raw arithmetic,
per-oracle applicability, independent numerical failures and defined/undefined trace states while
withholding the producer's aggregate postcondition. Recipes expose executed settings and input hashes;
the synthesizer can inspect the original frozen proposal and recipe.

## Review rubric for a search analysis

`ravel review-rubric show` prints the `search-analysis-review` rubric: what a review panel checks in a
new search before it accepts the strategy, the background estimate, the validation, the multivariate
method, the systematic uncertainties, the sensitivity and the note. Every item states the evidence
that satisfies it and what counts as a blocking finding.

The analysis declares a review packet (`kind: search-analysis-review-packet`) with one object per
section: `strategy`, `backgrounds`, `validation`, `multivariate`, `systematics`, `sensitivity` and
`note`. `ravel review-rubric check --packet PACKET.json` applies the computed items and exits 0 on a
pass, 1 on a blocking finding and 3 when the result is inconclusive. A blocking item without its
evidence is an `A` finding that names the item, for example a major background with neither a control
region nor a cited method. An advisory item is reported and does not block. A packet that lacks a
whole section is inconclusive, never a pass. Items without a rule are judgment items; the reviewer
answers them with located evidence.

A run selects its rubric with `ravel review-rubric select --rundir RUN [--overlay OVERLAY.json]`, which
writes `inputs/review_rubric.json`. Every reviewer packet of that run then carries the merged rubric
and, for each review subject that is a review packet, the ready check input
`artifacts/rubric-check-<subject id>.json`. The plan critic, physics critic, skeptical verifier,
physics decider and integrity auditor run it through the broker with
`check run review.rubric` on that file. The receipt of the check is evidence a blocking finding cites.

An overlay holds requirements that stay outside the repository. It is a JSON file
(`kind: review-rubric-overlay`) kept with the requester's private inputs and pinned by the sha256 of
its bytes; a changed file refuses the reviewer packet. An overlay has two lists. `add` holds new
items. `tighten` raises an item to blocking, or adds a rule that must hold together with the item's
own rule. An overlay must not remove an item, replace a rule or lower a severity. Rules are data, so an
added item is computed without a code change; `ravel.workflow.review_rubric` lists the rule forms.

## Prospective declaration

Copy `src/ravel/data/templates/physics_review_policy.json` to `inputs/physics_review_policy.json`
and specialize it **before** recording CHECK-IN 1 approval. It binds actors, maximum redos, exact
mutable effective-setting paths, allowable stages, required integrity/scientific checks, and claim
scopes/actions. Never widen this file after registration. A changed policy or first approval makes
the registered review stale; a genuinely new scope needs a new declared run with parent evidence.

Record check definitions, thresholds, units, normalization, population/channel basis, exposure,
and expected precision prospectively in a diagnostic contract (see
[diagnostic contract controls](../../../tests/unit/test_diagnostic_plan.py) and
[ordinary review controls](../../../tests/unit/test_physics_review.py)). Reviewers inspect
those definitions. A JSON `pass` is a reported check result, not an independently established fact.
`ravel diagnose` checks the supplied contract and measurements; it never authorizes compute.

Retain waypoint evidence in dedicated paths. Later bulk output must use distinct stage/output
paths while keeping reviewed smoke artifacts available. Overwriting the same reviewed paths
invalidates GO. Give the full run its own approved input bindings. Directory inputs
must be represented by explicit file manifests when opening review; do not hide mutable contents
behind an unenumerated directory path.

## Open, review, repair, recheck

Run `ravel review --help` and the subcommand help for exact fields. A cycle requires actual
successful retained execution receipts, actual effective settings, located check evidence and
a valid waypoint manifest. Checks contain `id`, `status` (`pass`, `fail`, `inconclusive`),
`evidence` entries with `path` and `location`, and execution `attempt_ids`.

1. `ravel review --rundir RUN open --request REQUEST.json` freezes the cycle. Small evidence is stored once by content hash; large
   files retain hashes and sizes without copying whole ROOT/HepMC files. Preserve originals.
2. Record role verdicts from dispatched scientific roles: `ravel judgment prepare-role`, run the
   prepared graph, then `ravel judgment consume --binding ROLE_DIRECTORY/binding.json` (or
   `ravel review --rundir RUN review --request REQUEST.json` with that role's `binding`). A request
   that only names a declared reviewer is retained as advice and changes no journal state. Accept a declared scope only if its required
   checks pass and all inherited findings are explicitly closed. `send_back` requires findings
   naming evidence, check IDs, setting paths and required stages. `stop` prevents further admission.
   Acceptance also recomputes the fit and scan alarms from the cycle's retained outputs
   (`inference.json` records and the boundary flags of other result files; see
   [inference engines](../../reference/inference-engines.md#computed-review-checks)). A computed
   failure refuses any scope that needs a scientific check; a diagnostic scope stays available.
3. Prepare the minimal correction on the declared copies. `ravel review --rundir RUN correct --request REQUEST.json` records the exact
   changed bytes and stage specifications. The admission consumes a redo even if execution fails.
   It must not widen CHECK-IN 1's compute envelope. Changes to unlisted inputs are refused.
4. Execute admitted stages through the supervisor. Ordinary execution, reuse and delivery remain
   blocked. A failed attempt records correction failure; retries need a new admission and remaining
   budget. A stage already successfully redone must not run again under the same admission.
5. Open the successor with its correction ID, fresh successful receipts and rechecked outputs.
   All old material findings are inherited. Fresh critic/verifier/decider decisions must close them.
   Every inherited finding's requested checks must pass before closure, even when the accepted scope
   is narrowed to a diagnostic result. A failed or inconclusive defect recheck remains open.
6. Record the physicist's existing authorized GO using `workflow_state go`. No new user permission
   is implied when the existing instruction already authorizes the precise action. New scope or
   a policy stop is surfaced as a concrete decision for the physicist.

An accepted cycle can be followed by an open request with `"checkpoint": true` at the next consequential junction:
settings must remain identical, execution evidence must be new, and a new output must be checked.
This starts a new review while retaining history and cumulative redo use. Changed settings require
a recorded send-back/correction path, not a checkpoint reset.

A native correction changes approved card bytes, so it needs an amended CHECK-IN 1 approval. After a
send-back, edit the source card copy, build the derivative plan and prepare its cards and manifest.
Then re-approve CHECK-IN 1 with `workflow_state approve`. The new approval names the changed inputs
against the approval the review registered. Every named path must be in the review policy's
`allowed_changed_paths` and must be one of the correction's changed paths. Only then can the decider
admit the correction. Under that amended approval, the native correction adapter adopts the prepared
cards and manifest without regenerating them, and the full dependent chain runs. Preparation
happens before admission; it must not regenerate frozen settings while corrective execution is underway.
Launch is refused for any other changed byte, an ordinary preparation stage or a dropped descendant.
It is also refused when the compute plan, model, masses, detector, event count or statistical scope
falls outside the amended approval. Without the amended approval, the changed cards are refused; no
route admits them under the unchanged first approval.

## Material evidence discovered after acceptance

When new evidence exposes a material scientific defect in an accepted claim,
retain the original approval, votes, check results, outputs and execution receipts.
Record a late finding and place a scientific hold on that exact accepted cycle
and claim scope. Do not rewrite a historical acceptance as a failed calculation.

The originally registered critic or verifier owns a new finding-context JSON
document. Another independent reporter can supply evidence; this action does not
enroll a new review actor. The context has `schema_version: 1`,
`kind: "post_acceptance_scientific_finding"`, the original `run_id`, `cycle_id`,
`cycle_sha256`, `claim_scope`, ordered `accepted_review_sha256` list,
`role` (`physics_critic` or `skeptical_verifier`), that role's registered `actor_id`,
and a nonempty `findings` list. Each finding contains `id`, `summary`, `check_ids`,
`accepted_evidence` and `new_evidence`. Evidence entries contain `path`, exact
`sha256` and a located `location`. Bind an affected scientific check required by
the accepted scope, its original frozen evidence, and new nonempty evidence.
State any limits on what the available records establish.

The registered decider reviews those exact context bytes and submits a request
with `actor_id`, `cycle_id`, `claim_scope`, `summary`, `finding_context` (the path),
and `finding_context_sha256` (the reviewed byte digest):

```bash
ravel review --rundir RUN hold --request hold-request.json
ravel review --rundir RUN status
```

This appends a `scientific_hold` event and advances the journal checkpoint. It
retains the context and bounded evidence by content hash while preserving the
accepted records. Status reports `scientific_hold`, the held scope and unresolved
findings. Current delivery, reuse, bulk and correction admission refuse. A live
source or input-inventory mismatch can be reported before the hold diagnostic;
either blocker prevents the action. The retained journal and detached admission
checks also validate the hold independently of that live inventory.

A hold grants no execution, correction, new cycle, retry, budget reset or lift.
It does not revoke the factual record of past execution or retrospectively
authorize anything. Removing the new report does not lift a retained hold.
Missing or corrupt retained evidence makes the current review invalid and keeps
actions blocked. Local actor IDs and hashes retain the existing declared
separation and custody limits; they are not actor authentication.

The held run and cycle remain held. To establish a replacement claim, declare a
separate study with explicit parent evidence identifying this hold, its accepted
cycle, affected checks and unresolved finding. Prospectively approve its actual
method, sources, inputs, runtime, resource bounds and discriminating rechecks.
Retain the raw evidence needed to address the defect and obtain fresh critic,
verifier and decider acceptance for the replacement products and named scope.
Only those newly accepted products can support restored delivery or reuse.
Do not reset or recycle the old approval, attempt budget or output directory.
The hold API does not automatically link or approve a separate study; the
orchestrator must bind the parent finding and closure evidence in its new contract
and review. Keep the original held history visible alongside the replacement.

## Adaptive justification

`ravel decision-case` validates a bounded graph of public assertions, evidence anchors and reviewed
supporting links. Descend further only for an unverified assumption, conflict, novelty or consequential
choice. A branch ends in a pinned observation, tool result, source or explicit requirement; otherwise
it produces a concrete evidence/experiment request. Cycles and unbounded elaboration are refused.
It validates structure and custody, not the truth or entailment of arbitrary prose. Reviewers judge
those links. Store concise decision records, not private chains of thought.

## Boundaries and evaluation

GO v3, supervised launches, stage reuse, lifecycle delivery, result packaging, scan harvest and
verification inspect the current review. Launches retain the exact detached review and authorizations
before process creation. Later acceptance must not backfill an earlier launch. Local hash chains detect
inconsistency; they are not signatures or protection against an adversary rewriting the entire tree.
Direct external tools outside these interfaces are not universally intercepted.

The frozen benchmark exercises clean cases, deliberate faults and paired changes in producer prose.
It establishes deterministic guard behavior. To measure reviewer quality, run blinded live reviewers
against held-out faults and clean controls, logging sensitivity, false send-backs, repair success,
review cost, and time to justified decision. Multiple models agreeing is not independent scientific
validation. Keep calibration cases separate from confirmation cases, retain failed experiments,
and do not retune a simulator merely to match a target contour.

The experiment contract draws on enforced stage transitions in [Curie](https://arxiv.org/html/2502.16069v1)
and falsifiable tests in [POPPER](https://proceedings.mlr.press/v267/huang25n.html). It does not claim
those systems' empirical benefits transfer to RAVEL without an evaluation.

### Bounded indexed role evidence

Binary outputs are retained as exact indexed bytes. Large packets use a bounded
initial presentation containing complete text witnesses, byte-header witnesses
for binary members, the complete index digest/count, and explicit omission
commitments. A header, an index row, or an on-demand hash does not establish that a
reviewer read the artifact or its physical meaning. The exact judgment request
and public case must fit as complete text; otherwise preparation refuses and
requires a declared bounded witness. No initial presentation silently closes an
unresolved evidence request.

Use `ravel review-context index --packet <packet> --manifest-sha256 <digest>`
to page/search the artifact catalogue. `--section omissions` pages the original
omission reasons; `--query`, `--offset` and `--max-bytes` bound each index reply.
Then use `ravel review-context read --packet <packet> --manifest-sha256 <digest>
--artifact <indexed-id> --offset <byte-offset> --max-bytes 65536`. Binary or split
UTF-8 pages identify their base64 encoding, exact page hash, full artifact hash,
byte range and remaining bytes. The deterministic Host actions `review-index`
and `review-read` use the same allowlist and existing tool-call accounting.
An omitted large original is not an indexed copy: request a source-bound bounded
witness or a new complete packet before claiming to have inspected it. Projected
review records blinded by the role policy remain blinded.

Preparation authenticates the full copied index and ending custody. The reserved
external request records its actual initial presentation. Exact-subject receipts
count complete inline content only; source provenance, catalogue entries,
binary headers and later requested pages do not silently become proof that the
initial model call read an exact scientific subject. Explicit reviewed findings
and supporting page artifacts remain necessary. Freshness and host identity are
attestations with the existing qualifications; this does not authorize native work,
authenticate an actor, or establish physics acceptance.
