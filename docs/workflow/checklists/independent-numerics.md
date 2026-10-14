# Independent numerical review

For an epoch-two plan, `ravel.workflow.spawn_rows.derive(facts)` reads the packaged
`src/ravel/data/knowledge/spawn_rows.json` staffing policy. It returns review-point records,
without launching workers. Smoke/full tool nodes with a producer draft need a
pre-flight consult, one per registered consult family after tool-alias
resolution; authored nodes with deterministic evaluators need three
candidates from at least two model families, or two under an explicit deadline.
Absolute predictions need two blinded re-derivations and a normalization
recomputation. Panels of multiple attempts need a comparative review for shared
unjustified premises. Primary stated-input or cited-formula analytic claims need
a derivation that forbids the first method.

Drafts use the existing `spec_template` or `authored.specification` pin.
A deterministic evaluator is declared in `authored.signature.evaluator` or node
field `/review/evaluator`. Node fields `/review/deadline` and `/review/author_kind`
carry the explicit deadline and producer kind. `/review/panels` carries the bound
attempt population. Calculation/prediction claims are primary by default;
`/review/primary_claims` can declare the exact primary claim IDs. These metadata
values use the existing typed node-field schema; they do not add plan keys.

The registered `spawn_rows` decision-gate provider refuses launch or claim
acceptance until the relevant independent worker receipts are registered and
byte-bound to the current review subject. `spawn_rows.pending(rundir)` supplies
its remaining obligations to a controller. The core review-point derivation and
controller must compose this extension; their existing status view alone does
not enumerate these records. Candidate selection records, tolerance-bound RCA
opening and full independent-method enforcement remain controller obligations.
An A consult finding needs a recorded fix or waiver; opinions alone cannot block.

Use `world_digest.digest(rundir, bound_inputs)` with the complete explicit
population of run-relative journal, resource state, execution receipt and worker
input paths. Its returned `bound_inputs` contains the current content pins and
`sha256` commits to the canonical projection. Bind that projection at worker
dispatch and recompute it when any listed input changes. Unbound files, clock
time and file timestamps do not affect it. This read-only projection grants no
execution authority or scientific certification. Bundle/worker integration must
supply the complete population and deny worker writes to controller inputs.

Before certifying a fit or selected candidate, put its fit/selection PIN and
certifying reference PIN in the approved request plan's node `fields` at pointer `/review/certifications`:
`{"fit": {"path": "...", "sha256": "..."}, "reference": {"path": "...", "sha256": "..."}}`.
The field value is a list of these records, with the ordinary plan field authority
and evidence metadata. Every fit/selection provenance record must declare `inputs` as a PIN list.
Intermediate JSON records declare their own `inputs`; opaque leaves terminate
the graph. Include every tuning and candidate-selection oracle. The computed
`ravel.validation.input_closure.check(rundir, fit, reference)` traverses and
validates the pins. A reference whose content entered this closure cannot certify
the fit, even through a copied file. Stale or unavailable provenance also refuses
certification. These checks do not establish that a producer disclosed all inputs;
provenance completeness still requires the independent verifier.

The input-closure provider runs at claim acceptance and delivery gates. It reads
the pinned plan, so action-body overrides cannot erase a required check.
To compare analytic outputs, call `spawn_rows.compare_outputs` with two PINs,
the contracted JSON pointer (`second_pointer` when the output layouts differ), common unit and declared absolute/relative
tolerances. It reads existing resonance-width or formula-grid outputs without
running either method. Comparisons establish numerical agreement only; the
independent worker must establish distinct physical derivation and source scope.

## Second method, assumption audit, model critique and explore/exploit

The same `derive(facts)` call appends four more data rows; each points into the same
custody and gate. `K7S` staffs a `second-method-deriver` for every claim whose computed basis
carries `analytic` or `numerical_solver` and that `K7` does not already staff. Its
`forbidden_method_nodes` are the first method's lineage nodes; compare the two pinned
outputs with `spawn_rows.compare_outputs`. A claim with only a declared analytic basis has
no computed first method to forbid and needs an explicit lineage.

`K8` staffs one `assumption-auditor` per run with at least one claim, at the `delivery`
gate. The auditor returns an `assumption-audit` record with integer severities from 1 to
10 and a boolean control status per item. Before delivery,
`ravel.validation.assumption_audit.check(audit, result)` lists every uncontrolled item at or
above the row's severity floor (7) that the result's `assumptions_reported` omits. The
result assembler must call it and refuse delivery when it returns errors.

`K10` staffs a `model-critic` before adoption of a node that authors or imports a model. Such
a node has the `model-authoring` implementation, an `author_kind` of `model`, or one of the
model operations listed in the row. It is gated at `checkin2_accept` for that node.

`K11` declares the explore/exploit split of a research round: an `envelope` node, a
`research-coordinator` node, or any node with `/review/attempt_budget` or
`/review/explore_exploit`. The budget defaults to 2. A declared split is
`{"exploit": n, "explore": m}` with nonnegative integers summing to the budget. The default
rounds the exploit half down and gives the remainder to exploration. Exploit attempts staff
`research-evolver` on promoted mechanisms; explore attempts staff `research-explorer` on
untried seeds or limitations. An inconsistent split refuses derivation, so the gate refuses.
The point's `budget_split` is the record for the round's `resource_ledger` reservation.
