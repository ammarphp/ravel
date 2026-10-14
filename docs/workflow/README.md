# Generation-based recasting workflow

Given a published analysis with an analysis routine and a new-physics model, simulate the model's
events, run the routine, and produce the comparison plots and a statistical exclusion that show
whether the model is visible in — or excluded by — that analysis's data.

This page describes the existing generation-based Rivet/SimpleAnalysis route. Begin at
[start](start.md) for route selection, including scoped generation, supplied likelihoods and
[scientific studies](reference/scientific-studies.md).

```
 generation       shower          analysis                        visualize          data            exclusion
 MadGraph    →    Pythia8    →    Rivet routine        →    plots vs data    →   HEPData /     →   pyhf
 (LHE)            (HepMC)         OR SimpleAnalysis         + named outputs      bundled REF      (likelihood
                                 (YODA / ntuple)                                                  or counting) → CLs
                                                                                                       ↓  one µ₉₅ per point
                                                       ┌────────────── SCAN (outer loop, step 8) ──────────────┐
                                                       │  grid of model points → interpolate µ₉₅=1 → CONTOUR   │
                                                       └───────────────────────────────────────────────────────┘
```

Steps 1–7 calculate **one model point → one µ₉₅**; step 8 performs a requested scan. The approved
scientific question determines whether completion requires a point, figure or contour. A point
is partial when the request requires a larger domain.

