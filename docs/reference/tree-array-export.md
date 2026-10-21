# Supplied tree-to-array export

Use science mode `tree-array-export` to export a supplied ROOT tree population to
raw arrays. `ravel tree-array-export inspect --task task.json` checks the contract
and commitments without decoding a tree. Execution remains the ordinary
method-decision, admission, plan, approval and supervised science-worker route.
The exporter provides no direct launch command, acquisition or installation.
NumPy, Awkward and uproot belong to the full Python installation.

The task has exactly `input` and `input_sha256`, binding the request bytes.
A schema-2 request has these required fields:

| Field | Contract |
|---|---|
| `study_id` | Supplied nonblank label; it never selects code or constants |
| `parameter_grid` | Explicit `axes` (`name`, `unit`) and ordered finite `points`, each mapping all axis names to numeric values; retained as study metadata, without replication or evaluation |
| `sources` | Nonempty list of supplied source pins, each with `path` and `sha256`; there is no installed source roster |
| `datasets` | Nonempty ordered list of `id`, `pin`, `tree`, `destination`, `format`, `consumer` |
| `layout` | Explicit `dtype`, ordered `columns`, `jagged_groups`, `padding`, `overflow` |
| `source_premises` | Explicit `units`, `ordering`, `weight_semantics`, bound to the supplied sources |
| `max_seconds`, `max_ram_mib` | Finite execution and allocation bounds |

Each dataset pin binds the complete local file. Identifiers and input files must
be distinct, including file aliases. `tree` selects the actual source tree.
`destination` is a canonical relative pathname within a fresh output directory;
file/directory overlaps and collisions with delivery metadata refuse. `format`
is `npy` or `npz`, with the matching suffix. NPZ contains the numeric `array`
member. `consumer` is a supplied logical association or explicit null; it is
recorded without writing to the consumer's directory.

The supported output dtype is `float64`. Each column has unique `name`, `kind`
and source `unit`. A `scalar` column also names its `branch`. A `jagged` column
names `branch` and a nonnegative positional `index`. A `constant` column has a
finite numeric `value`, or null for NaN. Every jagged branch appears exactly
once in `jagged_groups`, which declare corresponding fields with equal eventwise
lengths. The largest requested index in a group defines its exported object
shape. `overflow: truncate` retains the requested positional entries and
records each branch's dropped object count in `truncated_objects`;
`overflow: refuse` rejects a larger source object population. `padding` is a
finite numeric value or null for NaN. No multiplicity, branch or padding policy
is inferred. A schema-1 request relying on installed inputs must supply the new
contract; omitted required fields raise `MissingArrayInput` (`missing_input`).

All actual tree entries survive, including empty-object events. The exporter
checks complete requested branch membership and corresponding jagged lengths.
Source nulls, nonnumeric values, infinities and integer values not exactly
representable as float64 refuse. Source NaNs remain distinct from introduced
padding and constant NaNs in per-column counts. Raw signed weights and any
normalization branches remain separate source columns. No rescaling, sorting,
selection, physics calculation, preprocessing or training is inferred.

`layout` is either the inline object above or the identifier of a packaged layout template
(`ravel.physics.tree_array_export.layout_names()`); the request then carries the resolved
layout. Two templates ship, both over a published open-data ntuple format:

| Template | Columns |
|---|---|
| `atlas-opendata-13tev-diphoton-raw46` | 46 columns in the earlier producer's order: first two photons, two leptons and six jets as (pt, eta, phi) in stored order and NaN padded; `met_et`, `met_phi`, `mcWeight`, `SumWeights`, `XSection`; the two leading-photon tight-ID flags; the seven scale factors; two constant-NaN reserved columns |
| `atlas-opendata-13tev-lepton-jet-large-r-raw` | 39 columns: two leptons and four jets as (pt, eta, phi, E), the leading large-R jet as (pt, eta, phi, E, m), then missing momentum, weights and scale factors |

Both use `padding: null` (NaN) and `overflow: truncate`, and mark dimensionful columns as
source units because the public format page states none. A different population needs
only another layout, inline or packaged, plus explicit dataset destinations and
consumer associations; source-unit, ordering and weight conventions still accompany the
supplied source commitments. The same exporter handles a different population, grid,
layout and format without editing product code.

Delivery records the request, full dataset census, columns, shapes, NaN counts,
source premises, inputs and artifact pins. The canonical `completion.json`
binds every requested array, association file, delivery file and directory.
Finalization reopens the pinned request to derive the expected full roster and
rechecks authenticated completion bytes, source descriptors, ancestors, member
census, returned result and ordinary report. Reduced inventories and external
completion copies must not replace that roster.

`max_ram_mib` bounds the complete output allocation before branch reading.
Reader buffers, padded fields and serialization require additional peak memory;
real input supervision and measured qualification remain separate obligations.
Synthetic reader controls establish software behavior, not native reader
compatibility or scientific accuracy.
