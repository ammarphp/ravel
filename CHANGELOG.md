# Changelog

## 1.3.0

Adds a checkpointed controller for open-ended research, cost-aware engagement, a research loop with a declared budget, a generated capability catalogue, literature retrieval with provenance screening, and governed model seats for any provider.

**Controller**

- Any question runs from request to reviewed delivery under a LangGraph controller with durable checkpoints. A resumed run keeps its pinned source and dependency identities.
- When an input, tool or licence is missing, the run records an alternative or ends in a qualified result that lists its open obligations. Unaffected work continues after a failed step, and recorded assumptions travel with the result as qualification.
- Each obligation is checked and recorded by the action it governs. A not-applicable entry carries a typed reason and its evidence.

**Engagement and cost**

- Lean, standard and full engagement tiers are chosen from the route, deliverables, consequence, compute and novelty of the task. A needed tool runs at every tier, and observed failures raise the tier.
- `ravel operator set --compute-policy` selects bounded, generous or adaptive compute within the operator's ceiling.
- Model usage and cost are measured per session alongside compute. `ravel setup-models` uses account usage and prior runs to choose the model mix per tier.

**Statistics**

- A catalogue of statistical situations covers limits, fits and measurements, with a probe for each situation. Deliveries state the uncertainties they include and the assumptions they rest on.

**Capabilities and knowledge**

- The capability catalogue is generated from code: science modes, operations, routes, role cards, tools and knowledge entries. Every role receives it in its instruction packet.
- A searchable knowledge atlas links each entry to its source.

**Research and literature**

- The research loop declares its cycles, children, model calls, tokens, time and cost before CHECK-IN 1. It stops on a recorded low expected information gain or an exhausted budget, and reuse requires current source, premise and input identities.
- Literature retrieval runs over immutable indexed snapshots with lexical, dense and hierarchy-aware search. Excluded roots and derived-origin lineage are screened together, and a citation names the material served.

**Models and providers**

- Roles, seats and transports are separate. Any wired provider reaches the governed path, and selection checks the executable, tool surface and qualification record for the seat.
- `ravel doctor` reports the wired transports.

**Sites and batch**

- Prepared studies submit and run as batch jobs through `ravel site study-job`, including HTCondor, and export to Snakemake with `ravel site-workflow`.
- Sandbox detection and site setup adapt a run to its host, and optional tools fall back to compatible alternatives.

**Safety**

- Inputs default to restricted classification and narrow the provider policy of the run. Artifacts are private, destinations are checked, and a resumed run checks the integrity of its record.
- `ravel operator init` and `ravel operator set` keep the operator ledger in a user-owned file. `ravel operator export-run` backs up a quiescent run for restore.
- A conditional approval labels the results it covers, and a tampered autonomy or batch ledger ends the run.

## 1.2.3

Fixes HTCondor submission and Snakemake profile loading.

- HTCondor sites can select their own queue attribute.
- The generated Snakemake profile loads on Snakemake 9.
- A refused HTCondor submission keeps its submit file and error. A validation-only dry-run is allowed.

## 1.2.2

Fixes a race in worker completion.

- A worker run now reports completion only after every process it started is confirmed gone. Stopping a worker waits for its supervisor and child processes to exit, and reports it when they do not.

## 1.2.1

Adds measured fault diagnosis with verified repair, bounded unattended endings, research objectives with retained scope, and a checked chain from generated events to limits.

**Diagnosis and repair**

- Fault injection: single planted faults in cards, selections, normalization, templates and inference are scored against matched untouched controls. Each case records detection, first affected stage, discriminating test, repair, rerun of the affected descendants only, and the corrected conclusion.
- A discrepancy is followed to a contrast and a correction. The repair counts only after the affected descendants have rerun and the final quantity agrees with an independent reference.
- Boundary events for a candidate routine are built from a reconstructed event and checked against an independent oracle. A disagreement is reduced to a minimal event, and the whole original population is rerun after the correction.

**Unattended and reviewed work**

- A run that makes no progress ends in a qualified report: repeated unchanged send-backs and exhausted correction budgets list the open obligations and narrow or withdraw the claim.
- Evidence obligations are typed. Copied source content and unsupported claims of method independence are refused, and executed reviewer checks keep their credit only while worker custody holds.
- Every delivery route checks limitations against the accepted claim scope. A submitted defect names the stage that owns it.
- An optional investigator team with boundary review, and bounded exploration of alternatives that records where each reference came from.

**Research objectives**

- Regional and uniform improvement claims, separate cost and accuracy requirements, and complementary candidate coverage.
- Search retention is separate from improvement verdicts. Paired differences use recorded same-event covariance, and an opt-in allocator spends effort where the expected information is largest.

