# Session manual — run the pipeline in a fresh session

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

Self-contained: everything needed is in this repository — no external paper or reference is required.

## What it does
Given a published analysis (with a Rivet **or** SimpleAnalysis routine) and a new-physics model,
simulate the model and test it against that analysis's data: MadGraph → Pythia8 → analysis routine →
named comparison plots → HEPData/bundled data → a **pyhf** 95% CL limit — and, for the actual
deliverable, the **step-8 mass-plane scan → exclusion contour**, gated by the **step-9
verification panel** before anything is delivered.

## Prerequisites
- macOS / Apple Silicon, no admin rights, network access, a few GB free.
- The conda toolchain in the repo (`$RAVEL_NATIVE_BUILD/tools/`); if absent, step 1 of
  `docs/workflow/README.md` builds it.

## The prompt to give the agent
The RECOMMENDED form is the physicist entrypoint — paste into a fresh session in this repo:

> Initiate: **[your request — e.g. "reproduce Figure N of arXiv:XXXX.XXXXX", or "run
> <analysis code> on <model / spectrum>", or "what do <this class of searches> say about
> <a scenario>?"]** — cards attached / to be defined.

That routes through `docs/workflow/start.md`: the agent classifies the request into a machine task contract
(`route_prompt.py`), surveys WITHOUT generating, and sends **CHECK-IN 1** (published-figure
gallery, plan, cost estimate, numbered flags) — **no heavy compute until you approve**. Then it
drives `docs/workflow/README.md` steps 3→9: generation, the detector-fidelity gate, analysis, plots, data,
per-point pyhf, the **scan → contour** (step 8 — the deliverable for any
reproduction/reinterpretation, not a single point), and the **mandatory verification panel**
(step 9) whose verdict ships with the results deck.

A bare development-style prompt ("follow docs/workflow/README.md on analysis X / model Y") still works —
the agent must STILL send CHECK-IN 1 before generation, scan for the deliverable, and pass the
panel; those gates are the workflow, not the prompt form.

## Files the agent uses
| Path | Role |
|---|---|
| `docs/workflow/start.md` → `docs/workflow/README.md` + `docs/workflow/steps/` + `docs/workflow/checklists/` | the operational instructions (9 steps; check-in system) |
| `docs/workflow/reference/` | filled-in worked examples + the native-backend reference |
| `src/ravel/` + `native/` | the harness: intake and scan orchestration under `workflow/`, physics engines under `physics/`, figures under `plotting/`, gates under `validation/`, and compiled shower/RJR helpers under `native/` |
| `trial-runs/<run>/` | one isolated folder per run (RESULT.md + DEVIATIONS.md + RESUME.md) |
| `docs/workflow/analysis-simpleanalysis/` | SimpleAnalysis step 4B — **the native VM-free backend is the default** (`docs/workflow/reference/native-pipeline.md`); this container path is the legacy/general fallback |

## Swapping inputs
- **Different analysis:** pick another routine (`docs/workflow/checklists/choosing-routine.md`); the
  generation √s must match its beam energy.
- **Different model:** new process/parameter cards (`docs/workflow/checklists/model-cards.md`).
- **Different point / plane:** edit the masses in the parameter card, or give step 8 a grid spec.

## Success criteria
CHECK-IN 1 preceded all heavy compute; the deliverable (contour for a
reproduction/reinterpretation; labeled partial otherwise) exists under `trial-runs/<run>/plots/`
with stated coverage; the step-9 panel verdict is attached to the results deck; `RESULT.md` +
`DEVIATIONS.md` are filled. Run the `directory-keeper` skill at the end to keep `DIRECTORY.md`
current.
