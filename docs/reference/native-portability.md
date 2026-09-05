# Native portability on macOS

Ravel's Python replay environment and optional HEP toolchain are separate. The
native helpers now distinguish Apple Silicon, Intel and Rosetta processes, select
the matching installer, and use explicit conda environment prefixes. This removes
host-specific assumptions from these helpers. It does **not** establish that the
complete HEP stack installs or reproduces physics on every Mac.

## What has been checked

On 2026-09-05, read-only checks on the existing macOS 15.5 Apple Silicon installation
passed all 33 native prerequisites, including the optional RJR dependency. Shower,
RJR and RestFrames build dry runs resolved the installed compiler and SDK without
compiling or changing the toolchain. The targeted fake-tool suite passed 54 tests,
and the existing package-path suite passed another two.

The new CI job uses Python 3.12 on `macos-15-intel` (`x86_64`) and `macos-15`
(`arm64`). It asserts the actual kernel and Python architecture, tests an absent
installation, and exercises fake tools. These labels follow the
[GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Adding the job is not evidence of a completed remote CI run. Neither a clean Mac
installation nor native Intel HEP execution was exercised in the local check.

The native setup recipes require macOS 11 or newer. Older macOS, non-macOS builds,
and mixed Intel/ARM environments are outside these recipes. They remain distinct
from platforms supported by the Python-only replay package.

## Inspect before provisioning

With Ravel installed in the supported Python 3.10–3.12 environment:

```bash
python -B -m ravel.validation.native_doctor --json --require-rjr
```

From a source checkout, the equivalent command is:

```bash
python -B scripts/run.py ravel.validation.native_doctor --json --require-rjr
```

This command does not download, install, compile, repair environments, generate
events or change cards. It inspects files and runs bounded version/configuration
queries. Exit status 0 means its selected prerequisite checks pass; 1 means at
least one blocker was found. Missing dependencies remain visible in the JSON.
Package discovery does not exercise imports or prove ABI compatibility. A passing
preflight supplies no compute authorization or physics certification.
Python subprocess probes suppress bytecode writes, including isolated interpreters.

Use `--profile bootstrap`, `mg5`, `shower`, `recast` or `native` to select checks.
`--require-rjr` additionally checks the RJR executable and RestFrames library.
The default `native` profile includes the mapyde converter asset used by the
current native executor. It does not check analysis-specific cards, likelihoods
or approvals; the execution planner checks those separately.

The doctor accepts `--build-root` and `--binary-dir` for read-only inspection.
For setup and execution, use the shared environment variables instead:

```bash
export RAVEL_NATIVE_BUILD="$HOME/.local/share/ravel-native"
export RAVEL_NATIVE_BIN="$RAVEL_NATIVE_BUILD/bin"
source native/scripts/paths.sh
```

Use absolute paths. A new Miniforge prefix must not contain whitespace; the
bootstrap helper refuses it before downloading. Build argument handling preserves
spaces in supplied source, compiler and library paths, but this is not a promise
that every upstream build system supports them. `BUILD_DIR` is a compatibility
alias for `RAVEL_NATIVE_BUILD`; conflicting values fail. Existing source
installations retain the legacy build location when no override is given. An
installed wheel needs explicit native paths because native binaries are not
packaged. Compiling the C++ helpers also requires a source checkout.

## Bootstrap with reviewable pins

From the checkout, preview each applicable setup step:

```bash
bash environment/scripts/00-install-miniforge.sh --dry-run
bash environment/scripts/01-create-env.sh --dry-run
bash environment/scripts/02-get-madgraph.sh --dry-run
```

Later steps require their earlier prerequisites to exist. A missing prefix is a
blocker, not a reason to silently fall back to a different conda installation.
Remove `--dry-run` only when intentionally provisioning the selected user-owned
prefix. These commands do not require shell initialization or administrator rights.
Apple's SDK/Command Line Tools must already be available for compilation; the
helpers report missing SDKs without invoking an installer.

The bootstrap pins Miniforge **26.5.3-0** and the upstream SHA-256 for each macOS
architecture. It verifies the downloaded installer before execution and never
follows `latest`. The assets and checksums were checked against the
[official release](https://github.com/conda-forge/miniforge/releases/tag/26.5.3-0).
This pin applies to new installations; an existing native prefix is not upgraded
or rewritten. The bootstrap's base Python is separate from Ravel's Python and
from the MG5 environment.

The MG5 environment recipe selects Python 3.10, the gfortran 13 series, make, six
and numpy from conda-forge using an explicit prefix and strict channel priority.
It saves `ravel-explicit-packages.txt` in the new environment after resolution.
These constraints and the resulting local record are **not** a pre-solved,
cross-platform lock. Conda solver availability and the full native dependency
closure have not been verified on a clean Mac.

MadGraph is pinned to the recorded `v2.9.27` commit
`eb76cab72b8d44aac7162ac7221ac08a4384a169`. A changed upstream tag, partial existing
checkout, different commit or tracked source modifications cause a refusal.
Checking out this version does not imply equality with a paper's generator
version or establish physics reproduction.

## Build helpers

These wrappers activate `rivet` or `recast` by **full prefix**, discover compiler
commands and flags, and verify that the selected compiler targets the native Mac
architecture. They reject Rosetta and conflicting `CONDA_SUBDIR` selections. No
hardcoded compiler triplet or automake version is needed.

```bash
bash native/scripts/pythia-shower-build.sh --dry-run
bash native/scripts/restframes-native-build.sh --dry-run
bash native/scripts/rjr-resolve-build.sh --dry-run
```

Shower compilation requires Pythia8/HepMC3 headers, libraries and config tools in
`rivet`. RestFrames requires ROOT, a matching C++ compiler, an automake auxiliary
file pair and the recorded SimpleAnalysis RestFrames tarball. RJR additionally
requires the built RestFrames library and headers. Library architecture comes
from Mach-O contents, including ROOT libraries whose filenames end in `.so`.

Dry runs probe prerequisites and print JSON commands with explicit temporary
output placeholders. They do not extract archives or compile. Remove `--dry-run`
to intentionally build. `--out` selects a destination; `--restframes` selects the
RJR library prefix. `OUT` and `RF_PREFIX` remain wrapper compatibility options.
An explicit `CXX` must resolve successfully; it is not silently replaced with a
different compiler. Flag strings are tokenized into arguments without shell
evaluation.

Build output is staged. Existing binaries are refused unless `--replace` is
explicit; failed compilation preserves the previous binary. An existing
RestFrames installation is always preserved: select a new `--out` destination,
then point the RJR build at it. RestFrames archives with traversal or link entries
are rejected before extraction. The build continues to omit the historical ROOT
dictionary, as the standalone resolver does not stream RestFrames objects.

## Remaining provisioning and validation work

The setup scripts cover Miniforge, the MG5 environment/source, and builds against
already supplied dependencies. A complete clean installation still needs a
versioned acquisition/build recipe for Delphes and the SimpleAnalysis source
tree, plus resolved environments for Pythia/HepMC, ROOT, mapyde assets and
statistics. The [environment inventory](environment.md) records the existing
installation; it is not that missing lock or recipe.

Preserve incomplete prefixes for inspection and select a new build destination
instead of deleting or repairing them implicitly. Run the doctor after supplying
each dependency, then inspect an analysis-specific native execution plan through
the [native pipeline interface](../workflow/reference/native-pipeline.md).
Generation still requires its bound task contract, exact plan and actual
approval. The old `environment/scripts/03-run-madgraph.sh` is a historical example
with source-specific assumptions, not the portable entry point. Container/Podman
helpers are also outside this native portability claim.