**Generated events to limits**

- Event generation, selection and signal templates are bound to the exact sample bytes, exposure, weight moments, selection mapping, normalization, included factors and covariance. A missing fact stays a located obligation.
- A new operation in this chain registers from a single declaration.

**Testing and installation**

- Test files carry measured fast, medium and slow tiers, and public CI balances its shards by measured duration.
- The test runner and the cosmology solvers are optional extras of the package. The complete installer still installs them.
- Parallel scheduler status calls share one query. Report files keep their names when a parent directory name contains `.md`.

## 1.2.0

Adds governed HTCondor launches, project-wide provider defaults, MCFM amplitudes and the capabilities below.

**Facility runs**

- HTCondor projects: `ravel wms init --profile htcondor` pins a site profile, declares shared state and a job ceiling, and launches with zero scheduler retries. Only the exact approved launch command is admitted.
- Batch-slot leases in the HTCondor job scratch directory.
- A project default for data classification and the provider allowlist. Every new run inherits it, and a run or an amendment can only narrow it. A missing or altered default refuses dispatch.

**Scans and grids**

- Study grids: prepared study manifests across a grid of batch allocations, with bounded concurrency, explicit supersession and typed harvest.
- Per-point setting overrides for native scans and study grids. Overrides are part of the point identity, run as separate attempts, and are marked in harvests and plots.
- Native quantity outputs carry their hashes; harvest refuses a missing, unlisted or changed file.

**Calculations**

- MCFM per-point helicity amplitudes for interfering resonances, released and qualified on Linux x86_64.
- A producer's phase-space safety cuts apply when each point is drawn, so exposure and normalization stay exact for the restricted phase space.

**Checks on scientific work**

- Generation coupling-order conventions are recorded, and a fit whose terms, basis, scheme or cutoff differ from the generation is refused.
- Quantity descriptors are checked on every composition edge, including weight conventions.
- One owner per scientific quantity; a graph with two producers of the same quantity is refused.
- Review findings are classified: defects go to repair at their exact target, limitations go to the census and narrow or withdraw the claim.

**Agent hosts**

- One shared guard for every host. Codex, Gemini, opencode and Antigravity get generated hook adapters and gate shims, and each host's enforcement level is documented.
- Approval-checked PATH shims for native tools.

**Testing**

- Linux portability fixes.
- Public CI runs each test file in its own time-limited process; the two long files run in jobs of their own.

## 1.1.0

Restores the general analysis knowledge removed in 1.0.0 and adds the capabilities below.

**Restored general analysis knowledge**

- Routine catalogue: 633 entries (554 Rivet, 79 SimpleAnalysis) with source and asset identities.
- Native routines, generation recipes, leading-order normalization tables, published-likelihood inputs and channel mappings.
- Bundled routine sources and reference assets, including the cumulant routine and its Rivet and YODA sources.
- Ntuple-analysis selection tables and branch roles.

**Recasting capabilities**

- Yield routing from analysis request to routine, detector and statistics operations.
- Source restriction, delivery into a supplied workspace and generation controls.
- Columnar trust checks and event-level weights.
- 13 TeV NLO+NLL tables for gluino, squark, stop and sbottom pair production with three PDF sets.

**Ntuple-campaign capabilities**

- Workflow-manager-first runs, prompt logs and project instructions delivered to every agent.
- Relocatable submissions, a conformance check and site installation with an HTCondor profile.
- Physics objects from energy and mass, object weights and trigger selection.
- Rucio dataset handling at scale, columnar skims and classifier training.
- Irregular-grid statistics, a provider allowlist and site tool admission.

**General tools**

- Complete executor table, lineshape operations, a Rivet-to-fit link and a general four-lepton workflow.
- One study per batch allocation on Slurm clusters.
- CheckMATE, IRIS and manuscript builds released.

**Documentation and release checks**

- A rewritten README with defined terms, a glossary and a full reference list.
- Methodology pages on the agent architecture, the research loop and Recursive Decision Justification.
- A capability-regression gate: every capability of earlier releases is present, renamed or an approved removal.
- Public CI runs the test suite in parallel shards.

## 1.0.0

First public release.

- Ask a research question in plain words. RAVEL writes the specification and the plan, starts heavy work after your approval, and reviews the evidence.
- Operations for limits and statistics, reinterpretation of published searches, event generation and simulation, model building and theory, studies of your own data, parameter scans and cosmology.
- An installer for the full toolchain, and `ravel doctor` to check it.
- Every reported value links to its inputs, tool versions and decisions.
