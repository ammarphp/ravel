"""Portable explicit cap0 argument controls; all process/build custody is mocked.

The actual adapter, metadata census, argument construction and evidence writes
are exercised. These tests neither execute Rivet nor qualify native weights.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import existing_events as adapter
from ravel.physics import routine_build
from ravel.workflow import science
from ravel.workflow.execution import file_hash
from ravel.workflow.state_io import atomic_json, read_json
from test_rivet_built_adapter import task, evidence


def initial(value):
    value = copy.deepcopy(value)
    value.update(backend='rivet', source_root='upstream')
    value.pop('build_receipt'); value.pop('build_plan')
    value['runtime'].update(executable='rivet', build='rivet-build',
                            artifacts=['library.so'], environment={})
    value['observables'][0].pop('quantity_kind')
    value['observables'][0]['axes'] = [{'name': 'x', 'unit': '1'}]
    return value


@pytest.mark.parametrize('built', [False, True])
@pytest.mark.parametrize('bad', [None, False, True, 0.0, -0.0, 1, -1,
                                '0', [], {}, float('inf'), float('nan')])
def test_only_literal_integer_zero_is_admitted_before_process(built, bad, monkeypatch, tmp_path):
    value = task() if built else initial(task())
    value['native_weight_cap'] = bad
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *_a, **_k: pytest.fail('native call'))
    with pytest.raises(ValueError, match='literal integer zero'):
        adapter.run(value, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_native_selection_does_not_acquire_rivet_option():
    value = {'backend': 'native-selection', 'events': 'events.json',
             'object_contract': 'objects.json', 'selection': 'selection.json',
             'native_weight_cap': 0}
    with pytest.raises(ValueError, match='task fields'):
        adapter.validate(value)


@pytest.mark.parametrize('built', [False, True])
@pytest.mark.parametrize('mode', ['NU', 'EL'])
@pytest.mark.parametrize('cap', [False, True])
def test_exact_capped_or_legacy_argv_and_retained_declaration(tmp_path, monkeypatch, built, mode, cap):
    root, plugin, _, original, _, _ = evidence(tmp_path, monkeypatch)
    value = task() if built else initial(task())
    value['options'] = {'LMODE': mode}
    if cap:
        value['native_weight_cap'] = 0
    # Explicit signed/zero all-event population; metadata and counters remain
    # independent of any native projection or particle-fill count.
    event = (tmp_path / 'events.hepmc').read_text()
    prefix, row = event.split('E 0', 1)
    row = 'E 0' + row.split('HepMC::Asciiv3-END_EVENT_LISTING')[0]
    rows = [row.replace('E 0', f'E {i}', 1).replace('W 1\n', f'W {w}\n', 1)
            for i, w in enumerate((-.5, 0, 2))]
    (tmp_path / 'events.hepmc').write_text(prefix + ''.join(rows) + 'HepMC::Asciiv3-END_EVENT_LISTING\n')
    meta = read_json(tmp_path / 'metadata.json'); meta['events'] = 3
    atomic_json(tmp_path / 'metadata.json', meta)
    if not built:
        row = {'id': value['routine'], 'name': value['routine'],
               'source_files': [{'path': original.name}]}
        monkeypatch.setattr(adapter, '_source_files', lambda _t:
            ({'sources': {'rivet': {'revision': 'synthetic-pinned-source'}}}, row, [original]))
        (tmp_path / 'rivet-build').write_text('synthetic build executable')
        (tmp_path / 'out').mkdir()
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *_a, **_k:
                        SimpleNamespace(returncode=0, stdout='rivet v4.1.3\n'))
    calls = []

    def call(command, cwd, env, log):
        calls.append(list(command)); Path(log).write_text('unit routing observation')
        if '--weight-nominal' in command:
            if built:
                atomic_json(tmp_path / 'out/loader-event-observation.json', {
                    'kind': 'unit-dispatch-observation', 'plugin': str(plugin), 'environment': env,
                    'runtime_version': '4.1.3', 'python': {
                        'path': str(Path(value['runtime']['python']).resolve()),
                        'sha256': file_hash(value['runtime']['python'])}})
            (tmp_path / 'out/histograms.yoda').write_text('synthetic routing output')
        elif '-j' in command:
            Path(command[command.index('1') + 1]).write_bytes(b'synthetic compiled plugin')
        else:
            atomic_json(tmp_path / 'out/observables.json', {
                'observables': {value['observables'][0]['path']: {}},
                'event_counters': {'/RAW/_EVTCOUNT': {'entries': 3, 'sumw': 1.5, 'sumw2': 4.25}}})

    monkeypatch.setattr(adapter, '_call', call)
    result = adapter.run(value, tmp_path, tmp_path / 'out')
    native = next(command for command in calls if '--weight-nominal' in command)
    assert native[native.index('-a') + 1] == value['routine'] + ':LMODE=' + mode
    assert native[native.index('--weight-nominal') + 1] == 'nominal'
    assert result['census']['sumw'] == [1.5]
    assert result['census']['group_weight_second_moments'] == [[4.25]]
    declaration = tmp_path / 'out/native-dispatch.json'
    if cap:
        assert native.count('--weight-cap') == 1 and native[native.index('--weight-cap') + 1] == '0'
        assert native[-1] == str(tmp_path / 'events.hepmc')
        assert result['native_weight_cap'] == 0 and result['declared_analysis_options'] == {'LMODE': mode}
        assert result['native_effective_weights_observed'] is False
        record = read_json(declaration)
        assert record['launched_command'] == native
        assert record['events_sha256'] == file_hash(tmp_path / 'events.hepmc')
        assert record['native_weight_cap'] == 0 and record['declared_analysis_options'] == {'LMODE': mode}
        assert record['native_effective_weights_observed'] is False and record['physics_validated'] is False
        assert result['native_dispatch'] == {'path': declaration.name, 'sha256': file_hash(declaration)}
        assert record['native_cli_command'][1].endswith('/rivet')
        if built:
            assert native[1] == '-c' and native[2] == routine_build.RIVET_LOADER_OBSERVER
            reuse = read_json(tmp_path / 'out/build-reuse.json')
            assert reuse['command'] == native and reuse['native_dispatch'] == result['native_dispatch']
        else:
            assert record['native_cli_command'] == native
    else:
        assert '--weight-cap' not in native and not declaration.exists()
        assert not {'native_weight_cap', 'declared_analysis_options', 'native_dispatch',
                    'native_effective_weights_observed'} & result.keys()
        if built:
            assert 'native_dispatch' not in read_json(tmp_path / 'out/build-reuse.json')


def test_initial_cap_option_requires_v2_before_input_or_process(tmp_path, monkeypatch):
    value = initial(task())
    spec = {'schema_version': 1, 'mode': 'analyze', 'source': 'synthetic argument control',
            'assumptions': ['No native weight qualification'], 'max_seconds': 30,
            'approval_mode': 'scripted_yes', 'task': value}
    assert not science._new_capability(spec)
    value['native_weight_cap'] = 0
    assert science._new_capability(spec)
    monkeypatch.setattr(adapter, 'inputs', lambda *_a, **_k: pytest.fail('legacy cap input planning'))
    source = tmp_path / 'spec.json'; atomic_json(source, spec)
    with pytest.raises(ValueError, match='version 2'):
        science.plan(tmp_path / 'refused', source)
    assert not (tmp_path / 'refused').exists()


@pytest.mark.parametrize('built', [False, True])
def test_actual_v2_preparation_binds_option_without_native_call(tmp_path, monkeypatch, built):
    _, _, _, original, _, _ = evidence(tmp_path, monkeypatch)
    value = task() if built else initial(task())
    value.update(native_weight_cap=0, options={'LMODE': 'EL'})
    if not built:
        row = {'id': value['routine'], 'name': value['routine'],
               'source_files': [{'path': original.name}]}
        monkeypatch.setattr(adapter, '_source_files', lambda _t:
            ({'sources': {'rivet': {'revision': 'synthetic-source'}}}, row, [original]))
        (tmp_path / 'rivet-build').write_text('synthetic build executable')
    spec = {'schema_version': 2, 'mode': 'analyze', 'source': 'synthetic prospective cap argument control',
        'assumptions': ['No native argument, projection or weights are qualified by planning'],
        'max_seconds': 30, 'max_attempts': 1, 'approval_mode': 'scripted_yes', 'task': value,
        'review_policy': {'schema_version': 1, 'policy': {'schema_version': 1,
            'actors': {'proposer': 'producer', 'executor': 'executor', 'physics_critic': 'critic',
                       'skeptical_verifier': 'skeptic', 'physics_decider': 'decider'},
            'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
            'required_checks': [{'id': 'integrity', 'kind': 'integrity'},
                                {'id': 'scientific', 'kind': 'scientific'}],
            'claim_scopes': {'argument_declaration': {'checks': ['integrity', 'scientific'],
                                                    'actions': ['delivery', 'reuse']}}},
            'correction_contract': {'task_fields': [], 'input_slots': []}}}
    path = tmp_path / 'spec.json'; atomic_json(path, spec)
    # Replace only this adapter's module binding. Patching the global stdlib
    # subprocess.run also blocks ordinary platform identity collection.
    monkeypatch.setattr(adapter, 'subprocess', SimpleNamespace(run=lambda *_a, **_k:
        pytest.fail('planning invoked an adapter native process')))
    monkeypatch.setattr(adapter, '_call', lambda *_a, **_k: pytest.fail('planning invoked native route'))
    planned = tmp_path / 'prepared-only'
    science.plan(planned, path)
    assert science.verify_plan(planned)['schema_version'] == 2
    assert read_json(planned / science.SPEC)['task']['native_weight_cap'] == 0
    assert not (planned / science.APPROVAL).exists()
    assert not (planned / 'outputs/attempt-1').exists()
    # Planning copied the intake specification; the retained study copy is
    # authoritative. Changing the intake file does not rewrite that capsule.
    spec['task'].pop('native_weight_cap'); atomic_json(path, spec)
    assert science.verify_plan(planned)['schema_version'] == 2
    assert read_json(planned / science.SPEC)['task']['native_weight_cap'] == 0
    captured = read_json(planned / science.SPEC); captured['task'].pop('native_weight_cap')
    atomic_json(planned / science.SPEC, captured)
    with pytest.raises(ValueError):
        science.verify_plan(planned)
    assert not (planned / 'outputs/attempt-1').exists()
