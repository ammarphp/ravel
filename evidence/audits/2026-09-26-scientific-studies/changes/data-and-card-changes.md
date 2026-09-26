# Synthetic controls and input preservation

New data consist of small, explicitly synthetic event/object/measurement/model
fixtures. Rivet controls use twelve hand-constructed balanced massless event
records with artificial 1 pb cross sections. They are not showered or hadronized
predictions. No experimental data, cross-section tables, reference efficiencies
or historical run artifacts were changed. No competitor implementation was copied.

The pristine parent cards remain at their original hashes:

- `proc_card.dat`: `33f0290d75407e1b68dec5694744df21a95cfd05d22687efc24389f62dc34d54`
- `param_card_200_150.dat`: `b2c73dcbd5a3a95c22ecccaae60e3b9cb247fb88855f81e1740f52192d97cadd`

Development runs use ignored `local-runs/science-development/` in the active
source worktree, as required by the current distribution layout. They are
engineering controls, not new physics trial campaigns. Each successful study has
its inputs, approvals, execution state, outputs and RESULT; failures preserve logs
and spent-attempt receipts. Only the small curated evidence selection ships.

Workflow pointer: [scientific studies](../../../../docs/workflow/reference/scientific-studies.md).
Pedagogical pointer: [quantity semantics](../../../../docs/reference/quantities-and-measurements.md)
and [implementation report](../README.md).
