# Native EFT evolution and precision observables

The `eft-toolchain` study joins a supplied new-physics WCxf point to
Wilson running, matching and basis translation, flavio SM/NP predictions, and an
optional explicitly selected smelli likelihood. It uses the upstream numerical
implementations. RAVEL supplies the typed request, full population records,
ordinary approval/worker, time/RAM supervision, partial journals and review scope.

The pinned releases (wilson 2.5.2, flavio 2.7.1, smelli 2.4.3) run end to end
through the ordinary lifecycle; a flavio prediction with a shifted WET
coefficient has been executed this way. Numerical qualification of a given
request remains its own evidence.

## Scientific contract

`task` is `{ "config": "path/to/config.json" }`. The config is schema 1 and its
closed keys are documented by `physics.eft_toolchain_core.config`. The source-only
Host tool `eft-toolchain-context` takes a graph-bound task JSON, the config, WCxf
point, convention evidence, API pin and optional covariance cache as exact graph
inputs. It produces scientific preparation context and an ordinary task, without
importing scientific packages or scanning an installed runtime. Standard
`science.adapter` discovery exposes the operation to research tool preparation.
The ordinary study then validates the complete runtime input population.

The coefficient file contains exactly `eft`, `basis`, `scale`, and `values`.
Scale is in GeV; coefficient units and operator normalization are those of the
named, pinned WCxf basis. A coefficient is a real number or a `{Re, Im}` object.
Sparse omissions mean zero in that basis. Unknown operators and an imaginary
part on an explicitly real coefficient refuse. No flavour symmetry, real-only
restriction, Lambda rescaling, SFitter-22 correspondence or UFO matching is
inferred. Warsaw's upstream definition is dimensionful L=sum(C_i O_i), not an
implicit TeV^-2 or C_i/Lambda^2 input convention.

Every Wilson option is explicit: `smeft_accuracy`, `qed_order`, `qcd_order`,
`smeft_matching_order`, electroweak/bottom/charm matching scales and numerical
`parameters`. This is necessary because importing smelli changes Wilson's class
default to leading-log running. Options are applied after all imports, and
retained before use. Targets all start from the same input point; each invokes
native `match_run(..., sectors='all')`. No generated coefficient sector is
discarded. Each result includes native sparse WCxf, complete ordered basis,
explicit dense complex values, basis and coordinate metadata. A separate target
is not a sequential extra approximation to the preceding target.

For each flavio observable, the request specifies identity, arguments, declared
output unit and coefficient source (`input` or a target ID). The native
Observable `prediction_par` receives the complete default central parameter map
plus declared overrides. The zero-new-physics SM and NP calls are separately
retained before a difference is reported. Unknown parameter overrides or
argument sets refuse. Parametric and theory uncertainties require an explicit propagation study. Units retain their source declarations and require review against the observable definition.

The optional smelli branch selects built-in named likelihoods explicitly, with
one source coefficient point and an explicit CKM extraction/fixing choice. It
uses native `GlobalLikelihood.parameter_point(w).log_likelihood_dict()`, which
returns logL(NP)-logL(SM), including the upstream sum over selected groups.
The output quantity is the native fixed-point log-likelihood difference over the selected groups.
The actual component, observable and measurement populations and full SM/NP
parameter maps are retained. NP-dependent CKM extraction can change the Wilson
parameter options; that observed change is retained rather than hidden. A fixed
CKM request has different physics assumptions and needs justification.

## Deterministic covariance route

Smelli can otherwise sample missing covariances during construction. This route
requires an explicitly pinned **JSON** cache with fields `schema_version`,
`source`, `parameters` (complete default-plus-override central map), `fix_ckm`,
`ckm_scheme`, and `groups`. Each selected fast-likelihood group contains the
complete observable list, measurement central vector, measurement covariance
matrix and SM covariance matrix. String observables and `[name, argument, ...]`
identities follow native flavio ordering. The cache must match the selected
fast population exactly; no unused group is silently added or dropped.

Finite, square, exactly symmetric matrices and nonnegative native eigenvalues
are checked before loading. Covariance provenance and numerical conditioning require their own scientific evidence. RAVEL constructs fresh local
pickle files from these checked plain arrays because that is the native loader
format; it never deserializes a supplied pickle. Both native covariance compute
methods are temporarily replaced with a refusal throughout this branch, so a
cache miss must return its explicit missing-value status. Original methods are restored on all exits.
Actual permuted covariance arrays are retained after initialization. For an
ordinary-only likelihood selection, use an explicit empty groups object.
The native fixed SM covariance is an upstream approximation at the supplied
cache assumptions, not a recomputed NP covariance.

