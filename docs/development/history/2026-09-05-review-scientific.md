# Adversarial scientific software review

Reviewed the uncommitted implementation based on `8d8b4b53b358c9798ae9b0d6345919c907b8639e` in `<repository>` on 2026-09-05. Scope was priorities 1, 2 and 5 and their integration: mathematical result transport, artifact-bound comparisons, scientific intake and public capability claims. This was a local, read-only source review. No source, scientific run, network, credential or identity operations were performed. Temporary fixture directories and the review scripts/report are the only new review artifacts.

The issues below were reproduced before the implementation owners began repairing them. Line numbers refer to that reviewed state. A final verification pass must rerun the supplied regressions and the relevant suite against the completed tree. These are software consistency findings; none requires a new physics calibration campaign to resolve.

## Findings

### 1. P1 — A current certified source and its result pack can disagree by an arbitrary scale

Locations: `src/ravel/workflow/result_pack.py:450-453`, `src/ravel/validation/certificates.py:452-458`, `src/ravel/validation/validate_run_state.py:1388-1394`, `src/ravel/validation/validate_run_state.py:1614-1648`, and preferred-result loading in `src/ravel/workflow/scan_orchestrator.py:527-573`.

The acceptance certificate is validated against the underlying exclusion artifact. The live acceptance invariant requests that exclusion and any diagnostic report as subjects, but does not bind the emitted result pack. The typed-limit invariant validates both records individually without checking their mathematical agreement. Scan harvesting prefers the result pack without checking its source correspondence.

Reproduction is the first block of `<review-workdir>/ravel-review-pack-intake-probes.py`. It uses the existing approved acceptance fixture with compute plan `none`, creates a resolved exclusion at observed mu95 = 0.8, creates its valid certificate, and emits a result pack through `build_result`. The pack is then coherently rescaled by 0.01, including aliases, typed values, eligibility and its baseline. The exclusion remains 0.8. The pack is 0.008.

Expected: reject the changed pack or demonstrate a recorded, verified transformation from the source. Actual: `inv_certify_before_limit` returns PASS and `inv_limit_transport` returns PASS with two representations checked. The pack still carries the current acceptance certificate annotation.

Required fix: establish a transitive source binding for the pack. Compare its typed values, statuses, brackets and scientific identity/normalization to the authoritative source and current source digest at pack generation, live validation and scan harvest. A deliberate transformation needs explicit source/factor provenance and verified arithmetic. Binding a generated pack directly inside the certificate is not necessary if the derived-output binding is verified; avoid introducing a certificate/pack construction cycle. Add a stale preferred-pack control that must fail rather than silently fall back.

### 2. P1 — Producer-specific scientific consistency checks can be skipped or contradicted

Location: `src/ravel/validation/certificates.py:264-292`.

The recorded producer module/hash is checked, but the scientific operand validation is dispatched by separate optional document fields (`generator == "shape_fit.py"`, or presence of both `validation_points` and `rows`). The producer and these discriminators are not required to agree. Shape primary values are also read as direct scalars without checking the same document's canonical typed limits.

Reproduction: `<review-workdir>/ravel-review-certificate-probes.py`, using the existing approved R5 fixture. All three cases currently produce a new certificate and pass live validation:

1. Producer declares the current `ravel.physics.shape_fit` implementation, `mu95_exp` is 100, and the comparison point is 1.01. Omitting `generator` skips the primary consistency check.
2. Document declares `generator: shape_fit.py` but producer declares the current `ravel.validation.certify_acceptance` implementation. The incompatible producer discriminator is accepted.
3. Document declares the normal shape generator and producer, scalar `mu95_exp` equals the comparison point 1.01, but the canonical typed expected median is 100. `claim_errors` independently detects the conflict, while certificate creation and live checking return PASS.

Expected: all three reject before central-value agreement is credited. Required fix: tie recognized producer adapters to the producer identity; require internally consistent producer/generator/quantity/schema combinations; invoke the canonical limit reader for shape numerical operands; and compare normalized points with the producer's authoritative computed values. Generic declared measurement imports may remain a separately scoped supported representation, but recognized producer fields must not make contradictory records acceptable. A hash identifies an implementation version; it does not authenticate that every field was emitted by it. The documentation already acknowledges that distinction and should keep doing so.

### 3. P2 — Expected-only projections expose an eligible observed exclusion through the typed API

Locations: `src/ravel/physics/project_limits.py:131-138` and `src/ravel/physics/project_limits.py:275-283`.

Both projection routes copy the inference engine's complete `LimitResult`, including the observed slot. Counting uses background-only Asimov observations and labels the record `observed_semantics: Asimov diagnostic, not an observed projection`. Likelihood mode explicitly labels its original-data rescaling a proxy. The newly attached typed representation nevertheless marks that observed slot as a resolved root and sets `observed_root: true`.

An actual `cmd_counting` call with a substituted numerical fixture at observed = median = 0.5 produces an expected-only projection for which `point_value(record)` returns 0.5 and `read_limits(record).observed.exclusion()` returns True. `claim_errors(record)` returns no errors. This requires no malformed values or manual rewriting of the output. The substituted engine only keeps the test bounded; the record construction is the production code.

Expected: generic observed-limit consumers should not interpret a projected Asimov/scaled-data diagnostic as an observed experimental exclusion. Required fix: mark the projection's observed slot missing and retain the engine diagnostic separately, or add an explicit data/curve role that the central eligibility API enforces. Keep all five expected slots and their statuses. Test both projection routes and a genuine observed result as a control.

