---
name: new-analysis
description: Scaffold a new trial-run directory and its inputs for reinterpreting an analysis against a model in hep-agentic-pipeline. Use when starting a fresh run AFTER physicist-intake has produced the task contract — for a fresh physics REQUEST, fire physicist-intake first (it routes and gates; this skill only builds the skeleton).
when_to_use: a routed run needs its run-dir skeleton and input stubs (task contract already exists, or the session is development-side)
allowed-tools: Bash, Read, Write
---
# Skill — scaffold a new reinterpretation run

**OWNERSHIP (CR-022, do this FIRST):** acquire the run-dir lock before touching it —
`python3 trial-runs/_infrastructure/session_lock.py acquire <rundir> --owner <session-label>`;
a live foreign lock (exit 3) means another session owns this run: coordinate or `steal`
EXPLICITLY (recorded). Release at run close. The incident this kills: two concurrent eval
sessions silently sharing one run dir 18 s apart.

Creates `trial-runs/<date>_<analysis>_<model>/` with the standard layout, so the run is
reproducible, resumable, and `certify`-able. Trial runs are **records, not distributable**
(`workflow/DISTRIBUTION.md`); never reference them as examples in the agent-facing docs.
A fresh PHYSICS request routes through the `physicist-intake` skill FIRST — CHECK-IN 1 gates
all heavy compute; this skill is the scaffold, not the route.

## Steps
1. Pick the directory name: `trial-runs/<YYYY-MM-DD>_<ANALYSIS-OR-TOPIC>_<model-tag>/`
   (placeholder form — the real name uses the run's own date/analysis/model). Pass the date
   in — do not call `date` (it's nondeterministic).
2. Create the skeleton — including the TWO LEDGERS the check-in system requires from birth:
   ```bash
   R=trial-runs/<dir>; mkdir -p $R/{config,inputs,logs,outputs,build,plots}
   printf '# DEVIATIONS — mid-run changes of course (what/from/to/why/impact; append at the moment of change)\n\n(none yet)\n' > $R/DEVIATIONS.md
   printf '# RESUME — state checkpoint (update at every check-in + launch: state, running pids/logs, exact resume commands, what remains)\n\n(not started)\n' > $R/RESUME.md
   ```
   (`checklists/check-ins.md` makes the DEVIATIONS ledger mandatory and `verify_pack.py`
   checks it; `RESUME.md` is the charter-§4c checkpoint for anything that outlives a session.)
3. Populate `inputs/`:
   - `task_contract.json` (from `physicist-intake` / `route_prompt.py`) — the routing record;
   - a **copy** of the param card (never the pristine original) — per
     `workflow/checklists/model-cards.md` (incl. the EWKino recipe for chargino/neutralino);
   - `sr_spec.json` (the routine's SR-name → counter map; copy a sibling run's for the same
     routine) and `plot_labels.json` (for `name_plots.py`) — WHERE a routine exists; a
     no-routine (Option C) run skips both and says so in `RESULT.md`;
   - `figure_target.json` (the figure contract — `figure-contract` skill).
4. Confirm the routine + √s: `routine_fetch.py --query "<code/Inspire>"` (0 hits → the
   `route-analysis` skill's re-query loop, NOT a dead end); check `rivet --show-analysis <ID>`
   for Beams/Status (SINGLEWEIGHT/NOTREENTRY → see `run-stage`).
5. Then follow `workflow/WORKFLOW.md` **steps 3→9**: `run-stage` to generate/shower/analyze,
   fetch data, `pyhf_exclude.py`, `certify` — and for the reproduction/reinterpretation
   deliverable the **step-8 SCAN** (`run-scan` skill: the contour, not a point) and the
   **MANDATORY step-9 verification panel** (`verification-panel` skill) before anything is
   delivered. Fill `RESULT.md` (template: `trial-runs/README.md`).
6. End: run the `directory-keeper` skill to reconcile `DIRECTORY.md`.

Choose the routine path by what the analysis provides (Rivet vs SimpleAnalysis-native) —
`workflow/checklists/choosing-routine.md`. `[judgment]` for the model/card/statistics choices
(escalate via CHECK-IN flags); `[agent]` for plumbing.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Outputs can live wherever for now; I'll tidy later" | Catalogue D3 (recurrence): a pre-routing survey left a stray output dir OUTSIDE the run tree. Everything a run produces lives under its rundir from birth. |
| "I'll add the ledgers when something actually deviates" | Restarts and mid-run changes are NORMAL (charter §4c); a run born without `DEVIATIONS.md`/`RESUME.md` loses its first deviations — and `verify_pack.py` checks for them. |
| "It's a fresh physics request — scaffolding IS starting" | Trial gap G-AD-01: unrouted asks improvise. physicist-intake routes and gates FIRST; this skill is only the skeleton. |

## Stop conditions
- Physicist-facing session with no `task_contract.json` → back to the physicist-intake skill;
  never scaffold an unrouted physics ask.
- Routine unresolved after route-analysis's re-query loop → scaffold ONLY as the declared
  no-routine Option C (G-CMS-01/G-AD-07), never a silent custom path.
