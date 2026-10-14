"""Physics-fidelity comparison of a result with a reference.

The comparison object is built by ``ravel.plotting.reference_metrics``: declared
transformations, raw and shape relative L2, normalisation offset, total variation,
pulls, chi2 with covariances and declared systematics, Poisson deviance on raw counts,
curve, contour and region distances, scalar pulls and resolving power, typed tolerance
bases and an advisory diagnosis. Reports, check-ins and figure overlays read the same
object. ``ravel compare --spec S --out comparison.json`` writes one.
"""
from pathlib import Path

from ravel.plotting import reference_metrics

compare_binned = reference_metrics.compare_binned
compare_scalar = reference_metrics.compare_scalar
compare_curves = reference_metrics.compare_curves
compare_contours = reference_metrics.compare_contours
region_iou = reference_metrics.region_iou
summary_lines = reference_metrics.summary_lines
check_basis = reference_metrics.check_basis


def compare(prediction, reference, spec=None, base='.'):
    """Compare two declared sources (see ``reference_metrics.load_source``) under ``spec``."""
    document = {'schema_version': 1, **(spec or {}), 'agent': prediction, 'reference': reference}
    return reference_metrics.compare(document, Path(base))


def main(argv=None):
    return reference_metrics.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
