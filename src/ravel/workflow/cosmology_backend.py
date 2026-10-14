"""The external cosmology agent backend route is retired.

RAVEL no longer fetches, imports or calls the external agent backends this route used. Every entry
point that used to reach them refuses with the reason below, so a request that names one is told
why instead of failing later.

Cosmological calculation itself is unaffected: CAMB, CLASS and Cobaya run through the
``cosmology-solver`` operation in the ``cosmology`` toolchain group.
"""
from __future__ import annotations

REASON = ("The external cosmology agent backends were dropped from RAVEL and are no longer fetched or "
          "called. Cosmological calculations run through the cosmology-solver operation (CAMB, CLASS, Cobaya).")


class BackendRetired(ValueError):
    """Raised by every entry point of the dropped backend route."""


def refuse(*_args, **_kwargs):
    raise BackendRetired(REASON)


inspect_sources = prepare = read_results = invoke = apply_results = refuse
