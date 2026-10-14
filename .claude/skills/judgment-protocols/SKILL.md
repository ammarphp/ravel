---
name: judgment-protocols
description: Run the matching judgment PROTOCOL at any [judgment] site or physics decision under limited information — the eight operating procedures (look-first, basis-manifest, trap-sweep, anchor-chain, discrepancy-decomposition, source-ladder, conservative-default, kill-the-result) that turn physics knowledge into correct decisions. Fire BEFORE taking the judgment step, not after it goes wrong.
metadata:
  when_to_use: any [judgment]-tagged step; comparing anything to a published number/figure; routing a new analysis/model pair; a produced number about to be used downstream; two numbers disagree; required info is missing; an assumption must be made; a result is drafted for delivery
allowed-tools: Bash, Read
---
# Skill — judgment protocols (the HOW behind every [judgment] tag)

The full protocols with thought→reality tables and their failure mechanisms:
**`docs/workflow/checklists/judgment-protocols.md`** — read the matching one and RUN it. The domain
trap catalogue behind P3: **`docs/workflow/checklists/physics-traps.md`** (T1–T12, each with its cheap
check + route consequence).

## Which protocol fires (route by situation, not by step number)

| Situation | Protocol |
|---|---|
| About to render/compare/describe a published artifact | **P1 look-first** — extract it, LOOK at it, record its grammar first |
| About to compare any two numbers/curves (one published) | **P2 basis-manifest** — write both sides' conventions; refuse until matched |
| Routing a new analysis/model pair (step 2/3) | **P3 trap-sweep** — walk physics-traps.md T1–T12; hits become numbered flags; then `validate_parameters.py emit` auto-opens the D10 obligations (below) |
| Reinterpreting a measured spectrum with a signed or interfering signal | **P3 trap-sweep** plus the interpretation notes in `docs/reference/inference-engines.md` (the `differential-likelihood` record lists them) |
| A produced number is about to be used downstream | **P4 anchor-chain** — independent order-of-magnitude anchor first |
| Two numbers that should agree, don't | **P5 discrepancy-decomposition** — enumerate causes, test cheapest-first, decompose |
| Required information is missing | **P6 source-ladder** — paper → HEPData(+resources) → collab code → recast DBs → theses/citations → ask-with-options |
| An assumption must be made to proceed | **P7 conservative-default** — the claim-WEAKENING choice, reversible, flagged with sign+size |
| A result is drafted for delivery | **P8 kill-the-result** — three written attacks (basis/acceptance/statistics) before the panel |

## Red flags (you are rationalizing — stop and run the protocol)

| Thought | Reality |
|---|---|
| "The caption / my memory of this figure type is enough" | A recalled or captioned form is not the published form. Extract and look (P1). |
| "Both numbers are 'the limit', just compare" | Two quantities on different bases (charge sum, state count, order) differ by a factor that looks like physics. Write the basis manifest first (P2). |
| "This analysis is like the last one, same route" | T1/T2/T3 hits change the route entirely; sweep, don't pattern-match (P3). |
| "It ran clean / the fit converged, so the number is right" | A clean exit or a converged fit does not establish a correct number. Anchor it to an independent value (P4). |
| "It's probably statistics" | A residual's cause is unknown until a test discriminates it. Run the cheapest discriminating test first (P5). |
| "The paper doesn't provide it, so it's unavailable" | Inputs often live in record resources, auxiliary material, theses or code repositories. Walk the source ladder before declaring anything unavailable (P6). |
| "Lower-order/simpler is automatically conservative" | A correction below one makes the simpler number exclude more, not less; conservative means you checked the SIGN (P7). |
| "It matches, ship it" | A comparison against an input derived from the same source is circular and matches by construction. Try to kill the result (P8). |

## P3 → the D10 parameter-validation contract (trap hits become obligations you must discharge)
A trap sweep that flags **T3/T6/T7/T8** is not "recorded" until its physics is actually validated.
`src/ravel/validation/validate_parameters.py emit --rundir <run> --param <varied>` reads
`inputs/trap_sweep.json` (`traps_hit[]`) and writes `inputs/validations.json` (schema_version 1,
`generated_by`+`input_fingerprint`): a PENDING obligation for each varied physics parameter AND an
auto-emitted `trap_obligation` for each **GATED_TRAPS=(T3,T6,T7,T8)** hit (each carries the concrete
check it demands — per-point spectrum re-weight for T3, ISR/merging audit for T6, HV-parameter sourcing
+ truth-level validation for T7, width-dependent shape and acceptance validation for T8).
For T8, use new generation or applicable, independently reviewed coherent amplitude reuse or
full matrix-element reweighting. Validate support, effective statistics, interference, tails
and acceptance at each requested width; normalization-only narrow-template rescaling does
not discharge the obligation. Discharge each with
`record --param <name> --status PASS --evidence "<what you checked>"` — a **PASS is EARNED** (recording
PASS with no `--evidence` is refused). Before a scan's varied physics reaches long compute,
`check --rundir <run> --require-nonempty` GATEs (exit 1 while any obligation is not PASS, or the set is
empty; exit 0 only when all PASS). Only T3/T6/T7/T8 auto-open — other trap hits stay numbered flags.

**The trap-sweep artifact carries its own obligation ledger too.** `inputs/trap_sweep.json` has an
`obligations: [{trap, obligation_kind, artifact, status ∈ PENDING|PASS|FAIL}]` field, and
`validate_run_state.py`'s `inv_trap_obligations` invariant (`trap-obligations-discharged`) hard-FAILs
the run once generation/result_pack is reached if any **non-T3/T9** trap hit lacks an `obligations[]`
entry with `status==PASS` (write a PASS entry per obligation-bearing hit before generation ships, e.g.
width-shape-and-acceptance for T8). T3/T9 are excluded — they are already driven by the basis-manifest gate
(`inv_basis_manifest_before_comparison`). Unlike the scan-only D10 `validations.json` ledger above,
this gate applies in ALL task modes at generation.

## Under the model-tier policy (binding)
These protocols do NOT replace escalation — they make it sharp. A cheap model at a [judgment]
site runs the protocol MECHANICALLY (extract / manifest / sweep / anchor / decompose / climb),
then presents the structured evidence as the numbered CHECK-IN flag. In manual mode, unresolved
judgments go to the physicist. Under the explicit delegation recorded through
`docs/workflow/start.md`, the authorized scientific reviewers and coordinator decide within
the recorded scope and budgets. Keep independent CI2 and CI3 review; identify machine
decisions as such. This skill never grants delegation or substitutes a mechanical PASS for
scientific review. Unavailable required expertise or an action outside delegation is escalated.

## Stop conditions
- A required artifact or independent anchor is missing → hold the dependent claim, document
  the gap and pursue source recovery or a bounded discriminating experiment. Novel hypotheses
  may be tested without an established expected answer; do not invent inputs or certify the
  resulting number by repeating the same derivation. Continue independent work within scope.
- Two protocols disagree (the conservative default would violate the basis manifest) → escalate
  with both writeups; never pick silently.
