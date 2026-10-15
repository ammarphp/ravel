# Higgs decay card and output contracts

`ravel.physics.higgs_decays` prepares explicit native cards and job descriptions,
consumes pinned supplied program outputs, and compares complete scalar decay sets
with supplied cited reference rows. Registration is delivered as the decay-program
fragment in `src/ravel/data/higgs/registration/`; scientific mode dispatch and
native stage binding require that fragment's integration. There is no direct
native launch in this module.

HDECAY, eHDECAY, 2HDECAY, sHDECAY, N2HDECAY, Prophecy4f, 2HDMC and FeynHiggs each
have an adapter identity. All eight programs belong to the required toolchain.
RAVEL does not import their native or GPL implementations. Native syntax comes
from version-matched, supplied format descriptions. No installed binary, pinned
manual, real output layout or native accuracy qualification is established by the
synthetic software tests. FeynHiggs execution awaits the scope-tools interface.

## Supply a model point and a format description

A schema-one model point contains `program`, `version`, `order`, `ew_scheme`,
`physics_inputs`, `parameters` and `scalars`. Its physics inputs explicitly include
`alpha_s_mz`, `mb_mb_GeV`, `mc_GeV`, `mt_pole_GeV`, `gamma_w_GeV` and `gamma_z_GeV`.
Additional masses, EW inputs, scales, model parameters and native flags come from
the complete input schema of the selected release. The common list does not
establish that a program-specific card is physically complete. Scalar rows give
`pdg`, `mass_GeV` and `coverage` (`complete` or `four_fermion`). No physical values
or native options are supplied by RAVEL as defaults.

The format document contains `schema_version: 1`, the same `program`, `version`
and `order`, `complete_input_schema_declared: true`, a `card` and a `layout`.
The declaration is an explicit supplier premise, not an independent manual
review. Both the format document and its primary format source must be pinned.

`card` gives an ordinary `filename`, `template` and a `fields` mapping. Flattened
field names are `physics_inputs.<name>`, `parameters.<name>`, `ew_scheme` and
`scalars.<pdg>.mass_GeV`. Each field appears as `${<field-name>}` in the template;
every supplied physical input, parameter, scheme and scalar mass must be consumed.
A numeric field is `{"kind": "number"}`. A discrete control or scheme is
`{"kind": "enum", "tokens": {"<supplied-choice>": "<native-token>"}}`.
Version-specific syntax, indices, enum encodings and calculation-order conventions
must come from the selected primary source. Changing populations, parameters or
native column positions changes supplied documents, never product code.

## Declare the output layout

All layouts explicitly state `unit: "GeV"`. RAVEL does not infer conversions.
Fortran `D` exponents are accepted; nonfinite values and numeric underflow are
refused. Filenames must be ordinary basenames distinct from cards/publications.

- `column_tables` has a `files` list. Each file gives `name`, `columns`,
  `skip_rows`, `mass_column`, `total_width_column` (an index or explicit `null`),
  and `channels`. Each channel gives `id`, daughter PDGs, `column` and `quantity`
  (`branching_ratio` or `partial_width`). The declared native quantity is
  transported unchanged and the other is derived from the stated total width.
  Indices are zero-based. Exactly one row
  per requested mass is selected; no interpolation is performed. At least one
  file supplies the total width, and repeated totals must agree.
- `key_values` has a `files` list. Each file gives `name`, scalar `pdg`,
  `separator` (`=` or `:`), `mass_key`, `total_width_key`, and channels with `id`,
  daughter PDGs, `key` and `quantity`. Repeated keys or missing quantities fail.
- `slha` gives `name` and channels with `id` and daughter PDGs. Native DECAY
  headers contain the total width, followed by branching ratios and explicit
  daughter multiplicities. When a MASS block is present, selected scalar masses
  must match the supplied point exactly. Complete SLHA export includes its
  masses. Duplicate blocks/channels and unmapped selected channels fail.
  Unselected scalar blocks are not merged into a requested set.

