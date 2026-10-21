"""Explicit canary instrumentation. No transport, process launch or network client."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from .records import (CONFIG, FAULT, FAULT_RESULT, TRANSCRIPT, DiagnosticsRefused, before_effects,
                      canonical, digest, entries, latest, private_file, require_expected, seal, verify)

# Faults describe requests for the normal execution boundary; this module never
# performs an out-of-scope write, acquisition, or intentionally blocking call itself.
# Each lists the typed responses that count: a held or escalated step, or the tool
# broker's refusal of the call itself.
FAULTS = {
    'outside-output': {'operation': 'worker_write', 'target': '../undeclared.txt',
                       'declared_outputs': ['outputs/result.txt'], 'responses': [
                           {'status': 'held', 'codes': ['output_scope', 'sandbox_denied', 'undeclared_output']},
                           {'status': 'refused', 'codes': ['write_outside_workspace']}]},
    'missing-input': {'operation': 'consume_input', 'artifact': 'absent-input', 'responses': [
        {'status': 'held', 'codes': ['missing_input', 'input_missing', 'input_unavailable',
                                     'run_input_missing', 'predecessor_unreceipted']}]},
    'forbidden-source': {'operation': 'acquire_source', 'source_class': 'forbidden', 'responses': [
        {'status': 'held', 'codes': ['forbidden_source', 'source_forbidden', 'source_restricted']},
        {'status': 'refused', 'codes': ['forbidden_source']}]},
    'stalled-tool': {'operation': 'tool_call', 'tool': 'inert-stalled-tool', 'deadline_seconds': 0, 'responses': [
        {'status': 'escalated', 'codes': ['tool_timeout', 'tool_stalled', 'deadline_exceeded']}]},
}


def configure(store, *, canary=False, capture_transcripts=False, faults=()):
    if type(canary) is not bool or type(capture_transcripts) is not bool:
        raise DiagnosticsRefused('canary and transcript switches must be booleans')
    faults = sorted(set(faults))
    if any(f not in FAULTS for f in faults):
        raise DiagnosticsRefused('unknown diagnostic fault')
    if (capture_transcripts or faults) and not canary:
        raise DiagnosticsRefused('transcripts and fault injection require canary mode')
    value = seal({'schema': 'diagnostics-config.v1', 'canary': canary,
                  'capture_transcripts': capture_transcripts, 'faults': faults})
    existing = entries(store, CONFIG)
    if existing:
        if len(existing) != 1 or existing[0]['record'] != value:
            raise DiagnosticsRefused('diagnostic configuration is already frozen')
        verify(existing[0]['record'])
        return existing[0]['id']
    before_effects(store)
    return store.append(CONFIG, value)


def _config(store):
    found = entries(store, CONFIG)
    if not found:
        return {'canary': False, 'capture_transcripts': False, 'faults': []}
    if len(found) != 1:
        raise DiagnosticsRefused('multiple diagnostic configurations')
    result = found[0]['record']
    verify(result)
    if (result['capture_transcripts'] or result['faults']) and result['canary'] is not True:
        raise DiagnosticsRefused('canary-only instrumentation outside canary mode')
    return result


def capture_transcript(store, identity, text):
    """The controller supplies the worker stream; no input file or output path is accepted."""
    config = _config(store)
    if not config['capture_transcripts']:
        return None
    require_expected(store)
    if not isinstance(text, str):
        raise DiagnosticsRefused('transcript must be text')
    for field in ('step_id', 'seat', 'role', 'attempt'):
        if not identity.get(field):
            raise DiagnosticsRefused('transcript seat identity incomplete: ' + field)
    content = text.encode('utf-8')
    checksum = sha256(content).hexdigest()
    filename = digest({'identity': identity, 'sha256': checksum}) + '.txt'
    parts = ('diagnostics', 'transcripts', filename)
    present = [e for e in entries(store, TRANSCRIPT)
               if e['record'].get('identity') == identity and e['record'].get('sha256') == checksum]
    if present:
        return present[0]['id']
    path = store.path(*parts)
    if path.exists():
        # Recover a crash between writing bytes and appending their receipt.
        if path.read_bytes() != content:
            raise DiagnosticsRefused('transcript bytes conflict with their pin')
    else:
        private_file(store, parts, content)
    return store.append(TRANSCRIPT, {'schema': 'diagnostics-transcript.v1',
                                    'identity': deepcopy(identity), 'path_parts': list(parts),
                                    'bytes': len(content), 'sha256': checksum, 'canary_only': True})


def inject_fault(store, fault, identity, *, exercise):
    """Ask a canary's normal boundary to exercise a fault, crediting only persisted evidence.

    ``exercise(spec)`` must return ``{kind, record_id}`` pointing to its own
    controller-recorded response. An exception or missing response is reported as
    undetected. A callback's unrecorded assertion that a gate passed earns no credit.
    """
    config = _config(store)
    if not config['canary'] or fault not in config['faults']:
        raise DiagnosticsRefused('fault requires explicit opt-in on a canary run')
    require_expected(store)
    if not callable(exercise):
        raise DiagnosticsRefused('a local boundary exercise is required')
    if not all(identity.get(k) for k in ('step_id', 'seat', 'role', 'attempt')):
        raise DiagnosticsRefused('fault seat identity incomplete')
    spec = {'schema': 'diagnostics-fault.v1', 'fault': fault, 'identity': deepcopy(identity),
            'request': deepcopy(FAULTS[fault]), 'canary_only': True}
    spec['expected_run_id'] = require_expected(store)
    injection = store.append(FAULT, seal(spec))
    result = {'schema': 'diagnostics-fault-result.v1', 'injection_id': injection,
              'fault': fault, 'evidence': None, 'error': None}
    try:
        evidence = exercise(deepcopy(spec))
        if not isinstance(evidence, dict) or not evidence.get('kind') or not evidence.get('record_id'):
            raise DiagnosticsRefused('exercise returned no recorded response')
        # No diagnostic self-report may substitute for an execution-boundary record.
        if evidence['kind'] not in ('step-outcome', 'step-result', 'authority', 'broker-evidence', 'sandbox-probe'):
            raise DiagnosticsRefused('fault evidence is not an execution-boundary record')
        response = store.read(evidence['kind'], evidence['record_id'])
        marker = store.read(FAULT, injection)
        if response['seq'] <= marker['seq']:
            raise DiagnosticsRefused('fault response predates its injection')
        record = response['record']
        if record.get('step_id', record.get('step')) != identity['step_id']:
            raise DiagnosticsRefused('fault response belongs to another step')
        if record.get('attempt', 1) != identity['attempt'] or any(
                k in record and record[k] != identity[k] for k in ('seat', 'role')):
            raise DiagnosticsRefused('fault response belongs to another seat or attempt')
        result['evidence'] = deepcopy(evidence)
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    return store.append(FAULT_RESULT, seal(result))


def fault_verdicts(observed):
    records = observed['records']
    by_id = {entry['id']: entry for values in records.values() for entry in values}
    results = []
    for injection in records[FAULT]:
        spec = injection['record']
        verify(spec)
        responses = [e for e in records[FAULT_RESULT] if e['record']['injection_id'] == injection['id']]
        result = responses[-1]['record'] if responses else {}
        if result:
            verify(result)
        link = result.get('evidence') or {}
        response = by_id.get(link.get('record_id'), {})
        value = response.get('record', {})
        reason = value.get('reason') or value.get('failure') or value.get('error') or {}
        code = reason.get('code') if isinstance(reason, dict) else reason
        status = value.get('status', value.get('response'))
        responses = spec['request']['responses']
        detected = (response.get('kind') == link.get('kind') and response.get('seq', 0) > injection['seq']
                    and any(status == r['status'] and code in r['codes'] for r in responses))
        results.append({'fault': spec['fault'], 'node_id': spec['identity']['step_id'],
                        'injection_id': injection['id'],
                        'expected_response': ' or '.join(r['status'] for r in responses),
                        'observed_response': status or 'unrecorded', 'reason_code': code,
                        'detected': detected, 'evidence': link or None,
                        'error': result.get('error')})
    return results


def receipt_section(store):
    config = _config(store)
    return {'schema': 'diagnostics-receipt.v1', 'canary': config['canary'],
            'transcript_capture': config['capture_transcripts'],
            'transcript_record_ids': [e['id'] for e in entries(store, TRANSCRIPT)],
            'faults_enabled': list(config['faults']),
            'fault_injection_ids': [e['id'] for e in entries(store, FAULT)],
            'fault_result_ids': [e['id'] for e in entries(store, FAULT_RESULT)],
            'expected_record_ids': [e['id'] for e in entries(store, 'diagnostics-expected')]}
