"""Evidence rows for native actions, without writing the controller ledger.

Only the enforcing action's record can close a row. Scientific obligations and
worker-specific checks outside these explicit absence cases remain pending.
"""
from __future__ import annotations

import re

from .seat_rows import _row, na
from ..confine.resource_mechanisms import valid_resource_mapping

_PACKET_ROWS = frozenset(('CF03', 'CF13', 'CT02', 'I01', 'I02', 'E29'))
_PACKET_ROLE = re.compile(r'ROLE-.+-(?:purpose|knowledge|protocol-\d+)\Z')


def packet_rows(branch, entries, record):
    """Close only packet obligations already materialised for a native branch."""
    if branch not in ('launch', 'subgraph') or not record:
        return {}
    rows = {}
    for entry in entries:
        if not isinstance(entry, str):
            continue
        row = entry.split('@', 1)[0]
        if row in _PACKET_ROWS or _PACKET_ROLE.fullmatch(row):
            rows[row] = na(f'{branch}_receives_no_agent_instruction_packet', record=record)
    return rows


def observation_rows(launch, probe, settlement, role=None):
    """Close explicit native-action absence cases from its recorded launch.

    A missing or unrelated inventory probe supplies no CT05 decision. A launch
    probe that reports a mismatch records a violation. Ambiguous settlement never
    closes E30. ``role`` may be a card id or a card containing its id.
    """
    record = (launch or {}).get('journal_id')
    if not record:
        return {}
    rows = {row: na('native_action_returns_no_worker_final_record', record=record)
            for row in ('CF06', 'I07')}
    rows['G13'] = na('native_action_makes_no_broker_calls', record=record)
    if settlement in ('settled', 'released'):
        rows['E30'] = na('no_ambiguous_start', record=record, settlement=settlement)
    if launch.get('backend') == 'controller-acquisition':
        rows['CT05'] = na('trusted_controller_acquisition_starts_no_child', record=record)
    elif type(probe) is dict and probe.get('kind') == 'launch':
        if probe.get('equal') is True and not probe.get('differences'):
            rows['CT05'] = _row('satisfied', record=record, probe=probe.get('backend'))
        else:
            rows['CT05'] = _row('violated', record=record, reason='inventory_probe_mismatch')
    role_id = role.get('id') if isinstance(role, dict) else role
    if isinstance(role_id, str) and role_id:
        for field in ('model', 'independence'):
            rows[f'ROLE-{role_id}-{field}'] = na('native_action_starts_no_model_session', record=record)
        rows[f'ROLE-{role_id}-output'] = na('native_action_returns_no_worker_final_record', record=record)
    return rows


def role_worker_absence(card, launch, *, card_sha256, entries=()):
    """Classify only registered-role worker contract absence for an observed native action.

    These rows concern worker dispatch, environment, toolbelt, stopping and operation
    contracts, plus model-family accounting. They say nothing about numerical checks
    or the native operation's admission. Partial cards or unfinished launch shapes
    cannot establish this absence.
    """
    if not isinstance(card, dict) or not isinstance(launch, dict):
        return {}
    role_id = card.get('id')
    if (not isinstance(role_id, str) or not role_id.strip()
            or any(not isinstance(card.get(field), dict) for field in ('requires', 'tools', 'stop'))
            or not isinstance(card.get('operations'), list)):
        return {}
    if (any(not isinstance(launch.get(field), str) or not launch[field].strip()
            for field in ('journal_id', 'backend'))
            or type(launch.get('exit_status')) is not int
            or type(launch.get('timed_out')) is not bool
            or not isinstance(card_sha256, str)
            or re.fullmatch(r'[0-9a-fA-F]{64}', card_sha256) is None):
        return {}
    rows = [f'ROLE-{role_id}-{field}' for field in ('dispatch', 'requires', 'tools', 'stop')]
    rows += [f'ROLE-{role_id}-operations-{index}' for index in range(len(card['operations']))]
    # The catalogue can retain both source declarations and effective projections.
    # All materialised operation-contract instances concern this absent worker;
    # their suffix is a catalogue identity, not necessarily an effective-card index.
    pattern = re.compile(re.escape(f'ROLE-{role_id}-operations-') + r'\d+\Z')
    rows += [entry.split('@', 1)[0] for entry in entries
             if isinstance(entry, str) and pattern.fullmatch(entry.split('@', 1)[0])]
    rows.append('XF08')
    return {row: na('native_action_starts_no_registered_role_worker',
                    record=launch['journal_id'], card_sha256=card_sha256) for row in rows}


def path_absence(launch):
    """Classify only entrypoints absent from a finished, confined local capsule.

    The capsule must retain actual network, limits and confinement observations.
    These explicit absence rows establish no scientific check, operation admission,
    general launch gate or shell-parser correctness.
    """
    if not isinstance(launch, dict):
        return {}
    if (any(not isinstance(launch.get(field), str) or not launch[field].strip()
            for field in ('finished_id', 'journal_id', 'backend'))
            or type(launch.get('exit_status')) is not int
            or type(launch.get('timed_out')) is not bool):
        return {}
    plan, confinement = launch.get('plan'), launch.get('confinement')
    if (not isinstance(plan, dict) or plan.get('kind') != 'confined' or plan.get('network') != 'none'
            or not isinstance(plan.get('backend'), str) or not plan['backend'].strip()
            or plan['backend'] != launch['backend']
            or not isinstance(confinement, dict) or type(confinement.get('errors')) is not list
            or confinement['errors']):
        return {}
    limits, enforced = plan.get('limits'), plan.get('limits_enforced')
    if not valid_resource_mapping(plan['backend'], limits, enforced):
        return {}
    evidence = {'record': launch['finished_id'], 'started': launch['journal_id'], 'backend': launch['backend']}
    if 'custody_sha256' in plan:
        pin = plan['custody_sha256']
        if not isinstance(pin, str) or re.fullmatch(r'[0-9a-fA-F]{64}', pin) is None:
            return {}
        evidence['custody_sha256'] = pin
    groups = {
        'native_capsule_invokes_no_host_shell_hook_parser': ('G10', 'G14', 'SW27'),
        'native_capsule_uses_no_alternate_unconfined_or_supervisor_entrypoint': (
            'SW17', 'SW34', 'SW35', 'SW36', 'SW37', 'SW38'),
        'local_capsule_submits_no_remote_job_or_procedure_export': ('SW24',)}
    return {row: na(reason, **evidence) for reason, rows in groups.items() for row in rows}
