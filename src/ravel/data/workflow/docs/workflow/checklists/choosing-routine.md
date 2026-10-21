# Checklist — choosing and reusing an analysis routine · [judgment]

Goal: choose an event analysis and statistical representation that answer the
original question. Keep every requested observable, figure, model point and
comparison; an available routine or one successful component does not complete
the research task.

## 1. Discover existing source before constructing a routine

Use the installed offline census:

```sh
ravel analyses list --query "<paper identifier or topic>"
ravel analyses show <framework:routine>
ravel analyses check-source <framework:routine> --source <upstream-checkout>
```

Inspect the actual routine, metadata, paper and installed runtime. A paper can
have several routine variants. Catalogue membership, upstream `VALIDATED` status
and matching source bytes are useful evidence; they establish neither local
compilation nor applicability to the proposed signal, response or likelihood.
The catalogue (the shipped snapshot, or the one `ravel catalogue` builds from your checkouts) is a
discovery snapshot of the checkouts it read, not a restriction to previously exercised examples.

Reuse compatible upstream native source unchanged when it supplies the required
objects, selection and outputs. For catalogue Rivet source, the ordinary
`analyze` mode with backend `rivet` binds and builds that source. For a supplied
routine, including one absent from the catalogue, use the
[source-bound build and built-plugin route](../../reference/routine-build.md):
backend `routine-build`, then `rivet-built` with its observed build evidence.
The typed projection constructors cover a subset of Rivet's API; that subset
does not limit this ordinary existing-source route. Not every routine needs a
rewrite or a typed translation.

Choose the framework by event level, observable and response requirements.
Rivet source availability does not supply detector calibration or an experimental
likelihood. Other framework adapters retain their own explicit contracts and
runtime requirements; see the [scientific-study routes](../reference/scientific-studies.md).

## 2. Bind the complete event-analysis contract

Check beams and energy, process and decay content, event level, object definitions,
analysis options, response/calibration domain and any centrality or mixing
requirements. Preserve the whole source body and its required metadata, reference
binning, model files and other assets. Bind the actual compiler, plugin and runtime
dependencies rather than assuming an installed routine name selects the right code.

Declare every requested histogram, profile, counter and derived observable with
its axes, units, flows and normalization. Preserve ordered named weights, the
chosen nominal weight, original event groups and full exposure. An adapter that
lacks a required native output binding leaves that obligation open; a nearby
histogram is not a substitute. Compilation and registration qualify a source/API
step, not event physics, detector response or the paper's result.

## 3. Determine what the published inputs mean

Read actual table and column labels, plot annotations, booking source, paper
captions and provenance. A `/REF/` object or a `y01`/`y02` suffix does not identify
data or SM background by itself: column numbering is not a statistical model.
Check those meanings alongside the bin edges.

Distinguish observed counts, differential or normalized measurements,
efficiencies/cutflows, and prefit versus postfit predictions. A normalized shape,
efficiency or plotted noninteger value must not silently become a Poisson count.
For an inference task, obtain the full relevant SR/CR populations, signal
contamination, channel relationships, systematic variations, covariance and
auxiliary observations or likelihood. Keep missing information explicit and
acquire it through [data acquisition](data-acquisition.md); never infer a nuisance
law from an error bar, limit curve or simulation covariance.

## 4. Select the statistical family from that meaning

Use the existing ordinary [scientific-study lifecycle](../reference/scientific-studies.md)
and inspect the selected adapter's complete input contract. These are source
interfaces with separate execution and scientific validation requirements:

| Supplied representation or requested operation | Route and required distinction |
|---|---|
| Official HistFactory/pyhf workspace | `published-model`; use a signal-template successor only when every affected channel and variation is mapped to the supplied signal and its source assumptions. |
| Compatible native card or workspace | `native-likelihood` for its declared fixed evaluation, profile or saved-fit operation; retain the complete PDF, constraints, global observations and parameter domains. See [saved-fit diagnostics](../../reference/native-saved-fit.md). |
| Published HS3 model graph | [HS3 intake](../../reference/hs3-likelihood.md) for bounded import/evaluation. It does not automatically provide a fit or justify a template approximation. |
| Source-backed regional, transfer/ABCD or signed/interfering mean law | [Regional construction](../../reference/statistical-construction.md) lowers the complete supplied law to the existing native route. Disjoint-count and auxiliary-law assumptions must be supplied; this branch does not admit CLs automatically. |
| Alternative continuous or template background families | [Background construction](../../reference/background-model-construction.md) and `background-discrete-profile` retain all declared candidates on a common observation, auxiliary law and grid. Continuous exponential and template families follow their own source/domain contracts. |
| Measurement, normalized distribution, ratio or supplied correlated fit | [Quantity and measurement routes](../../reference/quantities-and-measurements.md), `continuous-fit` or [joint-fit](../../reference/joint-statistical-models.md), as applicable. Preserve the covariance, denominators, sampling law and fit domain; do not force a counting-limit interpretation. |

Do not combine overlapping analyses or turn marginal errors into independent
bins. Weighted or signed simulation needs its declared sampling model, including
unselected exposure and shared event groups; a covariance matrix alone does not
define the MC auxiliary experiment. If a route lacks a required construct, keep
the original inference obligation and propose a source-backed extension or a
discriminating experiment. A counting fallback is a new assumption to justify,
not the universal destination of every Rivet output.

## 5. Construct only the genuinely missing source operation

When reuse requires additional scientific inputs, retain the compatible original source and
add the missing operation explicitly. The
[particle](../../reference/rivet-particle-component.md) and
[shape](../../reference/rivet-shape-components.md) components feed native source
construction; [AgentRivet source delivery](../../reference/agentrivet-source.md)
is another construction route. Each must preserve the required selection,
normalization, assets and full output population. Unverified constructors can
remain supplied native C++ through the build route. Generated source is a
candidate for dependency review, compilation and event checks, not a certified
implementation of a paper.

## 6. Reuse validation within its demonstrated domain

Use [validation](validation.md) to compare the requested outputs with independent
references and retain failures. Record which source/runtime, model/process,
beam energy, decay/response/calibration, weights, normalization and observable
domain were checked. Reuse that evidence only where those assumptions remain
applicable and its commitments pass the current admission checks.

New model points do not inherit unconditional certification. Changed masses,
lifetimes, decay mixtures, detector response or inference laws can require new
inputs and qualification even when the routine code is unchanged. Preserve all
requested points and unresolved obligations, and record the chosen route,
assumptions, gaps and bounded next action in [CHECK-IN 1](check-ins.md).
