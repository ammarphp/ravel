# Validation results

Ravel has several kinds of evidence, each with a different scope. The registered
numerical claims below describe their recorded artifacts. They do not imply that
all analyses are certified or that the full pipeline has been independently
rerun on a fresh installation.

## Recorded results

| Check | Recorded result | Evidence and scope |
|---|---|---|
| Statistical-layer recovery | <!-- claim:benchmarks_reproduced -->7 observed S95 comparisons within 8.6% (statistical layer)<!-- /claim --> across four searches | [All benchmark cases](README.md); historical baseline |
| Native runtime comparison | 8h55m to 41m47s, or <!-- claim:arm64_speedup -->12.8x<!-- /claim --> | [Native performance study](native-performance.md); one matched 50k-event case |
| Native output comparison | <!-- claim:arm64_output_parity -->141/141 signal regions identical; final limit delta 0.51%<!-- /claim --> | [Native performance study](native-performance.md); implementation comparison |
| Mass-plane comparison | <!-- claim:fig3_residual -->24.9% median same-basis residual<!-- /claim --> | [Scan record](../../evidence/scans/slepton-bino-figure-3/RESULT.md); 50 matched cells from 52 points |
| Selection acceptance × efficiency | Six scorable baseline cases: four PASS, one WARN, one FAIL; three further cases unscorable | [All nine cases](README.md) |
| Adversarial workflow checks | <!-- claim:adversarial_gate_cases -->30<!-- /claim --> gate cases | [Adversarial suite](../../tests/adversarial/README.md); synthetic violations, not agent-task outcomes |
| Native analysis ports | <!-- claim:native_ported_routines -->3<!-- /claim --> routines with recorded bit-for-bit comparisons | [Native pipeline](../workflow/reference/native-pipeline.md); 141/141, 10/10, and 9/9 signal regions |
| Historical simulation scale | <!-- claim:scan_scale -->2.08M events across two 52-point scans<!-- /claim --> | [Claim registry](../../evidence/claims.json); generation record |
| Recorded pipeline structure | <!-- claim:execution_stages -->8<!-- /claim --> gated execution stages | [Architecture](../development/architecture.md) and [claim registry](../../evidence/claims.json); structural inventory |

The marked values are checked against [the claim registry](../../evidence/claims.json).
The benchmark headline is derived from recorded S95 inputs and published
references. [Evidence checks](evidence.md) verify required artifact paths and
checksums. Consistency and integrity checks alone do not establish scientific
correctness.

## Fresh fidelity and numerical audits

The [fresh RRR waypoint](../../evidence/audits/2026-09-06-rrr-waypoint/README.md)
records a completed 20,000-event four-state calculation with
<!-- claim:rrr_anchor_limits -->48.83 fb observed and 54.69 fb median expected at 150/140 GeV<!-- /claim -->.
These are conditional on its independently bound inclusive rate and declared K factor;
the published values are 46.633 and 56.526 fb. All six numerical roots resolve,
but the primary-region own-MC precision requirement is unmet, the algebraic
reconstructed-fraction comparison is about 11% low, and the truth acceptance
definition, detector working-point response and signal systematic variations
remain unresolved. The bundle provides derived public evidence and an offline
verifier, with large raw event custody explicitly outside its scope.

The [subsequent controlled comparison](../../evidence/audits/2026-09-06-rrr-cut-dependence/README.md)
gives <!-- claim:rrr_pool_limits -->47.37 fb observed and 57.27 fb median expected from the 60,000-event pool at 150/140 GeV<!-- /claim -->.
The independent 20k/40k parent streams are combined using their original exposure;
the pool is not independent of those parents. Its high/low own-MC errors meet the
unchanged 5% criterion at 4.03%/4.53%. The generation-cut control still gives
<!-- claim:rrr_cut_rate_ratio -->a high-region rate ratio of 1.412 (conditional 95% interval 1.146–1.678)<!-- /claim -->
when lowering the leading-parton threshold from 50 to 20 GeV. This interval includes
the independently propagated printed generator-integration error and does not establish
the declared ±10% equivalence. The 50 GeV cut matches the reference recipe. The full
comparison retains all 38 model channels, both SR aggregates and three matched official
nuisance arms. All 42 saved roots resolve; detector calibration, acceptance, coverage
and the full mass plane remain open.

The [event-identity and fresh-point evidence](../../evidence/audits/2026-09-06-rrr-event-identity/README.md)
contains <!-- claim:rrr_fresh100_limits -->210.00 fb observed and 169.09 fb median expected at 100/98 GeV<!-- /claim -->,
versus released values of 238.13 and 203.96 fb. All twelve native stages and six
roots completed, using a separate inclusive control at these masses. The 59/11
selected high/low events give 13.02%/30.15% histogram MC errors; all 38 channels,
including 22 zero-selected bins, remain explicit. The same evidence bundle gives
the original-LHA identity proof and all 40 descriptive hard-parton partitions.
The upper-slice high/low rate ratios are 1.227/1.016, with conditional intervals
[0.982, 1.473]/[0.768, 1.265]. Neither establishes equivalence or coverage.

