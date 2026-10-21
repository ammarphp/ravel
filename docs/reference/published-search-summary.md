# Requested published-search summaries

Use the `published-summary` scientific mode with task schema 2 to answer a request for a
summary plot of published search limits. The request declares a model, a process, an
experiment set and a mass window; each panel declares its basis. Schema 1 remains the
single-panel supplied-curve diagnostic and does not claim completion of the original task.

## Input document

The input document is `requested-published-summary/v2`. Its closed fields are
`schema_version`, `kind`, `parent_task`, `figure_target`, `search_census`, `panels`,
`source_assets` and `runtime_resources`. Every resource is an exact path and SHA256 input.
Each panel points to a schema-1 summary contract, which keeps its complete literal arrays,
units, source census and half-open mass-window rows. The whole input closure is at most
200 MiB, each source at most 16 MiB and each JSON document at most 1 MiB.

## Request declaration

`figure_target.request` holds:

| Field | Meaning |
|---|---|
| `model` | Requested model label, for example a benchmark model name or a coupling scenario. |
| `resonance`, `decay` | Requested process. The parent prompt names it as `resonance -> decay` or `resonance decaying to decay`; a `prime` suffix and `'` are equivalent. |
| `spin` | Optional nonnegative integer. When present, panels and eligible candidates share it. |
| `experiments` | Sorted experiment names. Each appears in the parent prompt, and every known collaboration the prompt names is included. |
| `window` | `lo_gev`, `hi_gev`, `upper_inclusive`. The nonzero bounds equal the parent task's `targets.masses_gev`. |

The parent task's `targets.model` binds `model` when the parser recorded one (a string or a
list); otherwise the prompt names the model.

## Panels and candidates

Each panel's `model_basis` has `model`, `resonance`, `spin`, `decay`, `production`, `width`,
`quantity`, `unit`, `energy_tev` and `branching_convention`. A panel carries the requested
process, its y-axis label states `[unit]`, and its x-axis label is in GeV. One panel carries
the requested model; alternative models and productions get their own panels. The rendered
schema-1 manifest has the same model, quantity and energy.

The search census lists one or more discovery operations per requested experiment. Every
discovered candidate has a disposition: `plotted`, `crosscheck`, `alternative_panel`,
`out_of_range` or `incompatible`. A candidate with the requested process that overlaps the
window gets a compatible panel. Different production, width or branching conventions stay in
separate panels; there is no acceptance or model conversion between them. A single in-window
sample is drawn as a marker, not an interpolated curve.

## Rendering and delivery

`summary_overlay` draws every panel with the `mplhep` house style of the first requested
experiment when the plotting library provides it, and the neutral ROOT style otherwise.
The header names the requested experiments and collision energies. The figure needs
source-pinned fonts, four-side inward major and minor ticks and the geometric lint.
Reviewers inspect the final PNG and PDF content as well.

The operation attaches one description-only primary synthesis target through the
`figure_target` lifecycle. It keeps per-source paper, version and figure or table
references, a source gallery, separate panel bases, output byte pins and task-fulfillment
evidence. It produces no combined collaboration figure, physicist verification stamp,
statistical combination, theory curve, uncertainty band or new limit.

The scientific worker gives this adapter a fresh `published-summary` child directory and
runs `science_figures` reporting, which checks the attachments and publication evidence.
Success is `delivered_pending_review`; source census, model applicability and task
completion are decided by the scoped review roles.
