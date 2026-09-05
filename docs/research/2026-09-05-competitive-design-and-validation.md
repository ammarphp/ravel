# Competitive design review and prospective validation protocol

Date: 2026-09-05. This is a source audit and a proposed experiment, not a claim
that Ravel outperforms another system. No agent benchmark or heavy simulation was
run for this document. No external source code was copied into Ravel.

Ravel's next substantial gain should be demonstrable reliability: completing
supported scientific requests, identifying unsupported ones for specific reasons,
preserving the numerical and physical meaning of results through failures, and
doing so with less human rescue. Additional instructions or more specialist
agents are candidate mechanisms, not evidence that this has happened.

## What was inspected

The local development baseline at the beginning of this review was
`b7b07de4665a02ff4c3cad3b1964f75bfc17a1e3`. Concurrent hardening work is outside
that snapshot; any experiment must freeze the final evaluated commit separately.
Local authorities inspected were `AGENTS.md`, `DIRECTORY.md`,
`docs/development/status.md`, `docs/development/history/mission-and-plan.md`,
`docs/reference/failure-modes.md`, and `docs/research/routing-evaluation.md`.

Fresh shallow clones, rather than old working copies or the pasted critique,
established these external revisions. The GitHub connector independently located
the Collider-Bench revision; repository files and the paper were then read.

