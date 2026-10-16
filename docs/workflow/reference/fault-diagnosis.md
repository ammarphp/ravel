# Diagnose, test and verify a correction

Use `ravel.workflow.diagnosis_repair` to connect existing diagnostic evidence to
a controlled correction. These helpers prepare and inspect work; they grant no
approval and launch no scientific processes. Machine proposals remain distinct
from human approval. Existing custody, review, execution and delivery gates apply.

1. Read actual comparison records. `cutflow_discrepancies` retains failed or
   missing cutflow rows; `residual_discrepancies` calls the existing above-noise
   attribution check. Supply the source-to-graph-node mapping. An attributed
   term remains a diagnostic observation, not an established physical cause.
   `first_divergence` compares independently computed stage quantities in an
   explicitly supplied causal order.
2. Call `rank_discrepancies` with the requested quantity's identity and unit.
   A cutflow residual or inverse-yield approximation is never promoted to a
   final-quantity bound. A supplied enclosure needs separately pinned evidence;
   endpoint sensitivity remains unbounded. Unknown effects stay visible ahead
   of known bounds, which sort by decreasing maximum absolute effect.
   Enclosures are labelled supplied, not certified.
3. Call `prepare_experiment` with the discrepancy and an ordinary constructive
   contrast request. Freeze rival predictions, the matched population, fixed
   artifacts, comparison, precision and stopping rule before acquiring results.
   `evaluate_experiment` recomputes the diagnostic result from pinned evidence.
   Unresolved evidence, nondiscriminating rivals and a frozen action to revise
   the hypothesis cannot select a correction.
4. Materialize the isolated corrected source separately. `prepare_correction`
   binds its before/after bytes and changed nodes to the measured controlled
   alternative. It still requires review; byte agreement does not prove runtime
   source consumption or semantic validity.
5. `request_rework(..., revised_spec=...)` uses ordinary graph revision, requires
   exactly the corrected nodes to change and binds their original and corrected
   source inputs. The revision checks the exact predecessor state before mutation.
   Omitting `revised_spec` requests invalidation only. Rework budgets and refusals
   for active or ambiguous calls remain intact. Execute the reviewed successor
   through the ordinary admitted workflow.
6. `verify_rerun` checks fresh completed receipts for affected descendants,
   unchanged receipts for other nodes and the actual final-node quantity against
   a separately pinned reference. It reconstructs the descendant population and
   complete dispatch requests, checks the accounted call population and metadata,
   and rereads source and receipt bytes before reporting the quantity.
   It also replays the measured correction and checks the retained predecessor
   specification after reading the final quantity and reference.
   A pending rerun or old result earns no
   completion credit. Scientific acceptance and source-consumption review remain
   separate obligations.

## Finite fault evaluation

The evaluation contains nine one-setting faults with matched correct controls:
cards, selection equality, omitted/repeated normalization factors, unit
conversion, bin permutation, stale control template, omitted likelihood channel
and an inference scale error. Each study includes signed event weights, a cross
section with units, selections, templates and a known-background likelihood.
The independent reference reconstructs the supplied rules using decimal weight
sums and a separate root solver. No generator or external model is needed.

```sh
python -m ravel.validation.fault_injection --out /path/to/new-evaluation
```

The command writes `scores.json`, per-case `score.json` files and graph receipts.
The seven scores are detection, first affected stage, discriminating test, repair,
affected-descendants-only rerun, corrected conclusion and untouched control.
Scores come from interventions and receipts; asserted success earns no credit.
The complete population and per-class denominators remain in the report.
Each proposal arm is attempted independently. A refused request is retained in
`proposal_errors`; it cannot suppress evaluation of the matched arm through call
ordering. Existing evaluation directories refuse reuse, including disjoint fault
subsets, so a later report cannot replace an earlier population.
These controls establish neither physical accuracy nor statistical coverage.

`--fault ID` restricts the declared population and may be repeated. The command
runs the deterministic proposer. `evaluate_case` and `evaluate_suite` accept a
caller-supplied proposer callable that sees only the synthetic contract and
artifacts, never the planted label or scoring key; sample and control call order
is randomized per paired evaluation. No host transport or model dispatch path
ships with this evaluator: a model proposal arm needs a registered graph and role
admission first.

## Routine counterexamples

`ravel.physics.routine_counterexamples.generate_boundary_events` creates a
complete bounded population from a supplied reconstructed event and independently
specified thresholds, overlap radii and flow edges. Cases include binary64
neighbors and equality, multiplicities, empty collections, ordering ties, signed
weights and visible collinear/charge configurations. Truncation refuses and
domain-exterior cases are recorded. Truth decay histories and exhaustive
combinations are outside this reconstructed-object contract.
Supplied numbers outside finite binary64 representation receive a domain refusal,
including integer inputs too large to convert.
Opt-in `pairwise_edges=True` adds all nine adjacent/equal combinations for each
distinct pair of supplied scalar threshold or flow targets. It does not combine
multiplicity or overlap factors, and insufficient bounds refuse the whole
requested population.

Supply an `IndependentOracle` reconstructed separately from source rules or an
expert check. Its callback receives only an event; it must not replay or inspect
the candidate implementation. The source pin authenticates declared source,
not authorship or independence. Review those independently. A direct interpreter
replay refuses; Python introspection cannot exclude a dishonest wrapper.

`routine_candidate.check_counterexamples` reloads the existing contract and
reruns the **entire original population** before all supplementary cases.
Repairs retain exact parent-feedback requirements. `minimize_disagreement` tries
bounded chunk deletions across collections, individual deletions and
simplifications, reevaluating both sides and preserving
the original disagreement. Exceptions are refusals; local reduction is not a
global minimum. All original failures and event bytes remain visible.
Supplementary success changes no candidate disposition and never replaces the
full regression population after a fix.
Any observed original or supplementary failure retains failed status even when
another supplementary case is refused; the refused case remains in the report.
