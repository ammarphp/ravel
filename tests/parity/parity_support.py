"""Cell builder for the parity matrix (transport declaration x role card) and the parity record.

A cell is the outcome of the production selector for one role card on one declared transport, under a
stated qualification state. Nothing here launches a process: probes and qualification records are
synthetic and written only under the test's temporary state directory.
"""
import json
import os
from pathlib import Path

from ravel.workflow import role_registry, transport_registry as tr

SYNTHETIC_MODEL = 'parity-model'
SYNTHETIC_FAMILY = 'parity'
EXECUTABLE_SHA = 'a' * 64
# The six stub kinds a parity cell may name (a declaration's transport_kind).
STUB_KINDS = ('cli-worker', 'cli-oneshot', 'ravel-loop', 'http-model', 'external-relay', 'host-subagent')
CLI_WORKER_HOSTS = ('claude', 'codex', 'gemini', 'opencode', 'antigravity')


def declarations(kind=None):
    rows = sorted(tr.all_declarations(), key=lambda d: d['id'])
    return [d for d in rows if kind is None or d['transport_kind'] == kind]


def cards():
    return sorted(role_registry.all_cards(), key=lambda c: c['id'])


def synthetic_probe(document):
    """A probe record that confirms every declared capability, for a CLI declaration; None otherwise."""
    if document['transport_kind'] not in tr.CLI_KINDS:
        return None
    declared = document['capabilities']
    return {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
            'declaration_sha256': tr.declaration_sha256(document), 'cli_version': 'parity 0.0.0',
            'help_sha256': 'b' * 64, 'flags': {flag: 'confirmed' for flag in tr.template_flags(document)},
            'capabilities_confirmed': {key: bool(declared[key]) for key in tr.BOOLEAN_CAPABILITIES},
            'unusable': [], 'probed_utc': '2026-10-11T00:00:00Z', 'executable_path': '/synthetic/' + document['id'],
            'executable_sha256': EXECUTABLE_SHA, 'exit_status': 0}


def write_qualification(document, probe):
    """A stored live qualification bound to the synthetic probe (tests only; under the temporary state dir)."""
    path = tr.qualification_path(document['id'])
    assert path.is_relative_to(Path(os.environ['RAVEL_STATE_DIR']))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
        'status': 'live_qualified', 'record_path': str(path), 'executable_path': probe['executable_path'],
        'executable_sha256': probe['executable_sha256'], 'declaration_sha256': tr.declaration_sha256(document),
        'probe_sha256': tr.digest(probe), 'receipt': {}, 'observed': {}, 'steps': [], 'rundir': 'synthetic',
        'qualified_utc': '2026-10-11T00:00:00Z'}))


VENDOR_MODELS = {'anthropic': 'claude-parity', 'openai': 'gpt-parity', 'google': 'gemini-parity',
                 'xai': 'grok-parity', 'alibaba': 'qwen-parity', 'meta': 'llama-parity'}


def _model_for(document):
    """A declared concrete id, else a synthetic id that names the declaration's own vendor family."""
    for model in document['models']:
        if '{' not in model['id']:
            return model['id']
    for model in document['models']:
        if model['family'] in VENDOR_MODELS:
            return VENDOR_MODELS[model['family']]
    return SYNTHETIC_MODEL


def preferences(card, document):
    model = _model_for(document)
    return {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: [document['id']]},
            'tier_models': {tier: {document['id']: model} for tier in tr.TIERS},
            'model_families': {SYNTHETIC_MODEL: SYNTHETIC_FAMILY}}


