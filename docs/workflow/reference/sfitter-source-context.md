# Complete SFitter source context

SFitter conductor packets retain the complete original source catalogue while
presenting a bounded scientific core and explicitly selected source pages. The
generic AgentGraph input cap stays 128. A catalogue establishes custody; it
does not establish that a model read every source or approved its physics.

Use the existing conductor preparation or phase continuation to obtain an
authenticated `context_pin`. Prepare a fresh packet with
`sfitter_conductor.prepare_lead_packet(context_pin, base, output)` and pass its
`{path, manifest_sha256}` binding to `lead_graph(..., packet_pin=packet)`.
The graph keeps raw `input0` as the original context. Stable `input1` through
`inputN` resolve all original catalogue paths, including IDs above 128.

The fixed proposal schema permits `request_context`, with explicit
`context_pages=[{input_id, offset, max_bytes}]`, current findings and no handoff,
documentation, production or approval. Declare finite `max_context_reworks`
when creating the lead graph. `followup_context(graph_root, context_pin, base,
fresh_output)` prepares those pages and revises the same graph, retaining its
original call/token ceilings and deadline. Execute it through the ordinary
Graph and Host again; no call is dispatched by packet preparation or revision.
Select all necessary pages again in the final stateless call.

A draft handoff that references a whole source requires complete byte coverage
in the actual final Host presentation receipt. Whole-source credit requires complete source bytes in that receipt. A production request can select catalogue IDs as future consuming-study
inputs, but the application binding records that the selection itself does not
establish whole-content presentation or scientific approval. The ordinary
scientific plan, approval, execution and independent review still apply.

Packets are limited to 4096 source inputs, 32 selected pages, 65536 bytes per
page and 64 MiB total packet bytes. The scientific core and serialized page
wrappers must also fit the declared Host inline allowance. Preparation refuses
an oversized required population; it never truncates it. Every packet reader
checks current originals and copies through the existing indexed-context
lifecycle, including producer-valid empty SOURCE files. The core retains
original handoffs, targets, actual review provenance, findings and holds.
The designer packet is not an independently blinded critic/verifier context.

For specialists, prepare with `purpose='specialist'`, pass `source_packet` to
`consultant_graph`, and consume their actual advisory returns with ordinary
`prepare(..., consultations=graph_root)`. For deterministic assembly, use
`purpose='assembly'` and `sfitter_workflow.assembly_graph(...,
source_packet=packet)`. Only the `sfitter-assemble` Host action resolves this
verified packet into its complete source allowlist. Explicit Host root bounds
still apply; other tool allowlists are unchanged.

The module CLI is `python -m ravel.workflow.sfitter_conductor`. Actions include
`prepare`, `packet`, `lead-graph`, `followup-context` and `adopt`. A packet-backed
lead requires both `--packet` and `--manifest-sha256`. `packet --selections`
reads the closed page-selection JSON array; `--packet-purpose` chooses lead,
specialist or assembly. Supply `--max-context-reworks` prospectively.

Campaign continuation additionally uses the composed research-cycle charged
revision API: `followup_context(..., campaign=cycle_root)` retains the original
reservation and authenticated predecessor/spec chain without recharge or reset.
Standalone follow-up uses that same checked entry with `cycle_root=None`.
The common entry authenticates the current nonvoting request and requested
pages, and fences the expected predecessor under the Graph revision lock.
Application production also validates the exact shared reservation chain before
its existing parent, charge, observed-usage and study checks.
That dependency and a connected campaign-bound test must be admitted together;
a standalone page-loop pass is not evidence of the campaign join. There is no
new scheduler, model tool loop, native SFitter parser or scientific validation
in source-packet preparation.


## Complete numerical source interface

The ordinary `sfitter-native-fit` schema2 interface now binds full native top22 or
Higgs20 coordinates, an explicit ordered subset embedded at zero in that full
basis, source-defined flow/SMC/CRAFT settings and authenticated `run`/`fit`/`plot`
phases. `sfitter_complete_native` and `sfitter_complete_worker` are the actual
adapter/child; `sfitter_profiles`, `sfitter_results`, `sfitter_compat` and
`sfitter_native_handoff` retain card, tensor, copied compatibility and ordinary
production commitments. They preserve existing approval and review authority.

The source physical score remains `-Q` and native profiles remain `exp(-Q)`.
Top uses normalized multibin signed correlated RFit; Higgs uses absolute
branching/production and current independent pull-square/EWPO semantics. SMC/CRAFT
histograms are unweighted particle diagnostics because their source discards
residual weights. A zero native physical log-prior is not an admitted proper
Bayesian prior. Posterior, convergence, interval and coverage qualification remain
unknown, including after native plots exist.

