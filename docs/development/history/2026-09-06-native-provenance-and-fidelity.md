# Original-event provenance and native fidelity follow-up

This revision makes native event identity explicit, preserves activated LHAPDF
toolchains, and reduces repeated validation work while retaining mutation checks.
It also publishes a second fresh RRR mass point and a direct investigation of the
generation-cut sensitivity. The physics reproduction remains incomplete.

## What changed in the implementation

### Exact original-event identity

A shower can legitimately remap particle masses, recoil and intermediate
representations. Matching an original hard event to a showered event by particle
order, a rounded momentum or a loose tolerance is therefore insufficient. The
new optional `original-v1` path records complete original LHA content while the
producer runs. It binds the sidecar to the original LHE events and the complete
new HepMC stream, including framing, event numbers and particle counts.

The implementation preserves the existing shower loop and does not replace the
event reader, change RNG calls, or retry a rejected event. It checks all original
fields, including signed zero and finite signed weights. Auxiliary event XML and
matching/merging modes outside this contract fail explicitly. Preserving signed
weights does not make a positive-weight estimator valid for them.

Original LHE input may be plain or gzip. The verifier binds decoded reads and
encoded hashing to the same opened file identity and rechecks the path afterward.
Independent review reproduced a parent-directory replacement that could otherwise
make those two operations refer to different files. The repaired code rejects it.
Successful outputs are published only after the owned producer exits successfully
and complete verification passes. Incomplete and failed records remain available.

This is an opt-in path for new shower output. It does not attach a newly invented
provenance record to old events. A separate historical replay can provide its own
identity evidence, as the completed RRR diagnostic does below. See the
[native workflow](../../workflow/reference/native-pipeline.md).

An isolated build and real 100-event exercise now complete through four supervised
stages: compilation, plain shower, gzip shower and final validation. Independent
review checks all original LHA fields and reaches complete decoded equality of
22,035,351 HepMC bytes, including 135,694 particle records. It also checks the
compiled library bindings and all four immutable receipts. This uses a retained
100-event subset and adds zero hard-event generation or full-native completion
credit. Its copied header is not an inclusive normalization measurement, and the
exercise does not compare against the original whole 1,000-event shower.

The first preparation stopped at the unchanged storage floor. A later admitted
attempt stopped before compilation because its local exercise helper listed both
library aliases and their resolved targets. The separate v3 helper retains all
510 logical source checks but declares 507 physical inputs once. Independent
review now exercises the real supervisor with the complete population. Earlier
failed protocols and logs remain intact. The production planner already resolves
and deduplicates these inputs; 96 actual populated dry-plan snapshots across eight
option/encoding combinations also pass. These are bounded implementation checks.

### Activated LHAPDF configuration

An explicit native option captures the actual compiler, linker flags, selected
LHAPDF library, architecture and complete PDF-set inventory. The generation
command uses that bound decision. It preserves applicable activation flags and
adds the selected C++ runtime only when required. Conflicting flags, unsupported
loader overrides, library drift and PDF-member changes are rejected.

This avoids modifying the installed MadGraph or LHAPDF toolchain to make a local
build succeed. The metadata command was exercised in the existing MadGraph
Python 3.10 environment. Source tests and a separate compile-only control do not
establish a completed generation campaign with the new PDF. An NNPDF control
still requires its own generated events and inclusive denominator. Details are in
[native portability](../../reference/native-portability.md).

### Validation work and campaign accounting

Validation now shares content hashes for the same physical file within one call.
Before returning, it rechecks file identities, directory membership, symlink
targets, the execution ledger, declared state, plans and runtime context. An
atomic replacement of the ledger cannot be hidden behind an already-open file.
No cache survives into a later validation call. This reduces repeated hash work;
it does not claim an atomic filesystem snapshot or a measured wall-clock speedup.

Campaign accounting now compares a child against its own canonical plan rather
than resolving a matching basename through the parent. That ambiguity interrupted
the fresh 100/98 workflow after generation. The original 20,000 events and failed
attempt were retained; a separately reviewed continuation completed the remaining
stages without regenerating or charging the same exposure again.

