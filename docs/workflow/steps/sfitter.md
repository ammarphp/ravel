# Native SFitter and portable specialists

The active `sfitter-native-fit` route uses the ordinary science lifecycle. It calls the exact SFitterAgents numerical package at commit `6072a79e0f132d61a927f11ed482a401b34f6e3f`, in a copied full source tree, through the existing `execute_native` supervisor. It also adapts the upstream specialist workflow to the existing RAVEL AgentHost/AgentGraph. The numerical engine and specialist knowledge are complementary parts of the implementation. This is a portable adaptation, not the complete upstream SFitterAgents application: its original Claude/Apptainer conductor application, persistent wiki/memory and SLURM production are not invoked by the active route. The source-bound portable phase conductor described below uses the existing RAVEL Graph and review seams.

Implemented source interfaces:

- `ravel.physics.sfitter_native.validate/inputs/run`: closed configuration, complete original235-file custody, schema1 exact shipped top/profile/double/flow settings; schema2 source-supported top/Higgs, coordinate subsets, flow/SMC/CRAFT and authenticated saved phases, explicit admitted interpreter/runtime, original plus copied input checks, one native call, progressive/opaque output preservation, bounded delivery and ending census.
- `ravel.physics.sfitter_worker.main`: ordinary native child, exact native `ProfileLikelihood.log_likelihood` for fixed vectors, or original `init_run → train → save → fit → plots` sequence. No native model/fitter imports occur in the planning process. Native `results.pkl` is retained before serialization and never unpickled by the parent. Both branches persist `initialized-state.json` after initialization and source checks, before training or evaluating fixed vectors. The snapshot observes the actual polynomial, measurement, error, pre-shrink correlation, inverse metric and normalization tensors, plus lossless float64 `corr_shrinkage`/`syst_rho` and integer `n_blocks_substituted`. It performs no additional score or matrix computation, survives later failures and carries independent consistency as unknown.
- `ravel.physics.sfitter_results`: full22-parameter/231-pair transport, original numeric dtype/shape/C-order bytes, base64 plus hash, geometry/completeness validation. NaN, infinities, signed zeros and underflow bits are preserved, not clipped or assigned scientific validity. The unchanged FitResults does not retain raw profile log scores, argmax coordinates or convergence metadata; these are explicitly unavailable/unknown.
- `ravel.workflow.sfitter_workflow.context/phase_graph/apply_handoff/ready_native`: extraction, SM/order/theory, full signed Wilson templates, convention translation and exact datacard composition. Source phases use pinned upstream role/skill texts with explicit domain and authority overrides. No separate scheduler, mutable research journal or runner is introduced.
- AgentHost tool actions `sfitter-context` and `sfitter-handoff`: every inspected role/code/paper/phase artifact must be an exact current Graph input. Host identity includes the adaptation, child, serializer and upstream census. Graph dependency order does not implicitly supply a model result; actual handoff files are explicitly pinned before the next phase.

The five phases expose all15 upstream SFitter specialist roles and selected SystemB EFT, coupling-order, UFO and scale/PDF specialists. The two upstream reviewer prompts are advisory designers during datacard drafting, not independent reviews. A fresh critic/verifier Graph uses actual existing `review_context` or `failed_stage_review` packets; ordinary review journal votes and decisions remain separate. Explicitly pinned memory can be source context; a cached wiki/verdict is never scientific evidence by itself. No model calls have been made for this implementation.

A handoff includes the exact scientific population digest, actual evidence pins and a closed phase payload. Extraction preserves native observation/error slots and optional published correlation blocks. SM rows bind perturbative order and theory-source magnitudes. Wilson rows require the complete declared linear, square and mixed terms, plus actual scan, coupling-sanity and fit-diagnostic artifacts. These signed absolute coefficients are never replaced by NDA magnitudes, incoherent class sums or a Taylor-normalized ratio. The final card must equal the full handoff composition, including measurement uncertainties and theory sources, byte-bound convention manifest and run card.

