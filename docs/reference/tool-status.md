# Tool checks

Generated from `src/ravel/data/backends/census.json`; do not edit this table.

Tools are required by their selected operation/profile. Run `ravel doctor --census`
for readiness checks on the selected machine.

| Tool | Requirement | Doctor check |
|---|---|---|
| AgentRivet (`e4d12ecc`) | required for profile | agent-sources/agentrivet |
| AnalysisBase 21.2 (inside the SA image) | required for profile | simpleanalysis/simpleanalysis-image |
| SimpleAnalysis (image `sha256:3156f065…`, source `5a33033d`) | required for profile | simpleanalysis/simpleanalysis-image; simpleanalysis/simpleanalysis-wrapper |
| CAMB 1.6.5, CLASS (classy) 3.4.1.0, Cobaya 3.6.2 | required for profile | cosmology/cosmology-python |
| CheckMATE 2 (`bacf9d17`) with ONNX Runtime C++ 1.30.0 | required for profile | checkmate/checkmate; checkmate/pythia82-config; checkmate/checkmate-python |
| Combine 9.2.1 on ROOT 6.22 (image `sha256:5da96967…`) | required for profile | root-combine/combine-image; root-combine/combine; root-combine/text2workspace; root-combine/combine-root-config |
| coffea, cabinetry, vector, boost-histogram, pyarrow | required for profile | site-root-wms/site-analysis-python |
| Collier or LoopTools | required for profile | no doctor check declared |
| Contur 3.1.5 (`contur[spey]`) + data | required for profile | contur/contur; contur/contur-data |
| CVMFS, X.509 grid proxy, Kerberos, HTCondor, apptainer, agent CLI | required for profile | site-access/cvmfs; site-access/grid-proxy; site-access/kerberos; site-access/htcondor; site-access/apptainer; site-access/agent-cli |
| Delphes 3.5.1 | required for profile | recast-base/delphes |
| docker / apptainer / podman on Linux | required for profile | container-runtime/podman; container-runtime/podman-machine; container-runtime/rosetta; container-runtime/container-engine |
| DsixTools | required for profile | no doctor check declared |
| EasyScan_HEP (`2dee5ede`) | required for profile | easyscan/easyscan-source; easyscan/easyscan-engines-manifest; easyscan/gm2calc |
| emcee 3.1.6, dynesty 2.1.5 | required for profile | python-host/host-python |
| FastJet 3.5.1 | required for profile | recast-base/fastjet-config |
| FeynArts 3.12 (patched with FAPatch) | required for profile | wolfram/wolfram-kernel; wolfram/feynarts-original; wolfram/feynarts-patched |
| FeynCalc (`fe664511`) | required for profile | wolfram/wolfram-kernel; wolfram/feyncalc |
| FeynGraph (`15afe2f2`) | required for profile | feyngraph/diagram-python; feyngraph/diagram-rust; feyngraph/feyngraph-source |
| FeynRules 2.3.49 | required for profile | wolfram/wolfram-kernel; wolfram/feynrules |
| FlexibleSUSY 2.9.0 (CMSSM, lowMSSM, NMSSM) | required for profile | spectrum/flexiblesusy-CMSSM; spectrum/flexiblesusy-lowMSSM; spectrum/flexiblesusy-NMSSM |
| FORM (standalone) | required for profile | no doctor check declared |
| GM2Calc 2.3.1, PhaseTracer (`a68b2fd2`) | required for profile | easyscan/easyscan-source; easyscan/easyscan-engines-manifest; easyscan/gm2calc |
| HEPData (API and `hepdata-cli` 0.3.1), INSPIRE, arXiv, Zenodo, GitLab | required for profile | python-host/host-python |
| HepMC2 2.06.11 | required for profile | checkmate/checkmate; checkmate/pythia82-config; checkmate/checkmate-python |
| HepMC3 3.3.1 | required for profile | rivet-shower/hepmc3-config |
| HEPTAPOD v2.1.0 (`705b03cc`) and EDA epoch (`cb771f8c`): NDA and Diagrammatica EDA | required for profile | diagram-consumers/heptapod-nda; diagram-consumers/heptapod-eda; wolfram/wolfram-kernel; wolfram/feynrules; wolfram/sarah; wolfram/feyncalc; wolfram/feynarts-original; wolfram/feynarts-patched; wolfram/heptapod |
| Herwig 7.3.0, ThePEG 2.3.0 | required for profile | contur/herwig |
| hi_class | required for profile | no doctor check declared |
| HTCondor, SLURM | required for profile | nyx/nyx; nyx/srun; nyx/scontrol; nyx/scancel; site-access/cvmfs; site-access/grid-proxy; site-access/kerberos; site-access/htcondor; site-access/apptainer; site-access/agent-cli |
| iminuit 2.32.0 | required for profile | python-host/host-python |
| JAX 0.4.35 | required for profile | python-host/host-python |
| LangGraph 1.2.14 (+ checkpoint 4.2.0, SQLite saver 3.1.1), LangChain Core 1.6.7, pydantic 2.14.0 | required for profile | python-host/host-python |
| LHAPDF 6.5.6 | required for profile | lhapdf-sets/pdfsets-index; lhapdf-sets/pdf-NNPDF30_nlo_as_0118; lhapdf-sets/pdf-LUXlep-NNPDF31_nlo_as_0118_luxqed; lhapdf-sets/pdf-cteq6l1; lhapdf-sets/pdf-NNPDF23_lo_as_0130_qed; lhapdf-sets/pdf-NNPDF23_nlo_as_0119; lhapdf-sets/pdf-CT14lo; lhapdf-sets/pdf-CT18NNLO; madgraph/mg-python; madgraph/mg5; madgraph/mg5-lhapdf-config; madgraph/mg5-options; madgraph/mg5-3; madgraph/mg5-3-lhapdf-config |
| LHAPDF sets: NNPDF30_nlo_as_0118, LUXlep-NNPDF31_nlo_as_0118_luxqed, cteq6l1, NNPDF23_lo_as_0130_qed, NNPDF23_nlo_as_0119, CT14lo, CT18NNLO | required for profile | lhapdf-sets/pdfsets-index; lhapdf-sets/pdf-NNPDF30_nlo_as_0118; lhapdf-sets/pdf-LUXlep-NNPDF31_nlo_as_0118_luxqed; lhapdf-sets/pdf-cteq6l1; lhapdf-sets/pdf-NNPDF23_lo_as_0130_qed; lhapdf-sets/pdf-NNPDF23_nlo_as_0119; lhapdf-sets/pdf-CT14lo; lhapdf-sets/pdf-CT18NNLO |
| MadAnalysis 5 v1.11.1 (`e25937ba`) with SampleAnalyzer | required for profile | ma5/ma5; ma5/sampleanalyzer |
| MadGraph 3.7.0 (`adf3d62d`) | required for profile | madgraph/mg5-3; madgraph/mg5-3-lhapdf-config |
| MadGraph5_aMC@NLO 2.9.27 (`eb76cab7`) | required for profile | madgraph/mg-python; madgraph/mg5; madgraph/mg5-lhapdf-config; madgraph/mg5-options |
| mapyde 0.5.0 | required for profile | simpleanalysis/mapyde |
| matplotlib 3.9.4, mplhep 0.3.59, contourpy | required for profile | python-host/host-python |
| MCFM per-point helicity amplitudes for interfering resonances | required for profile | mcfm-amplitudes/mcfm-amplitudes |
| MG5aMC_PY8_interface (`5d82df1b`) | required for profile | mg5-py8-interface/mg5-py8-interface |
| micrOMEGAs 7.1, SUSY-HIT, FeynHiggs, HiggsBounds | required for profile | no doctor check declared |
| micrOMEGAs (as a general DM tool) | required for profile | no doctor check declared |
| Model providers: Anthropic Messages, OpenAI Responses, Gemini, OpenAI-compatible chat completions | required for profile | research-host/research-host-config |
| MultiNest | required for profile | no doctor check declared |
| Nyx 26.09, AMReX 26.09, SUNDIALS 7.6.0; CosmicIC (supplied) | required for profile | nyx/nyx; nyx/srun; nyx/scontrol; nyx/scancel |
| ONNX 1.23.0, ONNX Runtime 1.30.0 | required for profile | python-host/host-python |
| Podman 5.8.2 (macOS client), vfkit 0.6.3, gvproxy 0.8.9, Podman VM `ravel`; Rosetta 2 | required for profile | container-runtime/podman; container-runtime/podman-machine; container-runtime/rosetta; container-runtime/container-engine |
| poppler (`pdftoppm`, `pdfinfo`), Graphviz (`neato`), librsvg (`rsvg-convert`) | required for profile | publication/pdftoppm; publication/pdfinfo; publication/neato; publication/rsvg-convert |
| Powheg | required for profile | no doctor check declared |
| pyhf 0.7.6 (+ `[minuit]`), jsonpatch | required for profile | python-host/host-python |
| pypdfium2 5.14.0 / PDFium, pypdf, Pillow | required for profile | python-host/host-python |
| pySecDec 1.6.6 with bundled FORM | required for profile | finite-integrals/integral-python; finite-integrals/integrals-make; finite-integrals/form |
| PySLHA 3.3.2, `particle` 0.26.2 | required for profile | python-host/host-python |
| Pythia 8.244 | required for profile | checkmate/pythia82-config |
| Pythia 8.312 | required for profile | rivet-shower/pythia83-config; rivet-shower/shower; rivet-shower/shower-merged |
| Python numerical core | required for profile | python-host/host-python |
| QGRAF model format | required for profile | source: src/ravel/physics/feyn_graph.py |
| RestFrames (from SA tarball, sha256 pinned) | required for profile | restframes/restframes; restframes/restframes-library; restframes/restframes-library-linux; restframes/rjr |
| Rivet 4.1.3, YODA 2.1.3 | required for profile | rivet-shower/rivet; rivet-shower/rivet-build |
| RooFit / XRooFit (ROOT ≥6.32.14 for HS3) | required for profile | recast-base/recast-root-config |
| ROOT 6.40 | required for profile | recast-base/recast-root-config |
| SARAH 4.15.4 | required for profile | wolfram/wolfram-kernel; wolfram/sarah |
| ServiceX 3.3.1, func-adl-servicex-xaodr25 | required for profile | iris/servicex |
| SFitterAgents/SFitter (`6072a79e`) + PyTorch 2.14.0 | required for profile | sfitter/sfitter-venv; sfitter/sfitter-source |
| SModelS 3.1.1 + database `official311.pcl` (Zenodo 18478920) | required for profile | smodels/smodels-311-version; smodels/smodels-311-database |
| Snakemake 9.27.0 | required for profile | site-root-wms/site-snakemake |
| SoftSUSY | required for profile | no doctor check declared |
| Spey 0.2.6 | required for profile | python-host/host-python |
| SPheno 4.0.5 | required for profile | spectrum/spheno |
| Supplied tree-to-array column layout | required for profile | source: src/ravel/physics/tree_array_export.py |
| SUSY cross-section tables (LHC SUSY XS WG: NNLL-fast, Resummino) via HEPi JSON | required for profile | source: src/ravel/physics/cross_sections.py |
| TeX Live or MacTeX with `pdflatex`, BibTeX, REVTeX | required for profile | tex/pdflatex; tex/revtex |
| TMVA | required for profile | no doctor check declared |
| uproot 5.3.12, awkward 2.6.7, hist 2.8.0, pandas 2.2.3 | required for profile | python-host/host-python |
| WCxf / wilson 2.5.2, flavio 2.7.1, smelli 2.4.3 | required for profile | python-host/host-python |
| Wolfram kernel (Mathematica or Wolfram Engine), `wolframscript` | required for profile | wolfram/wolfram-kernel |
| XRootD 6.2.0, fsspec-xrootd 0.5.5, Rucio clients 35.0.0, fsspec | required for profile | site-root-wms/site-analysis-python |
| boost-histogram | required for profile | python-host/host-python |
| cabinetry | required for profile | python-host/host-python |
| certifi | required for profile | python-host/host-python |
| coffea | required for profile | python-host/host-python |
| hatchling | required for profile | python-host/host-python |
| jsonschema | required for profile | python-host/host-python |
| mpmath | required for profile | python-host/host-python |
| numpy | required for profile | python-host/host-python |
| packaging | required for profile | python-host/host-python |
| pyarrow | required for profile | python-host/host-python |
| pytest | required for profile | python-host/host-python |
| PyYAML | required for profile | python-host/host-python |
| scipy | required for profile | python-host/host-python |
| sympy | required for profile | python-host/host-python |
| vector | required for profile | python-host/host-python |
