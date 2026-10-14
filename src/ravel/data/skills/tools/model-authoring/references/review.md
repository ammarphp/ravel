# Review record: model-authoring

Machine review during RAVEL development. It is not a physicist review.
Upstream titles and versions are citation pointers; no network retrieval was performed.

```json
{
  "skill": "model-authoring",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "Alloul et al., FeynRules 2.0 - A complete toolbox for tree-level phenomenology, arXiv:1310.1921, 2014; runtime pin 2.3.49",
    "Degrande et al., UFO - The Universal FeynRules Output, arXiv:1108.2040, 2012",
    "RAVEL docs/reference/models-and-normalization.md and model-sources.md",
    "RAVEL src/ravel/physics/model_authoring.py, fr_lint.py, ufo_check.py and model_physical_checks.py"
  ],
  "tested_versions": {
    "FeynRules": "2.3.49 (manifest pin; not executed)"
  },
  "executable_blocks": [
    "static-model-census",
    "inspect-ufo"
  ],
  "illustrative_blocks": [],
  "limits": [
    "Only static synthetic model rendering and UFO AST parsing run in tests.",
    "No native gauge check, export, model admission or physics trust promotion is claimed.",
    "Re-review when the model-admission contract changes."
  ]
}
```
