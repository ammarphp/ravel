# Ravel-HEP

Ravel helps collider-physics researchers run and review reinterpretation workflows,
with task contracts, approval checks, artifact provenance, and validation.

[![CI](https://github.com/ammarphp/ravel/actions/workflows/ci.yml/badge.svg)](https://github.com/ammarphp/ravel/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Use the command-line tools to validate a task contract, replay a bundled statistical
benchmark, or inspect a research checkout. Full simulations use the native HEP
toolchain: MadGraph, Pythia, Delphes, Rivet or SimpleAnalysis, and pyhf. Ravel provides
the workflow and checks around these tools.

## Try a cached replay

With Python 3.12 installed, run:

```bash
git clone https://github.com/ammarphp/ravel.git
cd ravel
python3.12 -m venv .venv-replay
.venv-replay/bin/python -m pip install --require-hashes -r requirements-replay.lock
.venv-replay/bin/python -m pip install --no-deps .
.venv-replay/bin/ravel replay --out ravel-replay-example
```

A successful run ends with `GATE: OK` and writes results, environment details, and
logs to `ravel-replay-example/`. Choose a new output directory for each run;
existing results are preserved. Installation details and alternative setup commands
are in the [installation guide](docs/installation.md).

This example freshly checks statistics using cached simulation inputs. Acceptance
certification may come from the recorded baseline. It does not generate events or
reproduce the complete analysis.

## Next steps

- [Use the CLI](docs/cli.md) for task validation, replay, and checkout audits.
- [Start a physics workflow](docs/workflow/start.md) to scope a question and prepare
  a run plan. Native execution is the default; full simulations need the separately
  installed HEP tools and the workflow's approved plan.
- [Review validation results](docs/validation/results.md), including the scope of
  each comparison, failures, and missing evidence.
- [Explore the documentation](docs/README.md) or [contribute](CONTRIBUTING.md).

Ravel is research software. Supported analyses have different validation limits;
check the [capabilities](docs/reference/capabilities.md) and
[limitations](docs/reference/limitations.md) before applying it to a new analysis.

## Help and citation

Report problems through [GitHub Issues](https://github.com/ammarphp/ravel/issues).
See [CITATION.cff](CITATION.cff) for citation information and
[third-party acknowledgements](docs/reference/third-party.md) for upstream tools.
Licensed under [Apache-2.0](LICENSE).
