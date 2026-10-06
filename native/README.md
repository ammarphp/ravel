# Native simulation helpers

Native execution is the default for Ravel's full simulation workflow. This
directory contains the C++ bridges and shell scripts that connect the separately
installed HEP tools. It is not needed for the cached Python replay.

| Path | Role |
|---|---|
| `src/pythia_shower.cc` | Pythia8 to HepMC3 shower bridge |
| `src/pythia_shower_merged.cc` | Bridge for the merged-generation route |
| `src/rjr_resolve.cc` | Recursive-jigsaw resolver using RestFrames |
| `scripts/run-pipeline-native.sh` | Native execution chain for configured runs |
| `scripts/restframes-native-build.sh`, `scripts/rjr-resolve-build.sh` | Native build helpers |
| `scripts/run-pipeline.sh`, `scripts/pipeline-env.sh`, `scripts/start-podman-vm.sh` | Container fallback helpers |

Begin with [installation](../docs/installation.md), then follow
[environment provisioning](../docs/workflow/steps/01-environment.md) and the
[native pipeline guide](../docs/workflow/reference/native-pipeline.md). The
[tool inventory](../docs/reference/environment.md) records compiler and upstream
software requirements. Build products and installed environments remain local.

For a new physics task, use [the workflow entry point](../docs/workflow/start.md)
to establish the inputs, applicable analysis, output location, resource budget,
and approval before launching generation. These scripts are execution components;
the approved task contract and lifecycle checks supply the surrounding workflow.

The [native performance study](../docs/validation/native-performance.md) documents
specific parity and timing results. Those comparisons do not certify every
selection or guarantee the same runtime on another configuration. Check
[capabilities](../docs/reference/capabilities.md) and
[limitations](../docs/reference/limitations.md) for analysis-specific boundaries.