This generation-based route uses a Rivet routine (https://rivet.hepforge.org) or a supported
SimpleAnalysis implementation. Both are first-class — step 4 chooses between them. Other
admitted operations follow their own contracts; planned backends are not executable support.

**Physicist-facing sessions enter via `docs/workflow/start.md`** (the "Initiate:" prompt forms + the promised
check-in sequence); every message a physicist sees follows `docs/workflow/checklists/check-ins.md`.

## Roles — the model-tier policy (binding)
Each step is tagged **[judgment]** (a physics-judgment point) or **[agent]** (mechanical — safe
to delegate to a lower-cost agent). **A weak/cheap model never silently takes a [judgment]
step.** Use the decision mode recorded through [start](start.md):
- **manual decision** (default): present the options and recommendation as a numbered
  CHECK-IN flag (`docs/workflow/checklists/check-ins.md`) and wait for the physicist's response.
- **delegated scientific decision**: when the user has explicitly delegated the applicable
  scope, the authorized reviewers and coordinator decide through the existing scientific
  review and approval path. Preserve independent CI2/CI3 review, resource and correction
  bounds, and revocation checks. Identify machine decisions accurately. Escalate an action
  outside delegation or unavailable required expertise; do not request renewed human assent
  for an action already covered by valid delegation.
- **script-assisted** (site says `script-assisted: <tool>`): run the named harness script and
  follow its output — the judgment is encoded in the tool, not improvised.
- **proceed-with-flag** (site says `proceed-with-flag`): a safe default exists — take it AND
  log it in the run's `DEVIATIONS.md` (+ its deviation check-in).
At EVERY [judgment] site, first run the matching operating protocol from
**`docs/workflow/checklists/judgment-protocols.md`** (the `judgment-protocols` skill routes by situation:
look-first / basis-manifest / trap-sweep / anchor-chain / discrepancy-decomposition /
source-ladder / conservative-default / kill-the-result) — the protocol is what makes the flag or
escalation SHARP (structured evidence + named options) instead of a shrug.
Tier-B verification (step 9) is its own case: a STRONG-model, fresh-context subagent runs the
adversary; a weak session that cannot spawn one escalates to the physicist rather than
reviewing its own work.

## Steps (work from the repo root; paths are relative to it)
| # | File | Role | What |
|---|------|------|------|
| 1 | `docs/workflow/steps/01-environment.md`   | [agent] | provision the conda tools (one-time) |
| 2 | `docs/workflow/steps/02-inputs.md`        | [judgment]  | obtain the routine; define the model + cards · **CHECK-IN** |
| 3 | `docs/workflow/steps/03-generate.md`      | [judgment] cards / [agent] run | MadGraph → LHE → Pythia8 → HepMC |
| 3.5 | `docs/workflow/checklists/detector-fidelity.md` | [judgment] judge / [agent] run | **detector-fidelity gate**: verify the Rivet routine's smearing, *or* match the Delphes card to published performance + certify per-SR acc×eff |
| 4 | `docs/workflow/steps/04-analyze.md`       | [judgment] choose / [agent] run | run a **Rivet** *or* **SimpleAnalysis** routine |
| 5 | `docs/workflow/steps/05-visualize.md`     | [agent] | plots vs data; **standardize plot names** |
| 6 | `docs/workflow/steps/06-acquire-data.md`  | [judgment] / [agent] | get the SR background + observed (and likelihood) — bundled-first, then HEPData |
| 7 | `docs/workflow/steps/07-exclude.md`       | [judgment]  | **pyhf** fit (serialized likelihood or counting model) → 95% CL limit on the model (**one µ₉₅ for this point**) · **CHECK-IN** |
| 8 | `docs/workflow/steps/08-scan.md`          | [judgment]  | **SCAN** — only when the request names axes: loop steps 3–7 over the named axes and assemble the requested quantity into the declared figures; before planning, reuse a completed identical scan read-only if one exists (see the step's reuse note) · **CHECK-IN** |
| 9 | `docs/workflow/steps/09-verify.md`        | [agent] tier A / [judgment] tier B | **VERIFICATION PANEL** — MANDATORY before any result is delivered: mechanical number-tracing (tier A) + adversarial physics attack (tier B), `docs/workflow/checklists/verification-panel.md`; verdict appended to the final check-in · **CHECK-IN** |

Steps 1–7 are the **inner loop** (one point → its requested quantity); step 8 is the **outer loop** over the named axes when the request asks for a scan.
Run a single point for a point request or validation; run a **scan** when the requested result
requires a parameter region. Neither output alone establishes publication-grade fidelity.

**Required skill per stage (SKILL-COVERAGE/G2).** A stage must not end with its governing skill
un-invoked. The bindings are keyed on the `run_state.current_step` stage names that
`workflow_state.py advance` writes: **`route` → `route-analysis`**, **`analysis` → `certify`**,
**`verification` → `verification-panel`**; and — because `scan` is a **task_mode**, not a stage —
a **scan-mode** run must have invoked **`run-scan`** by the **`statistics`** stage (the step-8 outer
loop that produces the exclusion contour). The Stop branch `stop_dispatch.py branch_skill_coverage`
(SKILL-COVERAGE/G2) BLOCKS turn-end (exit 2) when the stage maps to a required skill and
`run_state.skills_invoked` carries no matching entry — invoke the skill before advancing. Non-hook
FALLBACK: `workflow_state.py require --kind skill --what <skill>` returns nonzero when the stage's
skill is absent from the ledger.

Open each step file when you reach it. Make choices with `docs/workflow/checklists/`; on failure see
`docs/workflow/checklists/troubleshooting.md`. Filled-in examples are in `docs/workflow/reference/`.

## Check-ins (the physicist-facing layer — `docs/workflow/checklists/check-ins.md`)
Every physicist-facing message follows the standardized system in **`docs/workflow/checklists/check-ins.md`**;
physicist sessions enter via `docs/workflow/start.md`. The sequence:
- **CHECK-IN 1 "PLAN"** (after step 2, before ANY heavy compute): plain-language preamble, the
  published-figure GALLERY, the figure target(s) + the EARLY-VERIFICATION WAYPOINT, the plan,
  numbered flagged assumptions, and the three-response-mode footer.
- **CHECK-IN 2 "EARLY VERIFICATION"** (at the declared waypoint, before the bulk of compute): the
  published-element | produced-element side-by-side + a go/adjust ask. The GO is recorded with
  `workflow_state.py go`; full and scan compute waits for it (the CHECK-IN 2 gate). The
  [scientific review cycle](reference/physics-review.md) binds the critic, repair, skeptical
  verification, and synthesis to that decision and to later delivery.
- **DEVIATION check-ins** (immediate, own message, never batched): any mid-run change of course —
  reasoning + alternatives + impact, mirrored into the run's `DEVIATIONS.md` ledger.
- **FINAL "RESULTS DECK"** (after step 7/8, gated by the step-9 panel): headline figures with
  captions, key numbers with artifact provenance, limitations, deviations, the panel verdict, next
  steps.
Every displayed figure carries a physics-judgment caption (the caption rule); every decision is
narrated question→options→choice→reason (the "why" rule). Incorporate feedback by revisiting only
the step involved.

## Done when
Completion follows the approved deliverable and the required verification, not artifact existence alone.

- **A single point in this route** (steps 1–7) requires the named plots, a numerically supported
  pyhf 95% CL result, current execution/review evidence and the saved result record.
- **A requested scan** (step 8) additionally requires `scan.json`, the requested contour or line
  slice, stated coverage and any required published-reference comparison. A completed point
  does not complete a requested scan.
- **Other admitted operations** use their scoped or scientific-study completion contract. Do not
  force a supplied likelihood, quantity calculation or measurement task into a contour workflow.

## Reusable helpers

For an existing decision-justification case, `ravel rdj run --rundir RUN --case-id CASE
--host-config HOST.json --model MODEL` starts or resumes the registered `rdj.case` graph.
`run-roles` and the Python `run_roles` interface use that graph and return when proposer
content is needed. `run` pauses for typed proposer answers bound to the current case
digest; pass the interrupt-id response mapping with `--responses RESPONSE.json`.
Use `--edge-batch-size N --workers N` for separate parallel review batches. Reviews bind
the reviewed edges' Merkle digests; critic and verifier calls bind the complete case.
A started call with no registered receipt pauses for reconciliation and is never
dispatched again. Custody and invocation charges reuse the original reservation.
Campaign callers pass `--campaign DIR --campaign-charge VECTOR.json`, an explicit
per-call vector of `calls`, `output_tokens`, `wall_seconds`, and `native_attempts` against
their original campaign. Standalone cases charge the run. Until full-tool reviewers
are integrated, the dispatcher uses one receipted agent call per role batch. Authorization
remains `rdj_loop.authorize`: a resume value or reviewer verdict cannot override a failing edge.

Python helpers live in `src/ravel/`, grouped by workflow, physics, plotting, and validation.
Run a helper from the repository root with `python3 scripts/run.py ravel.<group>.<module>`.
Native sources and build scripts live in `native/`; `native/scripts/paths.sh` selects their
build and binary directories.
| Script | Step | Purpose |
|---|---|---|
| `routine_fetch.py`        | 2 | map a paper/Inspire/keyword → Rivet **and** SimpleAnalysis routine(s) |
| `figure_target.py`        | 2,5,8 | the **figure contract**: declare/resolve WHICH published figure is being reproduced; attach the extracted image + the generated counterpart; compose the side-by-side (`docs/workflow/checklists/figure-contract.md`) |
| `pythia_shower` (+`.cc`)  | 3 | Pythia8 → HepMC3 bridge |
| `name_plots.py`           | 5 | standardized, parseable plot names + an `INDEX.md` legend |
| `overlay_on_data.py`      | 5 | signal+background over the published data (the publishable view) |
| `fetch_figures.py`        | 5 | the analysis's **published figures** (arXiv source/PDF) for the fidelity check |
| `hepdata_fetch.py`        | 6 | published **likelihood** (resource endpoint) + **complete tables** (`--tables`: hepdata-cli, auto-falling back to the open `/record/data/<recid>/<table_id>/<version>` endpoint — same verify-after-download contract) |
| `rivet_ref_yields.py`     | 6 | Rivet bundled REF + signal YODA → per-SR (obs, bkg±unc, signal) |
| `pyhf_exclude.py`         | 7 | 95% CL upper limit on µ — serialized likelihood **or** counting model |
| `scan_orchestrator.py`    | 8 | **outer loop**: grid spec → per-point run dirs/TOMLs → harvest `result.json` → `scan.json` (plan/launch/status/assemble) |
| `scan_contour.py`         | 8 | render supplied scan columns with `--plot-spec`: selected axes, numerical/reference layers, labels, formats and output names; see the [declarative figure contract](checklists/figure-contract.md#declarative-scan-plots) |
| `verify_smearing.py`      | 3.5 | verify a Rivet routine declares its detector smearing/efficiencies + the era matches |
| `certify_acceptance.py`   | 3.5 | certify SA/Delphes per-SR acc×eff vs the published acc×eff map (tiered+attribution) |
| `validate_cutflow.py`     | — | certify A×ε vs the published cutflow (one-time per routine) |
| `reinterpret_db.py`       | — | independent SModelS exclusion cross-check |
| `workflow_state.py`       | — | **the per-run ledger every gate reads**: writes/drives `<rundir>/run_state.json` (skills/compute/subagents/edits + lifecycle cursor); subcommands init/record/advance/status/next/require. A step transition runs `workflow_state.py advance --to <stage>` — the fallback DRIVE precondition gate (G3): it reuses `validate_run_state` STAGE_ORDER/evaluate and REFUSES (exit 1, `blockers[]`) when the required-predecessor prefix has any FAIL, else stamps `current_step`/`next_required`. `workflow_state.py next` reports the pending action; at every step end, if it is non-empty, EXECUTE it this turn (background long jobs) — do not narrate it and stop. The Stop branch `stop_dispatch.py branch_drive` (DRIVE/D4) BLOCKS turn-end when `next_required` is pending, the turn is not a delivery/human-gate turn, and no live/recent background job exists; `next` is its non-hook FALLBACK (`docs/workflow/steps/03-generate.md`) |

**Rigour + readiness:** `scripts/audit.py`
evaluates readiness (`--write --out PATH` writes the report). Cutflow/fidelity certifications
and SModelS cross-check artifacts stay in the run directory; known limits are in
`docs/reference/limitations.md`. See `docs/workflow/checklists/validation.md` and
`docs/workflow/checklists/complex-analysis.md`.

## Mechanized enforcement (hooks) — the belt, with a non-hook fallback for each

The worktree `.claude/settings.json` wires the workflow's hard gates as Claude Code hooks. Hook governance covers Claude Code only; other hosts call `ravel gate` and rely on
the delivery-side checks (`docs/workflow/hooks.md`). Hooks resolve the session's own run through
the run registry, never the newest run. A hook is the *belt*; when a hook cannot run (a different harness, a fail-open crash,
a bare shell), the **non-hook FALLBACK** — a script or rule the step docs tell the agent to run by
hand — is the *suspenders*. Both enforce the same gate; neither is the sole line of defence.

| Hook (`.claude/hooks/`) | Event · matcher | Gate it mechanizes | Non-hook FALLBACK |
|---|---|---|---|
| the skill-precedence guard (G22/N1) | PreToolUse · `Skill` | BLOCKS (exit 2) a contract-presupposing skill (`new-analysis`/`run-scan`/`run-stage`/`certify`/`route-analysis`/`verification-panel`) until the ACTIVE run (session/cwd-scoped) carries a `task_contract.json` | `docs/workflow/start.md`'s rule — fire `physicist-intake` first |
| the PostToolUse observer (G2 substrate) | PostToolUse · `Bash\|Edit\|Write\|MultiEdit\|NotebookEdit\|Skill\|Agent\|Task` | records each Skill/Edit/subagent tool call to the run ledger (`run_state.json`); NEVER blocks (exit 0) — the substrate every Stop/DRIVE gate reads | the fallback twin: the agent runs `workflow_state.py record --kind <skill\|edit\|subagent> …` (`docs/workflow/checklists/check-ins.md`) |
| the UserPromptSubmit router (G1) | UserPromptSubmit | on every prompt that is not a development request or a short reply, runs `route_prompt.py` and INJECTS the INITIATE reminder as `additionalContext`; a development brief leaves no route-pending marker; non-blocking (exit 0) | `docs/workflow/start.md` itself (the routing rule) |
| the Stop dispatcher (`stop_dispatch.py`) | Stop | the branch brain: BLOCKS turn-end (exit 2, reason fed back) on the first tripped branch below; a crash fail-opens (exit 0) | per-branch, below |

The Stop dispatcher's branches (evaluated in priority order), each with its own fallback:

| Branch (`stop_dispatch.py`) | Gate | Non-hook FALLBACK |
|---|---|---|
| `branch_d18` (D18 umbrella) | on a CHECK-IN/RESULT **delivery** turn, BLOCKS if `validate_run_state.py` reports any FAIL | run `validate_run_state.py` before composing any check-in / RESULT |
| `branch_catch` (CATCH/D6) | BLOCKS turn-end while the ledger carries an unresolved failure record | `stage_supervisor.py` wraps every `run_stage` — writes `logs/<stage>.failure.json` + records it (G6/D6) |
| `branch_phantom` (PHANTOM/D5) | BLOCKS a turn that CLAIMS a background job is running when no matching live process exists | confirm the process is live (its log / `ps`) before saying it runs; the `record --kind compute` ledger entry is what makes it verifiable |
| `branch_drive` (DRIVE/D4) | BLOCKS a turn that narrates its `next_required` step instead of executing it (and no live/recent bg job) | `workflow_state.py next` — read the pending action and EXECUTE it this turn (`docs/workflow/steps/03-generate.md`) |
| `branch_skill_coverage` (SKILL-COVERAGE/G2) | BLOCKS a turn whose current stage skipped its governing skill | the skill-before-advance rule — `workflow_state.py require --kind skill --what <skill>`; invoke the skill, then advance |
| `branch_detach` (DETACH/N6) | BLOCKS a detached job with no durable `run_state`+heartbeat | `scan_babysitter.py` (keeps the scan alive + heartbeat) / `progress_reporter.py` (~30-min `ScheduleWakeup`, G7) |

**The one aggregate green bar:** `make green` runs the per-gate simulation
(`--require-all`), the agent-surface check, the run-state selftest and an informational audit. A
completeness test pins that every one of the 30 gates G0a–G27 has a case.

> **Delivery detection is artifact-keyed:** a freshly written `inputs/checkin2.json` / `outputs/results_deck.*` / `RESULT.md` makes the turn a DELIVERY turn (the D18 umbrella + open-defect gates fire) regardless of the prose; SessionStart injects the active run's state summary on every session start.
