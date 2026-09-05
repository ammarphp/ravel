# Independent verification of scientific correctness repairs

Date: 2026-09-05. Checkout: `<repository>`. Baseline HEAD: `8d8b4b53b358c9798ae9b0d6345919c907b8639e`.

All six reported findings are resolved in the final verified snapshot, including the additional derived-headline inconsistency found during the first verification pass. This verifies the findings in `<review-workdir>/ravel-adversarial-results-review.md`. The original report and both original regression scripts were preserved. Verification is local and read-only with respect to repository source. Numerical fixtures substitute bounded engine results where the test concerns downstream representation; no new scientific execution or calibration is claimed.

## Initial repaired snapshot

The initial `git diff --binary` SHA-256 was `e6de88069956b2780e960dfdda5324fc43a2f720433705e8912919bd9c714146`. A later whole-diff hash was `25b68148e66a597654e808908de5c5849bf6b4fee71ea769438a1f5d71e08aaa`; parallel finalization changed the overall working diff during this verification. Because ordinary Git diffs exclude new untracked source, the source file hashes below identify the actual reviewed implementations. A final snapshot is recorded below when the remaining derived-headline repair is verified.

| File | Initial verified SHA-256 |
|---|---|
| `src/ravel/limits.py` | `088630d5f6dab5f9e8da8fb35c9a9e05f968e331b2fb506a15ece0906573c150` |
| `src/ravel/validation/certificates.py` | `18814c4aabe3e69d7229e0970b56242a305c34cc5a67c2d4a516e5c13be29e32` |
| `src/ravel/workflow/intake.py` | `67ae32113861294bc4661ce7db3c82d9085de0db8c1b74346111160bcea7b57b` |
| `src/ravel/workflow/route_prompt.py` | `a6fa0bca512ea808a9d46af6369239d11e46646c3b77b0e09599a0ebe8d3d712` |
| `src/ravel/workflow/result_pack.py` | `b1af8ada71557af370ab4f44a76839d34498e409d91c4bf47853f869cfaf7175` |
| `src/ravel/workflow/scan_orchestrator.py` | `b44f69b606f97ae2cf0ccef5ef8f9c27bccf6f3d4f1c5e5351b0b87f79f2109c` |
| `src/ravel/physics/project_limits.py` | `17f5984cfb06677bb36be103e23978ab0789e6e790a751d0c5cb319e94e0dc7c` |
| `src/ravel/validation/validate_run_state.py` | `5a51fd0942867d192e1868acca66d3587df28826f3a420a1eb18e78ce29ae73b` |
| `src/ravel/validation/validate_task_contract.py` | `24123e7fc6eb39d8b33c18c2213a477dfda842cda41fecebb96efd49db88dd2e` |
| `benchmarks/capabilities.json` | `ff49a580d8e484021fa9f4bc5b47adfde89d0c416b50ba580f1da122fb26b3e2` |
| `docs/development/status.md` | `91b2395e42499318a75c8fe814b6119c86ff037a02fd8da3a5369d1b1357419b` |

## Finding dispositions

### 1. Certified source and result-pack agreement — original regression resolved; derived arithmetic initially remained open

The saved original regression now receives FAIL from both gates. Source observed mu95 = 0.8 and coherently edited pack observed mu95 = 0.008 yield `pack limits/statuses/brackets differ from the bound primary inference artifact`.

Code inspection confirms `limits.bind_source`/`source_errors` verify an exact primary path, current bytes, identity transport, typed curves/statuses/brackets, and overlapping identity/numerical metadata. The live gate independently selects the certified primary rather than trusting the pack's own source choice. Harvest checks a preferred modern pack and its current live certificate before collecting it. Existing positive source-transport controls pass.

A closely related scientific headline remains inconsistent at this initial snapshot. A real `build_result` fixture with observed mu95 = 0.8, `sigma_scale_k = 1`, and `sigma_lo_pb = 1` correctly computes `sigma_ref_fb = 1000` and `sigma_ul_ours_fb = 800`. Editing only `sigma_ul_ours_fb` to 0.001 leaves `source_errors` empty and both live mathematical/certificate invariants PASS. `source_errors` at initial lines 409-416 compares typed curves and overlapping source metadata but does not recompute this derived pack formula. This does not require changing or replacing the primary artifact.

The exact variant and its valid unmodified positive control are saved in `<review-workdir>/ravel-review-derived-headline-probe.py`. The implementation owner was notified. Final closure of finding 1 requires that test to reject the contradictory cross-section headline while accepting the unmodified pack.

### 2. Producer-specific operands — resolved

All three retained cases in `<review-workdir>/ravel-review-certificate-probes.py` reject:

