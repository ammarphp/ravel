# Capabilities

Choose a workflow from the resources available for the target analysis and the
validation it can support. The [scope contract](scope.md) defines the task modes,
required check-ins, and refusal conditions. The [limitations](limitations.md)
record current scientific and implementation gaps.

## Available interfaces

| Task | Interface | Meaning |
|---|---|---|
| Check a task contract | `ravel validate` | Validates schema and reference structure; grants no compute approval |
| Inspect the development surface | `ravel audit` | Diagnostic report about a source checkout and its available records |
| Reproduce or reinterpret an analysis | [Physics workflow](../workflow/start.md) | Plan, approve, execute the selected tools, then validate and review results |

Full physics runs use the native backend by default. Published selections,
likelihoods, efficiency maps, and validation references determine which analysis
route is defensible. An available engine does not establish that every analysis
using it is certified.

## Shape and template fits

Shape and template fits route to the scoped `shape_fit.py` engine (`stat_mode=shape-fit`), gated per analysis. Only an unrepresentable fit (unbinned / multi-observable / per-event NN) downgrades to the named `blocked-shape-fit` refusal + generator-level offer (docs/reference/scope.md §6.1).

The fit must meet the per-analysis validation requirements before serving a
physics result. Self-consistency tests and the existence of an implementation do
not replace a comparison with the published result.

## What the validation establishes

Statistical recovery, selection acceptance, native implementation parity, and
mass-plane agreement are different tests. Report each one's evidence and limitations
separately; a regression gate can pass while an acceptance certification fails.

The full workflow calls for source acquisition, explicit assumptions, reviewed
plans, and verification before delivering figures or limits. Its safeguards are
implemented through supported entry-point hooks and artifact checks.
These checks do not measure agent task success.
Whether an agent completes a request without guidance is a separate question that these checks do not answer.

## Refusals and scripted check-ins

A scope refusal names the missing capability and is reported as an unmet request, never as a
delivery, even when the refusal is scientifically justified. Record the missing capability and
an acceptance test for building it; the validity of the stop is assessed separately. The legacy
`served-with-refusal` inventory label receives no delivery credit, and partial inventory credit
describes existing components, not task success.

The `scripted_yes` approval mode answers each physicist check-in with a declared affirmative
response and must be authorized explicitly (`approval_mode: "scripted_yes"` and
`approve --scripted`). Its proposal and approval records are kept, the approval is recorded as
automated (`expert_review: false`), and it does not replace the physics-validity gates.