The adapter preserves native top `score=-Q`, profiles/importance target `exp(-Q)`, signed component-wise RFit clamp before correlated contraction, named nuisance-key correlations, original published-block replacement and capped shrinkage. Every multi-bin native group normalizes its full polynomial by its width-weighted integral; both native and specialist intakes require normalized multi-bin groups and absolute singletons. The native singleton denominator is one; a normalized singleton interpretation is refused. Schema1 keeps the complete native22 basis. Schema2 builds the full22 top or20 Higgs likelihood, then embeds the explicitly selected ordered coordinates into that full vector with every omitted coefficient fixed at zero before both native score and prior calls. It never passes a shortened basis to the native polynomial, Higgs branching or EWPO tensors. Basis/units/flavour/cutoff are declared and source-bound; only equal positive source/target scale is supported here. An externally converted card needs actual conversion evidence and review. This source interface neither computes RGE nor certifies a general SMEFT basis transformation.

Released cards remain unchanged. Ambiguous paired identities, unknown operator
tokens or unsupported nuisance placements refuse admission until the request
selects a matching reviewed source repair and disposition record.

## Ordinary invocation

Create a version2 scientific specification with mode `sfitter-native-fit`, task `{"config": "/absolute/config.json"}`, one attempt and zero redos. The only claim scope is `sfitter-native-delivery`, whose only action is `delivery`; there is no reuse scope. Use the existing public commands:

```
ravel plan --rundir /absolute/new-study --spec /absolute/science.json
ravel approve --rundir /absolute/new-study ...
ravel run --rundir /absolute/new-study ...
ravel status --rundir /absolute/new-study --write
```

Consult the current CLI arguments for approval/run. Planning is implemented; approval and dispatch are root-owned for this machine. A complete native delivery is not convergence/globality, a confidence interval, coverage calibration or EFT applicability. Native plots remain raw upstream outputs with unqualified interval interpretations.

For portable specialist preparation, use the APIs or:

```
python -m ravel.workflow.sfitter_workflow context --request workflow.json --output context.json
python -m ravel.workflow.sfitter_workflow graph --request workflow.json --output graph.json
python -m ravel.workflow.sfitter_workflow handoff --request workflow.json --handoff actual-phase.json --output handoff-receipt.json
```

These commands prepare advisory artifacts only. Execute the resulting DAG with the existing AgentGraph/Host after its model budgets are authorized. After actual successful native return, use ordinary `physics_review.open_cycle` plus fresh `review_context.create` packets and the existing votes/decider. After an actual failed stage, classify the genuine record and use canonical `failed_stage_review.intake/create_context/graph_feedback`; the failure stays failed. `sfitter_workflow.review_graph` accepts these matching current role packets; it cannot construct review evidence or cast votes.

## Datacard construction

The active assembler provides `assemble_datacard`, `assembly_graph` and `materialize_datacard`, plus the real Host tool `sfitter-assemble`. It lifts every supplied extraction, SM/theory and signed Wilson row into the native JSON. The exact shipped run-card body is retained with only run name and datacard path substituted. All supplied correlations, bin widths, units, operator squares and declared mixed terms remain. Same-scale coordinate transport uses the existing exact EFT transport result and its recorded binary64 projection; no coefficient, measurement or uncertainty is invented.

```
python -m ravel.workflow.sfitter_workflow assemble --request workflow.json --output draft.json
python -m ravel.workflow.sfitter_workflow assembly-graph --request workflow.json --output graph.json
python -m ravel.workflow.sfitter_workflow materialize --request workflow.json --output /absolute/fresh-bundle --native-settings runtime-settings.json
```

`materialize` writes the run-relative example outputs `<rundir>/data/assembled.json` and `<rundir>/params/assembled.yaml` in the fresh bundle directory supplied by `--output` (`<rundir>` here), an exact retained semantic copy, the datacard handoff, completed workflow and a preparation receipt. With explicit trusted runtime settings it also writes an actual `sfitter-native-fit` configuration and enumerates the complete existing native input graph. Its semantic handoff retains the original source pin so relative evidence resolves at its original location. The native `ReadDataCard` round trip remains unexecuted. Source-bound draft handoffs are not reviewer approval. Use the generated configuration for a fresh ordinary science plan; the command grants no execution or scientific acceptance.

