---
name: postmortem-capture
description: Capture what a hep-agentic-pipeline run hit — gaps, failures, workarounds, near-misses — into the durable records at run close: the run RESULT.md GAPS section, framework/FAILURE-CATALOGUE.md (what happened → how caught → where the guard lives), and framework/CHANGES-REGISTRY.md entries. Use at the END of any run or trial that hit at least one unplanned obstacle, before reporting it complete.
when_to_use: closing a run/trial/eval that hit unplanned obstacles, workarounds, or tool defects; after a verification panel surfaced findings worth guarding against
allowed-tools: Bash, Read, Edit, Write
---
# Skill — postmortem capture (an unrecorded gap is a repeat offense)

The generality trials proved it: gaps that land in records get fixed and eval'd; gaps that
stay in chat memory recur (charter §4d). Run this at close, while the evidence is fresh.

## 1. The run's own record
Append a **GAPS** section to the run's `RESULT.md`: one numbered line per gap —
what was attempted, what failed/missed, the workaround, file:line evidence. Cross-check the
run's `DEVIATIONS.md`: every ledger entry that exposed a tooling/doc hole gets a GAP line.
**Then write the run's verification ladder** (per `workflow/checklists/verification-ladder.md`,
as a VERIFICATION-LADDER file at the run root): R0–R6 statuses + the bracketing verdict per gap —
a gap is CONFIRMED only by the bracket (rung above passes, rung at/below fails); everything else
is labeled PLAUSIBLE-UNATTRIBUTED in RESULT.md. `not-checked` rungs are the run's named debt,
never implied away.

## 2. The failure catalogue (real incidents only)
For each gap that is a REAL incident (not a wishlist item), APPEND to
`framework/FAILURE-CATALOGUE.md` in its format: **what happened → how it was caught → where
the guard now lives** (or `guard: PENDING (CR-NNN)`). The catalogue is append-only and seeds
the step-9 Tier-B attack list and the routing evals — write entries so an adversary can
re-attempt the failure class mechanically.

**A DEFECTIVE HELPER is recorded as an OPEN defect note (N5/G26), not just narrated.** When a helper
tool itself is found wrong mid-run (it produced a bad number — e.g. a yield-reading helper reporting
A×e as 956%), append an entry to `run_state.open_defect_notes` (`{"helper","note","status":"open"}`) the
moment it is caught. `verify_pack.py` FAILs on any open note and the DELIVERY-only `branch_open_defect`
Stop-branch (token `G26-OPEN-DEFECT:`) BLOCKS any delivery that would let that helper's number feed a
comparison/check-in — until you fix the helper (or substitute a blessed tool) and flip the note
`status:"fixed"`.

## 3. The changes registry (every fix is findable)
For each gap needing a code/doc/skill fix: add a `CR-NNN` entry to
`framework/CHANGES-REGISTRY.md` (ID · date · what · why · where-embedded · status). Fix now →
status EMBEDDED with the fix + wiring named; defer → DEFERRED with the trigger. Map each gap
to its OWNER surface (a named skill / harness script / doc / PRODUCT-CONTRACT row) — a gap
with no owner is itself a finding.

## 4. Close the loop
- Owner is a skill/doc you can fix in-session → fix it, then the `embed-and-commit` skill
  (which now enforces the registry step).
- The gap class is routing/intake-shaped → note it as a candidate eval prompt in
  `framework/ROUTING-EVALS.md` so the next eval round tests it.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "I worked around it inline — not worth recording" | The AD trial re-hit three unguarded CMS-trial gaps (G-AD-02/08/09 = G-CMS-02/07/08): unrecorded gaps recur, near-verbatim. |
| "It's obviously a gap; confirming it is overkill" | A gap is CONFIRMED only by the bracket; everything else ships labeled PLAUSIBLE-UNATTRIBUTED, and `not-checked` rungs are named debt. |
| "Postmortem later, once things calm down" | Later = a fresh session without the live evidence (charter §4d: chat-memory gaps recur; recorded gaps get fixed and eval'd). |

## Stop conditions
- A run reporting "complete with workarounds" and no GAPS section = the postmortem is NOT
  done. An incident with no catalogue entry and no CR is captured nowhere durable.
