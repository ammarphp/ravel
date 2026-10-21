"""Controller-recorded manuscript procedure requests and private sink exports."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from . import common, legacy

REQUEST = 'manuscript-procedure'


def request(binding):
    """Pin a verified assembly for the outer controller's procedure delivery."""
    from ravel.controller.routes.manuscript import staged
    assembly = staged.assemble(binding, publish=False)
    path = Path(binding.output_root) / 'outputs/assembly.json'
    raw = path.read_bytes()
    if path.is_symlink() or json.loads(raw) != assembly:
        raise ValueError('the procedure requires the current assembly bytes')
    record = {'schema_version': 1, 'run_id': binding.store.run_id,
              'plan_sha256': binding.plan['sha256'], 'step_id': binding.step_id,
              'assembly_path': str(path), 'assembly_sha256': hashlib.sha256(raw).hexdigest(),
              'assembly': assembly}
    previous = [row['record'] for row in binding.store.scan(REQUEST)]
    if record not in previous:
        binding.store.append(REQUEST, record)
    return deepcopy(record)


def prepare_delivery(store, plan, run_dir):
    """Recheck the requested assembly and build its procedure from current custody."""
    rows = [row for row in store.scan(REQUEST) if row['record'].get('plan_sha256') == plan.get('sha256')]
    if not rows:
        assemblies = [row for row in store.scan('manuscript-assembly')
                      if row['record'].get('plan_sha256') == plan.get('sha256')]
        if assemblies:
            raise ValueError('the completed manuscript assembly requires its procedure-note request')
        return None
    from ravel.controller.routes.manuscript import staged
    from ravel.controller.routes.ml import staged as artifacts
    from ravel.workflow import procedure_export

    root = Path(run_dir).resolve()
    requests = {}
    for row in rows:
        record = row['record']
        requests[record['step_id']] = row
    steps = {step['id']: step for step in plan['steps']}
    for step_id, row in requests.items():
        record = row['record']
        if record['run_id'] != store.run_id or (steps.get(step_id, {}).get('graph') or {}).get('id') != 'manuscript.build':
            raise ValueError('the procedure request belongs to its current controller manuscript step')
        assembly = staged.assemble(staged.Binding(store, root, plan, step_id), publish=False)
        path = Path(record['assembly_path'])
        if (not path.resolve().is_relative_to(root / 'steps' / step_id / 'attempts')
                or any(p.is_symlink() for p in (path, *path.parents))
                or assembly != record['assembly']
                or hashlib.sha256(path.read_bytes()).hexdigest() != record['assembly_sha256']):
            raise ValueError('the procedure assembly changed after its recorded request')

    document = procedure_export.build(root, status='incomplete')
    index = artifacts.custody_index(store)
    sources = {pin['path']: pin for pin in document['source_pins']}
    outputs = {}
    selected = {artifact for artifact, row in index.items()
                if row.get('step_id') in steps and row.get('status') == 'accepted'}
    pending = list(selected)
    while pending:
        artifact = pending.pop()
        for parent in index[artifact].get('inputs') or []:
            if parent not in index:
                raise ValueError('the procedure requires every retained custody ancestor: ' + parent)
            if parent not in selected:
                selected.add(parent)
                pending.append(parent)
    for artifact in sorted(selected):
        row = index[artifact]
        step_id = row.get('step_id')
        _, path, custody = artifacts.adopted(store, root, step_id, row['path'], index=index)
        pin = {'path': str(path), 'sha256': custody['sha256'], 'size': path.stat().st_size}
        sources[pin['path']] = pin
        outputs.setdefault(step_id, []).append(pin)
    outcomes = {}
    for row in store.scan('step-outcome'):
        record = row['record']
        if record.get('step_id') in steps:
            outcomes[record['step_id']] = row
    for step_id, row in outcomes.items():
        document['nodes'].append({'id': 'controller:' + step_id, 'kind': 'controller-step',
            'stage': step_id, 'run': str(root), 'status': row['record']['status'],
            'depends_on': ['controller:' + parent for parent in steps[step_id].get('depends_on', [])
                           if parent in outcomes],
            'unresolved_parents': [parent for parent in steps[step_id].get('depends_on', []) if parent not in outcomes],
            'source_pins': outputs.get(step_id, []), 'missing_artifacts': [],
            'controller_record': {'id': row['id'], 'sha256': common.digest(row)}})
    document['source_pins'] = [sources[key] for key in sorted(sources)]
    document['controller'] = {'run_id': store.run_id, 'plan_sha256': plan['sha256'],
        'procedure_requests': [{'id': row['id'], 'sha256': common.digest(row), 'record': row['record']}
                               for row in requests.values()],
        'outcomes': list(outcomes.values())}
    document['verification_scope'] = 'controller custody digests and retained procedure source bytes'
    document['procedure_status'] = ('complete' if all(step['id'] in outcomes and
        outcomes[step['id']]['record']['status'] == 'completed' for step in plan['steps']) else 'incomplete')
    for pin in document['source_pins']:
        procedure_export._check_pin(pin, deep=True)
    return document


def write(staging, document):
    """Export the computed procedure inside the sink's private atomic delivery."""
    if document is None:
        return []
    from ravel.workflow import procedure_export
    target = Path(staging) / 'procedure'
    with legacy.stage('manuscript-procedure'):
        procedure_export.export(document['run'], target, _document=document)
    procedure_export.verify(target, deep=True)
    files = []
    for path in sorted(target.rglob('*')):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
        if path.is_file():
            relative = path.relative_to(staging).as_posix()
            files.append({'artifact': 'sink:' + relative, 'deliverables': [], 'path': relative,
                'sha256': common.sha256_file(path), 'size': path.stat().st_size,
                'source': 'controller:manuscript-procedure', 'source_sha256': common.digest(document), 'labels': []})
    return files