All new card/request/semantic/template bytes are captured, parsed and copied from the same bounded ordinary-file observation. Ending bytes and ancestor identities are checked. The existing Host/Graph, science approval, native supervision and review journals retain authority; there is no additional scheduler. The assembler has source and synthetic engineering controls; a full-study native demonstration remains outstanding.

## Complete upstream application boundary

The original noninteractive entry is `SFA_SESSION_DIR=<session> PYTHONPATH=<original>/src python -m launcher code <Claude arguments>`. It runs the unchanged conductor and phase skills inside Apptainer, maintains session-local lead/consultant memory and wikis, and supplies cluster execution through SLURM. That application backend is not yet implemented or admitted by RAVEL. A future wrapper should use the original entry and a dedicated writable `CLAUDE_CONFIG_DIR`, explicit image/cluster/runtime/call budgets and ordinary output intake, preserving the original application rather than reproducing its scheduler. It must never borrow global Claude or Codex configuration.

The portable phase conductor connects actual specialist returns to an original-skill phase lead. It produces source-bound handoff files, phase documentation, explicit production requests and owning-phase draft revisions. It delegates source-bound domain review preparation, consumption and rework to the repaired SFitter domain protocol. The phase continuation requires all original registered review roles, the exact current request and the whole owning phase; narrow acceptance grants no whole-phase approval. Review transport and scientific production still require their ordinary separate admission. These operations use the existing Graph/Host and judgment journal; the conductor creates no additional scheduler, mutable approval state or native runner.

The original application remains the preferred backend when complete upstream session memory/wiki and cluster behavior are required. Use its unchanged noninteractive launcher behind an explicit ordinary runtime contract and dedicated configuration rather than reproducing those facilities. The portable path still needs actual source-grounded SM/NLO and signed Wilson-scan production, coefficient/baseline evidence, native parser round trips and downstream fit review. Production requests are explicit missing-work handoffs, not executed MadGraph cards or completed measurements. Merely exposing all roles or accepting source drafts does not complete those obligations. The native exact polynomial and width-weighted normalization override any conflicting upstream Taylor prose.

## Portable phase conductor

`ravel.workflow.sfitter_conductor` reuses the original `sf-reinterpret`, phase, documentation and fidelity skills at the pinned upstream commit. `consultant_graph` retains the current whole-role population and explicit cumulative call/rework ceilings. `prepare` optionally reads the actual completed current consultant Graph; it refuses stale, incomplete or different-target returns. `lead_graph` emits one structured ordinary designer node. Its closed output distinguishes a source draft, production request, owning-phase send-back and unresolved work. The supplied skill text is context, never permission to execute the original launcher, containers or cluster commands.

```
python -m ravel.workflow.sfitter_conductor prepare --input workflow.json --consultations /absolute/current-consultant-graph --output /absolute/fresh-lead-context
python -m ravel.workflow.sfitter_conductor lead-graph --input /absolute/fresh-lead-context/context.json --output /absolute/fresh-lead-graph.json --model EXPLICIT_AUTHORIZED_MODEL --max-output-tokens 4096 --max-wall-seconds 600
python -m ravel.workflow.sfitter_conductor adopt --input /absolute/fresh-lead-context/context.json --graph /absolute/executed-lead-graph --output /absolute/fresh-draft
```

The existing Graph/Host dispatches the resulting model node only under its current caller-owned model and cost authority. `adopt` reads the true current returned value, validates the whole handoff and only accepts evidence actually presented in that node's inputs. It writes the handoff, documentation bucket, proposal and workflow draft with final byte/path checks. All source drafts retain `review_approved=false`, `physics_validated=false` and `execution_authorized=false`. An advisory send-back preserves the original files and Graph usage and rewinds only the owning phase's handoff suffix in a fresh draft. It does not grant retry authority or reset an existing budget.

