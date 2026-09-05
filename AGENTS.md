# hep-agentic-pipeline — agent instructions (Codex / any coding agent)

Agentic LHC reinterpretation: published ATLAS/CMS analysis + hypothetical model →
MadGraph → Pythia8 → Rivet/SimpleAnalysis → pyhf → the signal-over-published-data figures +
a **95% CL exclusion** (CLs). Reference method: arXiv:2306.11055 ("Reduce, Reuse, Reinterpret" / mapyde).

## FIRST: route the session (before reading anything else)
- **PHYSICIST / ANALYSIS request** (reproduce / reinterpret / scan a mass plane / summary plot /
  "is this model excluded" / anomaly search — any natural-language physics ask, often prefixed
  "Initiate"): read **`docs/workflow/start.md`** and follow it. Do NOT survey the repo first.
  Every physicist-facing message follows `docs/workflow/checklists/check-ins.md` (plan check-in with a
  published-figure gallery + flagged assumptions BEFORE any heavy compute; captions on every figure;
  results as a concise deck; deviations flagged immediately).
- **DEVELOPMENT request** (improve/audit/fix this repo): read `DIRECTORY.md` (map) +
  `docs/development/status.md` (state) + `docs/development/history/mission-and-plan.md` (authority; mission/intent; current
  capability STATE = `benchmarks/capabilities.json`).

## Hard rules (identical to CLAUDE.md — the two files must never disagree)
- **95% CLs exclusion, never 5σ discovery** — never phrase any result as a discovery.
- **No heavy compute** (MadGraph/scans) before the CHECK-IN 1 plan is presented and approved.
- **Never invent physics inputs** (efficiencies, likelihoods, k-factors, covariances): fetch them
  (HEPData/paper/WG grids), declare them as flagged assumptions, or escalate to the physicist.
- Numbers quoted to the physicist must trace to artifact files (result/scan/exclusion/figures json);
  mid-run protocol changes go in the run's `DEVIATIONS.md` and their own check-in.
- Trial-run records (`trial-runs/2026-*`) are development evidence, not product examples.
- The workflow itself: `docs/workflow/README.md` → `docs/workflow/steps/01…09` → `docs/workflow/checklists/`.

## Skills
Reusable procedures live in `.claude/skills/<name>/SKILL.md` (the single source; Claude Code) and
are mirrored for Codex under `.agents/skills/<name>/SKILL.md` by
`scripts/maintenance/sync_skills.py` — never hand-edit the mirror. If your platform does
not auto-load skills, read the relevant SKILL.md directly when its trigger matches (each has a
`description:` trigger line). The procedures include: **physicist-intake** (ANY physics request → task
contract + CHECK-IN 1 + compute block — fire it FIRST), route-analysis, run-scan,
figure-contract, verification-panel, cost-preflight, run-stage, certify, new-analysis,
postmortem-capture, embed-and-commit, directory-keeper, evaluate-suggestion. The workflow steps
name the skill to use at each point; `check_agent_surface.py` asserts frontmatter + mirror parity.
