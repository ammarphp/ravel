---
name: roofit-histfactory
description: Use when preserving an original RooFit source graph, constructing a complete regional Poisson likelihood, reviewing HistFactory nuisance and signal templates, or interpreting expected Asimov sensitivity and held-out Monte Carlo closure in RAVEL.
license: Apache-2.0
compatibility: ROOT 6.22 in the legacy root-combine manifest group and pyhf 0.7.6 are distinct routes. Original site RooFit graphs bind their actual runtime and source capsule; this handbook does not pin them to that container.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "native-statistical-construction statistical-model asimov-sensitivity mc-closure"
  upstream-version: "root-combine:ROOT=6.22 pypi:pyhf=0.7.6"
  last-reviewed: "2026-10-11"
---

# RooFit and HistFactory

## Preserve the source model

RooFit source graphs, HistFactory workspaces and RAVEL's declarative count models
are separate inputs. Choose the route that can retain the source's functions,
normalization, bin integrals, constraints and shared parameters. The ROOT 6.22
Combine container pin does not qualify a different site RooFit library or a
source model automatically.

`native-statistical-construction` reads an original C++ source capsule with a
complete dependency review, member spans and hashes, literal population axes,
all source cells, reviewed runtime and bounded work. It prepares native fit
bundles. Preparation itself imports no native library and proves neither native
integral parity nor optimizer convergence. Retain its structural, integration
and template-readback witnesses and the later native execution evidence.

`statistical_construction` handles complete regional source laws and emits a
native response, datacard and bridge. `statistical-model` is the supplied
Poisson/lognormal count-model route compiled to pyhf. It retains the full SR/CR
signal contributions, auxiliary covariance, overlap evidence and MC-statistics
contract. It is not a generic translator for every RooFit graph. Published
HistFactory JSON patching uses the separate pyhf-workspace-patching handbook.

Use ordinary `ravel plan`, approval and `ravel run` with the chosen registered
mode. RAVEL has no separate `ravel roofit` or `ravel histfactory` command.
Read `docs/reference/statistical-construction.md`, `domain-adapters.md`,
`columnar-analysis-modes.md` and the actual native model's runtime contract.

## Bin integrals and native geometry

A source template's values are bin integrals. Its piecewise-constant height is
value divided by width. A clipped source window includes only its overlap with
each bin. This exact reference uses rational source values and checks that the
geometry can survive conversion to native floats before evaluating the source
integral. It does not execute RooFit or demonstrate native parity:

```python ravel-block=source-template-integral
from ravel.physics import native_statistical_construction

def source_template_integral(template, window):
    """Source witness for a validated template, including native geometry refusal."""
    native_statistical_construction._template_native_geometry(template)
    return native_statistical_construction.template_integral(template, window)
```

Use the complete constructor validation before calling a witness on real input;
the helper above assumes a template with equal-length edges and values already
validated. Joint templates carry their full multidimensional geometry.
A source integral and a generated PDF height are different objects. Preserve
category populations and integration domains instead of evaluating only centers.

## Expected sensitivity and closure

A native constructor cell with a `discovery_diagnostic` emits an
`asimov-sensitivity` task. It retains every declared start, the null and free fits
and their diagnostics. The requested q0,A is twice the null-minus-free NLL;
its square root is a local expected asymptotic quantity. It is not observed
evidence or a calibrated global discovery significance.

`mc-closure` freezes the prediction and compares it against complete independent
held-out MC replicas with their original stream deliveries, sampling laws and
covariance transport. Reusing the same events as both prediction and replica
requires its actual dependence, not an independence label. Preserve failed fits
and missing contributions in the delivered record.

## Pitfalls

- An original graph is reduced to a few selected cells or leaves out a dependency.
  Caught by `ravel.physics.native_statistical_construction.validate_document`
  against its declared capsule and complete Cartesian population.
- A source bin integral is used as a PDF height, or a nonzero interval vanishes
  in native floating point. Caught by
  `ravel.physics.native_statistical_construction._template_native_geometry`
  for geometry and by
  `ravel.physics.native_statistical_construction.integration_witness` for recorded
  native/source comparisons.
- A count-model drops SR/CR contamination, asserts disjointness without evidence,
  or omits its template-statistics treatment. Caught by
  `ravel.physics.statistical_model.prepare` for the complete declared model;
  missing physics that the declaration conceals still needs source review.
- A fit is accepted from one optimizer success flag without likelihood parity or
  independent starts. Caught by `ravel.physics.statistical_model.fit` for its
  declared pyhf count-model fit, with its verification diagnostics.
- An incomplete or unbound held-out replica is called MC closure. Caught by
  `ravel.physics.mc_closure.inputs`, which loads both complete stream deliveries.
- Advisory: source transport, arithmetic closure and an Asimov profile do not
  establish empirical coverage or a general RooFit-to-HistFactory equivalence.
  Candidate check RF-A1 in `references/checks.md` requires native numerical and
  repeated-data witnesses for the actual source law.

## Wrong versus right

| Wrong | Right | RAVEL check |
|---|---|---|
| Keep only a convenient subset of graph cells | Retain the declared whole population and dependency capsule | `native_statistical_construction.validate_document` |
| Use bin values as density heights | Divide by bin width and compare clipped integrals | `native_statistical_construction.integration_witness` |
| Omit signal from affected controls | Keep the full declared region/component model | `statistical_model.prepare` |
| Accept optimizer success alone | Require multi-start and likelihood consistency evidence | `statistical_model.fit` |
| Reuse an incomplete prediction as the held-out sample | Bind both full independent stream deliveries | `mc_closure.inputs` |

More: `references/checks.md` and `references/review.md`. Upstream references:
ROOT 6.22 RooFit and RooStats reference guides; Cranmer et al., HistFactory:
A tool for creating statistical models for use with RooFit and RooStats,
CERN-OPEN-2012-016 (2012); pyhf 0.7.6 documentation.
