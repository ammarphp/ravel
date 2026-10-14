# Supplied held-out numerical reference checks

The `numerical-reference-check` scientific-study mode compares retained point
values against supplied references on a complete declared held-out deck. It uses
the ordinary schema2 plan, Check-In1, supervised worker, Check-In2 and independent
review lifecycle. It never evaluates a model or fits a function.

Use it after a producer has retained numerical results: for example, the existing
`eft-functions` operation's exact response scales. A candidate that matches its
training points can still fail the held-out comparison. All failed cells remain
in the result. Missing points, extra points, omitted components, different units,
normalization, domain, basis or conventions refuse admission.

The implementation draws on the pinned BootLoops [numeric-payload identity
scanner](https://github.com/BootLoops-ai/bootloops/blob/66b680ce742e654cfe86da4f072a69061fe182b1/tools/gatekeeper/oracle_integrity.py)
and [held-out checking tool](https://github.com/BootLoops-ai/bootloops/blob/66b680ce742e654cfe86da4f072a69061fe182b1/tools/gatekeeper/heldout_cv.py).
No upstream implementation bodies or solver dependencies are copied. RAVEL's
existing group-moment and fixed model-equation witnesses remain separate.

## Inputs

The task is exactly `{"input":"comparison.json"}`. Every file pin below has
`path`, lower-case SHA256 and positive integer `size`. Paths are relative to
`comparison.json`; nested EFT source paths follow the original EFT config.
Inputs use bounded descriptor snapshots with the existing source-table reader.
The ordinary plan captures the configuration and every declared constituent,
including origin evidence; a wrapper pin does not authenticate undeclared files.

```json
{
  "schema_version": 1,
  "kind": "heldout-numerical-reference-check",
  "deck": {"path":"deck.json","sha256":"<actual digest>","size":1234},
  "candidate": {
    "id":"candidate",
    "format":"point-values/v1",
    "file":{"path":"candidate.json","sha256":"<actual digest>","size":1234},
    "evidence":[{"path":"candidate-source.txt","sha256":"<actual digest>","size":123}],
    "projection":null
  },
  "references":[{
    "id":"reference",
    "file":{"path":"reference.json","sha256":"<actual digest>","size":1234},
    "evidence":[{"path":"reference-source.txt","sha256":"<actual digest>","size":123}]
  }],
  "duplicate_reference_policy":"report"
}
```

`deck.json` has exactly `schema_version:1`,
`kind:"numerical-reference-deck"`, `context`, `axes`, `components`,
`training_points` and `heldout_points`:

- Context has literal nonempty `quantity`, `model`, `process`, `normalization`,
  `domain` and `basis`. These are supplied interpretations, not verified physics.
- Each ordered axis has `id` and `unit`.
- Each ordered component has `id`, `unit`, `convention`, `atol` and `rtol`.
  Bands are fixed nonnegative engineering tolerances, not calibrated errors.
- Each point has `id` and an ordered `coordinates` vector. Mathematical equality
  detects duplicate coordinates even under different labels, decimal spelling,
  signed zero or equivalent rational representations. The training list can be
  empty; the held-out list is nonempty. Their physical coordinates must be disjoint.

Point-value files contain `schema_version:1`,
`kind:"numerical-point-values"`, the identical `context` and `axes`, ordered
`components` (only `id`, `unit`, `convention`), and `rows`. Each row has
`id`, `coordinates` and a `values` dictionary keyed by every component ID.
Each value is exactly `{"mid":"<exact number>","radius":"<absolute radius>"}`.
The candidate supplies **all** training and held-out points; every reference
supplies **all** held-out points. Row order can differ. No implicit projection,
interpolation, unit conversion, extrapolation or missing-value padding occurs.

Numeric tokens are bounded decimal/rational strings or integers. JSON floats,
booleans, nulls, complex expressions, nonfinite values, duplicate keys and
negative radii refuse. Complex quantities need explicitly declared real/imaginary
components and conventions. Values are never rounded through binary64.

## Comparison and integrity meaning

For candidate enclosure `(c,r_c)` and reference `(e,r_e)`, the exact rule is

`abs(c-e) + r_c <= r_e + atol + rtol*abs(e)`.

Thus the complete candidate enclosure must lie in the reference enclosure
enlarged by the declared band. A broad candidate radius cannot make a mismatch
pass. A broad oracle enclosure can yield a weak comparison; exact-zero and
nonzero-radius enclosures containing zero are reported separately. Radii are
caller-supplied numerical enclosures; the operation does not derive or certify
them as rigorous bounds or statistical uncertainties.

The result contains every exact residual, band, excursion, allowance and outcome,
the complete point/component/reference census, origin pins and resource counts.
Reference content digests canonicalize rationals and coordinate order while
ignoring reference labels and numeric spelling. Duplicate reference files and
duplicate component response vectors are reported. `refuse` makes duplicate
whole-reference payloads fail the declared content policy; `report` retains them
as an integrity observation. Identical correct values are possible for genuinely
independent algorithms. Neither duplication nor distinct content alone establishes
independence. Shared candidate/reference origin-evidence hashes are reported too.

`oracle_independence_proven` and `withholding_chronology_verified` always remain
false. Disjoint declared coordinates do not show that a producer never saw the
references or chose points after inspecting its result. For a genuine prospective
held-out experiment, independently retain the deck/reference/protocol before
construction, restrict producer access, and bind its observed production history
in the later ordinary review. Agreement proves only this supplied finite-deck
engineering comparison, not model validity, continuum accuracy or inference.

## Existing EFT response consumer

For an existing retained `eft-functions.json`, use
`format:"eft-functions/v1"` and a projection with exactly `configuration` (the
original EFT config pin) and `component_map` (deck component ID to source function
name). The complete delivered function basis must be mapped one-to-one. Components
are dimensionless; the sole axis is the delivered POI with its exact coefficient
unit. The deck basis equals the original `one_coefficient_basis` text. Original
model/card byte hashes and every configured/evaluated point are checked; all are
ordinary inputs. The consumer reads retained values only and imports no EFT
parser/evaluator. Retained source association is not requalification of the
producer, native likelihood, response applicability or oracle independence.

## Resources and ordinary delivery

The closed operation allows at most four axes, 32 components, 1000 points per
partition, eight references and 64,000 admitted candidate/reference cells.
Each input is at most 4MiB; at most 128 distinct files and 32MiB total input bytes
are admitted. Numeric tokens are at most 512 characters with decimal exponent
magnitude at most 128 and rational numerator/denominator bit length at most 4096.
The exact comparison is linear in the declared cell population; there is no
optimizer, native backend, stochastic sampling or extra process pool.

Use `ravel plan --rundir <fresh-run> --spec <science.json>` with schema2 mode
`numerical-reference-check`, an explicit review policy, one attempt and the
normal bounded `max_seconds`. Planning performs source/shape/census intake, not
the held-out numerical comparison or scientific acceptance. Approval and run use
the standard scientific-study route. The worker owns a fresh
`outputs/attempt-1/numerical-reference-check/` child, records the complete JSON,
a report and Check-In2. A mismatch is a failed result; no retry or tolerance change
is implied. Large full decks can exceed generic review snapshot caps; their exact
full files remain output inventory entries and need explicitly bound review
constituents rather than a claim that a small summary contains every cell.

Portable controls use fabricated retained values, a real ordinary plan and the
real worker/adapter/report with only authority mocked. Empirical oracle accuracy,
genuine withholding and installed backend comparisons require separately
approved experiments and their actual retained evidence.
