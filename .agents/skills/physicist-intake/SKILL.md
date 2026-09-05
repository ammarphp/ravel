---
name: physicist-intake
description: Handle ANY natural-language physics request in hep-agentic-pipeline — reproduce/reinterpret a published ATLAS/CMS analysis, scan a mass plane, make a summary plot of existing limits, "is model X excluded", model-agnostic/anomaly asks, projections — with or without the "Initiate:" prefix. Produces the task contract + CHECK-IN 1 and BLOCKS heavy compute until the physicist approves. Fire BEFORE reading anything except workflow/INITIATE.md.
when_to_use: the prompt is a physics ask (not repo development) — the very first thing a physicist-facing session does, before any survey, scaffolding, or generation
allowed-tools: Bash, Read, Write
---
# Skill — physicist intake (request → task contract → CHECK-IN 1 → compute block)

You are the AGENT executing a physicist's request. The physicist reads `workflow/INITIATE.md`;
YOU execute this procedure. The failure this skill kills: fresh sessions surveying the repo,
improvising a route, or spending generation budget before the plan is approved (failure F1/F5,
`framework/FAILURE-CATALOGUE.md` D3).

> **Enforced (G22/N1):** a `PreToolUse`-on-`Skill` hook (`.claude/hooks/pretooluse-skill.sh`)
> HARD-BLOCKS (exit 2) any contract-presupposing skill
> (`new-analysis`/`run-scan`/`run-stage`/`certify`/`route-analysis`/`verification-panel`) until THIS
> run has a `task_contract.json` — this intake skill must run first (it produces that contract). The
> contract check is **session/cwd-scoped to the active run** (the tool-call `cwd` when inside a
> `trial-runs/<rundir>` tree, else `session_id` via that run's `run_state.json`), NOT a repo-wide glob,
> so it still fires in a mature repo full of old contracts; no resolvable active run → blocked.
> FALLBACK when the hook does not fire: `workflow/INITIATE.md`'s routing rule.

## Procedure
1. **Classify mechanically** (never free-hand):
   ```bash
   python3 trial-runs/_infrastructure/route_prompt.py --prompt "<the request, verbatim>" \
     --out <rundir>/inputs/task_contract.json        # rundir from new-analysis, or a temp dir pre-scaffold
   python3 trial-runs/_infrastructure/validate_task_contract.py <rundir>/inputs/task_contract.json
   ```
   `--out` also initializes the rundir's minimal `run_state.json` ledger when absent
   (CR-131/N11), so the open-defect gate (N5/G26) evaluates on every run — compute=none
   tracks included.
   The contract's `task_mode`/`detector_mode`/`stat_mode` follow `PRODUCT-CONTRACT.md`; any
   `TBD-judgment` field and every `escalate` line becomes a NUMBERED FLAG in CHECK-IN 1 — the
   physicist decides, you never silently pick. `blocking` entries are named refusals: present
   them with the nearest supported alternative (e.g. shape-fit → generator-level comparison +
   sensitivity-expected-only; precedent: `framework/interrogations/generality.md`).
2. **Survey — no generation.** Run the RESOURCE SWEEP first (`resource-sweep` skill /
   `resource_census.py` — step 2.0; its `--markdown` block is CHECK-IN 1 §(i-b)), then resolve
   the analysis + candidate figures:
   `routine_fetch.py --query "<code/Inspire/arXiv>"` (route-analysis skill on 0 hits),
   `hepdata_fetch.py --inspire insNNNN` (figure_index), `fetch_figures.py --map-captions`.
   `task_mode=summary_plot` asks execute via **`checklists/summary-plot.md`** (the
   no-generation harvest→basis-manifest→overlay track); `projection`/`reinterpret` asks: the
   spec + routing live in `reference/projection-replane.md` (builds CR-024/025 pending — say so
   in the plan honestly).
   Cost the plan: `cost_preflight.py --mode <contract.compute_plan> --points N` — its numbers
   ARE CHECK-IN 1's budget line.
3. **Scaffold** the run dir via the `new-analysis` skill (creates `DEVIATIONS.md` + `RESUME.md`
   stubs; move the task contract into `<rundir>/inputs/`).
4. **Compose CHECK-IN 1 "PLAN"** exactly per `workflow/checklists/check-ins.md`: preamble ·
   figure GALLERY · figure target + EARLY-VERIFICATION WAYPOINT ([judgment] — propose, don't
   decide silently) · plan + the cost_preflight numbers · NUMBERED FLAGS (contract assumptions
   + escalate lines + TBD fields) · the three-response-mode footer. Emit it as `inputs/checkin1.json`
   and run `python3 trial-runs/_infrastructure/validate_checkin.py inputs/checkin1.json` before
   sending — a missing required section (any of the seven, an ill-formed `F<n>` flag, or fewer than
   the three response modes) is a FAIL; fix it, never send an invalid check-in.
5. **BLOCK.** No event generation beyond `smoke` until the physicist approves CHECK-IN 1.
   `approval_required` is structurally true — there is no override.
6. **After approval**: follow `workflow/WORKFLOW.md` steps 3→9 — the deliverable of
   reproduce/reinterpret/scan is the step-8 CONTOUR (run-scan skill), and NOTHING is delivered
   without the step-9 panel (verification-panel skill).

**Router integrity:** this skill routes by NAME (resource-sweep, route-analysis, new-analysis,
run-scan, figure-contract, verification-panel, cost-preflight); a renamed or removed skill makes
this router lie. After any skill rename/removal, reconcile the references here, then run the
directory-keeper skill + the surface gate (`check_agent_surface.py`).

## Resume rule (charter §4c — restarts/compaction are NORMAL)
After any restart or context compaction: re-anchor from FILES, never from an auto-summary —
re-read `workflow/INITIATE.md`, the run's `inputs/task_contract.json`, and its `RESUME.md`
before acting. Update `RESUME.md` at every check-in and every launch (state, running pids/logs,
exact resume commands, what remains).

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Let me survey the repo first to orient" | Catalogue D3: four fresh sessions burned tokens surveying dev docs instead of routing, and a pre-routing survey left a stray output dir outside the run tree. INITIATE.md, then this skill — nothing else first. |
| "This is interest-level curiosity, not a run request" | Trial gap G-AD-01: interest-level prompts had no entry point and improvised. They route HERE — the contract may still conclude compute=`none`. |
| "CHECK-IN 1 has sat a while; a sensible default keeps momentum" | There is no timeout-and-proceed; elapsed time is not approval (stop conditions below). |

## Stop conditions
- `validate_task_contract.py` fails → fix the contract, never proceed on an invalid one.
- The contract says `unsupported`/`blocking` → deliver the named refusal + alternative; STOP.
- Missing `required_user_inputs` → ask via CHECK-IN 1 flags; do not guess physics inputs.
- CHECK-IN 1 unanswered → the run stays blocked; there is no timeout-and-proceed. A long tool
  call, a finished background job, or elapsed wall-clock time is NOT approval — only the
  physicist's reply advances the run past the block.
