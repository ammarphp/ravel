# Review record: pyhf-workspace-patching

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "pyhf-workspace-patching",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "https://pyhf.readthedocs.io/ (Workspace, PatchSet)",
    "Heinrich, Feickert, Stark, Cranmer, pyhf: pure-Python implementation of HistFactory statistical models, JOSS 6 (2021) 2823",
    "RFC 6902, JavaScript Object Notation (JSON) Patch",
    "RAVEL src/ravel/physics/published_model.py and pyhf_exclude.py"
  ],
  "tested_versions": {"pyhf": "0.7.6", "jsonpatch": "1.33", "ravel": "0.4.0"},
  "executable_blocks": ["patch-with-digest"],
  "illustrative_blocks": [],
  "limits": ["The block was run on a tiny synthetic workspace, not a published likelihood."]
}
```
