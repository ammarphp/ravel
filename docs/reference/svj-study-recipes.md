# Supplied hidden-sector grid recipes

`svj-recipe` composes a supplied finite model grid, an explicitly selected analysis
package, response scenarios, and separately qualified generation/shower inputs.
It prepares unapproved child specifications, complete response covariances and a
record of every cell and unresolved input. It generates no events and performs no
fits. The original parent remains attached to every child.

## Ordinary lifecycle

Use a schema2 scientific specification with mode `svj-recipe`, task
`{"input":"/absolute/request.json"}`, the current closed review policy, and
`goal_binding` equal to the request's parent binding. Prepare it with
`ravel plan --rundir RUN --spec SPEC`; read `ravel status --rundir RUN --write`.
Each worker and each subsequent child requires the ordinary actual CHECK-IN 1,
method-decision admission, launch guard and source-qualified runtime.
Preparation grants no execution permission.

## Supplied request

The closed schema1 document contains `study_id`, `source`, `goal_binding`,
`analysis`, `axes`, `coordinate_constraints`, `points`, `response_scenarios`,
`background_scenarios`, `templates`, `generation_conventions`, three policy pins
(`generation_policy`, `analysis_policy`, `inference_policy`), `child_seconds`,
`assumptions`, and `delivery`.

- `analysis` supplies its `id`, positive `energy_tev` and `lumi_fb`, primary
  `sources`, `interpretation`, ordered fitted `bins` and `unresolved_bins`.
  Each bin maps `(id,channel,sample,index,role)`; role is SR or CR. Unknown
  populations remain located obligations and never become invented zero bins.
- `axes` is an ordered list of `{name,values}` vectors. The complete Cartesian
  product must equal the ordered point coordinates. Explicit
  `coordinate_constraints` lists `{axis,min,max}` bounds; an empty list asserts
  no additional recipe-level bounds. Every point carries its `id`, `coordinate`,
  and nullable `generation`, `shower_contract`, `analysis` and `response` pins.
- `generation_conventions.generation` explicitly binds `beam_pdg`, `energy_gev`,
  `order`, `scheme` and `jet_multiplicities`.
  `generation_conventions.shower` explicitly binds `backend`,
  `merging_scale_gev` and `max_jets`. These must agree with every supplied
  operative configuration. Missing conventions raise `SpecificationError` with
  `reason="missing_input"`; there is no implicit matching prescription.
- Response scenarios provide IDs, anchor coordinates and assumptions. Background
  scenarios supply nullable complete likelihood/response pins, an explicit
  anchor and assumptions. Joint background response bundles share the complete
  original cohort. Templates cover the full ordered point×response×background
  product, including blocked cells and their explicit MC interpretation.
- `delivery` chooses `{format,filename}` with format `json` or `tsv`. It is a
  presentation file in the fresh destination. The internal custody receipt and
  complete source-generated child files remain independently authenticated.

Resource admission bounds the request to 32 model points, 128 cells,
4096 expanded files and 200 MiB of source inputs. Generated members are bounded
individually and the complete successful delivery remains within 128 MiB.
These are engineering ceilings, never physical reference populations.

## Operative hidden-sector conventions

The paired shower contract contains `schema_version`, `parameter_bindings`,
`particle_mass_bindings`, `decay_fraction_bindings`, `visible_pdgs`, `settings`,
`particle_masses`, `invisible_pdgs`, ordered `decays`, `source_pins` and
`assumptions`. Parameter bindings explicitly map `{axis,block,codes}` to SLHA
operands. Mass and decay-fraction bindings explicitly map `{axis,pdg}` to card
masses and the complete invisible branching fraction of each active particle.
No particle identity, mass equality, coupling ratio or invisible fraction is
selected by the product.

Every operative HiddenValley setting and particle mass must agree with the
supplied card. Invisible daughters must be explicitly stable and invisible.
Each active particle must explicitly decay, initialize its ordered table with
`oneChannel`, have nonnegative branching fractions summing exactly to one, and
retain open invisible thresholds. The UFO, widths, fragmentation, tune, PDFs,
scales, seeds and runtime remain separately source-reviewed inputs. Matching
stability and physical applicability need executed qualification.

## Complete response and likelihood safeguards

`fixed_event_migrations` retains original event/group IDs, signed and zero
weights, rejected events, every destination and cross-anchor/cross-weight
covariance. No efficiency, detector calibration or trained tagger is inferred.
Hypothetical background anchors must agree with their all-bin likelihood totals
and preserve the supplied nuisance model.

A separate independent-bin template requires the explicit Poissonized-group,
fixed-denominator MC interpretation, diagonal within-cell covariance and exact
nominal/sumw2 parity in every fitted bin. Fixed-N, correlated, signed/cancelling
or shared-normalizer models remain complete and blocked from that projection.
Conditional prepared cells use the existing signal-template inference adapter;
its expected CLs quantiles and retained observed branch carry their existing
statistical scope. Calibrated response, sampling-law validity, convergence and
interval coverage require independent scientific review.
