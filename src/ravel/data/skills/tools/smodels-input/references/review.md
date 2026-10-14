# Review record: smodels-input

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "smodels-input",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "https://smodels.readthedocs.io/",
    "RAVEL src/ravel/physics/reinterpret_db.py (validate_document)"
  ],
  "tested_versions": {"smodels": "3.1.1 (not executed here)", "ravel": "0.4.0"},
  "executable_blocks": ["slha-input-census"],
  "illustrative_blocks": [],
  "limits": ["The census checks for block presence; it does not validate the spectrum or the cross sections."]
}
```
