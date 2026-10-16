# The research loop

Open-ended questions, method studies, anomaly searches, reproductions and reinterpretations all bind one
research protocol. For a search, the loop turns hypotheses into experiments, compares each experiment with a
baseline under a rule fixed in advance, selects candidates on one part of the data and confirms them on a part
withheld from selection. A plain reproduction or reinterpretation, with no search, calibration or selection
declared or observed, skips the candidate-search and confirmation stages. Every trial, failed or not, stays in
the record, and code computes when the loop stops.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/methodology-research-loop.svg">
  <img src="../figures/svg/light/methodology-research-loop.svg" width="100%" alt="The research loop. Sealed hypotheses from two independent idea streams enter a register. Experiments run in stages: a baseline, a screen on adaptive screening cells, a full evaluation on adaptive full cells, a committed selection, a confirmation on withheld cells with fresh seeds, then ablations and objection tests. Each comparison against the baseline yields a gain interval that a fixed rule maps to better, equivalent, worse or unknown. Code stops the loop on the target number of successes with family coverage, the round limit or the budget. Critique, acceptance, meta-review and integrity stages follow, and objections return work to experiments.">
</picture>

## Terms

- **Hypothesis.** A statement with categorical predictions, a kill condition and a family. Its state is kept in
  the *register*.
- **Hypothesis family.** A named group of related hypotheses. The stop rule lists the families, and its
  coverage floor counts how many of them have a full evaluation.
- **Candidate.** A method under test, defined by a map of named components and the scientific inputs it holds
  fixed. A seed candidate is generation 0; each revision is the next generation of its parent, up to 8.
- **Cell.** One unit of evaluation: a population (a pinned dataset or event sample), a normalization, a metric
  and its unit, and an *exposure*.
- **Fidelity.** How completely a cell reproduces the final evaluation; each cell records its fidelity as text.
  A screening cell runs on a declared subset and cannot claim full fidelity; a full-fidelity cell is the
  evaluation that selection and the stop rule count.
- **Exposure.** The role a cell's data plays: `adaptive_screen` (cheap screening), `adaptive_full` (full
  fidelity, used to select) or `withheld_confirmation` (read after selection is committed; each withheld
  population is consumed once).
- **Stage.** An experiment on one candidate over a set of cells, with a *purpose*.
- **Comparison.** Two stages over the same cells, judged by a rule declared before the data are seen.

## The protocol

Binding the research protocol is mandatory for research, method-study, anomaly-search, reproduction and
reinterpretation requests. The default protocol has nine stages, each with its agent roles and a review-round
limit. Stages complete strictly in order, and code alone decides whether a stage is not applicable: a plain
reproduction or reinterpretation skips ideas, screen, validate and critique to experiments unless a search,
calibration or selection is declared or observed.

| # | Stage | Roles | What it produces |
|---|---|---|---|
| 1 | Limitation census | limitation census, sufficiency verifier | Flaws and approximations of the reference method, with testable signatures |
| 2 | Ideas | two idea proposers, novelty scout | Two independent idea streams, one citation-led and one speculative |
| 3 | Baseline | baseline producer, comparative reviewer | Three columns: our result, our reproduction, the published result |
| 4 | Screen | screen producer, plan critic | Promote, discard or engineer each idea on a declared subset |
| 5 | Validate | research evolver, comparative reviewer | Evolution rounds, committed selection, withheld confirmation, the stop |
| 6 | Critique to experiments | rebuttal planner, skeptical verifier | One discriminating experiment per concern |
| 7 | Acceptance | ablation critic, skeptical verifier | Claims, with mechanism gains attributed by ablation |
| 8 | Meta-review | research meta-reviewer | An independent review of every claim and every failed trial |
| 9 | Integrity | integrity auditor | Fresh re-execution, reference checks, paper-versus-code alignment |

The two idea proposers work in separate contexts; neither sees the other's proposals until both finish.
Before any experiment, a *preregistration* records the approximations, the expected effect, and the evaluators
that will judge the result (limit setting, likelihood building, cutflow comparison), each pinned by digest or
marked inapplicable with a reason. Novelty orders ideas; it never accepts a result.

## Hypotheses

Hypotheses enter through a sealed board. Each participant first commits the digest of its proposals, then all
participants reveal; follow-ups and posts open after every initial reveal. The board is a hash-chained
journal. Posts are typed (hypothesis, prediction, rival, evidence request, finding, refutation, question) and
cannot carry a status, a vote or an approval.

