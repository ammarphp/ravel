# Scientific result and certification contracts

Ravel records three separate questions: whether an inference calculation produced a numerical limit, whether a declared comparison agrees with its reference, and whether the broader scientific model is valid. A resolved root answers the first question. An artifact-bound certificate answers a scoped version of the second. Neither establishes statistical coverage or detector fidelity by itself.

## Limits retain their meaning

`src/ravel/limits.py` defines the versioned `limits` object used by engines, packs, scan harvesting, projections and plots. It contains one observed curve and five ordered expected slots, corresponding to −2σ, −1σ, median, +1σ and +2σ. Every slot retains its value, status and bracket.

| Status | Meaning | Use in a contour or comparison |
|---|---|---|
| `resolved` | A numerical crossing supported by the emitting engine's checks | Eligible as a root; inspect model and certification scope separately |
| `below_scan` | The crossing lies below the evaluated range | Preserve the upper bound; never draw the endpoint as a measured crossing |
| `above_scan` | The crossing lies above the evaluated range | Preserve the lower bound; never draw the endpoint as a measured crossing |
| `missing` | The slot was not calculated or is unavailable | Keep a null slot and retain the case in coverage accounting |
| `unverified` | A new reported value lacks the required numerical evidence | Hold numerical-root claims |
| `legacy_reported` | A historical scalar has no recorded numerical crossing evidence | Explicit historical comparisons only; no live numerical certification |

For example, an observed upper-limit scan that reaches μ=100 without crossing CLs=0.05 stores `value: 100`, `status: above_scan`, and `bracket: [100, null]`. The bound can establish that the μ=1 hypothesis is not excluded by this upper-limit test. It cannot establish a root at μ=100 or that the model is allowed by all data.

Scalar compatibility fields must agree with the typed representation. Known censoring flags cannot be removed by copying a value into a preferred headline field. Rescaling preserves statuses and scales brackets with the values. Censored expected bands are not filled as ordinary uncertainty bands. Missing and failed points remain part of the planned population.

Expected-only projections expose a missing observed slot. Their Asimov or scaled-data diagnostic is retained separately with its role, so a generic observed-limit consumer cannot turn a projection into an observed exclusion.

Result packs also carry a `limit_source` identity binding to the exact run-relative primary inference file and its byte hash. Live gates compare all six curves, statuses, brackets and overlapping scientific identity/diagnostics with that source. A coherently rescaled pack still fails if it disagrees with its certified source. An arbitrary stated correction factor is not a verified transform. Post-hoc scan transformations remain separately scoped and do not acquire live certification from a pack identity binding.

Pack validation also recomputes advertised cross-section limits, S95 and driving-region yields from their primary operands. For example, sigma_ref in fb is 1000 × sigma_LO in pb × the declared correction, and sigma_UL is the resolved mu95 × sigma_ref. A declared cross section is still a scientific input requiring its own provenance; arithmetic consistency does not validate its prediction.

Fresh shape fits require successful finite optimizers and a finite crossing bracket for a resolved observed or median root. Expected band slots the engine did not calculate remain missing. The shape output explicitly retains its calibration limitation. The transport layer verifies consistency; it cannot prove that a manually supplied input came from a trustworthy generator.

## Artifact-bound comparisons

`src/ravel/validation/certificates.py` creates and verifies R5 and acceptance comparison certificates. A live certificate requires all of the following:

- An approved task contract pins the comparison plan's path and SHA-256. Approval binds the contract, CHECK-IN 1 and budget bytes.
- The plan names the analysis, quantity, units, process/normalization basis, policy, dependencies and every output it can support.
- Each predeclared point resolves to a prediction and a pinned reference record with matching identity and parameters. Exact-point policies reject nearest-node and interpolated substitutes.
- Every planned comparison is evaluated. Missing rows, repeated identities and failed rows cannot disappear from the denominator.
- Current reference, dependency, prediction and served-output bytes match the certificate. Changing a tolerance or reference requires updating the plan and recording a new actual approval.

R5 requires at least two distinct declared masses. Acceptance requires the predeclared signal-region/point comparisons relevant to the claim. The mechanism checks the declared plan; selecting a scientifically adequate reference population and dependency set remains a review obligation.

Use the same commands for either kind, with a plan whose `kind` is `r5` or `acceptance`:

```bash
python scripts/run.py ravel.validation.certificates pin-plan \
  --rundir RUN --plan inputs/r5-plan.json
# Present the pinned comparison plan and record the actual approval.
python scripts/run.py ravel.workflow.workflow_state approve \
  --rundir RUN --plan none --quote 'the actual approval text'
python scripts/run.py ravel.validation.certificates create \
  --rundir RUN --plan inputs/r5-plan.json --out outputs/r5-certificate.json
python scripts/run.py ravel.validation.certificates check \
  --rundir RUN --certificate outputs/r5-certificate.json --kind r5 --live
```

The `none` plan supports an approved static comparison. It cannot authorize a smoke run or generation. Use the actual approved execution rung when compute is part of the task. Approval records establish integrity of the recorded instruction, not independent human authentication.

The complete plan schema and passing/failing fixtures are in `tests/unit/test_certificates.py`. Plans specify `dependencies` as path/hash entries, `subjects` as run-relative output paths, and `comparisons` as identity/parameter records with prediction and reference JSON pointers. Reference entries include a byte hash. Prediction/reference operands carry their own analysis, quantity, units, basis and value. Do not replace a real reference with a fixture.

The shape writer accepts `--validation-context` to attach declared point identity to the value it actually computes. Acceptance producers accept `--certification-context`, mapping reported regions to their declared identities. Existing diagnostic reports remain readable. A bare `PASS`, `in_tolerance: true`, Markdown checkmark or old ladder record cannot authorize fresh serving.

## Comparison policy and remaining scientific work

The central-value policy checks the deterministic relative residual against the approved tolerance. A precision policy also requires declared standard uncertainties, distinct independence groups, a precision cap and a conservative residual-plus-uncertainty criterion. It does not infer covariance or prove independence. Correlated comparisons need a supported covariance-aware method. Coverage/calibration claims are not accepted as certificate policy labels.

Original publication truth, detector-model adequacy, nuisance construction, frequentist coverage, and performance on held-out tasks require their own evidence. Keep these obligations visible even when every software integrity check passes.
