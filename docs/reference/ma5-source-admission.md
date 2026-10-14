# Literal MA5 source configuration and SAF titles

`ma5_bookings.compile_source` admits literal Initialize bookings and direct,
standalone calls to `PHYSICS->mcConfig().Reset()`, `AddHadronicId`,
`RemoveHadronicId`, `AddInvisibleId`, `RemoveInvisibleId`, and
`PHYSICS->recConfig().Reset()`. ID arguments must be signed ASCII decimal
integers in the finite signed-32-bit admission domain. Duplicate insertions and
removal of absent IDs retain source set semantics, without an absolute-PDG
conversion. Calls retain source order; MC reset clears both sets.

When these calls exist, the booking declaration contains the exact
`physics_configuration` produced by the compiler and `configuration_sources`:
four `{path, sha256}` pins named `mc`, `rec`, `physics`, and `identification`.
The ordinary `ma5-saf` schema2 family and `ma5-pad` schema1 routes consume and
bind all four pins, require the finite supported API fragments, and compare the
configuration as typed JSON. A booking document without these operations retains
its original three booking fields plus source and scope; its schema is unchanged.

The additional configuration object contains:

- `operations`: ordered `{target, method, arguments}` objects.
- `mc_state_after_explicit_reset`: signed hadronic/invisible sets, or null when
  no reset establishes the initial state. Inherited state is never assumed empty.
- `rec_state_after_explicit_reset`: source reset defaults, or null without reset.
- `native_effective_configuration_observed`: always false in this source object.

Dynamic IDs, unknown configuration APIs, aliases, conditional/deferred/nested
calls and mutations outside Initialize are refused. The source compiler is not a
C++ interpreter and does not establish complete compilation, executable-source
correspondence, detector response or native runtime semantics. Other unsupported
booking families continue to refuse rather than omit outputs.

Quoted SAF titles may contain `#`. The source CounterManager writer quotes the
literal cut name and appends an unquoted `#` comment. The reader therefore removes
only comments outside quotes, preserving `#Phi` and trailing native comments.
Unsafe path/title characters and malformed quotes retain their refusals. Native
region filename cleaning remains the existing independently source-bound
`ma5_family.native_paths`; cut labels are not cleaned or ordinally remapped.

The PAD worker materializes absolute configuration pins at their original
booking-document base before reading its full SAF result. Its existing approval,
fixed supplied-event command, whole output census and result semantics remain.
No new runner, statistical engine or normalization is introduced. Native positive
and negative channels, unavailable per-bin variance/cross covariance, and unknown
scientific applicability remain distinct.

The real SVJ source case declares SR plus nine bins, 109 region-cut assignments
and no histograms. This is not the publication's full 36-bin fitted endpoint: 27
control-region bins remain unavailable in this recast source. Generated tagger
and smearer headers, native build/runtime/event response and complete physics
qualification remain separate prerequisites. A source-admission pass grants no
executed analysis coverage.