Code alone moves a hypothesis between states, from evidence it reads in the run:

| Evidence | New state |
|---|---|
| A registered comparator finds the prediction matches | survived test |
| The comparator finds it differs | prediction mismatch |
| It differs and a sensitivity check passes | rejected within the tested scope |
| The comparator cannot decide | inconclusive |
| The experiment fails to execute | execution failure (never counted as a refutation) |
| The budget for the hypothesis is spent | parked |
| A declared reopening condition is met | reopened |

A rejected hypothesis keeps the scope of the test that rejected it. It returns with a changed
signature or a satisfied reopening condition.

## Staged experiments

Each stage has one of six purposes. Code checks that every stage reads the exposures its purpose permits;
withheld cells are reserved for confirmation. The purposes do not impose one global order: each experiment
waits for its declared prerequisites and exposure gates, a confirmation waits for the committed selection, and
an ablation or a full experiment after a computed stop needs a recorded decision to continue.

| Purpose | Reads | Rule |
|---|---|---|
| `baseline` | adaptive | The reference every candidate is compared with |
| `screen` | adaptive screen | Requires an R1 decision before launch; cannot claim full fidelity |
| `full` | adaptive full | The results that count toward selection and the stop |
| `confirm` | withheld confirmation | After the selection is committed; each withheld population is consumed once |
| `ablation` | adaptive | Changes exactly one component of its parent: remove, replace or add |
| `objection_test` | adaptive | Answers a registered objection; runs outside the computed stop |

**Separation of selection and confirmation.** A confirmation cell differs from every selection cell in
population digest, seeds and generation. The selection is committed before any withheld read, with its rule
(direction, metric, the number *k* of candidates to keep and the significance level *α*), the full trial count *N*
including failures, and every candidate's value. A candidate's value is the mean over its full-fidelity trials,
never its best seed; a candidate with any failed or unresolved full trial is ineligible. Each withheld
population is consumed once in a ledger shared across the study, and a failed dispatch still spends it. A
selected candidate can receive further confirmation reads when their cells, seeds and generation are disjoint
from its earlier reads. With several selected candidates, noisy confirmations are corrected with the Holm
step-down procedure at level *α*; a rule that declares an exact, noise-free confirmation measurement can use a
deterministic threshold instead. If no candidate confirms, the report says so: a *null funnel*.

**Ablations.** An ablation keeps the parent's fixed inputs and changes exactly one named component. A claim
that a mechanism causes a gain requires an arm that lacks the mechanism, generic controls held
fixed, and attribution by the ablation critic. *Generic controls* are everything except the mechanism under test:
the candidate's held scientific inputs and its other components. Code refuses an ablation that changes them, so
the gain is attributed to the mechanism alone.

## Decisions

A comparison rule fixes, before any result is read, the metric and unit, the direction (minimize or maximize),
a minimum gain *g*, a tolerance *t* and how uncertainty enters (deterministic values, or supplied intervals).
For each cell the gain interval of candidate L over baseline R is

$$
\text{maximize: } [L_\text{lo} - R_\text{hi},\; L_\text{hi} - R_\text{lo}], \qquad
\text{minimize: } [R_\text{lo} - L_\text{hi},\; R_\text{hi} - L_\text{lo}],
$$

For a recorded same-event evaluation with an actual joint covariance and an explicit
symmetric interval multiplier *k*, use the oriented central difference ±
$k\sqrt{\operatorname{Var}(L)+\operatorname{Var}(R)-2\operatorname{Cov}(L,R)}$.
The covariance must belong to the paired coordinates, including retained event-group
covariance when available. Missing covariance or unrecorded pairing keeps the marginal
construction above; neither covariance nor an interval prescription is inferred.

The cell's claim decision is

| Decision | Condition on the gain interval [a, b] |
|---|---|
| better | a > g + t |
| worse | b < −t |
| equivalent | \|a\| ≤ t and \|b\| ≤ t |
| unknown | otherwise, or a value, interval or quality flag is missing |

Over all cells, the comparison is *equivalent* if every cell is equivalent, *better* if every cell is better or
equivalent, *worse* if every cell is worse or equivalent, and *unknown* otherwise. A trade-off between cells is
therefore unknown, never averaged away. Every decision rests on the recorded values; code recomputes it before
any stage that requires it runs.

