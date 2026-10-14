# Dijet source law in full auxiliary calibration

`full-auxiliary-calibration` now consumes the existing `normalized_dijet` regional
construction through the ordinary `native_likelihood` executor. The constructor
and density law are unchanged: `q=m/sqrt_s`,
`log g=alpha log(1-q)+sum_j beta_j log(q)^j`, two through five ordered coefficients,
with source-defined correlated coefficient responses. Each observed bin uses its
window numerator divided by the integral over the entire supplied domain.
Missing windows retain unobserved mass. All declared SR, CR, MC and Gaussian
observations remain part of the original repeated-sampling law.

A dijet calibration request adds two required prospective objects to the existing
calibration contract. Exponential, power and unshaped requests retain their
original schema.

```json
{
  "reference_budget": {
    "admission_reserved_evaluations": 1000000,
    "toy_reserved_evaluations": 3000000,
    "validation_reserved_evaluations": 10000000
  },
  "reference_admissibility": {
    "fraction_of_existing_mean_band": "1/10",
    "fraction_of_existing_nll_band": "1/10",
    "fraction_of_existing_q_margin": "1/10"
  }
}
```

These example ceilings are declarations, not defaults or measured fit costs.
Each integer must be at least the sum of the per-term reference `max_evaluations`
limits and at most 100,000,000. Each accuracy fraction is an exact positive
rational no larger than `1/10`. Each explicit configuration validation, native
admission, toy or delivery-validation invocation creates its own local audit.
Framework calls can repeat configuration validation; there is no across-call
cache and no claim that one audit meters total framework CPU, I/O or wall time.
The native and ordinary outer wall limits still apply independently.

Before every actual source reference call, the audit reserves that term's whole
`max_evaluations`. A returned call retains the complete fractions, gradient,
estimated probability/gradient errors, evaluation/subdivision counts and exact
settings. A failed kernel keeps its reservation and an unknown consumed count.
A reservation refusal invokes no quadrature. Seven complete mean evaluations
are prospectively required for one toy's draw and existing closure path; a toy
with insufficient declared reference reservation remains unissued. Actual
kernel or accuracy failures remain unresolved; no slot is redrawn or dropped.

For each bin, the source mean uses the original signed term amplitude, including
monomial, full-domain yield/MC normalization and shared logarithmic response.
Its estimated quadrature contribution is `sum(abs(amplitude)*probability_error)`.
Opposite signs do not cancel estimated errors. Require the estimate below the
positive total mean and below the declared fraction of the unchanged
`1e-10*(1+abs(mean))` mean band. For an observed count `n` and estimated mean error
`e`, the Poisson NLL estimate is `(1+n/(mean-e))*e`; all bins are included. Fixed
and free NLL estimates add absolutely, and the estimated q error is twice that
sum. Those estimates must meet the prospective fractions of the unchanged NLL
contrast band and q ambiguity margin. They never enlarge a band, absorb a
native/source discrepancy, clip negative q or manufacture a physical uncertainty.

The reference uses adaptive Simpson/Richardson **estimates**, not certified
error bounds. Native RooIntegrator1D warnings can return unconverged estimates;
its maxSteps limits one integral, not an entire fit. Native quadrature/fit work
is not measured by the source-reference meter. Native convergence, optimizer
qualification and frequentist coverage require separate actual evidence.

Public preparation stays ordinary:

```python
from ravel.physics import full_auxiliary_calibration
packet = full_auxiliary_calibration.context({"input": "native-config.json"}, base)
```

The existing `full-auxiliary-context` Graph/Host action authenticates the complete
request/source/runtime input closure and returns this prospective packet. Use
ordinary `ravel plan` and subsequent workflow gates to execute. Preparation
creates no approval, toys, profiles, scientific review or acceptance.

The isolated worker stages an eight-member, at most 8 MiB source program,
including the exact `continuous_dijet_shapes.py` imported by the current
`statistical_construction.py`. It captures authenticated bytes before writing,
executes those buffers rather than a host fallback, and checks membership,
origins, hashes, ordinary paths and ending identities. Admission diagnostics are
adjacent binding metadata; they do not change the scientific response object.
The optimizer, sampler, seeds and all existing restoration rules are unchanged.

Native journal rows retain source-reference and accuracy audits. Delivery
validation has its own bounded audit and replays retained full reference
results; it does not rewrite the original journal. The ordinary adapter writes
`native-calibration-reference-validation.json` before each validation call so
failed reservations remain inspectable. Reported mean/error contributions,
coefficient identities, cost sums and declared unchanged bands are checked.
Numerical report comparison permits fixed 1e-12 relative roundoff (floor 1e-20);
it is separate from the unchanged scientific mean/NLL/q guards.
A failed ordinary native boundary retains the entire original scheduled
population and any authenticated raw journal; provisional fit rows never gain
reuse authority from that failure audit.

## Delivery diagnostic census

A delivered dijet calibration must retain every ordered admission truth, its
full-bin means, explicit `estimated_reference_uncertainty_is_certified=false`,
and the complete reference reservation/return and TOTAL-mean diagnostics. Each
resolved toy retains the seven source mean evaluations used by generation,
observation/native-truth checking, free/fixed fitted means and free/fixed source
NLL. Every shaped term and SR/CR/MC channel remains in that sequence.

The consumer checks reported adaptive counters against the source algorithm's
feasible bounds and the prospective per-call ceiling. It does not require old
runtime counters to equal a new host's adaptive traversal, rewrite raw reports,
or turn Richardson estimates into certified numerical or physical uncertainty.
Genuine failed prefixes may end during a kernel group or after a returned group
before a TOTAL mean is emitted. Their unknown failed counts, unresolved slots
and all unissued slots remain in the original full denominator. Failed and
unissued evidence is not substituted for a resolved delivery.

The copied package includes the original eight transitive source members, each
bounded by 1 MiB and together by an explicit 8 MiB limit. There is no cross-call
cache or native-integral/optimizer cost certificate. V1's erased-diagnostic and
false-certification admissions remain retained failed review evidence.