- Missing shape generator with a declared shape producer and conflicting primary value: `shape prediction needs current producer evidence and a mu95 quantity`.
- Shape generator with an acceptance producer: the same rejection.
- Shape scalar equal to the normalized comparison but canonical expected median different: `shape primary limit representation is inconsistent: expected scalar median conflicts with typed limit`.

At initial `certificates.py:277-304`, the adapter is selected from either the producer declaration or the recognizable document representation, and incompatible combinations cannot avoid the check. The shape path invokes the canonical reader; acceptance requires its unique computed SR row. The expanded suite includes successful approved central comparisons, successful producer-derived acceptance, stale artifact/plan rejection, and existing shape writer controls. It passed.

### 3. Projection observed semantics — resolved

Independently executed both production command paths with a substituted engine result having observed = median = 0.5 and five resolved expected slots. Counting `cmd_counting` and likelihood `cmd_likelihood` both now emit:

```json
{"value": null, "status": "missing", "bracket": null}
```

in the observed slot. `point_value(record)` and `read_limits(record).observed.exclusion()` both return None. `point_value(record, "expected")` remains 0.5, the original engine observed diagnostic is retained at 0.5 in `diagnostic_observed`, and its role says either Asimov diagnostic or scaled-data proxy. `claim_errors` is empty for each correct output. A genuine observed engine result still returns observed 0.5 and exclusion True, demonstrating that the repair does not suppress ordinary observed limits.

`project_limits.py:117-127` implements the shared conversion; both CLI routes call it. Existing tests also retain expected censoring and numerical evidence.

### 4. Negation and positive targets — resolved for the reported cases and controls

The retained ordinary-language matrix now produces:

| Case | Actual |
|---|---|
| `do not want ... reproduce A and scan ...` | unsupported, no targets |
| `neither reproduce A nor scan ...` | unsupported, no targets |
| `do not reproduce A, but scan ...` | scan |
| `do not reproduce A; scan ...` | scan |
| ambiguous `do not scan ... and reproduce A` | conservative unsupported |
| `do not survey ATLAS ...; reproduce CMS ...` | reproduce with CMS target only |
| `do not merely survey ...; reproduce A` | reproduce with A target |
| `reproduce A and never claim discovery` | reproduce with A target |

The parser no longer splits bare coordinated `and` actions before resolving a negated clause. Router target extraction uses the same actionable text as scientific intent. All returned contracts retain approval requirements. These checks establish faithful handling of the concrete constructions, not a universal natural-language inference guarantee.

### 5. Supplied host discovery objective — resolved

The original correctly hashed and literally quoted interpretation that introduced a discovery objective after `Survey collider searches. Do not claim discovery.` now raises `ValueError: interpretation requests a discovery claim outside the supported scientific scope`.

The old regression script exits 1 at this final case because it originally printed the accepted result without catching exceptions; this is the expected repaired behavior, not a new test failure. It was not edited. The maintained pytest regression explicitly expects this rejection and passes. Valid unfamiliar-language host intake still passes as a zero-compute draft without a new approval. Grounding and the router now share the analysis/arXiv/Inspire identifier grammar.

### 6. Capability headline fidelity — resolved

Live reads confirm P1 and P4 are `partial`, each has a decision gate requiring its actual full deliverable/lifecycle evidence, and prior component measurements remain explicitly historical. `docs/development/status.md:17` reports 0.50 reference-task coverage, 0 of 7 fully served, 7 partial, and no autonomous/scientific correctness percentage. P1/P4 board rows are partial. This matches the registry's definition and the evidence already present without demanding a new physics campaign.

## Focused verification

Executed from the DSRLab parent:

```sh
PYTHONPATH=hep-agentic-pipeline/src <review-workdir>/ravel-cli-clean-env/bin/python -m pytest -q hep-agentic-pipeline/tests/unit/test_certificates.py hep-agentic-pipeline/tests/unit/test_limit_transport.py hep-agentic-pipeline/tests/unit/test_semantic_intake.py hep-agentic-pipeline/tests/unit/test_shape_fit_json.py hep-agentic-pipeline/tests/unit/test_cli_initiate.py
```

Result at initial repaired snapshot: **151 passed, 1 skipped, 14 dependency deprecation warnings**, in 25.09 seconds. The skip is the explicit release-only installed-wheel test because `RAVEL_TEST_WHEEL` was not set. The earlier `test_real_execution_receipt_staleness_blocks_harvest` failure now passes in this suite.

## Final verification addendum

Finding 1 is now fully resolved for the reported curve-transport and derived-arithmetic cases. The exact `<review-workdir>/ravel-review-derived-headline-probe.py` positive control continues to accept sigma_UL = 800 fb. Replacing it with 0.001 fb now produces:

