# Finite scalar integral production

`finite-integrals` is an ordinary scientific-study mode that generates, compiles
and evaluates scalar one-loop triangles and boxes with the separately installed
**pySecDec 1.6.6** release. It uses `LoopIntegralFromPropagators`, `loop_package`,
the generated `pylink` make target and `IntegralLibrary.use_Qmc`/`__call__`.
RAVEL supplies a closed physical request and retains the returned evidence;
pySecDec supplies the Feynman parameterization, sector decomposition and QMC.
Supply the installed runtime before planning.

Source and mocked-API tests exercise the request and transport contracts. A production call requires a qualified installed compiler, FORM and QMC runtime, numerical reference evidence and ordinary check-in approval.

## Physics contract

For N=3 or 4, the requested coefficient is the epsilon-zero term of

    integral d^D k / (i pi^(D/2)) product_i [(k+q_i)^2 - m_i^2 + i0]^-1,
    D = 4 - 2 epsilon, q_0 = 0, all propagator powers = 1.

The complete `sij = (q_i-q_j)^2` population has GeV^2 units. Ordered masses are
complex **mass squared** values, also in GeV^2. They are not masses or widths.
The built-in `(-1)^N Gamma(N-D/2)` prefactor is retained with
`additional_prefactor=1`; no extra 16 pi^2 or MSbar normalization is applied.
The finite coefficient has mass dimension 4-2N. Explicit positive `mu_gev` is
retained; its dimensional-regularization power has no effect at epsilon zero
because this admitted class has no poles.

On the Feynman simplex, F = sum_i x_i m_i^2 - sum_(i<j) x_i x_j sij.
Two domains establish nonzero F before requesting an integration:

* `euclidean_positive_masses`: real positive mass squares and all sij <= 0,
  so F is strictly positive.
* `causal_complex_masses`: every real mass square is positive and **every**
  imaginary mass square is strictly negative. Then Im F is strictly negative,
  even for timelike sij. The supplied poles determine the causal continuation;
  no width or finite i0 regulator is invented.

This finite restriction excludes UV/IR poles, zero-width timelike thresholds,
massless propagators, tensor numerators and higher loops. The supplied invariants require a physical kinematic basis, and pole masses require a consistent gauge/model scheme. Amplitude, Wilson-coefficient, EFT-matching and cross-section interpretations require their own source-grounded calculation contracts.

`scale_squared_gev2 = Q^2 > 0` rescales all invariants and mass squares before the
binary64 call. The result and errors are multiplied by `(Q^2)^(2-N)` afterward.
Both original exact decimal/rational tokens and actual binary64 call arguments
are retained. Nonzero normalized parameters must have magnitude in [1e-12,1e6].
An explicit 1–4 axis list includes every changing physical parameter; unlisted
parameters are fixed. All 1–64 requested points are required, with no selection
of successful points or automatic retry.

## Request and ordinary workflow

The ordinary task is `{"config":"path/to/integrals.json"}`. The closed config
schema is implemented by `physics.finite_integrals_core.config`; its keys are:

    schema_version=1, kind="pysecdec-finite-one-loop", source, evidence,
    runtime, propagators, regime, prescription, normalization, axes, points,
    precision, max_seconds, max_ram_mib, max_output_bytes, operation_resources

Use the exact `PRESCRIPTION` and `NORMALIZATION` constants. A point contains
`id`, the complete `invariants_gev2` dictionary, ordered
`masses_squared_gev2` (`real` and `imag` tokens), `scale_squared_gev2`, and
`mu_gev`. Precision contains positive `epsrel`, `epsabs`, `maxeval`, `minn`, and
an explicit positive seed. Epsabs is in the final GeV^(4-2N) units, and is
rescaled for the native call. QMC is explicitly single CPU with no CUDA devices;
one top-level call per point is counted. `maxeval` is an upstream requested
budget, not an OS-enforced exact count of integrand invocations.

Runtime contains exact `python`, `make`, and `cxx` file pins (`path`,`sha256`),
1–8 nonoverlapping complete `trees` with pinned `{schema_version:1,files}`
relative-path/hash manifests, `site_roots`, `contrib_root`, literal PATH
directories and version `1.6.6`. Every tree includes data/cache files and forbids
symlinks; at most 20,000 files per tree. Capturing an ordinary immutable runtime
is an explicit preparation step. All 58 non-test released pySecDec modules and
templates/data must match the shipped API manifest. Generated version metadata,
NumPy/SymPy and other installed dependencies, FORM/contrib executables, libraries,
and compiler runtime bytes need their own complete admission census. Actual
observed optional Python imports must be bound. Newly loaded platform standard
library paths are identified separately with their observed loader-census scope. `pySecDecContrib.dirname` must equal the admitted contrib root.

