# Fixed-truth calibration with continuous shape terms

The existing `full-auxiliary-calibration` science mode consumes the same
`native-likelihood` schema-2 input: its complete regional `model.construction`,
original observed data, runtime pins and explicit `calibration` request. There
is no separate shape-calibration engine. Use `full_auxiliary_calibration.context`
or its existing Graph/Host `full-auxiliary-context` tool to inspect the complete
fixed truth and scheduled count population; prepare an ordinary science plan,
then obtain the original Check-In 1 approval before supervised execution.
Preparation does not generate trials or fit anything.

`regional_calibration.means` and `source_nll` now consume admitted
`normalized_exponential` and `normalized_power` terms. The exponential convention
is proportional to `exp(c*x)` with respect to `dx`; the power convention is
proportional to `(x/a)^p` with respect to `dx` on a positive domain. Their exact
source schemas, full-domain normalization, correlated physical-coordinate
responses and numerical envelopes are the existing
[exponential](parametric-exponential-construction.md) and
[power](parametric-power-construction.md) contracts. The power kernel and its
whole-law lowering are a separately reviewed dependency. Unknown shape kinds,
including an unjoined dijet family, refuse; an input cannot provide a callback.

At every complete truth and returned fit state, the consumer computes the shape
parameter from the original bounded physical parameter and supplied Gaussian
factor `theta = observed + factor * eta`. Each background contribution is its
original polynomial/rate and log response multiplied by the full-domain window
fraction. Missing windows retain unobserved probability mass. They are not
renormalized into surviving SR/CR bins. Shape components remain nonnegative
backgrounds under the original construction validator. Original unshaped signed
interference, signal and control-region terms enter the TOTAL mean once; the
consumer does not invent independent Poisson draws for signed pieces.

The original count experiment and auxiliary conditioning remain unchanged:

- All disjoint main SR/CR observations are generated at the complete fixed
  parameter truth with their original component seeds and finite Knuth Poisson
  algorithm. The existing positive-mean/1000-mean scope still applies.
- Explicit independent Poisson MC normalization channels use their original
  shared rates and exposures. Conditional mode holds their supplied counts;
  unconditional mode draws them once. This does not replace weighted or
  fixed-total MC, infer a shape error or double-count a sample.
- Conditional Gaussian globals retain the original zero-centered observations;
  unconditional globals fluctuate around the supplied fixed nuisance truth.
  Physical auxiliary measurements retain the original correlated factor.
  Parameters themselves are never sampled from a constraint as a prior.
- Every scheduled trial remains in the denominator, including generation,
  optimizer, source-closure or ending-custody failures and unissued slots. The
  original cutoff, precision bands, bounds, seeds and reservations are retained.

The existing ROOT/Combine worker, optimizer, same-toy injection/readback and raw
RooFitResult retention remain the execution path. Shape workers additionally
carry a closed copied package containing the exact RAVEL package headers,
`statistical_construction`, `parametric_shapes`, `eft_functions` and `state_io`.
Ordinary intake binds every original member. The adapter captures each of the
eight bounded source buffers during the same admission observation, compares
its digest with the original input commitment, and writes those exact buffers
with those same commitments. It keeps this shape-package binding separate from
the original regional construction identity in `response_binding`.
The worker verifies the finite
package census and hashes, executes each authenticated source buffer without
rereading the pathname, verifies imported origins, and checks the sources again
at completion. Immediately before successful delivery, the host repeats the
complete closed package membership, path and byte check using the original
commitments; known-leaf hashes alone are insufficient. The checker repeats its
complete namespace census after all descriptor reads and imported-origin checks,
and compares every known leaf's ending identity with its authenticated read.
Changes during a later member read cannot hide behind the opening census.
These finite observations
do not lock the filesystem or certify absence of every transient change.
No host-installed RAVEL implementation supplies the native shape
law. Workers with no shape terms keep their existing helper staging and result
fields. Native Python/module startup compatibility remains an actual-runtime
qualification obligation.

The host admission comparison to `statistical_construction.mean_jet` and the
calibration source-NLL calculation share the same fraction kernels. They check
consistent composition; they are not independent numerical validation of those
kernels, ROOT evaluation or sampling coverage. Software controls use separately
written physical-x antiderivatives, zero-slope/logarithmic limits, full correlated
source laws, recorded facades and exact worker serialization. No observed
coverage, global optimizer guarantee, physics acceptance, calibrated interval
or exclusion follows from source preparation or those controls. Original
successful/failed receipts and acceptance bands are not changed.

C31 dependency join: the closed package also captures the current constructor’s
module-level `continuous_dijet_shapes` import. Each of the eight members remains
bounded at 1 MiB, with a closed aggregate of 8 MiB. It is a transitive source
dependency; calibration admission remains normalized exponential and power only.
The current dijet constructor, calibration reference law, sampler and optimizer
are unchanged. Real native calibration remains unqualified.
