# Constructing an original native statistical model

`native-statistical-construction` is an ordinary version 2 science preparation
mode. Its task is `{"input": "/absolute/path/recipe.json"}`. It constructs every
declared cell's complete card, generated PhysicsModel bridge, original source and
template files, and ordinary `native-likelihood` task. A
source-only preparation result says `physics_validated: false`.

The native fit subsequently uses the existing prepared runtime, Combine command
recipe, process custody, saved-fit/result delivery and ordinary review workflow.
The
prepared `task.json` records carry the original parent scope, literal cell
coordinates and original per-task resource ceiling. The preparation plan has its
own existing outer attempt ceiling. Preparing sixteen tasks does not authorize
sixteen fits, change their budgets, or establish a campaign runtime bound.
All cells pass the ordinary native configuration/input parser in a private sibling
staging directory before the complete requested output directory is published.
A malformed final cell leaves retained private staging evidence and serves no
partial public population. Original source/review custody and output ancestry are
rechecked before publication; the ordinary worker owns the fresh output path.

## Exact source recipe

The top-level fields are `schema_version: 1` or `2`, `kind: native-source-graph/v1`,
`question`, `scope`, `population`, `cells`, `source_capsule`, `members`, `review`,
`runtime`, `max_seconds`, and `assumptions`. Source/review roots, law source pins,
runtime pins and the review subject use absolute paths. No operator-written
prebuilt card is an input. `runtime` and every cell's `fit` are the existing
native-likelihood schemas; the source-pinned bridge covers
Combine 9.2.1 and ROOT 6.22/00, observed or explicitly source-generated MultiDimFit and the original full POI box.
The generated card is staged at `source/ravel_graph_model.txt` beside the copied
original source root. The existing native adapter runs in that card directory,
preserving original relative asset paths and layout. A colliding original card
name is refused. All declared prepared native libraries are loaded for the new
source-graph identity/bridge route; existing model branches retain their policy.

`population` contains ordered literal `mass`, `width`, `hypothesis`, `candidate`
axes. Explicit source-declared singleton axes are supported. `cells` must equal
the complete ordered Cartesian product (up to 512 cells). A missing, duplicate,
reordered or invented cell is refused. A cell has optional `expected_data`, and `id`, `coordinates`, `law`,
`parameters`, `observables`, `nodes`, `components`, `integration`, and `fit`.
Every cell contains actual code/template graph and complete regional law; axis
metadata is not a substitute for per-cell construction. Distinct physical models
require their distinct original input graphs, not merely different cell labels.

`law` is the existing complete `statistical_construction` source document. Its
original terms, units, source/energy/luminosity conventions, disjoint SR/CR counts,
leakage, signed interference and explicitly supplied template statistics remain
intact. Native graph contributions are added to that complete mean. To replace
an original component, supply an explicitly reviewed complete law with that
replacement; the constructor does not delete terms or infer missing rates.

`source_capsule` is the existing `analysis-source-capsule`, framework `cpp`, with
all original source/header/asset/template/variation/library dependencies declared
and a complete supplied dependency review. Whole declared files are retained.
`members` records `{id,path,first_line,last_line,sha256,depends_on}` for the complete
original function/class/helper mapping. Span hashes are checked against the same
consumed source buffers; dependencies must be present, acyclic and accounted.
The census is supplied and independently reviewed, not an invented C++ parser
proof. Preserving full files avoids rewriting an original class into a finite DSL.

Extra graph `parameters` have `{name,initial,bounds,fixed,unit,member}`. Integration
`observables` have `{name,bounds,unit,member}`; these are constant integration
variables, never hidden fit nuisances. Physical, generated, observation and node
names have one owner. Unused/missing coordinates/nodes and dependency cycles are
refused; the native witness also checks the actual declared class/server census,
complete ModelConfig nuisance/global/count population and observable ranges/units.

Each native `node` declares `{name,kind,depends_on,members,class}` plus either:

- `factory`: one exact original reviewed RooFactory literal, for example
  `expr::shape("exp(@0*@1)",massObs,slope)`. Existing native classes/factory syntax
  are transported through the original prepared library/runtime. The literal is
  scientific executable input subject to the original review gate, not arbitrary
  Python eval. Its runtime class and direct servers must match the declared map.
- `template`: `{source_path,observable,edges,values,semantics}` where semantics is
  `absolute_bin_integrals_piecewise_constant`. Its authenticated source file must
  contain exactly the canonical JSON of `{edges,values,semantics}` consumed by the
  constructor. Edges cover the complete observable domain and each value is a
  complete signed or positive bin integral. No midpoint approximation, clipping,
  inferred sumw2 law or subset renormalization is introduced.

Nominal and every original variation are separate complete template nodes. Their
original reviewed morph/transfer factory must use them explicitly. A variation
file or node omitted from the declared graph is refused. The constructor does not
invent a generic interpolation or uncertainty law.

