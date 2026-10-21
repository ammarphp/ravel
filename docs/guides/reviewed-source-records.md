# Reviewed source records

A source review is an input to a scientific request. It describes the exact
source bytes, the affected fields, and the review evidence. The package supplies
the schema and checker. The requester supplies the records and selects them by
file path and SHA256.

| Record | What it controls | What is preserved |
|---|---|---|
| Errata registry | A metadata pointer, its literal value, archive members and external attribution assertions | Original archive and workspace bytes |
| Repair manifest | Expected field values, copies, replacements, retained fields and parser projections | Original values, paired-row lineage and correction evidence |
| Defect registry | Physical-input coverage, unresolved defects and reviewed resolutions | Active holds under identity renaming and numeric-equivalent spelling |
| Cutflow definition | Predicates, ordered flows, missing decisions, region membership, reference rows and normalization | Original event exposure, signed moments and shared-event covariance |

Every record selects its own context. Study identity, named parameter axes,
dataset population and output format travel with that supplied context. A card
repair also selects its output filename and identity template. The transformation
engine keeps original and corrected identities separately.

A missing reviewed record produces a typed refusal. An active physical defect
requires a matching resolution with pinned source evidence. Removing or renaming
an affected row supplies no review of the remaining population. Coalescence
requires identical observation and prediction rows. A parser projection retains
the complete original list and its resulting list in the receipt.

Input review and scientific qualification are separate obligations. A review
receipt records custody and disposition. Detector fidelity, response validity,
fit accuracy and statistical coverage require their own supplied reference
quantities and executed comparisons. All source-record software controls use
fictional inputs.

The schema is `src/ravel/data/source_records/records.schema.json`. Operational
instructions are in `docs/workflow/steps/sfitter.md` and
`docs/workflow/reference/scientific-studies.md`.
