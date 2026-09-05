---
name: physicist-intake
description: Handle a new natural-language LHC physics request, including reproduction, reinterpretation, scans, existing-limit plots and collider-search method studies. Draft grounded intent and a task contract before survey or compute. For an existing run, refresh current state rather than rerunning intake.
when_to_use: a new physics request, with or without Initiate; existing-run follow-ups use the resume procedure
allowed-tools: Bash, Read, Write
---
# Physicist intake

Read `docs/workflow/start.md` first. This skill handles scientific intent and the initial plan;
it does not grant compute approval. Hooks reinforce the same procedure when available, scoped to
the active run rather than any contract found elsewhere in the repository.

## New request

1. Preserve the original request and choose a **new** run directory. Use the installed CLI:
   ```sh
   ravel initiate --prompt-file request.txt --out <new-run>
   ravel validate <new-run>/inputs/task_contract.json --json
   ```
   `--prompt "<verbatim request>"` is equivalent. Without installation, replace `ravel` with
   `python3 scripts/run.py ravel.__main__` from the checkout. Existing output paths are refused.
2. Review the draft. The action/negation parser is a bounded fallback. For unfamiliar phrasing,
   the host agent may supply `--interpretation <intent.json>` with the original request SHA-256
   and exact text spans; see `docs/cli.md`. Do not invent an analysis, dataset or result through
   that interface. `TBD-judgment`, required inputs and unresolved intent become numbered flags.
   Unsupported claims receive the named boundary and a relevant supported alternative.
3. Read `current_state.json` and perform only the next required work. For analysis intake, use
   **resource-sweep** then **route-analysis** to identify evidence and candidate figures, following
   `docs/workflow/steps/02-inputs.md`. Use **figure-contract** and **cost-preflight** for the
   requested deliverable and proposed budget. A `method_study` creates `<run>/method_proposal.md` and
   a survey contract with compute=`none`: specify candidate mechanisms, baselines, falsification
   tests, protected evaluation, data access and budget before designing an execution plan. No
   automatic novel-method training or physics closure is implied.
4. Complete needed run scaffolding with **new-analysis**, preserving the existing intake files.
   Compose CHECK-IN 1 per `docs/workflow/checklists/check-ins.md`: request, relevant figure gallery,
   verification waypoint, plan/budget, numbered assumptions, and all three response modes. Save
   `inputs/checkin1.json` and validate it with `ravel.validation.validate_checkin` before sending.
5. Record the physicist's actual approval with `ravel.workflow.workflow_state approve`, binding
   the current contract, check-in and budget. Reuse an existing valid approval within its scope.
   No generation, including smoke, or heavy compute before approval. Missing approval does not
   block independent read-only preparation. Elapsed time never supplies an answer or permission.
6. Continue only the required steps in `docs/workflow/README.md`; use **run-scan** when a scan is
   requested and **verification-panel** before delivery. Keep deviations and provenance current.

## Resume after restart or compaction

Run `ravel status --rundir <existing-run> --write`, then read `current_state.json` and the document
for its next blocker. The packet is rebuilt from the actual contract, ledger, gates, execution
receipts and approval. It is a view, never an authority: revalidate sources before launch or
serving. Consult `RESUME.md`/`DEVIATIONS.md` for necessary context, preserve failed evidence, and
do not reinitialize the run or read every development document.

## Boundaries

Invalid contracts cannot advance. Missing physics inputs stay explicit. A plan may remain a
zero-compute proposal; do not force a method study into an implemented training pipeline. A
blocked action remains blocked until the required evidence or actual user response exists.
After changing skill names or routes, run `scripts/maintenance/sync_skills.py` and the
`ravel.validation.check_agent_surface` gate; never hand-edit the Codex mirror.
