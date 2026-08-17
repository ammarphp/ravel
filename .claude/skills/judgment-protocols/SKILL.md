---
name: judgment-protocols
description: Run the matching judgment PROTOCOL at any [judgment] site or physics decision under limited information in hep-agentic-pipeline — the eight operating procedures (look-first, basis-manifest, trap-sweep, anchor-chain, discrepancy-decomposition, source-ladder, conservative-default, kill-the-result) that turn physics knowledge into correct decisions. Fire BEFORE taking the judgment step, not after it goes wrong.
when_to_use: any [judgment]-tagged step; comparing anything to a published number/figure; routing a new analysis/model pair; a produced number about to be used downstream; two numbers disagree; required info is missing; an assumption must be made; a result is drafted for delivery
allowed-tools: Bash, Read
---
# Skill — judgment protocols (the HOW behind every [judgment] tag)

The full protocols with thought→reality tables and worked incidents:
**`workflow/checklists/judgment-protocols.md`** — read the matching one and RUN it. The domain
trap catalogue behind P3: **`workflow/checklists/physics-traps.md`** (T1–T12, each with its cheap
check + route consequence).

## Which protocol fires (route by situation, not by step number)

| Situation | Protocol |
|---|---|
| About to render/compare/describe a published artifact | **P1 look-first** — extract it, LOOK at it, record its grammar first |
| About to compare any two numbers/curves (one published) | **P2 basis-manifest** — write both sides' conventions; refuse until matched |
| Routing a new analysis/model pair (step 2/3) | **P3 trap-sweep** — walk physics-traps.md T1–T12; hits become numbered flags; then `validate_parameters.py emit` auto-opens the D10 obligations (below) |
| A produced number is about to be used downstream | **P4 anchor-chain** — independent order-of-magnitude anchor first |
| Two numbers that should agree, don't | **P5 discrepancy-decomposition** — enumerate causes, test cheapest-first, decompose |
| Required information is missing | **P6 source-ladder** — paper → HEPData(+resources) → collab code → recast DBs → theses/citations → ask-with-options |
| An assumption must be made to proceed | **P7 conservative-default** — the claim-WEAKENING choice, reversible, flagged with sign+size |
| A result is drafted for delivery | **P8 kill-the-result** — three written attacks (basis/acceptance/statistics) before the panel |

## Red flags (you are rationalizing — stop and run the protocol)

| Thought | Reality |
|---|---|
| "The caption / my memory of this figure type is enough" | A1: two supervisor rejections came from exactly this. Extract and look (P1). |
| "Both numbers are 'the limit', just compare" | A4: a ×0.56→×1.01 basis tilt masqueraded as physics for weeks (P2). |
| "This analysis is like the last one, same route" | T1/T2/T3 hits change the route entirely; sweep, don't pattern-match (P3). |
| "It ran clean / the fit converged, so the number is right" | B1, B2: exit-0 wrong numbers are the house specialty. Anchor it (P4). |
| "It's probably statistics" | The cheapest discriminating test first — the 33% residual was NOT statistics (P5). |
| "The paper doesn't provide it, so it's unavailable" | The HEPData "impossible download" fell to a second look; theses carry cutflows (P6). |
| "Lower-order/simpler is automatically conservative" | k<1 cases OVER-excluded; conservative means you checked the SIGN (P7). |
| "It matches, ship it" | The RJR-circular 141/141 "match" was the disguise (P8). |

## P3 → the D10 parameter-validation contract (trap hits become obligations you must discharge)
A trap sweep that flags **T3/T6/T7/T8** is not "recorded" until its physics is actually validated.
`trial-runs/_infrastructure/validate_parameters.py emit --rundir <run> --param <varied>` reads
`inputs/trap_sweep.json` (`traps_hit[]`) and writes `inputs/validations.json` (schema_version 1,
`generated_by`+`input_fingerprint`): a PENDING obligation for each varied physics parameter AND an
auto-emitted `trap_obligation` for each **GATED_TRAPS=(T3,T6,T7,T8)** hit (each carries the concrete
check it demands — per-point spectrum re-weight for T3, ISR/merging audit for T6, HV-parameter sourcing
+ truth-level validation for T7, per-width generation for T8). Discharge each with
`record --param <name> --status PASS --evidence "<what you checked>"` — a **PASS is EARNED** (recording
PASS with no `--evidence` is refused). Before a scan's varied physics reaches long compute,
`check --rundir <run> --require-nonempty` GATEs (exit 1 while any obligation is not PASS, or the set is
empty; exit 0 only when all PASS). Only T3/T6/T7/T8 auto-open — other trap hits stay numbered flags.

**The trap-sweep artifact carries its own obligation ledger too.** `inputs/trap_sweep.json` has an
`obligations: [{trap, obligation_kind, artifact, status ∈ PENDING|PASS|FAIL}]` field, and
`validate_run_state.py`'s `inv_trap_obligations` invariant (`trap-obligations-discharged`) hard-FAILs
the run once generation/result_pack is reached if any **non-T3/T9** trap hit lacks an `obligations[]`
entry with `status==PASS` (write a PASS entry per obligation-bearing hit before generation ships, e.g.
per-width-regen for T8). T3/T9 are excluded — they are already driven by the basis-manifest gate
(`inv_basis_manifest_before_comparison`). Unlike the scan-only D10 `validations.json` ledger above,
this gate applies in ALL task modes at generation.

## Under the model-tier policy (binding)
These protocols do NOT replace escalation — they make it sharp. A cheap model at a [judgment]
site runs the protocol MECHANICALLY (extract / manifest / sweep / anchor / decompose / climb),
then presents the structured evidence as the numbered CHECK-IN flag; escalate-to-physicist stays
the default verdict wherever the site names nothing else (`workflow/WORKFLOW.md` §Roles).

## Stop conditions
- A protocol's mechanical step is impossible (artifact unfetchable, no anchor exists) → that IS
  the finding; flag it, do not improvise around it.
- Two protocols disagree (the conservative default would violate the basis manifest) → escalate
  with both writeups; never pick silently.
