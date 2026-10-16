# Environment manifest

The installed toolchain is defined by `native/setup/toolchain-manifest.json` (pinned commits, digests and
versions) and `native/setup/pdf-sets.json`, and by the Python requirement files in `environment/python/`.
This page summarizes them; when it disagrees with a manifest, the manifest is right. Run `ravel doctor --json`
to see what is installed on your machine: every group carries a `label` (ready, not-ready with its fix,
owner-action, remote or unsupported) and a recorded `qualification` (qualified, built-unqualified, failed or
not-built). Installed is not qualified; a qualification names an executed study, and the group's
`qualification_basis` says which.

For toolchain development, groups may also live in `native/setup/groups/<group-id>.json`.
Read `ravel.setup.manifest.view(root)` for the merged tree document or `load(root)`
for catalogue validation. The [fragment contract](../../native/setup/groups/README.md)
describes default membership, dependency order, release holds, the schema, the split
helper and `python -m ravel.setup.manifest view --canonical-sha256`.

## Python environments (the checkout)

| Environment | Contents | Pins |
|---|---|---|
| `.venv` | the RAVEL Python layer: pyhf 0.7.6 with `[minuit]`, mplhep 0.3.59, hepdata-cli 0.3.1, pyslha 3.3.2, CAMB 1.6.5, CLASS 3.4.1.0, Cobaya 3.6.2, ServiceX 3.3.1 | `requirements-full.txt`, `pyproject.toml` |
| `.venv-smodels` | SModelS 3.2.1 with NumPy 2 (isolated from the host NumPy 1.26) | `environment/python/requirements-smodels.txt` |
| `.venv-sfitter` | the SFitter environment with PyTorch 2.14.0 | `environment/python/requirements-sfitter.txt` and its replay lock |

The statistics-layer environment is separately version- and hash-locked in `requirements-replay.lock`; see the
[command-line reference](../cli.md). Site analysis libraries (coffea, cabinetry, vector, boost-histogram,
pyarrow) are provided by the analysis site's LCG view and are not pinned by RAVEL.

## Native toolchain (`bash scripts/setup/install.sh`, conda environments under the prefix)

| Group | Environment or source | Pins |
|---|---|---|
| `madgraph` | `mg5`, `mg5-3` | MadGraph5_aMC@NLO 2.9.27 (`eb76cab7`) and 3.7.0 (`adf3d62d`), LHAPDF 6.5.6 |
| `rivet-shower` | `rivet` | Rivet 4.1.3, YODA 2.1.3, Pythia 8.312, HepMC3 3.3.1 |
| `recast-base`, `ma5`, `checkmate` | `recast`, `pythia82`, `checkmate` | ROOT 6.40.00, FastJet 3.5.2, Delphes 3.5.1, MadAnalysis 5 1.11.1, CheckMATE 2 (`bacf9d17`) with Pythia 8.244 |
| `container-runtime`, `simpleanalysis`, `root-combine` | Podman 5.8.2 client, vfkit, gvproxy | SimpleAnalysis and CMS Combine images by digest |
| `smodels` | `.venv-smodels`, `smodels311` | database `official321.pcl` (Zenodo 10.5281/zenodo.23067688) with 3.1.1 and `official311.pcl` still installed; coverage statements cite the database version in `config/smodels.json` |
| `contur` | `herwig` | Contur 3.1.5 with `[spey]`, Herwig 7.3.0, ThePEG 2.3.0 |
| `wolfram` | your Wolfram kernel | FeynRules 2.3.49, SARAH 4.15.4, FeynCalc (`fe664511`), FeynArts 3.12, HEPTAPOD (`cb771f8c`, one checkout for NDA and EDA) |
| `pdg` | `pdg` wheel 2026.0 | PDG 2026 edition (CC BY 4.0); the subset RAVEL uses is `src/ravel/data/reference/pdg/` with its checksums |

