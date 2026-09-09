# Comparative pilot and the next capability work

Ravel's supported workflow coverage is a product limitation. A scientifically
appropriate refusal does not deliver the requested analysis. Comparative tests
must also distinguish an agent's ability to improvise around a tool from the
reliability of the tool's advertised integration. Neither property establishes
detector fidelity or a faithful RRR reproduction.

This exploratory pilot began on September 8, 2026 in America/New_York and ran
across September 9 UTC. The [evidence bundle](../../evidence/audits/2026-09-09-comparative-pilot/README.md)
contains the completed run summaries, independent audits, prompts and revisions.
No complete benchmark score, causal advantage or publication readiness is claimed.

## What was actually made comparable

The driver was `gpt-6-astra` through Codex CLI 0.153.4. Each task received a fresh
workspace, the same task text and the same experimental operating policy.
Required consultants were configured to use Astra, with a requested sequential policy. MadAgents
used its supported cold `none` memory pack; shipped framework instructions and
packaged knowledge remained available. Run order was fixed, and native runtime caches could become warm; timing is descriptive, not a randomized performance estimate. The requested serial consultant policy can disadvantage systems designed for parallel specialists. This is not a comparison of each author's
original model, hardware, memory configuration or published evaluation.

The generation task requested exactly 100 SM `pp -> e+ e-` parton events at
13 TeV, seed 1729, built-in cteq6l1, lepton pT above 10 GeV, absolute eta below
2.5 and dilepton mass above 40 GeV. It required the actual event file, cards,
execution log, numerical cross section and integration error, independent
kinematic checks and PNG/PDF figures. The generator was a separate copy of the
existing native MadGraph 2.9.27 installation. No shower, detector simulation,
large scan, container download or cloud compute was requested.