These are general transport grammars. No guessed program-specific column map
ships. A source description and real layout qualification are required before
using them as a certified native adapter. HDECAY's described `br.sm1`/`br.sm2`
filenames alone do not establish the column positions of a selected release.

The partial widths must sum to the stated total within `1e-6` relative, and each
branching ratio must equal its partial width divided by that total. Permutations
of the same daughter population are duplicates. One set records one program,
version, order and EW scheme; channels from another program are refused.

Prophecy4f produces a four-fermion sector. Its daughter populations have four
members and its ratios are normalized within that declared sector. A sector
width cannot be written as a complete scalar SLHA DECAY block or compared as
`Gamma_H`. RAVEL never silently inserts its widths into another program's set.
Exclusive physical channel mapping and interference treatment require primary
source review; the conservation test alone cannot establish them.

## Prepare cards or consume supplied outputs

A request JSON gives `schema_version: 1`, `action` (`prepare` or `parse`), pins
for `point`, `format` and `format_source`, and `publication` with supplied `json`
and `slha` filenames. A pin gives a regular `path` and its exact `sha256`.
Paths are resolved relative to the request document. `slha` is explicit `null`
for a sector-only JSON delivery. Original inputs and outputs are never modified.

For `parse`, supply `outputs`: records with `name`, `path` and `sha256` for
exactly the declared output file population. For `prepare`, supply `execution`:
`binary` (path/hash pin), an explicit `arguments` vector, `max_seconds` and
`disk_bytes`. Preparation renders the card and a job description in the requested
JSON; it launches nothing and produces no decay prediction.

```bash
python -B -m ravel.physics.higgs_decays transport \
  --request "$REQUEST" --base "$INPUT_ROOT" --output "$FRESH_OUTPUT"
```

The scientific adapter interface is `validate(task)`, `inputs(task, base)` and
`run(task, base, output)`, where `task` contains the request path. Its inputs
inventory includes point, format, primary format source, selected raw outputs or
binary, and implementation files. JSON carries input/output pins and explicitly
reports `physics_validated: false` and `layout_qualified: false`.

A prepared job's exact `command` vector and generated-card directory must be
bound to an ordinary supervised scientific stage. The existing
`ravel.workflow.launch_authorization.authorized_popen` interface requires the
method-decision record, scientific admission and current stage binding before
any native execution. A job description, supplier declaration or binary path is
not approval. Registration integration must preserve this boundary.

## Compare reference rows

Reference values enter at run time. The comparator accepts rows with `id`,
`channel`, `mass_GeV`, `quantity`, `value`, `unit` and `citation`. It also accepts
existing branching-row names `process`, `mass_gev` and `citation_key`; the caller
must resolve citation keys through the pinned reference-table reader. A total
width uses `quantity: "total_width"`, `channel: "Gamma_H"` and `unit: "GeV"`.
Branching ratios use `quantity: "branching_ratio"` and `unit: "1"`.

```bash
python -B -m ravel.physics.higgs_decays compare \
  --table "$DECAY_JSON" --reference-rows "$CITED_ROWS" --pdg "$SCALAR_PDG" \
  --channels bb tautau mumu cc gammagamma Zgamma gg WW ZZ Gamma_H \
  --output "$FRESH_COMPARISON_JSON"
```

The requested channel list is supplied and completeness is enforced. Per-channel
relative tolerances are 1.5% for bb, tautau, mumu, cc, gammagamma, Zgamma and gg;
3% for WW, ZZ and the total scalar width. The comparison selects one exact scalar
mass, rejects duplicate rows and incompatible units, and retains each failed
channel. Exit status is zero for numerical agreement, one for disagreement and
two for invalid inputs. Numerical agreement is not physics certification.
The current version-one reference schema has no total-width rows; a complete
comparison needs the supplied total-width row interface.
