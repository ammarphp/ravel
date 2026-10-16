# Step 2 — Inputs  ·  [judgment]  ·  CHECK-IN

Before sending inputs to a model, pin the run's
[data classification and allowed transport accounts](../reference/provider-policy.md).
Restricted input pins require an explicit restricted declaration at run start.

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below. The metadata
steps (resource census, routine lookup, HEPData and figure fetches) run with the project Python;
`$CONDA` is needed for the Rivet commands.

Decide the analysis routine and the model. Requires physics judgement.

0. **RESOURCE SWEEP (mandatory, before anything is declared unavailable).** The `resource-sweep`
   skill / `resource_census.py` walks HEPData (tables + the RESOURCES tab, where full likelihoods
   and efficiency maps live), the routine resolvers, arXiv source, GitHub (repos AND code search —
   recast repos rarely carry the analysis id in their name), and INSPIRE forward-citations
   (theses carry cutflows):
   ```bash
   python scripts/run.py ravel.workflow.resource_census \
       --inspire <recid> --arxiv <id> --analysis-id <code> --rundir <rundir> --markdown
   ```
   Several analyses: repeat `--analysis inspire=<recid>[,arxiv=<id>][,id=<code>]`. A survey,
   summary or study with no reference paper: `--keyword "<topic words>"` searches HEPData and
   INSPIRE and censuses the top `--limit` candidates (`--search-only` records the search alone).
   → one record per analysis or search in `<rundir>/inputs/resource_census/`, the index
   `<rundir>/inputs/resource_census.json`, and the CHECK-IN 1 census block. LOOK at every GitHub
   hit and likelihood/efficiency-map candidate before routing; run the trap-sweep
   (`docs/workflow/checklists/physics-traps.md`) alongside it. Read the HEPData rung's STATUS, not just its
   contents: `ABSENT` = definitively no record (open-API 404, INSPIRE-corroborated — plan around
   absence); `ERROR outage-or-block` = unreachable, NOT evidence of absence (retry/browser).

1. **Routine.** Resolve the analysis to a routine across **both** ecosystems at once — Rivet (Option A)
   and SimpleAnalysis (Option B) — from a paper code, Inspire id, or keyword:
   ```bash
   python scripts/run.py ravel.workflow.routine_fetch --query "<ATLAS-SUSY-20XX-XX | insNNNN | keyword>"
   ```
   It prints the matching Rivet routine id (→ step 4A) and/or the SimpleAnalysis `DefineAnalysis` name
   (→ step 4B, the mapyde `[simpleanalysis] name`). **It matches the analysis CODE / literal ids**
   (an experiment analysis code, an Inspire or arXiv id) against the routine files — **not physics
   vocabulary** — so a keyword query ("compressed sleptons") can return 0 hits for an analysis that
   IS covered: extract the code from the paper or HEPData first, then re-query with it. To get the
   **Inspire id** (`insNNNN`, needed below) from an analysis code: search hepdata.net for the code,
   read it off the matched Rivet routine id (`..._I<NNNN>` → `ins<NNNN>`), or skip it —
   `hepdata_fetch.py --routine <RIVET_ID>` resolves the Inspire id from the routine name itself.
   Then confirm a Rivet routine's data:
   ```bash
   $CONDA run -n rivet rivet --show-analysis <RIVET_ID> | grep -iE "Beams|luminosity|Status|Keywords"
   ```
   See `docs/workflow/checklists/choosing-routine.md`; for SimpleAnalysis, `docs/workflow/analysis-simpleanalysis/`.
2. **Model + cards.** Define the process and parameter cards for the model under test (see
   `docs/workflow/checklists/model-cards.md`). Either use cards supplied by the requester, or write them — the
   final state the model produces must be one the chosen routine selects on.
   Without a supplied model: write simplified-model SLHA cards with `ravel simplified-spectrum`, or author a
   FeynRules model from the Lagrangian with `ravel model` (ModelSpec or template, confirmed at CHECK-IN 1).
   Take the signal cross section from `ravel xsec` with its order, PDF and scale named, derive branching and
   filter factors with `ravel normalization factors`, and keep them in a normalization ledger
   (`ravel normalization-ledger`). See `docs/reference/models-and-normalization.md`.
   For a neutral resonance, inspect `ravel lineshape table` for the channel's formula, selection rule
   or free-width path. Use `ravel lineshape plan` to disclose the selected conventions and total-width
   source at CHECK-IN 1; `free` declares a total width independent of the couplings.
