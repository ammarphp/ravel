# Review record: roofit-histfactory

Machine review during RAVEL development. It is not a physicist review.
Upstream titles and versions are citation pointers; no network retrieval was performed.

```json
{
  "skill": "roofit-histfactory",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "ROOT reference guides, version 6.22: RooFit and RooStats",
    "Cranmer et al., HistFactory: A tool for creating statistical models for use with RooFit and RooStats, CERN-OPEN-2012-016, 2012",
    "pyhf documentation, version 0.7.6: HistFactory models",
    "RAVEL docs/reference/statistical-construction.md, domain-adapters.md and columnar-analysis-modes.md",
    "RAVEL src/ravel/physics/native_statistical_construction.py, statistical_model.py, asimov_sensitivity.py and mc_closure.py"
  ],
  "tested_versions": {
    "ROOT": "6.22 (manifest pin only; not executed)",
    "pyhf": "0.7.6 (manifest pin; source-integral example does not import pyhf)"
  },
  "executable_blocks": [
    "source-template-integral"
  ],
  "illustrative_blocks": [],
  "limits": [
    "Only exact source arithmetic and structural refusal run here; no RooFit, Combine or site job runs.",
    "The integral helper expects the template structure to have passed full constructor validation.",
    "Native model equivalence, optimizer convergence and coverage require separate evidence."
  ]
}
```