| Source | Exact inspected revision | Commit timestamp |
|---|---|---|
| [Collider-Bench](https://github.com/dfaroughy/Collider-Bench/tree/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c) | `2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c` | 2026-09-02 12:00:13 -07:00 |
| [Just Furnish Context](https://github.com/jfc-mit/jfc/tree/9eecb0e0b4c95c362053ad6b121760b47379bc54) | `9eecb0e0b4c95c362053ad6b121760b47379bc54` | 2026-03-31 13:47:43 -04:00 |
| [ColliderAgent](https://github.com/HET-AGI/ColliderAgent/tree/1140f39e8730889422a64a141fbd3ca10529e13b) | `1140f39e8730889422a64a141fbd3ca10529e13b` | 2026-05-11 20:49:27 +08:00 |
| [MadAgents](https://github.com/MadGraphTeam/MadAgents/tree/df241214d1e4a66b1f9964aa33dd2342b7084b9a) | `df241214d1e4a66b1f9964aa33dd2342b7084b9a` | 2026-08-06 14:56:20 +02:00 |
| [SFitterAgents](https://github.com/heidelberg-hepml/SFitterAgents/tree/c52ce2ba90e5ee089429d8cdce5762498a401573) | `c52ce2ba90e5ee089429d8cdce5762498a401573` | 2026-08-19 21:47:30 +02:00 |

Paper identity matters: [arXiv:2607.22813v1](https://arxiv.org/abs/2607.22813v1)
is *Agentic Re-Casting using Agentic Re-Simulations*, by Diefenbacher, Plehn,
Schiller, and Schmal. It discusses MadAgents.v3 and SFitter agents. It should not
be cited as FERMIACC or as the ColliderAgent paper. The arXiv submission record
reports 2026-07-24; the rendered HTML itself carries an August 24 date. Record
the version identifier, not an inferred chronology from that typeset date.

## Architectural lessons and boundaries

### Collider-Bench: separate task fidelity from provenance

The pinned benchmark defines reproduction tasks, constrained output templates,
public simulation tools, and numerical yield comparisons. Its sandbox contract
withholds hidden reference/evaluator directories; the unsandboxed backend is
explicitly unsuitable for scored runs. Numerical scoring tracks output coverage,
while the judge rubric separately audits whether submitted values came from the
agent's actual work. The rubric allows recovery only from that work, not from
the hidden answer. See the pinned
[README](https://github.com/dfaroughy/Collider-Bench/blob/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c/README.md),
[sandbox contract](https://github.com/dfaroughy/Collider-Bench/blob/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c/agent_runtime/SANDBOX.md),
[scorer](https://github.com/dfaroughy/Collider-Bench/blob/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c/ColliderBench/Evals/score.py), and
[judge rubric](https://github.com/dfaroughy/Collider-Bench/blob/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c/ColliderBench/Evals/judge_rubric.md).

Ravel inference: publish separate fidelity, completeness, and claim-support
outcomes. A close answer does not prove a valid derivation. Keep the originally
submitted artifact immutable and report any independently recovered result as a
secondary outcome. Benchmark-native yield reproduction is narrower than Ravel's
full analysis-to-exclusion lifecycle, so a shared task subset is required for a
head-to-head comparison. Public answers may already appear in model training;
filesystem isolation alone cannot eliminate that contamination.

### JFC: review must trace causes upstream

JFC specifies distinct execution and review roles, evidence-bearing reviews,
phase regression when upstream choices invalidate downstream work, and staged
data access with a human gate. Its review instructions ask whether a comparison
is informative, whether uncertainty hides problems, and whether limitations were
accepted too quickly. This is substantive scientific-review design, not merely
a list of roles. See the pinned
[root orchestration template](https://github.com/jfc-mit/jfc/blob/9eecb0e0b4c95c362053ad6b121760b47379bc54/src/templates/root_claude.md),
[review protocol](https://github.com/jfc-mit/jfc/blob/9eecb0e0b4c95c362053ad6b121760b47379bc54/src/methodology/06-review.md), and
[blinding protocol](https://github.com/jfc-mit/jfc/blob/9eecb0e0b4c95c362053ad6b121760b47379bc54/src/methodology/04-blinding.md).

Ravel inference: the review panel should identify the earliest invalid artifact,
invalidate dependent results, and demand regenerated evidence at those stages.
Multiple fresh reviewers are useful only if their access and questions prevent
shared assumptions from passing unchallenged. The inspected instructions do not
by themselves establish runtime enforcement, independent accuracy, or benefits
per dollar. Its measurement/search workflow also differs from a recasting-only
task. Those are experiment-design constraints, not a negative verdict on JFC.

### ColliderAgent: explicit boundaries and incremental dependency reuse

ColliderAgent separates skills/agents from Magnus execution blueprints. Its
orchestrator records run labels and parent runs, describes when upstream
artifacts can be reused, and requires updated scripts and downstream execution
when parameters change. It spans model construction through simulation and
analysis; generic end-to-end agentic phenomenology is therefore not a distinctive
Ravel claim. The pinned README still lists MA5 expert mode and fine-grained
package tuning as roadmap items. See its
[README](https://github.com/HET-AGI/ColliderAgent/blob/1140f39e8730889422a64a141fbd3ca10529e13b/README.md),
[orchestrator](https://github.com/HET-AGI/ColliderAgent/blob/1140f39e8730889422a64a141fbd3ca10529e13b/src/skills/pheno-pipeline-orchestrator/SKILL.md), and
[blueprints](https://github.com/HET-AGI/ColliderAgent/blob/1140f39e8730889422a64a141fbd3ca10529e13b/src/blueprints/README.md).

Ravel inference: make cache reuse conditional on the complete scientific input
fingerprint, including model/card/tool versions and statistical basis, and record
why an artifact was reused. Protocol changes should invalidate exactly the
affected descendants. This source inspection did not execute Magnus or certify
its deployment; README maturity statements are not a live availability test.

### MadAgents/SFitter: probe successful-looking mistakes

The paper's consultant design emphasizes checking installed-source behavior and
runtime probes for configurations that run but encode the wrong physics. It
also discusses the cost/context losses of unnecessary worker delegation. Its
repeatability appendix describes multiple pseudo-datasets with physicist-driven
agent runs, so those experiments are not evidence of unattended self-drive.
These are claims in [the paper, sections 3.1 and appendices B–C](https://arxiv.org/html/2607.22813v1),
not independently repeated results here.

The pinned [MadAgents README](https://github.com/MadGraphTeam/MadAgents/blob/df241214d1e4a66b1f9964aa33dd2342b7084b9a/README.md)
describes generated runtime variants and source-grounded memory. The linked
[SFitterAgents tree](https://github.com/heidelberg-hepml/SFitterAgents/tree/c52ce2ba90e5ee089429d8cdce5762498a401573)
contains only README and LICENSE at this revision and announces a future public
release. It cannot currently serve as a runnable public end-to-end baseline.

Ravel inference: invest in small falsification probes before longer runs, retain
source-location memory with fresh verification, and reserve specialist calls for
questions whose error or uncertainty warrants their cost. The project already
has analogous mechanisms; the novel question is whether their enforced coupling
improves useful scientific delivery.

## Local failures define the priority order

The local catalogue contains enough negative evidence to reject confidence based
solely on green mechanism tests. The following are incident-driven priorities,
not assertions that every listed defect remains open today.

| Failure evidence | Required adversarial test | Success criterion |
|---|---|---|
| `FAILURE-CATALOGUE.md` A3/A4: expected/observed and cross-section basis mismatch | Supply plausible numbers on an incompatible basis, with a correct control twin | Wrong-basis claim is blocked or explicitly relabeled; correct basis proceeds |
| A6: unsupported agreement prose | Deliver an agreement sentence with missing, stale, or contradictory comparison evidence | Independent scorer can identify the exact supporting artifact and tolerance, or the claim is withheld |
| B1 and C7: limit floor/harvest/rebase failures | Feed floored limits and absent normalization after a repaired stage | Bounds remain bounds; no numeric interpolation or comparison promotes them to measurements |
| B2/C1/C3: wrong configuration or empty output despite exit zero | Mutate run options, remove decay branches, or return success with no events | Scientific postconditions fail before expensive downstream work; valid paired cases pass |
| C6: disk exhaustion/orphaned stages | Inject a disk-budget failure and truncated output in a sandboxed stub | Terminal failure is recorded once; restart consumes a fresh valid artifact; cleanup preserves evidence |
| D3: cold routing failed at the workspace parent | Start at the documented workspace parent without an injected directory hint | Correct entrypoint is found before physics work; ordinary development tasks are not misrouted |
| D4–D18: stalled drive, recovery, changing protocol, incomplete delivery | Interrupt, resume, change upstream evidence, and inspect surviving downstream state | No stale result is served; next action and reason for any block remain explicit |
| N7/N9: premature blocking and enforcement disarm | Present a recoverable resource gap; separately attempt to disable a live guard | The first gets a bounded repair attempt; the second does not bypass the serving boundary |

The routing record deserves special care. `docs/research/routing-evaluation.md` says the
7/7 historical success used an injected working-directory hint, and that one
subject read an expected-verdict row. It records an unhinted spot-check as 1/2
because the second assignment did not run, plus a later individual P4 check. A
full cold unhinted cohort is still the stated re-evaluation condition. Do not
combine these into a new success rate or substitute them for full self-drive.

Likewise, `PLAN-OF-RECORD.md` distinguishes completing a 2-D scan from proving a
fresh agent can drive the workflow without operator rescue. Replaying a saved
artifact, firing a guard on a fixture, routing a prompt, and completing a new
scientific analysis are four different demonstrations. Preserve those labels.

## Prospective crossed protocol

This protocol is written before new scored outcomes. It is **not yet an
externally registered experiment**. Before starting a campaign, freeze its exact
task prompts, oracles, model/runtime settings, environment, budgets, ordering,
and code revision using the registry below, and place that record under an
independent timestamp or release. An outcome-dependent rewrite requires a new
campaign identifier; the original cohort remains reportable.

### Estimand and arms

Question: within a declared task distribution and fixed resource budget, does
Ravel's enforcement reduce unretracted unsupported scientific claims while
preserving useful completion, appropriate refusal, and numerical fidelity?

Use a 2×2 factorial design with the same underlying physics utilities, model,
runtime, data access, base interface contract, and operator safety limits:

| Arm | Ravel governance instructions | Ravel experimental enforcement |
|---|---|---|
| Baseline | Absent | Absent |
| Instructions | Present | Absent |
| Enforcement | Absent | Present |
| Full | Present | Present |

The baseline still receives ordinary task/tool documentation. The enforcement
arm receives the minimal schema/API contract needed to operate tools. Record
every unavoidable instruction emitted by a failing gate as treatment exposure.
If enforcement cannot be separated from the instructions without making an arm
unusable, report that identification limitation; do not label a three-arm
comparison a completed factorial design. Implement treatment removal only in
isolated experiment copies. Operator approval, resource ceilings, and host
permissions apply equally in all arms and are never ablated.

Predeclare contrasts: Full minus Instructions estimates the added effect of
enforcement given instructions; Full minus Enforcement estimates the added
effect of instructions given enforcement; `(Full − Instructions) −
(Enforcement − Baseline)` estimates interaction on the chosen rate scale. They
become causal estimates only under actual assignment, faithful arm delivery,
comparable exposure, and adequate independent replication. The supplied scorer
reports descriptive per-arm results; it does not perform those inferences.

### Cohort, isolation, and exposure

Use separate strata for routing, artifact-level fault recovery, statistical
replay, and full end-to-end physics. Do not pool these into a readiness number.
Start with bounded routing/replay/fault tasks before authorizing generated-event
campaigns. Every stratum includes supported completion controls and verified
refusal controls. Each injected failure has a nearby valid twin to expose false
blocks. Include new analysis families and negative development-routing controls,
not just the historical examples that informed the guards.

Choose the full task roster and repeat count before results; determine a serious
sample size from a precision or power target before making comparative claims.
A small initial campaign is explicitly a feasibility pilot. Repeat seeds form
paired task blocks across all four arms; randomize arm order with the registered
schedule seed. Record whether the provider actually exposes seed control.

Every subject starts fresh with no previous trial transcript, expected verdict,
answer artifact, personal memory, or scorer directory. For cold routing, launch
at the actual documented workspace parent with no injected project hint, while
keeping the ordinary shipped router available. Record the exact visible file
manifest, mount boundaries, cwd, environment, and prompt. Do not run subjects
inside the mutable development checkout or give them access to other arms.
Hash public source documents and record retrieval/network failures. Treat
discoverable public answers and likely training contamination as a separate
limitation; holdout scenario mutations reduce but cannot prove absence of it.

Freeze token/cost/wall-time budgets, retry limits, tool versions, environment
images or native manifests, and the intervention policy. Include installation
and review costs in the declared accounting boundary, or report them separately
with their own denominators. Do not let one arm silently receive rescues or
preinstalled prerequisites unavailable to the others. Expected human plan
approval follows the same scripted rule in every arm and is recorded separately
from substantive rescue; a physicist correction to a model, card, or procedure
is intervention, even when it arrives in a friendly check-in.

### Outcomes and independent scoring

The primary failure indicator is an unretracted, materially unsupported
scientific claim in what was delivered to the user. Score the entire delivered
trajectory, not merely the last sentence: an early wrong limit does not disappear
because the session later crashes. A clearly retracted draft remains a recorded
incident but is distinct from a silently invalid delivered conclusion. A failed
guard probe by itself is not a delivered scientific claim.

Report concurrently:

1. Unsupported-claim count per **all assigned runs**, with unknown judgments
   explicit and worst/best missingness bounds.
2. Verified useful completions per all assigned supported tasks. A zero-invalidity
   policy that refuses everything has zero useful completion.
3. Valid refusals per all assigned refusal controls, plus refusal rate on
   completion controls. A valid refusal names and verifies the concrete blocking
   resource or scope condition and explains the available next step.
4. Fidelity to a preregistered independent oracle, in declared units and basis.
   Use expected/observed consistently, record MC precision, preserve limits as
   bounds when appropriate, and predeclare treatment of zero references.
   A tolerance is frozen before seeing the candidate answer. Never fit a
   correction factor to the held-out answer to earn a pass.
5. Human interventions, API/model and compute cost, elapsed time, retries,
   recovered failures, and remaining missing outputs. Show both totals and
   denominators. Do not quote survivor-only fidelity without completion coverage.

Assign terminal states `completed`, `refused`, `timeout`, `crash`, or
`not_started` to every roster entry. Retry within the registered budget belongs
to that original assignment and retains all earlier evidence/cost. Extra retries
or post-hoc repairs are a separately labeled secondary cohort. Infrastructure
outages are recorded in the main cohort; a predefined sensitivity analysis can
exclude objectively exogenous outages, with the full original denominator shown.

Mechanically replay numerical oracles where possible. Independently score claim
support and refusal quality from immutable artifacts and transcripts; the
executor must not adjudicate itself. Blind reviewers to arm labels where
feasible and record when gate messages make blinding impossible. Two independent
reviewers score a prespecified subset or the whole cohort, report agreement and
disagreements, and adjudicate using a frozen rubric. No reviewer edits the
candidate output. Preserve original submissions and corrected secondary results
separately. Session IDs and SHA-256 fields provide traceability, not proof that
a reviewer was intellectually independent.

### Analysis and decision rules

Report counts, task-level outcomes, all denominators, missingness bounds, and
paired descriptive differences first. Do not treat multiple seeds of one task
as independent analysis families. For a later adequately sized study, predeclare
task-clustered uncertainty estimation and multiplicity handling for secondary
metrics. The current small utility deliberately supplies neither p-values nor
an aggregate leaderboard score.

Promotion requires fewer unsupported delivered claims **and** acceptable useful
completion, refusal specificity, fidelity, intervention, and cost under the
predeclared guardrails. If budgets are too small for useful completion in every
arm, the pilot establishes infeasibility at that budget, not superiority of the
arm that abstains fastest. A zero-failure pilot does not establish a zero-failure
system. Freeze and evaluate a later unseen cohort after fixing exposed failures.

## Implemented support and remaining work

The new [`framework/experiments`](../../benchmarks/governance/README.md) utility
creates the complete crossed roster, binds outcomes to it, rejects omissions,
duplicates, unplanned assignments, changed registry contents, self-scoring,
absent evidence digests, and nonfinite/invalid metrics. It keeps unknown
judgments and costs visible and separates useful completions from correct
refusals. Its tests use synthetic records only. It does not launch subjects,
enforce isolation, verify the bytes behind supplied hashes, or replace a physics
oracle. Those are explicit work items before a valid live campaign.

The credible long-term claim remains a hypothesis: an experiment-anchored,
artifact-bound lifecycle may improve the reliability of serving recast results.
The immediate path to supporting it is a frozen cold cohort with independent
scoring and complete failure accounting. A large instruction corpus, many green
fixture tests, and broad feature coverage are insufficient substitutes.
