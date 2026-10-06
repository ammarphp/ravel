# Retained RRR likelihood refits and omission controls

These retained calculations identify a large numerical defect in one historical
limit, small numerical changes at two other anchors, and an unresolved fit at a
fourth. A separate ATLAS signal-template control reproduces the published central
limits at one mass point to approximately 0.03% observed and 0.93% expected. Removing
signal nuisance modifiers and then control-region signal changes those limits.
These are local statistical diagnoses. They do not close the native reproduction
campaign, establish statistical coverage, or justify transferring ATLAS nuisance
parameters to another signal template.

No inference or event generation is performed by the summary or its validator.
The original driver, inputs, results, partial attempts and failure logs are
retained. [summary.json](summary.json) contains the unrounded arithmetic and source
hashes. [refit-comparison.png](refit-comparison.png) shows the two comparisons with
observed and expected roles kept separate.

## Native fixed-template anchors

The four anchors use the archived native signal patches and the same retained
background. Three have resolved observed and all five expected roots. The
150/130 GeV anchor fails the monotonicity check twice and has no replacement limit.
It stays in the four-anchor denominator.

| Parent / LSP mass [GeV] | Legacy raw observed μ95 | Refit raw observed μ95 | Observed change | Legacy raw expected median μ95 | Refit raw expected median μ95 | Expected change |
|---|---:|---:|---:|---:|---:|---:|
| 50 / 45 | 0.0959401485032 | 0.0478637928167 | −50.1108% | 0.0963195216141 | 0.0683306298829 | −29.0584% |
| 100 / 98 | 0.511075176265 | 0.507741882979 | −0.6522% | 0.414431197811 | 0.409864139196 | −1.1020% |
| 150 / 130 | 0.640039039931 | Failed | — | 0.579410789383 | Failed | — |
| 200 / 180 | 0.831823206114 | 0.822599669384 | −1.1088% | 1.07407963105 | 1.05812812831 | −1.4851% |

The raw signal strengths multiply their native patch yields. They must not be
compared directly with ATLAS signal strengths, which multiply a different signal
template and rate. The existing historical normalization is held fixed for the
cross-section comparisons below. If the historical conversion is
σ95 = C μ95, then

```
C = historical normalized observed μ95 × historical σref / legacy raw observed μ95
new σ95 / old σ95 = new raw μ95 / old raw μ95
```

The summary independently checks that the observed and expected historical
conversions give the same C and reproduce the retained comparison context. This
preserves a historical mapping; it does not validate the physical assumptions
behind that mapping.

| Parent / LSP [GeV] | Observed σ95 [fb], old → refit | Observed residual to published reference, old → refit | Expected σ95 [fb], old → refit | Expected residual, old → refit |
|---|---:|---:|---:|---:|
| 50 / 45 | 989.7771 → 493.7921 | +87.8420% → −6.2871% | 993.6909 → 704.9404 | +40.5225% → −0.3111% |
| 100 / 98 | 348.1421 → 345.8715 | +46.1983% → +45.2448% | 282.3086 → 279.1976 | +38.4137% → +36.8884% |
| 150 / 130 | No replacement | Unresolved | No replacement | Unresolved |
| 200 / 180 | 45.4458 → 44.9419 | −42.3035% → −42.9433% | 58.6812 → 57.8097 | −25.5900% → −26.6951% |

At 50/45, C = 10316.609687784132 fb per raw μ and the observed ratio is
0.4988922110658769. The recorded direct JAX check gives CLs =
0.0006037915682167335 at the old raw μ = 0.0959401485031872, far from the target
0.05. The new observed root is therefore not simply a change of cross-section
convention. Conversely, the small refit changes at 100/98 and 200/180 leave large
residuals. A single numerical explanation does not account for all three cells.

The historical scalar inversion and the guarded refit differ in numerical
procedure. This audit diagnoses the discrepancy on fixed templates; it does not
assign the entire difference to one implementation detail independently of the
optimizer, initialization and interpolation behavior. The broader retained-event
and normalization diagnosis is in the
[companion audit](../2026-09-05-rrr-diagnosis/README.md).

## Numerical checks and unresolved attempts

The resolved records use asymptotic CLs with the one-sided q-tilde statistic and
Brent root refinement. Their stored metadata specify relative root tolerance
10⁻⁴ and absolute tolerance 10⁻¹⁰. The summary checks that every reported root is
present among the actual retained evaluations, has a crossing bracket, agrees
with both canonical and compatibility fields, and evaluates to CLs = 0.05 within
an absolute tolerance of 5×10⁻⁴. This is a numerical consistency tolerance, not a
physics fidelity tolerance. The largest retained six-curve residuals for the three
native anchors are 1.90×10⁻⁶, 1.75×10⁻⁶ and 4.15×10⁻⁶ respectively.

