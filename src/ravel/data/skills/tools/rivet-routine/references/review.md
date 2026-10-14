# Review record: rivet-routine

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "rivet-routine",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "https://rivet.hepforge.org/",
    "Bierlich et al., Robust Independent Validation of Experiment and Theory: Rivet version 3, SciPost Phys. 8 (2020) 026, arXiv:1912.05451",
    "RAVEL src/ravel/physics/routine_build.py and docs/reference/routine-build.md",
    "RAVEL docs/reference/failure-modes.md C8 (pluginONNX routine without its weight file in rivet 4.1.3)"
  ],
  "tested_versions": {"rivet": "4.1.3 (not executed here)", "ravel": "0.4.0"},
  "executable_blocks": ["routine-data-files"],
  "illustrative_blocks": [],
  "limits": ["The data-file block scans routine source text; it does not compile or run the routine."]
}
```
