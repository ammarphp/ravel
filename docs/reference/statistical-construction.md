# Complete regional statistical construction

`ravel.physics.statistical_construction` validates supplied regional mean laws and emits source-bound native fit bundles.

## Callable path

1. Supply the complete question, all integer-count SR/CR bins, their observation identities and a source-backed disjoint-Poisson partition assumption. Include expected-event coefficients in every bin, including literal zero control contamination. Weighted or overlapping observation tables are not automatically Poisson counts.
2. `transfer_terms` expands a supplied complete matrix times shared nonnegative latent yields. `abcd_terms` expands A=beta*u*v*kappa, B=beta*u, C=beta*v, D=beta, without division or data-driven plug-in ratios. The caller explicitly declares parameter domains, fixed closure or supplied closure response. These recipes do not establish physical closure.
3. Full terms admit multicoefficient powers, cross terms and signed interference. Powers can also use physical auxiliary coordinates, allowing additive polynomial shape changes and zero-nominal migration. Log responses use the same shared coordinates. These are the supplied polynomial/log-response laws, not an automatic replacement for HistFactory code4/code4p or another published interpolation.
4. `validate`, `mean_jet`, `response` and `datacard` expose the complete supplied construction, analytic first derivatives, generated RooFit algebra and exact counting card. The pure `mean_jet` retains signed terms and classifies strict positivity of the total; it never clips. It does not evaluate a likelihood.
5. `write_native_bundle(document, fresh_output, runtime=..., fit=..., max_seconds=...)` emits `construction.json`, `model.txt`, the ordinary `native-input.json` and a mode/task handoff. Runtime and fit are the existing complete native-likelihood contracts. Ordinary `science.task_inputs` reaches the new optional `model.construction` branch and rechecks all scientific inputs and generated card bytes. No additional mode or supervisor is introduced.
6. Existing observed MultiDimFit saved-fit or profile-grid commands build the full model and retain native raw NLL, all profile rows, saved RooFitResult parameters/covariance/status/EDM, logs and failures according to the existing backend.

## Mathematical definition

For complete bin b, the supplied full mean is

`lambda_b = sum_t a_tb product_j x_j^p_tj product_i theta_i^q_ti exp(sum_i R_tbi theta_i)`.

All coefficients, exponents, domains and responses are supplied, with source identities. Coefficients are expected-event contributions. The declaration retains basis, source scale, units, energy/luminosity, domain and applicability assumptions; no WCxf/RGE or acceptance conversion is inferred.

The one supplied Gaussian auxiliary block is `z | theta ~ Normal(theta, L L^T)`, with explicitly supplied lower factor L and positive diagonal. Native coordinates are `eta=L^-1(theta-z)`. The same observation and parameter change gives one standard Normal constraint per eta coordinate, shared across bins and terms. The supplied covariance is retained as exact rational `L L^T`; it is not estimated from yields or a response covariance. All eta ranges are explicit, so their physical domain is the supplied transformed box, not an implicit axis-aligned physical-theta box. The normalized physical auxiliary density and normalized whitened density differ by the constant log determinant of L. Raw native NLL can have further omitted constants; subsequent numerical qualification must compare absolute constants explicitly or use declared differences, never silently equate raw values.

Native lowering places the whole signed sum in a single full-mean function per bin, with a zero dummy process to satisfy the card process census. The technical process label is not a physics background decomposition. `ModelConfig_bonly` has no inferential meaning here and is not used by the allowed observed study. Physical parameter roles and the full term decomposition remain in the pinned construction. Floating non-POI parameters enter ModelConfig nuisance membership; fixed parameters remain fixed. Gaussian auxiliaries appear once, and free-rate `flatParam` tags add no claimed sampling law.

Every admitted fixed witness records actual complete native coordinates, bounds and constant flags. The source comparison checks full means at those observed coordinates, the POI, all nuisance/global populations, every observed count and unit dataset weight, and zero-valued fixed transformed auxiliary observations. Signed negative components are allowed; nonpositive total means are refused. Outside the strict-positive domain the native optimizer's invalid-NLL behavior still requires qualification. No global positivity proof or optimizer validity follows from finite witnesses.

## Source basis and composition

The native lowering follows the retained official Combine v9.2.1 `<supplied-Combine-source>/python/ModelTools.py`, `<supplied-Combine-source>/python/PhysicsModel.py` and `<supplied-Combine-source>/python/DatacardParser.py`. The source-defined builder order permits variables/functions in `doParametersOfInterest` before nuisance construction; explicit `param` ranges and `extraNuisances` preserve the stated roles. Counting channels use the full expected mean. The branch admits Combine 9.2.1 only; source/API compatibility is not native ABI qualification. Official source URL and digest are in `<private-source-review>/primary/acquisition.json`.

## Generated native names

Admission enumerates the exact Combine 9.2.1 counting-card/plugin object namespace before lowering or writing a bundle. Physical coordinates must not reuse generated PDF, product, set, dataset, observation or process-expectation names. Cross-bin collisions such as A/A_bonly and A/A_proc_ravel_full are refused, including products created when the bin population exceeds 50. The supplied auxiliary names are algebraic labels; native coordinates retain the ravel_aux_i mapping. This changes naming admission only; no observations, response coefficients, nuisance law, bounds, commands or fit outcomes are changed. Arbitrary extra Combine builder flags, shapes and external objects remain outside this closed route.