Search retention is reported separately as a Pareto frontier over all declared
cell objectives. A candidate leaves the search when another has a nonnegative gain
lower bound on every objective and a lower bound above the rule's tolerance on at least
one. Trade-offs, overlapping uncertainty and missing objectives retain both candidates.
Frontier membership never establishes uniform improvement or authorizes a claim.
Candidate claim preferences recompute each possible winner's cell gains against
the retained minimum gain and tolerance. A loss beyond tolerance alone does not
establish that the other candidate clears the stricter improvement threshold.

An optional `objectives` list in the staged protocol can declare a narrower or
multiaxis conclusion before any affected execution evidence exists. Existing
protocols keep the whole-cell decision and claim rules above. Each objective
declares its `id`, `kind`, literal `scope`, exact `cell_ids`, and `requirements`.
Each requirement binds a `comparison_id`, a subset of its `cell_ids`, a
`preferred_candidate`, an `axis`, and explicit `allowed_decisions`. The named
cells must equal the union of those requirements. The complete ordinary
comparison still executes and is recomputed; an objective does not remove its
other cells or alter its global decision.

| Objective kind | Permitted conclusion |
|---|---|
| `regional_improvement` | Nonworsening performance in every named cell, with a strict gain in at least one; evidence stays within the named cells |
| `uniform_improvement` | The same condition, with every full stage cell of both participating candidates covered |
| `cost_accuracy` | Separate supplied cost and accuracy metrics meeting each declared outcome constraint; regressions can be explicitly permitted as a tradeoff |
| `complementary_portfolio` | At least two candidates assigned to separate named regions, all assignments nonworsening and each member strictly better in at least one assigned cell |

Improvement and portfolio requirements use the `performance` axis; their
permitted outcomes are `better` and `equivalent`. Cost and accuracy use distinct
`cost` and `accuracy` axes and distinct supplied metrics; the cost rule minimizes
cost. Their intervals and decisions remain separate. There is no implicit cost
weight, score, predictive law, or statistical combination of portfolio members.
Screening and withheld cells cannot enter these adaptive objective declarations.
Missing or ambiguous evidence leaves the declared objective unresolved and
retains every named candidate, including complementary members. Existing
search-frontier rules and periodic exploration continue independently.

Status reports type each conclusion by kind, exact scope and cell census, with
one evidence row per requirement cell. Supported conclusions are labeled
`supported_in_declared_scope`; unmet constraints are `requirements_not_met`;
incomplete evidence is `unresolved`. None authorizes a claim, extrapolation or
combined likelihood. Selection exposes the declarations and preserves its
existing ranking. Advisory allocation retains their candidate options without
scalarizing cost and accuracy.

A new claim can opt into these conclusions with `objective_ids`. Its comparison
identities must exactly match the objectives' comparison requirements, and its
stage obligations must include both complete operands. Its status exposes the
exact typed conclusion scopes. This permits a regional reporting obligation
when the whole comparison is a tradeoff; it does not fulfill a separately
required whole-comparison decision or an original uniform reporting obligation.
Ordinary source custody, acceptance scope, premise freshness, review and
objection requirements still apply. Bound objective rows and claim bindings
cannot be rewritten to match observed outcomes.

Experiment allocation defaults to guaranteed eliminated hypothesis classes per
worst path cost, abstaining at zero gain. The selectable `expected_information`
policy instead maximizes expected mutual information about the distinct classes
per expected path cost. It requires a pinned, source-backed predictive model or
calibrated record supplying the joint class/outcome law for every experiment;
agent confidence is inadmissible. Adaptive outcomes are conditioned on that law,
without assumed independence. The report records the policy, evidence and choice
reason; both policies remain advisory.

## Evidence and judgement

Completing a stage requires its full report and the receipts of every role it names, and each role must have
been shown the stage evidence. Screening, promotion and selection each need a [decision
justification](decision-justification.md) receipt: R1 to screen, R2 to promote or select, R3 for a claim of
method performance. Critique findings and verifier requests become items in the evidence queue: evidence goes to
an investigation worker, experiments to this loop, clarifications to the physicist at the next check-in. A
concern closes when its registered experiment has run and been reviewed. A meta-review objection can
request more evidence or revise a candidate or premise; a revision invalidates the stages that depend on it.

## Stopping

The preregistration declares a stop rule: a target number of successes, a coverage floor over hypothesis
families, a maximum number of rounds and a budget. A success is a distinct candidate whose full evaluation
succeeded with decision *better*. After each observed full evaluation code checks, in order:

