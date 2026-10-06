# Walkthrough — the SimpleAnalysis path (a search with a published likelihood)

A filled-in shape of `docs/workflow/README.md` for an analysis that ships a SimpleAnalysis routine + a serialized
pyhf likelihood (typical of compressed / electroweak SUSY searches). Replace the bracketed values.

| Step | What you do |
|---|---|
| 2 routine | `routine_fetch.py --query "[code/Inspire]"` → the SimpleAnalysis `DefineAnalysis` name; see `docs/workflow/analysis-simpleanalysis/` |
| 2 model | the electroweak/compressed simplified model the analysis targets; cards per `docs/workflow/checklists/model-cards.md` |
| 3–4 run | MadGraph → Pythia → Delphes → SimpleAnalysis → `sa2json` → signal patch — **native VM-free backend by default for EwkCompressed2018** (`docs/workflow/reference/native-pipeline.md`), else the containerized `docs/workflow/analysis-simpleanalysis/` fallback |
| 6 data | `hepdata_fetch.py --download-likelihood` → the published background-only workspace; `nlo_xsec.py` for the k-factor |
| 7 exclude | `pyhf_exclude.py likelihood --bkg <bkgonly> --patch <patch> --sigma-scale [k]` → µ₉₅ from the full combined likelihood |
| cert | `validate_cutflow.py` vs the published acceptance figures; the limit reaches the true CLs=0.05 crossing |

The combined likelihood carries the control regions + correlations, so a multi-region/multi-bin
analysis needs no simplification (`docs/workflow/checklists/complex-analysis.md`). A point at the edge of the
search's reach gives a large µ₉₅ — that is a real result, not a failure.
