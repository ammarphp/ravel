# Expected-only inference from a supplied regional law

`statistical_construction.write_native_bundle` and
`resonance_study.construct_regional` now support an explicit background Asimov
prescription. `mass_width_grid` carries the same prescription through its full mass/width,
SR/CR and source-response construction. The child remains the ordinary
`native-likelihood` operation with its existing supervised worker, runtime custody,
prospective review policy and independent result review. The ordinary worker performs the approved native fit after source preparation.

This capability needs the complete supplied background, transfer, signal response,
auxiliary law, physical domain and source/assumption pins. Supply integer observations, a complete background model and the declared auxiliary measurement or covariance. Paper-specific fit results require those complete source inputs.

## Data and conditioning

Add `expected_data` to the regional document (or the width law):

```json
{
  "kind": "regional-background-asimov/v1",
  "conditioning": "supplied_nominal",
  "point": {"mu": "0", "beta": "1", "ravel_aux_0": "1/2"},
  "source": "an_existing_source_id",
  "statement": "Source interpretation of this complete background generating state",
  "fit": null
}
```

`point` contains every physical parameter and every whitened `ravel_aux_i`
coordinate, as exact rational strings within the declared domain. The POI must be
zero with lower domain endpoint zero. Fixed parameters retain their source values.

- `supplied_nominal`: all original bin observations are explicitly `null`; no
  conditioning fit is performed. The point is supplied, not estimated from data.
- `fit_observed_background`: every bin contains a supplied nonnegative integer
  observation. `point` is the full fit start, with POI fixed to zero. Supply
  `fit={strategy, tolerance, max_calls, max_iterations, max_edm}`; tolerances and
  EDM threshold are positive rational strings, strategy is 0–2, and the two call
  bounds are integers at most 100000. The same ModelConfig NLL is minimized once
  using ROOT's RooMinimizer/Minuit2/Migrad followed by Hesse. Status 0, covariance
  quality 3, no invalid NLL evaluations, clean status history and the declared EDM
  gate are required. This implements the declared conditioning algorithm, not an
  assertion that it duplicates Combine's internal CascadeMinimizer fit or finds
  every possible optimum.

The supplied auxiliary factor defines physical nuisance coordinates
`theta = z + L eta` and the original auxiliary observation is `g_eta=0`.
At the chosen or fitted generating point `eta0`, the Asimov observation is
`g_eta=eta0`; the model still uses the same unit Gaussian for `g_eta | eta`.
Only parameter domains are finite; Gaussian observation support stays the full
real line. Original counts, global observations and all coordinate bounds/fixed
flags are retained before conditioning.

The constructed card uses explicit zero scaffolding when observations are null,
because the existing counting-workspace builder requires a count vector. This
file is labelled as scaffolding, never an observed dataset. The original ROOT
workspace survives unchanged. A separate `ravel_expected_workspace.root` contains
one complete unit-weight RooDataSet row of actual native count-function values,
which can be noninteger, and the generated global expectations. No rounding or
text-card decimal formatting is used to transfer those values.

## Supported inference family and command

The new route admits a source-certified nonnegative family
`lambda_i(theta,mu) = b_i(theta) + mu*s_i(theta)` with positive generating means,
nonnegative `mu`, complete SR/CR membership, and supplied nuisance correlations.
Admission checks every polynomial factor's sign on the declared rectangular
physical/auxiliary domain, excludes POI-dependent shape slopes and requires
nonzero signal. Signed interference, quadratic EFT
strength and nonmonotone responses use the
existing observed signed-profile route and need a separately specified interval
construction for expected inference.

The existing fit contract must specify `AsymptoticLimits`, `asimov_background`,
the same POI/domain, no grid, saved-fit or absolute-scan options. The admitted
native source/API is Combine 9.2.1 with ROOT 6.22/00. The command adds
`--run blind --picky --strictBounds --rule CLs --qtilde 1 --newExpected 1`.
The explicit prepared-dataset path defines the expected-data request. For the conditional branch, the workspace already
contains the independently retained conditioning result; `--run blind` prevents
a second, implicit observed-data conditioning fit. The asymptotic calculation
itself still performs native profile fits.

The five expected CLs endpoints are the 0.025, 0.16, 0.5, 0.84 and 0.975 quantiles.
A native observed row is refused. Finite, ordered, interior rows alone are not
accepted: the released bisection can return an uncrossed endpoint either near the
physical bound or near its provisional `median+4*sigma` bracket. Every reported
endpoint therefore gets three independently reset native nuisance profiles, at
its lower neighborhood, reported value and upper neighborhood. All five brackets
must straddle the source-defined CLs threshold. Bounds are never silently enlarged.
Expected bands describe the source asymptotic construction, not Bayesian credible
intervals, measured exclusions, toy calibration or proof of frequentist coverage.

## Actual crossing verification and optional bounded recovery

