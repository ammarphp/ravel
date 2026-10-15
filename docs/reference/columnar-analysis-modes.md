# Columnar ntuple analysis modes

These scientific modes prepare and check a complete ntuple-based search analysis: an
analysis challenge, a new search on supplied samples or a blinded study with Monte Carlo
expectations. Each mode takes one pinned request, runs through `ravel plan`, CHECK-IN 1
approval and the supervised worker, and delivers only its named scope.

| Mode | Module | Delivers |
|---|---|---|
| `ntuple-inventory` | `ntuple_inventory` | Inventory check, nominal selection kernel and, when every input is present, a ROOT-stream specification |
| `mc-expected-construction` | `mc_expected_construction` | Expected SR/CR source construction from a completed MC stream delivery |
| `mc-closure` | `mc_closure` | Closure of a frozen prediction against an independent held-out MC replica |
| `asimov-sensitivity` | `asimov_sensitivity` | Same-dataset Asimov discovery profiles and the local expected q0 |

The selection recipe is `columnar_ntuple_recipe.validate_recipe` (schema 1, nominal flags)
or `columnar_selection` (schema 2, changed working points, ordered delta-R overlap removal
and a source-declared joint trigger response from `columnar_response`).

No ntuple container, period or branch table is built into the code. A recipe carries them
as a `branch_roles` descriptor, required for schema 2 and optional for schema 1. The value
is either the descriptor below or the identifier of a packaged one
(`ravel.physics.columnar_ntuple_recipe.library_names()`); a named descriptor is resolved into
the recipe, so the recipe's digest covers the exact roles used:

```json
{"schema_version": 1, "kind": "columnar-branch-roles", "name": "...", "source": "...",
 "branches": [{"name": "...", "role": "scale_weight", "shape": "scalar", "unit": "1"}],
 "families": [{"pattern": "<regex>", "role": "baseline_or", "shape": "jagged", "unit": "1"}],
 "periods": ["2018"], "period_scoped_weights": {"<scalar weight>": ["2018"]},
 "containers": [{"prefix": "el", "selections": ["baseline", "signal"], "overlap_selections": ["baseline"]},
                {"prefix": "fatjet", "selections": ["stored"], "overlap_removal": ["largeR"],
                 "tagger": true, "tagger_valid": "<regex for the calibrated-range flag>"}]}
```

`containers` is optional. When present the container list is closed: a recipe object must use a
listed `prefix` and one of its `selections` (`overlap_selections` while stored overlap removal
applies), a tagger needs `"tagger": true` and a name matching `tagger_valid`, and
`overlap_removal` limits the recipe's overlap choice for that container.

Packaged descriptors:

| Identifier | Format |
|---|---|
| `atlas-cp-nominal-ntuple` | Flat ntuples written by ATLAS CP-algorithms analysis configurations: `<container>_<decoration>[_NOSYS]` kinematics in MeV, `select_` flags and stored overlap-removal flags, scale-factor, trigger, stored-MET and `PL_` particle-level families, the Run 2 and Run 3 period keys, the Run 2-only beamspot weight and the lepton/photon/tau/jet/large-R container table. This reproduces the former built-in role table; whether a branch exists remains the branch schema's to establish |
| `atlas-opendata-13tev-ntuple` | The ATLAS Open Data 13 TeV ntuple branch table (`lep_`, `jet_`, `photon_`, `largeRjet_`, `tau_` families, `scaleFactor_*`, `met_*`, `trig*`); dimensionful units are null because the public page states none |

Exact names take precedence over family patterns. A `null` unit means the format fixes no
absolute unit, so the branch list must state one. A branch with a known role cannot be retyped
as a recoil component or a scalar response coordinate, and a `baseline_or` flag cannot define a
changed predicate. `periods` limits the trigger map's keys, and `period_scoped_weights` refuses
a scalar weight outside its periods. Without a descriptor a schema-1 recipe accepts any
four-digit period and literal scalar weight; whether a branch exists is the branch list's to
establish.

## `ntuple-inventory`

`task = {"request": pin}`. The request has `schema_version: 1`, `original_goal`,
`goal_binding`, `requirements`, `inventory`, `recipe`, `branches`, `resolved_members`,
`sample_definitions`, `site_runtime`, `review_policy`, `assumptions` and `portfolio`.
Optional external documents are `null` until they are available.

The `requirements` document is the task roster supplied with the request:

```json
{"requirements": [{"id": "..."}], "target_families": ["..."], "stages": ["..."]}
```

Requirement identities, families and stages are nonempty and unique. The `portfolio`
(schema 2) has `stages` (one row per roster stage, in roster order, each with `id`,
`request` and `missing`), `prepared_stages` (the roster stages this preparation serves),
`target_families` (exactly the roster families) and `missing_scientific_inputs`. The result
lists every stage outside `prepared_stages` as remaining work.

The branch list is the exact scalar and jagged dtype/unit roster that the recipe needs.
Resolved members keep DID, GUID, Adler32 and inventory count in original order and add
observed analysis entries, byte size, ROOT URI, sample and source pin. Inventory counts are
not analysis entry counts. Missing members, sample definitions, normalizations or a site
runtime give a delivered preparation with the missing inputs listed.

The Host action `ntuple-inventory-context` gives a design role the same source context
for a declared Graph input.

## `mc-expected-construction`

The request has `schema_version: 1`, `stream_task`, `stream_result`, `stream_closure`,
`design`, `goal_binding` and `original_goal`. The design maps each MC sample quantity to
the complete ordered SR/CR basis, keeps MC moments and declares the expected-profile
generating point. Observed bins stay null; the output is a constructor input for a new
reviewed statistical construction.

## `mc-closure`

The request has `schema_version: 2`, `original_goal`, `goal_binding`, `requirements`,
`strategy`, `independence`, `cohorts` and `partition_protocol`. The `requirements` document
is the task roster above; for this mode `target_families` and `stages` are optional. The
frozen strategy and independence declarations are inputs of both ROOT producers. The
prediction and held-out cohorts are complete independent MC replicas with their own
ordinary stream deliveries. The Host action `mc-closure-context` supplies the source context.

## `asimov-sensitivity`

A `native_statistical_construction` cell with a `discovery_diagnostic` request emits this
mode's task. It profiles one source-Asimov dataset at the declared signal strength with
the full start population, keeps every fit in the journal and reports
`q0,A = 2 (NLL_null - NLL_free)`. `sqrt(q0,A)` is a local expected asymptotic value. The
Host action `asimov-sensitivity-context` supplies the recipe and work budget to the research
coordinator.