Runtime paths passed through generated Make syntax must be literal absolute
shell-safe paths. The worker clears inherited Make/CUDA/compiler override flags,
uses `make -j1`, pins CXX and PYTHON, sets FORMTHREADS=1, and puts temporary files
under its fresh output. Generation/build/integration stay in the existing owned
native process group. Wall/RAM guards are the existing common sampled supervisor;
storage is a completion postcondition, not a continuously enforced disk quota.
`operation_resources` is the existing solver declaration with zero generated
events and `solver_evaluations` equal to the point count.

The ordinary schema2 study must have one attempt, zero redos and the single
`finite_scalar_integral_delivery` scope with the `delivery` action. Use the
existing `ravel plan`, `ravel approve` and `ravel run` workflow. `finite-integrals-context` is a deterministic Host
context action with `request_input`: the task, config, API manifest and every
convention-evidence file must be explicit Graph inputs. The ordinary adapter is
also discoverable through the current generic science/context connector.

## Returns and comparison

Every native call's three literal strings (integral without prefactor, prefactor,
and integral with prefactor) are written before interpretation. The finite result
parser accepts exactly one complex epsilon-zero term, plus optional O(eps), and
refuses poles, extra terms, nonfinite values or negative error components. The
journal retains started/returned calls, generation/build phases, loaded-library
metadata and digest, actual arguments and progressive failures. Parent checks
bind raw returns to derived values and the full point population, all inputs,
observed imports and every final output. Corruption is retained as failure;
post-write checks do not replace corrupted evidence.

`reported-values.json` is produced only after complete delivery and estimated
component error targets pass. A final storage failure leaves this derivative
uncommitted and the adapter completion explicitly failed. Raw outputs are kept.
The QMC errors are reported component standard-deviation estimates. They are
**not certified absolute-error enclosures**, coverage claims, arbitrary precision
or evidence of independent numerical accuracy.

The existing `numerical-reference-check` accepts a new candidate format
`finite-integral-reported/v1`, whose projection has an exact `configuration` pin
and a complete one-to-one `component_map` to `real` and `imag`. Use
`finite_integrals_core.comparison_deck` for source-complete units, branch,
normalization, fixed parameters, axes and all original points. Reference rows
still use the unchanged `point-values/v1` rational-midpoint/absolute-radius law.
The new projection compares the **reported centers** against those supplied
reference enclosures plus fixed engineering bands. Native statistical errors
remain separate metadata and never become reference/candidate enclosure radii.
`qualified_enclosure`, `physics_validated`, oracle independence and withholding
claims remain false. The returned comparison semantics names this distinction.
Chronological withholding requires a retained source and acquisition history.

## First independent native qualification

A useful first experiment uses q differences zero and equal complex mass square
m^2 = 4-3i GeV^2, with Q^2 = 2 and 8 GeV^2 and mu = 1 and 2 GeV. The exact
Feynman-parameter identity is

    I_N = (-1)^N Gamma(N-2)/Gamma(N) (m^2)^(2-N).

Thus the triangle is -2/25 - (3/50)i GeV^-2 and the box is
7/3750 + (4/625)i GeV^-4. An independently authored rational oracle tests the
normalization, imaginary sign, dimensional rescaling and mu independence. A
real-mass Euclidean control tests I_3=-1/(2m^2), I_4=1/(6m^4). Follow with
nonzero kinematic points and independently obtained reference evidence before
claiming general accuracy. Four ordinary cases and 16 total calls are proposed
in the owner's qualification design, all unapproved and unexecuted. Measured
runtime/build/storage requirements and source review determine subsequent budgets.

Primary sources: [released source](https://github.com/secdec-research/secdec/tree/39ce21f9b36f74bcadfd927749daa79d601e8542),
[documentation](https://secdec.readthedocs.io/en/stable/gettingstarted.html),
[pySecDec paper](https://arxiv.org/abs/1703.09692).
The separately installed backend is GPL-3.0; no upstream implementation is
bundled into the RAVEL patch. Optional runtime distribution obligations remain
with that runtime's licenses.