The JAX refits used 44, 42 and 39 sampled μ evaluations, taking approximately
171, 133 and 136 seconds. A sampled μ evaluation invokes multiple profile fits;
these counts are not individual minimizer-call counts. These timings are
retrospective observations, not general runtime benchmarks.

Two separate NumPy/guarded-optimizer checks reevaluate the observed roots:

| Anchor | Raw μ checked | NumPy observed CLs | Absolute error from 0.05 |
|---|---:|---:|---:|
| 50 / 45 | 0.0478637928167 | 0.0500019169844 | 1.91698×10⁻⁶ |
| 100 / 98 | 0.507741882979 | 0.0499999200545 | 7.99455×10⁻⁸ |

Both logs record escalation from untrusted SLSQP fits to guarded iminuit MIGRAD.
These are useful checks across tensor backends and minimization behavior. They
use the same likelihood and pyhf implementation, so they are not an independent
statistical formulation, independent detector simulation, or coverage study.
Their `expected_cls` arrays are expected CLs values evaluated at the observed μ;
they do not constitute independent checks of the five expected roots. No NumPy
check for the 200/180 anchor is retained.

The [first 150/130 attempt](logs/m150_dm20-jax-refit.log) and the
[tighter retry](logs/m150_dm20-tight-refit.log) both end with
`CLs observed or expected curve is not monotonically decreasing`. Both contain 55
logged scan evaluations before rejection. The associated fit tolerances are
10⁻⁷ and 10⁻⁹, respectively, based on the retained drivers and run declarations;
the failure logs do not embed full invocation or input-hash records. No scalar is
recovered from the partial scan. Also retained are earlier incomplete NumPy
refit logs for 50/45 and 100/98, each stopping after four scan evaluations. Those
logs do not establish why execution stopped and are not counted as completed
refits.

## Published ATLAS signal patch at 150/130 GeV

