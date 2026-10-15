<!-- Generated from the RAVEL role registry f40dbf8f991f96c069c979c80fd2cc443083667fdc9abd2baefd65aa10e66abb. Do not hand edit. -->
# Ravel — agent instructions

Ravel's immediate development objective is the strongest practical recasting platform across
LHC analysis families. Scientific-tool integrations, custom routines and fits, physics judgment
and effective autonomy belong to this phase. Source-backed method development through bounded
research experiments belongs to this phase. Dedicated new ML-training expansion remains later
work with its own prerequisites.
Implemented operations and validation remain limited to their source contracts and executed
evidence; a proposal establishes neither implementation nor physics validity.

Research should generate and test ambitious hypotheses. Missing prior evidence
does not by itself justify rejecting a direction. During ideation, critique should
produce better candidates or discriminating experiments; after execution, verify
what the evidence supports. Keep citation-led and speculative exploration active.

## Route the session first

- **New physics request** (reproduce, reinterpret, scan, summarize limits, fit or measure,
  calculate, study supplied events or models, study a search method, write up a result or draw
  diagrams): read `docs/workflow/start.md` and follow its route-specific intake. Do not survey the
  repository or launch compute before intake. The literal "Initiate:" prefix is optional.
- **Existing physics run**: rebuild its view with `ravel status --rundir <run> --write`, read
  `current_state.json`, and open the workflow step for its next blocker. Revalidate the actual
  contract, approval and execution evidence before acting. Do not reinitialize the run.
- **Development request** (improve, audit, or fix this repository): read, in order,
  `CONTRIBUTING.md` → `DIRECTORY.md`. Current adapter contracts and executed evidence define each
  operation's support.

## Hard rules

- Deliver the quantity the request asks for. RAVEL produces exclusion limits, fits,
  measurements, calculations and summaries of published results. An exclusion request that does
  not prescribe a statistic gets **95% CLs exclusion limits** by default. A prescribed statistic
  (an explicit formula, an Nσ region, a Δχ² threshold or a Bayesian credible interval) is the
  requested quantity: deliver it as the primary result, with CLs optionally alongside. An
  exclusion result is not a discovery claim. For other admitted operations, report the contracted
  quantities and their scope. Trace quoted numbers and figure claims to current artifacts,
  including numerical status and uncertainty limits. A cached regression pass, central-value
  agreement, and physics certification are distinct.
- No event generation, including a smoke run, or other heavy compute before the actual
  CHECK-IN 1 approval. Reuse a valid approval within its recorded scope; elapsed time is not approval.
- Never invent efficiencies, likelihoods, covariances, k-factors, or other physics inputs.
  Obtain evidence, flag a justified assumption, or escalate. Record protocol changes in the
  run's `DEVIATIONS.md` and the corresponding check-in.
- Preserve original scientific records. Use supplied cards and edit copies only, never the originals.
- The enforcement surface (settings, hooks, gate tools) is read-only during physics sessions;
  changes belong in development sessions. Use the supervised execution workflow for long stages.
- Keep operational instructions in `docs/workflow/` and teaching material in `docs/guides/`.
  Run directories under `trial-runs/` are local working state and are never tracked.
- Follow `docs/workflow/checklists/check-ins.md` for plans, numbered assumptions, deviations,
  and results. Apply `docs/workflow/checklists/plot-criteria.md` to figures. The model-tier and
  escalation rules for [judgment] steps remain in `docs/workflow/README.md`.
- Reconcile layout changes with the directory-keeper skill before reporting completion.

## Load on demand

Environment inventory and native provisioning: `docs/reference/environment.md` and
`docs/workflow/steps/01-environment.md`. Use the documented native path helper and conda environments,
and do not modify an installed toolchain without a reviewed environment change. Package/CLI use:
`docs/cli.md`. Generation, normalization and plotting rules: `.claude/rules/` when that stage begins.

Skills have one source in `.claude/skills/`; `scripts/maintenance/sync_skills.py` generates
`.agents/skills/` for Codex. Read only the matching skill and current workflow step. Never edit a
mirror by hand. After instruction changes, run sync and `ravel.validation.check_agent_surface`.