## Runtime and result custody

`runtime` pins an executable Python, explicit site roots, every file of the
installed dependency closure of wilson (and flavio and smelli when selected), and
the distribution versions. The closure follows the installed distributions'
declared requirements (extras excluded) and censuses every top-level package and
metadata directory they record, so an unrecorded file in an admitted package is a
change. Bytecode caches are excluded; the worker runs with an empty pycache prefix.
Write the block from an installed environment:

```sh
python -m ravel.physics.eft_toolchain runtime --site "$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
  --package wilson --package flavio --out runtime.json
```

The adapter additionally requires the reviewed release census in
`src/ravel/data/eft_toolchain/upstream-api.json`: the released versions and the
hash of every file of the wilson, flavio and smelli wheels pinned in
`pyproject.toml`. Installed versions must equal those releases. A new release
needs a new reviewed census (`python -m ravel.physics.eft_toolchain api`).
No dependency is installed or downloaded by the adapter.
Python `-I -B`, explicit one-thread limits, no optimized assertions, input hashes,
observed Python import identities and ending full file census are retained.
The interpreter version/path and process identity are recorded. Standard-library files outside declared site roots are allowed without individual file pins; this is not complete interpreter/OS loaded-library closure. Native import compatibility is
not established by the source manifest.

Only ordinary schema-2 one-attempt studies with zero automatic redos and the
`eft-toolchain-fixed-point-delivery` delivery scope can dispatch. The existing
science worker calls the existing `reinterpret_db.execute_native` supervisor;
there is no second job scheduler or runtime. The request declares seconds,
aggregate sampled RAM and maximum JSON export bytes. Each journal write is
bounded; the adapter also checks a whole native-directory postcondition of eight
times that export ceiling. That final disk check is not a continuously enforced
hard disk quota. Subsequent actual admission must account for the chosen runtime,
cache dimensions, logs and generated intermediates.

`<attempt-output>/eft-native/progress.json` journals each started/completed transformation,
SM prediction, NP prediction and likelihood return before dependent checks.
Nonfinite scalar returns are retained as explicit diagnostic objects and refuse
successful delivery. Exceptions retain prior returns. The parent checks exact
requested populations and current input identity; its raw output census is
written before semantic adjudication. This is transport consistency, not an
independent numerical oracle. Internal integrator/evaluator counts are not
instrumented; the reported wrapper return count is explicitly narrower.

## Numerical qualification requirements

A root-admitted qualification can test zero coefficients, a same-scale identity,
a supported basis round trip at fixed scale, pure real/imaginary flavour
components and a known SMEFT-to-WET matching example against upstream tests or
an independent analytic limit. Run high/low scale comparisons with all options
fixed and retain all generated coefficients. For observables use the SM zero
limit and a published one-operator limit with separately justified parameters.
For smelli compare the exact selected native components and their SM reference,
with fixed source/cache/CKM populations. Physical matching, truncation validity and numerical error bounds require independent evidence in addition to round-trip agreement.

Collider/SFitter and flavour constraints become combinable only after the
coefficient conventions and statistical overlap are independently grounded.
The route supplies complete coefficient and precision evidence. A joint likelihood requires the grounded convention map and overlap model.

Primary implementations: [Wilson](https://github.com/wilson-eft/wilson),
[WCxf bases](https://github.com/wcxf/wcxf-bases),
[flavio](https://github.com/flav-io/flavio), and
[smelli](https://github.com/smelli/smelli). The reviewed release versions and wheel file hashes
are shipped in the API contract. Standalone wcxf is deprecated upstream;
this route uses `wilson.wcxf`. No upstream scientific source is modified.

The delivery gate binds every packed target and SM/NP summary to its literal
ordered journal return, and checks duplicated retained summaries for equality.
WCxf values retain explicit zero keys and complete-basis implicit zeros. For
smelli, the original component dictionary order is recorded before JSON sorting,
and the unchanged upstream `sum` of noncustom component float values must exactly
equal the returned global score. This is a transport/source consistency check,
not a likelihood oracle. Native child and checker must use matching CPython
major/minor and floating format for this reduction; a mismatch is a refusal that
needs separate qualification, without a widened tolerance or custom summation.
