# Whole resonance studies

`resonance-study` connects a finite, explicit set of physical alternatives and supplied searches to ordinary scientific studies. It prepares an explicitly selected stage, consumes separately accepted predecessor outputs, and reports every declared hypothesis/search pair. Existing science, Graph, review and original-task APIs retain execution and acceptance authority.

For a toponium study, retain the whole task contract: interpreting a putative toponium signal as a new resonance, assessing constraints from other LHC searches, and producing a summary plot. A mass label is insufficient to define a resonance. Supply mass, total width, spin/CP, collision energy, production channels, decay branching fractions, complex coupling values with units and coefficient conventions, and an interference/prediction basis. Scalar and pseudoscalar alternatives are distinct physical hypotheses. Relabeling one hypothesis twice refuses. Production, decay-channel, signed daughter and coupling rosters are canonical unordered populations. Exact integer/binary64 values share identity when equal (including signed zero); nearby unequal values are not rounded together.

## Recipe and source meanings

A schema-1 recipe contains `parent_contract` (path/SHA256/size), `census_scope`, `hypotheses`, `searches`, `correlations`, `stages` and `pairs`. Pins elsewhere are path/SHA256. Absolute canonical input/output paths simplify relocation. The parent contract must carry ordinary task requirements; every child study retains its exact `goal_binding.contract` and an original assignment ID. Compilation preserves the complete original parent goal.

Each hypothesis supplies `id`, `interpretation`, `spin`, `cp`, `mass_gev`, `width_gev`, `energy_tev`, `production`, `decays` (`products` are signed daughter PDGs, with `branching_ratio`), `couplings` (`name`, `real`, `imag`, `unit`, `convention`), `interference`, `basis`, `model`, `sources` and `missing`. These are source-bound premises. The compiler authenticates bytes and checks finite/domain structure. The Lagrangian-to-UFO/card coefficient map and width consistency require supplied model/card construction and independent review.

Each search supplies `id`, `experiment`, `version`, `source`, `routine_ids`, `applicability`, `observable` and `missing`. Applicability gives mass and relative-width closed intervals (or `null` when unknown), energy, supported spins/CP, production, signed decay products and prediction bases. Verify installation against the selected routine source and runtime. Observable fields are `quantity`, `unit`, `confidence` and `scope`; their meanings must come from the exact source. Missing numeric curves, likelihoods, templates or convention mappings remain blockers. Never infer them from a title, plot label or source pin.

`pairs` is the complete Cartesian product of hypothesis and search IDs. Each row contains a pinned exact physical `mapping` or `null`, declared stage IDs, an optional existing `backend_portfolio` pin, and missing obligations. A mapping binds the full hypothesis/search hashes, basis, observable, located source pins and scope conditions. Omitted/incompatible pairs must not disappear from the denominator. Every unordered search pair has an explicit `independent`, `shared` or `unknown` correlation record, source pins and meaning. Likelihood combination requires its own admitted statistical operation and source-grounded independence model.

## Connected ordinary execution

Each stage supplies `id`, hypothesis/search IDs (search can be null for a common upstream stage), a role, an existing schema-2 study pin, document bindings, predecessor links, exports, claim scope and missing obligations. Ordinary studies require one attempt, zero redos and their original review policy. Allowed roles use existing operations:

| Stage | Existing operation examples |
|---|---|
| Event/search response | `analyze`, `ma5-pad`, `ma5-saf`, `quantities`, `group-normalization` |
| Template/full output | `signal-template`, `scientific-delivery` |
| Plot/source summary | `published-summary`, `scientific-delivery` |

Supply the actual adapter contracts/runtime closure, rather than inventing a generic runtime alias. `model_event_plan.prepare` remains the generator blueprint builder. `prepare_backends` delegates an applicable pair to `backend_portfolio.prepare`. `research_portfolio` delegates complete rival proposals to `research_blueprint.bound_portfolio`; the existing research cycle owns admission and dispatch.

For interference, positive-only `signal-template` lowering is refused. The `construct_regional` API delegates a supplied full-bin signed law to `statistical_construction.write_native_bundle`. It preserves background + signed interference + quadratic contributions in the TOTAL mean, signal/control contamination, the parameter domain and supplied auxiliary law. It prepares an observed `MultiDimFit` task. Native positivity, parameter-domain behavior, parity, fit quality and calibration require their applicable scientific evidence. Signed contributions remain inside the positive TOTAL Poisson mean; covariance and independence require supplied source laws.