For actual review, `prepare_role`, `consume_review` and `rework_review` require the separately supplied domain protocol. Its exact request must name this adopted workflow and phase; its binding must retain that same request. The ordinary protocol/judgment consumer owns acceptance and actual send-back, including current concern coverage and review actors. If that required module is absent, the conductor refuses. The source controls exercise these delegate calls with an explicit stand-in until a coherent real protocol join is tested. Draft progression does not imply reviewer-approved phase completion.

No complete original application, native parser or full-study demonstration is claimed by this interface. It is a connected portable construction path with explicit production and review dependencies.

## Runtime and resource boundary

The core is separable from the Claude/Apptainer/SLURM launcher; CPU mode is explicit. This adapter does not invoke the upstream launcher, install tools or submit cluster jobs. `-I -B`, explicit site roots, exact interpreter bytes, package versions, declared source/runtime assets and observed nonstdlib import origins are required. Imports and Python startup can execute trusted code before an origin check; this is not an OS sandbox or a complete shared-library/stdlib closure. CPU mode explicitly hides CUDA before importing Torch; unexpected upstream automatic device selection is refused. Native randomness is unchanged, with no new seed/reproducibility claim.

The configured native time/RAM/export ceiling is enforced through existing supervision and delivery validation. Raw logs, process/exit receipts, progress, copied sources/cards, model, opaque result and plots are retained on failure. Serializer failure or missing final runtime custody makes the stage fail without erasing raw data. There is no automatic retry or approval. All real fits and numerical qualification remain unexecuted.

## Qualification before a full comparison

The prepared bounded qualification uses the full22 basis and three fixed vectors on an explicitly synthetic one-bin transport card. This tests native API/score/export only and earns no measurement/campaign credit. An admitted actual Torch/PyTables runtime is still required. No matching runtime is fabricated from the software-test fake assets. The held intent/template documents exact resource ceilings and blocked runtime requirements.

A full native comparison requires a separately reviewed full card shared by both arms, complete template/SM/order/uncertainty/EFT evidence, exact native runtime/device, and a root-admitted resource budget for the shipped numerical workload (10 million sampling draws plus training/profile work). Native convergence evidence, score/interval conventions, multi-start/globality checks and coverage are separate obligations. Charge both arms extraction/template/convention/card/review overhead and permit upstream to win. Neither the synthetic controls nor the small qualification are full-study benchmark tasks.

## Attribution

SFitterAgents upstream numerical/role/skill sources are MIT licensed, copyright2026 Heidelberg HEPML and MadGraphTeam. The exact original license is shipped at `src/ravel/data/sfitter/LICENSE.upstream.txt` and retained in every copied native tree. External SMEFT/MadGraph/model/data/runtime packages retain their own licenses and citations. The RAVEL adaptation supplies finite scientific handoffs and ordinary custody/review integration; it does not claim authorship of the upstream numerical method or specialist knowledge. Scientific contract reference: independently reviewed `c3645f20`, stored beside the original source comparison.


## Complete native profiles and saved phases

The schema2 config is consumed by the existing `sfitter-native-fit` ordinary
adapter. Set `profile` to `top` or `higgs`, `parameters` to the explicit ordered
nonempty native subset, `algorithm` to `flow`, `smc` or `craft`, and `phase` to
`run`, `fit` or `plot`. The existing source/runtime/card/purpose/budget fields
remain mandatory. `inference` is exactly
`native_profile_and_marginal_measure_unqualified`; this preserves source outputs
without asserting a qualified posterior, p-value or interval. `saved_run` is null
for `run`, otherwise the exact `state-capsule.json` pin from a current successful
ordinary native delivery. A new ordinary approval is still needed for every
phase. `fit` loads the authenticated model and refits; `plot` loads authenticated
model/results and does neither training nor fitting. Full native run membership,
original cards, adapter/compatibility bytes, runtime, semantic inputs and producer
handoff remain bound. Caller-created files or a passed result bit are insufficient.

Diagnostic `toy`, `spiral` and `five_point` profiles retain their full source
coordinates and are engineering controls with `purpose=analytic_qualification`;
they cannot stand in for a physical measurement. Their likelihood and prior
semantics are preserved separately from the physical `score=-Q` convention.

