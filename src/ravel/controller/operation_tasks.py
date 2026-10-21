"""Closed, input-bound native task adapters shared by controller routes.

Registration selects installed code, never a worker-provided module or command.
P04 still owns plan admission, signatures, authority, confinement and adoption.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys

from .step import custody, operations
from .step.services import digest

# Each adapter implements validate(task), inputs(task, base), run(task, base, out).
# Expanding this registry requires a source change and a matching operation signature.
REGISTERED = {
    'measurement': 'ravel.physics.measurement',
    'authored-analysis': 'ravel.physics.authored_analysis',
}
FIELDS = {'materializer', 'task_input', 'result_output'}


def _runtime():
    # This installed source root, never an ambient or worker-supplied search path.
    return {'PYTHONPATH': str(Path(__file__).resolve().parents[2]), 'PYTHONNOUSERSITE': '1'}


def declaration(step):
    value = (step.get('parameters') or {}).get('operation_task')
    if (type(value) is not dict or set(value) != FIELDS or value.get('materializer') != 'science-mode'
            or step.get('kind') != 'operate' or (step.get('parameters') or {}).get('launch') is not None):
        raise ValueError('operation task needs a closed registered materializer declaration')
    if value['task_input'] not in {r['artifact'] for r in step.get('inputs') or ()}:
        raise ValueError('operation task must name a declared input')
    from .step.spec import SAFE_PATH
    output = value['result_output']
    if (type(output) is not str or not output.startswith('outputs/') or not SAFE_PATH.fullmatch(output)
            or output not in {r['path'] for r in step.get('outputs') or ()}):
        raise ValueError('operation task result must name a declared confined output')
    operation = step.get('operation')
    signature = operations.signatures().get(operation)
    module = REGISTERED.get(operation)
    if (module is None or signature is None or signature['implementation'] != {
            'kind': 'science-mode', 'mode': operation, 'module': module}):
        raise ValueError('operation has no matching registered task materializer')
    if operations.executor_errors(step, signature):
        raise ValueError('operation task must retain its registered native executor')
    return deepcopy(value), importlib.import_module(module)


def descriptor(step):
    """Approval-time source identity, replayed by the ordinary commitment verifier."""
    _, adapter = declaration(step)
    from .confine.inputs import hash_copy
    from .judgment import schemas
    paths = [Path(__file__).resolve(), Path(adapter.__file__).resolve(),
             operations.SIGNATURES, operations.SIGNATURES.parent / 'roles' / 'executors.json',
             schemas._directory().joinpath('judgment-plan.v1.json'),
             Path(operations.__file__).resolve()]
    return {'adapter': 'operation-task', 'module': __name__, 'operation': step['operation'],
            'implementation': adapter.__name__, 'interpreter': sys.executable,
            'environment': _runtime(),
            'sources': [{'path': str(path), 'sha256': hash_copy(path)[0]} for path in paths],
            'interpreter_sha256': hash_copy(Path(sys.executable).resolve())[0]}


def _load(path):
    from ravel.workflow.state_io import _unique
    def reject(value):
        raise ValueError('nonfinite operation task: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique,
                      parse_constant=reject)


def _validated(adapter, task_path, allowed):
    task = _load(task_path)
    adapter.validate(task)
    paths = adapter.inputs(task, Path(task_path).parent)
    allowed = {Path(p).resolve() for p in allowed}
    if any(Path(p).resolve() not in allowed for p in paths):
        raise ValueError('native task reads a file outside its declared input custody')
    if adapter.__name__ == REGISTERED['authored-analysis'] and task.get('reference_paths'):
        # The outer capsule exposes only declared inputs and installed runtime. A
        # task needing additional withheld paths requires a distinct capsule policy.
        raise ValueError('operation task materializer does not admit withheld reference paths')
    return task


def materialize_launch(step, context):
    """Resolve one retained plan step using accepted input bytes, without executing it."""
    value, adapter = declaration(step)
    store = context['store']
    plan = operations.current_plan(store, context)
    planned = [s for s in plan['steps'] if s['id'] == step['id']]
    if len(planned) != 1 or planned[0] != step:
        raise ValueError('operation task differs from the retained approved step')
    by_id = {s['id']: s for s in plan['steps']}
    ancestors, pending = set(), list(step['depends_on'])
    while pending:
        parent = pending.pop()
        if parent not in by_id or parent == step['id']:
            raise ValueError('operation task dependency is absent or cyclic')
        if parent not in ancestors:
            ancestors.add(parent)
            pending.extend(by_id[parent]['depends_on'])
    errors, adopted, supplied = custody.input_errors(store, step, context['run_dir'], ancestors=ancestors)
    if errors:
        raise ValueError('operation task input custody refused: ' + str(errors))
    rows = [*adopted, *supplied]
    # resolve_launch checks paths, links and hashes before the task reader sees them.
    from .routes.analysis.execution import resolve_launch
    checked = deepcopy(step)
    checked['parameters']['launch'] = {'argv': [sys.executable] + ['@input:' + r['artifact'] for r in rows]}
    resolved = resolve_launch(checked, context, output_root=context['run_dir'], inputs=rows)
    paths = dict(zip((r['artifact'] for r in rows), resolved['argv'][1:]))
    source = value['task_input']
    _validated(adapter, paths[source], paths.values())
    argv = [sys.executable, '-m', __name__, '--operation', step['operation'], '--task', '@input:' + source,
            '--result', value['result_output'].removeprefix('outputs/')]
    for row in rows:
        argv.extend(['--input', '@input:' + row['artifact']])
    return {'argv': argv, 'env': _runtime(), 'reads': [], 'stage': step['operation'],
            'scope': {'operation': step['operation'], 'role': step['role'], 'step_id': step['id'],
                      'plan_sha256': plan['sha256'], 'task_input': source,
                      'operation_task_sha256': digest(value)}}


def _authored(adapter, task, base, output):
    """One authored attempt inside P04's enclosing P05 capsule.

    The native entrypoint is already the confined action: its child inherits that
    same kernel boundary and custody secret. Do not start a second OS sandbox.
    Reuse the authored adapter's syntax, lint, postconditions and classification;
    the standalone authored-study runner retains its own separate sandbox path.
    """
    import hashlib
    import os
    import shutil
    import signal
    import subprocess
    adapter.validate(task)
    if task.get('reference_paths'):
        raise ValueError('operation task materializer does not admit withheld reference paths')
    source = Path(base) / task['code']
    findings = adapter.lint(source.read_text(), task)
    if any(row['severity'] == 'error' for row in findings):
        raise ValueError('authored native task fails its source lint')
    pinned = hashlib.sha256(source.read_bytes()).hexdigest()
    folder = Path(output) / 'authored-analysis'
    folder.mkdir(exist_ok=False)
    work = folder / 'work'
    work.mkdir()
    (work / '.home').mkdir()
    (work / '.tmp').mkdir()
    shutil.copyfile(source, work / 'code.py')
    step_inputs = {'inputs': {row['name']: str((Path(base) / row['path']).resolve())
                             for row in task['io_contract']['inputs']},
                   'parameters': {row['name']: row['value'] for row in task.get('parameters', [])},
                   'outputs': [row['path'] for row in task['io_contract']['outputs']]}
    (work / 'step-inputs.json').write_text(json.dumps(step_inputs, sort_keys=True) + '\n')
    # Keep P05's custody marker and private runtime locations, including cleanup
    # attribution for descendants. The task supplies no environment or command.
    environment = {**os.environ, **adapter._environment(work)}
    proc = subprocess.Popen([sys.executable, '-B', '-s', 'code.py'], cwd=work,
                            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            start_new_session=True)
    try:
        _, stderr = proc.communicate(timeout=task.get('timeout_seconds', 600))
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        _, stderr = proc.communicate()
        timed_out = True
    raw = {'exit_code': proc.returncode, 'timed_out': timed_out, 'started': True,
           'stderr_tail': stderr.decode('utf-8', errors='replace')[-adapter.STDERR_TAIL:]}
    postconditions = adapter.check_outputs(work, task)
    unresolved = (work / 'unresolved.json').read_text()[:2000] if (work / 'unresolved.json').is_file() else None
    failure = adapter.classify(raw, postconditions, unresolved)
    if hashlib.sha256((work / 'code.py').read_bytes()).hexdigest() != pinned:
        failure = 'coding'
    observation = {**raw, 'postconditions': postconditions, 'failure_class': failure,
                   'lint': findings,
                   'unresolved_statement': unresolved, 'code_sha256': pinned,
                   'execution_boundary': 'enclosing_controller_capsule'}
    # Never let authored bytes impersonate the enclosing runner's observation.
    with (folder / 'observation.json').open('x') as stream:
        stream.write(json.dumps(observation, sort_keys=True, allow_nan=False) + '\n')
    if failure is not None:
        raise ValueError('authored native attempt failed: ' + failure)
    outputs = [{'path': (path := work / row['path']).relative_to(output).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for row in task['io_contract']['outputs']]
    return {'status': 'passed', 'kind': 'authored-analysis', 'status_scope': adapter.SCOPE,
            'physics_validated': False, 'attempt': 1, 'outputs': outputs,
            'observation': 'authored-analysis/observation.json',
            'limitations': ['Declared lint and postconditions only; scientific validity requires independent review.']}


NATIVE_RUNNERS = {'authored-analysis': _authored}


def main(argv=None):
    """Fixed confined entrypoint; no module, command or inline-code argument exists."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation', choices=tuple(REGISTERED), required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--input', action='append', default=[])
    parser.add_argument('--result', required=True)
    args = parser.parse_args(argv)
    from .step.spec import SAFE_PATH
    if not SAFE_PATH.fullmatch(args.result):
        raise ValueError('operation task result must remain confined')
    adapter = importlib.import_module(REGISTERED[args.operation])
    task = _validated(adapter, args.task, args.input)
    runner = NATIVE_RUNNERS.get(args.operation)
    result = (runner(adapter, task, Path(args.task).parent, Path.cwd()) if runner else
              adapter.run(task, Path(args.task).parent, Path.cwd()))
    target = Path(args.result)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, sort_keys=True, allow_nan=False) + '\n')
    return 0 if result.get('status') == 'passed' else 3


if __name__ == '__main__':
    raise SystemExit(main())
