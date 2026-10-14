# Review record: madgraph-model-import

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "madgraph-model-import",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "MadGraph5_aMC@NLO 2.9.27 source: madgraph/interface/madgraph_interface.py (help import: restrict_default.dat and the -full suffix) and models/import_ufo.py",
    "UFO format: Degrande et al., Comput. Phys. Commun. 183 (2012) 1201, arXiv:1108.2040",
    "RAVEL src/ravel/physics/model_events.py (inputs, render_scripts) and src/ravel/physics/ufo_interop.py"
  ],
  "tested_versions": {"madgraph": "2.9.27 (source read; no import run)", "ravel": "0.4.0"},
  "executable_blocks": ["ufo-census"],
  "illustrative_blocks": [],
  "limits": ["The census checks file presence only; it does not import or evaluate the UFO."]
}
```
