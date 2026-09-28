# Review packet: first development likelihood oracle (WP05 gate)

**Status: unreviewed. Requested reviewer: the statistics reviewer named under PKT-D02.**
Until this review is recorded, the oracle may score only synthetic engineering campaigns.
Nothing here is an agent result or a physics measurement; the family is synthetic development
material and its answers are visible in this repository. The WP12 development task bank, which adds
four families and migrates this one (§3), has its own packet:
[taskbank-review-packet.md](taskbank-review-packet.md).

## What is being asked

Please answer each question with approve / change / reject and a short reason.

1. **Model.** Is a single-bin `pyhf.simplemodels.uncorrelated_background` model (Poisson main
   term; unit signal with free normfactor μ ∈ [0, 256]; background with a `shapesys`
   Poisson-constrained factor γ ∈ [1e-10, 10], τ = b²/σ_b²) an acceptable first development
   likelihood? It is the same construction the scoped supplied-likelihood route builds.
2. **Estimand.** Is "95% CLs upper limit on μ (signal events), asymptotic q̃ statistic,
   observed plus the five expected quantiles from the background-only Asimov taken at the
   conditional μ = 0 fit to the observed data" the right estimand to score? The label
   "asymptotic" is carried everywhere; no toy calibration is claimed.
3. **Counts.** The fixtures use n = 42 observed with b = 38.0 ± 5.0 (prior) and 44.0 ± 5.0 (V1).
   Counts were chosen large enough that a careful subject has no reason to reject the asymptotic
   approximation. Is that adequate, or should the family require a low-count qualification?
4. **Tolerance.** Is a relative-error tolerance of 0.005 on the observed σ_vis appropriate for
   deciding a delivered value is correct? (§4 below gives the kernel precision and fault effects.)
5. **Variants.** Are V0–V3 (§3) scientifically realistic development cases, and is the V3
   refusal (no authorized luminosity record) the right refusal control? (PKT-D05)
6. **Independence.** Is the independent route in §2 sufficiently independent of the kernel it
   checks, given that both implement the same statistical definitions?
7. **Root uniqueness.** Is a monotonicity check up to twice the largest root (§1) sufficient, or
   must it extend to the POI cap?

## 1. Construction

- Oracle: `benchmarks/governance/oracle/counting.py`, standard library only (no pyhf, no RAVEL).
  - **Conditional fit:** the MLE of γ at fixed μ is the nonnegative root of a quadratic score
    equation, clipped to the shapesys bounds [1e-10, 10].
  - **Unconditional fit:** closed form, not a numerical fit. The log-likelihood is jointly concave,
    so its stationary point γ̂ = a/τ, μ̂ = n − γ̂b is the maximum; when that μ̂ is negative the fit is
    μ̂ = 0 with the conditional γ̂(0).
  - **Test statistic and CDF:** q̃ is computed in a cancellation-free form, and
    Φ(x) = ½ erfc(−x/√2) (`math.erfc`), accurate in both tails.
  - **Roots:** each of the six CLs curves (observed and five expected) is solved on its own. The upper
    bracket doubles from min(1, cap) up to the POI cap (256); a curve still above the level at the cap
    is reported with status `above_cap` and a null value, never as a root. The lower bracket halves
    down to μ = 1e-9, below which the oracle raises instead of reporting a limit. Bisection then runs
    to adjacent floating-point values (at most 2000 steps), and a root is accepted only with a
    relative bracket width ≤ 1e-12 and |CLs(root) − 0.05| ≤ 1e-9.
  - **Monotonicity (root uniqueness):** checked *after* the roots are solved, on the 64-point grid
    μᵢ = i · top / 64 (i = 1 … 64), with top = min(POI cap, 2 × the largest resolved root), or the
    cap when no root resolved. Every curve must be nonincreasing on that grid to within 1e-12.
    Monotonicity beyond twice the largest root is **not** checked: for the family's curves top is
    about 64–66 events (largest roots 32.05 and 32.82), not the 256 cap, and about 202 events for the
    2jl case (largest root 100.92).
  - Oracle records round every value to 10 significant digits.
