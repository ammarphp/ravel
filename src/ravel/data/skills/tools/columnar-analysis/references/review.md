# Review record: columnar-analysis

Machine review during RAVEL development. It is not a physicist review.
Upstream titles and versions are citation pointers; no network retrieval was performed.

```json
{
  "skill": "columnar-analysis",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "Uproot documentation, version 5.3.12: reading TTrees",
    "Awkward Array documentation, version 2.6.7: broadcasting and jagged arrays",
    "NumPy reference, version 1.26",
    "RAVEL docs/reference/columnar-analysis.md and columnar-analysis-modes.md",
    "RAVEL src/ravel/physics/columnar/ and columnar_analysis.py"
  ],
  "tested_versions": {
    "uproot": "5.3.12",
    "awkward": "2.6.7",
    "numpy": "1.26.4"
  },
  "executable_blocks": [
    "compile-columnar-recipe",
    "merge-columnar-partitions"
  ],
  "illustrative_blocks": [],
  "limits": [
    "Only tiny synthetic local ROOT files and pure Python operations run in tests.",
    "No source-analysis acceptance or detector response has been certified.",
    "Site, native routine and authored analysis execution are documented from source, not executed here."
  ]
}
```
