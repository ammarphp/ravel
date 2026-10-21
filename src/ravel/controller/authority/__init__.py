"""Controller authority service (P06): authority from outside the workers' reach.

Binding interface (PACKAGES.md 0.2): ``operator_config``, ``freeze_mode``, ``request`` and
``stop_state``. Gate helpers for the controller graph, the governed step and the sink:
``verify``, ``current``, ``authorize_effect``, ``effective_bounds``, ``control``, ``check``,
``observe_stop``, ``notify``, ``records`` and ``deviations``. ``render_checkin`` and ``validate_checkin``
build the typed check-ins the authority nodes present. The CLI is
``ravel operator init|set|show|stop|pause|resume|revoke|answer`` (``authority.cli``).
"""
from __future__ import annotations

from .checkin import render as render_checkin, text as checkin_text, validate as validate_checkin
from .common import (AuthorityRefused, DELEGATED, LEGACY_TERMINAL, MACHINE, OPERATOR_COMMAND, SCHEMA,
                     TERMINAL)
from .mode import effective_bounds, freeze_child, freeze_mode, frozen, narrow
from .operator import controller_home, operator_config
from .service import (answer, authorize_effect, current, deviations, disposition, ledger_evidence, notify,
                      plan_authority, read_authority, records, register_ledger_reader, request, verify)
from .stop import check, control, observe as observe_stop, stop_state
from .standing import register_recorders, delivery_decision, record_standing_rows, record_delivery_rows
from .rdj import final_task_action, review_deviation, review_final_task

__all__ = [
    'AuthorityRefused', 'DELEGATED', 'LEGACY_TERMINAL', 'MACHINE', 'OPERATOR_COMMAND', 'SCHEMA', 'TERMINAL',
    'answer', 'authorize_effect', 'check', 'checkin_text', 'control', 'controller_home', 'current', 'deviations',
    'disposition', 'effective_bounds', 'freeze_child', 'freeze_mode', 'frozen', 'ledger_evidence', 'narrow', 'notify',
    'observe_stop', 'operator_config', 'plan_authority', 'read_authority', 'register_ledger_reader',
    'records', 'render_checkin', 'request', 'stop_state', 'validate_checkin', 'verify',
    'register_recorders', 'delivery_decision', 'record_standing_rows', 'record_delivery_rows', 'final_task_action',
    'review_deviation', 'review_final_task',
]
