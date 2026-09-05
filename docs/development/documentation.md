# Documentation conventions

Choose a document's audience and purpose before writing it. Keep the root README focused
on what Ravel does, installation, one working first command, and links to the next task.
Use the [documentation index](../README.md) to route readers to detail.

| Location | Audience and purpose |
|---|---|
| `docs/workflow/` | Agents and physicists operating a run: intake, steps, decisions, and checks |
| `docs/reference/` | Users and maintainers checking interfaces, scope, supported modes, and limitations |
| `docs/validation/` | Researchers assessing measured outcomes and evidence boundaries |
| `docs/guides/` | Human learners reading preserved explanatory guides |
| `docs/research/` | Research comparisons, reviews, and prospective experiment protocols |
| `docs/development/` | Contributors maintaining the implementation and release process |
| `docs/development/history/` | Dated development records and earlier decisions |

## Operational instructions

Enter through [physics intake](../workflow/start.md), then use the
[workflow guide](../workflow/README.md), numbered steps, and checklists. Open detailed
instructions when their step is reached. Keep commands parameterized; identify worked
examples explicitly in `docs/workflow/reference/`.

State the action, expected artifact, failure condition, and recovery route. Explain enough
physics to make the decision correctly; put extended derivations and research arguments in
reference or research documentation. Mark the plan check-in and approval boundary explicitly.
Link to a maintained procedure instead of copying it into several files.

## Claims and history

Numerical claims belong beside their scope and evidence. Registered claim markers in the
[results overview](../validation/results.md) are checked by the publication gate. A historical
result must keep its date and limitations. A regression pass, cached acceptance result,
implementation comparison, and fresh physical reproduction are different kinds of evidence.

Keep original research artifacts and source/PDF guide pairs intact unless an edit is intentional
and separately verified. Label historical commands so readers use the maintained workflow for
current execution. Do not turn implementation plans into current capability claims.

## Names, links, and change records

Use lowercase kebab-case for Markdown filenames, except conventional entry points such as
README.md and platform-required SKILL.md. Python filenames use snake_case. Follow the
[layout guide](repository-layout.md) for folder boundaries and scientific-name exceptions.
Use document-relative Markdown links with the exact filename case. Public documentation must
link to public destinations; the export registry is not a browser redirect service.

Record environment changes in [environment history](history/environment-changes.md), and
card/data changes in [data and card history](history/data-and-card-changes.md), with links to
both the operational procedure and any explanatory guide affected. Preserve pristine inputs.

Reconcile [DIRECTORY.md](../../DIRECTORY.md) after layout changes, synchronize skill mirrors,
and run the publication and repository-hygiene checks. The public directory map is generated
from selected files; check the actual exported tree independently of the research checkout.