## What the new physics evidence establishes

The fresh 100/98 sample completes all twelve native stages and all six likelihood
roots. Its own four-state inclusive normalization gives 210.00 fb observed and
169.09 fb median expected, against released values of 238.13/203.96 fb. It contains
only 59 high-region and 11 low-region selections. The 13.02%/30.15% histogram MC
errors, 22 zero-selected channels and missing reference uncertainties remain
explicit. A valid root cannot supply missing MC precision or detector calibration.

The [matched statistical controls](../../../evidence/audits/2026-09-06-rrr-template-controls/README.md)
subsequently remove signal MC constraints, then additionally control-region signal.
Both omissions strengthen the limits and worsen this point's reference discrepancy.
The effects vary across expected quantiles and are not a common scale correction.
The public bundle includes exact small model inputs, every reported root, model
differences and sparse-bin precision. It distinguishes the complete new control
portfolios from the unavailable baseline portfolio. Its source-backed verifier
compares decompressed scientific input identities independently of local gzip
headers or encoding choices. CI runs both positive and adversarial admission checks.

For the separate 150/140 radiation-cut diagnostic, all 20,000 original lower-cut
hard events were content-joined. A supervised replay reproduced all 4,510,402,635
decoded HepMC bytes exactly. The independent reviewer checked original LHE and
sidecar identities while explicitly inheriting the producer's complete HepMC
byte traversal. The public bundle contains small verifiable projections of those
records; it does not distribute the raw event sample.

The below-50-GeV subset contributes 17 of 130 selected high-region events and
18 of 92 low-region events. Restricting to the complementary upper slice gives
selected-rate ratios of 1.227/1.016 against the independent nominal 60k pool.
The stated intervals, [0.982, 1.473]/[0.768, 1.265], do not establish equivalence.
These descriptive comparisons preserve the original 20,000-event denominator and
complementary moment covariance. They identify where contributions enter without
turning a generator cut into a fitted correction.

The [public evidence](../../../evidence/audits/2026-09-06-rrr-event-identity/README.md)
includes every one of the 40 displayed categories, all 147 native-region moments,
38 likelihood channels, missingness labels, figures and a standard-library
verifier. Its independent review closed seven admission gaps, including impossible
selected populations, replaced channel unions and deleted figure-source roles.
The original numerical data did not change during those verifier repairs.

## Verification and claim boundaries

The integrated native/LHAPDF/provenance checks passed 316 cases. Separate budget
checks passed 45 cases; public evidence and headline checks passed 73 cases.
These suites overlap and their counts are not added. A full staged run recorded
1,954 passes, 12 optional skips and four failures. Three isolated-worktree layout
failures were repaired and all 18 affected-module checks passed. The fourth
correctly required a new current fidelity audit for changed event-I/O source.
After the reviewed audit revision and filename repair, the publication checker
passes and the complete staged suite passes 1,980 tests with 12 optional skips.
Both installed-wheel cases use the candidate's freshly built wheel. These are
local source checks; public-export and remote CI results are recorded separately.

The completed native exercise and its independent output review are separate from
these unit tests. Its source/runtime bindings remain local evidence; this public
record summarizes the result without distributing a compiled binary or presenting
it as a clean installation test on another host.

Historical audits retain their original bytes. The revised audit distinguishes
inherited selection observations from checks of the new I/O implementation and
requires the original source and artifact roles to remain present. Neither an
updated checksum inventory nor unchanged function syntax constitutes a new
200,000-event reanalysis. CI explicitly runs the versioned audit's semantic
admission tests as well as its positive verifier; storing those tests beside an
audit does not automatically include them in the ordinary `tests/` collection.

The full fresh 52-point reproduction, truth-acceptance definitions, calibrated
detector/theory nuisance responses, merged-radiation validation and coverage remain
open. The close nominal 150/140 limit and the completed engineering tests do not
resolve them. The [current result board](../status.md) and
[validation results](../../validation/results.md) keep those conclusions separate.
