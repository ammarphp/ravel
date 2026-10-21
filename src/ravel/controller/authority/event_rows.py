"""Executed authority mechanisms, recorded from their authenticated action records."""
from __future__ import annotations

from copy import deepcopy

from . import checkin, common, retained

VALIDATION = 'checkin-validation'
VALIDATION_SCHEMA = 'checkin-validation.v1'


def validated(store, kind, artifact, context_record):
    """Retain successful validation before the request can present or resolve a check-in."""
    context = common.read(store, retained.KIND, context_record, retained.SCHEMA)
    if context['kind'] != kind or checkin.validate(artifact, context['view']):
        raise common.AuthorityRefused('check-in validation has no matching retained context')
    prior = common.scan(store, VALIDATION, VALIDATION_SCHEMA)
    if prior and all(prior[-1].get(k) == v for k, v in {
            'kind': kind, 'artifact': artifact, 'context_record': context_record}.items()):
        return prior[-1]
    return common.append(store, VALIDATION, {
        'schema': VALIDATION_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
        'run_id': common.run_id(store), 'time_ns': common.now_ns(), 'kind': kind,
        'artifact': deepcopy(artifact), 'context_record': context_record,
        'errors': [], 'before_presentation': True})


def evidence(store):
    """C23 and SW04; occurrence is never replaced by an absence assertion."""
    from .standing import _snapshot
    try:
        reader, entries, _ = _snapshot(store)
        if reader.check_binding():
            return {}
        indexed = {entry['id']: entry for entry in entries}
        decisions = common.scan(reader, common.AUTHORITY, common.SCHEMA)
        requests = common.scan(reader, common.REQUESTS, common.REQUEST_SCHEMA)
        proofs = common.scan(reader, VALIDATION, VALIDATION_SCHEMA)
        valid, expected = {}, []
        for row in proofs:
            context = common.read(reader, retained.KIND, row['context_record'], retained.SCHEMA)
            if (row.get('run_id') != reader.run_id or row.get('kind') != context['kind']
                    or row.get('errors') != [] or row.get('before_presentation') is not True
                    or indexed[context['id']]['seq'] >= indexed[row['id']]['seq']
                    or checkin.validate(row['artifact'], context['view'])):
                continue
            key = (row['kind'], row['context_record'], row['artifact']['sha256'])
            valid.setdefault(key, (row['id'], indexed[row['id']]['seq']))
        for row in decisions + requests:
            if row.get('kind') in common.CHECKINS:
                subject = row.get('subject') or {}
                key = (row['kind'], subject.get('context_record'), subject.get('checkin_sha256'))
                expected.append((key, indexed[row['id']]['seq']))
        rows = {}
        if valid and all(key in valid and valid[key][1] < seq for key, seq in expected):
            identifiers = sorted({identifier for identifier, _ in valid.values()})
            rows['C23'] = {'status': 'satisfied', 'evidence': {
                'record': identifiers[-1], 'validation_records': identifiers,
                'mechanism': 'authority.checkin.validate_before_presentation'}}
        answered = []
        for row in decisions:
            if row.get('source') != 'operator_cli' or row.get('label') != common.OPERATOR_COMMAND:
                continue
            pending = common.read(reader, common.REQUESTS, row['request'], common.REQUEST_SCHEMA)
            if (pending.get('run_id') != reader.run_id or row.get('run_id') != reader.run_id
                    or pending.get('answerable') is not True or not pending.get('nonce_sha256')
                    or pending['kind'] != row['kind'] or pending['subject_sha256'] != row['subject_sha256']
                    or (row.get('evidence') or {}).get('request') != pending['id']):
                continue
            answered.append({'record': row['id'], 'request': pending['id']})
        if answered:
            rows['SW04'] = {'status': 'satisfied', 'evidence': {
                **answered[-1], 'answers': answered, 'mechanism': 'authority.answer'}}
        return rows
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def crosscheck_rows(store, qualification):
    """Label credited review separately from executable numerical cross-check proof.

    A worker's statement of agreement is never an execution receipt. This
    recorder establishes only the labelled review, not numerical certification.
    """
    from .standing import _snapshot
    from ..confine import host_rows
    from ..ledger import state
    from ravel.workflow import review_independence
    if not qualification or not qualification.get('qualifications'):
        return {}
    try:
        reader, entries, _ = _snapshot(store)
        if reader.check_binding():
            return {}
        host = common.read(reader, host_rows.KIND, qualification['record'], host_rows.SCHEMA)
        sources = host['sources']
        if sources.get('qualifications') != qualification['qualifications']:
            return {}
        indexed = {entry['id']: entry for entry in entries}
        if any(common.digest(indexed[key]['record']) != digest
               for key, digest in sources['source_digests'].items()):
            return {}
        population = state.load(reader, full=True)
        credits = reader.scan('step-credit')
        rows = {}
        for key in population.current_keys():
            instance = population.instances[key]
            if instance.id != 'V09':
                continue
            scope = instance.scope
            for entry in reversed(credits):
                body = entry['record']
                if body.get('step_id') != scope.get('step') or body.get('attempt') != scope.get('attempt'):
                    continue
                own = body.get('own') or {}
                own_role = (own.get('query') or {}).get('role')
                own_seat = f'seat:{own_role}:1' if own_role else None
                candidates = ([own] if scope.get('seat') in ('producer', own_seat) else
                              [seat for seat in body.get('seats') or [] if seat.get('seat') == scope.get('seat')])
                for credit in candidates:
                    if not credit or credit.get('credited') is not True:
                        continue
                    query = credit.get('query') or {}
                    if query.get('run') != str(reader.run_dir.resolve()):
                        continue
                    unit = (scope.get('step'), scope.get('point') or '', scope.get('seat'), scope.get('attempt'))
                    expected_role = (population.seat_context.get(unit) or {}).get('role')
                    if expected_role is None or query.get('role') != expected_role:
                        continue
                    decided = review_independence.decide(query)
                    if (decided.get('independent') is not True
                            or decided.get('evidence_boundary') != review_independence.CONTROLLER_STORE):
                        continue
                    rows[key] = {'status': 'violated', 'evidence': {
                        'record': entry['id'], 'credit': entry['id'], 'query': deepcopy(query),
                        'mechanism': 'controller.qualified_crosscheck_review',
                        'qualification_records': list(qualification['qualifications']),
                        'host_record': qualification['record'],
                        'label': 'INDEPENDENT REVIEW; EXECUTABLE CROSSCHECK NOT ESTABLISHED',
                        'independence_label': decided.get('label'),
                        'reason': 'a credited review is distinct from an executable crosscheck receipt'}}
                    break
                if key in rows:
                    break
        return rows
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def record_executed_rows(store):
    """The delivery boundary invokes action recorders, independently of absence proofs."""
    from importlib import import_module
    from ravel.controller.graph import service
    from ..confine import host_rows
    from ..ledger import recorders
    from .standing import _snapshot
    reader, _, _ = _snapshot(store)
    if reader.check_binding():
        return {'recorded': [], 'pending': []}
    rows = evidence(store)
    rows.update(recorders.evidence(reader))
    rows.update(import_module('ravel.controller.routes.select').selection_rows(store))
    hosts = host_rows.evidence(store)
    rows.update(hosts)
    qualification = (hosts.get('SW30') or {}).get('evidence')
    rows.update(crosscheck_rows(store, qualification))
    return recorders.record(store, rows, service('ledger'), revalidate=True)
