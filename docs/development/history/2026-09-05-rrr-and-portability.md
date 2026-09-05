# RRR diagnosis and native portability

This follow-up diagnoses retained compressed-slepton results, tests cached
likelihoods, repairs contour-family selection and removes macOS assumptions from
native setup/build helpers. It also records a public-analysis expansion survey.
No events were generated, no installed HEP toolchain was rebuilt, and no original
scan, card, baseline or scientific log was rewritten.

The [main diagnosis and research program](../../research/2026-09-05-rrr-diagnosis-and-research-program.md)
states the scientific interpretation and next experiments. This record preserves
the implementation, bounded verification and unresolved results. The earlier
[v0.4.0 architecture verification](2026-09-05-architecture-hardening.md) remains a
separate dated release result. This follow-up's final source and separate
wheel/fidelity checks pass as recorded below; public-export and remote-CI results
remain pending, not inherited from that release.

## Retained-campaign findings

The [forensic audit](../../../evidence/audits/2026-09-05-rrr-diagnosis/README.md)
contains **156 campaign-point records**, comprising three campaigns on the same
52-point grid. This is not 156 distinct mass points. Its frozen extraction can be
replayed without private run directories or a native toolchain. The verification
record rehashed 1,627 archived/reference files and found no changed originals.

The audit preserves these historical observed summaries:

| Campaign | Eligible / planned | Signed median residual | Median absolute residual |
|---|---:|---:|---:|
| Original cteq6l1, old preparation | 50 / 52 | −22.72% | 24.92% |
| nn23nlo rescan, later preparation | 50 / 52 | −15.65% | 20.77% |
| Later cteq6l1, later preparation | 52 / 52 | −13.22% | 14.01% |

These populations reproduce the historical scalar/flag accounting; they do not
certify converged roots or complete detector exposure. All three campaigns used
interpolation between retained CLs samples. The low-mass `(50,5)` red cell is
particularly sensitive to a broad first interval. Its color denotes a larger
relative upper limit, not an event excess, discovery significance or a
contradiction with `mu95 < 1`.

Four nn23nlo-rescan points processed only 233, 221, 206 and 230 detector events,
although their shower and cutflow records said 20,000. Two already carried cap
flags; two remained ordinary comparison scalars. Four targeted regressions now
verify that incomplete or duplicated detector exposure stops the current
converter before conversion. Historical results are not mechanically rescaled
to repair unknown missing-event selection.

The original-versus-rescan comparison also changes effective preparation and
sampling, lacks the first two campaigns' effective run cards, and does not retain
paired events establishing a controlled PDF comparison. Some rescan normalization
metadata apply a correction twice, but the final inclusive-limit arithmetic
cancels that stored field. A k-factor-only explanation of the final residual is
therefore not supported. Acceptance conversion, selected flavour content,
generation-cut coverage and finite-MC uncertainty remain scientific obligations.

## Cached-workspace controls and unresolved fits

The [refit audit](../../../evidence/audits/2026-09-05-rrr-refits/)
keeps native signal-template results separate from an official signal-model
control. Three of four selected native anchors yielded refined roots:

| Native anchor `(parent mass, delta mass)` in GeV | Raw-template observed root | Raw-template expected median | Disposition |
|---|---:|---:|---|
| `(50,5)` | 0.04786379 | 0.06833063 | Resolved; observed root independently checked with NumPy |
| `(100,2)` | 0.50774188 | 0.40986414 | Resolved; observed root independently checked with NumPy |
| `(150,20)` | — | — | Failed: nonmonotonic observed or expected CLs curve |
| `(200,20)` | 0.82259967 | 1.05812813 | Resolved |

These are the fitted templates' raw strength parameters. They must not be
substituted directly into an archived scan's rebased model-strength columns.
The fourth anchor's failed attempts and logs remain evidence; no new all-grid
median is inferred from the three successful anchors.

The official ATLAS degenerate-slepton signal patch at masses **150/130 GeV** gives
`mu95_obs = 0.73633569` and `mu95_exp = 0.80610587`. With the recorded theory
normalization these correspond to 128.294 and 140.450 fb, versus the exact
published 128.33 and 139.16 fb: residuals −0.028% and +0.927%. This is a strong
statistical/model-input control at one point. It is not a validation of Ravel's
generated signal acceptance.

Review caught a canonical background digest mismatch. The original cached
archive's background matches the official patchset digest; its only differences
from the retained fit input are 24 integer/float representations. An exhaustive
comparison finds identical numerical values and structure. Model parameter
configuration, observations, auxiliary data and tested likelihood evaluations
also match. The audit retains both background files and the equivalence record;
this resolves numerical model identity without claiming identical source bytes.

Removing signal nuisances from that official model changes the limits by
−5.41% observed and −4.71% expected. The nominal-SR-only omission control changes
them by **−13.68% observed and −11.95% expected** relative to the full official
model. Smaller upper limits are stronger constraints. These controlled template
changes establish that omitted signal-model structure matters at this point;
they do not assign the whole native mass-plane residual to one cause or supply
a correction factor for other points.

## Contours, workflow and research scope

