# Conventions — how documentation is organized in this repo

This repo keeps **two strictly separate documentation tracks**. Never mix them. Confusing the
two is the single most common failure when extending this project.

## The two tracks
| | **Agent track** (`agent/`, `shared/agent/`) | **Pedagogical track** (`docs/`) |
|---|---|---|
| Audience | an LLM agent executing the task (incl. low-cost models like Haiku) | a human learner / supervisor |
| Goal | reproducibly *perform* the task | *understand* and *audit* the task |
| Style | minimal, imperative, instructional ("set X to Y", "run Z") | exhaustive, rigorous, explanatory |
| Physics | none beyond what's needed to act | full, from first principles |
| Format | small Markdown files, nested | one LaTeX document (compiled to PDF) |
| Length | each file ≤ ~1 screen | as long as needed (a tutorial) |

If you are explaining *why*, it belongs in the pedagogical track. If you are telling someone
exactly *what to do*, it belongs in the agent track.

## Agent-track rules (for reliable low-cost-model execution)
1. **One entrypoint, then nest.** A stage's `agent/WORKFLOW.md` is a short map. Details live in
   `steps/` (one file per step) and decisions in `checklists/`. The entrypoint tells the agent to
   **open each file only when it reaches that point** — this is deliberate context management, not
   just tidiness.
2. **Instructional, not narrative.** Prefer tables, numbered commands, and "if X then Y". Avoid
   background, motivation, and hedging — those live in the pedagogical track.
3. **General, with one worked example.** Steps/checklists are parameterized (model/process/point
   are variables). Concrete values live only in `agent/reference/worked-example-*.md` and
   `example-output/`. Do not hard-code a specific physics point into the steps.
4. **Cross-reference, don't duplicate.** Link to the checklist or troubleshooting file instead of
   repeating content. Each fact has one home.
5. **Mark check-ins explicitly.** Where a human should confirm, say so in the step.
6. **Right altitude.** Enough to act, not so much that the model loses the thread mid-task. If a
   step file grows past ~1 screen, split it.

## Where changes get recorded
Any change to the environment or to data/cards is logged in the stage's `changes/` registry
(`ENVIRONMENT-CHANGES.md` or `DATA-AND-CARD-CHANGES.md`), with a workflow-level pointer (to a
checklist) and a pedagogical-level pointer (to a guide chapter).

## The directory map is authoritative
`DIRECTORY.md` (repo root) describes the intended layout. It is kept in sync by the
`directory-keeper` skill (`.claude/skills/directory-keeper/`), which must be run at the end of any
task that adds, moves, or removes files.
