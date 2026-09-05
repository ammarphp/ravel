# Ravel — agent instructions

Ravel supports evidence-backed LHC reinterpretation and bounded research planning. Its current
engines produce scoped exclusion results; a method proposal does not imply implemented training,
automated novel-method discovery, detector fidelity, or statistical calibration.

## Route the session first

- **New physics request** (reproduce, reinterpret, scan, summarize limits, or study a search
  method): read `docs/workflow/start.md`, then use the physicist-intake skill. Do not survey the
  repository or launch compute before intake. The literal "Initiate:" prefix is optional.
- **Existing physics run**: rebuild its view with `ravel status --rundir <run> --write`, read
  `current_state.json`, and open the workflow step for its next blocker. Revalidate the actual
  contract, approval and execution evidence before acting. Do not reinitialize the run.
- **Development request** (improve, audit, or fix this repository): read, in order,
  `DIRECTORY.md` → `docs/development/status.md` → `docs/development/history/mission-and-plan.md`.
  The current capability state is `benchmarks/capabilities.json`; dated plans and summaries do
  not override current artifact evidence. Load other development documents only as needed.

## Hard rules

- Report supported **95% CLs exclusion limits**, never a discovery claim. Trace quoted numbers
  and figure claims to current artifacts, including numerical status and uncertainty limits.
  A cached regression pass, central-value agreement, and physics certification are distinct.
- No event generation, including a smoke run, or other heavy compute before the actual
  CHECK-IN 1 approval. Reuse a valid approval within its recorded scope; elapsed time is not approval.
- Never invent efficiencies, likelihoods, covariances, k-factors, or other physics inputs.
  Obtain evidence, flag a justified assumption, or escalate. Record protocol changes in the
  run's `DEVIATIONS.md` and the corresponding check-in.
- Preserve original scientific records. In the DSRLab source workspace, the pristine parent
  cards `proc_card.dat` and `param_card_200_150.dat` are protected; edit copies only. Do not disable
  their protection hook. Use supplied cards in a public checkout.
- The enforcement surface (settings, hooks, gate tools) is read-only during physics sessions;
  changes belong in development sessions. Use the supervised execution workflow for long stages.
- Keep operational instructions in `docs/workflow/`, teaching material in `docs/guides/`, and
  records in `evidence/` or original development runs. Development trial records are not product
  examples; public evidence is curated under `docs/development/distribution.md`.
- Follow `docs/workflow/checklists/check-ins.md` for plans, numbered assumptions, deviations,
  and results. Apply `docs/workflow/checklists/plot-criteria.md` to figures. The model-tier and
  escalation rules for [judgment] steps remain in `docs/workflow/README.md`.
- Reconcile layout changes with the directory-keeper skill before reporting completion.

## Load on demand

Environment inventory and native provisioning: `docs/reference/environment.md` and
`docs/workflow/steps/01-environment.md`. The source machine has no admin access; use its existing
conda environments and native path helper, and preserve the installed toolchain. Package/CLI use:
`docs/cli.md`. Generation, normalization and plotting rules: `.claude/rules/` when that stage begins.

Skills have one source in `.claude/skills/`; `scripts/maintenance/sync_skills.py` generates
`.agents/skills/` for Codex. Read only the matching skill and current workflow step. Never edit a
mirror by hand. After instruction changes, run sync and `ravel.validation.check_agent_surface`.