All source-defined numerical sections are retained rather than silently replaced
with the shipped top settings. Numerical allocations must be finite and bounded.
Higgs predictions use native branching/production tensors and EWPO. Higgs channels
are absolute; their current source contracts sum pull squares rather than applying
the top correlated metric. The full initialized tensors and current native Poisson
law are exported, including lossless Boolean masks. Source-aware statistical review
and independent accuracy/calibration remain required.

The original SMC/CRAFT `FitResults` constructor omits four mandatory flow-weight
histogram fields. The adapter applies one attributed MIT source delta **only in
the copied source**: these fields are `None` and the unavailable weight plot is
skipped. Original SMC/CRAFT marginalization discards residual log weights when
building histograms. Those outputs are explicitly unweighted particle diagnostics,
not Bayesian posterior densities. Physical native `log_prior` is zero with no
proper-prior or finite-support claim. Flow importance-weighted histograms also
remain statistically unqualified. Native profile-mass contour plots are not
Wilks or CLs contours; no thresholds or factors are silently translated.

Raw shipped cards remain unchanged and refused when their identities are
ambiguous. A separately declared source-derived card can be prepared with:

```
python -m ravel.physics.sfitter_card_derivation --source-root /absolute/exact-upstream --card selected-card.json --repair-manifest /absolute/reviewed-repairs.json --repair-manifest-sha256 <sha256> --output /absolute/fresh-derived-card
```

The supplied manifest binds the selected card, predecessor inputs, review
evidence and defect registry to exact source bytes. Its transformations specify
JSON field paths and expected values. Copies retain their source paths;
projections retain the complete original modifier list; paired coalescence
requires identical values and retains all original row indices. A supplied
identity template distinguishes repeated identities without merging independent
measurements. The context selects the card output filename and JSON format.
A missing repair manifest or defect registry is a typed missing-input refusal.

Supply `source_review: {path, sha256}` in the physical profile's run card. A
matching reviewed coverage record is required for its exact physical input.
Defects remain held under renaming; a reviewed resolution requires supplied
source evidence. Retained unused nuisance placements must state their exact
path, value, disposition and bound evaluator evidence. Neither successful
software execution nor a reviewed transformation certifies a physical law.

Supply `card_derivation` as the generated `derivation.json` pin and include it
in the semantic manifest's `sources`. The ordinary supervised adapter replays
its pinned `repair_manifest` and requires exact card/lineage correspondence.
The schema is `src/ravel/data/source_records/records.schema.json`; no reviewed
scientific record ships in the package.

For actual prediction-production continuity, `materialize --native-settings ...
--producers ...` accepts a pinned closed roster
`{"schema_version":1,"producers":[{"rundir":"...","artifacts":[{"path":"...","sha256":"..."}]}]}`.
Every SM and signed scan evidence member must belong to a current successful,
reusable ordinary producer with its actual output census and scientific review.
The generated config binds `production_handoff` to that exact whole scientific
workflow/card target. Units, perturbative orders, EFT conversion, denominator and
independent-MC/error assumptions remain supplied scientific premises; a successful
producer receipt does not infer them.

The complete schema2 runtime declares at most64,000 exact file assets, with a
64MiB serialized config/request transport ceiling and complete original-member
ending checks. No runtime files are truncated to fit it. The existing legacy
schema1 limit remains20,000. The64k bound is an explicit custody allocation; the
separate SFitter environment requires its own census and root runtime admission before a native job.


## Complete native profiles and saved phases

The schema2 config is consumed by the existing `sfitter-native-fit` ordinary
adapter. Set `profile` to `top` or `higgs`, `parameters` to the explicit ordered
nonempty native subset, `algorithm` to `flow`, `smc` or `craft`, and `phase` to
`run`, `fit` or `plot`. The existing source/runtime/card/purpose/budget fields
remain mandatory. `inference` is exactly
`native_profile_and_marginal_measure_unqualified`; this preserves source outputs
without asserting a qualified posterior, p-value or interval. `saved_run` is null
for `run`, otherwise the exact `state-capsule.json` pin from a current successful
ordinary native delivery. A new ordinary approval is still needed for every
phase. `fit` loads the authenticated model and refits; `plot` loads authenticated
model/results and does neither training nor fitting. Full native run membership,
original cards, adapter/compatibility bytes, runtime, semantic inputs and producer
handoff remain bound. Caller-created files or a passed result bit are insufficient.