| `ml` | `ml` environment | scikit-learn 1.7.2, torch 2.14.0, torch_geometric 2.7.0; reference-platform doctor and synthetic fits passed |

The other groups (`spectrum`, `finite-integrals`, `sfitter`, `easyscan`, `nyx`, `feyngraph`, `diagram-consumers`,
`publication`, `site-*`, `mcfm-amplitudes`, `agent-sources`) are pinned in the manifest in the same way.
`ravel doctor --json` also lists the refusal classes (loop decays of generated spectra, and the EasyScan cells that need
micrOMEGAs, SUSY-HIT, FeynHiggs, HiggsBounds or MultiNest) with what would make each possible.

## External data

| Item | Source |
|---|---|
| LHAPDF sets | `native/setup/pdf-sets.json`; a digest is `verified` when two independent downloads agree and `single-download` otherwise |
| Cross sections | Pinned LHC SUSY working-group tables via `ravel xsec lookup --request request.json`, with explicit order, PDF and scale |
| HEPData | the JSON API, `hepdata-cli` for full tables and the resource view for likelihoods |

The native HEP stack is ARM64-specific and does not yet have a verified cross-platform lock or OCI reproduction.

The September RS1 closure work uses an additional isolated statistics virtual environment
under ignored `local-runs/rs1-closure/numerics/venv-jax-guarded/`. It inherits the installed
recast Python 3.14 environment and adds iminuit 2.32.0 for guarded JAX profiling. The original
conda environments were not modified. This is a recorded local combination, not a portable
full-stack lock. Native plans pin the chosen Python executable and virtual-environment
configuration; result artifacts record statistical dependency versions. Frozen per-campaign
Python snapshots and separately built shower binaries prevent ongoing source edits from
changing an active run. Original installed binaries remain intact.

## Finding the toolchain

`source native/scripts/paths.sh` (bash or zsh) sets `RAVEL_NATIVE_BUILD` and
`RAVEL_NATIVE_BIN`. Python tools use the same search through `ravel.paths.native_build_root()`
and `native_binary()`. The first match wins:

1. `RAVEL_NATIVE_BUILD`, when set (`BUILD_DIR` is an alias and must agree with it).
2. The installer's pointer file `.ravel/native-prefix` (this checkout, then the main checkout).
3. The first existing directory among this checkout's `stages/01-event-generation/build` and
   `native/build`, the same two in the main checkout when this checkout is a linked git worktree
   (worktrees share the main checkout's toolchain without copying it), and the per-user
   shared location `${XDG_DATA_HOME:-$HOME/.local/share}/ravel-native`.

Binaries come from `RAVEL_NATIVE_BIN` when set, from `<prefix>/bin` when the prefix came from
steps 1 or 2, else the first existing `native/build/bin` in this checkout or the main checkout,
then `$RAVEL_NATIVE_BUILD/bin`.

When none of these exists, `paths.sh` stops with the list of searched directories. For a first
installation, set `RAVEL_NATIVE_PROVISION=1` or point `RAVEL_NATIVE_BUILD` at the new prefix;
the installer sets the prefix itself. `ravel doctor` reports what the resolved toolchain provides.

Discovery tools (`resource_census`, `hepdata_fetch`, `routine_fetch`, `fetch_figures`,
`figure_target`) run in the project Python environment; they need `certifi` for TLS, which is a
package dependency. `routine_fetch` scans the local Rivet and SimpleAnalysis sources when the
toolchain provides them and always consults the packaged analysis catalogue.

## Installing

`bash scripts/setup/install.sh` installs the complete pinned toolchain and `ravel doctor`
checks it; the [installation guide](../installation.md) lists each profile. The tables
above record the original development machine. The installer keeps such an existing
toolchain unchanged with `--adopt --prefix <its build directory>` and adds what is missing.
Per-run tool versions, cross-section sources and data sources are recorded with each run.

The requested order must match what the analysis states.
A charge-summed basis must be requested explicitly with `charge: "sum"`.
