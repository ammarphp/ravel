# Start or resume a physics request

Describe the scientific question in ordinary language. "Initiate:" is optional. Name a paper,
figure, analysis, model or mass range when known; attach available inputs. Missing inputs remain
explicit questions or flagged assumptions. A request to develop a collider-search method starts
as a bounded research proposal, with data access, baselines, evaluation splits, calibration and
compute still to be agreed. It does not launch model training.

For an analysis, the first deliverable is CHECK-IN 1: the request restated, relevant published
figures with captions, a proposed verification waypoint, a scoped plan and budget, and numbered
assumptions. The physicist may answer, ask questions or change the proposal. No generation,
including smoke, starts before approval. Timing depends on the chosen analysis and resources;
the approved budget and actual completed coverage are reported, not promised in advance.

Later check-ins show the early comparison, deviations, and the final figures with artifact-backed
numbers and limitations. Required verification follows `docs/workflow/steps/09-verify.md`.
Recasting results are 95% CLs exclusion limits; reference agreement is not discovery or coverage
certification. The requested deliverable controls whether a point, figure, or scan is appropriate.

## Agent procedure: a new request

1. Read `.claude/skills/physicist-intake/SKILL.md` (or its generated Codex mirror). Use the original
   request and a **new** run directory:
   ```sh
   ravel initiate --prompt-file request.txt --out <new-run>
   ravel validate <new-run>/inputs/task_contract.json --json
   ```
   From a source checkout without installation, replace `ravel` with
   `python3 scripts/run.py ravel.__main__`. The local action/negation parser drafts intent; a host
   agent may instead supply `--interpretation <intent.json>` grounded in the exact request hash
   and matching text spans. Structural validation does not establish scientific judgment.
2. Read the generated `current_state.json`. Resolve required inputs and draft assumptions using
   the relevant resource-sweep/route-analysis procedure and `docs/workflow/steps/02-inputs.md`.
   A `method_study` intent creates a zero-compute survey contract plus `<run>/method_proposal.md`;
   develop that proposal before choosing an executable research plan.
3. Present CHECK-IN 1 using `docs/workflow/checklists/check-ins.md`; validate its JSON and record
   the actual approval through the workflow. Never fabricate an approval quotation. Follow the
   next required step, retaining provenance and deviations. Load environment setup only when
   needed, using `docs/reference/environment.md`.

Intake records no completed skills, approved compute, or scientific result. The documented
procedure applies when host hooks are unavailable too. Existing guards scope a run by its
working directory/session; an unrelated old contract elsewhere is not sufficient.

## Agent procedure: resume an existing run

```sh
ravel status --rundir <existing-run> --write
```

Read the refreshed `current_state.json`: request, contract/ledger fingerprints, approval state,
execution receipts, lifecycle verdict, blockers and next required step. It is a derived view,
not execution authority. The executors and serving gates must check the current source artifacts
again. If inputs changed, repair the identified stale stage or approval; preserve failed receipts.

Open only the blocker-relevant workflow step or checklist. Use the run's `RESUME.md` and
`DEVIATIONS.md` for context when needed, not as substitutes for live validation. Do not replay
intake, overwrite an existing run, or survey all development documents after compaction.