Diagnostic `toy`, `spiral` and `five_point` profiles retain their full source
coordinates and are engineering controls with `purpose=analytic_qualification`;
they cannot stand in for a physical measurement. Their likelihood and prior
semantics are preserved separately from the physical `score=-Q` convention.

All source-defined numerical sections are retained rather than silently replaced
with the shipped top settings. Numerical allocations must be finite and bounded.
Higgs predictions use native branching/production tensors and EWPO. Higgs channels
are absolute; their current source contracts sum pull squares rather than applying
the top correlated metric. The full initialized tensors and current native Poisson
law are exported, including lossless Boolean masks. Source-aware statistical review
and independent accuracy/calibration remain required.

The original SMC/CRAFT `FitResults` constructor omits four mandatory flow-weight
histogram fields. The adapter applies one attributed MIT source delta **only in
the copied source**: these fields are `None` and the unavailable weight plot is
skipped. Original SMC/CRAFT marginalization discards residual log weights when
building histograms. Those outputs are explicitly unweighted particle diagnostics,
not Bayesian posterior densities. Physical native `log_prior` is zero with no
proper-prior or finite-support claim. Flow importance-weighted histograms also
remain statistically unqualified. Native profile-mass contour plots are not
Wilks or CLs contours; no thresholds or factors are silently translated.

Raw shipped cards remain unchanged and refused when their identities are
ambiguous. A separately declared source-derived card can be prepared with:

```
python -m ravel.physics.sfitter_card_derivation --source-root /absolute/exact-upstream --card selected-card.json --repair-manifest /absolute/reviewed-repairs.json --repair-manifest-sha256 <sha256> --output /absolute/fresh-derived-card
```

The supplied manifest binds the selected card, predecessor inputs, review
evidence and defect registry to exact source bytes. Its transformations specify
JSON field paths and expected values. Copies retain their source paths;
projections retain the complete original modifier list; paired coalescence
requires identical values and retains all original row indices. A supplied
identity template distinguishes repeated identities without merging independent
measurements. The context selects the card output filename and JSON format.
A missing repair manifest or defect registry is a typed missing-input refusal.

Supply `source_review: {path, sha256}` in the physical profile's run card. A
matching reviewed coverage record is required for its exact physical input.
Defects remain held under renaming; a reviewed resolution requires supplied
source evidence. Retained unused nuisance placements must state their exact
path, value, disposition and bound evaluator evidence. Neither successful
software execution nor a reviewed transformation certifies a physical law.

Supply `card_derivation` as the generated `derivation.json` pin and include it
in the semantic manifest's `sources`. The ordinary supervised adapter replays
its pinned `repair_manifest` and requires exact card/lineage correspondence.
The schema is `src/ravel/data/source_records/records.schema.json`; no reviewed
scientific record ships in the package.

For actual prediction-production continuity, `materialize --native-settings ...
--producers ...` accepts a pinned closed roster
`{"schema_version":1,"producers":[{"rundir":"...","artifacts":[{"path":"...","sha256":"..."}]}]}`.
Every SM and signed scan evidence member must belong to a current successful,
reusable ordinary producer with its actual output census and scientific review.
The generated config binds `production_handoff` to that exact whole scientific
workflow/card target. Units, perturbative orders, EFT conversion, denominator and
independent-MC/error assumptions remain supplied scientific premises; a successful
producer receipt does not infer them.

The complete schema2 runtime declares at most64,000 exact file assets, with a
64MiB serialized config/request transport ceiling and complete original-member
ending checks. No runtime files are truncated to fit it. The existing legacy
schema1 limit remains20,000. The64k bound is an explicit custody allocation; the
separate SFitter environment requires its own census and root runtime admission before a native job.
