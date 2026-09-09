# Data and card changes

## 2026-09-09 scoped controls

Added a 2jl single-bin approximation using n=263, b=283, uncertainty 24 and luminosity 3.2 fb^-1,
plus a 100-event LO Drell–Yan specification with explicit model, PDF, scales, cuts and bins.
A declared synthetic two-bin likelihood tests a different nuisance structure. Seed, scale,
flavor and supplied-card controls use copied specifications. Public card copies normalize
whitespace and redact the local home prefix in header paths. Original records and hashes remain.

No RRR signals, templates, experimental data, historical samples or pristine parent cards
were edited. Original parent-card SHA-256 values remain:

- proc_card.dat: 33f0290d75407e1b68dec5694744df21a95cfd05d22687efc24389f62dc34d54
- param_card_200_150.dat: b2c73dcbd5a3a95c22ecccaae60e3b9cb247fb88855f81e1740f52192d97cadd

Workflow: [scoped execution](../../../docs/workflow/reference/scoped-workflows.md).
Interpretation: [control definitions](../README.md).
