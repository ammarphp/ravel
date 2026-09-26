# Competitor capabilities and the next adaptation work

This September 26, 2026 refresh examines twelve systems: seven agent frameworks,
four established reinterpretation tools, and one benchmark. It is a public-source
capability audit, not a new performance trial. Eleven public repository HEADs
were resolved live; selected documentation, interfaces, and repository trees were
read. No competing framework was executed and no events were generated. Exact
revisions, source links, inspected-file hashes, and the distinction between
published claims, source presence, and earlier execution are recorded in
[competitors.json](../../evidence/audits/2026-09-26-analysis-landscape/competitors.json).
The Ravel comparison baseline is source `89273dfc928917fa43c64d236666679ab3b5efcb`,
behind public export `79c7aabb37fef3809d0a8e57882baedfdaa3dced`.

The clearest opportunity is to make preserved analyses scientifically admissible
with explicit quantity definitions and validation evidence. More agent roles or
more generated routines alone will not close that gap. Equally, Ravel should not
claim unique provenance, structured extraction, adversarial review, or superior
statistics: multiple peers already implement those ideas.

## What changed since the pilot

**SFitterAgents now has substantial public source.** The earlier README-only
finding is obsolete at the refreshed HEAD. The repository contains the SFitter
likelihood package, extraction and SMEFT parameterization workflows, datacards,
and agent instructions. Its advertised operational path requires Linux,
Apptainer, SLURM, and GPU resources for fits. Code availability is now confirmed;
installation, reproducibility, and physics accuracy remain untested here.
[Repository and setup](https://github.com/heidelberg-hepml/SFitterAgents/tree/6072a79e0f132d61a927f11ed482a401b34f6e3f).

**Modern statistical comparators are more capable than a simple CLs baseline.**
Contur 3 uses supplied SM predictions by default, incorporates available
experimental covariance, and offers Spey signal-strength fits. SModelS 3.2
announces ONNX surrogate statistical models, including ATLAS-SUSY-2018-16, and
changes its database region/statistical-model mapping. These are reasons to
benchmark inference transport and cost; neither can repair biased simulated
acceptance. [Contur 3 release paper](https://arxiv.org/html/2505.09272v1),
[SModelS release announcement](https://smodels.github.io/).

FERMIACC still has no matching runnable public repository located in this
refresh. The official paper and its links were checked, alongside a current
GitHub repository search for `FERMIACC` and targeted web searches. The GitHub
search returned two unrelated billiard/acceleration repositories. This bounded
search is not proof that no private or differently named release exists.
[FERMIACC paper](https://arxiv.org/html/2603.22538v1).

## Capability and adaptation matrix

“Present” below means a public interface, implementation, or instruction workflow
was inspected; it is not a successful execution claim. Previous trials are
reported only as the [September 9 pilot](2026-09-09-comparative-pilot.md), with its
setup confounds intact. HEAD pins are in the machine-readable companion.

| System | Public capability and evidence boundary | Material adaptation for Ravel |
|---|---|---|
| [ColliderAgent](https://github.com/HET-AGI/ColliderAgent/tree/1140f39e8730889422a64a141fbd3ca10529e13b) | FeynRules validation/UFO, MG5, shower/Delphes, and MA5 normal-mode interfaces and skills are present. Expert-mode MA5 remains on its roadmap. The earlier native Drell–Yan delivery succeeded after runtime repairs; Magnus and model generation were not validated by that trial. | Model admission and flexible analysis adapters are real gaps. Preserve external tool boundaries, verify executed model/process settings, and require physical controls beyond successful export. |
| [MadAgents](https://github.com/MadGraphTeam/MadAgents/tree/df241214d1e4a66b1f9964aa33dd2342b7084b9a) | Source-grounded MG configuration, LO/NLO/EFT/decay-chain guidance, target-derived runtime probes, and persisted learning are present. The earlier timed trial was confounded; the completed native control was operator assisted. | Check the user's intended observable against actual generation semantics, including interference, decay restrictions, and perturbative order. Source lookup and adversarial probing are prior art, not a unique Ravel contribution. |
| [FERMIACC](https://arxiv.org/html/2603.22538v1) | Paper describes typed model hypotheses, proposer/critic refinement, an executable-model contract, and generated recast selections. No public runnable implementation located. The paper explicitly defers comparison with published signal efficiencies. | Borrow the scientific requirement of a theory-to-executable-model contract, with original implementation. Do not use FERMIACC as established acceptance fidelity or a measured head-to-head baseline. |
| [AgentRivet](https://gitlab.com/hepcedar/AgentRivet/-/tree/e4d12eccb6aee546d993481c75576c0df4e2b037) | Paper-to-structured-summary-to-Rivet generation/review is present. The prior local trial stopped at provider authentication after routine lookup. Its published study documents normalization and complex-observable errors, with official-routine comparison deferred. | A reviewed generated routine must still pass fixed-event object, bin, and normalization comparisons. Preserve unresolved definitions and missing learned observables as specific blockers. |
| [HEPTAPOD](https://github.com/tonymenzo/heptapod/tree/865d3f0350e953237cf0f558386905e255997e43) | Modular toolbase/MCP bundles expose MG, event generation, analysis/recast linting, BSM inputs, and symbolic tools. Main-branch and feature-branch capabilities must be distinguished. Earlier events were delivered using workarounds, not a clean integration pass. | Support stage-scoped observable workflows and explicit dependencies. A linter is useful screening but cannot certify detector or statistical fidelity. |
| [HEPLocalAgent](https://github.com/AadarshSingh0/HEPLocalAgent/tree/a2d604aee3222f3d5b86bb0eb51e80e7decc83cd) | Deterministic request validation, bounded repair, managed native stacks, replay fixtures, and curated evaluation records are present. No matched live trial was run here. | Expand request-preservation regression cases and record runtime ownership. Its validation/repair evidence prevents treating these features as uniquely Ravel's. |
| [SFitterAgents](https://github.com/heidelberg-hepml/SFitterAgents/tree/6072a79e0f132d61a927f11ed482a401b34f6e3f) | Public measurement extraction, uncertainty decomposition, SM templates, SMEFT scans/interference, datacards, and fitting source are now present. No installation or fit tested in this audit. | A measurement route needs correlated uncertainty sources, conventions, order corrections, and operator-basis translation. These are substantial new scientific scope, not a few additional prompts. |
| [Contur](https://gitlab.com/hepcedar/contur/-/tree/0ff261c691cfc138e5855164250ab82e094c7353) | Mature particle-level Rivet/YODA-to-constraints workflow; source includes reference/theory/covariance handling. Current release supports SM predictions and optional Spey fits. Not executed here. | Build a typed measurement adapter with observable semantics and overlap/correlation policy; use an external backend before reimplementing global inference. Pin Rivet/YODA major versions. |
| [MadAnalysis 5](https://github.com/MadAnalysis/madanalysis5/tree/c2275a7967e75d7b78c4c385be9f232ef0fb2cc0) | Public event-analysis and recasting machinery, expert-mode extension points, and pyhf support are present. No recast run in this refresh. | External routine adapters can expand coverage. Every recast still needs its detector card, region mapping, validation benchmark, and normalization contract. |
| [CheckMATE](https://github.com/CheckMATE2/checkmate2/tree/ab96d9352320591166cceec659d858b6eb17e8ed) | Public ATLAS/CMS routines, multibin likelihood modes, and selected ONNX/TMVA-dependent analyses are present. It includes `atlas_1911_12606`. No new runtime trial. | Use a fixed-event selection comparison to investigate compressed-analysis differences. Treat object definitions and statistical input conventions as variables; a different engine is not ground truth. |
| [SModelS](https://github.com/SModelS/smodels/tree/ef008e1628d0bf6a801db52542dae106016f59e6) | Spectrum/topology decomposition, efficiency/upper-limit database matching, pyhf and neural-surrogate interfaces are present. No benchmark execution in this refresh. | Add a fast spectrum/map route with topology applicability and missing-coverage reports. A map-derived limit does not establish event-level reproduction. Statistical surrogates require domain/error checks against exact inference. |
| [Collider-Bench](https://github.com/dfaroughy/Collider-Bench/tree/2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c) | Public evaluation tasks, runtime tooling, and data/tool interfaces. It is a benchmark, not a competing analysis agent; no full benchmark run here. | Use held-out requests and endpoint-specific metrics, retain all attempted-task denominators, and separate setup failures, unsupported capability, fidelity, and cost. |

The AgentRivet study is particularly relevant to the current visual concerns:
its examples show that correct-looking numerical output can still use the wrong
normalization measure, and that an intermediate summary can omit essential
observable definitions. The transferable lesson is to compare the mathematical
quantity, the event population, and the rendered figure together. It does not
identify the cause of Ravel's RRR discrepancy.
[AgentRivet methods and results](https://arxiv.org/html/2606.13535v1).

## Three implementation priorities

### 1. Admit routines through executable scientific contracts

**Build:** a versioned analysis adapter contract covering source revision,
collider/beam applicability, truth versus reconstructed input, object definitions,
selection boundaries, histogram quantity and units, bin volumes, normalization,
region overlap, reference tables, likelihood availability, and external assets.
A routine discovered in a catalogue is a candidate. Admission requires a
recorded physicist decision plus executed evidence on the actual adapter and
reference inputs. Distinguish discovery, build, fixed-event validation,
reference closure, and delivered result as separate states.

**Acceptance tests:** one ATLAS and one CMS particle-level routine on frozen
events, then one simple reconstructed selection; no new large generation campaign.
Check every event/region or observable contribution against the pinned upstream
routine. Include unequal-width and two-dimensional bins, a flattened plot index,
normalized distributions with singular covariance, under/overflow, duplicate
reference IDs, lepton dressing, strict threshold ties, input-level mismatch,
negative-weight events, overlapping regions, missing learned-model assets, and
stale source hashes. Negative cases must identify the failed requirement; positive
cases must deliver a reference overlay and quantitative agreement in declared
units. Reproducing the routine on fixed events precedes reproducing the paper.

**Novelty limit:** contracts and preservation already exist. The possible
contribution is demonstrably reducing undetected scientific mismatches across
adapters under a controlled ablation. The catalogue itself is infrastructure.

### 2. Import external executed recipes and preserve the complete request

**Build:** read-only adapters for external framework artifacts into an original
Ravel evidence schema. Record the full requested endpoint and independently read
actual process/model restrictions, cards/defaults, PDF, scales, weight convention,
exposure, cross-section/branching basis, event census, tool revisions, and output
quantity. Missing fields remain unknown; they cannot satisfy equivalence. Keep
producer-native artifacts and distinguish operator intervention from agent work.
Ravel already compares its own scoped runs; external import is the missing link.

**Acceptance tests:** import the retained ColliderAgent, HEPTAPOD, and assisted
MadAgents Drell–Yan samples without rerunning them. All three must pass artifact
census while their differing recipes prevent an accuracy ranking. Use controlled
fixtures for seed-only differences, changed scale/model restriction, ambiguous
units, signed weights, partial event files, tampered cards, absent defaults,
incorrect beam energy, double branching factors, and an omitted requested plot.
A request-preservation test must reject silent substitution of parton generation
for detector analysis or of a new scan for a supplied-workspace limit.

**Novelty limit:** provenance and benchmark protocols are established ideas.
Publish a causal reduction in erroneous comparisons and incomplete deliveries,
with setup burden and false refusals measured. Do not claim superiority merely
because Ravel rejects a scientifically invalid comparison.

### 3. Add scientific adapters in order of validated leverage

**Build in stages:** first a measurement/YODA contract and an external mature
inference backend; next general signed/multiple-weight and normalization transport;
then new-model/UFO and EFT interference admission. Fast SModelS/map and surrogate
routes are optional independent branches with their own applicability evidence.
Retain exact pyhf as a control for any surrogate acceleration. Do not join these
branches into one unreviewable broad release.

**Acceptance tests:** reproduce one published covariance-bearing measurement with
its stated SM prediction and a documented overlap policy; reject unknown
correlations rather than fabricate independence. For weights, prove chunking,
merging, cancellation, and sum-of-weights-squared invariance with hand-calculable
fixtures. For models, require model identity, parameter conventions, widths,
restriction/coupling orders, physical-limit tests, and independent amplitude or
cross-section controls. For EFT, test SM, linear/interference, and quadratic terms
separately and verify the coefficient convention. For a surrogate, compare held-out
likelihood values and roots across its declared domain, boundary cases, and
adversarial out-of-domain inputs before any speed claim.

**Novelty limit:** FeynRules is a model-construction tool, not a detector-fidelity
repair. Importing an established tool's functionality is capability engineering.
Ravel's defensible research question is whether explicit human decisions plus
artifact-bound scientific checks improve fidelity per unit cost on held-out
analyses. That claim needs experiments; it is not established by this survey.

## Recommended comparison design

Use a shared scientific task specification and shared feasible compute budget,
while allowing each framework its documented native workflow. Script affirmative
physicist answers for the experiment and retain each actual proposal; label them
as scripted assent rather than expert review. Score requested deliverables,
scientific fidelity, interventions, tool/model usage, and runtime independently.
Keep installation failures in the product-coverage denominator but separate them
from physics errors. Randomize run order when comparing performance; freeze
recipes before comparing rates; use fixed events before new simulation.

Start with the retained parton samples, a supplied public likelihood, and the
small routine-admission controls above. Add a harder analysis only after the
simpler control shows which layer is trustworthy. RRR acceptance, low-splitting
shape, generator-cut stability, and full-plane closure remain separate publication
requirements. Neither broad source availability nor competitor feature parity
removes those requirements.
