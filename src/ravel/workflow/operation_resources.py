"""Declared non-event solver work at an ordinary checked stage boundary.

Counts describe the approved source operation; the generic owner enforces wall
time, not arbitrary in-process solver invocation counts. A solver's actual count
must be retained and checked by its source-bound worker. No approval is created.
"""
from copy import deepcopy
import math
from pathlib import Path
import json
import hashlib
import os
import stat

MAX_DOCUMENT_BYTES = 8*1024**2


def document_pin(path):
    """Bounded descriptor read with an ending ordinary-path identity check."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('solver authority must use ordinary paths')
    before=path.stat()
    def identity(s):
        return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_DOCUMENT_BYTES:
        raise ValueError('solver authority must be a nonempty ordinary document of at most8MiB')
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        raw=stream.read(MAX_DOCUMENT_BYTES+1)
        finished=os.fstat(stream.fileno())
    if (len(raw)>MAX_DOCUMENT_BYTES or len(raw)!=before.st_size
            or any(p.is_symlink() for p in (path,*path.parents))
            or any(identity(s)!=identity(before) for s in (opened,finished,path.stat()))):
        raise ValueError('solver authority changed during its bounded read')
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'text':raw.decode('utf-8')}


def document(path):
    from .state_io import _unique
    def finite(value):
        raise ValueError('nonfinite solver authority: '+value)
    def floating(value):
        result=float(value)
        if not math.isfinite(result):finite(value)
        return result
    return json.loads(document_pin(path)['text'],object_pairs_hook=_unique,parse_constant=finite,parse_float=floating)


def validate(value):
    if type(value) is not dict or set(value) != {
            'schema_version', 'kind', 'generated_events', 'solver_evaluations', 'max_seconds'}:
        raise ValueError('closed solver operation resources required')
    if (type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['kind'] != 'solver'
            or type(value['generated_events']) is not int or value['generated_events'] != 0
            or type(value['solver_evaluations']) is not int or value['solver_evaluations'] <= 0
            or type(value['max_seconds']) not in (int, float)
            or not math.isfinite(value['max_seconds']) or value['max_seconds'] <= 0):
        raise ValueError('solver requires positive evaluations/time and exactly zero generated events')
    return deepcopy(value)


def fields(mapping):
    return {'operation_resources': validate(mapping['operation_resources'])} if 'operation_resources' in mapping else {}


def binding(rundir, declaration, *, stage=None, command=None, cwd=None, inputs=None, outputs=None,
            events=None, max_seconds=None):
    """Re-read exact approval inputs; launch authorization checks their approval.

    Return the task/endpoint authority paths for a separate receipt commitment.
    They cannot enter the plan fingerprint: the contract hashes that very plan.
    Supplied resource classes alone never admit zero-event generic computation.
    """
    from . import execution
    declaration = validate(declaration)
    root = Path(rundir).resolve()
    contract_path = execution.resolve_path(root, 'inputs/task_contract.json')
    contract = document(contract_path)
    if contract.get('operation_resources') != declaration:
        raise ValueError('operation resources differ from the task contract')
    pin = contract.get('execution_plan', {})
    if type(pin) is not dict or set(pin) != {'path', 'sha256'}:
        raise ValueError('solver operation requires its task-bound endpoint plan')
    path = execution.resolve_path(root, pin['path'])
    if not path.is_relative_to(root):
        raise ValueError('solver endpoint plan must be inside its run')
    plan = document(path)
    if execution.file_hash(path) != pin['sha256']:
        raise ValueError('solver endpoint plan differs from the task contract')
    if plan.get('operation_resources') != declaration or plan.get('max_seconds') != declaration['max_seconds']:
        raise ValueError('endpoint solver resources differ from the declared contract')
    if stage is not None:
        matches = [s for s in plan.get('stages', []) if s.get('stage') == stage]
        if len(matches) != 1 or matches[0].get('operation_resources') != declaration:
            raise ValueError('solver stage lacks its exact endpoint resource declaration')
        expected = matches[0]
        if (expected.get('command') != list(command) or Path(expected.get('cwd', root)).resolve() != Path(cwd).resolve()
                or not {execution.resolve_path(root, p) for p in expected.get('inputs', [])}
                    <= {execution.resolve_path(root, p) for p in inputs}
                or {execution.resolve_path(root, p, output=True) for p in expected.get('outputs', [])}
                    != {execution.resolve_path(root, p, output=True) for p in outputs}):
            raise ValueError('solver command and artifacts differ from its endpoint plan')
    if events is not None and (type(events) is not int or events != 0):
        raise ValueError('solver stage must declare zero generated events')
    if max_seconds is not None and (type(max_seconds) not in (int, float) or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= declaration['max_seconds']):
        raise ValueError('solver stage exceeds its declared time ceiling')
    return [str(contract_path), str(path)]


def authority(rundir, declaration, **kwargs):
    from . import execution
    return execution.snapshot(rundir, binding(rundir, declaration, **kwargs))


def check_record(rundir, record):
    """Freshly verify the committed task/plan authority at finish and reuse."""
    declaration = validate(record['operation_resources'])
    actual = authority(rundir, declaration, stage=record['stage'], command=record['command'],
        cwd=record['cwd'], inputs=record['inputs'], outputs=record['outputs'])
    if actual != record.get('operation_authority'):
        raise ValueError('solver task/endpoint authority changed since launch')


def retained(snapshot, context, command):
    """Offline resource meaning against the retained first approval and endpoint."""
    spec = context.get('stage_spec', {})
    # The retained approved task class is authoritative. Context omission must
    # not reclassify a solver as an ordinary legacy launch.
    if snapshot.get('approval_kind') == 'science':
        if fields(spec) or 'operation_inputs' in snapshot:
            raise ValueError('unexpected solver authority in a scientific study')
        return
    contract = json.loads(snapshot['approval_inputs'][0]['text'])
    declared = fields(contract)
    if fields(spec) != declared:
        raise ValueError('retained solver resource class differs from the approved task')
    if not declared:
        if 'operation_inputs' in snapshot:
            raise ValueError('unexpected retained solver authority')
        return
    d = declared['operation_resources']
    pins = snapshot.get('operation_inputs', [])
    if len(pins) != 2:
        raise ValueError('solver launch lacks its retained task and endpoint')
    docs = []
    for pin in pins:
        raw = pin['text'].encode()
        if len(raw) > 8*1024**2 or hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('retained solver authority changed or exceeds its byte ceiling')
        docs.append(json.loads(raw))
    contract, plan = docs
    root = Path(snapshot['approval_inputs'][0]['path']).parent.parent
    if (pins[0]['path'] != snapshot['approval_inputs'][0]['path']
            or pins[0]['sha256'] != snapshot['approval_inputs'][0]['sha256']
            or contract['operation_resources'] != d or plan['operation_resources'] != d
            or plan['max_seconds'] != d['max_seconds']
            or pins[1]['sha256'] != contract['execution_plan']['sha256']
            or Path(pins[1]['path']) != root/contract['execution_plan']['path']
            or context.get('kind') != 'scientific-stage' or snapshot['required_plan'] != 'full'
            or type(context.get('events')) is not int or context['events'] != 0
            or type(context.get('max_seconds')) not in (int,float)
            or not 0 < context['max_seconds'] <= d['max_seconds']):
        raise ValueError('retained solver approval, resources or time differ')
    rows=[row for row in plan['stages'] if row['stage']==context['stage']]
    if len(rows)!=1 or rows[0].get('operation_resources')!=d or rows[0]['command']!=command:
        raise ValueError('retained solver stage differs from the declared endpoint')
    row=rows[0]
    def paths(values):
        return {str(Path(p) if Path(p).is_absolute() else root/p) for p in values}
    expected_authority={pin['path']:{'kind':'file','files':[{
        'name':'.','size':len(pin['text'].encode()),'sha256':pin['sha256']}]} for pin in pins}
    if (Path(row.get('cwd',root)) != Path(spec['cwd'])
            or not paths(row['inputs']) <= paths(spec['inputs'])
            or paths(row['outputs']) != paths(spec['outputs'])
            or context.get('operation_authority') != expected_authority):
        raise ValueError('retained solver artifacts or authority differ from the declared endpoint')