1. **successes**: the target is reached and the coverage floor is met;
2. **max rounds**: the round limit is reached and every full experiment in that round is observed;
3. **budget**: the observed cost reaches the budget.

A success or budget stop can therefore fall within a round; the round-limit stop waits for the round's full
experiments. A full experiment of a later round waits until every earlier round is observed.

If the loop stops below the coverage floor, the reason is recorded as *coverage unmet* and the report is a null
funnel. A further round after a computed stop needs an R2 decision that names the old stop and the new bounds.
The campaign also carries hard ceilings on model calls, output tokens, wall time, native attempts (one per
experiment) and 32 experiments.

## A worked example

The numbers below are synthetic. A study asks whether a new selection improves the expected 95% CLs upper
limit on a signal strength μ. The rule minimizes μ, with *g* = 0.05, *t* = 0.03 and supplied intervals: a cell
is *better* when the lower edge of its gain interval exceeds 0.08.

| Cell | Exposure | Baseline μ | Candidate μ | Gain interval | Decision |
|---|---|---|---|---|---|
| Low mass | adaptive full | 1.40 [1.36, 1.44] | 1.20 [1.17, 1.23] | [0.13, 0.27] | better |
| Mid mass | adaptive full | 0.95 [0.93, 0.97] | 0.82 [0.81, 0.83] | [0.10, 0.16] | better |
| High mass | adaptive full | 0.60 [0.59, 0.61] | 0.60 [0.59, 0.61] | [−0.02, 0.02] | equivalent |

The full comparison is *better*. With a stop rule of one success, a coverage floor of two families and four
rounds, the loop stops after round two, when this candidate and a second family have been evaluated. The
selection (*k* = 1, *N* = 7 trials, two of them failed) is committed. The confirmation then reads a withheld
cell with fresh seeds: baseline 1.10 [1.07, 1.13], candidate 0.95 [0.93, 0.97], gain [0.10, 0.20], *better*.
An ablation removes the new selection requirement and leaves everything else fixed; the ablated arm is
*equivalent* to the baseline on all three full cells, so the ablation critic attributes the gain to that
requirement. Had the mid-mass interval been [0.06, 0.14], that cell, and with it the whole comparison, would
have been *unknown*.

## Records

| Record | Contents |
|---|---|
| Campaign history | Immutable, hash-linked revisions of the campaign state and a head pin |
| `research/protocol.json` | The bound protocol, stage status, role receipts, preregistration and evaluator pins |
| `research/selection.json` | The committed selection: rule, *N*, every candidate's value, the selected set |
| Selection report | Confirmations, correction method, best-of-*N* value labelled optimistic, null funnel |
| Board journal | Commits, reveals, posts and code-written transitions, hash-chained |
| Protocol custody | Binding and preregistration events in a ledger outside the run |

Implementation: `ravel.workflow.research_protocol` (purposes, exposures, decisions, selection, confirmation,
stop), `ravel.physics.research_comparison` (the comparison rule), `research_cycle`, `research_evaluation`,
`hypothesis_board`, `research_board`, `evidence_queue`, and the stage table in
`src/ravel/data/research/protocol-default.json`.

## Glossary

| Term | Meaning |
|---|---|
| Ablation | A stage that changes exactly one component of its parent candidate |
| Candidate | A method under test: named components plus fixed inputs |
| Cell | Population, normalization, metric, unit and exposure |
| Coverage floor | The number of hypothesis families that must be evaluated before a success stop |
| Exposure | Screening, full or withheld use of a cell's data |
| Fidelity | How completely a cell reproduces the final evaluation; screening cells cannot claim full fidelity |
| Generic controls | The held inputs and other components an ablation keeps fixed |
| Gain interval | The range of improvement of a candidate over the baseline in one cell |
| Holm procedure | A step-down correction for testing several selected candidates |
| Hypothesis family | A named group of related hypotheses; the coverage floor counts families |
| Null funnel | A report in which no candidate confirmed or coverage was unmet |
| Preregistration | Approximations, expected effect, evaluators and the stop rule, fixed before experiments |
| Withheld confirmation | A read of data unused in selection, with fresh seeds; each withheld population is consumed once |

See also the [RAVEL glossary](../reference/glossary.md), the [agent architecture](agent-architecture.md) and
[Recursive Decision Justification](decision-justification.md).
