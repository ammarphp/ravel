# Exact scan comparison and supported contours

This audit re-renders the original compressed-slepton scan without changing its
limits or generating events. The observed residual is still **24.9%** over
**50 exact matched points out of 52 planned**. Two legacy bounds remain in the
coverage count and do not enter residuals or limit contours. The expected variant
has a 24.1% median on the same 50 points.

![Exact residuals with full point coverage](scan__reldiff.png)

[Observed contour and cell map](scan__fig3.png) ·
[Expected contour and cell map](scan__fig3_expected.png) ·
[Comparison JSON](scan__reldiff.json) · [Provenance](provenance.json)

Changes from the historical renderer:

- Reference limits are matched exactly, within 0.05 GeV, in every quantitative
  comparison. No nearest-reference extrapolation or interpolated reference value
  enters the diagnostic median.
- Contours use piecewise linear interpolation. Missing lattice vertices mask
  their incident triangles; this avoids bridging holes or creating crossings from
  cubic overshoot. Coverage is restricted to the observed mass/splitting lattice.
- Bounds, invalid inputs, unmatched references, and missing planned points have
  separate counts. Disconnected one-dimensional exclusions remain separate spans.
- HEPData columns require explicit observed/expected identity and pb/fb units;
  mass coordinates require GeV. Mass/mass tables are converted to mass/splitting.

## Inputs and reproduction

The [original scan](../../scans/slepton-bino-figure-3/scan.json) retains its historical
identity. The two YAML files are unmodified cached tables from
[ATLAS HEPData record 91374, version 5](https://www.hepdata.net/record/ins1767649):
[Figure 44ab limits](https://doi.org/10.17182/hepdata.91374.v5/t91) and Figure 16a
observed contour. Their hashes are in the provenance record.

From a source or public checkout with replay dependencies installed:

```bash
python benchmarks/plot_scan_demo.py --out NEW_OUTPUT_DIRECTORY
```

This creates PNG/PDF files, per-point comparison JSON, a render log, and hashes of
inputs, renderer, and outputs. Existing directories are refused. Matplotlib's
standard style is used if optional mplhep is absent. The images do not represent
an official ATLAS result; the ATLAS reference is overlaid for comparison.

The tests in `tests/unit/test_scan_fidelity.py` exercise disconnected intervals,
missing interior vertices, no-overshoot behavior, reference units/columns,
duplicate coordinates, complete denominator accounting, and all active scan
specifications through dry planning. See the
[implementation report](../../../docs/development/history/2026-09-05-physics-fidelity.md).
