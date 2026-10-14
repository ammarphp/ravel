---
name: new-analysis
description: Scaffold a new trial-run directory and the inputs its admitted request plan needs. Use when starting a fresh run AFTER physicist-intake has produced the task contract — for a fresh physics REQUEST, fire physicist-intake first (it routes and gates; this skill only builds the skeleton).
when_to_use: a routed run needs its run-dir skeleton and input stubs (the task contract already exists)
allowed-tools: Bash, Read, Write
---
# Skill — scaffold a new run

**OWNERSHIP (do this FIRST):** acquire the run-dir lock before touching it —
`python3 scripts/run.py ravel.workflow.session_lock acquire <rundir> --owner <session-label>`;
a live foreign lock (exit 3) means another session owns this run: coordinate or `steal`
EXPLICITLY (recorded). Release at run close. Without the lock, two concurrent sessions can
silently share one run dir.

Creates `trial-runs/<date>_<topic>/` with the standard layout, so the run is reproducible,
resumable and reviewable. Trial runs are **records, not distributable**;
never reference them as examples in the agent-facing docs.
A fresh PHYSICS request routes through the `physicist-intake` skill FIRST — CHECK-IN 1 gates
all heavy compute; this skill is the scaffold, not the route.

The scaffold follows the admitted request: `inputs/task_contract.json` and the request plan
(`inputs/plan.json`) name the claims, operations and stages. Create the artifacts those
operations consume and nothing else. A calculation, a summary of published results or a fit
to supplied data needs no cards, routine, generation or scan.

## Steps
1. Pick the directory name: `trial-runs/<YYYY-MM-DD>_<topic>/` (the run's own date and a short
   topic from the request). Pass the date in — do not call `date` (it's nondeterministic).
2. Create the skeleton — including the TWO LEDGERS the check-in system requires from birth:
   ```bash
   R=trial-runs/<dir>; mkdir -p $R/{config,inputs,logs,outputs}
   printf '# DEVIATIONS — mid-run changes of course (what/from/to/why/impact; append at the moment of change)\n\n(none yet)\n' > $R/DEVIATIONS.md
   printf '# RESUME — state checkpoint (update at every check-in + launch: state, running pids/logs, exact resume commands, what remains)\n\n(not started)\n' > $R/RESUME.md
   ```
   Add `build/` or `plots/` only when a planned stage writes there.
   (`docs/workflow/checklists/check-ins.md` makes the DEVIATIONS ledger mandatory and `verify_pack.py`
   checks it; `RESUME.md` is the checkpoint for anything that outlives a session.)
3. Populate `inputs/` from the plan. Always: `task_contract.json` (from `physicist-intake` /
   `route_prompt.py`) and the plan itself. Then, for each planned operation, the inputs its
   signature consumes (`ravel.validation.validate_request_plan.signatures()`), for example:
   - a model stage: a **copy** of each supplied card (never the pristine original), per
     `docs/workflow/checklists/model-cards.md`;
   - an analysis stage with a routine: the routine's region-name map and plot labels;
   - a figure claim with a declared reference figure: `figure_target.json` (`figure-contract` skill).
   Record in `RESULT.md` any planned input that does not exist and why.
4. For an analysis stage, confirm the routine and collision energy: `routine_fetch.py --query
   "<identifier>"` (0 hits → the `route-analysis` skill's re-query loop, NOT a dead end).
5. Then follow the workflow steps the plan's stages select (`docs/workflow/README.md`): only the
   stages the plan lists, a scan only when the request asks for one over named axes (`run-scan`),
   and always the **step-9 verification panel** (`verification-panel` skill) before anything is
   delivered. Fill `RESULT.md` (template: `docs/workflow/run-directory.md`).
6. End: run the `directory-keeper` skill to reconcile `DIRECTORY.md`.

For an analysis stage, choose the routine path by what the analysis provides —
`docs/workflow/checklists/choosing-routine.md`. `[judgment]` for the model/card/statistics choices
(escalate via CHECK-IN flags); `[agent]` for plumbing.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Outputs can live wherever for now; I'll tidy later" | An output written outside the run tree escapes its provenance and review. Everything a run produces lives under its rundir from birth. |
| "I'll add the ledgers when something actually deviates" | Restarts and mid-run changes are NORMAL; a run born without `DEVIATIONS.md`/`RESUME.md` loses its first deviations — and `verify_pack.py` checks for them. |
| "Every run needs cards, a routine and a scan" | The plan decides. Inputs no planned operation consumes are clutter that reviewers must rule out. |
| "It's a fresh physics request — scaffolding IS starting" | An unrouted request is answered by improvisation. physicist-intake routes and gates FIRST; this skill is only the skeleton. |

## Stop conditions
- Physicist-facing session with no `task_contract.json` → back to the physicist-intake skill;
  never scaffold an unrouted physics ask.
- Routine unresolved after route-analysis's re-query loop → scaffold ONLY as the declared
  no-routine path recorded in the plan, never a silent custom path.