`components` declare `{id,node,observable,normalization,measure,role,bin_windows,
coefficients,powers,log_response,meaning}`. Every original region has an explicit
window, coefficient/transfer and response to the same common auxiliary vector.
`powers` refer to declared physical or whitened coordinates. `log_response` uses
the original physical `theta = z + L eta`; the single original Gaussian auxiliary
law appears exactly once. Original explicitly supplied Poisson MC auxiliary
experiments remain part of that same complete count law.

## Integral and yield contract

For `normalization: full_domain`, a positive density contribution is its source
full-domain yield/transfer times

\[
\frac{\int_{\text{bin}} f(x;\theta)\,dx}
     {\int_{\text{full original domain}} f(x;\theta)\,dx}.
\]

The numerator and denominator are raw `RooAbsReal.createIntegral` results for the
same native function and variable; neither call passes `NormSet`. There is one
full-domain denominator per contribution, including all unobserved mass. The
default full observable range is used for the denominator, allowing the native
full-domain analytical integral where the original class advertises it. Bin
integrals use explicit named source ranges. No extra PDF normalization is applied.

`absolute_integral` retains `coefficient * integral_bin(f)` without any denominator.
`signed_density` and interference require this convention: signed components are
not coerced into positive PDFs. Only the sum of the complete original and added
contributions is the expected count. Finite strictly positive TOTAL means are
required for the original counting likelihood. No `abs`, flooring or clipping is
used to repair an invalid mean.

RooHistFunc evaluates raw histogram heights in ROOT 6.22. To represent source bin
integrals, the bridge supplies `value / bin_width` heights to RooDataHist using
the original TH1-pointer import without density correction and RooHistFunc order
zero. Thus the full native integral (RooDataHist sum with bin-volume correction)
preserves the original absolute template yield. RooHistFunc's workspace hook
embeds the original data histogram. An exact rational piecewise-constant reference
is available as `template_integral`; it is a software reference, not a native
integration/parity certificate.

Typed geometry must have finite, distinct binary64 endpoints and finite positive
source and native bin widths. The constant observable midpoint is formed from
the exact rational endpoints before conversion, avoiding overflow from adding
large native endpoints. Every exact template integral divided by its exact bin
width must produce a finite native height; a nonzero source integral must retain a nonzero finite height and a nonzero finite native height-times-width product.
Source zero and signed heights remain unchanged. Collapsed native edges and
unrepresentable geometry are refused during complete recipe validation, before
output staging. No clipping, silent zero, rescaling or new parameter repairs the
source law. These representability checks permit ordinary binary64 rounding;
they do not certify relative numerical error or native integral parity.

`integration` is `{eps_abs,eps_rel,max_steps,policy}` with policy
`ROOT6.22-RooIntegrator1D-original-default-zero-policy`. Each tolerance is explicitly
supplied between `1e-12` and `1e-4`; `max_steps` is 8 through 20. The generated
RooNumIntConfig explicitly selects RooIntegrator1D, Trapezoid, Wynn-Epsilon,
`fixSteps=0`, and ROOT's original `minSteps=999` zero-return policy. In the original
source, only the early zero test is guarded by `j >= _minStepsZero`; the independent
absolute/relative extrapolation convergence tests can return earlier. This does
not force all integrals to the maximum. Trapezoidal refinement through step M has
an estimated direct integrand-call envelope of `2^(M-1)+1` per elementary 1D
integration (524289 at M=20). It is not a hard total evaluation/runtime guarantee:
native class integrals, nested calculations and repeated fit evaluations differ.
Tolerances/settings and extrapolation estimates are not certified error bounds.

