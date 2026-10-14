---
name: verification-panel
description: Run the mandatory pre-delivery panel: Tier-A mechanical number tracing and Tier-B evidence-bound critic, optional repair proposer, skeptical verifier and synthesizer cycle. Preserve all findings and accept only the declared scientific claim scope.
when_to_use: a run has results drafted for delivery (final check-in / RESULT.md / scan deck) and has not yet passed the step-9 panel; or a FAIL verdict needs re-running after fixes
allowed-tools: Bash, Read, Agent
---
# Skill — the verification panel (step 9; both tiers; verdict ships verbatim)

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

The panel catches OUR mistakes before the physicist sees them (`docs/workflow/steps/09-verify.md` +
`docs/workflow/checklists/verification-panel.md` govern).

```
NO DELIVERY WITHOUT A FRESH PANEL VERDICT — A SKIPPED PANEL IS AN UNVERIFIED RESULT
```

## Tier A — mechanical integrity (cheap model is fine)
```bash
CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda
$CONDA run -n rivet python scripts/run.py ravel.validation.verify_pack <rundir>   # exit 1 = FAIL
```
Then the un-scriptable half BY HAND — every claim in the draft against its evidence, line by line:

| Claim | Requires | Not sufficient |
|---|---|---|
| any number (yield/σ/µ₉₅) | traces to `result.json`/`scan.json`/`exclusion.json` or shows its derivation, WITH units (fb vs pb is the classic) | sourceless or disagreeing = automatic FAIL |
| "matches / consistent with the publication" | its ladder rung row — WHICH published number, WHICH artifact, WHAT tolerance (`docs/workflow/checklists/verification-ladder.md`; catalogue A6) | prose agreement with no artifact behind it |
| coverage ("N of M points") | `n_done`/`n_planned`/`missing_tags` agree | reading it off the figure |
| a displayed figure | exists on disk + is captioned | referenced by name |
| "point excluded" | `quality` clean — floored/capped points are bounds | a saturated diff-map cell (B1) |
| mid-run change was fine | its `DEVIATIONS.md` entry (an unlogged change = FAIL-severity) | mentioned in chat |

## Tier B — critic, controlled repair, skeptical verifier, synthesizer

Follow [the scientific review reference](../../../docs/workflow/reference/physics-review.md)
for schemas, authority and evidence boundaries. Tier B remains a strong-model
physics-judgment step under `docs/workflow/README.md`. Use fresh contexts and source
profiles `physics-reviewer` (critic), `physics-improver`, `physics-verifier` and
`physics-synthesizer`. Reviewer actor IDs differ from each other and from the
proposer/executor. Strings declare separation; they do not authenticate it.

Before CHECK-IN 1, specialize `inputs/physics_review_policy.json` from
`src/ravel/data/templates/physics_review_policy.json` and bind it into the actual
approval. Declare maximum redos, mutable setting paths, allowed stages, required
checks and claim scopes/actions. Never retrofit or widen a registered policy. If
an existing approval omitted the policy, surface that concrete scope gap under
the reference's prospective-declaration requirements; do not manufacture approval
or replay an old GO.

The caller owns CLI writes. Strict JSON request files contain the named API's
keyword arguments. Open only with actual successful retained `stage_receipts`,
executed `effective_settings`, located `check_results` and a valid waypoint manifest:

```bash
ravel review --rundir RUN open --request OPEN_REQUEST.json
ravel review-context create --rundir RUN --role critic --out NEW_CRITIC_PACKET
ravel review-context read --packet NEW_CRITIC_PACKET --artifact a0000 --manifest-sha256 CREATION_DIGEST
ravel review --rundir RUN review --request CRITIC_REQUEST.json
```

Retain `CREATION_DIGEST` outside the packet from its creation result. Use manifest
artifact IDs; `a0000` is illustrative and may be an omission. The reader requires
that digest and exposes only hash-bound indexed copies. Supply verified content
to each fresh role without the parent transcript or unrestricted filesystem,
shell or browser access. Read-only profiles are guidance, not an OS sandbox.
Known verdict fields are projected, but arbitrary artifacts may carry narrative;
inspect projections and record blinding limitations. Large omitted files require
a bounded source-pinned witness, not a claim that they were inspected.

The critic receives source definitions, actual settings, measurements, precision
and inherited factual closure obligations. Withhold the producer headline and
preferred outcome; ask the critic to test evidence and justification. Do not
instruct it to refute a supplied headline. Use `docs/reference/failure-modes.md`
as methodology: axes/binning, like-for-like columns, process/order/charge/flavour
basis, units, exposure/channels, floored points, actual options, decays, native
routing, selection/detector validity and true 95% CLs crossing. Missing witnesses
become evidence requests, not invented defects.

