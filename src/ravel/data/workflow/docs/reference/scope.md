# Scope of RAVEL 1.3

RAVEL orchestrates physics research from a question to a reviewed result.
The controller records the question, chooses a route, plans the work, obtains
authority, runs tools and reviewers, and delivers the evidence with its scope.
The scientific interfaces below define the inputs, artifacts and checks for each operation family.

The [capability reference](capabilities.md) describes these families. The
[source inventory](documentation-inventory.md) lists the exact registered
operations, interfaces and configuration fields. Each operation has its own
input, output, resource and validation contract.

## Scientific interfaces

| Work | Inputs and result | Boundary |
|---|---|---|
| Published-result summaries | Acquired sources, quoted quantities, provenance and a requested summary or plot | The quoted result retains its original model, data and statistical definition |
| Reproduction and reinterpretation | A model, selection, detector response, normalization and statistical model; reviewed limits or comparisons | Acceptance, likelihood pairing and numerical closure apply to the selected study |
| Event generation and analysis | Supplied process/model cards or event files; generated events, selections, histograms and signal templates | Native tools, source versions and the approved event/resource budget govern execution |
| Likelihoods, fits and measurements | Supplied or constructed statistical models with declared correlations; estimates, intervals, limits and diagnostics | Each method owes its detected validity and uncertainty checks |
| Parameter scans | Declared axes, full point population and per-point computations; a result grid and figures | Missing or failed points remain visible in the coverage record |
| Theory and model calculations | Supplied model sources, parameter conventions and native tools; quantities and source-bound diagnostics | Applicability and numerical qualification belong to each adapter and model |
| Supplied-data studies | Typed arrays, tables, events, predictions or likelihoods; derived quantities and reports | Input units, population, covariance and lineage are part of the contract |
| Research and method studies | A question, budget, hypotheses and child experiments; retained evidence and a reasoned conclusion | The loop records stopping decisions, failed experiments and unresolved requirements |
| Literature and knowledge retrieval | A query or acquired source; selected passages, source identities and retrieval records | Source identity and acquisition lineage accompany each retrieved passage |
| CPU classifier studies | Supplied arrays, binary labels, split/seed policy and equal budgets; NumPy logistic or MLP models and diagnostics | Exposure, selection and evaluation checks bind the declared study |
| Notes and diagrams | Supplied scientific result records or model/diagram specifications; short notes, diagrams and build records | The build consumes the declared evidence and preserves result qualifications |
| Batch and site execution | An adopted workflow, site profile and resource ceilings; supervised jobs and adopted outputs | Scheduler support depends on the installed profile and its checks |

Use [study guides](../guides/study-types.md) for entry points and
[installation](../installation.md) for the complete toolchain.

## Result quantities

An exclusion request that does not prescribe a statistic gets **95% CLs**
exclusion limits by default. When the request prescribes a statistic—an explicit
formula, an Nσ region, a Δχ² threshold or a Bayesian credible interval—that
statistic is the primary result, with CLs alongside when requested. Fits,
measurements, calculations and summaries retain their contracted quantities.

An observed discovery claim requires authorized data, its own statistical
definition and the applicable validation. A prospective sensitivity study
retains its expected-data label.

### Statistical modes

`stat_mode` names the statistical model a result uses; the canonical list is `STAT_MODES` in
`result_pack.py`, mirrored here first.

