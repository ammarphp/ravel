# Review record: cross-section-normalization

Machine review during RAVEL development. It is not a physicist review.
Upstream titles and versions are citation pointers; no network retrieval was performed.

```json
{
  "skill": "cross-section-normalization",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "LHC SUSY Cross Section Working Group: cross-section tables and conventions; use the source edition and table hash in the RAVEL registry",
    "Allanach et al., SUSY Les Houches Accord 2, arXiv:0801.0045, 2008",
    "NumPy reference, version 1.26; SciPy reference, version 1.14.1",
    "RAVEL docs/reference/models-and-normalization.md",
    "RAVEL src/ravel/physics/cross_sections.py, normalization_ledger.py and native_normalization.py"
  ],
  "tested_versions": {
    "numpy": "1.26.4",
    "scipy": "1.14.1"
  },
  "executable_blocks": [
    "audit-normalization",
    "interpolate-supplied-table"
  ],
  "illustrative_blocks": [],
  "limits": [
    "Interpolation uses a synthetic table; no published physics value is asserted.",
    "A ledger audit establishes declared arithmetic and basis consistency, not the truth of its source statements.",
    "No generator, table download or new spectrum generation runs here."
  ]
}
```