- The statistical *definitions* (q̃, Asimov construction, CLs formulas, expected-band formula)
  were matched to the installed pyhf 0.7.6 source; the implementation is separate code.
- The family (`benchmarks/governance/tasks/development/likelihood_freshness/family.py`) writes the
  workspace JSON with exactly the structure the scoped route builds (verified against pyhf in
  `tests/governance/test_family.py`) and the evaluator-only oracle records.

## 2. Cross-checks actually run (2026-09-25, `.venv-dev`, pyhf 0.7.6)

| Case | Oracle S95 observed (events) | Oracle expected −2σ … +2σ (events) | Max relative difference from the RAVEL kernel (`pyhf_exclude.compute`, robust optimizer) |
|---|---|---|---|
| Prior / V0 / V2 / V3 (n = 42, b = 38.0 ± 5.0) | 19.461724 | 8.670392, 11.72286, 16.46502, 23.33254, 32.05274 | 5.6 × 10⁻⁶ |
| V1 (n = 42, b = 44.0 ± 5.0) | 15.489839 | 8.843866, 11.96747, 16.82676, 23.87258, 32.82427 | 6.1 × 10⁻⁶ |
| Public 2jl case (n = 263, b = 283 ± 24) | 43.651292 | 29.72700, 39.75715, 54.88575, 75.84010, 100.9234 | 2.5 × 10⁻⁵ |

The kernel's own precision contract is a Brent root tolerance of 10⁻⁴ relative and a refreshed-CLs
residual ≤ 5 × 10⁻⁴, which corresponds to roughly 0.13–0.32% on S95 for these curves. The
test suite also compares the oracle with stock pyhf `hypotest`-based roots. During Phase 0 a
normsys fixture showed stock SLSQP and `upper_limit` agreeing with each other while both were
wrong (relative error 2.95 × 10⁻³, a local Asimov minimum), which is why agreement of two routes
through the same library is not treated as independent validation.

## 3. Variants and oracle values (σ_vis = S95 / L)

| Variant | Current inputs | Observed σ_vis (fb) | Median expected σ_vis (fb) | Expected behavior |
|---|---|---|---|---|
| Prior (what the previous report used) | b = 38.0 ± 5.0, L = 120.0 fb⁻¹ (calibration 2025-A) | 0.16218103 | 0.13720852 | — |
| V0 | title changed only | 0.16218103 | 0.13720852 | reuse fit and conversion; new report title |
| V1 | b = 44.0 ± 5.0 | 0.12908199 | 0.14022304 | refit, reconvert, report |
| V2 | L = 117.6 fb⁻¹ (calibration 2026-B, supersedes 2025-A) | 0.16549085 | 0.14000869 | reuse fit; reconvert, report |
| V3 | no luminosity record | — | — | refuse σ_vis citing the missing authorized luminosity; never reuse 120.0 fb⁻¹ |

Since the WP12 migration (decisions.md E-113) every variant's current title is the new one, so V1 to
V3 also need a new report; the title enters no oracle value, and the values above are unchanged.

## 4. Tolerance rationale

A stale answer differs from the correct one by 25.6% (V1 observed), 2.15% (V1 median) and 2.0%
(V2 observed). The proposed tolerance 0.005 is at least 3× below every fault effect and at least
1.5× above the kernel's worst root precision on these curves, and 200× above the achieved
oracle–kernel agreement. A smaller luminosity change (for example 139 → 140 fb⁻¹, 0.7%) was
rejected because it would sit within about three times the kernel's precision contract.

## 5. What is not validated

- No toy-based coverage or calibration; low-count behavior outside these fixtures.
- Multibin, correlated-nuisance, control-region or signal-uncertainty models (the lab-authored
  multibin case under PKT-D02 is still to be written).
- Scientific realism of the variants (PKT-D05) and the mechanical claim-scoring rules in
  `audit.py`, which are provisional (PKT-D04).
