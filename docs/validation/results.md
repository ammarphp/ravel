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
comparison basis, exclusions, and unresolved mechanisms. A paired 52-point rescan
measured a +6.5% PDF-choice contribution; the remaining residual has not been
fully attributed. The figure is evidence of a particular reproduction study,
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
