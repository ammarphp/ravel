# Explicit nominal weight on supplied Rivet events

Explicit selection supports ASCII original stream names. Released Rivet converts
one byte at a time, while Python Unicode case conversion can change both characters
and length. Any non-ASCII original name therefore refuses this new naming protocol
without rewriting its bytes; the legacy route without explicit selection is unchanged.

An ordinary version2 `analyze` task with backend `rivet` or `rivet-built` may add
`"nominal_weight": "Weight"`. The name must match one original serialized weight
name exactly, including case. Metadata keeps its complete original `weight_names`
list and the HepMC file stays byte-identical. Do not put `Weight` first in metadata
unless that is the actual input order.

Omitting the field preserves the previous first-name default and result schema.
The explicit option currently binds the examined Rivet4.1.4 naming protocol; other
versions retain the legacy route until their naming behavior is source-qualified.
Empty/unknown names, ambiguous bracket/control suffixes and original streams that
native default `IRREG` filtering would drop are refused before execution.

The all-event census keeps every original sum, full ordered second-moment matrix,
signed and zero subevents and existing contiguous correlated-event grouping rules.
It additionally exposes the selected original index, its sum and second moment,
and negative subevent count. A zero selected sum cannot normalize the run, even
when auxiliary bookkeeping streams have nonzero sums. No sampling law is inferred.

Rivet4.1.4 preserves stream order, renaming the intended selected nominal stream
to the empty native label. Consequently its YODA histogram and RAW counter paths
have no weight suffix. Other streams retain their original `[name]` suffix, even
when they preceded the selected nominal in the original file. Reconciliation
requires the complete original counter denominator and every ordered moment.
Both compiled-source and receipt-qualified-plugin branches pass the explicit
`--weight-nominal` argument and retain it in `native-dispatch.json`, results and
plugin-reuse evidence. A dispatch declaration does not establish native effective
weights, capping behavior or physical normalization validity.

Native `AnalysisHandler::setWeightNames` also distinguishes the intended label
from its auto-detected normalization stream. Recognized `Weight`, `0`, `default`
or `nominal` names can supply that denominator even if a different custom label
is requested. The projection therefore records both selected and native
normalization indices and sums. It does not promise that the argument overrides
the source cross-section denominator. The caller still supplies and scientifically
justifies `cross_section_pb`; RAVEL does not derive it from bookkeeping fields.

The retained Sherpa2.2.8 manual identifies `Weight` as its named nominal stream and
describes `MEWeight`, `NTrials`, and `WeightNormalisation` as additional information.
The recovered boosted-ttbar release prefix has exactly that four-name population
in the order `MEWeight,NTrials,Weight,WeightNormalisation`. It is a source example,
not an eligible complete event cohort or generator validation. See the official
[Sherpa event-output documentation](https://sherpa.hepforge.org/doc/SHERPA-MC-2.2.8.html#Event-output).

A source-qualified native-group acquisition contract may carry the exact census
`nominal_weight_selection` object. Its `weight_mapping` must keep every original
stream in order and agree with all projected native names and RAW suffixes. The
unchanged acquired schema2 vectors, basis and moments keep the original logical
weight identifiers; the outer acquisition envelope transports the selection
record. This does not authenticate native execution, relabel auxiliary weights as
physical variations, or change downstream logical-nominal-first normalization
schemas. Those operations need their own explicitly source-bound transformation.

Required future qualification remains a complete input cohort, actual bound
Rivet/plugin execution, native labels/weights/YODA observations, current custody,
and own-role scientific review. The pure controls here provide implementation
evidence only.
