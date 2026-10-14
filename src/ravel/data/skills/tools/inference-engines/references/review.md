# Review record: inference-engines

Machine review during RAVEL development. It is not a physicist review.
Upstream titles and versions are citation pointers; no network retrieval was performed.

```json
{
  "skill": "inference-engines",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "pyhf documentation, version 0.7.6: models, modifiers and inference",
    "iminuit documentation, version 2.32.0: minimization and fit validity",
    "Cowan, Cranmer, Gross, Vitells, Asymptotic formulae for likelihood-based tests of new physics, arXiv:1007.1727, 2011",
    "SciPy reference, version 1.14.1",
    "RAVEL docs/reference/inference-engines.md and src/ravel/physics/inference/"
  ],
  "tested_versions": {
    "pyhf": "0.7.6",
    "iminuit": "2.32.0",
    "scipy": "1.14.1"
  },
  "executable_blocks": [
    "evaluate-prescribed-statistic"
  ],
  "illustrative_blocks": [],
  "limits": [
    "Only a synthetic closed-form rule is executed by the handbook tests.",
    "No coverage calibration, native likelihood or published result is claimed.",
    "The open-edge test checks result failure and boundary status, not an authorized scan extension."
  ]
}
```