If no repair is needed, create fresh verifier and synthesizer packets and submit
their judgments; no artificial improvement pass. Initial acceptance requires
`physics_critic`, `skeptical_verifier` and `physics_decider` to accept the same
named scope. Each review request contains `role`, `actor_id`, `verdict` (`accept`,
`send_back`, `stop`), `summary`, `findings`, `closes`, and `claim_scope`. Blocking
findings need stable `id`, concrete `summary`, located `evidence` (`path`,
`location`), `check_ids`, `required_paths` and `required_stages` within policy.
Use packet source identities for evidence paths.

When repair is required, the improvement agent proposes the minimum change,
held-fixed inputs, discriminating prediction, precision/covariance contract,
data-use history and stopping rule. It has no acceptance vote. Prepare copies;
the decider admits actual bytes and exact stage specifications:

```bash
ravel review-context create --rundir RUN --role improver --out NEW_IMPROVER_PACKET
ravel review --rundir RUN correct --request CORRECTION_REQUEST.json
```

The correction request names `actor_id`, `changed_paths`, `stages`,
`recheck_checks`, and `stage_specs` when needed. Admission consumes a redo even
on failure and cannot widen CHECK-IN 1. Execute only admitted stages through the
supervisor, then open a successor with `correction_id`, fresh successful receipts
and rechecked outputs. All material findings remain inherited. Preserve original
waypoint evidence; an old successful attempt cannot stand in for a new recheck.

Create a fresh `verifier` packet with factual findings, before/admitted setting
identities, exact admission and new successor evidence, withholding the improver's
favorable conclusion and other verdicts. Before the successor,
`fresh_attempts_available` is false: admission is not execution evidence. The
verifier tests each obligation, pairing/covariance, precision and held-fixed
controls. A repaired symptom does not certify the whole analysis. New objections
remain visible.

The `synthesizer` packet includes original findings, repair evidence, all verdicts
and unknown assumptions. The decider recommends a named scope, bounded correction,
stop or specific evidence request. It cannot vote away a send-back/stop, erase an
inherited finding or allow the improver to accept its own output. Record successor
judgments with `ravel review --rundir RUN review --request FILE`; all inherited
findings must be explicitly closed. Check state and allowed delivery action:

```bash
ravel review --rundir RUN status
ravel review --rundir RUN gate --action delivery
```

For consequential or unsupported claims, use adaptive public assertion DAGs:
`ravel decision-case --case CASE.json --out NEW_REPORT.json`. Each supporting hop
has a separate reviewer judgment and ends in a pinned observation, source,
invariant or explicit requirement, or yields a specific evidence/experiment
request. No mandatory seven-depth prose or private reasoning trace. Evaluate
supplied contrasts with `ravel diagnose --plan PLAN.json --out NEW_REPORT.json`.
Neither command proves arbitrary entailment, authorizes compute or turns target
matching into physics validation. Missing covariance is unresolved; calibration
populations cannot become independent validation.

## Verdict + delivery (never silently fixed)
The results deck carries this panel's verdict VERBATIM in its §7 `panel_verdict`: emit it as
`inputs/checkin_deck.json` and run `ravel checkin validate
inputs/checkin_deck.json` before delivery — it asserts the eight deck sections are present incl. that
verbatim panel verdict, and a missing one is a FAIL.

PASS → deliver only within the recorded accepted scope and allowed delivery action,
with the verdict + `verify_pack.py` report appended. CONCERNS → deliver WITH
findings appended and each answered (accepted-as-limitation or fixed+noted); unanswered
findings block. FAIL → do not deliver; fix, log in `DEVIATIONS.md`, RE-RUN BOTH TIERS. The
findings text is appended to the final check-in VERBATIM and un-pre-judged — no spin,
softening, or recommendation inserted ahead of the raw finding; even after fixes, the
physicist sees what the panel found.

A contradicted scientific hypothesis can support an honest diagnostic result
when integrity and that scope's checks pass. Integrity failure or an unresolved
blocking finding cannot be renamed diagnostic success. Mechanical PASS and
reviewer agreement do not establish physics fidelity or authenticated independence.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The run was careful; the panel is ceremony" | Ungrounded "consistent with the publication" claims are the most common error a reader finds in a delivered result. |
| "I'll fix the finding and drop it from the report" | Findings ship VERBATIM even after fixes; a silent fix hides the failure class from the physicist. |
| "I know this run best — I'll be the adversary" | The author's context is what produced the miss; catalogue A5 was caught only by outside eyes, twice. |

## Stop conditions
- `verify_pack.py` exit 1 → fix the artifact/prose mismatch before Tier B (mechanics first).
- Tier B reviewing roles share the producing context, lack the retained packet
  digest, or see withheld verdicts → record the access failure and repeat the
  affected fresh role. Distinct actor IDs alone are insufficient.
- Missing witness, unsupported material link, or unresolved inherited finding →
  specific evidence/experiment request; no automatic acceptance.
- A FAIL verdict is un-negotiable: no partial delivery, no "noting it in passing".
