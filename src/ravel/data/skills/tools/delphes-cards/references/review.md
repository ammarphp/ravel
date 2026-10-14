# Review record: delphes-cards

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "delphes-cards",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "Delphes 3.5.1 source tree: cards/delphes_card_CMS.tcl and cards/delphes_card_ATLAS.tcl (ECal and HCal EnergyFraction rows, MissingET and GenMissingET modules, NeutrinoFilter)",
    "de Favereau et al., DELPHES 3, JHEP 02 (2014) 057, arXiv:1307.6346",
    "https://delphes.github.io/",
    "RAVEL src/ravel/physics/delphes_cards.py and delphes2sa_native.py"
  ],
  "tested_versions": {"delphes": "3.5.1 (stock CMS and ATLAS cards read by delphes_cards.invisible_census; 1000039 and 1000012 reported visible)", "ravel": "0.4.0"},
  "executable_blocks": ["invisible-census"],
  "illustrative_blocks": [],
  "limits": [
    "The census reads calorimeter energy fractions and the MET filters; it does not model tracking of charged states.",
    "Other stock cards were not reviewed."
  ]
}
```
