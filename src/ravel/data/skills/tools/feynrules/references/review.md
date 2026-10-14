# Review record: feynrules

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "feynrules",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "FeynRules 2.0 manual: Alloul et al., Comput. Phys. Commun. 185 (2014) 2250, arXiv:1310.1921",
    "https://feynrules.irmp.ucl.ac.be/",
    "RAVEL src/ravel/physics/model_physical_checks.py, model_derivation_bridge.py and ufo_interop.py"
  ],
  "tested_versions": {"feynrules": "2.3.49 (not executed here; needs a licensed kernel)", "ravel": "0.4.0"},
  "executable_blocks": ["python2-raise-rewrite"],
  "illustrative_blocks": ["fr-session-shape"],
  "limits": [
    "Wolfram-language blocks are illustrative; no kernel runs in the tests.",
    "The rewrite block covers only the literal UFOError raise form that ufo_interop admits."
  ]
}
```
