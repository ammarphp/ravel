# Environment manifest

Pinned toolchain for reproducibility (R5/R8). All under
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

## Reproduce the reinterpretation envs
```bash
CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda
$CONDA run -n rivet python -m pip install "pyhf[minuit]" jsonpatch pyyaml
$CONDA create -y -n reinterp -c conda-forge python=3.11 pip numpy scipy matplotlib
$CONDA run -n reinterp python -m pip install smodels hepdata-cli
$CONDA create -y -n recast  -c conda-forge root fastjet      # for MA5/CheckMATE
```
Per-run tool versions + σ-source + data-source are stamped in each `trial-runs/<run>/provenance.json`.