```text
SOURCE: ['sigma_ul_ours_fb does not match its primary operands (expected 800.0)']
CERT: FAIL, served result is not bound to certified statistics
MATH: FAIL, result.json: sigma_ul_ours_fb does not match its primary operands (expected 800.0)
```

`result_pack.py:442-473` now implements shared mathematical headline derivation. Both generation and verification use it for sigma_ref = 1000 × sigma_LO × k, sigma_UL = resolved mu95 × sigma_ref, driving-SR signal events, S95, and the numerical baseline. `headline_errors` at `:476` rereads the pointed-to operands and checks advertised derived fields. Test coverage includes individual derived-field disagreement and a coherent cross-section/reference/limit edit that disagrees with actual provenance. A caller-supplied cross section without a primary rate remains explicitly a declared input; passing arithmetic does not independently validate the cross-section prediction.

All original producer regressions were rerun and reject. The full saved pack/intake script was rerun unchanged through a wrapper that catches only its newly expected discovery-rejection ValueError; every denial, positive conjunction control, target selection, and source mismatch behaved as recorded above. Projection implementation hashes remained unchanged from the separately verified production-command tests. The live P1/P4 statuses and generated headline remain corrected.

The same five-file focused test command was rerun after the final repair: **161 passed, 1 skipped, 14 dependency deprecation warnings**, in 26.97 seconds. The single skip remains the explicit `RAVEL_TEST_WHEEL` release opt-in test. `git diff --check` passed.

The final `git diff --binary` SHA-256 is **`74203d07bf76ebfd9b2501b8a944230247afffa333df8c5be0e4141249d95300`**. It was identical before and after the final tests. HEAD remains `8d8b4b53b358c9798ae9b0d6345919c907b8639e`; this verifies uncommitted source, not an already published revision.

Final source/test fingerprints follow. These include new files omitted from Git's ordinary tracked diff.

| File | Final verified SHA-256 |
|---|---|
| `src/ravel/limits.py` | `ccf9d320965f8062c9e63b26db073f8a43918067c656505a20681bc3b0291e17` |
| `src/ravel/validation/certificates.py` | `18814c4aabe3e69d7229e0970b56242a305c34cc5a67c2d4a516e5c13be29e32` |
| `src/ravel/workflow/intake.py` | `67ae32113861294bc4661ce7db3c82d9085de0db8c1b74346111160bcea7b57b` |
| `src/ravel/workflow/route_prompt.py` | `a6fa0bca512ea808a9d46af6369239d11e46646c3b77b0e09599a0ebe8d3d712` |
| `src/ravel/workflow/result_pack.py` | `554ff066cb2a67cfa777f61a99f51505cab35d00747d87fc6a718abdc724fa3d` |
| `src/ravel/workflow/scan_orchestrator.py` | `16ea96140671cee96a70bd80a53ff614f79a3eb27483a34174fc13620f0740e8` |
| `src/ravel/physics/project_limits.py` | `17f5984cfb06677bb36be103e23978ab0789e6e790a751d0c5cb319e94e0dc7c` |
| `src/ravel/validation/validate_run_state.py` | `5a51fd0942867d192e1868acca66d3587df28826f3a420a1eb18e78ce29ae73b` |
| `src/ravel/validation/validate_task_contract.py` | `24123e7fc6eb39d8b33c18c2213a477dfda842cda41fecebb96efd49db88dd2e` |
| `src/ravel/validation/verify_pack.py` | `cc437b1d6204185791a40974b7fdf93480e3d8e2381754a8d9e2637fe70c0048` |
| `benchmarks/capabilities.json` | `ff49a580d8e484021fa9f4bc5b47adfde89d0c416b50ba580f1da122fb26b3e2` |
| `docs/development/status.md` | `91b2395e42499318a75c8fe814b6119c86ff037a02fd8da3a5369d1b1357419b` |
| `tests/unit/test_certificates.py` | `0ad231b7338df9289e209b58a51ec5afb15a37fe3aa0bb84d75a279426573a02` |
| `tests/unit/test_limit_transport.py` | `f8d2fd4c6d33863424894b2937230f1c39307334e6e70b6858dfdce464513709` |
| `tests/unit/test_semantic_intake.py` | `1d876fe8023935909eb91a90a3789de50761be8ae5f463c132994120528a11d0` |
| `tests/unit/test_shape_fit_json.py` | `3f50733c03fe62bfc049b768402723ce53cb38a3a997e9a8431b81df16068c96` |
| `tests/unit/test_cli_initiate.py` | `5e0548143c1b461c9cf72374fed215801272656c7630afb0dc914130e812634d` |

There are no unresolved items among these six findings at this snapshot. This conclusion is limited to the concrete scientific representation, comparison consistency, and intent-routing scope reviewed here. Full repository/release validation, native execution evidence and scientific calibration remain distinct evidence obligations.
