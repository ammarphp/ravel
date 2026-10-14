"""Deterministic failure observations, diagnostic routes and separate denominators.

Only supplied execution observations enter classification. Suggestions and class
labels in model prose have no routing authority. Recovery is a proposal, never a
retry authorization or a scientific result.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

from . import broker

DATA = Path(__file__).resolve().parents[1] / 'data/knowledge/failure_classes.json'
ALIASES = {'mg5': 'madgraph', 'madspin': 'madgraph',
           'feynarts': 'feyncalc', 'site': 'backend', 'iris': 'backend'}
IDENTITY = re.compile(r'[a-zA-Z][a-zA-Z0-9_.-]{0,127}\Z')


def registry():
    value = json.loads(DATA.read_text())
    if value.get('kind') != 'failure-classes' or value.get('schema_version') != 1:
        raise ValueError('versioned failure registry required')
    ids = [row['id'] for row in value['rules']]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate failure rule')
    return value


def _text(value, label, maximum=128):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError('bounded ' + label + ' required')
    return value


def _list(value, label):
    if type(value) is not list or len(value) > 128:
        raise ValueError('bounded ' + label + ' list required')
    for item in value:
        _text(item, label, 1024)
    return value


def observations(value):
    """Validate execution facts; retain optional prose without interpreting it."""
    if type(value) is not dict:
        raise ValueError('failure observations required')
    result = deepcopy(value)
    tool = _text(result.get('tool'), 'tool').lower()
    result['tool'] = ALIASES.get(tool, tool)
    status = result.get('exit_status')
    if status is not None and type(status) is not int:
        raise ValueError('integer exit status required')
    signal = result.get('signal')
    if signal is not None and (type(signal) is not int or not 1 <= signal <= 128):
        raise ValueError('positive signal number required')
    if signal is None and status is not None and status < 0:
        result['signal'] = -status
    stderr = result.get('stderr', '')
    if type(stderr) is not str or len(stderr.encode()) > 262144:
        raise ValueError('bounded stderr required')
    result['stderr'] = stderr
    for field in ('declared_outputs', 'observed_outputs', 'failed_checks', 'quantity_witnesses'):
        result[field] = _list(result.get(field, []), field)
    for check in result['failed_checks']:
        if not IDENTITY.fullmatch(check.removeprefix('check:')):
            raise ValueError('failed check identity required')
    for section, fields in [('supervisor', ('lease_conflict', 'disk_full', 'stopped', 'timed_out', 'recorded_failure')),
                            ('provision', ('doctor_ready', 'missing_binary', 'missing_pdf_set', 'missing_image'))]:
        block = result.get(section, {})
        if type(block) is not dict:
            raise ValueError('structured ' + section + ' required')
        for name in fields:
            if name in block and type(block[name]) is not bool:
                raise ValueError('boolean ' + section + '.' + name + ' required')
        result[section] = block
    result['missing_outputs'] = sorted(set(result['declared_outputs']) - set(result['observed_outputs']))
    # JSON-safe and finite, including uninterpreted suggestion fields.
    broker.digest(result)
    return result


def _value(facts, field):
    for part in field.split('.'):
        if type(facts) is not dict or part not in facts:
            return None
        facts = facts[part]
    return facts


def _matches(facts, predicate):
    value = _value(facts, predicate['field'])
    if 'equals' in predicate:
        return type(value) is type(predicate['equals']) and value == predicate['equals']
    return type(value) is str and re.search(predicate['regex'], value, re.I) is not None


def classify(value):
    """A class from exit/signal, supervisor/provision facts, checks and witnesses.

    Infrastructure and provisioning take precedence over tool prose. Failed
    computed checks and quantity witnesses precede stderr matching. A successful
    stage's warning text alone cannot open a failure.
    """
    facts = observations(value)
    data = registry()
    infrastructure = [r for r in data['rules'] if r['family'] != 'tool']
    match = next((r for r in infrastructure if any(_matches(facts, p) for p in r['any'])), None)
    failures = bool(facts.get('exit_status') not in (None, 0) or facts.get('signal') or
                    facts['missing_outputs'] or facts['failed_checks'] or facts['quantity_witnesses']
                    or facts['supervisor'].get('recorded_failure'))
    if match is None and not failures:
        raise ValueError('observations contain no failure')
    if match is None and facts['failed_checks']:
        cid = facts['failed_checks'][0].removeprefix('check:').removeprefix('check.')
        match = {'id': 'check.' + cid, 'family': 'computed_check', 'route': 'rca', 'any': []}
    if match is None and facts['quantity_witnesses']:
        known = next((q for q in facts['quantity_witnesses'] if q in data['quantity_classes']), None)
        if known:
            match = {'id': 'quantity.' + known, 'family': 'quantity', 'route': 'rca', 'any': []}
    if match is None:
        match = next((r for r in data['rules'] if r['family'] == 'tool' and facts['tool'] in r['tools']
                      and any(_matches(facts, p) for p in r['any'])), None)
    from .consults import for_tool
    binding = for_tool(facts['tool'])
    if match is None and facts['missing_outputs'] and binding:
        match = {'id': 'tool.' + facts['tool'] + '.missing_outputs', 'family': 'tool', 'route': 'consult', 'any': []}
    if match is None:
        match = {'id': 'unknown', 'family': 'unknown', 'route': 'failed_stage_review', 'any': []}
    role = None
    if match['family'] in ('tool', 'computed_check'):
        selected = data['check_routes'].get(match['id'].removeprefix('check.'))
        if selected:
            from .consults import bindings
            role = bindings()['consults'][selected]['role']
        elif binding:
            role = binding['role']
    result = {'schema_version': 1, 'kind': 'failure-classification', 'class_id': match['id'],
              'family': match['family'], 'route': match['route'], 'consult_role': role,
              'agent_required': role is not None, 'observations': facts,
              'classification_basis': 'supplied_execution_observations',
              'registry_sha256': broker.sha(DATA), 'binding_sha256': broker.sha(Path(__file__).resolve().parents[1] / 'data/knowledge/consult_bindings.json'),
              'matched_rule': deepcopy(match), 'acceptance_vote': False}
    result['classification_sha256'] = broker.digest(result)
    return result


def denominators(classifications):
    """Keep infrastructure/provisioning outside the tool-failure denominator."""
    counts = Counter(row['family'] for row in classifications)
    return {'total': len(classifications), **{name: counts[name] for name in
            ('infrastructure', 'provisioning', 'tool', 'computed_check', 'quantity', 'unknown')}}


def recovery_packet(value, *, evidence=(), rca_ticket=None):
    """Advisory diagnostic/recovery handoff; old outputs and obligations survive."""
    classification = classify(value)
    return {'schema_version': 1, 'kind': 'failure-recovery-proposal', 'failure': classification,
            'evidence': deepcopy(list(evidence)), 'rca_ticket': deepcopy(rca_ticket),
            'next_action': classification['route'], 'consult_role': classification['consult_role'],
            'retry_authorized': False, 'failure_closed': False, 'physics_validated': False}


def recovery_routes(value, *, signal_basis, routine_ids=(), family=None, census_path=None, observations=()):
    """Route-ranking seam: prospective alternatives cannot change the failure class."""
    from .recast_route import rank_routes
    result = recovery_packet(value)
    result['prospective_routes'] = rank_routes(signal_basis=signal_basis, routine_ids=routine_ids,
                                              family=family, census_path=census_path, observations=observations)
    return result


def from_supervisor(record, *, stderr='', declared_outputs=(), observed_outputs=(), failed_checks=(), quantity_witnesses=()):
    """Translate a retained supervisor record without executing recovery or probes."""
    if type(record) is not dict or record.get('generated_by', record.get('generator')) != 'stage_supervisor.py':
        raise ValueError('recorded stage supervisor failure required')
    reason = _text(record.get('reason'), 'supervisor reason', 8192)
    supervisor = {'timed_out': bool(re.search(r'timeout|wall.clock|time.limit', reason, re.I)),
                  'stopped': bool(re.search(r'interrupt|stop request|signal (?:2|15)\b', reason, re.I)),
                  'lease_conflict': bool(re.search(r'lease conflict', reason, re.I))}
    # No invented nonzero exit: the open supervisor record itself is failure evidence.
    value = {'tool': record.get('stage'), 'exit_status': record.get('exit_status'), 'stderr': stderr,
             'supervisor': supervisor, 'declared_outputs': list(declared_outputs),
             'observed_outputs': list(observed_outputs), 'failed_checks': list(failed_checks),
             'quantity_witnesses': list(quantity_witnesses), 'retained_failure': True}
    if value['exit_status'] is None and not any(supervisor.values()) and not (failed_checks or quantity_witnesses or set(declared_outputs) - set(observed_outputs)):
        # A retained failed record may have no exit code; caller evidence is explicitly
        # retained, rather than assigning a fabricated numeric exit code.
        value['supervisor']['recorded_failure'] = True
    return value