| Mode | Model | Selected when |
|---|---|---|
| `published-likelihood` | the analysis's serialized pyhf workspace with the signal patch | the serialized likelihood is published (the strongest basis) |
| `simplified-likelihood` | the published simplified or covariance model | the analysis provides it |
| `constructed-likelihood` | a HistFactory/pyhf model built from the published yields, background estimates and a declared systematics registry with correlations (cabinetry builder, native-builder parity recorded) | a per-region systematics breakdown is published without a likelihood or covariance |
| `best-sr-counting` | single-bin counting per signal region, quoting the best expected-CLs region | no serialized likelihood is published |
| `combined-counting` | a simultaneous multi-bin counting fit | the signal regions are mutually exclusive |
| `stability-only` | a pipeline stability and validation statement without a limit | validation runs |
| `shape-fit` | a scoped binned-template fit (`shape_fit.py`): the paper's background shape times a flexible polynomial plus the signal template, to CLs; R5-gated per analysis | the result is a binned shape fit the engine represents and its R5 closes |
| `blocked-shape-fit` | the requested fit stays unmet because the selected legacy engine represents or validates a different fit; compatible native or custom alternatives are inspected | the shape fit's representation or R5 is open |
| `sensitivity-expected-only` | expected-only sensitivity (S/√B, expected CLs) with no observed-data claim | projections and prospective studies |
| `none-survey` | no per-run statistics; the result quotes other analyses' published limits | surveys and summary plots |
| `prescribed-statistic` | the statistic the request prescribes (an explicit formula, an Nσ region, a Δχ² threshold, another confidence level), delivered as the primary result with its definition and certified like a limit | the request names its statistic; `stat_mode_note` quotes it |

## Scope boundaries

| Subject | Scope in this release |
|---|---|
| Registered capability | A source declaration with its adapter and contract. Execution evidence is recorded separately |
| Transport declaration | A candidate route. Controller seats require a wired executor, admitted destination, current probe and required qualification |
| Scientific qualification | Evidence for a specific model, selection, statistic and input domain |
| Licensed tools | Execution under the user's licence; compatible alternative tools keep their own contracts |
| Detector response | The supplied or selected response model and its measured validation domain |
| Covariance and efficiencies | Supplied, derived or explicitly justified inputs with provenance |
| Aggregate resource isolation | The capabilities of the selected runtime, disclosed in its admission and execution records |
| Cost | Measured usage and catalogue-priced estimates retain their source and calculation basis |
| Scientific effectiveness | Established by executed studies and their evidence |

### Execution rules the contract pins

- **Skill precedence (N1).** A physics session invokes `physicist-intake` first: the intake routes the
  request, gates it and composes CHECK-IN 1. The gate on downstream skills (G22) holds until a validated
  `task_contract.json` exists, and names `physicist-intake` as the step to run.
- **In-tree outputs (N2).** A point or scan launched on the supervised path writes under the run
  directory. An output directory that resolves under a temporary location or the session scratchpad is
  rejected at launch, and a command writes where its `--out` points, so that stays under the run directory.
- **Detached long jobs (N6).** A long compute detached from the harness carries a durable
  `run_state.json` entry (`bg_kind=detached`, `logfile`, `done_condition`, `next_action`) and a
  harness-visible heartbeat; the turn-end gate (G27) refuses a detached job without them. Harness-tracked
  backgrounding re-invokes the agent on completion, so the physicist sees the result.

The [transport reference](transports.md) describes model interfaces and qualification.
[Inference engines](inference-engines.md) describes statistical validity and
uncertainty handling.

## Routes and contracts

The controller routes are registered under `src/ravel/data/controller/routes/`.
Its analysis, study, research, ML and manuscript adapters prepare the applicable
contract. Open questions retain their original requirements while the judgment
route proposes sub-problems.

Legacy task labels and detector/statistical enums are documented in the
[task-contract reference](task-contract.md). These labels describe one intake
interface; science modes provide the larger operation inventory.
[Workflow intake](../workflow/start.md) gives route precedence.

## Approval, fidelity and delivery

CHECK-IN 1 binds the plan, assumptions and resource scope before execution.
Later check-ins review intermediate evidence, changes and final results.
The [operator configuration](configuration.md) controls interactive or delegated
authority. The [controller appendix](../architecture/controller.md) explains the
checkpointed path.

Every delivery states its covered domain, uncertainty treatment and unresolved
requirements. A result's receipt binds the bytes used to support it.
Selection acceptance, native parity, statistical closure and scientific
conclusions carry separate evidence. A bounded result, qualified result or
partial grid retains that label in its figures and report.

See [output and provenance records](outputs.md) for the artifacts that establish
these statements.