The [matched 100/98 omission controls](../../evidence/audits/2026-09-06-rrr-template-controls/README.md)
remove signal MC constraints, then additionally control-region signal, while
preserving the background, observations and retained nominal signal. Both changes
strengthen the limits further and worsen this point's reference discrepancy.
The effect differs across expected quantiles. The bundle retains all baseline and
control roots, exact model patches, sparse-bin context and standalone verification.
The baseline's full fit portfolio remains unavailable; the new control portfolios
do not supply that missing evidence or establish coverage.

The [three-anchor comparison](../../evidence/audits/2026-09-06-rrr-fresh-anchors/README.md)
adds <!-- claim:rrr_fresh50_limits -->615.63 fb observed and 755.34 fb median expected at 50/45 GeV<!-- /claim -->,
using that mass point's own four-state inclusive normalization. Its observed and
median residuals are +16.84%/+6.82%; high/low histogram MC errors remain
20.41%/17.41%. The current population is
<!-- claim:rrr_fresh_anchor_coverage -->3 of 52 nominal mass points with completed fresh native evidence<!-- /claim -->.
Replicas and controls add no nominal-plane coverage. All 18 scalar limits, 114
channel-moment rows and six reconstructed fractions remain explicit. The fraction
comparison keeps fixed-N MC, histogram MC and inclusive-integration terms separate.
Missing reference errors, truth denominators and reconstruction migration prevent
acceptance certification. Central-limit agreement at 150/140 coexists with a
reconstructed-fraction shortfall and unresolved generator-cut dependence.

The [September physics pass](../development/history/2026-09-05-physics-fidelity.md)
adds a paper-defined eRJR correction, tested on identical retained events, and
stricter numerical/comparison checks. The
[native differential](../../evidence/audits/2026-09-05-native-fidelity/README.md)
improves one selection residual while retaining its FAIL verdict. These new
measurements do not overwrite the historical table above or its parity records.
The [scan re-render](../../evidence/audits/2026-09-05-scan-fidelity/README.md)
keeps the original pointwise limits and residuals and improves coverage accounting.

## Statistical recovery and selection fidelity

Model-independent S95 recovery tests the statistical inputs and inference for
the driving signal region. The seven observed comparisons span four searches.
They do not by themselves test detector simulation or event selection.

Acceptance × efficiency checks compare the selected signal yield with a published
reference. Six of the nine baseline cases have such a comparison; three are
unscorable. A locked regression floor may pass even when the acceptance
certification verdict is FAIL. Native/container parity is another distinct
comparison: agreement between implementations does not certify agreement with
experiment.

The [case index](README.md) records all nine outcomes and their historical baseline
timestamp. The [September replay audit](../development/history/2026-09-05-hardening.md)
records fresh local checks, including missing-artifact breaches. Historical green
rows are not current certification. The installed `ravel replay` command freshly
checks only its bundled fast case and labels cached acceptance explicitly.

## Mass-plane fidelity

The compressed-slepton study compares the ATLAS-SUSY-2018-16
(EwkCompressed2018) result across a 52-point mass plane. Its pointwise
cross-section-limit residual uses 50 reference-matched cells on a common
cross-section basis. Two floored legacy cells are treated as bounds, not valid
limit measurements.

![Compressed-slepton scan compared with the published ATLAS contour and per-cell residuals](../../evidence/scans/slepton-bino-figure-3/plots/sleptonbino_fig3_vsATLAS__fig3.png)

The [scan record](../../evidence/scans/slepton-bino-figure-3/RESULT.md) describes the
comparison basis, exclusions, and unresolved mechanisms. The later
[forensic audit](../../evidence/audits/2026-09-05-rrr-diagnosis/README.md) found
that the PDF rescan also changed the leading-parton cut and retained four
incomplete detector samples. It does not isolate a PDF-choice contribution.
The remaining residual has not been fully attributed. The figure is evidence of a particular reproduction study,
not a general accuracy guarantee for other models or analyses.

## Native implementation and runtime

The [ARM64 study](native-performance.md) records the same benchmark point under
emulation and native execution. Its checks include converter agreement,
signal-region equality on shared input, and a separate fresh-generation limit
comparison. The timing applies to that configuration and hardware; it is not a
runtime promise for arbitrary physics tasks.

## Workflow reliability

The adversarial suite constructs invalid states and checks that the relevant
guards reject them. Examples include missing approvals, tampered enforcement,
incomplete provenance, stage-order errors, and unverified delivery claims.
Unit regressions also exercise numerical and figure-layout failures.

These tests establish bounded software behavior. Whether the controls improve
scientifically warranted agent completion requires the
[prospective evaluation](../research/2026-09-05-competitive-design-and-validation.md),
with complete outcome accounting, valid-refusal controls, independent scoring,
and explicit cost and intervention records.