def cell(card, document, *, qualified=False, local_models=None):
    """The selector's answer for one card on one declaration: admitted, or refused naming what is missing.

    The cell measures this declaration's own capabilities for the card.
    """
    probe = synthetic_probe(document)
    if qualified and probe is not None:
        write_qualification(document, probe)
    elif probe is not None:
        tr.qualification_path(document['id']).unlink(missing_ok=True)
    probes = {document['id']: probe}
    executables = {document['id']: EXECUTABLE_SHA} if probe is not None else {}
    row = {'role': card['id'], 'family': card['family'], 'transport': document['id'],
           'transport_kind': document['transport_kind'], 'qualified': bool(qualified)}
    try:
        chosen = tr.select(card, preferences(card, document), probes=probes, executables=executables,
                           local_models=local_models)
    except tr.TransportRefusal as refusal:
        missing = list(refusal.missing)
        return {**row, 'status': 'refused', 'missing': missing}
    return {**row, 'status': 'admitted', 'missing': [], 'attestation_capability': document['capabilities']['attestation'],
            'selection': {k: chosen[k] for k in ('transport_id', 'model', 'family')}}


def mode_of(card):
    """The CHECK-IN 1 mode of a role: blocking when its card can block, voting when it votes, else advisory."""
    independence = (card.get('independence') or {}).get('kind')
    if tr.is_voting(card):
        return 'voting'
    return 'blocking' if independence in ('specialist', 'investigation') else 'advisory'


def violations(row, card, document):
    """Reasons a cell contradicts the declaration, computed without the selector's own helper functions."""
    problems = []
    requires = card.get('requires') or {}
    declared = document['capabilities']
    kind = document['transport_kind']
    if row['status'] == 'refused':
        if not row['missing'] or any(type(m) is not str or not m for m in row['missing']):
            problems.append('a refusal must name the missing capability')
        return problems
    if 'tools' in requires and tr.TOOLS.index(declared['tools']) < tr.TOOLS.index(requires['tools']):
        problems.append('admitted with fewer tools than the card requires')
    if requires.get('structured_output') and not declared['structured_output']:
        problems.append('admitted without the structured output the card requires')
    if 'attestation_min' in requires and \
            tr.ATTESTATION.index(declared['attestation']) < tr.ATTESTATION.index(requires['attestation_min']):
        problems.append('admitted below the attestation the card requires')
    if 'isolation_min' in requires and \
            tr.ISOLATION.index(declared['isolation']) < tr.ISOLATION.index(requires['isolation_min']) and kind != 'http-model':
        problems.append('admitted below the isolation the card requires')
    if requires.get('blind') and not (kind in tr.BLIND_KINDS or declared['isolation'] in tr.SANDBOX_ISOLATION):
        problems.append('a blind role was admitted on a route that cannot be blind')
    if tr.is_voting(card) and kind in tr.CLI_KINDS + ('host-subagent',) and declared['isolation'] not in tr.SANDBOX_ISOLATION:
        problems.append('a voting role was admitted on a CLI route without sandbox isolation')
    if row.get('selection', {}).get('transport_id') != document['id']:
        problems.append('admitted selection names another transport')
    return problems


def build_record(graphs, *, qualified_states=(False, True)):
    """The parity record the README reads: every cell, with refusals named and labels explicit.

    ``graphs`` is the graph registry's row list. The record states measurements of the stub suite only; a cell
    is never described as supported, and none of it is physics validation.
    """
    roles = cards()
    rows = []
    for qualified in qualified_states:
        for document in declarations():
            for card in roles:
                row = cell(card, document, qualified=qualified)
                row['mode'] = mode_of(card)
                row['label'] = ('admitted by the stub suite; role battery still unqualified'
                                if row['status'] == 'admitted' else
                                'blocked: unqualified transport' if 'qualification' in row['missing'] else
                                'refused: ' + ', '.join(row['missing']))
                rows.append(row)
    return {'schema_version': 1, 'kind': 'parity-record', 'scope': 'stub suite only; not live qualification',
            'transports': {d['id']: {'kind': d['transport_kind'], 'declaration_sha256': tr.declaration_sha256(d)}
                           for d in declarations()},
            'roles': {c['id']: {'family': c['family'], 'mode': mode_of(c)} for c in roles},
            'graphs': [{'id': g['id'], 'version': g['version'], 'roles': list(g['roles'])} for g in graphs],
            'cells': rows}
