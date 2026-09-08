"""Unambiguous mass-grid identity for published acceptance comparisons.

The tolerance resolves floating-point representation, not a physical mass bin.
Interpolation and unmatched-nearest policy remain with the calling validator.
"""
import math
import numbers

NODE_TOLERANCE_GEV = 1e-6


def validated_grid(points, x, y, tolerance=NODE_TOLERANCE_GEV):
    for name, value in (("first coordinate", x), ("second coordinate", y),
                        ("node tolerance", tolerance)):
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
            raise ValueError(f"invalid reference-grid {name}")
        if value < 0 or (name == "node tolerance" and value == 0):
            raise ValueError(f"invalid reference-grid {name}")
    if not points:
        raise ValueError("empty reference grid")
    coordinates = [(a, b) for a, b, _ in points]
    if len(set(coordinates)) != len(coordinates):
        raise ValueError("duplicate reference-grid coordinates")
    return sorted(points)


def matching_node(points, x, y, tolerance=NODE_TOLERANCE_GEV):
    matches = [row for row in points if abs(row[0]-x) <= tolerance and abs(row[1]-y) <= tolerance]
    if len(matches) > 1:
        raise ValueError("ambiguous reference-grid node; tolerance spans distinct published points")
    return matches[0] if matches else None


def aligned_slice(points, fixed_axis, coordinate, tolerance=NODE_TOLERANCE_GEV):
    rows = [row for row in points if abs(row[fixed_axis]-coordinate) <= tolerance]
    if len({row[fixed_axis] for row in rows}) > 1:
        raise ValueError("ambiguous reference-grid slice; cannot mix distinct fixed masses")
    variable_axis = 1-fixed_axis
    return sorted((row[variable_axis], row[2]) for row in rows)
