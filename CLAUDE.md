# hep-agentic-pipeline — project instructions

Agentic LHC reinterpretation: from a published ATLAS/CMS analysis + a hypothetical new-physics model,
run **MadGraph → Pythia8 → Rivet/SimpleAnalysis → pyhf** to show whether the model would appear in that
analysis's data — the signal-over-data overlay plus a **95% CL exclusion limit**. Reference paper:
arXiv:2306.11055 *"Reduce, Reuse, Reinterpret"* (the **mapyde** package). Deliverable: a journal paper +
a public GitHub repo.

## FIRST: which kind of session is this? (route BEFORE reading anything else)
- **PHYSICIST / ANALYSIS session** — the prompt is a physics request (reproduce/reinterpret/scan/
  summary-plot/"is X excluded"/anomaly search; often but NOT necessarily beginning "Initiate"):
  read **`workflow/INITIATE.md`** and NOTHING else first. Do NOT read ORCHESTRATION/STATUS/DIRECTORY
  or survey the repo — INITIATE.md routes you; every physicist-facing message follows
  `workflow/checklists/check-ins.md`; **no heavy compute before the CHECK-IN 1 go-ahead**.
- **DEVELOPMENT session** — the prompt is about improving/auditing/fixing this repo itself:
  read, in order: 1. `DIRECTORY.md` (repo map) · 2. `framework/STATUS.md` (state board) ·
  3. `framework/PLAN-OF-RECORD.md` (authority — outranks any auto-summary; mission/intent; current
  capability STATE = `framework/capability-matrix.json`). Optional 4th, dev
  repo only: `ORCHESTRATION.md` (the historical session build-plan). This order is identical in
  AGENTS.md and asserted by `check_agent_surface.py`.

Only **files on disk + this CLAUDE.md + auto-memory** survive across sessions; the conversation does
**not** (unless you `--resume` that exact session). The three files above are the handoff.

## Hard rules (never violate)
- **NEVER edit the pristine original cards**: `$DSRLAB_ROOT/proc_card.dat`
  (md5 `110cbdf8…`) and `$DSRLAB_ROOT/param_card_200_150.dat` (md5 `8ec86d0f…`).
  Always work on copies. A `PreToolUse` hook enforces this (exit 2) — do not disable it.
- **Trial runs (`trial-runs/2026-*`) are NOT distributable** and must never appear as examples in the
  agent-facing docs (`workflow/`, `README.md`, `SESSION-MANUAL.md`). See `workflow/DISTRIBUTION.md`;
  the hygiene grep must stay clean.
- **Keep the three doc tracks separate**: operational (`workflow/`), pedagogical (`pedagogical/`),
  records (`trial-runs/*/RESULT.md`, `framework/`). Never mix pedagogy into the agent docs.
- **This tool sets 95% CLs exclusion limits, NOT 5σ discovery.** Never phrase a result as a discovery.
- **The enforcement surface is mechanically read-only during physics sessions** (settings/hooks/gate tools; the protect-enforcement PreToolUse hook, catalogue N9) — enforcement changes happen in dev sessions.
- After any task that changes the repo layout, run the **`directory-keeper`** skill before reporting done.
- No admin rights on this machine; everything installs into conda envs.

## Environment
- conda: `stages/01-event-generation/build/tools/miniforge3/bin/conda` — call as `<conda> run -n <env> …`.
- envs: **`mg5`** (MadGraph 2.9.27 + gfortran), **`rivet`** (Rivet 4.1.3, Pythia8 8.312, pyhf 0.7.6,
  mplhep, yoda), **`reinterp`** (SModelS 3.1.1, hepdata-cli, pyslha), **`recast`** (ROOT + Delphes +
  autotools + CheckMATE build), **`py82`** (Pythia 8.2, for CheckMATE runtime), **`pipeline`**
  (podman + mapyde). MadGraph binary: `stages/01-event-generation/build/tools/mg5amcnlo/bin/mg5_aMC`.
