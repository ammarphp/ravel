# Full auxiliary pointwise calibration

`full-auxiliary-calibration` prepares and, after ordinary approval, executes a
fixed-truth repeated-sampling experiment on a complete supplied regional count
model. It uses the existing native likelihood transport and the unchanged
`regional_expected._profile_fit` implementation. The ordinary optimizer and scheduler retain their existing contracts.

Source and recording-facade tests exercise the declared transport and data contracts. Native ROOT behavior, fit quality, global minima and coverage require an admitted repeated-sampling study, resource reservation and review. The delivered quantities are fixed-truth profile-likelihood-ratio inclusion diagnostics and their failure-inclusive intervals.

## Supported source law

Start with the complete `statistical_construction` document described in
[regional-native-law.md](regional-native-law.md). Every SR and CR must have an
integer supplied observation, a strictly positive total mean, and a declared
disjoint Poisson count law. Signal, interference, background and shared nuisance
contributions all enter the total; nuisance sharing alone does not correlate
independent counts at a fixed truth.

Template statistics must be either conditional on supplied coefficients or the
existing `explicit_independent_poisson_auxiliary` construction. In the latter
case every MC bin remains present and its mean includes its declared exposure
and shared rate parameter. Fixed-N multinomial and signed-mark MC laws require
their own likelihood consumer and are refused here. Parametric shape terms and
an `expected_data` construction are also refused. The source-defined Gaussian
block is retained completely.

The model coordinates stay fixed: `theta = z0 + L eta`, including the original
`eta_bounds`. In unconditional auxiliary mode, the worker draws independent
standard-normal components and observes `g* = eta_truth + epsilon`; the physical
Gaussian measurement is `Z* = z0 + L g*`. Its covariance is therefore `L L^T`.
Globals can fall outside nuisance bounds without moving those bounds. MC
auxiliary counts are drawn from their full fixed-truth Poisson means. No nuisance
truth is drawn from a constraint PDF.

In conditional auxiliary mode, the original Gaussian globals (zero in these
source coordinates) and supplied MC observations are frozen. SR and CR counts
are still repeated. All constraint factors remain in both fits. This estimates
the explicitly conditioned experiment, rather than unconditional coverage.

## Input and ordinary workflow

Use `statistical_construction.write_native_bundle` with an observed schema-2
saved-fit configuration. Preserve that model, card and source population. Write
a separate prospective native configuration with an additional `calibration`
member. The inherited runtime contract remains complete: tool/module/library
pins, source version proof, environment and transport. This version supports the
reviewed ROOT `6.22/00` / Combine `9.2.1` regional API only. The source POI must
float. Its fit method is `MultiDimFit`, `data` is `observed`, `points` and
`minimizer` are null, and `saved_fit.maximum_edm` is `0.00001`. The saved-fit
configuration supplies admission metadata; calibration uses the existing RooMinimizer profile policy.

The additional member has exactly these fields; values below illustrate a
supplied contract, not a recommended cutoff or an executed experiment:

```json
{
  "kind": "regional-full-auxiliary-calibration/v1",
  "estimand": "pointwise_two_sided_profile_lr_inclusion",
  "source": "sampling-law-source-id",
  "statement": "Located justification of this fixed-truth repeated experiment",
  "truths": [{"id": "truth1", "point": {"mu": "1", "beta": "1", "ravel_aux_0": "0"}}],
  "trials_per_truth": 100,
  "auxiliary_mode": "unconditional",
  "seed": 971,
  "critical_q": "4",
  "confidence_level": "19/20",
  "numerical_margin": "1/1000000",
  "nll_absolute_tolerance": "1/1000000",
  "nll_relative_tolerance": "1/1000000",
  "reservation_seconds_per_toy": 10,
  "maximum_unresolved_fraction": "1/20"
}
```

`source` names an existing pinned construction source. Every truth must supply
every model parameter and every whitened auxiliary coordinate, in the original
bounds with fixed parameters unchanged. Exact rational strings preserve input
values. There are at most 32 distinct truths, 1,024 trials per truth and 2,048
scheduled trials overall. All generating means must be positive and no greater
than 1,000, the admitted scope of the finite Poisson generator. The proposed ensemble requires a separate precision assessment within these finite caps. The
confidence level must also remain strictly between zero and one in binary64,
and positive margins must remain positive after conversion. Admission refuses
underflow or endpoint rounding; it does not clip a supplied setting. The
unresolved-fraction criterion uses the exact supplied rational threshold.

