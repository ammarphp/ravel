# Amplitude-basis reweighting and measurement predictions

These modes predict how a differential measurement changes when new s-channel states interfere
with a continuum, for any coupling, mass, width and propagator choice, without generating new
events for each choice.

## Idea

When every hypothesis is a linear combination of a fixed set of amplitudes (the *basis members*),

    A(theta, x) = sum_k c_k(theta, s) a_k(x),

the squared amplitude at a phase-space point x, summed over helicities, is a quadratic form
c^dagger G(x) c. The coefficients c_k hold the couplings and the propagators of the partonic
invariant s. RAVEL stores the small Hermitian matrix G for every weighted integration point.
Any hypothesis is then evaluated afterwards, exactly, at the same points.

A hypothesis is data:

```json
{"id": "S600", "constant": {"continuum": 1},
 "states": [{"mass_gev": 125.0, "width_gev": 0.0041, "propagator": "fixed-width",
             "couplings": {"scalar_bottom": 1, "scalar_top": 1}},
            {"mass_gev": 600.0, "width_gev": 60.0, "propagator": "running-width",
             "couplings": {"scalar_top": [0.4, 0.0]}}]}
```

Couplings are real numbers or `[real, imaginary]` pairs. Propagators are `fixed-width`,
1/(s - M^2 + i M Gamma), or `running-width`, 1/(s - M^2 + i s Gamma/M).

Points with identical leptons use a pairing partition built from a fixed reference amplitude,
so every hypothesis stays a quadratic form and the estimator stays unbiased.

## Workflow

These modes read a supplied amplitude store: per-point records in independent equal-exposure
blocks, each checked against the producing program's own squared amplitudes before it was stored.

1. **`amplitude-predictions`** turns the store into binned predictions. The bin edges (literal
   or read from a HEPData table), point-level cuts on stored observables, the representation
   (integrated or differential) and any cited normalization factor are supplied in the
   document. It writes one `binned_values` result per stream, the joint block covariance and
   the input of a `differential-likelihood` document.
2. **`weighted-events`** writes the stored points as HepMC3 or Les Houches events with one
   named weight per hypothesis and per difference to the reference. Through the execution
   backend it runs an optional shower and any Rivet routine, then normalizes the RAW
   histograms by the attempted draws of each block.

`ravel amplitudes example --mode <mode>` prints an example document,
`ravel amplitudes check --mode <mode> --input doc.json` lists its inputs, and
`ravel amplitudes spec ...` writes the study specification for `ravel plan`.
Computation always runs through `ravel plan`, `ravel approve` and `ravel run`.

## Spin-0 members

`spin0_amplitudes` adds gluon-fusion spin-0 states decaying to four leptons:

- production through the exact quark-loop form factors, with scalar (CP-even) and
  pseudoscalar (CP-odd) Yukawa couplings for any declared quark mass;
- decay through the g1, g2 and g4 terms of the spin-0 ZZ vertex (g4 is CP-odd).

The amplitudes are numerators: the propagator comes from the hypothesis. Every constant
(alpha_s, v, Z mass and width, lepton couplings) is a required input.

Phases of helicity amplitudes depend on spinor conventions. Before spin-0 members join amplitudes
from another program, a closure fit must reproduce that program's own CP-even amplitudes at the
same points with one factor per helicity (`spin0` in the document that produced the store). The fit fails
if the ratio is not constant.

Useful exact properties:

- a scalar and a pseudoscalar never interfere after the gluon-helicity sum;
- a CP-odd decay term interferes point by point with the CP-even one, but cancels in
  CP-symmetric observables such as the four-lepton mass;
- a continuum has independent (++) and (--) gluon amplitudes, so it interferes with both.

## Coupling polynomials

With `coupling_scaling`, the listed states scale as kappa^p. Each difference to the reference
is then written exactly as a constant, an interference term (kappa^p) and a pure-signal term
(kappa^2p). The `differential-likelihood` input carries these terms with their powers. The width
stays as declared while the coupling scales.

## Normalization of signed streams

Rivet routines usually scale a histogram by crossSection()/sumOfWeights(). That is wrong for a
signed stream such as an interference or a difference. Event weights here are absolute (the mean
over the attempted draws of a block is the cross section in pb), and predictions come from the
`/RAW/` histograms divided by the attempted draws.

## Uncertainty

Blocks of one cohort are independent equal-exposure estimates; their centered covariance of the
mean is the Monte Carlo covariance. Cohorts are independently integrated contributions (for
example lepton-flavour channels) and add. Draws that the program reports as failed are not
zeros: predictions refuse blocks with failed draws.
