"""Computed claim-check registry for every typed scientific route.

``resolve(plan, reading=None, registry=None, artifacts=None)`` supplies node/claim
requirements. ``evaluate`` supplies machine rows from those exact lineage refs.
``evaluate_check`` checks a single raw evidence payload. ``science_errors`` is the
completed science-envelope seam. Callers must retain both failures and clean controls;
a row's pass establishes its declared check only, never scientific certification.
"""
from .registry import conformance, computed_id, evaluate, evaluate_check, registry, resolve
from .envelope import science_errors

__all__ = ['conformance', 'computed_id', 'evaluate', 'evaluate_check', 'registry', 'resolve', 'science_errors']