A document binding is `{id,task_key,source}`. A link is `{document,pointer,from_stage,export}` and replaces an existing exact pin-shaped slot using a separately accepted predecessor export. It must point backward within the same physical hypothesis/search. Every stage exports the complete `result.json`; other exports are explicit relative paths. Native tasks with top-level `input_sha256` or `contract_sha256` receive the new commitment for the SAME serialized copy. Physical labels and digest strings are not relocated as pathnames.

```console
ravel resonance-study assess --request /absolute/recipe.json
ravel resonance-study prepare --request /absolute/recipe.json --stage selected_stage --runs /absolute/predecessor-runs.json --out /absolute/fresh-preparation
ravel plan --rundir /absolute/fresh-preparation/ordinary-study --spec /absolute/fresh-preparation/science.json
```

`predecessor-runs.json` maps prior stage IDs to unchanged ordinary run directories; use `{}` for a first stage. The preparation calls the real selected adapter's input/resource checks. The generated specification carries a `resonance_handoff`; ordinary plan/approval/worker/result input enumeration rebinds the whole source recipe and current predecessor review/reuse gates. An old output needs successful ordinary execution, the current exact accepted claim scope, a valid detached reuse snapshot and unchanged full output membership. Held/unreviewed results must not feed a successor. Root must supply the existing approval/native lease and actual independent reviews before any scientific job. Inspect and execute the ordinary next command under its existing approval and retry policy.

For the requested summary plot, provide a `published-summary` stage with actual source curves on a compatible quantity/model/energy basis, including a complete retained-series census and its required scope/precision declarations. It uses the existing published-summary figure route. An incompatible ttbar coupling limit must not be relabeled as a cross-section limit, and a source limit must not constrain a different loop/flavor/width convention without a separately grounded map. Failed or absent native work is not a numerical zero.

For `published-summary`, the compiler projects every supplied panel's typed energy and literal target-basis/window from the same captured contract/survey/manifest bytes, and runs the existing summary census validator on those objects. A panel energy different from its hypothesis or assigned search refuses before output creation. Each such stage must carry `target_mapping`, a pinned schema-1 document with `original_study`, full `hypothesis_sha256`/`search_sha256` (null when no search), `projected_target`, `correspondence`, located `sources` and `limitations`. `correspondence` retains the selected hypothesis interpretation (`model`), full search `observable` (or null), declared `basis`, and explicit `meaning` for any source label correspondence. The map binds the actual full projection and original study bytes; it is a source premise, not proof of a model transformation. A source scope condition blocks preparation. Accepted predecessor links must leave this mapped typed target unchanged; a different target requires a new explicit source recipe/study.

The summary projection preserves null prediction-basis and unit fields. Supply explicit source-grounded energy and unit mappings. Modes with an opaque typed projection retain `unprojected_source_premise` and the original study pin. Complete adapter input checks and independent scientific review establish the mapping meaning.

## Whole return and report

```console
ravel resonance-study collect --request /absolute/recipe.json --runs /absolute/terminal-runs.json --out /absolute/fresh-summary
```

Collection retains every terminal stage's full native output inventory and complete returned result, including failed, held and unreviewed results. Each optional quantity is an exact result JSON pointer with its literal unit/meaning. Returned nulls and absent selectors stay distinct. `accepted_scoped_deliveries` means only the specified review scope accepted those deliveries; the raw result status remains visible and can be failed. The collected result retains that exact scoped-delivery status.

`cross-search-summary.json`, strict artifact/report recipes, `report.json` and `REPORT.md` retain all pairs and correlation scope conditions. They use the existing `scientific_artifact` and `scientific_report` consumers. Whole-task completion requires genuine full outcomes, the requested plot and ordinary parent review through `task_completion`. Independent sources, physical maps, coverage of all relevant searches and scientific interpretation remain reviewer obligations.

The Host exposes `resonance-assess`, `resonance-prepare` and `resonance-collect` as ordinary tool actions with exact request/selection plus the full bound input population. Preparation/collection output stays within configured Host roots. Blind critic/verifier roles must not invoke these context-rich construction tools. Only ordinary Graph accounting is used.
