"""The ML route (``ml.inference``, ``ml.training``) and admission of the ML science modes.

``ml.json`` holds two route specs. Inference applies a pinned classifier through ordinary
science-mode operations (a request on supplied events normally takes the study route, which
admits the same operations through ``admit``). Training on supplied data is planned as the staged
executor's typed stages, each a governed plan step and a confined launch (``staged`` is the route
adapter); method studies the judgment graph plans run the ``ml.study`` subgraph. ``admit`` is the
science-mode admission the governed step calls (``modes``); ``training`` holds the training-only rules.
"""
from __future__ import annotations

from .modes import GOVERNED, INFERENCE, MANUSCRIPT, TRAINING, admit, governed
from .training import (PREREQUISITE_HOLD, STAGED_INTERFACE, STAGED_OPERATIONS, prerequisites, staged_errors,
                       staged_plan_errors)

ROUTE_IDS = ("ml.inference", "ml.training")

__all__ = ["GOVERNED", "INFERENCE", "MANUSCRIPT", "PREREQUISITE_HOLD", "ROUTE_IDS", "STAGED_INTERFACE",
           "STAGED_OPERATIONS", "TRAINING", "admit", "governed", "prerequisites", "staged_errors", "staged_plan_errors"]
