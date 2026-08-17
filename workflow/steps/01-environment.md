# Step 1 — Environment  ·  [agent]

Provision the native toolchain (no containers, no admin). One-time.

`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda`

1. MadGraph + compiler env (if not present):
   ```bash
   bash stages/01-event-generation/scripts/00_install_miniforge.sh
   bash stages/01-event-generation/scripts/01_create_env.sh          # env mg5: python3.10 + gfortran
   $CONDA install -y -n mg5 -c conda-forge six numpy
   bash stages/01-event-generation/scripts/02_get_madgraph.sh        # MadGraph at build/tools/mg5amcnlo
   ```
2. Analysis env:
   ```bash
   $CONDA create -y -n rivet -c conda-forge rivet yoda contur pythia8 hepmc3 pyhepmc matplotlib uproot numpy
   ```
3. Build the Pythia8→HepMC3 shower bridge (once):
   ```bash
   $CONDA run -n rivet bash -c 'cd trial-runs/_infrastructure && \
     arm64-apple-darwin20.0.0-clang++ pythia_shower.cc -o pythia_shower \
     $(pythia8-config --cxxflags --libs) $(HepMC3-config --cflags --libs) -Wl,-rpath,$CONDA_PREFIX/lib'
   ```

Steps 1–3 cover the **Rivet path** (step 4A). A **SimpleAnalysis / scan→contour** analysis (step 4B,
step 8 — e.g. the EwkCompressed2018 / RRR Fig-3 reproduction) needs the rest of the toolchain below.
Provision it now, BEFORE step 8, or a scan stalls on a missing env/build.

4. Reinterpretation + recast envs (exact pinned commands in `framework/ENVIRONMENT.md` §Reproduce):
   ```bash
   $CONDA run -n rivet python -m pip install "pyhf[minuit]" jsonpatch pyyaml
   $CONDA create -y -n reinterp -c conda-forge python=3.11 pip numpy scipy matplotlib
   $CONDA run -n reinterp python -m pip install hepdata-cli smodels   # HEPData full-table/contour fetch (step 6)
   $CONDA create -y -n recast -c conda-forge root fastjet              # native ROOT 6.40 + Delphes (step 4B/8)
   ```
   `recast` must end up with **DelphesHepMC3** + `libDelphes` on its path (built against its ROOT); see
   `framework/ENVIRONMENT.md` for the Delphes build. Verify: `$CONDA run -n recast root-config --version`
   (≥6.40) and `command -v DelphesHepMC3`.
5. mapyde + its bundled assets (the cards, proc/param templates, and the slepton likelihood that
   steps 2/3/6 reuse — and the container fallback for non-slepton analyses):
   ```bash
   $CONDA create -y -n pipeline -c conda-forge python=3.11 podman
   $CONDA run -n pipeline python -m pip install mapyde
   $CONDA run -n pipeline mapyde --prefix cards   # confirm the bundled cards/likelihoods/templates resolve
   ```
   (The amd64 container images are only needed for `--backend container`; pre-pull them per
   `workflow/analysis-simpleanalysis/02-install-mapyde.md` if you will use that fallback.)
6. Native SimpleAnalysis backend (the step-8 DEFAULT; VM-free — see `reference/native-pipeline.md`):
   ```bash
   git -C stages/01-event-generation/build/tools/simple-analysis-src submodule update --init --recursive
   bash trial-runs/_infrastructure/restframes_native_build.sh                 # native RestFrames (arm64)
   $CONDA run -n recast bash trial-runs/_infrastructure/rjr_resolve_build.sh   # the native RJR resolver
   ```

**Verify (all paths):**
- Rivet/MG: `$CONDA run -n rivet rivet --version`; `$CONDA run -n mg5 python <mg>/bin/mg5_aMC` (banner).
- Native scan: `$CONDA run -n recast root-config --version` (≥6.40); `command -v DelphesHepMC3`;
  `trial-runs/_infrastructure/rjr_resolve` exists; `$CONDA run -n reinterp hepdata-cli --help`.

## Paper-PDF tooling (figure extraction)
`fetch_figures.py`'s pdf-page route needs `pdftoppm` (poppler). It is NOT provisioned by
default: `<conda> run -n rivet conda install -y poppler` (or use the arxiv-tex route, which
needs no renderer). Without it, paper-PDF page extraction fails while everything else works
(trial gap G-CMS-10).

**Next:** `steps/02-inputs.md`
