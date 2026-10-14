# Checks and evidence: cross-section-normalization

`cross_sections.lookup` owns registry selection and source identity;
`interpolate` owns only interpolation. The latter's input dictionaries are not
physics evidence. `k_factor` checks the two records' shared convention.
`normalization_ledger.validate` checks declarations; `check` recomputes and names
failures and warnings. Callers must inspect `passed`. A warning does not disappear
because the yields agree arithmetically.

Tests run both blocks with generic synthetic inputs. They check a power-law
interpolation and relative uncertainty, refusal of extrapolation and a zero
node, pb/fb equivalence, signed selected yields, errors from sumw2, bin-width
division, a zero denominator, missing sources, requested N and duplicated or
incompatible corrections. They do not fetch tables or run a generator.

| Advisory ID | Candidate check | Evidence needed | Current enforcement |
|---|---|---|---|
| XS-A1 | Match the requested final state, multiplicities, cuts, decay/filter inclusion and weight estimator to the production receipt and normalization source | Process cards, actual settings, source convention, generated census, signed-estimator definition and independent normalization audit | Partial: `cross_sections.k_factor`, `native_normalization.decay_factors`, `normalization_ledger.check` and `check_engine_scale` check their declared inputs; none establishes an unrecorded physical equivalence |

Read-only implementation references: `cross_sections.py`,
`normalization_ledger.py`, `native_normalization.py`, `group_normalization.py`,
`simplified_spectrum.py`, and `src/ravel/physics/columnar/engine.py`.
The cross-section table registry is existing RAVEL package data, not newly
invented or copied physics inputs.
