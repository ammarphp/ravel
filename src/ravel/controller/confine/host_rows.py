"""Delivery evidence for qualified controller workers; host hooks only detect.

No host finding establishes a sandbox boundary. Source records must survive a
fresh journal verification; SW30 additionally executes the production refusal.
"""
from __future__ import annotations

from copy import deepcopy
import re

from ravel.controller import testing
from ravel.controller.authority import common, standing
from .ledger_evidence import ledger_evidence

ROWS = ('CT08', 'SW10', 'SW11', 'SW14', 'SW18', 'SW19', 'SW31', 'SW32')
LABEL = 'HOST HOOKS ARE DETECTION ONLY; QUALIFIED CONTROLLER WORKERS'
KIND = 'host-surface-check'
SCHEMA = 'host-surface-check.v1'


def _sha(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def _sources(reader):
    from ravel.workflow import transport_registry as tr
    admission = ledger_evidence(reader).get('SW29')
    if not admission:
        return None
    hosts = reader.scan('host-observation')
    if not hosts:
        return None
    host = hosts[-1]
    body = host['record']
    tripwire = body.get('tripwire')
    if (body.get('source') != 'controller' or type(tripwire) is not dict
            or tripwire.get('declared') != reader.run_id or tripwire.get('controller_process') is not True
            or tripwire.get('mode') not in ('block', '1')
            or type(body.get('host_findings')) is not list
            or any(type(item) is not str for item in body['host_findings'])):
        return None
    qualifications = reader.scan(tr.QUALIFICATION_KIND)
    dispatches = reader.scan('step-dispatch')
    observations = reader.scan('step-observation')
    inventories = reader.scan('tool-inventory')
    sessions = reader.scan('worker-session')
    if not dispatches or not observations or not inventories or not sessions:
        return None
    used = [host, reader.read('code-identity', admission['record']),
            reader.read('restricted-source-policy', admission['policy_record'])]
    for dispatch in dispatches:
        d = dispatch['record']
        selection = d.get('selection')
        if type(selection) is not dict:
            return None
        qualification = next((q for q in qualifications if
            tr._store_qualification_valid(q['record'])
            and q['record']['transport_id'] == selection.get('transport_id')
            and q['record']['probe_sha256'] == selection.get('probe_sha256')), None)
        if qualification is None:
            return None
        q = qualification['record']
        receipt, observed = q.get('receipt'), q.get('observed')
        if (not all(_sha(q.get(key)) for key in ('executable_sha256', 'declaration_sha256', 'probe_sha256'))
                or q['declaration_sha256'] != selection.get('declaration_sha256')
                or type(receipt) is not dict or not _sha(receipt.get('sha256'))
                or not _sha(receipt.get('digest')) or not receipt.get('path')
                or type(observed) is not dict or not observed.get('session_id')
                or type(observed.get('surface')) is not dict
                or not observed['surface'].get('ravel') or observed['surface'].get('unexpected') != []):
            return None
        matches = [o for o in observations if all(o['record'].get(k) == d.get(k)
                   and d.get(k) is not None for k in ('node_id', 'attempt'))
                   and o['record'].get('seat') == d.get('seat')]
        if not matches:
            return None
        for observation in matches:
            o = observation['record']
            session = next((s for s in sessions if
                s['record'].get('run_id') == reader.run_id
                and s['record'].get('session_id') == o.get('session_id') and o.get('session_id')
                and s['record'].get('receipt_sha256') == o.get('receipt_sha256')
                and s['record'].get('step') == o.get('step_id')
                and s['record'].get('attempt') == d['attempt']
                and s['record'].get('seat') == d.get('seat')), None)
            if session is None:
                return None
            acting = session['record'].get('step_spec') or {}
            if acting.get('id') != o.get('step_id'):
                return None
            parent = d.get('parent_step') or d.get('step_id')
            if acting['id'] != parent:
                parameters = acting.get('parameters') or {}
                if (parameters.get('seat_of') != parent
                        or parameters.get('purpose') != d.get('purpose') or not d.get('seat')):
                    return None
            inventory = o.get('tool_inventory')
            if (o.get('status') != 'ok' or o.get('transport') != selection['transport_id']
                    or type(inventory) is not dict or inventory.get('kind') != 'worker'
                    or inventory.get('backend') not in ('linux', 'macos')
                    or inventory.get('equal') is not True or inventory.get('differences') != []
                    or inventory.get('mcp_observed') is not True or inventory.get('mcp_error')
                    or inventory.get('issuer_read_denied') is not True
                    or inventory.get('issuer_replace_denied') is not True
                    or not all(type(inventory.get(k)) is list for k in
                               ('tools', 'declared_tools', 'read_roots', 'writable', 'env_names'))
                    or inventory['tools'] != inventory['declared_tools']
                    or sorted(inventory['tools']) != sorted(d.get('admitted_tools', []))
                    or type(inventory.get('network')) is not str):
                return None
            probe = next((i for i in inventories if i['record'] == inventory), None)
            if probe is None:
                return None
            used.extend((observation, probe, session))
        used.extend((dispatch, qualification))
    # Every successful observation must have an admitted dispatch; unmatched records
    # cannot silently lend evidence to a different worker.
    if any(not any(all(o['record'].get(k) == d['record'].get(k) for k in
                           ('node_id', 'attempt', 'seat')) for d in dispatches) for o in observations):
        return None
    unique = {entry['id']: entry for entry in used}
    return {'label': LABEL, 'mechanism': 'controller.qualified_worker_host_surface',
            'scope': 'controller transport qualifies; user host hooks are detection only',
            'host_observation': host['id'], 'code_identity': admission['record'],
            'policy_record': admission['policy_record'], 'host_findings': deepcopy(body['host_findings']),
            'qualifications': sorted({e['id'] for e in used if e['kind'] == tr.QUALIFICATION_KIND}),
            'inventories': sorted({e['id'] for e in used if e['kind'] == 'tool-inventory'}),
            'source_digests': {key: common.digest(value['record']) for key, value in sorted(unique.items())}}


def evidence(store):
    """Return only currently verified row evidence; failure never records credit."""
    try:
        reader, _, _ = standing._snapshot(store)
        if not testing.controller_process() or testing.seams_enabled() or reader.check_binding():
            return {}
        sources = _sources(reader)
        if sources is None:
            return {}
        # Authenticate all prior checks before appending. A forged check is never
        # repaired by writing a valid one after it.
        checks = common.scan(reader, KIND, SCHEMA)
        try:
            testing.refuse_for_controller('host qualification', owned=True)
        except testing.SeamRefused as exc:
            refusal = str(exc)
        else:
            return {}
        expected = {'sources': sources, 'controller_process': True, 'seams_enabled': False,
                    'guard': 'testing.refuse_for_controller', 'argument': 'host qualification',
                    'owned': True, 'exception': 'SeamRefused', 'refusal': refusal}
        if not checks or any(checks[-1].get(k) != v for k, v in expected.items()):
            common.append(store, KIND, {'schema': SCHEMA, 'schema_version': 1, 'uid': common.uid(),
                          'run_id': common.run_id(store), 'time_ns': common.now_ns(), **expected})
        authenticated, _, _ = standing._snapshot(store)
        check = common.scan(authenticated, KIND, SCHEMA)[-1]
        current = _sources(authenticated)
        if (current != sources or check.get('run_id') != store.run_id
                or any(check.get(k) != v for k, v in expected.items())
                or testing.seams_enabled() or not testing.controller_process()):
            return {}
        result = {row: {'status': 'satisfied', 'evidence': {**deepcopy(sources), 'record': check['id']}}
                  for row in ROWS}
        result['SW30'] = {'status': 'satisfied', 'evidence': {**deepcopy(sources), 'record': check['id'],
                          'mechanism': 'controller.executed_seam_refusal'}}
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
