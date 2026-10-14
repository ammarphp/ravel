# Review record: hepdata-retrieval

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "hepdata-retrieval",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "https://www.hepdata.net/",
    "https://github.com/HEPData/hepdata-cli",
    "RAVEL src/ravel/workflow/hepdata_fetch.py (endpoint notes tested 2026-08-28)"
  ],
  "tested_versions": {"hepdata-cli": "0.3.1 (not executed here)", "ravel": "0.4.0"},
  "executable_blocks": ["record-table-urls"],
  "illustrative_blocks": [],
  "limits": ["No network access in the tests; the block builds URLs from a synthetic record JSON."]
}
```
