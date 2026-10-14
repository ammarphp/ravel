# Review record: lhapdf-pdf-sets

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "lhapdf-pdf-sets",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "LHAPDF 6: Buckley et al., Eur. Phys. J. C 75 (2015) 132, arXiv:1412.7420; https://lhapdf.hepforge.org/",
    "LUXlep-NNPDF31_nlo_as_0118_luxqed.info from the official LHAPDF set archive (SetIndex 82400, DataVersion 2, NumMembers 101, ErrorType replicas, Flavors)",
    "Buonocore, Nason, Tramontano, Zanderighi, arXiv:2005.06477 (cited by the LUXlep set)",
    "MadGraph5_aMC@NLO 2.9.27 source: Template/LO/Cards/run_card.dat (lpp comment) and madgraph/various/banner.py (create_default_for_process)",
    "MadGraph5_aMC@NLO 3.7.0 Template/LO/Cards/run_card.dat (lpp and pdlabel comments), https://github.com/mg5amcnlo/mg5amcnlo",
    "RAVEL src/ravel/physics/model_events.py and pdf_variations.py"
  ],
  "tested_versions": {"lhapdf": "6.5.6 (set metadata only)", "madgraph": "2.9.27 source; 3.7.0 run card template", "ravel": "0.4.0"},
  "executable_blocks": ["pdf-info-flavours", "beam-readback"],
  "illustrative_blocks": [],
  "limits": [
    "No generation was run with LUXlep; the MadGraph 3.7.0 beam handling is read from its run card template only.",
    "The model-events lepton-beam route is outside this release."
  ]
}
```
