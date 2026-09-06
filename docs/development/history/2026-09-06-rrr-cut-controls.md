# RRR precision and generation-cut controls

The completed 150/140 GeV controls demonstrate why agreement with a published
limit must be checked alongside the stability of the simulated prediction. The
nominal 60,000-event pool gives observed and median expected limits within about
1.6% of the published values, while a lower generation cut changes the high-region
selected rate by about 41%. The latter fails the prespecified equivalence test.
No cut or physics parameter was selected to improve the observed-limit agreement.

## Completed evidence

The [control bundle](../../../evidence/audits/2026-09-06-rrr-cut-dependence/README.md)
contains four native results, three official-model nuisance controls, all 38
likelihood-channel comparisons, primary-region unions and four figure files.
It includes all six roots for each completed fit and commitments to the retained
failures. The 60k pool uses the original independent 20k and 40k samples; it is
not a third independent sample. Original-exposure coefficients and squared-weight
moments remain explicit.

The nominal pooled limits are 47.37 fb observed and 57.27 fb median expected,
compared with published values of 46.633 and 56.526 fb on the declared four-state
inclusive rate basis. The high/low primary-region own MC diagnostics are 4.03%
and 4.53%, meeting the unchanged 5% threshold. These histogram diagnostics do not
certify particle-level acceptance, detector response, likelihood coverage or the
remaining mass plane.

Changing only the leading-parton generation threshold from 50 to 20 GeV raises
the generated cross section by a factor of 2.230 and lowers the selected fraction.
The resulting high-region rate ratio to the nominal pool is 1.412, with a
conditional 95% interval of approximately [1.146, 1.678], including the printed
integration errors under the stated independence assumption. The low-region
ratio is 1.264 with interval [0.983, 1.545]. Neither establishes the prescribed
equivalence interval [0.9, 1.1]. Sparse channels remain unresolved, including
zero-count bins; no precision or covariance is invented for them. The nominal
50 GeV threshold matches the pinned reference recipe.

The three official-workspace fits hold nominal signal, background, observations
and control-region signal fixed. Removing non-MC signal nuisances strengthens
the observed and median limits by 4.63% and 5.88%; removing all signal nuisances
strengthens them by 6.36% and 6.52%. These isolate an effect within the official
model. They do not supply a correction to native yields, a calibration of native
uncertainties, or a shared cross-section normalization between the two models.

## Public verification

The bundle's standard-library verifier checks 24 native roots, 18 official
roots, 120 ratio calculations, units, complete populations, source relationships
and the exact 14-file public inventory. An optional source-root argument also
checks 105 selected original records and their deterministic public projections.
Neither mode reruns events or fits. The original raw files and full private
receipts are not shipped; hashes commit to them without making that unshipped
custody independently reconstructible from the public bundle.

Two new publication claims derive their values from the actual pooled limit
record and high-region comparison. Tests reject coordinated corruption of both
the prose and claim registry when the underlying evidence disagrees. The full
publication command invokes the bundle verifier and fails when that verifier
fails.

Independent review found and repaired two distribution problems in the tests.
Importing the immutable verifier could create unmanifested bytecode under ordinary
Python. The test now compiles its source into a module namespace without writing
a cache. The source-relocation control also assumed the private archive existed.
It now skips only when all private research originals are absent and fails on
partial private availability. The first actual export revealed that a public
predecessor manifest must not be treated as evidence of a private archive: that
run recorded 117 passes, one skip and one failure. The repaired nested public
checkout includes that predecessor manifest and exercises ordinary Python
without bytecode or import-path environment overrides.

The repaired source bundle module passes 65 tests. Before the final export
repair, a separate reviewer ran it together with the publication-scope module:
83 passed. After that repair, an independent copy of the actual public export
passes 64 bundle tests with one private-archive skip; a partial-private negative
control fails as required instead of skipping. The nested public-only test
records 63 passes, one private-archive skip and one self-recursion deselection.
These populations are separate and are not added into a larger independent-test
count. Both shipped PNGs were inspected after their final copy;
all four figure hashes match the independently reviewed originals.

## Open physics and execution work

The first pooled fit's one-hour timeout remains preserved. A separately reviewed
derivative reused the same event samples and completed under a prospective
90-minute cap. The fresh 100/98 GeV anchor generated its 20k events and then
stopped because allocation accounting confused the child's own pinned plan with
an incidental parent-plan pin. The reviewed continuation preserves both successful
stages, adds no generated events or reservation, and retains its original physics
commands and caps. It is not yet a completed result in this evidence bundle.

The next physics question is how much of the lower-cut selected rate arises
from the newly admitted hard-parton phase space and how much remains in the
shared domain. That event-level diagnosis must validate actual LHE/HepMC
topologies, event identity and original exposure before assigning contributions.
Parser rejections remain failed diagnostics until repaired and independently
checked. The cut control alone does not distinguish missing higher-multiplicity
matrix elements, shower behavior, PDF dependence or detector response. It does
not justify a visual correction to the residual map.

Full-plane reproduction, truth acceptance, detector response, signal systematics
and statistical coverage remain open. Their outcomes are not implied by the
software tests or the nominal one-point limit agreement.
