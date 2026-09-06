---
name: stage-recovery
description: Recover a FAILED pipeline stage in hep-agentic-pipeline the D8-RESOLVE way — run local diagnosis AND an external recipe/fix search CO-PRIMARY (resource_census.py --debug recipe-search), never search-last. A diagnosed generator-model failure cannot be closed until a recipe_search.json exists. Fire the moment a stage exits nonzero (MadGraph empty SRs, undecayed sparticles, a shower/Delphes crash) or a stage_supervisor failure.json lands.
when_to_use: any pipeline stage failure (nonzero rc, empty/degenerate output, a logs/*.failure.json from the stage_supervisor); before writing off a stage as "the tool is broken"
allowed-tools: Bash, Read, Edit, Grep
---
# Skill — stage recovery (RESOLVE, D8): diagnose locally and search externally CO-PRIMARY

The failure this kills: on a diagnosed stage failure the external fix-search is ordered LAST (or never),
so a public recipe/UFO/restrict-card/known-fix that would repair it sits unexamined while the run
improvises. RESOLVE means the two branches run **in parallel, both first-class**.

1. **Record the failure.** `python3 scripts/run.py ravel.workflow.workflow_state record --kind failure
   --payload '{"stage":"<madgraph|pythia|delphes|...>","logfile":"logs/<stage>.log","failure_class":
   "tool_generator_model|other"}'` — this appends to `run_state.open_failure_records`.
2. **Branch A — local diagnosis (judgment-protocols P: discrepancy-decomposition / anchor-chain).**
   Read the stage log; check the known traps (SLHA width-only DECAY, model-dependent mass/mixing inputs, `xqcut`
   merging, env-trap generation outside the mg5 env — `.claude/rules/madgraph-pythia.md`).
3. **Branch B — external recipe search (CO-PRIMARY, run at the SAME time as A):**
   `python3 scripts/run.py ravel.workflow.resource_census --debug recipe-search --tool <tool>
   --model <model> --symptom "<symptom keywords>" --rundir <rundir>` — writes
   `inputs/recipe_search.json` (GitHub code search finds recipes hidden in recast run configs;
   INSPIRE finds theses/recasts). LOOK at the hits before concluding "the tool is broken".
4. **Close-block (mandatory for a generator-model failure).** You may NOT close a `tool_generator_model`
   failure until `inputs/recipe_search.json` exists:
   `python3 scripts/run.py ravel.workflow.resource_census --assert-recipe-search --rundir <rundir>`
   must exit 0. The Stop-dispatcher runs this at turn-end; a nonzero exit blocks the close.
5. **Apply + re-run + record the resolution** (postmortem-capture at run close): what the recipe search
   found, what fixed it, and a DEVIATIONS.md entry if the fix changed the plan.

Done = failure recorded, BOTH branches run, recipe_search.json present, `--assert-recipe-search` green.
