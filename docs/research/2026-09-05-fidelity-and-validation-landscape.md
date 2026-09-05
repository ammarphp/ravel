# Physics fidelity and validation landscape

Ravel's strongest defensible direction is a workflow that makes scientifically
wrong but successful-looking calculations difficult to deliver. Its statistical
layer is a useful foundation, but current evidence does not establish superiority
over comparable tools. This review informs the accompanying implementation and
specifies what further comparisons would actually test that hypothesis.

Reviewed 5 September 2026. Repository heads were pinned through Git's remote
references; relevant documentation and examples were read without copying code.
The public Ravel starting point was `eed98d374b2ff660d378ed37ccc42bdd9090d307`;
the development checkout started at `b0e09467be0f0d38ff0e26369605051ada27fbd9`.

## Comparison identities

| Project | Reviewed revision |
|---|---|
| [MadAgents](https://github.com/MadGraphTeam/MadAgents/tree/df241214d1e4a66b1f9964aa33dd2342b7084b9a) | `df241214d1e4a66b1f9964aa33dd2342b7084b9a` |
| [ColliderAgent](https://github.com/HET-AGI/ColliderAgent/tree/1140f39e8730889422a64a141fbd3ca10529e13b) | `1140f39e8730889422a64a141fbd3ca10529e13b` |
| [Collider-Bench](https://github.com/dfaroughy/Collider-Bench/tree/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c) | `2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c` |
| [mapyde](https://github.com/scipp-atlas/mapyde/tree/7cc0afbb52283ea2a8f4375e4063227e8e2f9b8f) | `7cc0afbb52283ea2a8f4375e4063227e8e2f9b8f` |
| [pyhf](https://github.com/scikit-hep/pyhf/tree/f19891b2255b9d8327ad0a2fc1d3b49664afbd9d) | `f19891b2255b9d8327ad0a2fc1d3b49664afbd9d` |
| [cabinetry](https://github.com/scikit-hep/cabinetry/tree/0252deed24451e835570619d67e60a674034d9d5) | `0252deed24451e835570619d67e60a674034d9d5` |
| [CheckMATE](https://github.com/CheckMATE2/checkmate2/tree/b812999b2aebfb37b65e36ea0b408661940a0515) | `b812999b2aebfb37b65e36ea0b408661940a0515` |
| [MadAnalysis 5](https://github.com/MadAnalysis/madanalysis5/tree/20f2114b447c52b787ce32916ce9e44f990dd783) | `20f2114b447c52b787ce32916ce9e44f990dd783` |
| [SModelS](https://github.com/SModelS/smodels/tree/53a19a64c4c7d0bf3e9129d647091bba49c5e405) | `53a19a64c4c7d0bf3e9129d647091bba49c5e405` |

These are review revisions, not a claim that Ravel installs or interoperates with
all these packages. Ravel's tested replay dependency remains pyhf 0.7.6.

## Lessons that matter

**MadAgents: test silent physics failures.** The MadAgents paper describes
installation, interactive support, and autonomous generation; the separate
MadAgents.v3/SFitter study tests configurations that run successfully while
simulating the wrong request. Its five-question, ten-repetition table sums to
11/50 correct for the bare harness, 24/50 cold, and 27/50 warm. Warm still gets
0/10 on its SMEFT question. These are that study's model, tasks, and grading
conditions, not comparative Ravel scores. Relevant failure families include
conjugate decays, nested decays, fiducial cuts, off-shell windows, and perturbative
order/width consistency. The lesson for Ravel is to test process meaning and
stage-level observables, with repeated trials and retained failures. Sources:
[MadAgents v4](https://arxiv.org/html/2601.21015v4),
[MadAgents.v3/SFitter, Appendix B](https://arxiv.org/html/2607.22813v1).

**ColliderAgent: inspect what the prompt already supplied.** Its public examples
show substantial end-to-end physics workflows, but the U1 leptoquark prompt also
supplies the model, scan, detector settings, selections, experimental bins, and
inferential prescription. That example uses independent per-bin nuisances and a
profile-likelihood difference of four, summed across ATLAS and CMS. Ravel's
95% CLs calculation on an available published HistFactory workspace is a different
construction. A better-looking limit is not evidence one construction is more
accurate. Match data, signal, nuisance model, and target statistic before comparing
numerical results. Sources: [ColliderAgent paper](https://arxiv.org/abs/2603.14553),
[pinned U1 prompt, section 3.3](https://github.com/HET-AGI/ColliderAgent/blob/1140f39e8730889422a64a141fbd3ca10529e13b/paper-reproduction/1811.07920/prompt_figure_3.md).

**Collider-Bench: judge the yield vector independently.** Its tasks target
published binned signal yields and score relative L2 distance. The sandbox keeps
hidden references and evaluator code outside the agent's mounted surfaces. That
is a useful boundary for a prospective Ravel evaluation: development cutflows can
be transparent, while held-out evaluation references remain inaccessible to the
agent. Include timeout, invalid output, and missing-yield cases in the denominator.
Source: [Collider-Bench documentation](https://github.com/dfaroughy/Collider-Bench).

**mapyde: make the first calculation executable.** Its generation, simulation,
analysis, and inference chain illustrates why the public entry point needs a
worked configuration and installation route. Ravel already uses that tool ecosystem;
its contribution must be assessed in the workflow and evidence it adds. This pass
therefore restores practical README examples, adds a runnable draft initiation
command, and ships a repeatable plotting demonstration.
Source: [mapyde](https://github.com/scipp-atlas/mapyde).

**pyhf and cabinetry: expose the fit, not just its crossing.** pyhf is Ravel's
statistical engine, so agreement with it tests Ravel's integration, not independent
statistical superiority. cabinetry exposes named fit parameters, uncertainties,
correlations, nuisance impacts, likelihood scans, and optional saturated-model
goodness of fit. Ravel should make failed fits, active bounds, and unavailable
diagnostics explicit before adding more polished exclusion plots. This pass adds
root/fit accounting and input checks; complete pulls, covariance, impacts, and
coverage studies remain further work. Sources:
[pyhf upper-limit implementation](https://scikit-hep.org/pyhf/_modules/pyhf/infer/intervals/upper_limits.html),
[cabinetry inference and visualization API](https://cabinetry.readthedocs.io/en/latest/api.html).

**Established recasting tools: do not compare against an obsolete baseline.**
Current CheckMATE documents multibin fits, full and simplified likelihood routes,
pyhf/Spey integration, and HS3/XRooFit support. MadAnalysis 5 also supplies an
established event-analysis and recasting environment. SModelS offers a different
simplified-model interpretation route. Each is relevant to a different comparison;
none can fairly be reduced to an old single-bin counting baseline. Sources:
[CheckMATE installation and multibin options](https://github.com/CheckMATE2/checkmate2),
[MadAnalysis 5](https://github.com/MadAnalysis/madanalysis5),
[SModelS](https://github.com/SModelS/smodels).

## What changed as a result

The [implementation report](../development/history/2026-09-05-physics-fidelity.md)
and linked audits give the measured results. The work separates three mechanisms:

| Layer | Implemented experiment or safeguard | Interpretation |
|---|---|---|
| Physics definition | Compare the eRJR boost expression with the ATLAS paper; replay identical retained events with only that expression changed | A causal implementation comparison; the remaining acceptance deficit is still a failure |
| Numerical inference | Refine CLs crossings and report their status; reject invalid counting inputs and invalid fits | Numerical correctness, not a coverage or calibration claim |
| Evidence interpretation | Refuse missing or incomparable driving acceptance data; aggregate all driving regions | Prevents optimistic classification from incomplete evidence |
| Visualization | Exact reference matches, explicit full-population accounting, supported linear contours | No fabricated reference cells or cubic overshoot |
| Operation | Draft initiation, active-template dry planning, repeatable plot inputs and hashes | The documented path is executable and testable |

No code from a comparator was copied. A paper-defined correction can deliberately
break agreement with an older reference implementation; preserving the old oracle
as historical evidence is preferable to retaining a physics error for parity.

## A credible route to stronger statistical claims

The next comparative study needs three separately scored tracks. Combining them
into one success percentage would hide the cause of any apparent advantage.

1. **Same likelihood, same data.** Use fixed full workspaces, identical signal
   patches, parameter bounds, and CLs conventions. Compare Ravel with direct pyhf
   and a second frontend. Record observed and expected limits, nuisance solutions,
   optimizer failures, active bounds, runtime, and numerical tolerance. Include
   nearly empty bins, weak signals, large correlations, and boundary solutions.
2. **Statistical calibration.** Generate pseudo-data from declared models over
   weak/strong signals, low counts, and nuisance correlations. Measure the relevant
   exclusion probability or interval coverage with binomial uncertainty. Compare
   asymptotic and toy constructions at selected stress points. Do not describe a
   handful of recovered S95 values as this experiment.
3. **Physics-to-limit propagation.** Freeze the statistical workspace and vary
   one physics component at a time: object efficiency, overlap removal, ISR/PDF,
   merging, or normalization basis. Carry weighted-event sumw and sumw2 and show
   per-stage distributions. Judge held-out mass points before accepting a detector
   tuning. Repeat on another analysis to test transfer.

The compressed-slepton historical median remains 24.9%. A later workspace study
reports smaller residuals with multiple simultaneous changes; it is not a clean
attribution. The present eRJR correction concerns another analysis and cannot be
used to explain the compressed-slepton residual. For the squark/gluino retained
samples, distributed cutflow losses still lack a uniquely established cause.

To evaluate the agent layer, reuse the predeclared
[prospective comparison design](2026-09-05-competitive-design-and-validation.md)
with the same model, budget, inputs, and allowed tools; isolate workflow controls
from cached knowledge. Report valid refusals and unwarranted success separately.
A strong result would be fewer scientifically unsupported deliveries at comparable
completion and cost. That remains a testable objective, not a current result.
