# Choosing a study contract

Start with the scientific quantity and evidence you need. RAVEL retains that request, its supplied files, parameter domain and deliverables in a task contract. Routing chooses an installed fixed route or judgment planning from those facts. Execution requires the actual admitted operation and its retained result records.

Use [the workflow entry procedure](../workflow/start.md) to begin and [the CLI guide](../cli.md) for commands. [The architecture appendix](../architecture/README.md) explains the controller behind each route.

## Match the intent to the result

| Intent | Contract and primary result | Inputs and limits to state |
|---|---|---|
| Summarize published results | Source-linked quantities, compatible overlays or a source census | Exact definitions, units, domains and source locations; quoted published numbers remain published evidence |
| Reproduce a result | Declared counterpart, source comparison, residuals and uncertainty | Original input population and comparison basis; a requested plane requires its full declared point population |
| Reinterpret a model | New inference for the declared model within the selected analysis/response contract | Model admission, detector/selection applicability, normalization and statistical assumptions |
| Scan parameters | Per-point results plus complete domain/status census and declared contours or surfaces | Axes, ranges, lattice, failures, untested cells and interpolation policy |
| Project sensitivity | The declared prospective metric and its uncertainty | Exposure, response and background assumptions; expected-only scope where observed data are absent |
| Fit or measure | Contracted parameters, intervals, likelihood/fit diagnostics or measured quantities | Data model, covariance, nuisance treatment, estimator and validity checks |
| Calculate or propagate | The requested formula, derivation or numerical quantity with conventions and uncertainty | Units, domains, numerical precision and supplied joint uncertainty law |
| Study supplied events | Audited analysis outputs over the supplied population | Format, weight/normalization, features, response and selection definitions |
| Generate events | Complete audited generation artifacts and recipe | Model/process/card identities, perturbative settings, seeds and statistics; generation alone establishes no detector acceptance |
| Compare or develop a method | Preregistered comparisons, failed trials, confirmation and scoped conclusions | Baseline, metric/direction, exposure split, trial count, stopping and attribution controls |
| Apply or train an ML model | Pinned-model inference, or separately admitted staged training/evaluation artifacts | Features, preprocessing, partitions, leakage checks, seeds and protected confirmation authority |
| Prepare a scientific document | Claims and figures bound to accepted evidence, integrity review and the declared rendering/source artifact | Citation provenance, unresolved results, figure population and format/runtime requirements |

The route selector and installed specifications are [`controller/routes/select.py`](../../src/ravel/controller/routes/select.py) and [`data/controller/routes/`](../../src/ravel/data/controller/routes/). [Scientific studies](../workflow/reference/scientific-studies.md) describes callable operations; their own source contracts and executed evidence constrain support.

## State the requested statistic

An exclusion without a prescribed statistic uses 95% CLs by default. If you ask for an explicit formula, confidence level, N-sigma region, chi-square threshold or Bayesian credible interval, that quantity remains the primary result. A significance or discovery-reach question retains its metric and calibration requirements. An exclusion value is not a discovery significance.

The statistical model follows available evidence: applicable published likelihood, supplied covariance/simplified model, constructed likelihood, then justified counting. Every omitted correlation or uncertainty source needs a stated reason. Acquire the physical inputs required by the selected method and retain their provenance. [Inference engines](../reference/inference-engines.md) and [scope](../reference/scope.md) define the methods, validity checks and labels.

## Separate preparation from authorized execution

Before CHECK-IN 1, RAVEL can read sources, inspect supplied data, prepare configurations and calculate a cost proposal within the preparation contract. Event generation, including a smoke run, requires actual approved execution authority. A plan states its rungs and resources; the controller checks them again before launch.

| Rung | Meaning |
|---|---|
| `none` | No scientific execution; source/context and administrative preparation |
| `dry` | Render or validate configurations and inputs without event generation |
| `smoke` | Small approved execution to test the selected chain and waypoint |
| `pilot` | Matched approved execution that calibrates the next resource forecast |
| `full` | Complete approved point or scoped calculation |
| `scan` | Approved repeated computation over the declared population |

A route with a declared waypoint asks for reviewed CHECK-IN 2 evidence and GO before the dependent work. A scope change needs its own current approval. Final acceptance uses the original task census, fresh required review and CHECK-IN 3. A checkpoint or resume command supplies no authority. See [controller boundaries](../architecture/controller.md).

## Open questions and proportional work

An open question enters framing and decomposition, preserving every original requirement. A research campaign records rivals, prospective predictions and discriminating child studies. Before each cycle it records expected gain, evidence and projected cost. It stops on a recorded low-gain judgment or exhausted approved remainder and produces a progress or qualified synthesis.

Lean, standard and full engagement organize compatible review duties in proportion to source-checked complexity. Unknown complexity keeps full engagement. Child experiments receive their own tier and reservation; a full research parent does not force every child to use the same tier. Required tools, independence and physical validation remain obligations at every tier. [Research architecture](../architecture/research.md) explains the budget and stopping mechanisms.

## Read the ending literally

An accepted delivery means the current source's required result-path checks, review, authority and artifact custody satisfied the declared scope. Each additional model or domain requires its own applicable validation evidence. A qualified delivery retains useful evidence and states unresolved assumptions, failed checks, missing inputs or unfinished obligations. A diagnostic result establishes its stated software or numerical diagnostic. A hold names a boundary and what would release it.

The controller records tool-composition plans, research campaign preparation, deterministic literature retrieval and short-note assembly through their source-bound contracts. See [execution](../architecture/execution.md) and [research](../architecture/research.md) for source and evidence links.

For any study, retain the receipt with its artifacts. It identifies current evidence, qualification, review, included uncertainty, missing measurements and remaining work. [Safety and provenance](../architecture/safety.md) explains private inputs, visible artifact notices and explicit export.
