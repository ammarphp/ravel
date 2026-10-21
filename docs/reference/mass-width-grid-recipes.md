# Supplied regional mass and width construction

`mass-width-grid` prepares every cell of an explicitly supplied mass × width grid.
It uses the existing regional construction, generation preparation, native-fit
preparation and ordinary science admission.

Use a version-2 ordinary science specification, mode `mass-width-grid`, matching
`goal_binding`, and task `{input}`. The pinned input is schema 2 with
`goal_binding`, `analysis`, `axes`, `cells`, `regional_input`, `native_runtime`,
`native_fit`, `review_policy`, `child_seconds`, `assumptions`, and `output`.
Missing analysis, grid, population or output contracts raise a typed
`MissingInputError`. Supply the study identity and complete grid explicitly.

The analysis supplies `id`, positive `energy_tev` and `lumi_fb`, `observable`,
resonance `pdg`, `references`, `missing`, ordered `region_ids`, and `generation`.
Generation declares `beam_pdg`, `energy_gev`, `initial`, `required_final`, and
complete `decay_channels`. Beam energies must sum to the declared collision
energy. Every source process must retain the declared initial and required final
particles. Operative cards must have exactly the requested mass and width, a
complete branching sum and the supplied decay-channel population. Responses and
generation use the same source-card bytes. These are supplied physical premises;
their physical qualification requires independent evidence.

Axes are `mass_GeV` and `width_over_mass`. Masses are positive; width fractions
are positive, distinct and increasing within the supplied domain. `cells` is the complete ordered Cartesian
product with `coordinate`, `generation_request`, `response`, and `missing`.

## Supplied observation and transfer law

A schema-1 law supplies `sources`, contiguous `windows`, `regions`,
`region_pairs`, `transfer`, `latent_rates`, `resonant_backgrounds`, `auxiliary`,
`template_statistics`, `partition`, `poi`, and `assumptions`. A source-bound
`expected_data` generating prescription can be declared. Each region specifies
`id`, statistical `role`, integer `observed` counts and `source`. Explicit
nominal expected-data construction uses null observations, never reconstructed
or rounded published counts.

Every region belongs to exactly one supplied `{id, tagged, antitagged}` pair.
`latent_rates` maps each pair ID to the complete per-window parameter population.
The shared transfer declares Bernstein `degree` (0–12), `domain`, `evaluation`,
`coordinates`, `coefficients`, `tag_efficiency`, `log_response`, and `source`.
Coefficient count is degree + 1; names and positive-domain rate parameters are
supplied. Point evaluation uses exact declared coordinates. `bin_average` uses
exact bin integrals and requires null coordinates.

For each supplied pair, the nonresonant means are

\[
 b_{\mathrm{tag},i}=\frac{\epsilon}{1-\epsilon}
   \left(\sum_j c_j B_j(x_i)\right)\nu_i,
 \qquad b_{\mathrm{anti},i}=\nu_i.
\]

The efficiency is supplied and strictly between zero and one. Shared auxiliary
responses remain on the complete ordered region/bin basis. Resonant components,
Gaussian factor and observation partition remain explicit. A postfit marginal
band establishes no prefit covariance or auxiliary experiment. Finite-MC
auxiliaries require a supplied applicable consumer.

## Response, exposure and output

A response supplies `schema_version`, exact `coordinate`, `sources`,
`observable`, `windows`, `region_ids`, `energy_tev`, `lumi_fb`, `normalization`,
`components`, `model`, `assumptions`, and `construction_metadata`. Its basis,
energy, luminosity, model and complete decay convention must match the analysis.
Selected weights and all nuisance responses retain every region and window.

Normalization declares `cross_section_pb`, `includes_branching: true`,
`generated_sumw`, `accepted_sumw`, `acceptance_definition:
accepted_over_complete_generated`, `efficiency_definition:
fit_bins_over_accepted`, `population`, and `source`. The cross section already
includes the declared branching fraction. Acceptance and efficiency enter once:

\[
 s_{r,i}=\frac{\sigma[\mathrm{pb}]\,1000\,L[\mathrm{fb}^{-1}]}
 {\sum_{\mathrm{complete\ generated}}w}\sum_{\mathrm{selected}\ r,i}w.
\]

A model declares its parameter-card pin, PDG, width scheme, explicit interference
hypothesis, `coupling_projection: none`, source and full `decay_channels`.
Neglected interference is a supplied assumption. Included interference keeps
signed contributions with the amplitude-strength law and a strictly positive
total mean. A strength result acquires no implicit coupling bound.

`construction_metadata` supplies presentation fields `model_id`, `question`,
`energy`, `luminosity`, `scale`, and `domain_statement`. These labels supply no
numerical input or physics authority. Preserve original labels when checking
migration byte identity; record truthful labels for a changed exposure.

`output` supplies `result: {filename, format}` (`json` or `json-compact`) and
`report: {filename, format}` (`markdown`, `csv` or `json`). Safe basenames must
differ. Every cell remains blocked, conditionally constructed or prepared;
missing science never becomes a zero limit. Derived files and input identities
are checked against intended bytes at completion. Report formatting changes no
physics or population.

Prepare the supplied specification with:

```bash
ravel plan --rundir <fresh-run> --spec <supplied-science.json>
```

Every generated study still requires the existing method-decision and admission
route. Resource limits remain: 128 grid cells, 60 law windows, 16 regions, 32
auxiliary coordinates, 512 metadata members/32 MiB, expanded generation closure
of 20000 members/16 GiB, and 64 MiB completed delivery. The regional constructor's
parameter, observation, term and formula bounds apply independently.
