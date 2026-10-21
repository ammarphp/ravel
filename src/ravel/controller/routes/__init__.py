"""Routes as data: selection over the start.md table (``select``) and the route-spec compiler (``compile``).

Route specs live in ``src/ravel/data/controller/routes/`` (read-only package data, written by the
route packages); their schema is ``route-spec.v1``. Plans are ``plan.v1`` documents of ``step.v1``
steps. A request no spec matches is planned by the judgment graph; nothing is refused.
"""
from __future__ import annotations

from .compiler import CompileError, compile, conformance_errors, plan_errors, plan_sha256
from .select import JUDGMENT, RouteSpecError, adapter_module, find, load_specs, registered, select, view

__all__ = ["CompileError", "JUDGMENT", "RouteSpecError", "adapter_module", "compile", "conformance_errors", "find",
           "load_specs", "plan_errors", "plan_sha256", "registered", "select", "view"]
