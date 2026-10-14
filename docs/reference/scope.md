# PRODUCT CONTRACT — what this pipeline does, refuses, and labels

> This contract defines the `task_contract.json` route. `route_prompt.py` drafts its
> classification (schema: `validate_task_contract.py --schema`); CHECK-IN 1 presents it.
> Separately admitted [scientific-study operations](../workflow/reference/scientific-studies.md)
> use their own contracts. Begin at [start](../workflow/start.md); unsupported operations remain
> explicit unmet requirements, never silent improvisations.
> [Limitations](limitations.md) and current execution evidence constrain result claims.

## Constructive routing before a refusal

The task-mode parser is a bounded legacy intake aid, not the inventory of all scientific
operations. A request that no rule recognises becomes an open research parent with its whole
obligation census; it is never refused for a missing rule. Consult the selected package's
actual `science.MODES` and dispatch contracts with `ravel.workflow.capability_routing`, and
provide grounded intent or an appropriate scientific specification. The recovery packet
preserves exact request bytes, source identities, candidate scope and discover → retrieve →
reuse/adapt → qualify actions. It confers no execution approval or parent-goal acceptance.
`ravel initiate` prints that packet for unsupported drafts and saves it for supported ones.

Preserve every requested experiment, analysis population, parameter domain, metric and
output. A local subset, point, proxy, diagnostic or alternative can be useful partial work;
it cannot silently replace the original task. Existing authorization covers routine
read-only discovery and reversible preparation. Compute still uses the applicable ordinary
plan/approval/review route. Reuse an existing approval only within its exact recorded scope.

Before declaring a scientific operation unavailable, distinguish a parser gap, missing
adapter, incompatible adapter, missing public inputs, an outage, and genuinely unavailable
private data. Discover publications/tool catalogues, retrieve official source and model
inputs, reuse compatible artifacts or build a declared custom routine/fit, then prepare the
smallest relevant qualification. Source presence is not scientific validation. Do not invent
unavailable physical inputs or carry a result beyond its applicability.

## 1. Task modes (`task_mode`)

`task_mode` is derived. `ravel initiate` reads the request into `inputs/reading.json` and
`ravel.workflow.derived_label.derive` takes the first rule that matches:

| rule | condition | `task_mode` |
|---|---|---|
| D1 | a boundary holds the whole request | `unsupported` |
| D2 | one scoped adapter serves every requested stage | `generate` or `likelihood` |
| D3 | one route-A lifecycle shape serves the request | its shape, as below |
| D4 | a calculation served by goal-bound scientific children | `calculation` |
| D5 | otherwise | `research`: a parent whose children are scientific studies, scoped runs or route-A runs, each with its own contract and CHECK-IN 1 |

Route hints from keywords are recorded in the reading; they propose and never admit. A
benchmark, challenge or task name is a locator only and never changes the label. The label
selects today's evaluator. Every requested stage, tool, deliverable, template, prescribed
statistic, constraint and stated parameter range is an obligation of the contract's census,
after the whole request verbatim.

| mode | the ask | deliverable | compute |
|---|---|---|---|
| `survey` | "what analyses say anything about X?" | analysis/figure candidates + plan (no generation) | none |
| `reproduce` | re-derive a published result (validation) | published-vs-ours side-by-side + relative difference | approved point or scan; incomplete requested coverage is partial |
| `reinterpret` | a model the analysis never considered | new exclusion statement on that model | approved point or scan; incomplete requested coverage is partial |
| `scan` | explicit grid / mass-plane request | 2-D µ₉₅=1 contour + coverage | scan |
| `projection` | expected reach at a future lumi / detector variant | expected-only contour/limit, labeled | scan |
| `summary_plot` | combine several analyses' PUBLISHED limits on one canvas | overlay of published limits (+ ours where run) | none-to-point |
| `anomaly_search` | model-agnostic / "strange topologies" | AD-style sensitivity study, expected-only | point-to-scan |
| `no_routine` | the legacy routine lookup has no applicable routine | inspect source-backed native construction/build, typed selection and explicitly scoped proxy alternatives | only the separately admitted route |
| `generate` | generation-only parton control | complete audited LHE, effective recipe, figure and check-in | one bounded approved attempt |
| `likelihood` | supplied workspace or counting approximation | verified observed/expected CLs roots, units, recipe and figure | one bounded approved attempt |
| `unsupported` | a boundary holds the whole request: no scientific object, an ungrounded context identifier, or an unsupportable claim, inaccessible input or contradiction covering every part | recovery packet and the boundary rows, each with what would make it possible; original requirement remains open | none |

