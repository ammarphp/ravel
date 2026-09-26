# Proposed validation targets across the public routine landscape

This is an ordered portfolio of **40 concrete routine/component candidates**, not 40 reproduced papers or newly supported analyses. Every identity resolves in the pinned catalogue, and the [machine-readable plan](../../evidence/audits/2026-09-26-analysis-landscape/validation-targets.json) carries exact source revisions, source hashes/URLs, upstream metadata links, missing inputs, and proposed discriminating experiments. No experiment below has been executed or authorized by this document.

The selection uses routine metadata, dependency signals, and current Ravel gaps. It does **not** claim full paper-by-paper review, verified likelihood bytes, or complete analysis applicability. Source routines and publication metadata must be checked during admission. Relative effort is engineering judgment: **bounded** means a constrained control after runtime/sample prerequisites; **substantial** means significant response/dependency/mapping work; **new-domain** means additional scientific infrastructure. These are not time estimates or closure guarantees.

The [competitor capability map](2026-09-26-competitor-capability-map.md) explains why fixed-event comparison and quantity semantics come before broad new simulation. A successful adapter comparison is implementation evidence; reproducing a paper additionally requires the correct generator recipe, response, normalization, uncertainty treatment, and published-reference agreement.

The two Drell–Yan examples use different published collision energies. Each control
needs its own matching beam/event contract; pairing them tests the adapter across
analyses and does not authorize reusing a 7 TeV sample as a 13 TeV prediction.

## First eight discriminating experiments

Use frozen eligible events where they exist and compact constructed boundary cases. A generated control remains a separately proposed, budgeted experiment requiring the actual check-in. Never substitute the existing 100-event parton pilot for a showered/hadron-level sample. Keep event identity, generator/response settings, and numerical tolerance explicit.

### 1. Drell-Yan baseline — `rivet:ATLAS_2013_I1234228`

**Experiment:** Freeze dilepton events; compare lepton construction, pair selection and every mass-bin contribution to the pinned routine, including events on either side of each boundary.

**Required before execution:** General Rivet event-input adapter, frozen reference outputs and confirmed particle-level definition.

