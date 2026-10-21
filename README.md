# RAVEL

RAVEL is a governed research system for high-energy physics. State a question,
choose the inputs and budget, and follow a recorded path through planning,
scientific tools, review and delivery.

<a id="1-check-the-installation"></a>

## Install

```bash
git clone https://github.com/ammarphp/ravel.git
cd ravel
bash scripts/setup/install.sh
.venv/bin/ravel doctor
```

The installer brings its own Python, needs no administrator rights and resumes a failed step where it stopped.
<!-- ravel:disk:start -->
The default installation needs 63.1 GB of disk space.
<!-- ravel:disk:end -->
It plans about 8 hours for the default toolchain; `bash scripts/setup/install.sh --dry-run` prints the size and time of each part before anything changes.

The symbolic tools use your Wolfram Engine or Mathematica licence. The [installation guide](docs/installation.md) covers the licence, analysis-facility installs and model-provider setup.


<a id="quick-start"></a>
<a id="start-a-study"></a>
<a id="2-compute-a-first-limit"></a>
<a id="3-ask-a-coding-agent"></a>
<a id="working-with-a-coding-agent"></a>
<a id="commands"></a>

## A first study

After [model setup](docs/installation.md#choose-models-and-providers), start a
controller run with a synthetic question and your supplied inputs:

```bash
source .venv/bin/activate
ravel ask "Fit the supplied signal and background model and report a 95% CLs limit." --input studies/inputs/model.json --rundir studies/first-fit
ravel status --run RUN_ID
ravel drive --resume RUN_ID
```

Use the run ID printed by the first command. CHECK-IN 1 presents the plan,
assumptions and budget for approval. The controller reports the next step,
retains failed attempts and reviews the result against the original question.
[Study guides](docs/guides/study-types.md) cover each kind of work;
[scope](docs/reference/scope.md) states the available paths and their boundaries.

<a id="how-ravel-works"></a>
<a id="how-a-calculation-runs"></a>

## How it works

The controller owns the run's state, authority and delivery. Agents propose
plans and perform scoped work; tools and independent reviewers provide evidence.
See the [architecture appendices](docs/architecture/README.md),
[workflow diagrams](docs/architecture/visual-overview.md) and
[methodology](docs/methodology/README.md).

<a id="limitations"></a>
<a id="what-ravel-does"></a>
<a id="supported-analyses-and-statistics"></a>

## What RAVEL covers

The table counts registered operations. Each study uses the selected adapter's
contract and executed evidence. The [complete inventory](docs/reference/documentation-inventory.md)
links every declared interface to its reference.

<!-- ravel:capabilities:start -->
| Family | Operations | Examples |
|---|--:|---|
| [Event generation and simulation](docs/reference/event-production.md) | 17 | MadGraph generation with decays and named weights, Pythia showering, Delphes detector simulation, LHE rewrites, PDF variations |
| [Analysis and reinterpretation](docs/workflow/reference/scientific-studies.md) | 25 | Rivet, SimpleAnalysis and MadAnalysis 5 routines, columnar selections, newly written analysis code, SModelS and Contur constraints, signal patches for published likelihoods |
| [Statistics and limits](docs/reference/inference-engines.md) | 24 | 95% CLs limits with pyhf, statistics the request prescribes, Combine and RooFit likelihoods, profile fits, workspace combinations |
| [Measurements and global fits](docs/reference/quantities-and-measurements.md) | 12 | Higgs coupling and signal-strength fits, SFitter global fits, EFT responses and coefficient conventions, EasyScan parameter scans |
| [Models and calculations](docs/reference/models-and-normalization.md) | 26 | FeynRules and SARAH models, FlexibleSUSY and SPheno spectra, widths and decays, Feynman diagrams and amplitudes, loop integrals, EFT running, symbolic and numerical calculations |
| [Machine learning](docs/workflow/checklists/ml-training.md) | 3 | Classifier training against baselines with one held-out test, published ONNX classifiers on supplied events |
| [Literature, comparison and reports](docs/workflow/reference/research-orchestration.md) | 7 | Literature census and published-limit overlays, figure digitisation and comparison, result comparisons, report delivery |
<!-- ravel:capabilities:end -->

<a id="toolchain-and-platforms"></a>

## Toolchain

The complete installer prepares the required tools and reports licence or site
actions. See [component inventory](docs/reference/component-inventory.md) and
[tool status](docs/reference/tool-status.md).

<details>
<summary>Toolchain groups</summary>

<!-- ravel:toolchain:start -->
| Toolchain | Tools |
|---|---|
| Miniforge and the build compilers | Miniforge |
| RAVEL's Python environments (.venv, .venv-smodels, .venv-sfitter) |  |
| Model-provider configuration for research and review roles |  |
| MadGraph5_aMC@NLO 2.9.27 and 3.7.0 with LHAPDF 6.5.6 | MadGraph5_aMC@NLO, LHAPDF |
| LHAPDF parton-density sets in one shared data directory | LHAPDF PDF sets |
| Rivet 4.1.3, Pythia 8.312, HepMC3 and RAVEL's shower programs | Rivet and YODA, Pythia 8, HepMC3 |
| MadGraph-Pythia 8 interface for MadGraph's own showering | MG5aMC_PY8_interface |
| ROOT 6.40, FastJet 3.5.2 and Delphes 3.5.1 | ROOT, FastJet, Delphes |
| MadAnalysis 5 v1.11.1 with SampleAnalyzer | MadAnalysis 5 |
| CheckMATE 2 with its own Pythia 8.244 and Delphes 3.5.1 | CheckMATE, Delphes, Pythia 8 |
| Container engine for the Linux-only tools | Podman, vfkit and gvproxy |
| SimpleAnalysis (container) and mapyde 0.5.0 | mapyde |
| RestFrames library and RAVEL's recursive-jigsaw program | RestFrames |
| Analysis source catalogue | Rivet |
| Combine 9.2.1 on ROOT 6.22 (container) | ROOT, Combine |
| Wolfram kernel (your licence) with FeynRules, SARAH, FeynCalc, FeynArts and HEPTAPOD | FeynRules, SARAH, FeynCalc, FeynArts, HEPTAPOD |
| FlexibleSUSY 2.9.0 (CMSSM, lowMSSM, NMSSM) and SPheno 4.0.5 | FlexibleSUSY, SPheno |
| pySecDec 1.6.6 with FORM | pySecDec and FORM |
| SModelS 3.2.1 database (3.1.1 kept runnable) | SModelS database 3.2.1, SModelS database 3.1.1 |
| Contur 3.1.5 with its data and Herwig 7.3.0 | Contur, Herwig and ThePEG |
| CAMB, CLASS and Cobaya (in the main Python environment) | CAMB, CLASS (classy), Cobaya |
| SFitterAgents source in .venv-sfitter | SFitterAgents |
| EasyScan_HEP with GM2Calc 2.3.1 and PhaseTracer | EasyScan_HEP, GM2Calc, PhaseTracer, ALGLIB |
| ServiceX client | ServiceX, func-adl-servicex-xaodr25 |
| Nyx 26.09 with AMReX 26.09 and SUNDIALS 7.6.0 | Nyx and AMReX, SUNDIALS |
| PDF, graph and SVG tools for reports | poppler, Graphviz, librsvg, pypdfium2, pypdf |
| Linux site analysis and Snakemake environments |  |
| Analysis-facility access: CVMFS, grid proxy, Kerberos, HTCondor, apptainer, agent CLI |  |
| MCFM per-point helicity amplitudes for interfering resonances | MCFM |
| FeynGraph diagram generator (Rust build) | FeynGraph |
| HEPTAPOD NDA and Diagrammatica EDA diagram tools | HEPTAPOD |
| External agent sources (AgentRivet) | AgentRivet |
| Machine-learning libraries: scikit-learn, PyTorch (CPU) and PyTorch Geometric | scikit-learn, PyTorch (CPU), PyTorch Geometric |
| PDG 2026 offline database (data CC BY 4.0) and RAVEL's pinned subset | PDG Review of Particle Physics data (2026 edition), pdg Python package |
| TeX manuscript compiler and class assets |  |
<!-- ravel:toolchain:end -->

</details>

<a id="outputs"></a>
<a id="what-ravel-checks"></a>
<a id="getting-help-and-contributing"></a>

## Documentation

- [Installation](docs/installation.md) and [configuration](docs/reference/configuration.md)
- [Command guide](docs/cli.md) and [parser reference](docs/cli/commands.md)
- [Study guides](docs/guides/study-types.md) and [workflow intake](docs/workflow/start.md)
- [Outputs and provenance](docs/reference/outputs.md), [scope](docs/reference/scope.md) and [glossary](docs/reference/glossary.md)
- [Build, test and release](docs/build-and-release.md), [contributing](CONTRIBUTING.md) and [issues](https://github.com/ammarphp/ravel/issues)

<a id="licence-and-citation"></a>

## Citing RAVEL

Use [CITATION.cff](CITATION.cff). Cite the upstream tools used in your study;
[Appendix B](#appendix-b-citing-upstream-tools) links their citation records.

<a id="license"></a>

## Licence

RAVEL uses the [Apache License 2.0](LICENSE). Upstream tools retain their own
licences; see [NOTICE](NOTICE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Appendix A: Architecture

The [architecture index](docs/architecture/README.md) covers the controller,
research, providers, scientific execution, safety and provenance. Each appendix
includes a diagram and legend.

<a id="appendix-b-citing-upstream-dependencies"></a>

## Appendix B: Citing upstream tools

When you publish results from a study, cite the tools it used. Each entry gives the reference the tool asks for; where a tool names none, the entry gives its release paper or its home page. [upstream.json](src/ravel/data/citations/upstream.json) records where each reference was found, and `scripts/maintenance/render_citations.py` renders this list from it. [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) lists the upstream code RAVEL redistributes and its licences.

<details>
<summary>References for each upstream tool</summary>

**[MadGraph5_aMC@NLO](https://github.com/mg5amcnlo/mg5amcnlo)**: event generation.

1. [arXiv:1405.0301](https://arxiv.org/abs/1405.0301), [doi:10.1007/JHEP07(2014)079](https://doi.org/10.1007/JHEP07%282014%29079).
2. For mixed-coupling or NLO electroweak computations, also: [arXiv:1804.10017](https://arxiv.org/abs/1804.10017), [doi:10.1007/JHEP11(2021)085](https://doi.org/10.1007/JHEP11%282021%29085).

**[Pythia 8](https://pythia.org/)**: showering and hadronisation.

3. [arXiv:2203.11601](https://arxiv.org/abs/2203.11601), [doi:10.21468/SciPostPhysCodeb.8](https://doi.org/10.21468/SciPostPhysCodeb.8).

**[Herwig 7](https://herwig.hepforge.org/)**: event generation and showering.

4. [arXiv:1512.01178](https://arxiv.org/abs/1512.01178), [doi:10.1140/epjc/s10052-016-4018-8](https://doi.org/10.1140/epjc/s10052-016-4018-8).

**[HepMC3](https://gitlab.cern.ch/hepmc/HepMC3)**: event records.

5. [arXiv:1912.08005](https://arxiv.org/abs/1912.08005), [doi:10.1016/j.cpc.2020.107310](https://doi.org/10.1016/j.cpc.2020.107310).

**[Delphes](https://github.com/delphes/delphes)**: detector simulation.

6. [arXiv:1307.6346](https://arxiv.org/abs/1307.6346), [doi:10.1007/JHEP02(2014)057](https://doi.org/10.1007/JHEP02%282014%29057).

**[FastJet](https://fastjet.fr/)**: jet clustering.

7. [arXiv:1111.6097](https://arxiv.org/abs/1111.6097), [doi:10.1140/epjc/s10052-012-1896-2](https://doi.org/10.1140/epjc/s10052-012-1896-2).
8. Optionally, also: [arXiv:hep-ph/0512210](https://arxiv.org/abs/hep-ph/0512210), [doi:10.1016/j.physletb.2006.08.037](https://doi.org/10.1016/j.physletb.2006.08.037).

**[LHAPDF](https://lhapdf.hepforge.org/)**: parton densities.

9. [arXiv:1412.7420](https://arxiv.org/abs/1412.7420), [doi:10.1140/epjc/s10052-015-3318-8](https://doi.org/10.1140/epjc/s10052-015-3318-8).

**[MCFM](https://mcfm.fnal.gov/)**: amplitudes for interfering resonances. Home page: <https://mcfm.fnal.gov/>.

**[Rivet](https://gitlab.com/hepcedar/rivet)**: analysis routines.

10. [arXiv:2404.15984](https://arxiv.org/abs/2404.15984), [doi:10.21468/SciPostPhysCodeb.36](https://doi.org/10.21468/SciPostPhysCodeb.36).

**[YODA](https://gitlab.com/hepcedar/yoda)**: histograms.

11. [arXiv:2312.15070](https://arxiv.org/abs/2312.15070), [doi:10.21468/SciPostPhysCodeb.45](https://doi.org/10.21468/SciPostPhysCodeb.45).

**[SimpleAnalysis](https://gitlab.cern.ch/atlas-sa/simple-analysis)**: public event selections. Home page: <https://gitlab.cern.ch/atlas-sa/simple-analysis>.

**[RestFrames](https://github.com/crogan/RestFrames)**: recursive-jigsaw reconstruction. Home page: <http://restframes.com/>.

**[MAPyDE](https://github.com/scipp-atlas/mapyde)**: card conventions and event conversion.

12. [doi:10.5281/zenodo.7796373](https://doi.org/10.5281/zenodo.7796373).
13. [arXiv:2306.11055](https://arxiv.org/abs/2306.11055), [doi:10.21468/SciPostPhysCodeb.27](https://doi.org/10.21468/SciPostPhysCodeb.27).

**[CheckMATE](https://github.com/CheckMATE2/checkmate2)**: reinterpretation.

14. [arXiv:2507.08565](https://arxiv.org/abs/2507.08565), [doi:10.1140/epjc/s10052-026-15414-8](https://doi.org/10.1140/epjc/s10052-026-15414-8).
15. [arXiv:1611.09856](https://arxiv.org/abs/1611.09856), [doi:10.1016/j.cpc.2017.08.021](https://doi.org/10.1016/j.cpc.2017.08.021).

**[MadAnalysis 5](https://github.com/MadAnalysis/madanalysis5)**: reinterpretation.

16. [arXiv:1206.1599](https://arxiv.org/abs/1206.1599), [doi:10.1016/j.cpc.2012.09.009](https://doi.org/10.1016/j.cpc.2012.09.009).
17. [arXiv:1405.3982](https://arxiv.org/abs/1405.3982), [doi:10.1140/epjc/s10052-014-3103-0](https://doi.org/10.1140/epjc/s10052-014-3103-0).
18. [arXiv:1407.3278](https://arxiv.org/abs/1407.3278), [doi:10.1140/epjc/s10052-014-3242-3](https://doi.org/10.1140/epjc/s10052-014-3242-3).
19. [arXiv:1808.00480](https://arxiv.org/abs/1808.00480), [doi:10.1142/S0217751X18300272](https://doi.org/10.1142/S0217751X18300272).
20. [arXiv:1910.11418](https://arxiv.org/abs/1910.11418), [doi:10.1140/epjc/s10052-020-8076-6](https://doi.org/10.1140/epjc/s10052-020-8076-6).
21. [arXiv:2006.09387](https://arxiv.org/abs/2006.09387), [doi:10.1140/epjc/s10052-021-09052-5](https://doi.org/10.1140/epjc/s10052-021-09052-5).
22. [arXiv:2112.05163](https://arxiv.org/abs/2112.05163), [doi:10.1140/epjc/s10052-022-10511-w](https://doi.org/10.1140/epjc/s10052-022-10511-w).
23. [arXiv:2206.14870](https://arxiv.org/abs/2206.14870), [doi:10.21468/SciPostPhys.14.1.009](https://doi.org/10.21468/SciPostPhys.14.1.009).
24. [arXiv:2303.03427](https://arxiv.org/abs/2303.03427), [doi:10.1140/epjc/s10052-023-11779-2](https://doi.org/10.1140/epjc/s10052-023-11779-2).

**[SModelS](https://github.com/SModelS/smodels)**: simplified-model constraints.

25. [arXiv:2409.12942](https://arxiv.org/abs/2409.12942), [doi:10.1007/JHEP11(2024)074](https://doi.org/10.1007/JHEP11%282024%29074).
26. [arXiv:2306.17676](https://arxiv.org/abs/2306.17676), [doi:10.21468/SciPostPhys.15.5.185](https://doi.org/10.21468/SciPostPhys.15.5.185).
27. [arXiv:2112.00769](https://arxiv.org/abs/2112.00769), [doi:10.1007/JHEP08(2022)068](https://doi.org/10.1007/JHEP08%282022%29068).
28. [arXiv:2009.01809](https://arxiv.org/abs/2009.01809), [doi:10.1016/j.cpc.2021.107909](https://doi.org/10.1016/j.cpc.2021.107909).
29. [arXiv:1811.10624](https://arxiv.org/abs/1811.10624), [doi:10.1016/j.cpc.2019.07.013](https://doi.org/10.1016/j.cpc.2019.07.013).
30. [arXiv:1701.06586](https://arxiv.org/abs/1701.06586), [doi:10.1016/j.cpc.2018.02.007](https://doi.org/10.1016/j.cpc.2018.02.007).
31. [arXiv:1312.4175](https://arxiv.org/abs/1312.4175), [doi:10.1140/epjc/s10052-014-2868-5](https://doi.org/10.1140/epjc/s10052-014-2868-5).

**[Contur](https://gitlab.com/hepcedar/contur)**: constraints from measurements.

32. [arXiv:1606.05296](https://arxiv.org/abs/1606.05296), [doi:10.1007/JHEP03(2017)078](https://doi.org/10.1007/JHEP03%282017%29078).
33. [arXiv:2102.04377](https://arxiv.org/abs/2102.04377), [doi:10.21468/SciPostPhysCore.4.2.013](https://doi.org/10.21468/SciPostPhysCore.4.2.013).

**[AgentRivet](https://gitlab.com/hepcedar/AgentRivet)**: agent-built Rivet routines. Home page: <https://gitlab.com/hepcedar/AgentRivet>.

**[HEPData](https://www.hepdata.net/)**: published data tables. Home page: <https://www.hepdata.net/>.

**[pyhf](https://github.com/scikit-hep/pyhf)**: likelihood fits.

34. [doi:10.5281/zenodo.1169739](https://doi.org/10.5281/zenodo.1169739).
35. [doi:10.21105/joss.02823](https://doi.org/10.21105/joss.02823).

**[ROOT](https://root.cern/)**: data handling and RooFit.

36. [doi:10.1016/S0168-9002(97)00048-X](https://doi.org/10.1016/S0168-9002%2897%2900048-X).

**[Combine](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit)**: statistical combinations.

37. [arXiv:2404.06614](https://arxiv.org/abs/2404.06614), [doi:10.1007/s41781-024-00121-4](https://doi.org/10.1007/s41781-024-00121-4).

**[Spey](https://github.com/SpeysideHEP/spey)**: measurement likelihoods.

38. [arXiv:2307.06996](https://arxiv.org/abs/2307.06996), [doi:10.21468/SciPostPhys.16.1.032](https://doi.org/10.21468/SciPostPhys.16.1.032).

**[iminuit](https://github.com/scikit-hep/iminuit)**: minimisation.

39. [doi:10.5281/zenodo.7695764](https://doi.org/10.5281/zenodo.7695764).
40. [doi:10.1016/0010-4655(75)90039-9](https://doi.org/10.1016/0010-4655%2875%2990039-9).

**[Wolfram Engine](https://www.wolfram.com/engine/)**: symbolic kernel. Home page: <https://www.wolfram.com/engine/>.

**[FeynRules](https://feynrules.irmp.ucl.ac.be/)**: model files from a Lagrangian.

41. [arXiv:1310.1921](https://arxiv.org/abs/1310.1921), [doi:10.1016/j.cpc.2014.04.012](https://doi.org/10.1016/j.cpc.2014.04.012).

**[SARAH](https://sarah.hepforge.org/)**: model files and spectrum generators.

42. [arXiv:1309.7223](https://arxiv.org/abs/1309.7223), [doi:10.1016/j.cpc.2014.02.018](https://doi.org/10.1016/j.cpc.2014.02.018).

**[FeynArts](https://feynarts.de/)**: diagram generation.

43. [arXiv:hep-ph/0012260](https://arxiv.org/abs/hep-ph/0012260), [doi:10.1016/S0010-4655(01)00290-9](https://doi.org/10.1016/S0010-4655%2801%2900290-9).

**[FeynCalc](https://github.com/FeynCalc/feyncalc)**: amplitude algebra.

44. [arXiv:2512.19858](https://arxiv.org/abs/2512.19858).
45. [arXiv:2312.14089](https://arxiv.org/abs/2312.14089), [doi:10.1016/j.cpc.2024.109357](https://doi.org/10.1016/j.cpc.2024.109357).
46. [arXiv:2001.04407](https://arxiv.org/abs/2001.04407), [doi:10.1016/j.cpc.2020.107478](https://doi.org/10.1016/j.cpc.2020.107478).
47. [arXiv:1601.01167](https://arxiv.org/abs/1601.01167), [doi:10.1016/j.cpc.2016.06.008](https://doi.org/10.1016/j.cpc.2016.06.008).
48. [doi:10.1016/0010-4655(91)90130-D](https://doi.org/10.1016/0010-4655%2891%2990130-D).

**[HEPTAPOD](https://github.com/tonymenzo/heptapod)**: diagram estimates.

49. [arXiv:2512.15867](https://arxiv.org/abs/2512.15867).

**[Diagrammatica](https://github.com/tonymenzo/heptapod)**: code from diagrams.

50. [arXiv:2603.26990](https://arxiv.org/abs/2603.26990).

**[FeynGraph](https://github.com/jens-braun/feyngraph)**: feynman diagrams. Home page: <https://github.com/jens-braun/feyngraph>.

**[FlexibleSUSY](https://github.com/FlexibleSUSY/FlexibleSUSY)**: spectra and decays.

51. [arXiv:1406.2319](https://arxiv.org/abs/1406.2319), [doi:10.1016/j.cpc.2014.12.020](https://doi.org/10.1016/j.cpc.2014.12.020).
52. [arXiv:1710.03760](https://arxiv.org/abs/1710.03760), [doi:10.1016/j.cpc.2018.04.016](https://doi.org/10.1016/j.cpc.2018.04.016).

**[SPheno](https://spheno.hepforge.org/)**: spectra and decays.

53. [arXiv:hep-ph/0301101](https://arxiv.org/abs/hep-ph/0301101), [doi:10.1016/S0010-4655(03)00222-4](https://doi.org/10.1016/S0010-4655%2803%2900222-4).
54. [arXiv:1104.1573](https://arxiv.org/abs/1104.1573), [doi:10.1016/j.cpc.2012.05.021](https://doi.org/10.1016/j.cpc.2012.05.021).

**[PySLHA](https://pypi.org/project/pyslha/)**: spectrum files.

55. [arXiv:1305.4194](https://arxiv.org/abs/1305.4194), [doi:10.1140/epjc/s10052-015-3638-8](https://doi.org/10.1140/epjc/s10052-015-3638-8).

**[pySecDec](https://github.com/secdec-research/secdec)**: loop integrals.

56. [arXiv:2305.19768](https://arxiv.org/abs/2305.19768), [doi:10.1016/j.cpc.2023.108956](https://doi.org/10.1016/j.cpc.2023.108956).
57. [arXiv:2108.10807](https://arxiv.org/abs/2108.10807), [doi:10.1016/j.cpc.2021.108267](https://doi.org/10.1016/j.cpc.2021.108267).
58. [arXiv:1811.11720](https://arxiv.org/abs/1811.11720), [doi:10.1016/j.cpc.2019.02.015](https://doi.org/10.1016/j.cpc.2019.02.015).
59. [arXiv:1703.09692](https://arxiv.org/abs/1703.09692), [doi:10.1016/j.cpc.2017.09.015](https://doi.org/10.1016/j.cpc.2017.09.015).

**[SymPy](https://www.sympy.org/)**: symbolic evaluation.

60. [doi:10.7717/peerj-cs.103](https://doi.org/10.7717/peerj-cs.103).

**[PDG](https://pdg.lbl.gov/)**: particle data.

61. [doi:10.1142/S0217751X26300115](https://doi.org/10.1142/S0217751X26300115).

**[SFitterAgents](https://github.com/heidelberg-hepml/SFitterAgents)**: higgs and EFT fits.

62. [arXiv:2607.22813](https://arxiv.org/abs/2607.22813).
63. [arXiv:2601.21015](https://arxiv.org/abs/2601.21015).
64. [arXiv:2411.00942](https://arxiv.org/abs/2411.00942).

**[EasyScan_HEP](https://github.com/phyzhangyang/EasyScan_HEP)**: parameter scans.

65. [arXiv:2304.03636](https://arxiv.org/abs/2304.03636), [doi:10.1016/j.cpc.2023.109027](https://doi.org/10.1016/j.cpc.2023.109027).
66. [arXiv:2606.31214](https://arxiv.org/abs/2606.31214), [doi:10.1140/epjc/s10052-026-16358-9](https://doi.org/10.1140/epjc/s10052-026-16358-9).

**[GM2Calc](https://github.com/GM2Calc/GM2Calc)**: muon g−2 predictions.

67. [arXiv:1510.08071](https://arxiv.org/abs/1510.08071), [doi:10.1140/epjc/s10052-015-3870-2](https://doi.org/10.1140/epjc/s10052-015-3870-2).
68. [arXiv:2110.13238](https://arxiv.org/abs/2110.13238), [doi:10.1140/epjc/s10052-022-10148-9](https://doi.org/10.1140/epjc/s10052-022-10148-9).

**[PhaseTracer](https://github.com/PhaseTracer/PhaseTracer)**: phase transitions.

69. [arXiv:2412.04881](https://arxiv.org/abs/2412.04881), [doi:10.1140/epjc/s10052-025-14258-y](https://doi.org/10.1140/epjc/s10052-025-14258-y).
70. [arXiv:2003.02859](https://arxiv.org/abs/2003.02859), [doi:10.1140/epjc/s10052-020-8035-2](https://doi.org/10.1140/epjc/s10052-020-8035-2).

**[WCxf](https://wcxf.github.io/)**: wilson-coefficient exchange format.

71. [arXiv:1712.05298](https://arxiv.org/abs/1712.05298), [doi:10.1016/j.cpc.2018.05.022](https://doi.org/10.1016/j.cpc.2018.05.022).

**[Wilson](https://github.com/wilson-eft/wilson)**: running and matching.

72. [arXiv:1804.05033](https://arxiv.org/abs/1804.05033), [doi:10.1140/epjc/s10052-018-6492-7](https://doi.org/10.1140/epjc/s10052-018-6492-7).

**[flavio](https://github.com/flav-io/flavio)**: flavour and precision observables.

73. [arXiv:1810.08132](https://arxiv.org/abs/1810.08132).

**[smelli](https://github.com/smelli/smelli)**: global EFT likelihood.

74. [arXiv:1810.07698](https://arxiv.org/abs/1810.07698), [doi:10.1140/epjc/s10052-019-6977-z](https://doi.org/10.1140/epjc/s10052-019-6977-z).

**[CAMB](https://camb.info/)**: cosmological power spectra.

75. [arXiv:2607.14854](https://arxiv.org/abs/2607.14854), [doi:10.1088/1475-7516/2026/10/013](https://doi.org/10.1088/1475-7516/2026/10/013).
76. [arXiv:astro-ph/9911177](https://arxiv.org/abs/astro-ph/9911177), [doi:10.1086/309179](https://doi.org/10.1086/309179).

**[CLASS](https://lesgourg.github.io/class_public/class.html)**: cosmological power spectra.

77. [arXiv:1104.2933](https://arxiv.org/abs/1104.2933), [doi:10.1088/1475-7516/2011/07/034](https://doi.org/10.1088/1475-7516/2011/07/034).

**[Cobaya](https://cobaya.readthedocs.io/)**: cosmological inference.

78. [arXiv:2005.05290](https://arxiv.org/abs/2005.05290), [doi:10.1088/1475-7516/2021/05/057](https://doi.org/10.1088/1475-7516/2021/05/057).
79. [ascl:1910.019](https://ascl.net/1910.019).

**[Nyx](https://github.com/AMReX-Astro/Nyx)**: cosmological simulation. Home page: <https://amrex-astro.github.io/Nyx/>.

**[AMReX](https://github.com/AMReX-Codes/amrex)**: adaptive mesh refinement for Nyx.

80. [doi:10.21105/joss.01370](https://doi.org/10.21105/joss.01370).
81. [doi:10.1177/10943420211022811](https://doi.org/10.1177/10943420211022811).
82. With pyAMReX or more modern features of AMReX, also: [doi:10.1177/10943420241271017](https://doi.org/10.1177/10943420241271017).

**[SUNDIALS](https://github.com/LLNL/sundials)**: differential-equation solvers for Nyx.

83. [doi:10.1145/3539801](https://doi.org/10.1145/3539801).
84. [doi:10.1145/1089014.1089020](https://doi.org/10.1145/1089014.1089020).
85. With GPU features of SUNDIALS, also: [doi:10.1016/j.parco.2021.102836](https://doi.org/10.1016/j.parco.2021.102836).
86. With its ARKODE package, also: [doi:10.1145/3594632](https://doi.org/10.1145/3594632).

**[ServiceX](https://github.com/ssl-hep/ServiceX)**: remote columnar data. Home page: <https://servicex.readthedocs.io/>.

**[func-adl-servicex-xaodr25](https://github.com/iris-hep/func_adl_servicex_xaodr25)**: query translation for ServiceX. Home page: <https://github.com/iris-hep/func_adl_servicex_xaodr25>.

**[uproot](https://github.com/scikit-hep/uproot5)**: rOOT files in Python.

87. [doi:10.5281/zenodo.4340632](https://doi.org/10.5281/zenodo.4340632).

**[Awkward Array](https://github.com/scikit-hep/awkward)**: columnar arrays.

88. [doi:10.5281/zenodo.4341376](https://doi.org/10.5281/zenodo.4341376).

**[XRootD](https://github.com/xrootd/xrootd)**: remote file access. Home page: <https://xrootd.slac.stanford.edu/>.

**[Snakemake](https://github.com/snakemake/snakemake)**: facility workflows.

89. [doi:10.12688/f1000research.29032.2](https://doi.org/10.12688/f1000research.29032.2).

**[LangGraph](https://github.com/langchain-ai/langgraph)**: research graph. Home page: <https://github.com/langchain-ai/langgraph>.

**[Podman](https://podman.io/)**: containers. Home page: <https://podman.io/>.

**[PyTorch](https://pytorch.org/)**: machine learning.

90. [doi:10.1145/3620665.3640366](https://doi.org/10.1145/3620665.3640366).

**[scikit-learn](https://scikit-learn.org/)**: machine learning.

91. <https://jmlr.csail.mit.edu/papers/v12/pedregosa11a.html>.

**[ONNX Runtime](https://onnxruntime.ai/)**: published classifiers.

92. <https://onnxruntime.ai/>.

**[Matplotlib](https://matplotlib.org/)**: figures.

93. [doi:10.1109/MCSE.2007.55](https://doi.org/10.1109/MCSE.2007.55).

**[mplhep](https://github.com/scikit-hep/mplhep)**: hEP figure style.

94. [doi:10.5281/zenodo.3766157](https://doi.org/10.5281/zenodo.3766157).

**[Miniforge](https://github.com/conda-forge/miniforge)**: bootstrap Python and conda environments. Home page: <https://github.com/conda-forge/miniforge>.

**[LHAPDF PDF sets](https://lhapdf.hepforge.org/pdfsets.html)**: parton-density data sets. Home page: <https://lhapdf.hepforge.org/pdfsets.html>.

**[MG5aMC_PY8_interface](https://launchpad.net/mg5amcnlo)**: madGraph's own Pythia 8 showering. Home page: <https://launchpad.net/mg5amcnlo>.

**[vfkit](https://github.com/crc-org/vfkit)**: container virtual machine on macOS. Home page: <https://github.com/crc-org/vfkit>.

**[gvproxy](https://github.com/containers/gvisor-tap-vsock)**: container virtual-machine networking. Home page: <https://github.com/containers/gvisor-tap-vsock>.

**[FORM](https://github.com/form-dev/form)**: symbolic manipulation for loop integrals. Home page: <https://github.com/form-dev/form>.

**[SModelS database 3.2.1](https://github.com/SModelS/smodels-database-release)**: simplified-model results database. Home page: <https://github.com/SModelS/smodels-database-release>.

**[SModelS database 3.1.1](https://github.com/SModelS/smodels-database-release)**: simplified-model results database (earlier release). Home page: <https://github.com/SModelS/smodels-database-release>.

**[ThePEG](https://thepeg.hepforge.org/)**: event-generator toolkit under Herwig. Home page: <https://thepeg.hepforge.org/>.

**[ALGLIB](https://www.alglib.net/)**: numerical library for phase-transition scans. Home page: <https://www.alglib.net/>.

**[poppler](https://poppler.freedesktop.org/)**: pDF rendering for reports. Home page: <https://poppler.freedesktop.org/>.

**[Graphviz](https://graphviz.org/)**: graph layout for reports. Home page: <https://graphviz.org/>.

**[librsvg](https://gitlab.gnome.org/GNOME/librsvg)**: sVG rendering for reports. Home page: <https://gitlab.gnome.org/GNOME/librsvg>.

**[pypdfium2](https://github.com/pypdfium2-team/pypdfium2)**: pDF page rendering in Python. Home page: <https://github.com/pypdfium2-team/pypdfium2>.

**[pypdf](https://github.com/py-pdf/pypdf)**: pDF reading and assembly in Python. Home page: <https://github.com/py-pdf/pypdf>.

**[PyTorch Geometric](https://github.com/pyg-team/pytorch_geometric)**: graph neural networks. Home page: <https://github.com/pyg-team/pytorch_geometric>.

**[PDG Review of Particle Physics data](https://pdg.lbl.gov/)**: particle properties. Home page: <https://pdg.lbl.gov/>.

**[pdg Python package](https://github.com/particledatagroup/api)**: offline access to PDG data. Home page: <https://github.com/particledatagroup/api>.

</details>

## Appendix C: Glossary

The [glossary](docs/reference/glossary.md) defines the workflow terms and links
to their contracts. The [visual overview](docs/architecture/visual-overview.md#glossary)
provides a compact reading aid.
