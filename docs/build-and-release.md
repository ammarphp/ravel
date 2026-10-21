# Build, test and release

The source tree contains the Python package, native installation recipes,
declarative tool and role registries, user documentation and software tests.
The package build bundles declared workflow instructions and selected data.
Native executables are installed into their toolchain prefix.

## Development setup

Install the complete Python profile and required native prerequisites described
in [installation](installation.md):

```bash
python3.12 scripts/setup/python_installation.py
source .venv/bin/activate
python -m pip check
ravel --help
```

The host environment is `.venv`; required isolated engines use `.venv-smodels`
and `.venv-sfitter`. `pyproject.toml` defines package metadata, dependency groups,
the CLI entry point and the Hatch build backend.
`environment/python/installation.json` is the installation contract.

## Tests

Run a focused test file for the behavior being changed, then the required wider
suite. The default suite remains complete:

```bash
python -m pytest tests -q
python scripts/maintenance/ci_shards.py --tier fast --run --file-timeout 180
```

The shard runner starts one pytest process per file and retains every exit
status. File timing records determine scheduling; unmeasured files receive a
conservative allocation. Long tests have dedicated jobs. The public CI uses
Python 3.12, the hash-locked statistics layer and the full Python profile.
See [contributing](../CONTRIBUTING.md) for lock installation, full shard
commands, native prerequisites and failure reporting.

| Test area | What it checks |
|---|---|
| Unit and adapter tests | Typed inputs, numerical contracts, interfaces and failure handling |
| Controller composition | Planning, approvals, instructions, confined effects, review and delivery joins |
| Transport controls | Model/route identity, capture custody, qualification and budget checks |
| Documentation checks | Parser and capability coverage, configuration entries, links and generated-byte equality |
| Instruction checks | Source inventory, mirrors, delivery manifests and per-seat obligations |
| Packaging checks | Wheel/source contents, installed resources and import closure |
| Generality and scope | Published files, source identities, restricted material and neutral examples |

Software fixtures use synthetic inputs and controlled executables. Native and
scientific validation retain their own source, environment, data and acceptance
records.

## Documentation and generated files

Edit canonical sources, then regenerate their projections. Run the commands
from the repository root:

```bash
python scripts/maintenance/render_citations.py
python scripts/maintenance/render_component_inventory.py
python scripts/maintenance/sync_instruction_bundle.py
python scripts/maintenance/build_instruction_catalogue.py
python scripts/maintenance/render_documentation_inventory.py --write
python -m ravel.workflow.knowledge_atlas --write
```

Role or skill changes also use the corresponding agent-surface builders.
Their generated mirrors are checked against the source registries.
`hatch_build.py` rejects stale bundled instructions and undeclared package
members. The [documentation inventory](reference/documentation-inventory.md)
connects each exposed capability to its documentation entry.

## Build artifacts

```bash
python -m build
```

The build produces a source archive and wheel under `dist/`. A release check
installs these artifacts into fresh environments, checks package contents and
resources, and rebuilds a wheel from the source archive. The resulting evidence
binds the artifact bytes and source identity.

## Release gates

Release preparation selects the product tree, regenerates its derived records
and checks scope, generality, licences, documentation and package integrity.
The selected tree receives the full required test and composition checks.
Live transport qualification has its own operator authorization.
Evidence records bind the candidate and the gate outcomes; publication follows
the release's approval and signing procedure.

A successful software gate establishes its tested contract. Scientific claims
travel with their separate numerical, detector and analysis-validation evidence.
