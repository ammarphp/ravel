# Supplied coefficient-convention transport

Mode `eft-convention-transport` substitutes a supplied real square invertible map `c_source = M c_target` in complete signed SM, linear, square and cross response arrays. Decimal/rational strings remain exact through substitution and inversion; a cross monomial appears once with its absolute coefficient. Matrix expansion handles the two contributions to an off-diagonal target monomial explicitly. It never derives a Warsaw/SILH/flavour map from names or evolves a renormalization scale.

The closed task is `{"request": "/absolute/request.json"}`. The request binds exact polynomial and map files, their actual evidence pins, a binary64 projection policy and an explicit maximum coefficient rounding residual. Both files declare complete ordered coefficient axes, basis/flavour/unit/cutoff/scale conventions and full observable/bin populations. Source and target units, cutoff and renormalization scale must be exactly equal. Complex coefficients, missing directions, singular maps, omitted or reversed terms and scale evolution are refused. The target coordinate box must map wholly into the declared source coordinate box; this check is algebraic and never certifies an EFT-validity domain.

The primary output retains rational coefficients, inverse map, source/target coordinate domains and current source pins. Optional native numeric projection is always present under the explicit request policy and retains each exact `binary64 minus rational` residual plus a per-bin response error bound on the declared coordinate box. That bound concerns coefficient rounding in the unnormalized polynomial only; it does not cover native arithmetic, a normalized ratio near a zero denominator, physical theory error or inference. No uncertainty, covariance, prediction normalization or likelihood is transformed. Negative response coefficients and interference signs are preserved.

Use an ordinary version2 science specification, one attempt/zero redos, scope `eft-convention-algebra-delivery` with action `delivery` only. The usual plan/approval/run/status lifecycle applies. Completion delivers the supplied coordinate calculation. Physical basis equivalence, EFT applicability and downstream execution authority remain unknown/false. No automatic fit or accepted-result reuse is authorized.

SFitter specialist convention handoffs can additionally bind `transport_request` and `transport_result` pins alongside `semantic_manifest`. Intake freshly recomputes the complete exact result. Ready-native verifies basis/order/scale/flavour/units, full bin identities and the actual native card against the recorded binary64 projection. Every nonzero transformed term must be present; absent exactly zero cross terms are explicit structural zeros. The original fixed top score, RFit, correlation/shrinkage and width-weighted polynomial ratio remain unchanged. Host handoff custody enumerates the nested map/polynomial/evidence inputs as exact current Graph inputs. This computed transport remains a draft scientific convention artifact, subject to independent physical review and fresh native admission.

Only source and software controls have run. Artificial sign/rotation examples earn no SMEFT-domain, native-fit, measurement or benchmark credit. General RGE, complex/chiral/flavour matching and arbitrary model-to-EFT equivalence require separate source-backed scientific methods.

## Generation and fit coherence

Generation planning records `generation_convention` in CHECK-IN 1 and in the
ending generation receipt. The record retains the actual process-card bytes and
pin, model source digest and restriction, and the study's optional `conventions`
declaration: `basis_identifier`, `ew_input_scheme`, `validity_cutoff` and
`operator_groups` (for example `{"NP": ["ca", "cb"]}`). Each supplied axis carries
one power of its declared coupling-order group. No basis, input scheme or cutoff
is inferred from a model name. Null means undeclared; the literal
`"none declared"` records an explicit absence of a validity cutoff.

`NP^2==1` selects only interference in the squared matrix element; it excludes
the SM term. `NP^2<=1` permits SM and linear terms. `NP^2<=2` permits terms through
degree two. `NP<=1` (also `NP=1`) bounds each amplitude and can retain squares
and cross terms. `NP==1` selects amplitudes of exactly that order. The record
keeps amplitude and squared constraints separately, including raw syntax,
comments and continued-card bytes. It records possible polynomial monomials,
not a proof that their coefficients are nonzero. Missing order-group mappings,
unbounded orders or jointly higher-degree populations remain undeclared. An
independently supplied SM contribution must be recorded explicitly; an
interference sample does not contain it.

The fit semantic manifest can bind
`"generation_coherence": {"record": {"path": "...", "sha256": "..."}, "exception": null}`.
The pin names either the standalone record or a generation receipt containing
it. The process-card pin is resolved relative to that record; producers use
absolute paths. In `eft`, declare the same `basis_identifier`, `ew_input_scheme`
and `validity_cutoff`. The checker compares the complete SM/linear/square/cross
term population keyed by axes with the manifest's `target_basis`, `linear`,
`quadratic` and `mixed_pairs`. The convention handoff and both native statistics
input paths recheck current nested pins. Adding or dropping terms, or changing a
declared basis, scheme or cutoff, refuses the handoff. Missing values on either
side and a missing generation record appear as CHECK-IN flags, never as agreement.

An exception is a pinned JSON document with `kind`, `generation_sha256` (the
canonical record digest from `generation_conventions.digest`), exact `fit`
projection from `fit_convention`, and nonempty `reason` and `effect`. Kind
`declared_truncation` can only remove terms; record which contributions are
removed and the resulting scope or sensitivity change. Kind `deviation` records
a study exception with its effect. Both remain explicit CHECK-IN disclosures
bound by the ordinary fit approval; they confer no physical validation.

Kind `convention_transport` additionally binds `approval_run`, `transport_request`
and `transport_result`. The checker verifies the current ordinary approval for
mode `eft-convention-transport`, the exact request/output identity, freshly
recomputed algebra, source/target bases and complete term populations. It must not
change the electroweak scheme or validity cutoff, or fill missing declarations.
This preserves the existing independent review and native execution requirements.
