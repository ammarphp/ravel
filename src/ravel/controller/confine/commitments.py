"""Protected approval-time operation identities and materialised input bytes.

Deferred producer outputs commit the approved producer and output declaration,
never a future content hash. Existing ``custody.input_errors`` must enforce their
accepted actual bytes at the effect boundary.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

from . import inputs
from ..step import spec
from ..step.services import digest

KIND = 'operation-input-commitment'


def _hash(path):
    try:
        return inputs.hash_copy(path)[0]
    except (OSError, ValueError) as exc:
        raise ValueError(f'operation commitment cannot read {path}: {exc}') from exc


def _under_run(run, spelling):
    path = Path(spelling)
    target = path if path.is_absolute() else run / path
    # Keep the original path for hash_copy(): resolving first would hide symlinks.
    if '..' in target.parts or not target.is_relative_to(run):
        raise ValueError('operation input must be under the run directory')
    return target


def _ancestors(step, by_id):
    found, pending = set(), list(step.get('depends_on') or [])
    while pending:
        name = pending.pop()
        if name not in by_id:
            raise ValueError('operation dependency is absent from the plan')
        if name == step['id']:
            raise ValueError('operation dependency cycle')
        if name not in found:
            found.add(name)
            pending.extend(by_id[name].get('depends_on') or [])
    return found


def _input(ref, run, by_id, ancestors, baseline=None):
    artifact = ref.get('artifact')
    if not isinstance(artifact, str) or not artifact:
        raise ValueError('operation input needs an artifact identity')
    producer, separator, output = artifact.partition(':')
    binding = {}
    if separator:
        source = by_id.get(producer)
        if source is None or producer not in ancestors:
            raise ValueError('operation producer must be a dependency ancestor')
        declarations = [row for row in source.get('outputs') or [] if row.get('path') == output]
        if len(declarations) != 1:
            raise ValueError('operation producer output is not uniquely declared')
        binding = {'producer': producer, 'producer_step_sha256': digest(source),
                   'output': deepcopy(declarations[0])}
    path = ref.get('path') or (f'steps/{producer}/{output}' if separator else artifact)
    target = _under_run(run, path)
    if not ref.get('sha256') and separator:
        if baseline is not None:
            deferred = baseline.get('deferred') is True
        else:
            # A producer artifact present at approval is a byte commitment. A
            # genuinely future output retains only its approved source binding.
            target = _under_run(run, f'steps/{producer}/{output}')
            deferred = not target.exists() and not target.is_symlink()
        if deferred:
            return {'ref': deepcopy(ref), 'deferred': True, **binding}
    sha = _hash(target)
    if ref.get('sha256') and sha != ref['sha256']:
        raise ValueError('operation input digest differs from approval')
    return {'ref': deepcopy(ref), 'deferred': False, 'path': str(target), 'sha256': sha, **binding}


def _file_token(token, run, *, executable=False):
    if executable and '/' not in token:
        spelling = shutil.which(token)
        if spelling is None:
            raise ValueError('operation executable is unavailable')
        path = Path(spelling)
    else:
        path = Path(token)
        if not path.is_absolute():
            path = run / path
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError('operation file token is unavailable: ' + token) from exc
    return {'token': token, 'resolved': str(resolved), 'sha256': _hash(resolved)}


def _materializer(plan, step):
    """Pin installed input-bound route code; P04 must still materialise its argv."""
    if (step.get('parameters') or {}).get('operation_task') is not None:
        from ..operation_tasks import descriptor
        return descriptor(step)
    from ..routes.select import find, adapter_module, spec_sha256
    route = plan.get('route') or {}
    if not isinstance(route, dict) or not route.get('id'):
        raise ValueError('native operation without argv needs an approved installed route')
    try:
        spec = find(route['id'])
        actual = spec_sha256(spec)
        if route.get('spec_sha256') is not None and route['spec_sha256'] != actual:
            raise ValueError('operation route spec differs from approval')
        declared = (step.get('parameters') or {}).get('route_adapter')
        if declared is not None and declared != spec.get('adapter'):
            raise ValueError('operation route adapter differs from installed family')
        module = adapter_module(spec)
    except (LookupError, ImportError) as exc:
        raise ValueError('operation materializer adapter is unavailable') from exc
    if module is None or not getattr(module, '__file__', None):
        raise ValueError('operation route has no installed materializer module')
    try:
        path = Path(module.__file__).resolve(strict=True)
    except OSError as exc:
        raise ValueError('operation materializer module file is unavailable') from exc
    return {'route_id': route['id'], 'route_spec_sha256': actual,
            'adapter': spec['adapter'], 'module': module.__name__,
            'path': str(path), 'sha256': _hash(path)}


def _body(plan, run_dir, baseline=None):
    if not isinstance(plan.get('sha256'), str) or not plan['sha256']:
        raise ValueError('operation commitment needs an authenticated plan sha256')
    run = Path(run_dir).absolute()
    steps = plan.get('steps') or []
    by_id = {step['id']: step for step in steps}
    if len(by_id) != len(steps):
        raise ValueError('operation plan has duplicate step ids')
    rows = []
    previous = {row['id']: row for row in (baseline or {}).get('steps', [])}
    for step in steps:
        launch = (step.get('parameters') or {}).get('launch')
        if not (step.get('operation') or step.get('kind') in ('operate', 'acquire') or launch is not None):
            continue
        # Only a confined launch commits an executable and its argv; an acquire or operation step that the
        # governed step runs as a worker session (no launch) commits its inputs like any worker step.
        native = spec.branch(step) == 'launch'
        ancestors = _ancestors(step, by_id)
        refs = step.get('inputs') or []
        prior_inputs = (previous.get(step['id']) or {}).get('inputs', [])
        row = {'id': step['id'], 'step_sha256': digest(step), 'native': native,
               'inputs': [_input(ref, run, by_id, ancestors,
                                 prior_inputs[index] if index < len(prior_inputs) else None)
                          for index, ref in enumerate(refs)]}
        if native:
            argv = (launch or {}).get('argv')
            if argv is None:
                row.update(mode='input-bound-materializer', materializer=_materializer(plan, step))
                rows.append(row)
                continue
            if not isinstance(argv, list) or not argv or not all(isinstance(t, str) and t for t in argv):
                raise ValueError('native operation needs a materialised nonempty string argv')
            from ..routes.analysis.execution import acquisition_implementation
            action = acquisition_implementation(step)
            files = []
            if action is not None:
                row['controller_action'] = action
                files.append({'index': 0, **_file_token(action['interpreter'], run, executable=True)})
            declared = {ref['artifact'] for ref in refs}
            for index, token in enumerate(argv):
                if token.startswith('@input:'):
                    if index == 0 or token[len('@input:'):] not in declared:
                        raise ValueError('operation argv names an undeclared input')
                    continue
                if index == 0 and action is not None:
                    continue
                if index == 0:
                    files.append({'index': index, **_file_token(token, run, executable=True)})
                    continue
                candidate = Path(token) if Path(token).is_absolute() else run / token
                try:
                    is_file = candidate.is_file()
                except (OSError, ValueError):
                    is_file = False
                if is_file:
                    files.append({'index': index, **_file_token(token, run)})
            row.update(argv_sha256=digest(argv), files=files)
        rows.append(row)
    return {'plan_sha256': plan['sha256'], 'run_dir': str(run), 'steps': rows}


def _records(store, sha):
    found = []
    for envelope in store.scan(KIND):
        record = envelope.get('record', envelope)
        if record.get('plan_sha256') == sha:
            identifier = envelope.get('id') or envelope.get('record_id') or record.get('_record_id')
            if not identifier:
                raise ValueError('operation commitment has no protected record id')
            found.append((identifier, record))
    if found and any(record != found[0][1] for _, record in found[1:]):
        raise ValueError('operation commitments conflict for the approved plan')
    return found


def create(store, plan, run_dir):
    """Append an approval commitment, or reuse an exactly equal protected record."""
    if not isinstance(plan.get('sha256'), str) or not plan['sha256']:
        raise ValueError('operation commitment needs an authenticated plan sha256')
    found = _records(store, plan['sha256'])
    body = _body(plan, run_dir, baseline=found[0][1] if found else None)
    if found:
        if found[0][1] != body:
            raise ValueError('operation commitment changed since approval')
        return found[0][0]
    return store.append(KIND, body)


def verify(store, plan, step, run_dir):
    """Verify approval identities and current pinned bytes; return the record id.

    Deferred outputs additionally require ``custody.input_errors`` at effect time.
    No deferred entry asserts a content digest for bytes not yet produced.
    """
    if not plan.get('sha256'):
        raise ValueError('operation verification needs an approved plan sha256')
    found = _records(store, plan['sha256'])
    if not found:
        raise ValueError('operation has no protected input commitment')
    body = _body(plan, run_dir, baseline=found[0][1])
    if found[0][1] != body:
        raise ValueError('operation commitment differs from current plan or bytes')
    matches = [row for row in body['steps'] if row['id'] == step.get('id')]
    if len(matches) != 1 or matches[0]['step_sha256'] != digest(step):
        raise ValueError('operation step differs from approval')
    return found[0][0]