Source repairs and holds come from explicitly selected, byte-bound reviewed records.
`sfitter_card_derivation` requires a repair manifest and defect registry; there is no
built-in card roster, repair table or row-count exception in the engine. The records for
the three released full cards (`Top_Full.json`, `Higgs_Full.json`,
`Higgs_Full_with_CtG.json`) ship as data in `src/ravel/data/sfitter/published-records` and
are bound to a selected source root by `ravel.physics.sfitter_published_records` (`bind`,
`derive`, or the `--source-root/--card/--output` command), which refuses card bytes that
differ from the record's pin. The shipped Higgs records keep the released row 197/5019
response held as an unresolved defect; the shipped Top records hold the unresolved intents of
the shadowed `D6qt1xD6qt1` term and the unused measurement nuisance as assumptions. Every copy,
replacement, retained field and parser projection keeps its original values in
lineage. Coalescence requires identical observation and prediction rows. Missing
records and unresolved physical defects refuse before derived-card publication.

A physical profile selects `source_review: {path, sha256}` in its supplied run
card. The matching defect registry binds evaluator sources, input coverage,
assumptions and any retained unused nuisance placements. An active defect can be
resolved only by a matching reviewed resolution with byte-bound evidence. Row
identity spelling and numeric-equivalent JSON spelling must not clear a hold.
The result and saved capsule preserve `native_law_assumptions`,
`scientific_input_support` and `scientific_input_holds`. Old capsules without
these records require source requalification. Review records establish input
custody and declared disposition; scientific qualification remains separate.

Actual SM/scan producers can be bound by materialization's `--producers` roster;
the native consumer checks current successful ordinary execution, output membership
and reuse review, rather than caller-created success flags. No source adapter or
portable role replaces those scientific/execution obligations.

The complete schema2 runtime declares at most64,000 exact file assets, with a
64MiB serialized config/request transport ceiling and complete original-member
ending checks. No runtime files are truncated to fit it. The existing legacy
schema1 limit remains20,000. The64k bound is an explicit custody allocation; the
separate SFitter environment requires its own census and root runtime admission before a native job.


## Complete numerical source interface

The ordinary `sfitter-native-fit` schema2 interface now binds full native top22 or
Higgs20 coordinates, an explicit ordered subset embedded at zero in that full
basis, source-defined flow/SMC/CRAFT settings and authenticated `run`/`fit`/`plot`
phases. `sfitter_complete_native` and `sfitter_complete_worker` are the actual
adapter/child; `sfitter_profiles`, `sfitter_results`, `sfitter_compat` and
`sfitter_native_handoff` retain card, tensor, copied compatibility and ordinary
production commitments. They preserve existing approval and review authority.

The source physical score remains `-Q` and native profiles remain `exp(-Q)`.
Top uses normalized multibin signed correlated RFit; Higgs uses absolute
branching/production and current independent pull-square/EWPO semantics. SMC/CRAFT
histograms are unweighted particle diagnostics because their source discards
residual weights. A zero native physical log-prior is not an admitted proper
Bayesian prior. Posterior, convergence, interval and coverage qualification remain
unknown, including after native plots exist.

Source repairs and holds come from explicitly selected, byte-bound reviewed records.
`sfitter_card_derivation` requires a supplied repair manifest and defect registry;
there is no built-in card roster, repair table or row-count exception. Every copy,
replacement, retained field and parser projection keeps its original values in
lineage. Coalescence requires identical observation and prediction rows. Missing
records and unresolved physical defects refuse before derived-card publication.

A physical profile selects `source_review: {path, sha256}` in its supplied run
card. The matching defect registry binds evaluator sources, input coverage,
assumptions and any retained unused nuisance placements. An active defect can be
resolved only by a matching reviewed resolution with byte-bound evidence. Row
identity spelling and numeric-equivalent JSON spelling must not clear a hold.
The result and saved capsule preserve `native_law_assumptions`,
`scientific_input_support` and `scientific_input_holds`. Old capsules without
these records require source requalification. Review records establish input
custody and declared disposition; scientific qualification remains separate.

Actual SM/scan producers can be bound by materialization's `--producers` roster;
the native consumer checks current successful ordinary execution, output membership
and reuse review, rather than caller-created success flags. No source adapter or
portable role replaces those scientific/execution obligations.

The complete schema2 runtime declares at most64,000 exact file assets, with a
64MiB serialized config/request transport ceiling and complete original-member
ending checks. No runtime files are truncated to fit it. The existing legacy
schema1 limit remains20,000. The64k bound is an explicit custody allocation; the
separate SFitter environment requires its own census and root runtime admission before a native job.
