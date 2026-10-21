# Higgs decay input and output conventions

## Supply a model point and a format description

A schema-one model point contains `program`, `version`, `order`, `ew_scheme`,
`physics_inputs`, `parameters` and `scalars`. Its physics inputs explicitly include
`alpha_s_mz`, `mb_mb_GeV`, `mc_GeV`, `mt_pole_GeV`, `gamma_w_GeV` and `gamma_z_GeV`.
Additional masses, EW inputs, scales, model parameters and native flags come from
the complete input schema of the selected release. The common list does not
establish that a program-specific card is physically complete. Scalar rows give
`pdg`, `mass_GeV` and `coverage` (`complete` or `four_fermion`). Supply every physical value and native option explicitly.

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

All layouts explicitly state `unit: "GeV"`; record every unit conversion.
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

These general transport grammars require a source description and version-matched layout qualification. HDECAY's described `br.sm1`/`br.sm2`
filenames alone do not establish the column positions of a selected release.

The partial widths must sum to the stated total within `1e-6` relative, and each
branching ratio must equal its partial width divided by that total. Permutations
of the same daughter population are duplicates. One set records one program,
version, order and EW scheme; channels from another program are refused.

Prophecy4f produces a four-fermion sector. Its daughter populations have four
members and its ratios are normalized within that declared sector. A sector
width cannot be written as a complete scalar SLHA DECAY block or compared as
`Gamma_H`. Keep its sector widths separate from another program's complete decay set.
Exclusive physical channel mapping and interference treatment require primary
source review; the conservation test alone cannot establish them.