At the prepared generating point, each Poisson mean equals its Asimov count and
each full Gaussian observation equals its nuisance value. Thus every source NLL
term is at its minimum. This termwise argument supplies the reference NLL without
an extra fitted denominator. At each fixed strength the native worker starts from
the complete prepared coordinates, finite parameter ranges, fixed flags and
symmetric/asymmetric error state; it preserves the same data and global values.
It uses a fresh RooMinimizer/Minuit2/Migrad plus Hesse for any floating nuisances,
with strategy 1, tolerance and maximum EDM 1e-5, at most 50000 function calls and
10000 iterations per profile. If no nuisance floats, it evaluates the NLL directly.
Full raw fit results precede all status, covariance-population and finite checks.

For quantile p the checked statistic is `q=2*(NLL_profile-NLL_Asimov)` and its target
is `[Phi^-1(p)+Phi^-1(1-.05*p)]^2`, matching the released `newExpected` convention.
The native bracket radius is `max(.0005,.005*mu)+2^-23*abs(mu)`, the released
crossing resolution plus float32 transport rounding. Lower and upper q must lie
strictly on opposite sides beyond a declared numerical guard; the original
three profiles must be ordered. The host independently recomputes every q from
all source Poisson deviances and full Gaussian auxiliary terms. This is a finite
numerical profile check, not a rigorous numerical enclosure or proof of global
optimization, uniqueness, regularity or coverage.

Omitting `expected_data.crossing` selects `{mode: "verify_only",
max_profile_evaluations: 15}`. A failed original bracket then makes the operation
unresolved. A study can instead prospectively declare:

```json
"crossing": {"mode": "verify_or_refine", "max_profile_evaluations": 100}
```

The finite integer cap must be 16–200 and counts all original and recovery profile
points. For each failed endpoint this route first profiles the original physical
upper bound and requires it to cross; it then bisects from zero to that bound,
retaining every return. Strict opposite signs and the same resolution are required
for the recovered bracket. Near-threshold equality triggers two explicit nearby
profiles, never an assumed crossing. Missing domain crossing, exhausted budget,
unrepresentable grid, failed fit or unresolved numerical signs remains a retained
failure. The existing ordinary stage wall limit applies to this whole operation;
there is no hidden retry, larger domain or automatic budget extension. The study
must reserve these extra profile fits before approval.

`inference.quantiles` contains only qualified endpoints on a passed delivery.
`quantile_provenance` distinguishes verified original endpoints from bounded
native refinements. `combine_result` and `native-expected-combine-result.json`
preserve the complete original rows, quantiles, reference comparisons and success
flag. `rows` remains the literal original tree and is labeled accordingly.
`native-expected-crossings.json` retains original failed bracket diagnostics, every
profile and its raw fit pin, and all resolved bracket indices. Canonical reference
comparisons use qualified endpoints; the original comparisons remain available.
A recovered result preserves the unchanged upstream result and its original dataset and optimizer observation scope.

## Evidence and numerical limits

`native-expected-data.json` and `ravel_expected_preparation.json` retain the full
source request, original counts/globals/state, generating and final states,
actual count values and dataset readback. Conditional preparation also preserves
its complete native RooFitResult file and literal scalar, parameter, covariance
and status-history returns. The raw ROOT result is written before scalar checks;
nonfinite JSON evidence is explicitly tagged and causes failure. Complete outputs
remain present on failure. Exact prepared-file digests are fixed before inference
and checked afterward; changed evidence is refused, not regenerated.

The normal native probe reopens the separate workspace and checks the full
count-PDF/observable/region/role/POI linkage, functions, parameter domains and
Gaussian support. Combine 9.2.1 then **regenerates its internal nominal Asimov**
from this prepared state. The result records `internal_asimov_dataset_independently_exposed: false`; prepared-data readback retains its distinct dataset identity. Native analytic qualification must test the
resulting NLL contrasts and endpoints as well as preparation.

Profile-fit globality, detector/MC-law validity, asymptotic regularity and coverage require their own scientific evidence. Literal optimizer
warnings stay visible for reviewers. The new conditional raw fit has its explicit
diagnostic gates; AsymptoticLimits' internal fits retain existing log/row evidence
without inventing saved fit diagnostics.

## Source basis

The exact source package is authoritative for options and object semantics:
[Combine 9.2.1 AsymptoticLimits](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/src/AsymptoticLimits.cc),
[AsimovUtils](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/src/AsimovUtils.cc),
and [ROOT 6.22 RooMinimizer](https://github.com/root-project/root/blob/v6-22-00/roofit/roofitcore/inc/RooMinimizer.h).
The [Combine statistics guide](https://cms-analysis.github.io/HiggsAnalysis-CombinedLimit/v9.0.0/part3/commonstatsmethods/#blind-limits)
explains the nominal versus post-fit choice. The asymptotic method is described by
[Cowan et al.](https://arxiv.org/abs/1007.1727). These references establish method
and API provenance, not actual qualification of a supplied analysis.
