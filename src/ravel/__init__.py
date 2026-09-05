"""Ravel's task-contract API; full simulation remains workflow-driven."""
__version__ = "0.4.0"
__all__ = ["validate_task_contract", "__version__"]


def validate_task_contract(contract: object) -> list[str]:
    """Return errors; an empty list means schema-valid, not compute-approved."""
    from .validation.validate_task_contract import validate
    return validate(contract)
