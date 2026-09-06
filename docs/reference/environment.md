# Environment manifest

Recorded development toolchain inventory (R5/R8), not an exact environment lock. All under
`stages/01-event-generation/build/tools/` (gitignored, regenerable). Conda = Miniforge arm64.

## Conda environments
| Env | Python | Key tools | Used for |
|---|---|---|---|
| `mg5` | 3.10 | MadGraph 2.9.27 (+gfortran, six, numpy) | event generation |
| `rivet` | 3.14 | Rivet 4.1.3, YODA, Pythia8 8.312, HepMC3, Contur 3.1.4, **pyhf 0.7.6**, jsonpatch, certifi, pyyaml, matplotlib, **mplhep 1.2.0**, uproot | shower bridge, analysis, publication plots, pyhf exclusion, validation |
| `pipeline` | 3.11 | podman 5.8.2 (native arm64), vfkit, gvproxy, mapyde 0.5.0 | SimpleAnalysis container chain |
| `reinterp` | 3.11 | **SModelS 3.1.1**, **hepdata-cli 0.3.1**, pyhf 0.7.6, pyslha 3.3.2 | full-table fetch, likelihood download, SModelS cross-check |
| `recast` | 3.14 | ROOT, fastjet, Delphes, **autoconf/automake/libtool**, future/scipy/pyhf/setuptools | **MadAnalysis5 1.11.1 (built)** + CheckMATE2 build/run |
| `py82` | 3.x | **Pythia8 8.244** (the 8.2 series) | CheckMATE2's Pythia (conda 8.312 dropped `Info::errorMsg`) |

## External tools / data
| Item | Version / source |
|---|---|
| MadGraph5_aMC@NLO | 2.9.27 (github mg5amcnlo) |
| SimpleAnalysis source | `gitlab.cern.ch/atlas-sa/simple-analysis` (80 DefineAnalysis routines), `:master` container image |
| SModelS database | `official311.pcl` 3.1.1 (1.3 GB, Zenodo `records/18478920`), cached in `~/.cache/smodels` |
| MadAnalysis5 | **1.11.1, built from source** (`ma5 -sf`; not on conda-forge) under `build/tools/` |
| CheckMATE2 | **compiled + linked** under `build/tools/checkmate2/` (autotools + Delphes shim + Pythia 8.244 + `-Wno-c++11-narrowing`); runtime needs a Pythia-8.2-consistent Delphes — see KNOWN-LIMITATIONS |
| NLO+NLL σ | LHC SUSY x-sec WG grids via **HEPi JSON** (`nlo_xsec.py`); NNLL-fast download URLs dead |
| HEPData | JSON API (open), `hepdata-cli` full tables, `/record/resource/<id>?view=true` likelihood |
| podman runtime | native arm64 5.8.2 + applehv VM (`mg-vm`), amd64 images under emulation |

The Python replay environment is separately version- and hash-locked in
`requirements-replay.lock`; see the [command-line reference](../cli.md). The native HEP stack below is
ARM64-specific and does not yet have a verified cross-platform lock or OCI reproduction.

The September RRR closure work uses an additional isolated statistics virtual environment
under ignored `local-runs/rrr-closure/numerics/venv-jax-guarded/`. It inherits the installed
recast Python 3.14 environment and adds iminuit 2.32.0 for guarded JAX profiling. The original
conda environments were not modified. This is a recorded local combination, not a portable
full-stack lock. Native plans pin the chosen Python executable and virtual-environment
configuration; result artifacts record statistical dependency versions. Frozen per-campaign
Python snapshots and separately built shower binaries prevent ongoing source edits from
changing an active run. Original installed binaries remain intact.

## Provisioning and optional environments

Start with [environment setup](../../environment/README.md) and follow the
[provisioning sequence](../workflow/steps/01-environment.md). Fresh installations use
`native/build/`; an existing development installation retains its original location.
The shared helper supports an explicit `RAVEL_NATIVE_BUILD` override.

After Miniforge is installed, these optional environment commands run from the
repository root in Bash. They are examples for extending the recorded environment,
not a complete recipe or a version lock for the full simulation chain.

```bash
source native/scripts/paths.sh
RAVEL_CONDA="$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda"
"$RAVEL_CONDA" run -n rivet python -m pip install "pyhf[minuit]" jsonpatch pyyaml
"$RAVEL_CONDA" create -y -n reinterp -c conda-forge python=3.11 pip numpy scipy matplotlib
"$RAVEL_CONDA" run -n reinterp python -m pip install smodels hepdata-cli
"$RAVEL_CONDA" create -y -n recast -c conda-forge root fastjet
```
Per-run tool versions + σ-source + data-source are stamped in each `trial-runs/<run>/provenance.json`.
