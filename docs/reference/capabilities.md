# Capabilities

Start with the [release scope](scope.md), then choose a
[study guide](../guides/study-types.md). The complete
[documentation inventory](documentation-inventory.md) joins code declarations
to reference pages. Its [JSON form](documentation-inventory.json) gives stable
identifiers and source locations.

## Scientific work

| Family | Reference |
|---|---|
| Generation, showering and simulation | [Event production](event-production.md) |
| Event selections and supplied arrays | [Analysis admission](analysis-admission.md), [columnar modes](columnar-analysis-modes.md) |
| Models, spectra, amplitudes and normalization | [Models and normalization](models-and-normalization.md), [domain adapters](domain-adapters.md) |
| Likelihood construction, inference and uncertainty | [Statistics core](statistics-core.md), [inference engines](inference-engines.md), [statistical construction](statistical-construction.md) |
| Supplied quantities and measurements | [Quantities and measurements](quantities-and-measurements.md) |
| Parameter scans and sampling | [Parameter-space sampling](parameter-space-sampling.md) |
| Research and literature | [Research appendix](../architecture/research.md), [knowledge](knowledge.md) |
| Machine learning | [Execution appendix](../architecture/execution.md), [study guides](../guides/study-types.md) |
| Reports, manuscripts and diagrams | [Scientific reports](scientific-reports.md), [manuscript production](manuscript-production.md), [model-bound diagrams](model-bound-diagrams.md) |
| Batch workflows | [Site workflows](site-workflows.md), [batch allocations](batch-allocations.md) |

## How capability facts are assembled

`ravel.workflow.capability_catalogue` joins science modes, operation signatures,
route contracts, role cards, tools and knowledge entries. Deciding seats receive
the catalogue through their governed instruction packets.
`ravel.controller.capabilities` provides the sealed planning view.
`ravel.workflow.knowledge_atlas` supplies searchable source-linked knowledge.

The catalogue distinguishes registration, adapter availability, prerequisites,
tool qualification and scientific qualification. The selected adapter's contract
defines its input, execution and output requirements.
The [tool-status table](tool-status.md) records installation declarations;
`ravel doctor` reports the current machine.

## Interfaces and evidence

The [CLI reference](../cli.md) covers user commands. The
[parser reference](../cli/commands.md) lists commands, subcommands and options.
[Configuration](configuration.md) describes operator, model, transport, site
and study settings. [Output records](outputs.md) connects results to the
checkpoints, approvals, execution records and receipts that support them.

Source registration, software tests, live tool checks and scientific closure
answer separate questions. The [scope page](scope.md#scope-boundaries) states
their boundaries; each delivered result records the evidence actually obtained.
