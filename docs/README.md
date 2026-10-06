# Documentation

Start with a cached replay to try Ravel's statistical checks, or follow the physics
workflow when you have an analysis question and a configured native toolchain.

## Getting started

| I want to… | Read |
|---|---|
| Install Ravel and run the first example | [Installation](installation.md) |
| Validate a contract or replay cached inputs | [Command-line reference](cli.md) |
| Reproduce or reinterpret a published analysis | [Start a physics workflow](workflow/start.md) |
| Analyze supplied events or models | [Scientific studies](workflow/reference/scientific-studies.md), [quantity and measurement contracts](reference/quantities-and-measurements.md), [domain adapters](reference/domain-adapters.md) |
| Follow an existing run | [Session guide](workflow/session-guide.md) |
| Understand what is supported | [Capabilities](reference/capabilities.md), [scope](reference/scope.md), and [limitations](reference/limitations.md) |

## Using and checking results

The [workflow guide](workflow/README.md) connects the numbered steps, analysis
choices, and checklists. [Task-contract reference](reference/task-contract.md)
defines the fields that make a request executable and reviewable.

[Scientific result contracts](reference/scientific-results.md) explain limits, scan bounds and artifact-bound certificates. [Durable execution](workflow/reference/durable-execution.md) explains stage reuse, interruption recovery and the current-state packet.

Read the [results overview](validation/results.md) for the different validation
questions, then the [benchmark cases](validation/README.md) for their individual
outcomes. [Evidence checks](validation/evidence.md) explain how published claims
are bound to artifacts. The [native performance study](validation/native-performance.md)
records a particular implementation and timing comparison.

## Development

- [Contributing](../CONTRIBUTING.md): set up a development environment and check a change.
- [Directory index](../DIRECTORY.md): repository layout and where new files belong.
- [Third-party tools](reference/third-party.md): upstream software and attribution.

Use the current workflow and reference pages for operating instructions.

## Analysis expansion

Use `ravel analyses` ([command-line reference](cli.md)) and the
[frozen catalogue survey](../evidence/audits/2026-09-26-analysis-landscape/README.md) for
source-backed routine discovery. Neither demonstrates physics support.