The approved scientific question determines the deliverable. A requested grid or contour uses
[step 8](../workflow/steps/08-scan.md); a single point is partial when that larger domain is
requested. A supported point request can end at a verified point result. A single-point QUERY
against an already-completed identical scan is a **read, not a run** (step 8's reuse rule).

## 2. Detector modes (`detector_mode`)

| mode | what models the detector | when | fidelity ceiling |
|---|---|---|---|
| `rivet-smearing` | the Rivet routine's own smearing/efficiency functions | analysis ships a Rivet routine | fast-sim floor (§5) |
| `simpleanalysis-delphes-native` | Delphes → native SimpleAnalysis | exact registered capability or independently admitted source/build route | parity is established per routine; no automatic fidelity transfer to another routine |
| `container` | Delphes → SA in a bound compatible container | inspect exact source, event format, runtime/assets and analysis applicability | fidelity and cost require the selected route; emulated containers are slow |
| `particle-level` | none (truth-level objects, no detector) | `no_routine` / `anomaly_search` / quick sensitivity | proxy only — labeled, never a claimed exclusion of record |
| `parton-level` | none; no shower/hadronization | `generate` | scoped LO generation, no acceptance claim |
| `none` | no detector operation requested | `likelihood` | supplied statistical model only |
| `effmap-folded` | published per-object / per-SR efficiency maps folded over truth objects (no detector sim of our own) | LLP/displaced (trap T2) via D2, or no-routine SUSY via D1 | map's documented accuracy (e.g. ~25%); R5-gated per analysis; unmapped response is unknown; zero filling is not a conservative yield or exclusion guarantee |
| `delphes-custom-uncertified` | Delphes fast-sim (stock ATLAS/CMS card) feeding a CUSTOM selection with no certified routine (the Option-C detector variant) | no Rivet/SA routine exists but a Delphes card is warranted (e.g. τ_h+MET recasts) | uncertified fast-sim: labeled proxy, **never an exclusion of record** until per-SR acc×eff certification vs published anchors (T10) closes — the route gate WARNs and CHECK-IN 1 must surface it |

## 3. Statistical modes (`stat_mode` — canonical enum = `result_pack.py` STAT_MODES)

| mode | model | when |
|---|---|---|
| `published-likelihood` | the analysis's serialized pyhf workspace + signal patch | it exists on HEPData (preferred, strongest) |
| `simplified-likelihood` | published simplified/covariance model | provided by the analysis |
| `best-sr-counting` | single-bin counting per SR, quote best expected-CLs SR | no serialized likelihood |
| `combined-counting` | simultaneous multi-bin counting fit | SRs mutually exclusive |
| `stability-only` | no limit — pipeline stability/validation statement only | validation runs |
| `shape-fit` | scoped binned-template fit (`shape_fit.py`): paper's background shape × flexible poly + signal template → CLs; **R5-gated per analysis** | the result is a binned shape/bump fit AND the engine can represent it AND its R5 closes |
| `blocked-shape-fit` | the selected legacy engine cannot represent or validate this fit; requested result remains unmet | inspect compatible native/custom alternatives (§6.1) |
| `sensitivity-expected-only` | expected-only sensitivity (S/√B, expected CLs) — no observed-data claim | projections, AD studies, tagger what-ifs |
| `none-survey` | no per-run statistics — quotes OTHER analyses' published limits | `survey` / `summary_plot` |
| `prescribed-statistic` | the statistic the request prescribes (explicit formula, N-sigma region, Δχ², another confidence level), delivered as the primary result with its definition; certified like a limit | the request names its statistic; `stat_mode_note` quotes it |
| `none-generation` | no exclusion inference | `generate` |
| `provided-likelihood` | supplied pyhf model or explicit counting approximation | `likelihood`; see [scoped contract](../workflow/reference/scoped-workflows.md) |

An exclusion request that does not prescribe a statistic gets **95% CLs** limits by default;
CLs is not itself a Gaussian significance. When a request prescribes a statistic (an explicit
formula, an Nσ region, a Δχ² threshold or a Bayesian credible interval), that statistic is the
requested quantity and the primary result, with CLs optionally alongside. Fits, measurements,
calculations and summaries report their own contracted quantities. An observed discovery
claim or excess p-value needs authorized data and an appropriate independently validated
analysis, not a relabelled exclusion. A prospective
significance/discovery-reach question is a different study intent. Preserve that metric,
prepare its statistical model/calibration route, and withhold an unsupported number; do not
rewrite it as expected CLs or observed exclusion.

## 4. The archetype census (the figure-selection basis)

Detector-level BSM search routines are mostly counting/cutflow analyses that fall into **4
archetypes** (A 0ℓ jets+MET · B multilepton/EWino · C 1ℓ+jets · D monojet/MET-binned), which share
ONE overlay primitive + ONE cert primitive (`figure_manifest.py`). Every routine outside the recipe
table, and every ESCAPE hit, is a per-paper `[judgment]` figure choice via `figure_target.py resolve`. The MASS-PLANE overlay
(`mass_plane_overlay.py`) is the summary form no routine emits natively.

## 5. Fidelity labels (every result carries exactly one)

| label | meaning | evidence artifact |
|---|---|---|
| `bit-for-bit` | native chain reproduces the reference container per-SR yields exactly | 141/141 SR parity; µ₉₅ to 0.51% (`docs/workflow/reference/native-pipeline.md`) |
| `certified` | tiered acc×eff / cutflow certification PASS vs published | `validate_cutflow.py` / `certify_acceptance.py` output |
| `fast-sim-floor` | standard chain, uncertified region: intrinsic ~10–20% acc×eff floor | `docs/reference/limitations.md` (mapyde tunes ~15%) |
| `particle-level-proxy` | truth-level stand-in, no detector model | declared in `result.json` limitations[] |
| `degraded-anchor` | reference digitized from the published figure (no HEPData table) | provenance notes the digitization |
| `effmap-folded` | published efficiency map folded over truth kinematics; no detector model of our own | map version + validity envelope + map systematic recorded in the basis manifest; R5 closure at ≥2 published points |

A result's prose NEVER upgrades its label ("roughly matches" ≠ `certified`).

## 6. Refusal cases (name the line, offer the nearest supported thing)

1. **Shape/template-fit statistics**: inspect the actual workspace, channels, modifiers,
   response, control contamination, interference and available native runtime before choosing
   an engine. `shape_fit.py` is a restricted binned 1-D family; its failure to represent an
   unbinned, simultaneous or per-event-discriminant model is an adapter boundary. Current
   scientific operations include source-bound native/published/HS3 models, joint models and
   restricted custom continuous or SR/CR models, each with its own contract. Inspect them or
   construct an explicit compatible successor; no file-presence argument proves suitability.
   The legacy `shape-fit` delivery still requires its per-analysis R5 closure. A failed R5
   withholds that requested result and triggers diagnosis/adaptation; a generator-level or
   sensitivity diagnostic is labelled partial and cannot replace the requested fit/limit.
   A closure for one shape analysis does not certify another.
2. **Discovery claims versus prospective sensitivity**: withhold an unsupported observed
   discovery/5σ/excess claim. Preserve the user's question and explain its exact evidence
   boundary. Explicit prospective significance or discovery-reach studies can proceed to a
   zero-compute design and source-backed statistical qualification; they are not exclusion
   questions and have no implied result or calibrated engine.
3. **Invented physics inputs**: missing efficiencies, likelihoods, k-factors and covariances
   are sought in official public resources and preserved caches, or requested from their
   owner. Outages and missing identifiers are not absence. Genuinely unavailable private
   inputs keep the dependent quantitative requirement unmet; never guess them. Conditional
   alternatives state their assumptions and remain separate from the original result.
4. **Off-grid model points**: the published map/reference domain constrains reuse and
   comparison. Unsupported extrapolation of acceptance/efficiency or reference limits is
   forbidden. It does not make a new parameter point uninformative or forbid a qualified
   extension. Keep the requested coordinates; retrieve or generate/validate the missing
   model, response and likelihood inputs under an admitted plan. Published on-grid checks
   and new off-grid predictions are distinct evidence.
5. **Generation without an approved plan**: any smoke, full, or scan generation before CHECK-IN 1
   approval (`approval_required` is ALWAYS true in the task contract; the compute ladder is
   dry → smoke → full → scan, `cost_preflight.py`).
6. **Operation boundaries**: these legacy detector-recasting contracts do not grant arbitrary
   data access, collider simulation or detector design. Inspect current supplied-model,
   measurement, domain and provider contracts before declaring a whole subject unsupported.
   An absent adapter can be a development/qualification task; unavailable private data and
   an unrepresented scientific model remain explicit barriers to the dependent result.
6b. **Sensitivity integrity (A7/A8)**: a `sensitivity-expected-only` number ships only
   within the legacy limit-delivery route when (a) the sensitivity artifact records a **pyhf** `method` — an A×ε-scale borrow of a
   published absolute limit is NOT an expected limit (`check_statistics` hard-FAILs it
   post-epoch) — and (b) a non-FAIL acc×eff certification exists
   (`sensitivity-expected-only ∈ CERT_REQUIRED_STAT_MODES`; `inv_certify_before_limit`).
6c. **Approval is an artifact**: the CHECK-IN 1 go-ahead is recorded as
   `inputs/checkin1_approval.json` via `workflow_state.py approve` (which requires a VALID
   `checkin1.json` + a recorded `cost_preflight.json` budget). The supervised launch (`ravel run`,
   `stage_supervisor`, `launch_authorization`) checks it just before it starts a smoke, full or
   scan process, and delivery refuses generation output that has no approved launch record
   (`inv_approval_before_compute`). The PreToolUse Bash hook refuses literal generator and
   supervisor commands without it; it reads command text only, so delivery is the backstop.
7. **Projection readiness**: counting-mode limits (`task_mode=projection`,
   `stat_mode=sensitivity-expected-only`) are EXPECTED-ONLY and BRACKETED (stat/syst/frozen). A
   physicist-facing projection number ships only after the R5-analog published-projection
   round-trip closes — the stat–syst–frozen band must CONTAIN a published HL-LHC/Run-3 expected
   limit for a representative analysis at the published f. Until closure, projection is
   specified but not delivered; the offer is the labeled expected-only bracket as a sensitivity study,
   never an exclusion of record. The f=1 identity + scenario-ordering are self-consistency
   selftests, NOT the R5 gate.
8. **Replane readiness**: replane (`task_mode=reinterpret` via a composition/plane fold) ships a
   number only after a round-trip reproduces a paper's OWN published contour on the σ×BR leg
   within tolerance. Composition-dependent A×ε is NOT re-simulated by the fold (declared caveat)
   and must be bounded or escalated (trap T3). Synthetic round-trip/monotonicity selftests are
   self-consistency, NOT the R5 gate.
9. **First-skill precedence (N1)**: a physics session must invoke `physicist-intake` before any
   downstream skill. Loading `new-analysis` or a `run-*` skill before a validated
   `task_contract.json` exists is refused — the PreToolUse-on-`Skill` gate exits 2 (gate G22).
   The nearest supported thing: run `physicist-intake` first (it routes + gates + composes CHECK-IN 1).
10. **Detached long jobs (N6)**: a long compute detached from the harness (`nohup`/`start_new_session`)
   is refused turn-end unless it carries a durable `run_state.json` entry
   (`bg_kind=detached` + `logfile` + `done_condition` + `next_action`) AND a harness-visible heartbeat.
   DRIVE mandates harness-tracked backgrounding (`run_in_background`) so completion re-invokes the
   agent; a bare `nohup` silently defeats that lever and blinds the physicist (gate G27).

## 7. Result semantics (what a delivered number MEANS)

- Every number traces to a machine artifact (`result.json` / `scan.json` / `exclusion.json` —
  the number-integrity rule, `docs/workflow/checklists/verification-panel.md`).
- Coverage is stated: `n_done`/`n_planned`, partial grids labeled partial (never extrapolated).
- Comparisons are like-for-like: same σ basis (`model_basis` after rebase), observed-vs-observed
  or expected-vs-expected (LIKE-COLUMNS), reference never interpolated.
- A floored/capped µ₉₅ is a **bound, not a limit** (`quality` tag; rendered '×').
- A point or scan launched on the supervised path writes **under the run directory**: an
  `OUTDIR` that resolves under `/tmp`, `/private/tmp`, or the session scratchpad is rejected at
  launch and FAILs `validate_run_state.py`'s outputs-in-tree invariant (N2/G23). A standalone
  command writes where its `--out` points; keep that under the run directory, because
  `verify_pack.py`, `directory-keeper` and `.gitignore` see only the run directory.
- The workflow's delivery step runs the step-9 verification panel, and its verdict ships verbatim
  with the result (never silently fixed). A command run outside the workflow does not run the
  panel.
- Compute: with a local backend, points and partitions run one at a time under the machine
  lease; a `site` backend uses up to `max_concurrent` remote slots. A coarse 2-D grid takes hours
  locally, and a publication-dense plane needs a site backend. The container fallback runs
  sequentially and takes hours per point.
- A `summary_plot` deliverable is ACCEPTED only when `summary_audit.py --check` passes (rules R-SA1..8:
  survey↔basis_manifest bijection; disposition completeness; no keyword-only exclusions — a
  dropped curve needs a physics/out-of-range/superseded reason class; legend label↔channel
  derivable from the candidate's survey `final_state`; superseded curves rendered as cross-check,
  not co-equal; per-curve provenance+lumi+obs/exp labelled; drawn coverage annotations consistent
  with every candidate's stated reach; transformation stated). Until the gate is green the run is
  a declared PARTIAL, never 'served'.

## 8. Where this contract binds

`route_prompt.py` (deterministic classification) → `validate_task_contract.py` (schema gate) →
CHECK-IN 1 (the physicist sees the classification + cost + flags) → the skills
(`physicist-intake`, `route-analysis`, `cost-preflight`) carry the stop conditions. Any change
to a mode/label/refusal lands HERE first, then in the enum sources it mirrors
(`result_pack.py` STAT_MODES, `task_contract.json` schema), and the change is recorded in
`CHANGELOG.md`.

**Authority of record:** each admitted operation is bounded by its current adapter contract
and executed evidence; catalogue membership or a development proposal does not establish
scientific support.

**The full binding chain** (run leg, extending the classification chain above):
`route_prompt.py` → `validate_task_contract.py` (schema) → CHECK-IN 1 → [run] →
`validate_run_state.py --check` (lifecycle: ordering + completeness + mode-invariants incl. R5 closure and
likelihood↔selection pairing; stage matrix DERIVED from §1/§2/§3, legacy runs grandfathered) →
`verify_pack.py` (artifact integrity) → step-9 panel.

## 9. Verification of the enforcement spine (this cycle's scope)

The workflow-adherence gates (the hooks, Stop-dispatch branches, `validate_run_state.py` invariants,
and skill/tool gates that make an agent FOLLOW the workflow) is itself a product surface, so its scope
and its bar are stated here like any other:

| scope item | verification mechanism | the bar (and its non-goal) |
|---|---|---|
| Verification of the enforcement gates | the per-gate adversarial harness (`tests/adversarial/run_suite.py`, one case per G0a-G27) + make green | the bar is "harness green", NOT a physicist-vetted full-physics run |

## Supplied-data scientific operations

The [scientific-study contract](../workflow/reference/scientific-studies.md) adds
source-backed supplied-event, quantity/measurement, model/provider, native statistical,
construction/build, response and comparison operations alongside the task routes above.
The actual selected `science.MODES`/dispatch source is the current inventory; this prose
list and historical task-mode enums are not an exhaustive capability registry. These admit existing event/object records and explicitly supplied
models; they do not relax generation, detector or reproduction gates. In particular,
UFO inspection is not model generation, lifetime geometry is not a displaced-track
efficiency, and a supplied Gaussian measurement likelihood is not an experimental
full likelihood. Requested paths and methods outside those adapters remain unmet
product requests.
