"""Ravel's public task-contract validation API; full simulation remains workflow-driven."""
from functools import lru_cache
import runpy

from .resources import resource_root

__version__ = "0.2.0"
__all__ = ["validate_task_contract", "__version__"]


@lru_cache(maxsize=1)
def _validator():
    return runpy.run_path(str(resource_root() / "trial-runs/_infrastructure/validate_task_contract.py"))


def validate_task_contract(contract: object) -> list[str]:
    """Return validation errors; an empty list means schema-valid, not compute-approved."""
    return _validator()["validate"](contract)
