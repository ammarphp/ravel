# Review record: mcfm-amplitudes

Machine review during RAVEL development. It is not a physicist review.
Upstream titles and versions are citation pointers; no network retrieval was performed.

```json
{
  "skill": "mcfm-amplitudes",
  "reviewed": "2026-10-13",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "MCFM manual, version 10.2.1: process definitions and integration conventions",
    "NumPy reference, version 1.26: complex arrays and einsum",
    "Buckley et al., The HepMC3 Event Record Library for Monte Carlo Event Generators, arXiv:1912.08005, 2020",
    "RAVEL docs/reference/amplitude-reweighting.md",
    "RAVEL src/ravel/physics/amplitude_basis.py, amplitude_records.py, amplitude_store.py, amplitude_predictions.py and weighted_events.py"
  ],
  "tested_versions": {
    "MCFM": "10.2.1 (manifest pin; not executed)",
    "numpy": "1.26.4"
  },
  "executable_blocks": [
    "recombine-amplitudes",
    "read-completed-block"
  ],
  "illustrative_blocks": [],
  "limits": [
    "All amplitudes and block records in handbook tests are synthetic.",
    "Installer build, adoption, confinement and record defaults are tested with inert clients; native qualification remains open.",
    "No native scientific program runs here.",
    "Same-program square closure and phase alignment are narrower than physics accuracy."
  ]
}
```
