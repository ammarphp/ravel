---
name: verification-panel
description: Run the MANDATORY step-9 pre-delivery verification panel in hep-agentic-pipeline — Tier-A mechanical number-tracing (verify_pack.py + artifact-vs-prose line check) and the Tier-B fresh-context physics adversary armed with the FAILURE-CATALOGUE attack list. No result, deck, or RESULT.md reaches the physicist without this panel's verdict attached.
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
| "point excluded" | `quality` clean — floored/capped points (CR-001) are bounds | a saturated diff-map cell (B1) |
| mid-run change was fine | its `DEVIATIONS.md` entry (an unlogged change = FAIL-severity) | mentioned in chat |

## Tier B — physics adversary (STRONG model, FRESH context — never the run's own author)
Spawn a fresh-context reviewer (the `physics-reviewer` subagent where available) with the
ARTIFACTS + FIGURES ONLY (no run narrative), instructed to REFUTE the headline. Its attack
list starts at `docs/reference/failure-modes.md` (walk A1→D3 against this run: figure actually
extracted? axes from the figure? like columns? same σ basis? floored flat-band points?
run.options honored? empty-Events/undecayed signatures? 1-D collapse? untagged container
routing?) then free-form: basis choices, statistical treatment (true CLs crossing, 95% CL
never discovery), proxy validity domains, unflagged material assumptions.

## Verdict + delivery (never silently fixed)
The results deck carries this panel's verdict VERBATIM in its §7 `panel_verdict`: emit it as
`inputs/checkin_deck.json` and run `python3 scripts/run.py ravel.validation.validate_checkin
inputs/checkin_deck.json` before delivery — it asserts the eight deck sections are present incl. that
verbatim panel verdict, and a missing one is a FAIL.

PASS → deliver with the verdict + `verify_pack.py` report appended. CONCERNS → deliver WITH
findings appended and each answered (accepted-as-limitation or fixed+noted); unanswered
findings block. FAIL → do not deliver; fix, log in `DEVIATIONS.md`, RE-RUN BOTH TIERS. The
findings text is appended to the final check-in VERBATIM and un-pre-judged — no spin,
softening, or recommendation inserted ahead of the raw finding; even after fixes, the
physicist sees what the panel found.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The run was careful; the panel is ceremony" | Catalogue A6: ungrounded "consistent with the publication" claims were the #1 USER-caught class — the supervisor caught what we shipped, twice. |
| "I'll fix the finding and drop it from the report" | Findings ship VERBATIM even after fixes; a silent fix hides the failure class from the physicist. |
| "I know this run best — I'll be the adversary" | The author's context is what produced the miss; catalogue A5 was caught only by outside eyes, twice. |

## Stop conditions
- `verify_pack.py` exit 1 → fix the artifact/prose mismatch before Tier B (mechanics first).
- Tier B run by the same context that produced the run → invalid; re-run fresh.
- A FAIL verdict is un-negotiable: no partial delivery, no "noting it in passing".