The patch metadata identify ANA-SUSY-2018-16, degenerate selectron/smuon left and
right chiralities, and parent/LSP masses 150/130 GeV. The published model and
reference data are associated with
[HEPData ins1767649](https://www.hepdata.net/record/ins1767649).
The benchmark normalization in the retained comparison context is
σref = 174.232472 fb. Thus the published central limits correspond to

```
observed μ95 = 128.33 / 174.232472 = 0.7365446780781484
expected μ95 = 139.16 / 174.232472 = 0.7987030109978580
```

The full published signal patch gives observed μ95 = 0.7363356850527608
(128.293586628556 fb, −0.0283748% residual) and expected median μ95 =
0.8061058733783046 (140.449819012421 fb, +0.9268605% residual). This is central-limit
agreement at one anchor on an equivalent numerical background model. It does not
establish global closure, agreement of every expected quantile, or frequentist
coverage. The native 150/130 failure uses a different signal patch and remains
unresolved despite this successful published-template control.

The retained mapyde background and the original published background have
different byte and pyhf canonical digests. The original
[background-official.json](inputs/background-official.json) matches the patchset's
declared canonical SHA256
`7f3c55fc8985618b8190047100942847c8ee6e2f4db261356e3ea3394855bc42`.
The retained background canonical digest is
`0c95a4e37ce618c77789e243c0f161e09ebe61a84e32527428740ef180e45a1e`.
The difference is 24 equal integer/float representations such as `0` versus `0.0`.
Every numeric value, list position, key and nonnumeric value agrees. The summary
checks this recursively and rejects changed numeric values or Boolean/number
substitutions. This resolves the apparent background-identity discrepancy at the
numerical model level without claiming byte identity. Extraction and model-array
checks are retained in
[background-equivalence.json](inputs/background-equivalence.json).

## One-anchor omission controls

The first control removes every modifier from each added signal sample except
the `mu_SIG` normfactor. The signal's nominal values remain exactly equal in every
channel. This removes 867 modifier instances across 32 added signal samples,
including `histosys`, `normsys`, `lumi` and `staterror`. It is an aggregate
counterfactual: the observed change cannot be assigned to a particular nuisance
or to MC statistics alone. Background nuisance modifiers remain unchanged,
including background uses of nuisance names that also occurred on signal.

The next control removes the six control-region signal additions and preserves
all 26 remaining signal-region additions exactly. The control-region data,
background samples and background constraints remain in the likelihood. The
operation removes signal contamination in those regions, not the control regions
themselves. At μ = 1 the removed nominal CR signal sums to 49.1311342716217 events;
the retained SR signal sums to 63.2768300846219 events. These are yield sums, not
measures of the individual regions' statistical influence.

| Signal treatment | Observed μ95 | Expected median μ95 | Observed change from preceding control | Expected change from preceding control |
|---|---:|---:|---:|---:|
| Full published signal patch | 0.736335685053 | 0.806105873378 | — | — |
| Remove signal nuisance modifiers | 0.696531920125 | 0.768145930797 | −5.4057% | −4.7091% |
| Then remove CR signal | 0.635605163816 | 0.709768888351 | −8.7472% | −7.5997% |

Relative to the full patch, both omissions together change the observed limit by
−13.6800% and the expected limit by −11.9509%. These are ratios of successive
limits; the sequential percentages must not be added. Relative to the respective
published references, the final residuals are −13.7045% observed and −11.1348%
expected. The plot uses this latter reference denominator, while the table above
uses the preceding-control denominator.

The retained native patches have only a signal-strength normfactor and no
signal MC-statistical nuisance. The published-template controls demonstrate that
signal modeling choices matter at this anchor. They do not determine the effect
for the different native templates or across the mass plane. Applying the ATLAS
modifiers to native events without constructing and validating their response
would not be supported by this experiment.

## Provenance and artifact boundaries

The three native JAX refit JSON records embed the exact retained background and
patch SHA256 hashes. They do not embed execution-time dependency, engine or driver
versions. Their original [probe source](inputs/probe_refit-source.txt) is retained
as historical context. The two NumPy observed checks and the old-m50 direct
evaluation lack embedded input hashes; their association with inputs is
retrospective through the tag, identical tested μ, logs and saved source. This
weaker provenance is stated in each summary record. A manifest created now binds
the retained bytes; it cannot retroactively attest how an earlier process ran.

The three ATLAS control records embed input hashes, Python/backend/dependency
versions, and engine/driver hashes. They record Python 3.14.5, pyhf 0.7.6,
NumPy 2.4.6, SciPy 1.17.1 and JAX/JAXlib 0.10.1. The full-patch run identifies the
[initial driver](inputs/initial-driver-source.txt); the two omission runs identify
the retained [refit.py](refit.py). Both driver versions are preserved and their
recorded hashes are checked. Fit tolerance is 10⁻⁷ for these retained runs. The
current driver's default is 10⁻⁹, so reproducing the retained protocol requires
explicitly specifying `--fit-tolerance 1e-7` where applicable. Native probe runs
also differ in maximum minimizer iterations from the durable driver.

The retained comparison context preserves source-scan and reference-grid hashes.
The reference grid is the sibling
[atlas-limit-grid.yaml](../2026-09-05-scan-fidelity/atlas-limit-grid.yaml), with
SHA256 `22512c78fe0febd8103aa4efeb050d4b8b50c21dd79e649815ca9104aa151248`.
No plot overlay role is inferred from the visual resemblance of RRR paper dots.
The observed and expected comparisons here use explicitly labeled reference
columns.

## Reproduce and validate the retained summary

From the repository root, the read-only validator needs only Python's standard
library and performs no fits or rendering:

```sh
python evidence/audits/2026-09-05-rrr-refits/summarize.py --check
python evidence/audits/2026-09-05-rrr-refits/test_summarize.py
```

To deliberately regenerate the derived JSON and figure with matplotlib installed:

```sh
python evidence/audits/2026-09-05-rrr-refits/summarize.py --write
```

`--write` does not change inputs, original results, logs or `refit.py`. It also
does not silently replace the manifest. After reviewing an intentional artifact
change, explicitly reseal and validate it:

```sh
python evidence/audits/2026-09-05-rrr-refits/summarize.py --seal --check
```

[manifest.json](manifest.json) covers the folder's files, including this narrative
and plot, except itself and Python bytecode caches. Validation checks exact file
inventory, sizes and SHA256 digests, then reconstructs `summary.json` exactly. The
negative controls cover input substitutions, coherent unsupported scalar changes,
missing failure evidence, unreviewed extra results, altered nominal yields in an
omission control, normalization disagreements, Boolean/numeric equivalence errors,
and false summary counts even after resealing. No artifact exceeds 5 MB and no
personal absolute paths are needed for reproduction.

The passing validator certifies consistency of this retained audit bundle. It
does not certify a native exclusion result for serving or publication as a
validated physics reproduction.
