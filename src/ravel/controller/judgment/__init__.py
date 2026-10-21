"""The judgment route: questions with no fixed path, driven end to end.

A request that no route spec matches, an open or held parent and a mixed request go to the
registered graph ``judgment.plan`` (``graph``): the question is framed, decomposed into typed
steps from the closed vocabulary, every judgment call is classed by code and recorded, R2 and
R3 calls are reviewed or escalated, and the run ends in a reviewed delivery or a qualified one.
Nothing is refused for lack of a path.

Binding interface (PACKAGES.md 0.2)::

    classify(action) -> str                       # R0|R1|R2|R3 from code tables; unknown -> R3
    record_judgment(store, record) -> str         # judgment-record.v1; the store record id

Helpers for the controller graph and the governed step: ``explain`` (the factors of a
class), ``requirement`` (what a class requires before its effect), ``check_record`` (a decide
step's record, before it may close), ``record_outcome``, ``reviewer_items``,
``authority_subject`` (an R3 request with its conservative default), ``check_attacks`` (the
three P8 attacks before the final review) and ``bounds`` (frame, plan, review and replan
bounds, operator-configurable through the frozen mode). Importing this package loads no graph
framework.
"""
from __future__ import annotations

from .classes import classify, explain, requirement
from .control import bounds
from .protocols import check_attacks
from .records import (JudgmentRecordError, authority_subject, check_record, record_judgment, record_outcome,
                      reviewer_items)

GRAPH_ID = "judgment.plan"

__all__ = ["GRAPH_ID", "JudgmentRecordError", "authority_subject", "bounds", "check_attacks", "check_record",
           "classify", "explain", "record_judgment", "record_outcome", "requirement", "reviewer_items"]