The second task supplied the ATLAS 2016 2jl fitted-background inputs from
[arXiv:1605.03814](https://arxiv.org/abs/1605.03814): n=263, b=283, db=24 and
3.2 inverse femtobarns. It explicitly requested a single-bin pyhf
`uncorrelated_background` approximation with a unit signal template, asymptotic
qtilde CLs, observed and median-expected roots, root residuals, visible-cross-section
units and a CLs figure. This holds the statistical prescription fixed. It tests
input transport and inference; it does not validate event acceptance or recreate
the collaboration's complete likelihood.

The budget was 600 seconds per subject/task, one physics worker, and a requested
8,000 generated-token target including consultants. The wall timeout is enforced;
the token target is an instruction, not a guaranteed accounting cap. Preserve
observed usage and retries rather than substituting the requested budget for
actual expenditure. CPU thread variables were set to one. These laptop pilot
conditions do not reproduce a published cluster benchmark.

All experimental physicist check-ins received a standing affirmative answer.
Concrete proposals and automatic approval records were retained where the
framework had check-ins. They are labeled scripted affirmative and provide no
substantive expert review. We did not disable the scientific-validity gates or
grant credit for stopping at one.

The public Ravel baseline was frozen at `6f445b9d759463a609016c2b27a6810f6ec1655e`;
its source provenance was `908ed5e297254e68fd2878314c9663ccb6a7e97a`.
Repairs described below were made in a separate development worktree, not inserted
into the running baseline. References already shipped with a framework were not
removed. The pilot is not a blinded held-out study.

## Public source and execution availability

| System | Public revision acquired | Execution condition |
|---|---|---|
| [ColliderAgent](https://github.com/HET-AGI/ColliderAgent) | `1140f39e8730889422a64a141fbd3ca10529e13b` | Installed skills and Magnus SDK. Local Magnus startup failed because Docker was absent. Tested its explicitly documented native execution option; this does not validate Magnus. |
| [MadAgents](https://github.com/MadGraphTeam/MadAgents) | `df241214d1e4a66b1f9964aa33dd2342b7084b9a` | Supported Codex folder install: 46 roles, eight skills, cold memory. Shipped verification and a fresh-context installation review completed. |
| [HEPTAPOD](https://github.com/tonymenzo/heptapod) | `865d3f0350e953237cf0f558386905e255997e43` | Installed mg5/analysis bundles through toolbase and connected the benchmark project. Backend calls and native workarounds are distinguished in the results. |
| [AgentRivet](https://gitlab.com/hepcedar/AgentRivet) | `e4d12eccb6aee546d993481c75576c0df4e2b037` | README editable installation succeeded. Its ATLAS-paper lookup correctly found an existing Rivet routine. The Astra model-provider preflight stopped at missing `OPENAI_API_KEY`; no analysis-generation result is claimed. |
| [HEPLocalAgent](https://github.com/AadarshSingh0/HEPLocalAgent) | `a2d604aee3222f3d5b86bb0eb51e80e7decc83cd` | Public source acquired. Its Ollama and managed-stack configuration was not replaced with an invented Astra adapter. No matched live model run. |
| [SFitterAgents](https://github.com/heidelberg-hepml/SFitterAgents) | `c52ce2ba90e5ee089429d8cdce5762498a401573` | The acquired revision contains README and license only. No runnable release to test. |
| [Collider-Bench](https://github.com/dfaroughy/Collider-Bench) | `2986d8b270ae49e0d6e8c95bbf95ef1159f16d7c` | Public benchmark suite, not another analysis agent. Inspected for evaluation design; full benchmark not run. |
| [LeWRON](https://github.com/quarkquartet/LeWRON) | `2cce628c3ab97797d0a4c334a36795cbf0fa7ad5` | Public adjacent system for phase-transition/gravitational-wave workflows. Not treated as a collider-reproduction baseline. |
| [FERMIACC](https://arxiv.org/abs/2603.22538) | No runnable public repository located | Official paper links and targeted repository searches did not identify a release. This is an availability finding, not a measured performance failure or proof that no code exists. |

The first MadAgents launch failed because ephemeral Codex execution could not
resolve its parent session for consultant dispatch. That attempt is preserved as
an evaluator-harness failure. The corrected runner retained session records and
disabled memory injection/generation; it did not modify MadAgents' implementation.
This distinction matters: broken evaluation plumbing must not become a claim
about a competitor's physics.

The retained MadAgents attempt also encountered the evaluator's two-open-thread
cap, which counts retained consultant sessions rather than only active work.
It eventually reached a native linker failure and the 600-second timeout. This
is not an interpretable estimate of MadAgents' unconstrained performance. An
explicit operator-assisted follow-up kept its physics card unchanged, changed
only output paths, and supplied the missing SDK/library environment. It produced
the requested 100 events in 13.3 seconds. That isolates a runtime setup problem;
it does not retroactively make the autonomous attempt a success. The ColliderAgent
statistics run removed the retained-thread cap; the Ravel statistics run had
already started with the earlier setting. The serial active-consultant policy
remained requested. The receipt records each run's actual configuration.

The JSON event stream is not a complete record of consultant dispatch. Where
available, runtime session metadata is retained separately to verify actual
parent/child execution. An unverified independent-review claim receives no extra
credit merely because a Markdown report says a reviewer ran.

## Completed outcomes

| System and task | Actual result | Complete framework delivery |
|---|---|---|
| Ravel, Drell-Yan | Refused unsupported generation-control route; no events | No |
| ColliderAgent, Drell-Yan | 100 events, audited cuts and figures; documented native path after SDK/linker repair | Yes, on that native path; Magnus not validated |
| HEPTAPOD, Drell-Yan | 100 events, audited cuts and figures after native generation and LHE-reader workarounds | No clean integration pass; artifacts delivered |
| MadAgents, Drell-Yan | Timed attempt stopped with zero events; harness and linker failures confound interpretation | No measured complete delivery; operator control is separate |
| Ravel, ATLAS 2jl | Existing counting component produces both limits and figures; full lifecycle demands irrelevant acceptance certification | No; component succeeds |
| ColliderAgent, ATLAS 2jl | Newly written standalone pyhf component produces both limits and figures; no shipped statistics-only route | No; component succeeds |

The independent [counting audit](../../evidence/audits/2026-09-09-comparative-pilot/independent-counting-audit.json)
checks both serialized likelihoods against the requested model, invokes pyhf
afresh at each reported root and on both sides, and checks the conversion to fb.
Both give 43.6513 observed and 54.8857 median-expected signal events, or 13.6410
and 17.1518 fb. Their largest inter-system difference is about 0.000011 events.
This supports agreement of these particular numerical components, not statistical
superiority of either product, asymptotic coverage or the original ATLAS likelihood.
Both original CLs figures were visually inspected and their roots, labels and
units checked. The [gallery](../../evidence/audits/2026-09-09-comparative-pilot/index.html)
retains the separate producer figures instead of silently harmonizing their outputs.

All three completed LHE samples, including the operator-assisted MadAgents
control, passed an independent census of their 100 actual events and requested
kinematic cuts. The MadAgents control has cross section 760.535 ± 6.492428 pb
(printed integration error). It receives no autonomous delivery credit. Exactly
300 completed parton events are retained across these three samples; no detector
campaign or new RRR sample was launched in this pilot.

## Findings that already change the development priorities

**The lifecycle is coupled too tightly to full reinterpretation.** The live Ravel
generation request initially acquired an inappropriate reproduction/scan draft.
The agent corrected its interpretation and stopped because the shipped taxonomy
and native registry do not expose a standalone SM generation-control workflow.
Ravel's instructions do describe direct MadGraph generation stages; the finding
is not that MadGraph cannot generate Drell-Yan. The missing product is a supported
request-to-execution-to-artifact path for that task.

**Semantic validation and execution capability are different gates.** The cheap
12-request routing census found unsupported generation, model-building and
statistics-only requests. Some other requests produced a valid route without
establishing an executable adapter. In particular, ordinary expected-limit
language could trigger projection/scan planning. A structurally valid contract
does not establish that the original request survived intact.

**A common prompt does not fix the physics recipe.** The generation prompt left
scale choice to the agent while requiring it to report the result. Compare actual
cards before interpreting cross-section differences. Renormalization and
factorization scales, flavor scheme, perturbative order, generation cuts and
normalization are part of the scientific task definition. A difference here is
not automatically a faulty simulator. Future fidelity comparisons should freeze
these prescriptions or prespecify how their uncertainty is assessed.

The inspected executed cards differ in model restriction as well as scale:
ColliderAgent imported `sm-no_b_mass` and selected dynamic scale choice 3;
HEPTAPOD imported `sm` and fixed both scales to 91.188 GeV. Their independently
read LHE cross sections were 605.07 and 771.2809 pb respectively. The 27.5%
difference is not attributable to either change separately from this pilot.
Treat it as a failed recipe-equivalence condition, not an accuracy ranking.

**Published ambition is not a fidelity certificate.** FERMIACC describes a
structured analysis representation and generated recasting implementation, but
explicitly leaves comparison of simulated signal efficiencies with published
efficiencies as future work. Its paper therefore does not establish superiority
on the acceptance problem at issue here. HEPLocalAgent's
[evaluation](https://arxiv.org/abs/2608.28244) also reports incomplete execution
and request-preservation failures. These are reasons to test common endpoints,
not reasons to discount those systems or assume Ravel is superior.

## Durable repairs in this update

- Refusal validity is separated from capability delivery. The historical
  `served-with-refusal` label now receives zero delivery credit. Missing gates
  cannot credit verified delivery, and the headline counts verified complete
  requests rather than unratified status strings. Partial inventory credit is
  retained as component coverage, not an empirical task-success rate.
- Expected-limit terminology alone no longer triggers a future projection.
  Explicit HL-LHC, future-luminosity and detector-projection requests retain their
  routes. This repairs interpretation without claiming a new execution capability.
- The comparison protocol makes scripted approvals, setup failures, retries,
  model availability, native alternatives and full requested-task denominators
  explicit. An independent stdlib LHE auditor checks actual generated records;
  adversarial fixtures reject wrong beams, seeds, PDFs, event counts, weights
  and lepton kinematics.

No competitor implementation was incorporated into Ravel. Public repositories
were executed in separate experimental workspaces; the new audit code is original.
These repairs do not change RRR signal events, tune its response or certify its
exclusion contour.

## What to build next, and how to know it worked

| Priority | Missing capability or weakness | Concrete acceptance condition |
|---|---|---|
| 1 | Stage-scoped generation control | Typed `generate` request, explicit absent detector/statistics stages, preserved beam/process/cuts/seed, approved bounded launch, actual LHE and plots; the fresh Drell-Yan request completes through the supported path. |
| 1 | Stage-scoped likelihood control | Supplied public or declared approximate likelihood reaches common inference without inventing a mass scan; roots, residuals, nuisance convention and units survive into JSON and figures. |
| 1 | Effective-recipe comparability | Compare executed cards and normalization, including defaults and resolved model restrictions, before scoring rates or shapes. Reject an equivalence claim on a mismatch. |
| 2 | Request preservation | Audit every requested stage/output against the proposed plan. Negative constraints and ordinary expected/observed statistics do not become new scans or projection assumptions. |
| 2 | General analysis admission | Reproduce a published fiducial analysis on fixed events; check object definitions, cut boundaries, region membership, normalization and published cutflow before introducing a detector approximation. |
| 2 | Detector-response closure | A simpler reconstructed-object control with published references verifies threshold efficiencies and bin migration. Transfer any recurring discrepancy to the RRR diagnosis. |
| 3 | New models and regimes | Add FeynRules/UFO validation, EFT interference/order handling, LLP truth-to-response adapters and custom-analysis compilation only with explicit reference tasks and end-to-end acceptance criteria. |

The next RRR experiment should still separate effective-recipe mismatch from
truth-to-reconstruction and fitted-bin migration at retained diagnostic anchors.
Use the existing events and traces first. The low-splitting shape discrepancy,
global bias and incomplete full-contour reproduction remain publication blockers.
A simple control passing can locate a failure; it cannot remove a failed RRR
physics comparison from the evidence required for publication.
