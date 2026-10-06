# Installation

The package is named `ravel-hep`; its command and Python import are `ravel`.
Install from this repository or a built wheel. The commands below do not assume a
PyPI release.

## Python tools and cached replay

Use Python 3.12 for the committed replay lock. The package declares Python
3.10–3.12 support; the recorded clean replay environment used CPython 3.12.13 on
macOS ARM64. See the [CLI reference](cli.md) for that check's scope.

From a new checkout:

```bash
git clone https://github.com/ammarphp/ravel.git
cd ravel
python3.12 -m venv .venv-replay
.venv-replay/bin/python -m pip install --require-hashes -r requirements-replay.lock
.venv-replay/bin/python -m pip install --no-deps .
.venv-replay/bin/ravel --help
.venv-replay/bin/ravel replay --out local-runs/replay-example
```

The dependency lock checks downloaded distribution hashes. `--no-deps` keeps the
package installation from replacing those resolved dependencies. The build backend
is pinned separately in `pyproject.toml`.

If you use `uv`, the equivalent setup is:

```bash
uv python install 3.12.13
uv venv --python 3.12.13 .venv-replay
uv pip sync --python .venv-replay/bin/python --require-hashes requirements-replay.lock
uv pip install --python .venv-replay/bin/python --no-deps .
.venv-replay/bin/ravel replay --out local-runs/replay-example
```

Use one setup method and a new output directory for each replay. The directory
contains `results.json`, `environment.json`, and `work/` with subprocess logs and
statistical outputs. Failed attempts retain their output directory too.

The installed replay works outside the checkout and needs no network after
installation. It refits one benchmark from bundled inputs. Event simulation is
cached; acceptance certification may also be cached. `GATE: OK` means this scoped
regression passed. Full interpretation is in [validation results](validation/results.md).

## Native simulation tools

Native execution is the default for full physics workflows. It needs a separate
HEP toolchain: generator and compiler, shower, analysis tools, detector simulation
where applicable, and published analysis inputs. Installing the Python replay
package does not provision those tools.

Follow [environment provisioning](workflow/steps/01-environment.md) and the
[native pipeline guide](workflow/reference/native-pipeline.md). The
[environment directory](../environment/README.md) explains the bootstrap helpers;
the [recorded tool inventory](reference/environment.md) provides version and build
context. A container backend remains available for analyses that require it.

Before generating events, enter through [the physics workflow](workflow/start.md)
and complete its plan, input review, cost estimate, and approval. Keep simulation
outputs with the run's evidence.

## Development

Use [CONTRIBUTING.md](../CONTRIBUTING.md) for editable installation, test commands,
and review expectations. Dependency and wheel maintenance are documented in the
[CLI reference](cli.md).
