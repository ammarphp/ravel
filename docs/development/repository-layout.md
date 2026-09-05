# Repository layout

The public repository is organized around using, extending, and checking the software.
The research workspace uses the same active source layout and retains additional historical
run records. The export process selects the public files explicitly.

| Directory | Contents |
|---|---|
| `src/ravel/` | Importable Python package and command-line interface |
| `src/ravel/physics/` | Simulation adapters, statistical inference, and reinterpretation calculations |
| `src/ravel/workflow/` | Routing, run state, provenance, scheduling, and resource acquisition |
| `src/ravel/validation/` | Input, lifecycle, result, and benchmark checks |
| `src/ravel/plotting/` | Figure extraction, plotting, and presentation helpers |
| `src/ravel/data/` | Read-only tables, templates, and packaged fixtures |
| `native/` | C++ sources, native build helpers, and pipeline launch scripts |
| `environment/` | Optional simulation-tool provisioning |
| `benchmarks/` | Benchmark definitions, recorded baselines, scan specifications, and evaluation tooling |
| `tests/` | Unit tests, adversarial scenarios, and test fixtures |
| `scripts/` | Repository checks, documentation generation, and maintenance commands |
| `docs/` | User guides, workflow instructions, reference material, and contributor documentation |
| `evidence/` | Curated research artifacts, evidence manifests, and their source identities |

Start at the [documentation index](../README.md) for user tasks or
[CONTRIBUTING.md](../../CONTRIBUTING.md) for development commands.

## Naming conventions

- Python modules and tests use lowercase `snake_case`, with `test_` for test modules.
- Shell scripts and prose documents use lowercase `kebab-case` names.
- Directory names describe their contents. Internal project phases and change-request
  numbers are not the primary names of public software directories.
- Conventional entry points retain their expected names, including `README.md`, `LICENSE`,
  `NOTICE`, `CHANGELOG.md`, `CITATION.cff`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md`.
- Agent platforms require `SKILL.md`; those files retain that name.
- Dates identify dated audit records. They are not required on maintained guides.
- Scientific identifiers and original artifact filenames retain their established spelling
  when changing them would obscure provenance or break an external format.

## Documentation boundaries

The root README explains what Ravel does, gives one working first command, and points readers
to the next task. It does not contain the capability board, benchmark tables, an architecture
essay, or a publication-novelty argument.

`docs/workflow/` contains operational instructions. `docs/reference/` defines interfaces,
scope, and limitations. `docs/validation/` explains measured comparisons and their evidence.
`docs/research/` contains research discussion and prospective experiments.
`docs/development/` describes maintenance, decisions, and development history.

Numerical publication claims remain checked at their dedicated validation destination.
Moving them out of the README does not remove the evidence checks.

## Historical records and public evidence

Original development runs keep their existing identities and bytes. They are not relocated
or renamed merely to make an old experiment look like a new product example.
The public evidence collection gives each selected group a readable destination and retains
its original run identifier in the collection registry.

The exporter verifies the source artifacts, applies only declared transformations, and then
checks the actual exported bytes. Its public directory map describes the shipped tree.
The research workspace's directory map also identifies local archives and tool installations.

New software must use package imports and the shared path helpers. Do not derive the
repository root by assuming a fixed number of parent directories. Native tool lookup retains
the existing local installation and supports explicit overrides; moving documentation must
not silently move or recreate that toolchain.

## Maintenance

When adding or moving a file, update its callers, documentation links, package resource
selection, and any export classification that applies. Check the public export independently
of the research checkout. Keep test collection and skipped-test reasons visible during a
migration so a missing directory cannot turn an omitted check into an apparent success.

See the [distribution policy](distribution.md) and [directory map](../../DIRECTORY.md).
