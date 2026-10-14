# Checks and evidence: columnar-analysis

The five caught pitfalls resolve to actual checks in `columnar.recipe`,
`columnar_analysis`, `columnar.engine` and `columnar.expressions`. The public
compilation function returns a plan; it does not inspect files. Production
planning calls `columnar_analysis.inputs`, including every file and map.
A compiled expression is a plan object; use its `evaluate_cut` method for cuts.

The tests execute both marked blocks. A tiny local ROOT sample has positive and
negative weights and a flow entry. Its split and whole passes must retain the
same moments; overlap, plan drift, unknown weights, bad edges and a missing
branch are refused. A separate undefined-value test exercises negation.
These are arithmetic and schema controls, not detector calibration.

| Advisory ID | Candidate check | Evidence needed | Current enforcement |
|---|---|---|---|
| CA-A1 | Compare per-event decisions and weighted cutflow to an independent source implementation, including detector/trigger/overlap response | Source spans, same-event decisions, published cutflow or response controls, tolerances and independent review | Not implemented by recipe compilation; `columnar_analysis.specification_report` binds source items and open ambiguities, while acceptance certification remains a separate gate |

Runtime references: `src/ravel/physics/columnar/`, `columnar_analysis.py`,
`authored_analysis.py`, `reco_ntuple_routine.py`, `ntuple_inventory.py`,
`mc_expected_construction.py`, `dataset_query_quantities.py` and
`src/ravel/workflow/analysis_spec.py`. No external code is copied here.
