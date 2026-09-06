# Change registry — Environment & architecture

**Category: changes to the *computing environment*** (software installed, tools configured).
These are the things a reader of an eventual publication needs in order to reproduce the
analysis architecture. They do **not** touch the physics inputs (those are in
[the data and card registry](data-and-card-changes.md).

## September 2026 RRR closure additions and qualifications

The later pooled retry uses a separate immutable orchestration snapshot with the
same 95-file v5 inventory and only the independently reviewed full-completion reader
replaced. Actual scientific stage commands still run the original v5 sources. This
avoids authenticating old products against subsequently edited current-source paths;
the original failed fit and source-drift checks remain in the campaign history.
The loader checks exact inventory and import precedence and requires inherited
`PYTHONDONTWRITEBYTECODE=1` together with Python `-B`.

The native receipt context also depends on the invoking shell's PATH. On this host,
the source checkout working directory reproduces the original native environment
digest, while the DSRLab parent gives a different digest. Recovery used the recorded
context and did not weaken runtime comparison or rewrite receipts. These private host
environment values are excluded from public evidence. A context hash is not a complete
shared-library environment lock.

The subsequent [execution and resource follow-up](2026-09-06-rrr-execution-followup.md)
records the repaired timeout supervision, exact 95-file v5 runtime, stricter 1.26-million-event
admission ceiling and retirement of five inactive installation-test environments. All 26
physics modules and the numerical engine remain unchanged from the preceding frozen runtime.
The runtime requires inherited no-bytecode settings and rejects unmanifested files; the
recorded test-cache incident was reconciled before activation.

An isolated Python 3.14 virtual environment inherits the existing recast installation and
adds iminuit 2.32.0 for the explicitly selected JAX backend. Its installation evidence is
retained under `local-runs/rrr-closure/numerics/`; the original conda environments are unchanged.
The campaign builds a separate Pythia shower executable with checked configuration and
serialization failures, using the installed Pythia 8.312/HepMC3 toolchain. It preserves the
old executable. Run plans pin frozen Python source snapshots, selected executables and
virtual-environment configuration. These records do not lock every shared library or prove
equivalence to the RRR paper's earlier tool versions.

The older E3 claim that all MadGraph 2.9.x patch versions have identical LO physics was not
established by a controlled version comparison. Its historical wording below is preserved,
but must not be reused as a current methods claim. Record actual versions and measure
version sensitivity when it matters. The workflow-level description is the
[native execution reference](../../workflow/reference/native-pipeline.md); the interpretation
and limitations are in the [environment manifest](../../reference/environment.md).

> Scope note: the host had **no** Fortran compiler, **no** conda/brew/pyenv, and only a system
> Python 3.13. Everything below was provisioned **into the project** (`build/tools/`, gitignored)
> with **no administrator rights**. Nothing system-wide was modified.

## E1 — User-space package manager (Miniforge / conda)
- **What:** installed Miniforge to `build/tools/miniforge3` (conda **26.3.2**).
- **Why:** to obtain a Fortran compiler and a MadGraph-compatible Python without admin rights.
- **How:** `scripts/00_install_miniforge.sh` (downloads `Miniforge3-MacOSX-arm64.sh`, `bash … -b -p …`).
- **Methods phrasing:** *"A user-space conda environment was provisioned via Miniforge."*

## E2 — Isolated environment `mg5`
- **What:** conda env `mg5` = **Python 3.10.20**, **gfortran 13.4.0**, GNU make 4.4.1, plus
  **six 1.17.0** and **numpy 2.2.6**.
- **Why (each):**
  - Python 3.10 — MadGraph 2.9.x uses `imp`/`distutils`, removed in Python ≥3.12; the system
    Python 3.13 cannot run it.
  - gfortran — MadGraph's matrix-element / phase-space-integration core is Fortran; the host had none.
  - six, numpy — MadGraph 2.9.x runtime dependencies (`six` is mandatory at startup).
- **How:** `scripts/01_create_env.sh` + a `conda install … six numpy`.
- **Methods phrasing:** *"Events were generated with MadGraph5_aMC@NLO running under Python 3.10
  with gfortran 13.4 (conda-forge)."*

## E3 — MadGraph5_aMC@NLO source
- **What:** shallow git clone of tag **v2.9.27** (commit `eb76cab…`) → `build/tools/mg5amcnlo`.
- **Why:** the event generator. v2.9.27 is the latest 2.9.x on the official GitHub repo
  (`mg5amcnlo/mg5amcnlo`). The reference paper used v2.9.3, which is **not** tagged on GitHub
  (tags start at v2.9.10); LO matrix-element physics is identical across 2.9.x patch releases.
- **How:** `scripts/02_get_madgraph.sh`.
- **Methods phrasing:** *"MadGraph5_aMC@NLO v2.9.27 was used; LO results are insensitive to the
  2.9.x patch level."*

## E4 — MadGraph configuration edits
- **What:** appended 4 settings to `build/tools/mg5amcnlo/input/mg5_configuration.txt`:
  `fortran_compiler = gfortran`, `automatic_html_opening = False`, `auto_update = 0`, `run_mode = 0`.
- **Why:** force use of the conda gfortran; keep runs headless, non-interactive, and reproducible
  (single-core is the most reliable mode; raise for large samples).
- **How:** appended at MadGraph-acquire time (a `.orig` backup of the pristine config is kept).
- **Methods phrasing:** *"MadGraph was run single-threaded in non-interactive mode."*

## E5 — Native RestFrames (recursive-jigsaw library, for the VM-free recast path)
- **What:** built **crogan/RestFrames v1.0.1** natively (arm64) against the `recast`-env ROOT 6.40
  → `build/tools/restframes-native/{lib/libRestFrames.dylib, include/RestFrames/}`.
- **Why:** the EwkCompressed2018 (ANA-SUSY-2018-16) selection's R_ISR & M_S signal-region cuts are
  computed with RestFrames. SimpleAnalysis was the last container-only piece of the pipeline; a
  native RestFrames lets `trial-runs/_infrastructure/rjr_resolve` reproduce those two variables on
  this Apple-Silicon host with **no VM / no ATLAS AnalysisBase**, validated boolean-exact at the cuts.
- **How:** `native/scripts/restframes-native-build.sh` — extracts the
  `Ext_RestFrames/data/tarball`, swaps in the recast-env `automake-1.17` `config.guess`/`config.sub`
  (the 2016 ones don't know aarch64-apple-darwin), `./configure --with-rootsys=$(root-config --prefix)`,
  then compiles the 52 `.cc` sources straight into a `.dylib` (skipping the ROOT-6.40-incompatible
  `rootcling` dictionary step, which only matters for TTree streaming the standalone resolver never does).
- **Methods phrasing:** *"The recursive-jigsaw R_ISR and M_S observables were reproduced natively
  with RestFrames v1.0.1 built against ROOT 6.40, reading the Delphes→SimpleAnalysis ntuple."*

## E6 — RS UFO model added to the MG5 models library (2026-07-04)
- **What:** `import model RS` auto-downloaded the RS-graviton UFO (v2.1, P. de Aquino) from
  `madgraph.mi.infn.it/Downloads/models/RS.tgz` into `build/tools/mg5amcnlo/models/RS/`, then
  py2→py3-converted it in place via `set auto_convert_model T` (first import fails loudly on the
  py2 module; the converted model is what remains on disk).
- **Why:** the CMS A→BC dijet-substructure trial (`trial-runs/2026-07-04_CMS_2412.03747_ABC-dijet/`)
  needed a narrow s-channel resonance decaying to boosted 2-prong (G*→W⁺W⁻) and 3-prong (G*→tt̄)
  daughters; the pruned stock models dir (sm/loop_sm/MSSM_SLHA2/DMsimp_s_spin1) had no such state.
- **How (reproduce):** `set auto_convert_model T` + `import model RS` in any mg5 session (needs
  network on first use). Graviton = particle `y`, PDG 39; mass `MGr` (Block mass 39), width
  `DECAY 39`, scale `LRS` (frblock 1). Under `build/` → gitignored, regenerable.

## Host (for completeness)
macOS 15.5 (Darwin 24.5.0), arm64 (Apple Silicon), 8 cores. Apple Command Line Tools provide the
macOS SDK that conda's gfortran links against (`SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`).

## Reproduce the whole environment
```bash
bash scripts/00_install_miniforge.sh
bash scripts/01_create_env.sh
build/tools/miniforge3/bin/conda install -y -n mg5 -c conda-forge six numpy
bash scripts/02_get_madgraph.sh
```
Everything lands under `build/` (gitignored, regenerable).

## 2026-07-08/11 — HVT_UFO model installed (+ modified) in the MadGraph models dir
- Added `build/tools/mg5amcnlo/models/HVT_UFO` (gitignored build tree): the Heavy-Vector-Triplet
  UFO from the model authors' repo github.com/riccardotorre/HVT_tools (master tarball, fetched
  2026-07-08). Converted py2→py3 by MG5 2.9.27 `convert model` in place.
- LOCAL MODIFICATION (not upstream): `parameters.py` WVz/WVc changed internal→external (DECAY
  block) because the authors' analytic width formulas go complex below the tt̄ threshold — widths
  per point via MadWidth (`set WVz Auto`). Provenance + diff note:
  `trial-runs/2026-07-08_PROJ_hvt-zprime-ww-isr-boosted/inputs/model/PROVENANCE.txt`;
  failure-catalogue C9/C10. Reproduce: re-fetch tarball, `convert model`, apply the same
  externalization (or copy particles/parameters from the run's inputs/model/).

## 2026-08-16 — podman VM (mg-vm) + applehv boot-image cache DELETED (~12 GB reclaimed)
- Removed the `mg-vm` podman machine (applehv, 50 GiB sparse / 12 GB on disk, last up 2026-06)
  and the cached applehv boot image (957 MB): `podman machine rm -f mg-vm` + cache dir removal.
  ~/.local/share/containers is now empty (12 KB).
- Rationale: nothing has needed the container path since the 2026-06-16 native cutover (native
  flagship SA + native Rivet + the Option-D efficiency-map route serve current demand); the VM
  was cold for 2 months. Supervisor-approved 2026-08-16.
- The `pipeline` conda env (podman client + mapyde) is KEPT — re-provisioning is one command
  sequence per `docs/workflow/analysis-simpleanalysis/02-install-mapyde.md` (boot image + the one SA
  image ≈ 3–4 GB, ~30–60 min), and is now the STANDARD per-validation pattern: the container
  oracle is provisioned when a CR-005 port needs its bit-for-bit diff, then deleted again
  (see `framework/CR005-NATIVE-SA-GENERALIZATION.md`).

## 2026-08-16 (later) — CR-005 oracle round-trip + containers.conf
- Podman machine re-provisioned FOR the CR-005 validations and torn down after (machine rm +
  connection rm + cache dir): ~/.local/share/containers back to 0B. The per-use oracle pattern
  is now the documented standard (native-pipeline.md §porting step 5).
- NEW persistent host file: `~/.config/containers/containers.conf` sets
  `[engine] helper_binaries_dir` to the pipeline env bin (conda podman's $BINDIR expansion
  corrupts under `conda run`; without it `machine start` cannot find gvproxy). Harmless to keep.
- Gotchas recorded: machine lifecycle MUST use the native podman 5.8.2
  (stages/**/tools/podman-native/) — the conda podman's vfkit exits 1; `pipeline-env.sh` must be
  sourced under BASH (BASH_SOURCE corrupts its paths under zsh); after `machine rm`, stale
  `system connection` entries block re-init until `podman system connection rm mg-vm{,-root}`.


## 2026-09-05 — isolated Python replay distribution

Added `requirements-replay.lock` with transitive version/hash pins and an isolated CPython 3.12
replay environment. The `ravel-hep` wheel packages the existing engine sources and an explicit
cached-input allowlist. The new CLI uses its own interpreter and writes replay outputs into a
new user-selected directory. This does not alter the native MadGraph/Pythia/Delphes/Rivet stack.
The recorded full HEP environment remains an inventory, not a verified cross-platform lock.
Recipe and runtime verification: `docs/cli.md`; scientific scope: `docs/development/history/2026-09-05-hardening.md`.
CI uses Ubuntu 24.04 and Python 3.12 with the locked audit/replay dependencies. Checkout 7.0.1
and setup-python 7.0.0 are pinned by full commit SHA and use Node 24. The package job installs
the built wheel and runs its console entry point outside the checkout.

## 2026-09-05 — package and native path reorganization

Active Python implementations now live in `src/ravel/`, with separate physics, workflow,
validation, plotting, and data subpackages. The wheel uses those same implementations;
there is no second generated engine-source tree. Source commands use `scripts/run.py`.

Native sources and helpers moved to `native/` and provisioning helpers to `environment/`.
The existing ignored conda installation remains under the original stage build directory.
The three prebuilt native executables moved to `native/build/bin` with identical SHA-256
hashes and no rebuild. Fresh installations default to `native/build`; explicit
`RAVEL_NATIVE_BUILD` and `RAVEL_NATIVE_BIN` overrides support other locations. Original
process and parameter cards remain in place and are never normalized in place.

The isolated replay environment remains separate from the existing native Python environments.
This migration installs no new native physics tool versions and performs no event generation.
Source and installed replay, import boundaries, executable loading, and dependency compatibility
are checked separately. See `docs/development/repository-layout.md` and `native/README.md`.

## 2026-09-05 — Native portability helpers; installed stack preserved

Added architecture-aware prerequisite checks and dry-run/staged build helpers.
The bootstrap now selects Intel/ARM Miniforge 26.5.3-0 by pinned SHA256 and obtains
MadGraph at the pinned v2.9.27 revision. These are provisioning defaults, not claims
that the existing installed stack was upgraded. No native toolchain installation
or compilation was performed in this pass. Refit diagnostics use the existing
native Python 3.14/JAX environment separately from the supported Python 3.12 replay
lock. See `docs/reference/native-portability.md` and the dated RRR implementation
record for versions, verification scope and remaining clean-install requirements.

## 2026-09-06 — activated LHAPDF capture and isolated provenance builds

The new optional native LHAPDF path records activated compiler/linker flags, the
selected architecture and library, and the complete PDF-set inventory. A metadata
capture succeeded in the existing MadGraph Python 3.10 environment. Installed
MadGraph, LHAPDF and compiler files remain unchanged. Captures are path- and
context-bound; a capture for a development worktree cannot be reused as approval
for a relocated installation. No new-PDF event-generation result is credited.

The production original-LHA exercise completed an isolated build of the updated
shower wrapper and two 100-event plain/gzip showers, with separately captured
headers and libraries. Independent review verified all four receipts, complete
original-event joins and decoded byte equality. Earlier storage-floor and duplicate
library-input failures remain preserved. The completed historical replay has its
own separately built wrapper and evidence. Existing frozen scientific runtimes
and native binaries remain unchanged. Unit tests use the clean Python 3.12 replay
environment; guarded likelihood controls use their own pinned JAX environment.
The [implementation record](2026-09-06-native-provenance-and-fidelity.md) and
[native portability guide](../../reference/native-portability.md) distinguish
source tests, actual build exercises and full native physics execution.

Three additional inactive installation-test virtual environments were retired
after recording complete file/link inventories and package metadata and confirming
that current campaign sources and active processes did not reference them. Their
test logs and wheels remain available. Active HEP, replay and guarded JAX runtimes,
shared Python installations and physics products were preserved. The original
campaign ceiling, storage margin, derivative provision and free-space floor were
not changed; successful execution passed a fresh admission check.
