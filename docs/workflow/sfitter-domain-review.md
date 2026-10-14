# SFitter domain review and return to work

Use `ravel sfitter-review context --request review-request.json` after a returned
SFitter specialist handoff. The request binds the exact workflow draft, full
observable regime census, raw check artifacts, declared scientific criteria and
original registered scientific check IDs. It does not approve the draft or run a fit.

The pinned SFitter sources at commit `6072a79e0f132d61a927f11ed482a401b34f6e3f`
(`sf-deep-verify`, `sf-reinterpret`, `sf-parameterize`, `<supplied-domain-source>/sf-discipline.md`
and the scientific reviewer) and the upstream license are context. Their cluster commands,
unbounded review loops, memory mutations and numerical rules are not execution
instructions. Native SFitter `-Q`, `exp(-Q)`, component RFit, named correlations,
shrinkage and polynomial coefficients remain unchanged.

The closed request has `schema_version: 1`, `id`, `workflow: {path, sha256}`,
`stage` (one of the existing five phases, or `native_result`), `regime` (JSON pin),
`checks`, `required_concerns`, `check_mapping` and `claim_scope`. The registered
scope and checks remain the original review authority. A concern outside the
requested action's material scope is retained as a warning, not a resolved fact.

`regime` contains `schema_version`, the complete ordered `observables` census
(`ID`, `acceptance: fiducial|total|unknown`, `source`) and primary `sources` pins.
A located source is `{artifact: {path, sha256}, location: <RFC6901 pointer>}`.
Every check has `id`, `concern`, complete `observables` identities, `method` and
located `data`. Data use the closed method schemas in
`ravel.workflow.sfitter_review_protocol`; there are no expression evaluators.

The nine concern families are extraction traceability, uncertainty roundtrip,
observable semantics, SM baseline, coupling contamination, coefficient baseline,
theory double counting, datacard roundtrip and documentation. Full coverage is
checked separately for each required method and observable. Missing bins,
unknown fiducial/total meanings, unmapped couplings and unexecuted native checks
stay inconclusive. Blindspot triage locates work; it cannot verify that work.

Implemented artifact recomputations are:

- `traceability`: locate each requested bin and retain declared source confidence.
- `quadrature`: rebuild independent-component totals against an independently
  located total. Independence and comparison tolerance need source justification.
- `regime_consistency`: compare units, integrated/differential and normalization
  meanings, fiducial/total regime and declared luminosity treatment.
- `vector_agreement`: compare actual handed-off SM values with a separate pinned
  reference under a source-bound criterion.
- `polynomial`: evaluate the actual full-basis linear, square and signed mixed
  coefficients at supplied scan points. Multi-bin groups use the exact native
  width-weighted ratio. This is not a Taylor expansion, R² guarantee, global
  interpolation test or EFT-validity test. An independent SM comparison is also
  needed for complete coefficient-baseline coverage.
- `coupling_census`: inspect actual generated Fortran `GC_N` references against
  the model-specific coupling map and complete observed DIM6 block/address census.
  The zeroing record explicitly names `stage: pre_activation|final_scan`,
  `provenance: constructed_input|returned_parameter_card`, `model_source`,
  `parameter_card` pin, `execution`, `dim6_parameters`, `parameter_locations`,
  `parameter_operators` and `active_values`. Pre-activation values are all zero;
  a final scanned card may activate only its exactly declared selected-axis values.
  The existing SLHA recipe parser is reused. A construction-only card/command
  ledger stays inconclusive, even if its intended values are correct. Returned
  provenance requires exact current ordinary stage/attempt/output custody.
  Mapping and model parameter completeness remain explicit scientific premises.
- `uncertainty_inventory`: locate physical source identities and flag sources
  independently included more than once. Different names do not imply independence.
- `datacard_composition`: compare the authenticated whole card with returned
  extraction, SM and coefficient handoffs and validate native semantic scope.
- `native_parser_roundtrip`: read a current successful ordinary SFitter attempt's
  initialized tensors and source/runtime receipt; compare measurements, SM,
  coefficients and widths without importing Torch or evaluating Q. It cannot
  qualify the covariance, fit convergence, intervals or calibration.
- `document_inventory`: locate measurement/model/method/uncertainty/limitation
  documentation for the complete population.
- `prescribed`: retain a necessary unexecuted probe with available evidence.
  Its status always remains inconclusive.

No universal R², interference threshold or tolerance is supplied. A criterion
must bind an external justification. Reviewer judgment must assess whether that
criterion, primary source and independence premise are adequate for the action.

For ordinary CHECK-IN 2, `prepare_role(rundir, request_pin, out, **role_options)`
creates a complete concern case and calls existing `scientific_judgment.prepare_role`.
Use the normal critic, separate verifier and synthesizer actors. The domain binding
contains `request`, `report`, `case` and the unchanged nested `judgment` binding.
Dispatch the latter through `scientific_judgment.execute_role`; a supplied campaign
and observed experiment use the existing cumulative reservation/failed-call ledger.
The Host tool `sfitter-review-protocol` prepares or consumes; it never dispatches
a nested model or scientific worker. All protocol dependencies must be explicit
Graph inputs. Public consumption refuses control-only transport by default.

`consume(rundir, binding)` freshly recomputes the report, checks the exact current
role/case/scope and records through the original physics-review journal. Failed or
unknown material concerns cannot be turned into acceptance by a model label.
Original source pins are retained by that journal, so delivery/reuse checks also
refuse later source drift. Unresolved warnings remain in the displayed report and
role context. Raw numerical delivery does not imply scientific resolution.

After a genuine recorded `send_back`, `rework(rundir, binding, out)` uses the
finding's original check IDs to select the earliest owning phase. It writes a
fresh workflow preserving the preceding handoff prefix and returns the existing
bounded phase Graph. The old workflow, role calls and votes remain immutable;
no votes are carried forward. The SFitter conductor delegates this seam only when
the protocol binds its exact adopted workflow and phase.

A new handoff replaces the affected phase and descendants in a fresh workflow.
Changed model/operator/normalization premises require a fresh workflow/target and
regime, not a carried review. Revised artifacts need a fresh domain request,
case and role review. Within-run execution still requires existing correction
admission and a fresh CHECK-IN 2 cycle. When the original redo bound is exhausted
(including SFitter's one-attempt delivery-only native policy), the rework is only
a prospective fresh-study draft: fresh ordinary plan/admission are required.
Adequate repair design is not actual repair closure.

Failed native outputs remain on the canonical `failed-review`/research-cycle
diagnostic route. This protocol can display their prescribed unresolved concerns;
it cannot open an ordinary successful receipt or accept a failed numerical result.
Scientific effectiveness, native accuracy, covariance and full-study comparison
remain separate qualification work.
# Finite recomputation

Computed predictions, comparison residuals and absolute-plus-relative comparison bands must remain finite. Arithmetic overflow is refused before a check can be labeled passing. This guard changes no declared tolerance, polynomial coefficient convention, native score or scientific acceptance requirement.
