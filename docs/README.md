# Documentation

Install the toolchain, configure model access, then choose a study route.
The controller keeps the question, approvals, execution and delivery connected.

## Getting started

| I want to… | Read |
|---|---|
| Install Ravel and check the installation | [Installation](installation.md) |
| Validate a contract or run a single command | [Command guide](cli.md), [parser reference](cli/commands.md) |
| Reproduce or reinterpret a published analysis | [Start a physics workflow](workflow/start.md) |
| Analyze supplied events or models | [Scientific studies](workflow/reference/scientific-studies.md), [quantity and measurement contracts](reference/quantities-and-measurements.md), [domain adapters](reference/domain-adapters.md) |
| Follow an existing run | [Session guide](workflow/session-guide.md), [resume across upgrades](workflow/run-directory.md#resume-across-upgrades) |
| Classify inputs and choose network access | [Data and transport policy](workflow/reference/provider-policy.md) |
| Share or back up a run | [Private runs and sharing](workflow/run-directory.md#private-runs-and-sharing), [export and restore](workflow/run-directory.md#export-and-restore) |
| Check delivery status | [Outcomes and exit codes](cli.md#work-command-outcomes), [artifact labels](workflow/run-directory.md#labels-on-delivered-artifacts) |
| Understand what is supported | [Capabilities](reference/capabilities.md) and [scope](reference/scope.md) |

## Study and architecture guides

[Study types](guides/study-types.md) maps each scientific intent to its route and
contract. The [architecture appendices](architecture/README.md) explain the
controller, research loop, execution, providers and safety with diagrams and
legends. [Configuration](reference/configuration.md), [output records](reference/outputs.md)
and the [source-derived inventory](reference/documentation-inventory.md) provide
complete interface references.

## Methodology

The [methodology pages](methodology/README.md) describe the [agent architecture](methodology/agent-architecture.md),
the [research loop](methodology/research-loop.md) and
[Recursive Decision Justification](methodology/decision-justification.md).

## Using and checking results

The [workflow guide](workflow/README.md) connects the numbered steps, analysis
choices, and checklists. [Task-contract reference](reference/task-contract.md)
defines the fields that make a request executable and reviewable.

[Scientific result contracts](reference/scientific-results.md) explain limits, scan bounds and artifact-bound certificates. [Durable execution](workflow/reference/durable-execution.md) explains stage reuse, interruption recovery and the current-state packet.

## Build and contribute

- [Build, test and release](build-and-release.md): package layout, generators and release gates.
- [Contributing](../CONTRIBUTING.md): environment setup and change validation.
- [Directory index](../DIRECTORY.md): repository layout.
- [Third-party notices](../THIRD-PARTY-NOTICES.md): redistributed code and licences.

## Analysis expansion

The package ships a pinned snapshot of the public Rivet and SimpleAnalysis routine metadata, so
`ravel analyses` ([command-line reference](cli.md)) discovers routines offline. Build a fresh
catalogue from your own checkouts with `ravel catalogue`; it outranks the snapshot. Neither
demonstrates physics support.

The source-bound continuation references cover [literal source tables](reference/source-tables.md), [complete-group arithmetic](reference/full-cohort-arithmetic.md) and [registered historical helpers](reference/registered-historical-helpers.md). Source transport and engineering checks do not qualify scientific results.

- [Source classifier inputs](reference/classifier-inputs.md): static tensor census and declared scalar preparation; inference obligations remain.

- [Quantity-bound scientific reports](reference/scientific-reports.md): requested quantities, exact selected facts and retained draft corrections.

- [Scientific phase reservations](reference/scientific-phase-reservations.md): reserve pending checks before constructing or polishing candidates.

- [Model-source bundles](reference/model-sources.md): complete supplied source preservation, cache and optional provider boundaries.

- [Failed-stage diagnostic review](workflow/reference/failed-stage-review.md): preserve partial outcomes for critique and a separately admitted successor.

- [Initialized-settings qualification](reference/initialized-settings-qualification.md): bounded current-wrapper checks on 32 retained events; native qualification is separately admitted.

- [Native event-group acquisition](reference/native-group-acquisition.md): retain complete groups, RAW primitives and whole native inventory with separate execution custody.

- [Workspace combination](reference/workspace-combination.md): complete original-law preservation, explicit correlations and count-once auxiliary compilation.

- [Connected research cycle](reference/connected-research-cycle.md): hypothesis-led ordinary experiments, bound critiques, constructive revisions and quantity-aware synthesis.

- [Supplied-point Ward diagnostic](reference/model-ward.md): exact two incoming gluon slots, bound source/card/points and separate zero-width scope.