`render_fig3` now retains only the requested reference contour family. The cached
demonstration supplies the published expected contour as well as the observed
one, so an expected residual panel cannot silently carry an observed reference
curve. If its matching family is absent, the panel says so. Historical scan
numbers and exact-reference populations remain unchanged.

The [reproduction closure checklist](../../workflow/checklists/reproduction-closure.md)
and statistics/scan/judgment instructions require per-point numerical and
exposure checks, complete populations and controlled comparisons before a causal
attribution or reproduction claim. The standing reference-task board is not
upgraded by diagnostic fixes.

The [public HEP analysis survey](../../research/2026-09-05-public-hep-analysis-landscape.md)
contains 26 curated candidates, 45 discovery-index entries and 16 successful
repository pins. The two analysis counts overlap. The survey's integrity check
and five adversarial rejection controls pass; **zero new scientific validations**
are credited. An index entry or pinned repository does not establish a downloaded
workspace, runnable adapter, detector fidelity or scientific closure. Four
HEPData retrieval failures remain recorded as acquisition failures.

## Native portability and independent review

The [native portability reference](../../reference/native-portability.md) documents
read-only diagnostics, architecture-aware bootstrap, explicit conda prefixes and
staged build helpers. New Miniforge installations use a pinned release and
architecture-specific checksums; existing installations are preserved. Compiler
selection uses the selected environment or explicit `CXX`, not a fixed triplet.
The helpers detect native ARM/Intel, refuse Rosetta/mixed architecture and inspect
Mach-O contents even when ROOT libraries use `.so` filenames.

Independent review reproduced one material mismatch: ROOT preflight ignored an
explicit `CXX` override although the build honored it. With a missing compiler,
the initial doctor reported ready. After repair, the same negative control
reports `root_configuration: fail`, while the real-installation positive control
still passes. The final author suite contains paired regression tests.

The review also identified incidental Python bytecode writes in isolated child
probes. Children now use `-I -B` and propagate bytecode suppression to conda/config
subprocesses. A bounded conda-version check additionally rejects a broken entry
point despite an executable file and compatible base Python. The independent
reviewer verified archive-symlink rejection before any extraction, and refusal
to replace a symlink output while preserving its owner's bytes. No outstanding
material finding remained in the bounded helper scope.

On the existing **macOS 15.5, native arm64** host, all 33 doctor prerequisites
passed, including optional RJR. Actual shower, RJR and RestFrames dry runs
resolved the installed compiler target `arm64-apple-darwin20.0.0` and the selected
SDK. No compiler invocation producing objects or binaries was run. The new CI
matrix selects `macos-15-intel`/`x86_64` and `macos-15`/`arm64`, with explicit kernel
and Python 3.12 architecture assertions. Remote job completion is pending.

No clean-Mac installation, native Intel HEP run or ABI validation was performed.
The full Delphes/SimpleAnalysis acquisition/build recipe and cross-platform
resolved native environments remain incomplete. These limitations survive a
passing fake-tool CI job.

## Bounded verification record

| Check | Result | Scope |
|---|---|---|
| Native portability author tests | 54 passed | Fake architectures/tools, overrides, absent/broken prefixes, output preservation and archive checks |
| Existing package-path tests | 2 passed | Path lookup compatibility |
| Independent portability rerun | 54 passed in 7.97 s | Final source, no inherited PYTHONPATH |
| Incomplete/duplicated detector exposure | 4 passed | Converter stops before executing conversion or writing a normalization result |
| Native doctor | 33 pass, 0 fail | Existing Apple Silicon prerequisites only |
| Build dry runs | 3 pass | Shower, RJR, RestFrames; no build |
| Shell syntax | 13 scripts pass | `/bin/bash -n` for environment/native helpers |
| Retained-campaign audit | 12 focused tests; 1,627 originals unchanged | Frozen extraction, arithmetic and population integrity |
| Publication-time RRR integrity | 4 passed | Current positive control; altered residual, missing snapshot and changed algorithm rejected |
| Cached-refit summary integrity | 9 passed | Retained-input/result bindings; no new fits |
| Survey integrity | Positive control, five rejection controls and report/link census pass | Metadata integrity; zero executed/newly validated analyses |
| Final full source suite | 1,155 passed, 2 skipped, 243 warnings in 228.48 s | Two release-only installed-wheel cases skipped here |
| Separate wheel/fidelity suite | 44 passed | Both installed-wheel cases enabled; refreshed renderer provenance included |
| Combined forensic/refit audit tests | 21 passed in 0.88 s | Twelve diagnosis tests plus nine summary/binding tests |
| Publication, evidence and agent surface | PASS; 14 focused evidence checks pass | Current artifact bindings and instruction/surface consistency |
| Adversarial board | 29 PASS, 0 FAIL, 1 SKIP | Optional G21 live-agent-attestation artifact absent; no fresh live-agent result |
| Fast cached benchmark | GATE OK | Scoped replay only; no acceptance upgrade |
| Public-export suite and remote CI | Pending | To be checked on the exported/published revision |