**What it distinguishes:** Separates object selection and bin normalization from detector effects. Effort: bounded. [pinned source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2013_I1234228.cc), [publication metadata link](https://arxiv.org/abs/1305.4192).

### 2. Drell-Yan transfer — `rivet:CMS_2018_I1711625`

**Experiment:** Reuse a suitable frozen dilepton sample; compare the CMS-defined observables independently, then test unequal mass-bin widths and channel combination.

**Required before execution:** CMS reference booking and exact per-channel normalization; do not presume ATLAS and CMS fiducial definitions coincide.

**What it distinguishes:** Detects experiment-specific assumptions hidden in a supposedly generic adapter. Effort: bounded. [pinned source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2018_I1711625.cc), [publication metadata link](https://arxiv.org/abs/1812.10529).

### 3. Diboson and missing momentum — `rivet:ATLAS_2016_I1494075`

**Experiment:** Freeze four-lepton and two-lepton-plus-invisible examples; compare lepton pairing, invisible-particle definition and disjoint channel assignment.

**Required before execution:** Frozen diboson events and an explicit channel/object contract.

**What it distinguishes:** Ensures neutrinos in an ordinary collider final state do not trigger a forward-flux workflow; tests combinatorics. Effort: bounded. [pinned source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2016_I1494075.cc), [publication metadata link](https://arxiv.org/abs/1610.07585).

### 4. Diboson transfer — `rivet:CMS_2012_I1298807`

**Experiment:** Compare the same eligible four-lepton events through CMS and its upstream reference separately; test alternate pairings and same-flavor ties.

**Required before execution:** CMS pairing prescription and frozen upstream outputs; shared events alone do not make fiducial regions identical.

**What it distinguishes:** Exposes ordering, double-counting and pairing errors before detector studies. Effort: bounded. [pinned source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2012_I1298807.cc), [publication metadata link](https://arxiv.org/abs/1406.0113).

### 5. Inclusive jets — `rivet:ATLAS_2010_I871366`

**Experiment:** Replay a tiny frozen hadron-level jet sample and synthetic boundaries; compare clustered four-vectors, multiplicities, rapidity slices and histogram contribution counts.

**Required before execution:** Pinned jet algorithm/runtime and per-object versus per-event output semantics.

**What it distinguishes:** Tests whether one event contributing several jets is incorrectly normalized as one entry. Effort: bounded. [pinned source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2010_I871366.cc), [publication metadata link](https://arxiv.org/abs/1009.5908).

### 6. Jet transfer — `rivet:CMS_2016_I1459051`

**Experiment:** Replay fixed jet events with CMS booking; compare bin edges, rapidity slices, histogram integrals and equivalent chunked input.

**Required before execution:** Confirmed CMS jet/radius options and differential bin measure.

**What it distinguishes:** Tests bin-volume and merge consistency independently of any exclusion fit. Effort: bounded. [pinned source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2016_I1459051.cc), [publication metadata link](https://inspirehep.net/literature/1459051).

### 7. Ordinary reconstructed search — `simpleanalysis:ZeroLeptonDiscovery2018`

**Experiment:** Replay fixed reconstructed objects and trace every zero-lepton region decision against pinned upstream SimpleAnalysis, including veto and threshold ties.

**Required before execution:** Reference upstream runner and matching object schema/efficiency policy; adapter registration is not closure.

**What it distinguishes:** Localizes generic MET, overlap-removal and region-bookkeeping failures. Effort: bounded. [pinned source](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-22_Discovery.cxx), [publication metadata link](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-22).

### 8. Leptonic reconstructed search — `simpleanalysis:EwkTwoLeptonZeroJet2018`

**Experiment:** Trace fixed two-lepton events across flavor, charge, jet-veto and kinematic boundaries, comparing each region decision to the upstream routine.

**Required before execution:** External SimpleAnalysis adapter and explicit object/selection contract.

**What it distinguishes:** Provides a simpler leptonic control for the compressed-search acceptance problem. Effort: bounded. [pinned source](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-32.cxx), [publication metadata link](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-32).

For all eight, compare event contributions and bin contents before figures. Then independently verify axis/units, integrated versus differential quantities, unequal bin widths, normalization integrals, under/overflow, and plotted overlays. A deterministic boundary fixture needs exact expected decisions; stochastic or numerical comparisons need prospective tolerances. Any missing definition blocks the affected scientific claim, with the unresolved input retained.

## Wave 2: detector, tagger and shape controls

These targets follow the basic adapter controls. The canonical RRR task remains a publication requirement; other analyses help locate transferable failures and cannot replace its closure.

| Routine and sources | Discriminating experiment | Missing input or adapter | Transfer and effort |
|---|---|---|---|
| [rivet:ATLAS_2015_I1404878](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2015_I1404878.cc) · [paper](https://arxiv.org/abs/1511.04716) | Compare fixed semileptonic top events through object reconstruction and each reported observable. | Top-decay, b-jet and reconstruction conventions; verified histogram references. | Tests assignment ambiguities beyond Drell-Yan. **substantial**. |
| [rivet:CMS_2018_I1620050](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2018_I1620050.cc) · [paper](https://arxiv.org/abs/1708.07638) | Compare dilepton-top bin yields, then independently derive normalized distributions and their covariance constraints. | Normalization denominator and correlated reference uncertainties. | Tests normalized-shape constraints and prevents independent-bin likelihood invention. **substantial**. |
| [rivet:ATLAS_2020_I1790439](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2020_I1790439.cc) · [paper](https://arxiv.org/abs/2004.03969) | Compare fixed Higgs-to-four-lepton pairing, fiducial event membership and differential distributions. | Production/decay definition, reference bins and normalization basis. | Tests rare-signal pairing and production-versus-decay normalization. **substantial**. |
| [rivet:CMS_2022_I2142341](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2022_I2142341.cc) · [paper](https://arxiv.org/abs/2208.12279) | Replay fixed photon events; compare isolation, pair assignment and differential fiducial bins. | Photon promptness/isolation definition and production-mode mixture. | Tests photons and observable-specific fiducial definitions. **substantial**. |
| [rivet:ATLAS_2019_I1725190](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2019_I1725190.cc) · [paper](https://arxiv.org/abs/1903.06248) | Compare identical truth inputs before/after the exact response prescription; test migration and the routine single-weight/non-reentrant restrictions. | Response functions, allowed weight/finalization mode and reproducible stochastic handling. | Distinguishes rate bias, smearing bias and incorrect merge semantics. **substantial**. |
| [simpleanalysis:EwkCompressed2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-16.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-16) | Use retained RRR event traces to compare truth acceptance, reconstructed acceptance, RestFrames observables, all SR/CR contributions and fixed-template inference separately. | Unclosed detector/acceptance, low-splitting shape and generator-cut stability; final full-plane reference closure. | Directly addresses the publication blocker without tuning to the observed contour. **substantial**. |
| [simpleanalysis:EwkCompressedVBF2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-16_VBF.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-16) | Replay eligible fixed events and compare forward-jet selection plus RestFrames quantities separately from soft-lepton response. | VBF-specific event/object contract and reference cutflow. | Tests whether compressed-analysis repairs generalize to another topology. **substantial**. |
| [simpleanalysis:EwkThreeLeptonOnshell2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2019-09_OnShell.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2019-09) | Trace fixed three-lepton events through pairing/category choices and exact region-to-likelihood ordering. | Validated adapter and channel mapping; indexed models require independent acquisition. | Tests category bookkeeping and ambiguous lepton assignments. **substantial**. |
| [simpleanalysis:MonoJet2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-EXOT-2018-06.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/EXOT-2018-06) | Compare fixed event selections with varying jet thresholds and vetoes; only later propose matched-recipe generator-cut controls. | ISR/shower recipe and trigger/object reference evidence. | Tests cut dependence relevant to compressed RRR without assuming a universal correction. **substantial**. |
| [simpleanalysis:DirectStau2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-04.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-04) | Separate truth tau decay/polarization from reconstructed tau decisions on the same frozen events. | Tau efficiencies, fake treatment and decay conventions. | Prevents attributing tau-response differences to signal normalization. **substantial**. |
| [simpleanalysis:TauStrong2016](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2016-30.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2016-30) | Compare tau/jet overlap handling and region assignments using hand-selected threshold cases. | Tau-tag response and exact overlap/removal order. | Tests whether tau handling survives a different topology. **substantial**. |
| [simpleanalysis:ThreeBjets_NN_2020](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-30.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-30) | Compare each fixed feature vector and network score before comparing bin membership. | Network/preprocessing assets, b-tag calibration dependency and runtime version. | Exposes feature-order, precision and tagging errors invisible in aggregate yields. **substantial**. |
| [simpleanalysis:TriHiggs6b](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-HIGP-2024-32.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/HIGP-2024-32) | Resolve dynamically assembled model/variable filenames; compare parity/model selection and feature scores on fixed objects. | Model-file resolution and provenance beyond literal filename fragments. | Tests asset discovery and deterministic routing across learned models. **substantial**. |
| [simpleanalysis:ZeroLeptonBDT2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-22_BDT.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-22) | Compare feature vectors, BDT scores and strict score thresholds on fixed reconstructed events. | Exact BDT assets/runtime and preprocessing. | Separates classifier implementation from detector response. **substantial**. |
| [rivet:ATLAS_2022_I2172216](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginONNX/ATLAS_2022_I2172216.cc) · [paper](https://arxiv.org/abs/2210.15413) | Run fixed inputs through the pinned ONNX and smearing interfaces separately; compare scores and region counts. | ONNX model/input contract and validated smearing response. | Tests that Rivet discovery does not imply a pure particle-level measurement. **substantial**. |
| [rivet:ATLAS_2017_I1614149](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginATLAS/ATLAS_2017_I1614149.cc) · [paper](https://arxiv.org/abs/1708.00727) | Compare clustering, grooming and resolved/boosted category membership on fixed hadron-level events. | Exact FastJet-contrib algorithms and category overlap policy. | Checks nontrivial jet dependencies and topology transitions. **substantial**. |
| [rivet:CMS_2019_I1764472](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2019_I1764472.cc) · [paper](https://arxiv.org/abs/1911.03800) | Compare constituents and jet mass before histogram normalization on identical frozen events. | Grooming/contrib settings and mass/normalization reference. | Tests whether visually shifted shapes arise before plotting. **substantial**. |
| [simpleanalysis:EwkFullHad2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-41.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-41) | Verify classifier/tagging calibration acquisition before replaying fixed boosted-object selections. | External ROOT calibration asset and large-R/tagging conventions. | Tests a real missing-asset blocker before expensive simulation. **substantial**. |

## Wave 3: new scientific domains

These are distinct scientific admission projects. Prior success with prompt pp searches does not validate their beam, lifetime, decay, correlation or transport assumptions.

| Routine and sources | Discriminating experiment | Missing input or adapter | Transfer and effort |
|---|---|---|
| [simpleanalysis:DisappearingTrack2018](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-19.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-19) | Factor lifetime/geometry, event acceptance and tracklet reconstruction; compare controlled decay positions and published supported benchmark points. | Validated decay/geometry and tracklet-efficiency adapter. | Tests applicability limits of prompt-object infrastructure. **new-domain**. |
| [simpleanalysis:DisappearingTrack2018_EventAcc](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-19_EventAcc.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-19) | Compare the event-only variant to the corresponding factor in the full routine on the same inputs. | Variant-specific semantics and shared event identity. | Prevents counting an acceptance component as a complete search result. **new-domain**. |
| [simpleanalysis:DisappearingTrack2018_TrackletAcc](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2018-19_TrackletAcc.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2018-19) | Compare the tracklet-only variant at matched lifetimes/boosts and track its denominator explicitly. | Tracklet domain and relation to full/event-only routines. | Tests factorization and denominator consistency; this is not another independent paper. **new-domain**. |
| [simpleanalysis:DisplacedTrack2020](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/blob/5a33033d788619bb1039a5b8116fdf43c46fc72a/SimpleAnalysisCodes/src/ANA-SUSY-2020-04.cxx) · [paper](https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/SUSY-2020-04) | Test length-unit conversions, decay positions and prompt/displaced boundary cases before reference efficiencies. | Non-prompt tracking/trigger response and lifetime convention. | Exposes silent reuse of prompt efficiencies. **new-domain**. |
| [rivet:ALICE_2015_CENT_PBPB](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginALICE/ALICE_2015_CENT_PBPB.cc) · no paper link in metadata | Validate calibration inputs against beam/energy metadata and test centrality percentile boundary mapping. | Correct ion energy-per-nucleon convention and calibration sample. | Separates calibration infrastructure from a publication result; helper does not count as an independently reproduced paper. **new-domain**. |
| [rivet:ALICE_2016_I1419244](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginALICE/ALICE_2016_I1419244.cc) · [paper](https://arxiv.org/abs/1602.01119) | Test particle correlations and event-plane/centrality conventions on synthetic symmetric events before data comparison. | Heavy-ion event metadata, centrality and correlated uncertainty treatment. | Tests a qualitatively different observable algebra. **new-domain**. |
| [rivet:ALICE_2012_I930312](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginALICE/ALICE_2012_I930312.cc) · [paper](https://arxiv.org/abs/1110.0121) | Compare pair counting and mixed/background populations using controlled duplicated and permuted events. | Pair/background construction, nuclear reference and covariance. | Tests correlated populations where independent-event assumptions fail. **new-domain**. |
| [rivet:LHCB_2022_I2694685](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginLHCb/LHCB_2022_I2694685.cc) · [paper](https://arxiv.org/abs/2205.03936) | Verify asymmetric beam boosts, prompt-charm ancestry and pp/pPb normalization independently. | Nuclear beams, prompt definition and nuclear-reference transport. | Tests mixed beam options and ratios; pPb is not fixed-target. **new-domain**. |
| [rivet:LHCB_2016_I1394391](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginLHCb/LHCB_2016_I1394391.cc) · [paper](https://inspirehep.net/literature/1394391) | Compare invariant-mass pairings and Dalitz-boundary membership on exact decay kinematics. | Decay generator/amplitude conventions and normalized distribution semantics. | Tests decay observables outside generic high-pT exclusions. **new-domain**. |
| [rivet:LHCB_2015_I1396331](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginLHCb/LHCB_2015_I1396331.cc) · [paper](https://inspirehep.net/literature/1396331) | Compare parent/decay ancestry, rapidity bins and charm-species normalization on fixed events. | Heavy-flavor production/decay definitions and branching basis. | Tests ancestry and forward acceptance without treating charm hadrons as prompt leptons. **new-domain**. |
| [rivet:CMS_2020_I1776758](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2020_I1776758.cc) · [paper](https://arxiv.org/abs/2001.06899) | Compare charm/bottom flavor labeling and the ratio numerator/denominator on shared events. | Flavor definition, shared-population covariance and normalization convention. | Tests ratio uncertainties and heavy-flavor semantics. **substantial**. |
| [rivet:LHCF_2018_I1518782](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginLHCf/LHCF_2018_I1518782.cc) · [paper](https://arxiv.org/abs/1703.07678) | Verify laboratory energy/angle acceptance and photon ancestry on controlled forward kinematics. | Forward hadronization/acceptance and relevant beam configuration. | Tests extreme-rapidity observables beyond central detector assumptions. **new-domain**. |
| [rivet:TOTEM_2012_I1220862](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginTOTEM/TOTEM_2012_I1220862.cc) · [paper](https://inspirehep.net/literature/1220862) | Compare momentum-transfer definition and elastic event selection before beam-optics/acceptance corrections. | Elastic generator, beam optics and normalization inputs. | Separates forward elastic physics from ordinary pp hard-scattering simulation. **new-domain**. |
| [rivet:FASER_2024_I2855783](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginNeutrino/FASER_2024_I2855783.cc) · [paper](https://arxiv.org/abs/2412.03186) | Validate flux normalization, target composition and interaction response separately on controlled neutrino inputs. | Flux/transport/interaction backend and their joint covariance. | Tests genuinely new physics stages; ordinary missing-energy events are not a substitute. **new-domain**. |

## Gaps and stopping rules

**LHCb fixed-target remains unfilled.** No routine was confidently identified from this snapshot’s titles/beam metadata. Locate the official public implementation and establish target species, laboratory-to-center-of-mass transformation, and event-input requirements before adding a target. The listed LHCb pPb collider and decay analyses are useful adjacent controls but do not provide fixed-target coverage.

The disappearing-track full, event-acceptance and tracklet-acceptance routines are intentionally separate targets for a factorization test. They are not three independent paper reproductions. The ALICE centrality routine is a calibration helper, not a standalone measurement.

Advance each target only after its specific missing inputs are resolved and the physicist approves a bounded experiment. Record upstream disagreement, unavailable reference information, failed dependency provisioning and wrong requested outputs as distinct outcomes. Do not tune selections or normalizations to improve a published contour. Stop a broad campaign when a cheaper frozen-event or fixed-template control can still distinguish the competing explanations.
