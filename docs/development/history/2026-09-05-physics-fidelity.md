# Physics fidelity, numerical inference, and usable demonstrations

This pass expands the public entry point and corrects independently reproduced
physics, numerical, and reporting failures. It follows the repository-layout
migration. It does not rewrite historical scientific results or claim that all
analyses are now certified.

Development began at `b0e09467be0f0d38ff0e26369605051ada27fbd9`, with public main
at `eed98d374b2ff660d378ed37ccc42bdd9090d307`. The public checkout initially matched
the preceding curated export; the source additionally retains private run inputs,
full simulation artifacts, tool installations, and historical planning records.
The final distribution contains the active implementation, tests, guides, and
selected audits. It does not copy private simulation directories wholesale.

## Entry point and repository operation

The README grew from 281 words into a substantive entry point with:

- a concise purpose and documented scope;
- real figures, a compact evidence table, and artifact links;
- hash-locked installation and a runnable cached replay;
- draft task initiation and structural contract validation;
- a plotting demonstration that writes fresh outputs and input/output hashes;
- the native-toolchain route and an explanation of what approval and validation mean.

`ravel initiate` wraps the existing deterministic router. It preserves the request,
validates its draft contract before writing, and initializes the existing lifecycle
ledger. It refuses blank or unsupported requests, invalid contracts, and existing
destinations. A state-write failure returns nonzero and retains partial evidence.
It does not create approvals, invoke an LLM, or launch generation.

Quantitative claim markers in the README are checked against the same registry as
the detailed validation page. The README selects a subset; the detailed page must
still include every verified registry claim. Five active scan specifications had
old template paths. Their path fields now reference the canonical package template;
all five are exercised through the actual dry-plan command. Mass grids, original
cards, and historical scan manifests are unchanged.

## A measured physics correction

The eRJR three-lepton implementation formed a boost-dependent quantity using
boosted leptons but an unboosted reconstructed invisible momentum. The
[ATLAS paper, section 5](https://arxiv.org/abs/1912.08479), specifies the transformation
for both. The corrected production calculation applies the same Lorentz boost to
all components. Independent invariant checks and a retained-event differential
separate the definition from implementation parity.

| Same 200,000 retained C1N2 events | Before | Corrected |
|---|---:|---:|
| SRlow selected events | 43 | 95 |
| SRlow acceptance | 0.000215 | 0.000475 |
| Relative shortfall from published acceptance | 65.2% | 23.1% |
| SRISR selected events | 19 | 19 |

The existing acceptance threshold still returns **FAIL**. The change is attributable
to one expression because the input events and all other cuts were held fixed.
It is not evidence of improved detector simulation, a new event sample, or general
agreement with ATLAS. The
[differential audit](../../../evidence/audits/2026-09-05-native-fidelity/README.md)
contains stage counts, event identifiers, input hashes, and a reproduction command.
The reference search itself uses eRJR; attributing the discrepancy to “full RJR
versus emulation” was not supported by the paper.

The squark and gluino retained samples reproduce their original selection counts,
but their differences from published cutflows are spread across multiple stages.
They remain unresolved fidelity questions. The compressed-slepton mass-plane
residual belongs to a different analysis and remains 24.9% in this pass.

The native generic adapter also now applies declared signal eta and identification
requirements, refuses identification information unavailable from Delphes, and
preserves nominal event weights. Native output writers carry raw counts, sumw and
sumw2 instead of assuming a uniform positive weight. Signed/nonuniform fixtures
exercise those bookkeeping changes. The retained certification samples use
uniform positive weights, so this was a latent robustness problem rather than the
cause of their observed residuals.

## Numerical inference and acceptance reporting

A controlled counting example, with observation/background 10, background
uncertainty 2, signal 5 and only five CLs scan points, exposed a numerical issue:
the old interpolated limit was 1.850559, versus approximately 1.658748 from a
refined pyhf crossing. The 11.6% discrepancy came from scan discretization.

The updated engine refines bracketed CLs crossings to an explicit tolerance,
records each observed/expected crossing status and bracket, distinguishes measured
roots from floors and scan ceilings, and rejects invalid interiors. It preserves
the input nuisance model; independent counting uncertainties remain an explicit
assumption rather than invented correlations. Input validation rejects negative
uncertainties, nonfinite values, and invalid normalization. Named best-fit
parameters and proximity to bounds are reported where available; missing covariance,
pulls, and calibration studies remain explicitly unavailable.

Acceptance/cutflow checks now distinguish a real zero yield from absent data,
refuse missing or incomparable driving references, and aggregate the largest
residual across every driving region. The older implementation could select the
best region while labeling it the worst. Acceptance-only reference tables are not
silently treated as acceptance × efficiency. Approximate nearest-node references
cannot confer PASS/WARN on a different mass point. Historical regression floors
and original certificates remain unchanged.

The [statistical audit](../../../evidence/audits/2026-09-05-statistical-fidelity/README.md)
records the numerical example, fit diagnostics, comparator counterexamples, and
cached benchmark replay. The full nine-case replay retains the same two missing
native-artifact provenance failures. Passing numerical regression floors does not
repair those missing inputs or convert a failing acceptance comparison into a pass.

## Visualization correctness

Every quantitative scan comparison now uses the same eligibility and exact
reference matching rules. Bounds, invalid inputs, unmatched reference points,
and missing planned points have separate counts. No nearest-neighbor reference
extrapolation enters the median. A per-point JSON sidecar makes the population
and metric inspectable.

Contours use piecewise linear interpolation, bounded by their triangle vertices.
Triangles touching missing/invalid lattice vertices are masked. Isolated
refinement coordinates do not turn an entire otherwise-supported row into a
hole. Detecting an entirely absent row or column requires its planned coordinates
to be represented explicitly; a planned point count alone cannot identify its
location. This remains a limitation when incomplete scan records omit coordinates.
Disjoint one-dimensional exclusion spans remain disjoint; a sampled endpoint is
not quoted as a measured exclusion reach without a bracketing crossing.

HEPData import requires unambiguous observed/expected columns, explicit pb/fb
limit units and GeV mass units, consistent lengths, and finite physical numbers.
Booleans, ambiguous expected-band columns, duplicate coordinates, impossible mass
splittings, and nonfinite derived residuals are refused or explicitly unscorable.
Empty contours cannot be labeled as drawn. All-bound scans fail with an explicit
no-measured-limits message.

The [scan audit](../../../evidence/audits/2026-09-05-scan-fidelity/README.md) includes
fresh PNG/PDF outputs and reproduction commands. The observed comparison remains
50 matched cells out of 52 planned, with median absolute residual 24.9%; its
expected counterpart remains 24.1%. These are re-renderings of cached limits.

## What the broader landscape changes

The [pinned landscape review](../../research/2026-09-05-fidelity-and-validation-landscape.md)
identifies useful practices from MadAgents, ColliderAgent, Collider-Bench, mapyde,
pyhf/cabinetry and established recasting tools. The main lessons are silent-failure
tests, isolated stage comparisons, hidden evaluation references, complete outcome
accounting, executable examples, and diagnostics beyond a final limit curve.
No comparator code was copied.

Ravel uses pyhf and has not established superiority over it or other workflows.
The scientific target is fewer unsupported deliveries, with accurate inference
and better physics fidelity at measured cost. A matched-model numerical benchmark,
pseudo-data calibration study, and held-out physics comparison remain distinct
experiments. Further generation would need a concrete approved compute plan; this
pass uses retained artifacts and bounded software tests.
