# Native categorical observables

Both ordinary `rivet` and source-built `rivet-built` analyze tasks accept a
`native_categorical` observable. The ordinary public scientific plan, approval,
supervision and review lifecycle still applies. This is source/API transport;
no new native execution or physics acceptance follows from parsing a file.

Declare `quantity_kind: "native_categorical"`, `representation: "native"`,
`normalization: "absolute"`, the literal finalized object path and its unit.
Each axis has `name`, `unit` and `native_type`: `S` for literal strings, `I` for
literal integers or `D` for continuous geometry. String/integer axis units must
be `1`. At least one axis is categorical. A label such as `0.125` stays a string
category and is distinct from `1.250000e-01`.

The nested `native_categorical` contract pins a source excerpt and explicit
`source_dependencies`, each with path, SHA256, first/last line and exact text.
It declares `final_native_type`, all matching `raw_objects` with literal paths,
types, roles and units, `source_finalization`, `native_error_semantics`,
`flow_policy: "retain_all"`, `group_covariance: "not_supplied"` and a
`native_weight` name/suffix mapping. The latter is a declared, unverified mapping;
it does not establish which weights the native process actually selected.
Source files and the transport implementation enter ordinary scientific inputs.

Only the reviewed YODA 2.1.3 V3 typed serialization is admitted. One to three
axes retain first-axis-fastest ordering, categorical OTHER flow and continuous
underflow/overflow. Complete row counts, literal geometry, masks, final values,
signed labeled marginal errors, undefined tokens and declared RAW states remain
in JSON. The portable table explicitly shows masked and undefined states.
Categorical RAW histograms retain `sumW`, `sumW2` and `numEntries`; continuous
RAW moment columns and categorical profiles require further qualification.

No numeric-label conversion, widths, scaling, rebinning, normalization, covariance
or group moments are inferred. Whole observed native object inventory is retained
separately from requested objects; it is not by itself a proof of complete source
booking coverage. Published-reference parsing and mocked native namespace tests
are engineering controls, not new native event observations.
