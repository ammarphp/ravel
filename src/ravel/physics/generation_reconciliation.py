"""Science-mode adapter for physics-intent reconciliation of supplied MadGraph cards.

Task: {"intent": path, "proc_card": path, "run_card": path, "param_card": path (optional)}.
The comparison itself lives in ravel.workflow.spec_reconciliation.
"""
from ravel.workflow.spec_reconciliation import execution_seconds, inputs, run, validate

__all__ = ["validate", "inputs", "execution_seconds", "run"]
