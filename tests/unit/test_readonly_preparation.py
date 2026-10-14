"""Prospective controls; no claim of actual admission, physics or speedup.

Real ValidationSessions/files and source adapter arithmetic exercise the lifetime.
Worker join fixtures explicitly stand in for authority/process registration only;
the unchanged original registration/approval suites remain required independently.
No subprocess, provider, model, graph or native effect is needed in this file.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.workflow import execution, science, readonly_preparation as rp
from ravel.workflow.validation_io import ValidationSession
from ravel.workflow.state_io import read_json, atomic_json


def session(root, runtime=None):
    root.mkdir(parents=True, exist_ok=True)
    current = {'version': 'synthetic'} if runtime is None else runtime
    return ValidationSession(root, resolve_path=lambda base, value, output=False: Path(value) if Path(value).is_absolute() else base / value,
        read_json=read_json, runtime_context=lambda: deepcopy(current),
        digest=execution.digest, state_name='ledger.json')


def owner_at(root, monkeypatch, *, process_binding=None):
    monkeypatch.setattr(execution, '_validation_session', lambda root: session(Path(root)))
    return rp.WorkerReadOnlyObservation(root, process_binding=process_binding)


def tiny_module(paths=(), result=None):
    """Source-independent engineering adapter, never scientific authority."""
    value = {'status': 'passed', 'physics_validated': False, 'values': [3, 7]} if result is None else result
    module = SimpleNamespace()
    def inputs(task, base): return list(paths)
    def run(task, base, out): raise AssertionError('eligible preparation invoked effectful run')
    def readonly_inputs(task, base, context): return inputs(task, base)
    def calculate(task, base, context): return deepcopy(value)
    def materialize(result, spec, context): return (('adapter.json', rp._bytes(result)),)
    module.inputs, module.run = inputs, run
    module.readonly_inputs, module.calculate, module.materialize = readonly_inputs, calculate, materialize
    module.READONLY_WORKER_V1 = rp.ReadOnlyAdapterV1(
        tuple((name, getattr(module, name)) for name in ('inputs', 'run', 'readonly_inputs', 'calculate', 'materialize')),
        readonly_inputs, calculate, materialize, False)
    return module


def prepare(owner, module, root, original=None, effective=None):
    original = {'value': 1} if original is None else original
    effective = {'value': 2} if effective is None else effective
    owner.inputs(module, original, root, 'original')
    owner.inputs(module, effective, root, 'effective')
    result = owner.calculate(effective, root)
    spec = {'schema_version': 2, 'mode': 'engineering', 'task': effective}
    proposal = {'attempt': 1, 'base_dir': str(root), 'output_directory': 'outputs/attempt-1'}
    owner.materialize(proposal, spec, result)
    return result, proposal, spec


def test_detached_bundle_closes_before_first_write_and_retains_complete_bytes(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    with owner_at(root, monkeypatch) as owner:
        result, proposal, spec = prepare(owner, tiny_module(), root)
        bundle = owner.finish()
        assert not (root / 'outputs').exists()
        assert not owner.closed and not owner.session.closed
    assert owner.closed and owner.session.closed and owner.resources == {}
    expected = bundle.result_bytes
    result['values'][0] = 99
    proposal['attempt'] = 99
    spec['task']['value'] = 99
    out = root / 'outputs' / 'attempt-1'
    out.mkdir(parents=True)
    returned = bundle.write(out)
    atomic_json(out / 'result.json', returned)
    bundle.check_delivery(out, out, returned)
    assert (out / 'adapter.json').read_bytes() == expected
    assert returned['values'] == [3, 7] and bundle.proposal['attempt'] == 1


@pytest.mark.parametrize('change', ['ledger', 'runtime', 'absence', 'tracked', 'file', 'inventory'])
def test_later_participant_callback_cannot_escape_earlier_terminal(tmp_path, change):
    first = session(tmp_path / 'first')
    current = {'version': 'one'}
    second = session(tmp_path / 'second', current)
    data = first.rundir / 'data.bin'; data.write_bytes(b'old')
    first.require_regular(data); first.hash_file(data)
    absent = first.rundir / 'absent'; first.require_inventory(absent)
    obj = {'x': 1}; first.track(obj)
    directory = first.rundir / 'members'; directory.mkdir(); (directory / 'a').write_bytes(b'a')
    first.require_inventory(directory)
    def late():
        assert not first.closed
        if change == 'ledger': first.ledger.write_text('{}')
        elif change == 'runtime': first.runtime_context = lambda: {'version': 'changed'}
        elif change == 'absence': absent.mkdir()
        elif change == 'tracked': obj['x'] = 2
        elif change == 'file': data.write_bytes(b'new')
        else: (directory / 'b').write_bytes(b'b')
    second.retain_final_check(late)
    for s in (first, second): s.readonly_freeze()
    for s in (first, second): s.readonly_drain()
    with pytest.raises(ValueError): first.readonly_terminal()
    assert not first.closed and not second.closed
    first.close(); second.close()


def test_final_read_addition_is_in_complete_tail_and_old_baseline_cannot_refresh(tmp_path):
    s = session(tmp_path)
    path = tmp_path / 'late'; path.write_bytes(b'first')
    s.retain_final_check(lambda: s.hash_file(path))
    s.retain_final_check(lambda: path.write_bytes(b'other'))
    s.readonly_freeze(); s.readonly_drain()
    with pytest.raises(ValueError, match='identity changed|file changed'): s.readonly_terminal()
    s.close()
    t = session(tmp_path / 'other')
    p = t.rundir / 'data'; p.write_bytes(b'old'); t.hash_file(p)
    t.readonly_freeze()
    p.write_bytes(b'new')
    # Explicitly replacing a first commitment cannot turn drift into a baseline.
    t.files[str(p)] = ('replaced-original',)
    t.readonly_drain()
    with pytest.raises(ValueError, match='original'): t.readonly_terminal()
    t.close()


@pytest.mark.parametrize('which', ['method', 'direct_list'])
def test_callback_registration_after_freeze_refuses(tmp_path, which):
    s = session(tmp_path)
    s.readonly_freeze()
    with pytest.raises(ValueError):
        if which == 'method': s.retain_final_check(lambda: None)
        else:
            s.final_checks.append(lambda: None)
            s.readonly_drain()
    s.close()


@pytest.mark.parametrize('which', ['original', 'effective', 'proposal', 'result'])
def test_complete_mutable_arguments_refuse_late_changes(tmp_path, monkeypatch, which):
    original, effective = {'value': 1}, {'value': 2}
    with owner_at(tmp_path, monkeypatch) as owner:
        result, proposal, _ = prepare(owner, tiny_module(), tmp_path, original, effective)
        value = {'original': original, 'effective': effective, 'proposal': proposal, 'result': result}[which]
        owner.add_ending_check(lambda: value.update(extra='late'))
        with pytest.raises(ValueError, match='changed'): owner.finish()
    assert owner.closed and owner.session.closed


def test_original_effective_callbacks_and_calculation_population_are_distinct(tmp_path, monkeypatch):
    module = tiny_module()
    seen = []
    original_hook = module.readonly_inputs
    module.readonly_inputs = lambda task, base, context: (seen.append(deepcopy(task)) or original_hook(task, base, context))
    d = module.READONLY_WORKER_V1
    module.READONLY_WORKER_V1 = rp.ReadOnlyAdapterV1(tuple((n, module.readonly_inputs if n == 'readonly_inputs' else f) for n, f in d.bindings), module.readonly_inputs, d.calculate, d.materialize, False)
    with owner_at(tmp_path, monkeypatch) as owner:
        prepare(owner, module, tmp_path)
        assert seen == [{'value': 1}, {'value': 2}]
        with pytest.raises(ValueError, match='one read-only'): owner.calculate({'value': 2}, tmp_path)
        owner.finish()


@pytest.mark.parametrize('kind', ['missing', 'run_in_worker', 'injected_input', 'injected_run', 'hook'])
def test_initial_incompatible_descriptor_has_full_fallback(tmp_path, monkeypatch, kind):
    module = tiny_module()
    if kind == 'missing': del module.READONLY_WORKER_V1
    elif kind == 'run_in_worker': module.run_in_worker = lambda *_: None
    elif kind == 'injected_input': module.inputs = lambda *_: []
    elif kind == 'injected_run': module.run = lambda *_: None
    else: module._validation_inputs = lambda *_: []
    if kind == 'hook':
        d = module.READONLY_WORKER_V1
        module.READONLY_WORKER_V1 = rp.ReadOnlyAdapterV1((*d.bindings, ('_validation_inputs', None)), d.inputs, d.calculate, d.materialize, False)
    assert rp.select_descriptor(module) is None


@pytest.mark.parametrize('kind', ['run', 'calculate', 'descriptor', 'parent', 'thread'])
def test_late_ownership_or_callable_change_never_downgrades_to_effect(tmp_path, monkeypatch, kind):
    module = tiny_module()
    process = [11, 22, 'start']
    reader = lambda pid: process[2]
    process_module = SimpleNamespace(process_identity=reader)
    monkeypatch.setattr(rp.os, 'getpid', lambda: process[0]); monkeypatch.setattr(rp.os, 'getppid', lambda: process[1])
    with owner_at(tmp_path, monkeypatch, process_binding=(process_module, reader, tuple(process))) as owner:
        prepare(owner, module, tmp_path)
        def late():
            if kind == 'run': module.run = lambda *_: None
            elif kind == 'calculate': module.calculate = lambda *_: None
            elif kind == 'descriptor': module.READONLY_WORKER_V1 = None
            elif kind == 'parent': process[1] += 1
            else: owner.thread += 1
        owner.add_ending_check(late)
        with pytest.raises(ValueError): owner.finish()
    assert owner.closed and not (tmp_path / 'outputs').exists()


def test_late_process_identity_after_session_tail_refuses_detached_return(tmp_path, monkeypatch):
    process = [11, 22, 'start']; reader = lambda pid: process[2]
    module = SimpleNamespace(process_identity=reader)
    monkeypatch.setattr(rp.os, 'getpid', lambda: process[0]); monkeypatch.setattr(rp.os, 'getppid', lambda: process[1])
    with owner_at(tmp_path, monkeypatch, process_binding=(module, reader, tuple(process))) as owner:
        prepare(owner, tiny_module(), tmp_path)
        real = owner.session.readonly_terminal
        def tail(): real(); process[2] = 'replacement-start'
        monkeypatch.setattr(owner.session, 'readonly_terminal', tail)
        with pytest.raises(ValueError, match='process ownership'): owner.finish()


def test_primary_callback_failure_closes_every_resource_and_keeps_cleanup_diagnostic(tmp_path, monkeypatch):
    with owner_at(tmp_path, monkeypatch) as owner:
        prepare(owner, tiny_module(), tmp_path)
        other = session(tmp_path / 'other')
        class Resource:
            def __enter__(self): return self
            def readonly_check(self): pass
            def readonly_freeze(self): pass
            def readonly_sessions(self): return (other,)
            def readonly_close(self): other.close(); raise RuntimeError('secondary-close')
        # Register an actual module factory so the live ownership guard applies.
        import sys
        def Factory(): return Resource()
        monkeypatch.setattr(sys.modules[__name__], 'Factory', Factory, raising=False)
        owner.resource(Factory)
        owner.add_ending_check(lambda: (_ for _ in ()).throw(ValueError('primary-drain')))
        with pytest.raises(ValueError, match='primary-drain') as caught:
            try: owner.finish()
            except BaseException as primary: owner.close(primary); raise
        assert other.closed and owner.session.closed and any('secondary-close' in n for n in caught.value.__notes__)


def test_new_participant_during_drain_refuses_and_existing_reads_remain_allowed(tmp_path, monkeypatch):
    from ravel.workflow.fresh_replication import _ProducerSessions
    with owner_at(tmp_path, monkeypatch) as owner:
        prepare(owner, tiny_module(), tmp_path)
        def late(): owner.resource(_ProducerSessions)
        owner.add_ending_check(late)
        with pytest.raises(ValueError, match='new participant'): owner.finish()


@pytest.mark.parametrize('change', ['source', 'member', 'symlink'])
def test_full_input_identity_inventory_and_ancestry_stay_live(tmp_path, monkeypatch, change):
    root = tmp_path / 'run'; root.mkdir()
    directory = root / 'data'; directory.mkdir(); payload = directory / 'payload'; payload.write_bytes(b'old')
    with owner_at(root, monkeypatch) as owner:
        prepare(owner, tiny_module([payload]), root)
        owner.session.require_inventory(directory)
        def late():
            if change == 'source': payload.write_bytes(b'new')
            elif change == 'member': (directory / 'extra').write_bytes(b'new')
            else:
                target = root / 'saved'; directory.rename(target); directory.symlink_to(target, target_is_directory=True)
        owner.add_ending_check(late)
        with pytest.raises(ValueError): owner.finish()


@pytest.mark.parametrize('kind', ['destination', 'writer', 'return', 'common', 'artifact'])
def test_detached_commit_failure_cannot_overwrite_or_rebaseline(tmp_path, monkeypatch, kind):
    with owner_at(tmp_path, monkeypatch) as owner:
        prepare(owner, tiny_module(), tmp_path); bundle = owner.finish()
    out = tmp_path / 'out'; out.mkdir()
    if kind == 'destination':
        (out / 'adapter.json').write_bytes(b'accepted earlier')
        with pytest.raises(FileExistsError): bundle.write(out)
        assert (out / 'adapter.json').read_bytes() == b'accepted earlier'
        return
    if kind == 'writer':
        def refuse(*args, **kwargs): raise OSError('synthetic write failure')
        monkeypatch.setattr(Path, 'open', refuse)
        with pytest.raises(OSError, match='write failure'): bundle.write(out)
        assert owner.closed
        return
    result = bundle.write(out); atomic_json(out / 'result.json', result)
    if kind == 'return': result['values'][0] = 99
    elif kind == 'common': (out / 'result.json').write_text('{"status":"passed","physics_validated":false,"values":[99,7]}')
    else: (out / 'adapter.json').write_bytes(b'altered')
    with pytest.raises(ValueError): bundle.check_delivery(out, out, result)


def test_delivery_bounds_refuse_whole_population_without_truncation(tmp_path, monkeypatch):
    with owner_at(tmp_path, monkeypatch) as owner:
        module = tiny_module()
        owner.inputs(module, {}, tmp_path, 'original'); owner.inputs(module, {}, tmp_path, 'effective')
        result = owner.calculate({}, tmp_path)
        monkeypatch.setattr(rp, 'MAX_RESULT_BYTES', 1)
        with pytest.raises(ValueError, match='byte bound'): owner.materialize({}, {}, result)
    assert owner.closed and not (tmp_path / 'outputs').exists()


def test_path_object_population_remains_bound_without_json_coercion(tmp_path, monkeypatch):
    path = tmp_path / 'payload'; path.write_bytes(b'input')
    with owner_at(tmp_path, monkeypatch) as owner:
        prepare(owner, tiny_module([path]), tmp_path)
        paths = owner.path_arguments[0][0]
        assert paths == [path]
        owner.add_ending_check(lambda: paths.clear())
        with pytest.raises(ValueError, match='arguments or delivery'): owner.finish()


def test_pre_admission_injection_falls_back_without_adapter_import_or_owner(tmp_path, monkeypatch):
    def imported(_): raise AssertionError('adapter resolution happened before admission')
    monkeypatch.setattr(science, 'adapter', imported)
    assert science.prepare_readonly_worker(tmp_path, verifier=science.verify_worker) is None
    assert not (tmp_path / 'outputs').exists()


def test_legacy_schema_keeps_original_worker_admission_path(tmp_path, monkeypatch):
    monkeypatch.setattr(science, 'review_enabled', lambda _: False)
    assert science.prepare_readonly_worker(tmp_path, verifier=science.verify_worker) is None


def test_standalone_comparison_preserves_injected_two_argument_request(tmp_path, monkeypatch):
    from ravel.physics import research_comparison as comparison
    fixed = {'direction': 'maximize', 'tolerance': 0, 'min_gain': 0, 'uncertainty': 'deterministic'}
    request = {'cells': [], 'protocol_sha256': '1' * 64, 'comparison_id': 'inert', 'rule': {'sha256': '2' * 64}}
    def old_request(task, base): return request, fixed, []
    monkeypatch.setattr(comparison, '_request', old_request)
    assert comparison.inputs({}, tmp_path) == []
    assert comparison.calculate({'request': {'sha256': '3' * 64}}, tmp_path)['cell_count'] == 0
    assert rp.select_descriptor(comparison) is None


def comparison_task(root, *, quality=True, uncertainty='deterministic', left=5, right=3):
    root.mkdir(parents=True, exist_ok=True)
    def emit(name, value):
        path = root / name; atomic_json(path, value)
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size}
    a = emit('left.json', {'value': left, 'quality': quality, 'interval': [left, left]})
    b = emit('right.json', {'value': right, 'quality': True, 'interval': [right, right]})
    fixed = emit('rule.json', {'schema_version': 1, 'metric': 'supplied', 'unit': '1', 'direction': 'maximize', 'min_gain': 0, 'tolerance': 0,
        'uncertainty': uncertainty, 'reduction': 'all_cells'})
    sides = lambda pin: {'source': pin, 'value_pointer': '/value', 'quality_pointer': '/quality', 'interval_pointer': '/interval'}
    request = emit('request.json', {'schema_version': 1, 'protocol_sha256': '1' * 64, 'comparison_id': 'supplied-finite-control', 'rule': fixed,
        'cells': [{'id': 'cell', 'metric': 'supplied', 'unit': '1', 'exposure': 'adaptive_full', 'left': sides(a), 'right': sides(b)}], 'dependencies': []})
    return {'schema_version': 1, 'request': request}


@pytest.mark.parametrize('quality,left,right,decision', [(True, 5, 3, 'better'), (True, 1, 3, 'worse'), (False, 5, 3, 'unknown')])
def test_complete_comparison_old_new_result_and_artifact_bytes_match(tmp_path, monkeypatch, quality, left, right, decision):
    from ravel.physics import research_comparison as comparison
    task = comparison_task(tmp_path / 'inputs', quality=quality, left=left, right=right)
    oldout = tmp_path / 'legacy'; oldout.mkdir()
    old = comparison.run(task, tmp_path, oldout)
    with owner_at(tmp_path / 'run', monkeypatch) as owner:
        result, _, _ = prepare(owner, comparison, tmp_path, task, task)
        bundle = owner.finish()
    out = tmp_path / 'new'; out.mkdir(); assert bundle.write(out) == old
    assert result['decision'] == decision and result['physics_validated'] is False
    assert (out / 'research-comparison.json').read_bytes() == (oldout / 'research-comparison.json').read_bytes()
    assert result['complete_original_cell_denominator'] == ['cell']


def test_complete_derived_old_new_covariance_units_population_and_bytes_match(tmp_path, monkeypatch):
    # The fixture is the unchanged original full correlated source definition.
    from test_derived_quantities import sample
    from ravel.physics import derived_quantities as derived
    contract, joint, _ = sample.__wrapped__(tmp_path)
    path = tmp_path / 'contract.json'; atomic_json(path, contract)
    task = {'schema_version': 1, 'input': str(path), 'contract_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    old = derived.run(task, tmp_path, tmp_path / 'legacy')
    with owner_at(tmp_path / 'run', monkeypatch) as owner:
        new, _, _ = prepare(owner, derived, tmp_path, task, task)
        bundle = owner.finish()
    assert new == old and len(new['output_basis']) == 12 and len(new['input_basis']) == 16
    assert new['output_covariance'] == old['output_covariance'] and new['inference'] is None
    out = tmp_path / 'new'; bundle.write(out)
    assert (out / 'derived-quantities.json').read_bytes() == (tmp_path / 'legacy' / 'derived-quantities.json').read_bytes()


def test_producer_rechecks_remain_run_bound_and_full_semantic_recheck(tmp_path, monkeypatch):
    from ravel.workflow import fresh_replication as fresh
    seen = []
    def verifier(root, approved=False, *, _session=None, _recheck=False):
        seen.append((Path(root), _session.rundir, approved, _recheck)); return {}
    monkeypatch.setattr(science, 'verify_plan', verifier)
    monkeypatch.setattr(science, 'review_enabled', lambda _: True)
    monkeypatch.setattr(execution, '_validation_session', lambda root: session(Path(root)))
    a, b = tmp_path / 'a', tmp_path / 'b'; a.mkdir(); b.mkdir()
    with fresh._ProducerSessions() as scope:
        for root in (a, b, a):
            s = scope.session_for(root)
            science.verify_plan(root, approved=True, _session=s, _recheck=True)
        assert len(scope.entries) == 2
    assert seen == [(a, a, True, True), (b, b, True, True), (a, a, True, True)]


def test_public_worker_preserves_clock_and_ordinary_common_delivery_after_closed_preparation(tmp_path, monkeypatch):
    """Actual worker main/common writers; disclosed inert admission and figures."""
    from ravel.physics import science_worker as worker
    from ravel.plotting import science_figures
    task = comparison_task(tmp_path / 'inputs')
    with owner_at(tmp_path / 'run', monkeypatch) as owner:
        from ravel.physics import research_comparison
        owner.inputs(research_comparison, task, tmp_path, 'original')
        owner.inputs(research_comparison, task, tmp_path, 'effective')
        result = owner.calculate(task, tmp_path)
        spec = {'schema_version': 2, 'mode': 'research-comparison', 'task': task,
                'assumptions': ['Supplied arithmetic; no acceptance']}
        proposal = {'attempt': 1, 'base_dir': str(tmp_path), 'output_directory': 'outputs/attempt-1',
                    'stage_binding': {'input_snapshot': {}}}
        owner.materialize(proposal, spec, result); bundle = owner.finish()
    rd = tmp_path / 'run'
    monkeypatch.setattr(science, 'prepare_readonly_worker', lambda *a, **k: (bundle.proposal, bundle))
    monkeypatch.setattr(science_figures, 'render', lambda *a: {'figures': [], 'tables': []})
    assert worker.main([str(rd), '--attempt', '1']) == 0
    out = rd / 'outputs' / 'attempt-1'
    assert read_json(out / 'result.json') == result and read_json(out / 'recipe.json')['specification'] == spec
    assert not read_json(out / 'verification.json')['physics_validated']
    assert (out / 'research-comparison.json').read_bytes() == bundle.result_bytes


@pytest.mark.parametrize('mutation', ['positive', 'status', 'parent', 'child', 'identity', 'fingerprint'])
def test_extracted_independent_worker_predicates_keep_real_process_record_conditions(tmp_path, monkeypatch, mutation):
    """Actual predicate body, explicitly synthetic prior plan/launch authority."""
    from ravel.workflow import physics_review
    s = session(tmp_path)
    atomic_json(tmp_path / 'execution_attempt.json', {'attempt': 1})
    p = {'base_dir': str(tmp_path)}
    stage = {'inputs': ['data'], 'outputs': ['outputs/attempt-1'], 'command': ['worker']}
    binding = {'fingerprint': 'exact', 'inputs': ['data']}
    record = {'status': 'running', 'supervisor_pid': science.os.getppid(), 'child_pid': science.os.getpid(),
              'child_identity': 'synthetic-start', 'fingerprint': 'exact'}
    if mutation == 'status': record['status'] = 'succeeded'
    elif mutation == 'parent': record['supervisor_pid'] += 1
    elif mutation == 'child': record['child_pid'] += 1
    elif mutation == 'identity': record['child_identity'] = 'changed'
    elif mutation == 'fingerprint': record['fingerprint'] = 'changed'
    seen = []
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **kw: p)
    monkeypatch.setattr(science, '_selected', lambda *a, **kw: (stage, binding, 30))
    monkeypatch.setattr(science, '_check_launch_selection', lambda *a: seen.append(a[2]))
    monkeypatch.setattr(execution, 'load_execution', lambda _: {'stages': {'science': record}})
    monkeypatch.setattr(execution, 'process_identity', lambda _: 'synthetic-start')
    monkeypatch.setattr(physics_review, '_stage_spec', lambda *a: {'synthetic': True})
    if mutation == 'positive':
        result = science._verify_worker_observed(tmp_path, s)
        assert result['attempt'] == 1 and result['output_directory'] == 'outputs/attempt-1'
    else:
        with pytest.raises(ValueError, match='current approved supervised attempt'):
            science._verify_worker_observed(tmp_path, s)
    assert seen == ['science']
    s.close()


@pytest.mark.parametrize('change', ['positive', 'refused_admission', 'attempt', 'late_process'])
def test_public_preparation_driver_registration_admission_calculation_ending(tmp_path, monkeypatch, change):
    """Real driver and adapter/lifetime; authority callback is inert and disclosed."""
    from ravel.physics import research_comparison as comparison
    task = comparison_task(tmp_path / 'inputs')
    root = tmp_path / 'run'; root.mkdir()
    atomic_json(root / 'execution_attempt.json', {'attempt': 1, 'correction_plan_sha256': None})
    events = []; process = ['synthetic-start']; owners = []
    spec = {'schema_version': 2, 'mode': 'research-comparison', 'task': task}
    monkeypatch.setattr(science, 'review_enabled', lambda _: True)
    monkeypatch.setattr(science, '_await_worker_registration', lambda _: events.append('registered'))
    def factory(root):
        assert events == ['registered']
        events.append('session')
        return session(root)
    monkeypatch.setattr(execution, '_validation_session', factory)
    monkeypatch.setattr(science, '_READONLY_SESSION_FACTORY', factory)
    monkeypatch.setattr(science, 'execution_spec', lambda *a, **k: deepcopy(spec))
    def admitted(root, s, *, _readonly=None):
        events.append('admission'); owners.append(_readonly)
        if change == 'refused_admission': raise ValueError('explicit inert authority refusal')
        _readonly.inputs(comparison, task, tmp_path, 'original')
        _readonly.inputs(comparison, task, tmp_path, 'effective')
        if change == 'late_process':
            _readonly.add_ending_check(lambda: monkeypatch.setattr(execution, 'process_identity', lambda _: 'changed-start'))
        return {'attempt': 1, 'base_dir': str(tmp_path), 'output_directory': 'outputs/attempt-1'}
    monkeypatch.setattr(science, '_verify_worker_observed', admitted)
    monkeypatch.setattr(science, '_READONLY_CORE_BINDINGS', tuple((name, getattr(science, name)) for name, _ in science._READONLY_CORE_BINDINGS))
    if change == 'positive':
        proposal, bundle = science.prepare_readonly_worker(root, verifier=science.verify_worker, attempt='1')
        assert proposal['attempt'] == 1 and bundle.result['decision'] == 'better'
        assert isinstance(bundle, rp.PreparedDelivery) and owners[0].descriptor is comparison.READONLY_WORKER_V1
    else:
        with pytest.raises(ValueError):
            science.prepare_readonly_worker(root, verifier=science.verify_worker, attempt='2' if change == 'attempt' else '1')
    assert events == ['registered', 'session', 'admission']
    assert owners[0].closed and owners[0].session.closed and not (root / 'outputs').exists()