The ordinary task is `{"input": "/absolute/path/to/calibration-native-input.json"}`.
Put it in an ordinary science specification with mode
`full-auxiliary-calibration`, complete prospective review policy and an outer
ceiling at least as large as the native `max_seconds`. Then use the existing
`ravel plan --rundir <new-study> --spec <specification>` route. Planning emits the bound sampling and fit contract. Existing approve/run/status/review steps remain required;
there is one original native wall deadline and no automatic retries.

For a source-only Graph context, call
`full_auxiliary_calibration.graph(task, base_dir, task_pin)` with the exact
`{path, sha256}` task commitment. The existing AgentHost action
`full-auxiliary-context` authenticates that task and the full dependency graph,
returns all truths/bins/auxiliaries/means/policy/resource declarations, and
performs zero draws or fits. The ordinary science plan remains the executable
handoff.

## Same-toy fits and retained evidence

Each scheduled slot is committed to a journal before any draw. Independent
component seeds derive from the master seed, truth ID, ordinal and component
name; failures and scheduling order do not move later random streams. The
journal retains seeds, Python/RNG version, all observations and physical Gaussian
measurements. The finite PRNG/Poisson implementation is part of the declared
numerical procedure; its source tests are not a calibration of ideal random
sampling.

The worker injects and reads back every count and global, including zero counts.
A clipped or missing observation makes that slot unresolved; it is never
redrawn. It creates a new NLL after injection, with the original nuisance and
global-observable options. Free and exact-POI constrained profiles share this
same immutable toy. Both start from the prospectively fixed source starts and
errors; no favorable truth-dependent nuisance start is substituted. A fixed
point with no floating nuisance is a deterministic NLL evaluation.

The unchanged profile helper requests Migrad and Hesse under strategy 1,
tolerance `1/100000`, at most 50,000 function calls and 10,000 iterations, and an
EDM ceiling `1/100000`. Two top-level profiles are scheduled per toy. Hesse,
fallback behavior and internal evaluations are additional work, so two is not
an optimizer-evaluation bound. Per-toy reservations determine whether a slot
can start; the existing outer native deadline provides termination. Actual
profile diagnostics and elapsed times are retained.

The host derives the full seed, generating-mean and physical Gaussian ledgers
from the immutable request/source and observed globals. It checks full censuses,
conditional freezes and strictly positive native truth/fitted means before
numerical agreement bands. A renewed observation hash must not authorize a
changed derived field. The native RNG law requires its own independent numerical evidence.

Raw RooFitResult files are written before diagnostic checks, and complete
binary64 coordinates, constants, bounds, covariance, statuses and full means
are retained. The source recomputes full Poisson-plus-Gaussian NLL contrasts on
the same toy and returned states. Additive NLL offsets cancel within that toy;
absolute values from separate invocations are not subtracted. The denominator
is the actual free profile, never an Asimov termwise minimum. Negative raw q,
failed diagnostics, source disagreement, changed state/data, or a q within the
predeclared cutoff margin remain unresolved with their raw evidence. Nothing is
clamped or silently dropped. Nonfinite failed-fit scalars are retained as
explicit markers in the same strict-JSON evidence returned by the callback and
written to its journal; they never satisfy a finite fit gate. Ending checks restore and compare the original
complete model/data/globals/errors.

The native command plan, logs, workspace/source probes, all raw fit files,
`native-work/ravel_calibration_journal.json` and `native-calibration.json` are
retained under the ordinary attempt. A failed native/transport/custody boundary
must not qualify provisional passes; the adapter retains a conservative full-N
failure audit plus any authenticated raw progress. The report exposes that
available conservative full-N audit while keeping the original failure status. A killed worker can leave a
partial journal, which remains failure evidence. The approved source request
still defines every scheduled slot even if no complete payload returns.

## Failure-inclusive report

At each fixed truth, q is `2*(NLL_fixed - NLL_free)` and inclusion is
`q <= critical_q` outside the declared numerical ambiguity margin. The cutoff
must be predeclared; tuning it on these same toys is a different procedure.
For N scheduled slots, K resolved inclusions and F unresolved or unissued slots,
the report retains:

- identification interval `[K/N, (K+F)/N]`;
- conservative binomial interval
  `[ClopperPearsonLower(K,N), ClopperPearsonUpper(K+F,N)]` at the declared level;
- full included/excluded/unresolved counts and unresolved-tolerance disposition;
- the resolved-only fraction, explicitly selection-sensitive;
- `0.5/sqrt(N)` as a Bernoulli Monte Carlo SE upper bound, which does not cover
  missing-fit uncertainty, optimizer error or dependence-law failure.

`calibration-summary.json` and `calibration-report.md` expose the complete
cohorts. A delivered diagnostic can contain unresolved slots. Ensemble adequacy, optimizer globality, simultaneous or uniform nuisance coverage, CLs calibration, detector modeling and physics acceptance each require explicit review and qualification evidence.
