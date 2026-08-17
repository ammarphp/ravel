# Stage 01 — Event Generation (MadGraph)

Produce **parton-level Monte-Carlo events** (a Les Houches `.lhe` file) for a requested physics
process, using MadGraph5_aMC@NLO. This is the first stage of the pipeline; its output feeds the
parton shower (stage 02).

## Two ways in
- **Drive it as an agent →** `agent/WORKFLOW.md` (minimal, step-by-step, general to any LO
  MadGraph process; decisions in `agent/checklists/`, a full example in `agent/reference/`).
- **Understand it as a human →** `docs/pedagogical-guide.pdf` (exhaustive tutorial + audit
  document, from first principles).

## What's here
| Path | Purpose | Track |
|---|---|---|
| `agent/` | minimal instructional workflow for an executing agent | agent |
| `docs/pedagogical-guide.tex` (+ `.pdf`) | exhaustive learning/review guide | pedagogical |
| `changes/` | registry of environment + data/card changes made | both |
| `inputs/` | the cards: process, parameter (pristine + normalized) | data |
| `scripts/` | the worked-example automation (00–03 + normalizer) | software |
| `example-output/` | a small, committed known-good result (LHE + banner) | output |
| `build/` | **local-only** (gitignored): conda + MadGraph + run outputs + logs | software/output |

## Quick run (worked example: slepton 200/150)
```bash
bash scripts/00_install_miniforge.sh
bash scripts/01_create_env.sh
build/tools/miniforge3/bin/conda install -y -n mg5 -c conda-forge six numpy
bash scripts/02_get_madgraph.sh
NEVENTS=1000 bash scripts/03_run_madgraph.sh run_02
```
Expected: 1000 events, inclusive cross-section ≈ 104 fb (0-jet Born ≈ 47 fb). Details and
sanity checks in `agent/reference/worked-example-slepton-200-150.md`.

## Adapting to a different request
Change the cards and run-card fields per the checklists in `agent/checklists/`. The procedure is
identical; only the values differ. The pedagogical guide's "Generalizing" chapter walks through
the decision process.
