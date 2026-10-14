# Native simulation helpers

Native execution is the default for Ravel's full simulation workflow. This
directory contains the toolchain manifest, the C++ bridges and the shell scripts
that connect the HEP tools installed by `bash scripts/setup/install.sh`.

| Path | Role |
|---|---|
| `src/pythia_shower.cc` | Pythia8 to HepMC3 shower bridge |
| `src/pythia_shower_merged.cc` | Bridge for the merged-generation route |
| `src/rjr_resolve.cc` | Recursive-jigsaw resolver using RestFrames |
| `scripts/run-pipeline-native.sh` | Native execution chain for configured runs |
| `scripts/restframes-native-build.sh`, `scripts/rjr-resolve-build.sh` | Native build helpers |
| `scripts/run-pipeline.sh`, `scripts/pipeline-env.sh`, `scripts/start-podman-vm.sh` | Container fallback helpers |
| `setup/toolchain-manifest.json`, `setup/pdf-sets.json` | Every tool and PDF set the installer provides, with pinned sources and readiness checks |
| `setup/recipes/`, `setup/wrappers/` | Build recipes and container wrappers used by the installer |

Begin with [installation](../docs/installation.md), then follow
[environment provisioning](../docs/workflow/steps/01-environment.md) and the
[native pipeline guide](../docs/workflow/reference/native-pipeline.md). The
[tool inventory](../docs/reference/environment.md) records compiler and upstream
software requirements. Build products and installed environments remain local.

For a new physics task, use [the workflow entry point](../docs/workflow/start.md)
to establish the inputs, applicable analysis, output location, resource budget,
and approval before launching generation. These scripts are execution components;
the approved task contract and lifecycle checks supply the surrounding workflow.

Native parity and timing depend on the routine and configuration. Check
[capabilities](../docs/reference/capabilities.md) and
[limitations](../docs/reference/limitations.md) for analysis-specific boundaries.
