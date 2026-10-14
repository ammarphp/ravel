# Review record: ma5-expert

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "ma5-expert",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "https://madanalysis.irmp.ucl.ac.be/",
    "Conte, Fuks, Serret, MadAnalysis 5, Comput. Phys. Commun. 184 (2013) 222, arXiv:1206.1599",
    "Conte, Dumont, Fuks, Wymant, Designing and recasting LHC analyses with MadAnalysis 5, arXiv:1405.3982",
    "RAVEL src/ravel/physics/ma5_saf_reader.py, ma5_saf.py and ma5_pad.py"
  ],
  "tested_versions": {"ma5": "1.11.1 (not executed here)", "ravel": "0.4.0"},
  "executable_blocks": ["saf-counters"],
  "illustrative_blocks": ["expert-mode-shape"],
  "limits": [
    "The SAF block reads supplied text only.",
    "Expert-mode commands are illustrative and were not run in this review."
  ]
}
```
