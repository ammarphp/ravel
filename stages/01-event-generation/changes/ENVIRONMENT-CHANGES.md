# Change registry — Environment & architecture

**Category: changes to the *computing environment*** (software installed, tools configured).
These are the things a reader of an eventual publication needs in order to reproduce the
analysis architecture. They do **not** touch the physics inputs (those are in
`DATA-AND-CARD-CHANGES.md`).

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
- **How:** `trial-runs/_infrastructure/restframes_native_build.sh` — extracts the
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
  sequence per `workflow/analysis-simpleanalysis/02-install-mapyde.md` (boot image + the one SA
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
Recipe and runtime verification: `docs/CLI.md`; scientific scope: `docs/development/2026-09-05-hardening.md`.