The first integrated source run reported **1,150 passes, two skips and one
failure** while the scan demonstration still carried its previous renderer
provenance. After refreshing that demonstration, a **44-test wheel/fidelity
check passed**, including the failed case and both installed-wheel tests that
skip in the source suite. The final complete source rerun then passed **1,155
tests with two skips and 243 warnings in 228.48 seconds**. Its local machine
records are `local-runs/rrr-diagnosis/final-tests.log` and
`local-runs/rrr-diagnosis/final-tests.xml`. The initial integrity failure remains
recorded here; no integrity requirement was weakened to obtain the final pass.

The publication gate now requires `scripts/check_rrr_audits.py`, the cached-refit
summary's `--check` mode and the survey catalog validator. These checks recompute
retained arithmetic and verify evidence consistency; they do not run simulation
or replace the failed native fit with a fabricated result. The nine refit
integrity tests and twelve forensic tests passed together in 0.88 seconds. The
adversarial board's 29 passing cases and one optional G21 skip must not be
reported as thirty fresh passes: no current live-agent-attestation artifact was
supplied. The fast cached benchmark remains a scoped replay, not a new acceptance
or end-to-end reproduction certificate.

The combined author portability/path command passed 56 tests in 7.90 seconds.
With a Python 3.12 test environment, run from outside the checkout:

```bash
export RAVEL_CHECKOUT=/absolute/path/to/ravel
export PYTHONPATH="$RAVEL_CHECKOUT/src"
export PYTHONDONTWRITEBYTECODE=1
python -m pytest "$RAVEL_CHECKOUT/tests/unit/test_native_portability.py" \
  "$RAVEL_CHECKOUT/tests/unit/test_package_paths.py" \
  "$RAVEL_CHECKOUT/tests/unit/test_detector_exposure.py" -q
python -B -m ravel.validation.native_doctor --json --require-rjr
```

The detector tests were a separate four-test invocation in this verification;
the combined command above reruns all 60 focused cases. Native prerequisites are
expected to fail clearly on an unprovisioned machine. See the forensic and survey
directories for their independent replay commands and verification JSON.

The independent portability review rechecked these twelve file hashes after its
final tests. They identify the reviewed implementation, not the eventual release
commit or a scientific certificate:

| File | SHA-256 |
|---|---|
| `src/ravel/validation/native_doctor.py` | `304a3e058c177e503d3e9997614da7fbb77f1ea82f4d6c52832fba25fa2c51bb` |
| `src/ravel/physics/native_build.py` | `1d45bc49d91456b8180f002dcb2c130ab5813fbdd7527b1cfc6e9e47fed18a82` |
| `native/scripts/macos-common.sh` | `29fec293128745ae6ceebf4c053419ea0d8c04d96c3f831c5f10bc799e4681ec` |
| `native/scripts/paths.sh` | `50129edfe25563565fb2ebe1b784b533836bcc00c48a8b70e4742eaf1c97e8cd` |
| `native/scripts/pythia-shower-build.sh` | `0b83daf5f3ee5476da84744424b3a10c765baed9041795b316b06bed201eed5c` |
| `native/scripts/rjr-resolve-build.sh` | `c986a2a4bc5fb18aadf39d8a6d58b1dc536f77a93684b8f4a043f467455d8b5d` |
| `native/scripts/restframes-native-build.sh` | `971ee8af319739c3d8119c00069566c14923418b278c787bac3451d7a6572633` |
| `environment/scripts/00-install-miniforge.sh` | `c99b6869df6db088c2806b11b4f78cc5191f35849dd2a02454566f7cf72984f6` |
| `environment/scripts/01-create-env.sh` | `4867bd75a466a4046b3e3ed3db809895ba83f5122ad80671b3bf1deeb352032c` |
| `environment/scripts/02-get-madgraph.sh` | `8944680ca5c7cb750ec20d28df5e50fbb0483a79332145965c152c658c06ed6b` |
| `tests/unit/test_native_portability.py` | `b060d8bc794879675cdd650106539b697d9b92c356015d0d9182ecc13f0a9712` |
| `.github/workflows/ci.yml` | `5e86c12e4a7ef6444b03cb020fc3a1af4e6aca582c968c4fbec7f7cf0e537cd3` |

The existing eRJR 23.1% acceptance deficit, current cached acceptance failures,
two missing-YODA provenance cases and original 24.9% slepton median remain
separately recorded. This work adds diagnostic evidence and safer execution
components; it does not retroactively replace certificates or close detector
fidelity, finite-MC/systematic uncertainties, statistical coverage or autonomous
end-to-end reproduction.

## Final publication-gate review

Independent review found two omissions in the new archival checker: removing a
CSV from the manifest could hide corrupted bytes, and a contradictory dedicated
snapshot digest was not checked. The checker now requires exactly the five
expected generated outputs and checks the actual snapshot digest. Two additional
negative tests bring its targeted suite to six passes (0.12 s), after the 1,155-test
full run above. The reviewer independently replayed both original bypasses and the
valid control: both corruptions are rejected and the valid audit passes. No
outstanding material finding remains in this bounded review.

Public commit checks are available in the
[GitHub workflow](https://github.com/ammarphp/ravel/actions/workflows/ci.yml).
This local verification record does not substitute for those commit-specific results.