3. **Figure target ([judgment]).** Declare WHICH published figure this run reproduces — the figure
   contract (`docs/workflow/checklists/figure-contract.md`). If the requester named it ("reproduce Fig N of
   arXiv:…"), declare directly; else resolve candidates from the HEPData figure index and choose:
   ```bash
   python scripts/run.py ravel.workflow.hepdata_fetch \
     --inspire insNNNN --out <rundir>/outputs/hepdata          # manifest carries figure_index
   python scripts/run.py ravel.plotting.figure_target resolve \
     --analysis <ID> --hepdata-manifest <rundir>/outputs/hepdata/hepdata_manifest.json \
     --role summary --model-keywords "<model words>"           # prints ranked candidates; CHOOSE
   # FETCH the published figure BEFORE declaring — declare's --caption must carry the PAPER
   # caption's first sentence, which fetch_figures extracts (figure_map.json); at minimum run
   # --map-captions to get the caption text even when no image can be pulled:
   python scripts/run.py ravel.plotting.fetch_figures \
     --inspire insNNNN --figure <N> --out <rundir>/outputs/published    # or: --map-captions
   python scripts/run.py ravel.plotting.figure_target declare \
     --rundir <rundir> --role summary --primary --figure-id "Figure <N>" \
     --source <user-prompt|registry-hint|hepdata-table-name|paper-inspection|description-only> \
     --caption "<first sentence of the published PAPER caption>" --inspire insNNNN [--arxiv XXXX.XXXXX] \
     --axes-x <linear|log> --axes-y <linear|log>   # the PUBLISHED axis scales, read off the extracted figure
   ```
   **Record the published axes at declaration** — the axis scales are facts read off the extracted
   figure, not defaults (`docs/workflow/checklists/plot-guidelines.md`); the step-5/8 renderers consume them via
   `--figure-target`.
   `resolve` never auto-picks — read the table descriptions and decide. If no paper caption could be
   extracted, fall back to the HEPData table description for `--caption` and note that provenance in
   `--source`. Then `figure_target.py attach-image` (the image fetch_figures extracted — or its
   precise textual reference, a valid degraded state) + `show` (prints the check-in block).
   Relative `--path` values resolve against `--rundir`; `--route` is inferred when omitted. A
   synthesis with no single published figure is declared `--source description-only` with a
   `--caption` and no `--figure-id`; it needs no paper id and is addressed with `--role`.
4. Place cards in the run's `inputs/`; record the routine ID and the model in `RESULT.md`.

**arXiv-only requests:** an arXiv id resolves to the Inspire id via the arXiv
page's INSPIRE link, `hepdata.net` search, or the Rivet routine name's `_I<NNNN>` suffix —
never stall on "no Inspire id given". The intake layer (`route_prompt.py` →
`inputs/task_contract.json`, validated by `validate_task_contract.py`) already extracted the
ids it could; CHECK-IN 1 presents that contract's flags.

**CHECK-IN 1 "PLAN"** — compose it per `docs/workflow/checklists/check-ins.md`, and send it **before ANY heavy
compute**: (i) the plain-language preamble; (ii) the published-figure GALLERY —
`fetch_figures.py --map-captions` extracts every figure + caption into `figure_map.json`; display
several distinct candidates, each with a one-line caption; (iii) the figure target(s) (echoed via
`figure_target.py show`) + the proposed EARLY-VERIFICATION WAYPOINT ([judgment]: a partial
published-figure element reproducible cheaply, to be shown side-by-side at CHECK-IN 2); (iv) the
plan (samples, observables, stats, budget); (v) the NUMBERED FLAGS — every assumption/decision with
its why + alternatives; (vi) the three-response-mode footer (answer the flags / ask clarifying
questions / propose alterations). Generation waits for the response.
Recording the approval also writes the code-derived research preregistration that
launch requires. `ravel research-preregister --rundir <rd>` reproduces it for an
approved plan.

**Next:** `docs/workflow/steps/03-generate.md`

Before presenting the plan, check requested tools against operation signatures, retain the
coordinator for an outcome-open question, and resolve `publication_title` witnesses to source
identifiers with receipts. Title words do not select a route. Carry counterfactual `assumption`
facts and selection-provided normalization into the numbered flags; do not supply missing
physics values. See [intake reading and gaps](../../reference/intake-and-challenges.md#holds-and-gaps).

## Role knowledge before dispatch

Load the effective role card and assemble its knowledge before starting a worker:

```python
from ravel.workflow import role_registry, knowledge_bundle

card = role_registry.load("generator")
order = knowledge_bundle.bind_work_order(
    {"node_id": "node-inputs", "operation": "model-events"},
    card,
    {"workspace": workspace},
)
```

The binding can also name `atlas_path`, `premises_path`, `role_bindings_path`,
`source_root` and `withheld_ids` for an explicitly frozen source selection.
It writes `inputs/knowledge/index.json` and authenticated item files inside the
worker workspace. The dispatcher includes the returned `bundle_sha256` in its
request digest and pins the index with the worker inputs. This API prepares the
bundle; the dispatch consumer must connect it to its own launch and receipt.

The card's `must_read` items come first. Reviewer obligations become `self_check`.
Producers receive at most three procedural sections, or a smaller positive
`max_procedural_items` from the card. Checks and premises do not count toward that
cap. Consults receive full handbooks and are exempt from the procedural cap.
The token budget uses a conservative UTF-8 byte charge for content. Required
items that cannot fit cause refusal; optional omissions retain their IDs and
reasons in `knowledge_omitted` and the bundle index.

Node facts select sections through `handbook_sections`, a map from handbook ID
to a list of section slugs. Role and operation defaults select a section when
the facts give none; otherwise the first section is used. Unselected sections
also appear in the omission census. `knowledge_bundle.serve_section(id, slug,
binding)` returns only that section and its nested content. Stale handbook or
premise pins require source reconciliation before assembly. Cold bundles have
no lessons or producer headlines.

Before accepting the final record, call
`knowledge_bundle.validate_cited_ids(record, order["knowledge_bundle"])` with
the same `atlas_path` when using a frozen atlas. The record must carry a
`knowledge_used` list; unknown or unserved IDs cause refusal.
`knowledge_bundle.omission_census(orders)` returns all omissions by node.
For the existing routine-construction roles, `knowledge_bundle.agentrivet_brief`
preserves the original `Briefs` projection and live observations as supplied
construction context, separate from the cold bundle. Knowledge selection grants
no execution approval or scientific acceptance.


## Supplied grids, generation recipes and fit campaigns

`ravel model-spectrum grid --request REQUEST --out OUT` consumes operation
`parameter-grid`. Its closed request fields are `schema_version`, `operation`,
`config`, `review_policy`, `supervisor_seconds`, `goal_binding`, and `grid`.
Config, policy and grid use exact `{path,sha256}` pins; `goal_binding` is
explicitly nullable. The grid schema1 document supplies `study_id`, `axes`,
`bindings`, `relations`, `dataset_population`, `source_evidence` and `delivery`.
Axes are named finite value vectors. Bindings map each parameter to an explicit
SLHA block and integer code tuple. Relations supply a constant literal or an
affine source, scale and offset; dependency order is explicit. Datasets are
`{id,source}` records whose pins are part of the source graph. `delivery` chooses
JSON or TSV and a safe filename. Every point is prepared, every nonselected card
byte is retained, and each child still needs ordinary approval and admission.
No population, model relation or output presentation is installed as a default.

For a hidden-sector generation/response recipe, use ordinary mode `svj-recipe`
with a supplied request. It requires arbitrary axes, explicit analysis metadata,
complete response and background populations, card-address and particle/fraction
bindings, and operative `generation_conventions`. Matching, merging scales,
beam content, particle identities and hidden-sector settings are selected by
inputs and must match actual cards. See [recipe schema](../../reference/svj-study-recipes.md).
Missing conventions are typed missing-input refusals; mismatched cards are hard
failures. Null physical assets stay visible as blocked cells.

Ordinary mode `joint-score`, task `{"input":"/absolute/campaign.json"}`, consumes
a schema1 input containing exact `design`, `law_prerequisite` and
`parent_qualification` pins. The prerequisite binds a current actual accepted
full-law-gradient review, all role decisions, exact input/result/compiled/receipt
artifacts, qualified runtime sources and joint identities for every supplied
case. The qualification contract and receipt retain registered initial/final
helper phases; custody alone never grants scientific admission.

The supplied design schema1 contains:

- `study_id`, `parameter_grid:[{name,values}]`, `dataset_population:[id,...]`,
  `measurement`, `background_source`, `source_relocations` and `delivery`.
- `cases` with source-law fields (`id`, `workspace`, `mc_model`, `signal_samples`,
  `source_bin_map`, `source_bound_semantics`, `expected_source_coordinates`),
  plus `parameter_point`, `dataset_id`, objective-keyed
  `expected_free_coordinates` and `original_named_seeds`. Each seed supplies
  `{id,points}` with complete `{mu,source,latent}` vectors for every objective.
- `objectives:[{id,fixed_mu}]`; null means free strength, a literal fixes it.
  `comparisons:[{id,left,right,scale,minimum,atol}]` requests scaled NLL
  differences and a declared numerical criterion.
- `solver:{path,sha256}`, `fit_protocol` with `mu_domain`, `budget_per_fit`,
  `solver_options`, explicit `rate_caps` and `endpoint_budget`, and explicit `resource_bounds`.
  Numerical source pins use absolute paths. Solver options and resource
  ceilings are required inputs, never silent settings.
- `qualification_scope:{fixed_vector_count,central_steps,budget_used}` binds
  actual prerequisite qualification completeness. `source_relocations` maps
  case IDs to explicitly declared metadata-only additions `{id,reference}`;
  deleted or changed operative sources remain refused.

The same accepted-law compiler serves all cases and objectives. Free dimensions,
seed denominators and output inventories derive from the supplied campaign.
Every raw return is retained before independent endpoint evaluation; returned
oracle values survive later comparison failures. Exact selected-endpoint
binding, complete input rechecks, helper admission and final custody gates remain
mandatory. JSON or TSV delivery never replaces the internal raw/checked records.
A passed campaign establishes only the declared stationary endpoint comparisons;
globality, coverage, physics accuracy and exclusion remain separate claims.
Required omissions raise `SpecificationError` with `reason="missing_input"` and
an explicit field. Native work uses the existing method-decision and launch
admission path after actual CHECK-IN 1; no preparation command launches it.

At rate, sample-exposure, yield, template and likelihood joins, retain supplied
quantity descriptors and run the ordinary request-plan check. Present every
`quantity_obligation` in the numbered CHECK-IN flags; resolve the missing fact
from a source or an explicitly recorded assumption. A `quantity_incompatible`
error requires compatible input or an explicit conversion operation. Inspect
ordered likelihood bins, auxiliary-information identities and matching regional
exposure revisions. Cross-input equality compares only stated shared facts;
a background-only workspace does not acquire a signal model-point requirement.
Known sign-preserving producers declare their weight convention. If a producer
has no declaration, retain the consumer's located weight obligation; a declared
signed-to-absolute relabeling is refused. See [quantity contracts](../../reference/knowledge.md#quantity-contracts-on-composition-edges).

For the generated-event selection and template chain, follow the explicit
[quantity handoff contract](../reference/scientific-studies.md#generated-event-quantity-handoffs). Its source
pins, fixed-normalization assumptions and consumer requirements must be present
before the corresponding operation can use that handoff.
