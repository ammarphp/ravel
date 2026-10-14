"""The external cosmology derivative runtime is retired together with its backend route.

See ``cosmology_backend``. Nothing here loads, wraps or runs an upstream agent framework; every
entry point refuses with the recorded reason.
"""
from __future__ import annotations

from .cosmology_backend import BackendRetired, REASON, refuse

validate_limits = validate_derivative = prepare = invoke = model_configuration = phase_request = refuse
verify_source_inventory = refuse


class Boundary:
    def __init__(self, *_args, **_kwargs):
        raise BackendRetired(REASON)


class OrdinaryQuantityTool(Boundary):
    pass


class RuntimeBinding(Boundary):
    pass