### 4. P2 — Coordinated negation can become a positive compute proposal, and denied targets persist

Locations: `src/ravel/workflow/intake.py:44-58` and `src/ravel/workflow/route_prompt.py:153-165`.

The parser splits `and scan/reproduce/...` into a new clause before determining negation scope. It also does not recognize `neither ... nor ...`. Target extraction runs on the raw prompt rather than its actionable clauses.

Reproductions in `<review-workdir>/ravel-review-pack-intake-probes.py`:

| Request | Expected | Actual |
|---|---|---|
| I do not want you to reproduce ATLAS SUSY-2018-16 and scan the masses. | Neither requested | `scan` |
| I want you to neither reproduce ATLAS SUSY-2018-16 nor scan its masses. | Neither requested | `reproduce` |
| Do not survey ATLAS SUSY-2018-16; reproduce CMS SUSY-2019-12. | CMS target only | Both ATLAS and CMS target IDs |

Required positive controls: `I do not want you to reproduce A, but scan the masses` and `Do not reproduce A; scan the masses` must preserve the positive scan; `Please do not merely survey searches; reproduce A` must preserve reproduce; `Reproduce A and never claim discovery` must preserve reproduce. The bare `Do not scan ... and reproduce ...` construction is ambiguous and should remain a conservative draft rather than silently settle its scope.

These errors do not themselves authorize generation: `approval_required` remains true and new drafts do not receive approvals. Their impact is wrong scientific scope and misleading compute proposals. Fix clause scope and share target extraction/normalization with the actionable interpretation path; do not patch only the observed strings.

### 5. P2 — A supplied host interpretation may introduce a discovery deliverable despite an explicit denial

Locations: `src/ravel/workflow/intake.py:17-37` and `src/ravel/workflow/route_prompt.py:170-177`.

The structural grounding checks validate request hash, literal evidence spans and a restricted set of new analysis IDs. Discovery checking only inspects the original actionable request, not the interpretation objective or requested outputs.

Reproduction in `<review-workdir>/ravel-review-pack-intake-probes.py`: original request is `Survey collider searches. Do not claim discovery.` A correctly hashed interpretation with a full exact evidence span, kind `survey`, objective `Claim discovery of a new particle at 5 sigma.`, and requested output `Announce a discovery.` is accepted. `route` returns survey, preserves that objective, and `validate(contract)` returns no errors.

Expected: reject a semantically supplied output that violates the product's explicit discovery boundary. This does not require a general semantic proof engine. Apply known forbidden-intent checks to the proposed objective/outputs too and preserve draft/uncertainty status for all remaining judgment. The same analysis identifier grammar should be used by router and grounding validation, rather than two drifting regex subsets.

### 6. P2 — Capability headline claims exceeded their own full-deliverable definition

Locations at review start: `benchmarks/capabilities.json:5`, P1 at `:14-25`, P4 at `:64-70`, and generated `docs/development/status.md` headline/board.

The registry defines `served` as a full deliverable chain that exists and was exercised. P1's own evidence explicitly retains lifecycle FAIL, undeclared figure target, pending CHECK-IN 1 approval, and no step-9 Tier-B review. P4's gate is the shape engine selftest while its requested 2408.00049 instance remains held for R5 closure. Those are useful component or partial-task results, not two fully served reference tasks under the registry's definition.

Expected correction: P1 and P4 partial, preserve their component/historical evidence, and give each a full-deliverable promotion condition. This yields 0/7 fully served and 0.50 under the existing half-credit convention. Root confirmed this correction was underway during review. No new scientific campaign is demanded by this finding; it is accurate representation of present evidence.

## Verification and remaining boundaries

The following bounded command was run from the DSRLab parent so the historical `py.py` cannot shadow pytest dependencies:

```sh
PYTHONPATH=hep-agentic-pipeline/src <review-workdir>/ravel-cli-clean-env/bin/python -m pytest -q hep-agentic-pipeline/tests/unit/test_certificates.py hep-agentic-pipeline/tests/unit/test_limit_transport.py hep-agentic-pipeline/tests/unit/test_semantic_intake.py
```

Observed result: 104 passed, 1 failed, 14 dependency deprecation warnings. Failure: `test_real_execution_receipt_staleness_blocks_harvest` at `tests/unit/test_limit_transport.py:260`, expecting `done` after the successful supervised fit but receiving `pending`. Native/execution work was concurrent at this point, so this is an integration failure to reproduce against the finalized tree, not an attributed root cause. Root was informed immediately.

The new modules have a sensible separation of concerns: typed limits are inference-independent; certificates recompute declared comparisons; an approved pinned plan governs live comparison scope; intake creates a draft without execution approval. The central-value and precision certificate scope strings explicitly disclaim detector/coverage certification. Recomputed changed dependency/reference/prediction/subject hashes, distinct mass/reference identities, all-row denominators, stale plan approvals, one-sided bounds, missing expected slots, and internally contradictory scalar aliases already have meaningful tests and resisted the ordinary checks inspected here.

No finding here asks for source authentication beyond the stated local evidence model, universal statistical coverage, automatic reference-population adequacy, or renewed detector campaigns. Those remain scientific review obligations and should not be presented as solved by mechanism tests. The needed software repairs are agreement between known operands, faithful transformations between artifacts, clear observed-versus-projected roles, and preservation of the user's intended scope.
