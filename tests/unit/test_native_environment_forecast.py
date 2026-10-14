"""Inert source/ordinary-planning controls; no native or physics qualification.

Authored without collection, product imports or test execution. Root supplies the
complete frozen source and helpers before running these prospective controls.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import generation_efficiency as g, science

THREADS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
           'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')


def source_pin(path):
    raw = path.read_bytes()
    return {'path': str(path.absolute()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def source_pair(tmp_path, monkeypatch, *, executor=None, caller=None):
    # Only two exact real source buffers become inert AST fixtures; their code
    # is never imported/evaluated and no environment/native effect is invoked.
    physics = Path(g.__file__).parent.parent / 'physics'
    root = tmp_path / 'ravel'
    (root / 'workflow').mkdir(parents=True)
    (root / 'physics').mkdir()
    execute = (physics / 'reinterpret_db.py').read_text()
    invoke = (physics / 'model_events.py').read_text()
    if executor is not None:
        before, after = executor
        assert execute.count(before) == 1
        execute = execute.replace(before, after)
    if caller is not None:
        before, after = caller
        assert invoke.count(before) == 1
        invoke = invoke.replace(before, after)
    (root / 'physics/reinterpret_db.py').write_text(execute)
    (root / 'physics/model_events.py').write_text(invoke)
    monkeypatch.setattr(g, '__file__', str(root / 'workflow/generation_efficiency.py'))
    return g._Inputs(tmp_path), root / 'physics'


def test_current_default_call_preserves_caller_and_predicts_only_thread_clamps(tmp_path, monkeypatch):
    for key in THREADS: monkeypatch.setenv(key, '8')
    caller_before = g.machine_observation()
    capture = g._Inputs(tmp_path)
    observed, prospective, executor = g.prospective_native_machine(capture)
    physics = Path(g.__file__).parent.parent / 'physics'
    assert observed == caller_before
    expected = deepcopy(caller_before)
    expected['selected_environment'].update({key: '1' for key in THREADS})
    assert prospective == expected
    assert all(g.os.environ[key] == '8' for key in THREADS)
    assert executor == source_pin(physics / 'reinterpret_db.py')
    assert capture.rows[str((physics / 'model_events.py').absolute())] == source_pin(physics / 'model_events.py')
    assert {row['path'] for row in capture.finish()} == {
        str((physics / name).absolute()) for name in ('reinterpret_db.py', 'model_events.py')}


def test_real_public_plan_records_both_sources_without_approval_or_native_effect(tmp_path, monkeypatch):
    from test_generation_efficiency import spec
    from ravel.physics import reinterpret_db
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('planning must not execute a native process')
    monkeypatch.setattr(reinterpret_db, 'execute_native', forbidden)
    value, request = spec(tmp_path / 'source')
    run = tmp_path / 'run'
    science.plan(run, request['path'])
    checkin = json.loads((run / 'inputs/checkin1.json').read_text())
    process = checkin['sections']['iii']['generation_efficiency']['process']
    physics = Path(g.__file__).parent.parent / 'physics'
    assert process['native_environment_source'] == source_pin(physics / 'reinterpret_db.py')
    assert process['native_environment_caller_source'] == source_pin(physics / 'model_events.py')
    assert process['machine']['selected_environment']['OMP_NUM_THREADS'] == '1'
    assert checkin['sections']['iv']['new_generated_events'] == 3
    assert science.verify_plan(run, approved=False)['mode'] == 'model-events'
    assert calls == []
    assert not (run / science.APPROVAL).exists()
    assert not (run / 'execution_attempt.json').exists()


@pytest.mark.parametrize('legacy', [False, True])
def test_exact_supported_legacy_and_optional_base_laws(tmp_path, monkeypatch, legacy):
    change = ('os.environ if environment is None else environment', 'os.environ') if legacy else None
    capture, physics = source_pair(tmp_path, monkeypatch, executor=change)
    _, expected, pin = g.prospective_native_machine(capture)
    assert expected['selected_environment']['MKL_NUM_THREADS'] == '1'
    assert pin == source_pin(physics / 'reinterpret_db.py')
    assert len(capture.finish()) == 2


def test_exact_literal_none_caller_uses_supported_default(tmp_path, monkeypatch):
    capture, _ = source_pair(tmp_path, monkeypatch, caller=(
        "generated_event_ceiling=c['generation']['events'])",
        "generated_event_ceiling=c['generation']['events'], environment=None)"))
    caller, expected, _ = g.prospective_native_machine(capture)
    assert caller['hostname'] == expected['hostname']
    assert all(expected['selected_environment'][key] == '1' for key in THREADS)
    assert len(capture.finish()) == 2


@pytest.mark.parametrize('expression', ["{}", "{'PATH': '/explicit-only'}", 'os.environ.copy()', 'selected_environment'])
def test_explicit_or_unresolved_caller_never_forecasts_inherited_state(tmp_path, monkeypatch, expression):
    capture, _ = source_pair(tmp_path, monkeypatch, caller=(
        "generated_event_ceiling=c['generation']['events'])",
        "generated_event_ceiling=c['generation']['events'], environment=" + expression + ')'))
    with pytest.raises(ValueError, match='explicit or unknown native caller environment'):
        g.prospective_native_machine(capture)


@pytest.mark.parametrize('before,after,message', [
    ('os.environ if environment is None else environment', 'os.environ.copy()', 'transformation'),
    ('os.environ if environment is None else environment', 'environment if environment is None else os.environ', 'transformation'),
    ('environment=None):', 'environment={}):', 'default'),
    ('environment=None):', 'environment=None, **kwargs):', 'default'),
    ("MKL_NUM_THREADS='1'", "MKL_NUM_THREADS='2'", 'thread environment law'),
    (", VECLIB_MAXIMUM_THREADS='1'", '', 'thread environment law'),
    ('    env = dict(', '    environment = {}\n    env = dict(', 'rebinding'),
    ('    explicit_environment = (', "    env['MKL_NUM_THREADS'] = '8'\n    explicit_environment = (", 'rebinding'),
    ('    explicit_environment = (', "    env.update({'PATH': '/changed'})\n    explicit_environment = (", 'rebinding'),
    ('    explicit_environment = (', '    alias = env\n    explicit_environment = (', 'rebinding'),
    ('    explicit_environment = (', "    os.environ['PATH'] = '/changed'\n    explicit_environment = (", 'rebinding'),
])
def test_changed_executor_default_transform_or_later_environment_write_is_refused(tmp_path, monkeypatch, before, after, message):
    capture, _ = source_pair(tmp_path, monkeypatch, executor=(before, after))
    with pytest.raises(ValueError, match=message): g.prospective_native_machine(capture)


@pytest.mark.parametrize('before,after,message', [
    ('    from ravel.physics.reinterpret_db import execute_native', '    from unrelated import execute_native', 'caller binding'),
    ('    from ravel.physics.reinterpret_db import execute_native', '    from ravel.physics.reinterpret_db import execute_native\n    execute_native = foreign', 'caller binding'),
    ("generated_event_ceiling=c['generation']['events'])", "generated_event_ceiling=c['generation']['events'], **selected_environment)", 'caller environment'),
    ('    from ravel.physics.reinterpret_db import execute_native', "    os.environ.update({'PATH': '/changed'})\n    from ravel.physics.reinterpret_db import execute_native", 'rebinding'),
])
def test_unknown_caller_binding_kwargs_or_environment_mutation_is_refused(tmp_path, monkeypatch, before, after, message):
    capture, _ = source_pair(tmp_path, monkeypatch, caller=(before, after))
    with pytest.raises(ValueError, match=message): g.prospective_native_machine(capture)


@pytest.mark.parametrize('member', ['reinterpret_db.py', 'model_events.py'])
def test_ending_rechecks_executor_and_caller_sources(tmp_path, monkeypatch, member):
    capture, physics = source_pair(tmp_path, monkeypatch)
    g.prospective_native_machine(capture)
    path = physics / member
    path.write_bytes(path.read_bytes() + b'\n# changed source after observation\n')
    with pytest.raises(ValueError, match='commitment|changed'): capture.finish()


@pytest.mark.parametrize('where,statement', [
    ('executor', "os.environ = {'PATH': '/replaced'}"),
    ('executor', 'del os.environ'),
    ('caller', "os.environ = {'PATH': '/replaced'}"),
    ('caller', 'del os.environ'),
])
def test_whole_environment_attribute_store_or_delete_is_refused(tmp_path, monkeypatch, where, statement):
    # Inert source mutation only: no live os.environ replacement is executed.
    marker = '    env = dict(' if where == 'executor' else '    from ravel.physics.reinterpret_db import execute_native'
    replacement = '    ' + statement + '\n' + marker
    capture, _ = source_pair(tmp_path, monkeypatch, **{where: (marker, replacement)})
    with pytest.raises(ValueError, match='rebinding'):
        g.prospective_native_machine(capture)


def test_caller_unknown_keyword_outside_authenticated_signature_is_refused(tmp_path, monkeypatch):
    capture, _ = source_pair(tmp_path, monkeypatch, caller=(
        "generated_event_ceiling=c['generation']['events'])",
        "generated_event_ceiling=c['generation']['events'], undeclared_environment_option=True)"))
    with pytest.raises(ValueError, match='caller keyword'):
        g.prospective_native_machine(capture)
