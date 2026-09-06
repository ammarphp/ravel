# RRR timeout, resource admission and export follow-up

The pooled 60,000-event derivative exceeded its original one-hour fit cap without
producing a final limit. Its timeout handler then raised a process-group permission
error and escaped before recording a terminal failure. The ledger incorrectly
remained running after the recorded supervisor and child had gone. The original
ledger, attempt, fit log and worker traceback were preserved before an explicitly
recorded transition to failed status. The timeout remains a failed numerical attempt.
Its pooled event moments are not an accepted likelihood result.

## Process cleanup

Cleanup now records signal delivery attempts, errors, bounded waits and an explicit
active-process census separately. It reaps its own exited child and still checks for
surviving descendants. Cleanup errors cannot replace the original timeout reason or
cause recursively repeated termination. A failed attempt whose cleanup is unresolved
blocks an automatic retry until a fresh census establishes no active group members.
The census excludes zombie entries; an empty active-member list does not claim that
every operating-system process entry has disappeared.

A bounded test on the actual Mac reproduced a relevant failure mechanism. Terminating
a newly created child without reaping it left a zombie, and a subsequent process-group
KILL returned EPERM. Reaping removed the entry. The matching Apple kernel source
filters zombies from group signalling and can return EPERM when no eligible member
is found. This supports the mechanism; it does not retrospectively establish the
unrecorded process state at the original pooled failure. See the
[matching XNU implementation](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.121.6/bsd/kern/kern_sig.c#L1703).

All 64 supervisor and execution tests passed, including real termination, surviving
descendants and interrupted-supervisor recovery. Three additional isolated checks of
the frozen execution runtime passed for normal exit, TERM timeout and a timeout that
required KILL. They left no active test-process groups. No scientific process was
targeted by these tests.

The frozen runtime preserves every v4 physics and inference byte. It changes the
supervisor and adds the reviewed campaign-admission module. Its exact file inventory
is checked before activation. An initial live-test harness omitted the inherited
no-bytecode environment flag: Python's `-B` flag alone did not propagate to a helper
subprocess, which created ten cache files. Those generated files were inventoried,
archived and removed before activation; all manifest source bytes were unchanged.
The corrected controls and launchers require `PYTHONDONTWRITEBYTECODE=1` as well as
`-B`, and reject unmanifested runtime contents, including bytecode.

## Prospective resource restriction

The source-bound storage forecast for the original allocation fell below the required
reserve. The campaign therefore registered a stricter effective ceiling of 1.26 million
events under the unchanged original 1.28-million-event upper allocation. The 52 nominal
points remain planned, with one fewer optional 20k control or top-up allowance.
Existing charges and reservations remain 104,000 events. This is an agent-selected
resource decision under the continuing task scope, not a numerical term attributed
to the user.

The admission helper checks the registered policy, all original parent-approval
bindings and the retained event charges. Future launchers pin the required policy
hash, so deleting both policy and registration cannot silently restore the larger
ceiling. Legitimate later attempts and reservations are added to the live inventory;
the historical inventory remains evidence of the restriction's starting state.

The forecast subtracts only the 81,000 fully completed native events from future
exposure. Existing retained storage is already reflected in free disk space and is
not subtracted a second time. The 30% margin, separate 10 GiB derivative allowance
and 60 GiB minimum reserve are unchanged. The revised snapshot left about 63.7 GiB;
each launch must recalculate it. Precision and equivalence thresholds were not relaxed.
The 38 focused admission/storage tests and 14 independent adversarial controls passed.

Five obsolete, inactive installation-test environments were inventoried and retired,
recovering approximately 0.21 GiB. Their original test records and wheels remain.
No raw physics product, active runtime, shared Python installation or shared tool/download
cache was removed. The separate test-bytecode reconciliation is recorded above.

## Physics procedure correction

An independent source study of the installed MSSM_SLHA2 UFO found the bino mass exposed
through MASS[1000022], with neutralino mixing supplied independently. The active rules and
card lint had generalized an earlier wrong-mass observation into a universal claim that
MSOFT/HMIX override MASS. That explanation is now explicitly model-dependent. The checklist
requires the imported UFO, restriction/cache inputs, mass/coupling dependencies, effective
cards and generated products to be checked. A supplied simplified-model spectrum remains
distinct from a newly calculated self-consistent MSSM spectrum. Inherited widths and
small-splitting decays retain their unresolved validation scope.

The generation step and its skill/checklist entry points also contained stale instructions
exempting lepton/monojet searches from merging and treating a historical 5% inclusive-rate
comparison as universal. They now refer to the existing source-backed merging checklist.
Radiation review follows the publication and recoil-sensitive observables; an unmerged
one-parton approximation remains explicitly distinct from the ATLAS merged prescription.
The native adapter's rejection of merged samples is unchanged. Raw HepMC retention follows
validation/dependency needs and the resource budget rather than automatic deletion.

These edits change guidance and warning text, not LHE parsing or any frozen campaign runtime.
Historical narratives remain preserved with an explicit qualification in the card registry.

## Public-checkout tests

The first exported archive passed its source/evidence review but exposed two test
environment assumptions. A signed-event test stubbed native execution without supplying
the inert resolver file now required for provenance. That test now declares and checks
its fixture hash. Hook tests had depended on both Git metadata and incidental writes
to the current checkout; they now exercise isolated Git repositories.

Review also found a real installer defect: failed Git-path resolution or writes could
still produce a success message. The installer now fails immediately and resolves
relative hook paths from the repository root, including invocation from a nested
directory. Tests cover separate Git metadata, relative custom hook paths, failed
resolution, failed installation and propagation of the actual checker exit code.
The 75 focused fixture/hook checks passed. Public validation must still initialize a
real Git checkout and install its hook for the unchanged G20 integration check.

The final complete source suite passed 1,533 tests with 12 optional skips in 475.71 seconds.
Publication and agent-surface checks also passed. A separate public candidate was then
initialized as a real Git checkout with the actual hook installed and its own wheel built.
Its complete suite passed 1,524 tests with 21 optional skips in 610.49 seconds. Both
installed-wheel cases executed and passed. The 21 skips are recorded in the test report;
they are not additional successful cases.

An independent review verified 837 selected bindings, all 111 files under exported
`src/` and `native/` against the committed source, the exact tracked export inventory and 72
entry-point links. All 38 frozen waypoint files remained unchanged. It also checked the
export for private home paths, including within compressed evidence. The failed first
stage, its five failures and the corrected second stage remain separate records.
These are locally verified candidate results; a public push and its remote CI result
must be recorded separately.

## First remote run and CI setup correction

The engineering update was published as `d1d635134ee80e19b76d344c72954f20ac4fc6cc`.
Its [first remote CI run](https://github.com/ammarphp/ravel/actions/runs/34019382010)
passed the replay, claim/evidence, adversarial-board, installed-wheel and both Mac
prerequisite jobs. The full test job recorded 1,520 passes, 23 skips and two failures.
Both failures were the same G20 integration check: the job had not installed the Git
hook. The isolated installer tests no longer supplied that incidental side effect.
The dedicated adversarial job already installed the hook and passed.

The test job now explicitly installs the actual hook before pytest. The G20 requirement
and its tests remain unchanged. This corrects CI setup, not physics or the tested Python
implementation. The failed run is preserved; a new remote run must validate the correction.

These engineering results do not establish full-plane RRR reproduction, acceptance
closure, detector calibration, nuisance completeness or statistical coverage. The
frozen public 20k waypoint retains its original scope. Later physics controls require
their own source-bound curation and scientific review.
