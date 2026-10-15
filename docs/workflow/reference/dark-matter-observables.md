# Supplied dark matter observables

`ravel.physics.dark_matter` transports relic density, freeze-out `xf`, annihilation
channel fractions, proton/neutron SI and SD cross sections in `cm^2`, and a
present-day annihilation rate in `cm^3/s`. Scientific applicability and current
native qualification require the supplied model and the source-reviewed binding.
The integration fragments remain pending; this adapter has no standalone launch
command. This release does not include its toolchain group or its scientific mode;
both are held until the exact source release, licence evidence and current native
receipts are available.

## Prepare source inputs

Supply a request with `schema_version: 1`, a `study_id`, `model`, `parameters`,
`calculation`, `astrophysics`, and a selected `report`. The study identity is
metadata. Every parameter value, grid, source population and output filename is
supplied at run time.

The model records `id`, `format` (`calchep` or `ufo`), `candidate`, the complete
`particles` inventory (`name`, `mass_gev`, `odd`), declared
`coannihilation_partners` (`name`, `mass_gev`), `delta_m_fraction`, and
`coupling_conventions`. The threshold is the absolute partner mass difference
divided by the candidate mass. A declared partner within that threshold must be
in the particle inventory with the same mass and odd parity. Preserve supplied
portal-coupling normalizations; this adapter defines no new scalar convention.

`calculation` records a supplied `freeze_out` prescription, `today_velocity_c`,
`today_rate_definition`, and `channel_fraction_cutoff`. The rate definition must
state whether the result is a fixed-velocity value or a specified velocity
average. The native binding must implement that exact definition. Do not infer
an average from a single velocity calculation.

`astrophysics` records `local_density_gev_cm3`, the complete supplied
`velocity_distribution` object, and `density_fraction`. Limits must carry
matching conventions. `report` has a supplied safe `filename` and `format`
(`json` or `json-compact`). No named experimental curve or reference value ships
with this adapter.

A source decision records `tool: micromegas`, exact `version`, source `files`
(pins with path, size and SHA256), `licence`, `licence_sha256`, and
`redistribute: false`. The pins must map to that source tree. Download archives
belong under the supplied data root. The native installation recipe builds the
tool in its source tree with conda X11 headers and batch CalcHEP. It invokes no
GUI. Builds require the 25 GiB free-disk floor plus a declared build reserve.

A model build package supplies `model`, `files`, and `binding_files`. Its pinned
Makefile compiles RAVEL's `main.c` and `driver.h` with the supplied binding,
linking the tool through `MICROMEGAS_ROOT` and producing `main`. A UFO package
also supplies its source-reviewed external conversion recipe and inputs; model
Python is never imported by RAVEL. Cold staging is:

```bash
python -B -m ravel.physics.dark_matter prepare-model \
  --package supplied-model-package.json --data-root /absolute/data/micromegas
```

This copies authenticated files into a fresh per-model directory and stages the
RAVEL-authored transport template. It launches no converter or compiler.
Declare model compilation as a programme in a supplied `parameter-space-sampling` plan.
The supplied Makefile owns the native conversion and compilation. The ordinary
method decision, CHECK-IN 1 admission and existing science supervisor remain
required before that programme executes. Every build plan declares its temporary
build directories for cleanup and preserves its model inputs and failed logs.

## Execute through the scientific lifecycle

An execution config records `schema_version: 1`, `request` (pin), `tool`
(`root` and source `decision` pin), `model_files`, `binding_sources`, compiled
`binary` (pin), `resources` (`max_seconds`, `max_ram_mib`, `max_output_bytes`),
and `limits` (row/text pin pairs). The ordinary task is `{"config": PIN}`.
After dispatcher integration, construct the ordinary specification through
`dark_matter.specification` with the actual source, assumptions, actors and
finite budget. Use the established lifecycle:

```bash
ravel plan --rundir supplied-study --spec supplied-science.json
ravel approve --rundir supplied-study --quote 'The actual approval of this proposal'
ravel run --rundir supplied-study
ravel status --rundir supplied-study --write
```

Admission binds the selected mode, task and output directory. The compiled
binary receives the full staged request path and a fresh driver-output path.
The existing executor supervises its owned process group, wall time and RAM.
After exit, the adapter checks the complete ordinary output population against
the output byte ceiling, retains raw custody, parses the driver JSON, and
rechecks all input and returned bytes after report publication. The output-size
check is post-execution; wall/RAM supervision does not provide a live disk-write
quota. Bindings must keep intermediate output inside the admitted directory.
Dynamic-library closure and actual tool-version/particle/convention observations
require the queued native qualification; cold file presence does not prove them.

## Compare supplied references

Driver JSON uses `schema_version: 1`, `status: ok`, `candidate`, `mass_gev`,
`omega_h2`, `xf`, four `sigma_si_p_cm2`/`sigma_si_n_cm2`/`sigma_sd_p_cm2`/
`sigma_sd_n_cm2` fields, `sigma_v_today_cm3_s`, `channels`, and
`channel_fraction_remainder`. Each channel has a fraction and two incoming and
outgoing states. Fractions plus the declared omitted remainder sum to one.
Malformed, duplicate, negative, nonfinite, failed or inconsistent output is
refused; failed native files remain in the attempt.

Use `compare_reference(value, row, units=..., conditions=...,
relative_tolerance=..., text=...)` for a supplied qualification value. It verifies
the current qualification-row schema and extracted source text before checking
an explicitly supplied relative tolerance. Pending values are refused.

Use `compare_direct_detection(result, row, text=...)` for a cited exact mass
node. Its source row records `quantity: sigma-si-p` or the corresponding
interaction/nucleon, units `cm^2`, and conditions `mass_gev`, `interaction`,
`nucleon` and `astrophysics`. Preserve any additional source conventions in the
conditions. A mismatched density, velocity law or density fraction is refused
with both computed and limit conventions. There is no extrapolation or silent
halo rescaling. The ratio and `above_limit` flag are comparisons with the
supplied source; they are not a newly constructed likelihood or exclusion
confidence level.

The adapter delivers computed observables and source comparisons. It sets
`physics_validated`, `execution_authorized` and `original_task_complete` to false.
Native qualification, source applicability and scientific acceptance remain
separate evidence.
