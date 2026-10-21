---
name: physicist-intake
description: Handle a new natural-language physics request, including reproduction, reinterpretation, scans, existing-limit plots, fits, measurements, calculations, supplied-event or model studies, generation, manuscripts, diagrams and collider-search method studies. Draft grounded intent and a task contract before survey or compute. For an existing run, refresh current state rather than rerunning intake.
metadata:
  when_to_use: a new physics request, with or without Initiate; existing-run follow-ups use the resume procedure
allowed-tools: Bash, Read, Write
---
# Physicist intake

State the required output and precision in the user's terms. Choose the cheapest method that meets the output, validity domain and precision, record why each cheaper method is insufficient or missing with evidence in `inputs/method-decision.json`, and stop when the answer is complete. Validate and render the record with `ravel method-decision --rundir RUN` before CHECK-IN 1 approval; full and scan launches refuse a missing, invalid or unjustified decision.

Read `docs/workflow/start.md` first and pick the route from its table "Which route a request
takes". This skill handles scientific intent and the initial plan; it does not grant compute
approval. Hooks reinforce the same procedure when available, scoped to
the active run rather than any contract found elsewhere in the repository.

## New request

For a request limited to supplied-event analysis, quantity transport, supplied
measurement inference or the bounded domain operations, use
`docs/workflow/reference/scientific-studies.md` before creating a run. Preserve the
original request, check that the typed study covers its entire requested scope,
state input provenance and numbered assumptions, and use `ravel plan` with a new
directory as its explicit intake. Then use its `approve/run/status` lifecycle and
CHECK-IN 2. Do not initialize a reproduction contract and silently change its mode.
The host agent selects this route; the intent parser does not automatically draft
these new specifications. Scripted assent still needs explicit experimental
authorization and does not establish expert scientific review. A larger paper
reproduction request remains subject to the full procedure below.

1. Preserve the original request and choose a **new** run directory. Use the installed CLI:
   ```sh
   ravel initiate --prompt-file request.txt --out <new-run>
   ravel validate <new-run>/inputs/task_contract.json --json
   ```
   `--prompt "<verbatim request>"` is equivalent. Without installation, replace `ravel` with
   `python3 scripts/run.py ravel.__main__` from the checkout. Existing output paths are refused.
2. Review the draft. The action/negation parser is a bounded fallback. For unfamiliar phrasing,
   the host agent can supply `--interpretation <intent.json>` with the original request SHA-256
   and exact text spans; see `docs/cli.md`. When you can already see that the parser will miss
   the request's kind, supply the interpretation on the first `initiate` call. Do not invent an analysis, dataset or result through
   that interface. `TBD-judgment`, required inputs and unresolved intent become numbered flags.
   Unverified claims receive the named boundary and a relevant supported alternative.
3. Read `current_state.json` and perform only the next required work. For analysis intake, use
   **resource-sweep** then **route-analysis** to identify evidence and candidate figures, following
   `docs/workflow/steps/02-inputs.md`. Use **figure-contract** and **cost-preflight** for the
   requested deliverable and proposed budget. A `method_study` creates `<run>/method_proposal.md` and
   a survey contract with compute=`none`: specify candidate mechanisms, baselines, falsification
   tests, protected evaluation, data access and budget before designing an execution plan. No
   automatic novel-method training or physics closure is implied.
   For `generate` or `likelihood`, follow `docs/workflow/reference/scoped-workflows.md` and
   `ravel plan/approve/run`. Prepare the typed specification and CHECK-IN 1 before compute.
   These routes require scoped verification, not detector certification. Scripted YES needs
   explicit user authorization and remains distinct from expert review. Continue with their
   result check-in instead of the full-analysis scaffolding below.
4. Complete needed run scaffolding with **new-analysis**, preserving the existing intake files.
   Compose CHECK-IN 1 per `docs/workflow/checklists/check-ins.md`: request, relevant figure gallery,
   verification waypoint, plan/budget, numbered assumptions, and all three response modes. Save
   `inputs/checkin1.json` and validate it with `ravel.validation.validate_checkin` before sending.
5. Use the manual or delegated approval path selected in `docs/workflow/start.md`.
   In manual mode, record the physicist's actual approval with
   `ravel.workflow.workflow_state approve`, binding the current contract, check-in and budget.
   An explicit autonomous instruction in the original request or actual CHECK-IN 1 response
   must be recorded through the scientific-autonomy declaration and authenticated delegated
   approval path; a task file or agent recommendation alone does not grant that authority.
   Reuse a valid approval within its scope. Delegated decisions are machine decisions, and
   internal CI2 and CI3 reviews still run. No generation, including smoke, or heavy compute
   before applicable approval. Missing approval does not block independent read-only
   preparation. Elapsed time never supplies an answer or permission.
6. Continue only the required steps in `docs/workflow/README.md`; use **run-scan** when a scan is
   requested and **verification-panel** before delivery. Keep deviations and provenance current.

## Statistic

Keep the statistic the request names. An exclusion request that does not prescribe a statistic
gets 95% CLs exclusion limits by default. When the request prescribes a statistic (an explicit
formula, an Nσ region, a Δχ² threshold or a Bayesian credible interval), that statistic is the
requested quantity: record its definition in the contract assumptions and CHECK-IN 1 and deliver
it as the primary result, with CLs optionally alongside. Fits, measurements, calculations and
summaries report their own quantities. See `.claude/rules/statistics.md`.

## Resume after restart or compaction

Run `ravel status --rundir <existing-run> --write`, then read `current_state.json` and the document
for its next blocker. The packet is rebuilt from the actual contract, ledger, gates, execution
receipts and approval. It is a view, never an authority: revalidate sources before launch or
serving. Consult `RESUME.md`/`DEVIATIONS.md` for necessary context, preserve failed evidence, and
do not reinitialize the run or survey the repository again.

## Boundaries

Invalid contracts must not advance. Missing physics inputs stay explicit. A plan can remain a
zero-compute proposal; do not force a method study into an implemented training pipeline. A
blocked action remains blocked until the required evidence or actual user response exists.
After changing skill names or routes, run `scripts/maintenance/sync_skills.py` and the
`ravel.validation.check_agent_surface` gate; never hand-edit the Codex mirror.


If the deterministic draft is `unsupported`, read its printed capability recovery packet.
Distinguish unresolved intent from an actual claim/data boundary. Inspect exact current
scientific-operation source contracts, retain the whole original request, and supply grounded
intent or an appropriate component specification. Do not rewrite a significance request as
exclusion or replace generation/reinterpretation with a supplied-event diagnostic. Public
resource recovery and reversible planning do not need a redundant approval; execution retains
its ordinary exact-scope approval. Parent delivery is assessed against all requested dimensions,
not the first successfully admitted component.

## Live steering before dispatch

Read `ravel gate-wiring steer state --rundir <run>` before each dispatch.
Acknowledge new events with `ravel gate-wiring steer ack <event-id> --rundir <run>
--interpretation <text> [--amended-plan <path>]`. Reconcile requirements and
redirects in the amended plan, then call `dispatch_permitted(run, node_id)`.
A scope increase needs CHECK-IN 1 reapproval even after acknowledgement.
Pause and veto prevent dispatch. Priority orders eligible pending work inside
the existing budget. Preserve earlier results. Research-board posts are advisory
and grant neither steering nor approval.
