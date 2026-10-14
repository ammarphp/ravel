# Supplied parton records and named PDF variations

`pdf-variations` connects supplied tree-level parton integration contributions to
all named members of `NNPDF30_nlo_as_0118` DataVersion 2 using LHAPDF 6.5.6.
It executes through the existing scientific-study route. No new collision events
are generated. The first runtime capsule uses Darwin and explicitly observes the
loaded LHAPDF and C++ libraries. Source tests do not qualify that native capsule.

Use a version 2 scientific specification with `mode: "pdf-variations"`,
`task: {"config": "/absolute/path/to/pdf-variations.json"}`, one attempt, and a
prospective review policy as described in [scientific review](science-review.md).
The standard CLI provides intake, actual approval, supervision and later review:

```bash
ravel plan --rundir /absolute/path/to/new-study --spec /absolute/path/to/study.json
ravel approve --rundir /absolute/path/to/new-study --quote 'Actual approval of the exact proposal'
ravel run --rundir /absolute/path/to/new-study
ravel status --rundir /absolute/path/to/new-study --write
```

The config has `schema_version: 1`, a nonempty `source`, a `runtime`, `pdf_data`,
`records`, `max_seconds`, and `max_ram_mib`. `runtime` pins the Python executable,
its installed source/dependency manifest, and the declared physical native library
files with their load aliases. `pdf_data` binds the full regular directory and a
manifest with every set member, set metadata, `lhapdf.conf`, and `pdfsets.index`.
`records` pins the exact JSON record file. Pins use `path` and `sha256`; native
library pins additionally include `load_path`. Ambient PDF search paths and prefix
fallbacks are excluded, all approved grid assets are copied to a fresh attempt,
and original and copied source/member identities are checked at completion.

The record schema is `pdf-fixed-parton-records`, version 1. It declares the exact
set, ordered members 0 through 100, `error_type: "replicas"`, and member 0 as
nominal. `source_inputs` retains one to 64 exact original files. Each event has a
unique `input_sha256:encounter_ordinal` identity, both incoming PDGs and momentum
fractions, an explicit factorization scale in GeV, a signed `nominal_weight`, and
a complete response for each declared region or likelihood channel/bin. One to
4096 independent single events and one to 32 unique regions are supported. The
operation does not parse a generator file to establish the truth of those supplied
parton identities, scales or response declarations. Authenticated extraction and
physics adjudication remain necessary for an actual recast.

The perturbative contract is explicit: `hard_order: "LO"`,
`counterterms: "none"`, `operation: "pdf_only"`,
`alpha_s_policy: "unchanged_all_members"`, `response_policy: "fixed_supplied"`,
and `group_rule: "independent_single_event"`. No scale is inferred from SCALUP.
The normalization maps a supplied integral contribution to expected events using
one positive factor common to every member. It cannot use this ratio formula on
NLO subtraction/counterterm records or correlated event groups, change alpha_s,
retune the shower, or alter amplitudes, branching fractions, selection or response.
Using this NLO PDF set does not convert an explicitly LO hard calculation to NLO.
The [LHAPDF paper](https://arxiv.org/abs/1412.7420) explains the PDF ratio and the
additional generator information needed for NLO reweighting.

For member m, the transported contribution is the supplied signed contribution
multiplied by the common normalization and by
`[xf_m(pdg1,x1,Q)/xf_0(pdg1,x1,Q)] * [xf_m(pdg2,x2,Q)/xf_0(pdg2,x2,Q)]`.
The x factors cancel at the same fixed incoming point. Negative densities and
weights are retained. A zero nominal PDF denominator, out-of-grid point,
nonfinite value, underflow/overflow, missing member, positivity clipping or changed
alpha_s is refused. There is no epsilon denominator, per-member renormalization,
weight clipping or extrapolation. This does not recover phase space absent from
the supplied nominal sample; support coverage requires separate evidence.

`pdf-variations.json` preserves all 101 named weights per event, all absolute
member yields across the complete regional basis, nominal member-zero yields,
the replica mean, PDF covariance/correlation, and nominal finite-MC covariance.
PDF covariance uses only replicas 1 through 100 and divisor 99. Member zero is
excluded, even though its PDF grid was formed from a replica mean: evaluating a
nonlinear observable on that grid does not generally equal the mean observable.
The complete-set [LHAPDF uncertainty prescription](https://hepcedar.gitlab.io/lhapdf/classLHAPDF_1_1PDFSet.html)
is checked at its nominal 68.268949 percent confidence level. Undefined correlation
for a zero-variance region is recorded as null.

Finite-MC covariance is the separate nominal, uncentered, independent-event Gram
matrix under a Poissonized event census. It retains shared-event regional
correlations and signed-weight contributions. It is conditional on the supplied
single-event sampling assumption. PDF ensemble dispersion and finite-MC sampling
uncertainty are different statistical quantities and are not added automatically.
Other sample designs and per-member finite-MC propagation require additional
contracts. All member weights remain available for those follow-up operations.

`native-pdf-evaluations.json` retains every native density and alpha_s value;
`native-execution.json` retains owned execution/resources; the result retains
actual imported source and loaded library bindings. Successful execution remains
pending prospective scientific review. A three-point grid-knot qualification tests
native density evaluation and coherent arithmetic at those points only. It does
not validate interpolation elsewhere, a generator-to-likelihood map, detector
response, a fit, or an exclusion. Supporting other sets, Hessian/asymmetric or
combined alpha_s prescriptions, and authenticated generator-to-likelihood member
propagation are explicit continuation work, not implied by this first operation.