- The toolchain under `stages/**/build/` (~10 GB) and the heavy `trial-runs/` intermediates are
  **gitignored** and fully regenerable. The curation policy (single statement, mirrored in
  `.gitignore`'s trial-run block): TRACKED = `RESULT.md`/`DEVIATIONS.md`/`RESUME.md`, `config/`,
  `inputs/` (cards/specs/contracts), `logs/` (the evidence chain), `plots/`, curated result
  JSONs (`outputs/*.json` + the native `output/{exclusion.json,png,*.txt,*_patch.json}`), and
  hand-written `build/*.cc|*.py` sources; IGNORED = event files, procdirs, HEPData/figure
  fetches, feature CSVs, zips.

## Recurring gotchas (hard-won — do not relearn the hard way)
- `conda run … <<heredoc` does **not** pass stdin. Write the script to `/tmp/x.py`, then
  `<conda> run -n <env> python /tmp/x.py`.
- **`timeout` is absent on this macOS host.** Use background jobs (`run_in_background`) + poll a log,
  never `timeout …`. Long MadGraph/shower/build jobs always go in the background.
- **Run `trial-runs/_infrastructure/lhe_check.py` before showering** (masses vs intended, MODSEL,
  weights, merged-flag). For `MSSM_SLHA2` the `MASS` block is *overridden* by `MSOFT`/`HMIX`, and a
  **width-only DECAY table** (no BR rows) silently yields undecayed sparticles → empty SRs.
  Details: `.claude/rules/madgraph-pythia.md`.
- Multi-jet (≥4-jet) SRs need ME/PS **merging** or they come out ~30–40% low. Set `xqcut` explicitly
  with a keyed Python edit (a greedy `sed` silently misses), and verify `Events/` is non-empty.
- NLO σ via `nlo_xsec.py`: the HEPi EWKino grid is a **single charge** — compare like-for-like, expect
  k≈1.2–1.3 (k<1 is unphysical). Details: `.claude/rules/statistics.md`.
- Every figure must pass `workflow/checklists/plot-criteria.md` (incl. no axis-tick-label overlap).

## Where things are
- **Method** (agent-operational): `workflow/WORKFLOW.md` → `workflow/steps/NN-*.md` → `workflow/checklists/`.
- **Helpers**: `trial-runs/_infrastructure/` — `validate_cutflow.py` (tiered+attribution cert),
  `nlo_xsec.py`, `overlay_on_data.py` (mplhep), `pyhf_exclude.py`, `rivet_ref_yields.py`,
  `pythia_shower` / `pythia_shower_merged`.
- **Quality bar**: `framework/` — `STATUS.md`, `audit.py` → `AUDIT.md` (the readiness board), `validation/`,
  `crosscheck/`, `KNOWN-LIMITATIONS.md`. `framework/benchmark/` is the **built, green regression
  gate** (Session 1): `python3 framework/benchmark/run_benchmark.py --fast` (~7 s) per session,
  `--full` before/after any physics change; baselines + caveats in `BENCHMARK.md`.
- **Detailed domain rules** (loaded on demand by path): `.claude/rules/{madgraph-pythia,statistics,plots}.md`.

## Tools: when to use what
- **`/goal`** for convergent, checkable work only (e.g. "the benchmark fast gate passes", "every stage
  has a findings file"). Not for open-ended design or physics judgement.
- **Skills** (16; `.claude/skills/`, mirrored to `.agents/skills/` by `sync_skills.py`):
  physicist-facing — `physicist-intake` (ANY physics request → task contract + CHECK-IN 1 +
  compute block), `route-analysis` (routine/detector/stat routing incl. the 0-hit and
  no-routine paths), `judgment-protocols` (the eight operating protocols behind every
  [judgment] site + the physics trap-sweep T1–T12), `run-scan` (step-8 grid → contour),
  `figure-contract` (declare/extract/compose), `verification-panel` (step 9, both tiers),
  `cost-preflight` (budget before compute), `resource-sweep` (automated source-ladder census +
  the `--debug recipe-search` fix-finder); stage/process — `run-stage` (gen/shower/Rivet/native-SA idioms),
  `stage-recovery` (on a stage failure, diagnose locally AND recipe-search externally CO-PRIMARY, D8),
  `certify` (per-run `certify_acceptance.py` vs one-time `validate_cutflow.py`),
  `new-analysis` (scaffold a run dir), `postmortem-capture` (gaps → catalogue+registry),
  `embed-and-commit` (embed + register + commit), `directory-keeper` (reconcile
  `DIRECTORY.md`), `evaluate-suggestion` (adopt/adapt/defer/decline).
- **Subagents** (`.claude/agents/`): `stage-interrogator` (per-stage deep dive), `physics-reviewer`
  (adversarial physics check); the built-in Explore agent for fan-out search. Don't delegate work that
  needs the main thread's running context.
- Workflow steps tagged **[judgment]** follow the model-tier policy (`workflow/WORKFLOW.md`
  §Roles — binding): DEFAULT = escalate-to-physicist via a numbered CHECK-IN flag and wait;
  a site may instead name `script-assisted: <tool>` (run the named harness script) or
  `proceed-with-flag` (safe default + `DEVIATIONS.md` entry). A cheap model never silently
  takes a judgment step. **[agent]** steps may be delegated.
