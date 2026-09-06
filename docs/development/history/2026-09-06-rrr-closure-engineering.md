# RRR closure implementation and verified waypoint

This engineering checkpoint repairs several distinct failure modes exposed during the RRR
investigation. It includes a completed four-state 20k native waypoint and its portable small
likelihood artifacts. Scientific controls and the full mass-plane reproduction remain active.
A passing test suite or a close single-point limit does not certify physics reproduction.

## Numerical inference

The previous profile optimizer could return a successful status on an inconsistent branch.
The revised engine evaluates the original objective, bounds and projected gradients, rejects
non-finite candidates, compares bounded multistart solutions, checks profile nesting and
rechecks all six limit roots against a frozen candidate portfolio in two traversal orders.
MIGRAD fallback also has to pass these checks. Endpoints and unresolved roots remain explicit.
These finite controls establish numerical consistency within their scope. They are not a
proof of the global minimum or of frequentist coverage.

The previously failed retained 150/130 GeV template now resolves all six roots. Separately,
the fresh 20k 150/140 GeV anchor was checked with an independent NumPy objective and numerical-
derivative MIGRAD implementation. Eleven fits, including independent restarts, agree with
saved CLs values within 3.975e-8 at the tested observed and median-expected roots. Its original
failed boundary attempts remain retained; all attempts fit within the prospective ten-minute
control envelope. This independent control has not been applied to every scan point.

## Complete signal bookkeeping

The compressed-slepton adapter now supplies the six published control regions as well as the
32 likelihood signal channels. Leptons are jointly ordered before flavour-dependent control
selections. Every original event remains in a reconstruction trace, including rejected or
unsolved events. Signal conversion retains per-bin sumw and sumw2 and explicitly declares its
MC constraint. Empty selected bins remain precision unresolved; missing detector, ISR,
trigger and theory variations are not represented as measured zero uncertainties.

Independent replicas are pooled by original generated exposure, with squared coefficients
for their second moments and retained source/event identifiers. The reader verifies compatible
physics, independent seeds, complete ancestor receipts and original normalizations. Adding
independent replicas is distinct from summing different physical process components. A
reconstruction ancestry reader and a separate slepton-origin partition check preserve unknown
origins, signed parent pairs and original cross-section weights. They do not infer the origin
of a particular native-selected lepton from a raw reconstructed event overlay.

## Event production and execution

The native shower checks every setting, requested event count and serialization/close result.
Compressed LHE and HepMC transport preserves original bytes and rejects truncation, count
mismatch, broken framing and gzip integrity failures. The normalization parser now accepts
valid LHE generator metadata while retaining strict subprocess row accounting. A zero-parton
process with a positive jet-existence cut rejects before integration.

Complete-execution validation requires every declared stage and its matching receipt. The
older partial-resume API remains separate. Campaign accounting includes failed, running and
archived generation attempts at their original requested exposure, and pending child
reservations. Canonical paths prevent duplicate symlink artifacts and virtual-environment
configuration is included in interpreter identity. RISR serialization uses round-trip double
precision; a physical strict-boundary fixture exercises the earlier rounding defect. Existing
scientific runs and already active frozen binaries were not retroactively replaced.

## Waypoint evidence and scientific limits

The portable [20k waypoint bundle](../../../evidence/audits/2026-09-06-rrr-waypoint/README.md)
contains exact small likelihood operands, numerical outputs, recipe cards, signal/response
diagnostics and source pins. Its no-fit verifier checks byte integrity, denominators,
arithmetic and fixed-parameter likelihood identities. It explicitly distinguishes portable
small inputs from retained local raw events and producer receipts.

At 150/140 GeV, the independent 20k sample gives 48.83 fb observed and 54.69 fb median expected
on the declared four-state inclusive rate basis, versus 46.633 and 56.526 fb published. Its
reconstructed-fraction diagnostics remain roughly 11% low with 7%/8% own MC errors. Public
truth, dressing, jet and migration definitions and the effective normalization of the
released template remain incomplete. Detector working-point approximations and potential
compensation between nominal yield and uncertainty treatment remain under investigation.
The later 40k, six-state, pooled and paired-tag controls are separate local records pending
public curation; their existence does not upgrade this frozen bundle.

The historical 52-point numerical replay is also distinct from fresh physics. Its old
patches have 32 SR samples, no CR signal and no signal uncertainty modifiers. Five completed
refits preserve substantial signed residuals under their original conditional conversion.
Two original timeouts and 45 ready cases remain in the stopped batch denominator; a separate
once-only timeout retry phase retains the original failures. No repaired global contour or
complete fresh 52-point reproduction is claimed.

## Verification at this checkpoint

- Complete source unit suite: 1,475 passed, 12 skipped, 740.65 seconds. Ten skips require
  uproot; the other two require a supplied built wheel.
- Relevant native/ROOT suite in the installed Rivet environment: 230 passed, 17.36 seconds.
- CLI suite with a freshly built wheel: 40 passed, 49.63 seconds, including both isolated
  installed-wheel tests.
- Independent reviews additionally exercise likelihood minima, actual ROOT moments,
  origin accounting, source substitution, campaign reservations, current audit pins and
  physical selection boundaries. Their narrower checks are not added to the full-suite
  count as if they were disjoint tests.

Fresh native/statistical audits preserve their failed and unscorable scientific cases.
The broader nine-case benchmark still has two missing generated-YODA provenance failures.
Regression floors, acceptance certification and evidence availability remain separate.
Publication export and remote CI must be verified for the actual distribution commit.