API/source provenance for these conventions: ROOT tag `v6-22-00`,
[RooAbsReal](https://root.cern.ch/doc/v622/classRooAbsReal.html),
[RooHistFunc](https://root.cern.ch/doc/v622/classRooHistFunc.html), and original
`RooIntegrator1D.cxx`, `RooDataHist.cxx`, `RooHistFunc.cxx` implementations. Exact
downloaded source hashes and branch locations are retained in the implementation
package's `primary-sources/provenance.json`.

## Source review and later qualification

`review` declares `{root,files,subject,critic,verifier}`. `files` pins the complete
existing Graph record/dependency snapshot, including an already existing lock.
The subject file is exactly `subject(recipe)`: canonical bytes of the whole recipe
except the review receipt references, including all cells, source/member/template
dependencies, original libraries/runtime and fit/resource specifications. Each
review role has `{node,packet_sha256}`. Distinct existing critic and verifier nodes
must pass `agent_graph.model_receipt(... require_exact_subject=True)` with current
accounted calls and full context. Preparation does not call either model.

The review public value has kind `native-source-graph-review/v1`, decision
`source_clear`, the exact subject SHA, complete ordered member IDs, no unresolved
members, and explicit `physics_validated: false` and
`numerical_equivalence_qualified: false`. Existing Graph transport custody does not
authenticate the asserted human/actor identity or prove reviewer independence,
numerical equivalence or scientific truth. No new self-signed author flag replaces
that gate.

Native `source_graph` is mutually exclusive with original regional `construction`
and EFT source branches. Existing arbitrary supplied-card/class routes remain
available. The source-graph witness proves only declared native graph/data/domain
custody and the original full counting/auxiliary linkage. Its result rows contain
no inherited `reference_mean`, `exact_rational` or numerical tolerance label.
`numerical_equivalence_qualified`, `expected_data_qualified`, and
`calibration_qualified` remain false. The explicit generated-data route below is
structural delivery only. Derivative/calibration and generic automatic CLs inversion
remain outside this source-graph operation; original regional inference is unchanged.

After broad implementation/integration, qualification must compare every original
cell's native graph and bin/full-domain integrals against independent source
references, test normalization/units/variation transport and signed TOTAL domains,
qualify numerical convergence and density positivity across the full parameter
box, preserve saved-fit failures and establish optimizer/inference/calibration
adequacy. No existing C27/C26/C25/C23 failures, 130-strand/16-family/18-comparator
population, full 52 RS1 points, or standing scientific questions are upgraded by
this source/software package.

## Full joint observable source graphs

Schema 2 preserves the complete original ordered observable tuple in each
component's `observables`. Every `bin_windows` row is a hyperrectangle with all
original names and finite rational endpoints inside their original full domains.
A template has `source_path`, ordered `axes` of `{observable,edges}`, ordered
Cartesian `values` rows of `{indices,integral}`, and unchanged
`absolute_bin_integrals_piecewise_constant` semantics. Missing, duplicated or
reordered cells refuse. Every original variation remains a separate full table.
No factorization, marginal renormalization, density flattening or signed clipping
is introduced. The native bridge uses actual joint `createIntegral` APIs;
`RooDataHist.set(row,height,0)` retains zero deterministic metadata errors.
Explicit Poisson MC means keep their original exposure-times-latent law; a graph
contribution must not replace those auxiliary means.

Joint geometry checks source/native edges, native RooBinning midpoint, widths,
volume, density height and reconstructed nonzero integral representability.
These are binary64 transport checks, not numerical-accuracy guarantees.

Schema 2 `integration` retains `eps_abs`, `eps_rel`, `max_steps` and adds policy
`ROOT6.22-joint-original-source-relative-policy`, `max_eval_2d`, `max_eval_3d`,
`max_eval_nd`, `max_warn`, `max_template_cells`. Explicit finite evaluation
limits are 1 through 10000000; warning limit is 1 through 1000; complete table
limit is 1 through 65536. These are adapter resource bounds, never truncated
physics populations. The original 8MiB document, 512-cell and 32-observable
bounds remain. A residual native numeric dimension above the released
RooAdaptiveIntegratorND maximum 15 refuses; the full tuple is not restricted
to 15 when native analytic/factored pieces reduce that residual dimension.

The original function, full ranges and native analytic/numeric/factored partitions
are observed. Source-declared transformed lvalues retain their class and original
observable dependency closure. That mapping is a structural check, not proof of
transformed domain/Jacobian equivalence. Original source transformation and native
Jacobian behavior are retained in the bound functions/libraries and require later
numerical qualification. Requested settings and source-derived effective settings
are separate: ROOT6.22 RooAdaptiveIntegratorND uses relative tolerance with
effective absolute tolerance zero and resets `maxWarn` to zero. Returned scalar
values, raw logs and unknown status/error/evaluation counts remain visible.
Convergence requires the declared numerical evidence and independent checks.

## Explicit generated expected data

An optional `expected_data` has kind `source-graph-asimov/v1`, conditioning
`supplied_nominal` or `fit_observed_at_fixed_poi`, full `point`, original law
`source`, explicit `statement`, and `fit` (null for supplied nominal, the existing
bounded minimizer settings for conditioning). The point includes every original
physical parameter, graph coordinate and whitened Gaussian eta, and can use a
nonzero signed POI. Conditioning requires the complete original integer dataset.
Null source observations can use a clearly labelled temporary zero build scaffold
for nominal generation; literal original nulls are never reported as observed data.

The shared preparation reads every original native `ravel_mean_i`, fills all SR/CR
and explicit MC auxiliary counts fractionally, and sets original Gaussian globals
to the generating eta. Count-variable domains and Combine's original Poisson
noRounding path are retained. Out-of-domain means refuse; bounds are not enlarged.
The complete initial/generating/final state, fixed flags, counts, original domains,
globals, conditioning fit population, tables and joint integrals are read back.
Source graphs use structural validators without inheriting regional numerical
parity. The fresh generated workspace goes to ordinary `MultiDimFit` with
`fit.data: source_asimov`, no `-t -1`, and no automatic CLs crossing flags.
Results say generated data and `observed_endpoint: null`; native/coverage/globality
qualification remains false. Original observed, regional expected, supplied-card
and endpoint-specific inference policies remain available.
