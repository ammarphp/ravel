# Third-party tools and licenses

This repository is a control plane around the standard HEP simulation and statistics toolchain.
The tools below are **external dependencies, invoked as installed programs/libraries — none of
their source code is vendored into this tree** (verified in the 2026-07-30 repo audit: the only
C++ files here are three project-authored drivers that `#include`/link upstream headers and
libraries). Each tool is the work of its own authors under its own license; consult each
project's distribution for the authoritative license text.

| Tool | Role here | Upstream license (as distributed) |
|---|---|---|
| MadGraph5_aMC@NLO | matrix-element event generation | UoI/NCSA-style open license (see upstream) |
| Pythia 8 | parton shower + hadronization | GPL v2/v3 (invoked as an external library; not vendored) |
| Delphes | fast detector simulation | GPL v3 (invoked as an external binary; not vendored) |
| Rivet / YODA | particle-level analysis routines + histograms | GPL v3 |
| ATLAS SimpleAnalysis | published SR-yield analysis routines | Apache-2.0 (ATLAS public release) |
| RestFrames | recursive-jigsaw reconstruction | MIT (linked by the project-authored `rjr_resolve.cc`) |
| pyhf | HistFactory statistical models, CLs limits | Apache-2.0 |
| SModelS | independent simplified-model recasting cross-check | GPL v3 |
| MadAnalysis 5 | independent recasting cross-check | GPL v3 |
| mplhep / matplotlib / numpy / scipy / uproot | plotting + numerics + ROOT-file IO | BSD/MIT-family |
| mapyde | the reference pipeline this project reproduces and extends (arXiv:2306.11055) | Apache-2.0 |
| LHAPDF + PDF sets | parton distribution functions | GPL v3 (sets under their own terms) |

Derivation notes (stated for completeness and credit):
- `trial-runs/_infrastructure/native_simpleanalysis.py` is a from-scratch Python
  reimplementation of the **selection logic** of the ATLAS `EwkCompressed2018` SimpleAnalysis
  routine (Apache-2.0), validated bit-for-bit against the upstream implementation's outputs
  (141/141 signal regions). It contains no copied upstream source.
- `trial-runs/_infrastructure/rjr_resolve.cc` is a project-authored driver that reconstructs the
  same recursive-jigsaw tree the ATLAS analysis defines, by calling the RestFrames library (MIT).
- Delphes detector cards and MadGraph run/param cards used in runs are configuration files
  derived from the mapyde reference configurations (Apache-2.0).

HEPData content (published tables, likelihoods, efficiency maps) is public data released by the
experimental collaborations for exactly this kind of reinterpretation use; per-record DOIs are
cited in the run records that use them.
