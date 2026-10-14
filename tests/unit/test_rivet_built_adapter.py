"""Built-plugin dispatch boundaries; real build evidence is tested separately."""
import copy
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

from ravel.physics import existing_events as adapter
from ravel.physics import routine_build
from ravel.workflow.execution import file_hash
from ravel.workflow.state_io import atomic_json, read_json


def task():
    return {'backend': 'rivet-built', 'routine': 'UnlistedSourceBooked',
            'build_receipt': 'built/build-receipt.json', 'build_plan': 'built/build-plan.json',
            'events': 'events.hepmc', 'metadata': 'metadata.json',
            'runtime': {'python': sys.executable, 'version': '4.1.3'},
            'observables': [{'path': '/UnlistedSourceBooked/count', 'axes': [],
                             'representation': 'integrated', 'normalization': 'absolute',
                             'unit': '1', 'quantity_kind': 'scalar_counter'}],
            'options': {}, 'seed': 23}


def evidence(tmp_path, monkeypatch):
    """A supplied stub isolates routing; it does not pretend to observe a build."""
    root = tmp_path / 'built'; (root / 'work/source/assets').mkdir(parents=True)
    (root / 'work/build').mkdir()
    plugin = root / 'work/build/RivetUnknown.so'; plugin.write_bytes(b'unit dispatch plugin')
    source = root / 'work/source/assets/model.dat'; source.write_bytes(b'bound asset')
    executable = tmp_path / 'rivet'; executable.write_text('runtime'); executable.chmod(0o755)
    dependency = tmp_path / 'library.so'; dependency.write_bytes(b'library')
    original = tmp_path / 'source.cc'; original.write_text('original')
    config = tmp_path / 'routine-build.json'; config.write_text('{}')
    capsule = tmp_path / 'capsule.json'; capsule.write_text('{}')
    log = root / 'probe.log'; log.write_text('retained observation')
    inventory = root / 'source-inventory.json'; inventory.write_text('{}')
    plan = {'framework': 'rivet', 'routine': 'UnlistedSourceBooked', 'base_dir': str(tmp_path),
            'input': {'path': str(config)}, 'source_capsule': {'path': str(capsule)},
            'source_inventory': {'files': [{'path': 'assets/model.dat'}],
                                 'layout': {'asset_dirs': ['assets']}},
            'runtime_identity': {'tools': {'probe': {'path': str(executable), 'sha256': file_hash(executable)}},
                                 'artifacts': [{'path': str(Path(sys.executable).resolve()), 'sha256': file_hash(sys.executable)},
                                               {'path': str(dependency), 'sha256': file_hash(dependency)}],
                                 'environment': {}},
            'probe_expectation': {'executable': 'probe'}}
    receipt = {'binary': {'path': 'work/build/RivetUnknown.so', 'sha256': file_hash(plugin)},
               'logs': {'probe.log': {'path': 'probe.log'}}}
    atomic_json(root / 'build-plan.json', plan); atomic_json(root / 'build-receipt.json', receipt)
    calls = []
    def verify(value, selected, base, output):
        calls.append((value, selected, base, output))
        assert base == str(tmp_path) and output == root
        if file_hash(plugin) != value['binary']['sha256']:
            raise ValueError('binary changed')
        return {'status': 'passed'}
    monkeypatch.setattr(routine_build, 'verify_receipt', verify)
    monkeypatch.setattr(routine_build, 'inputs', lambda *a: [config, capsule, original, executable, dependency])
    def loader_observation(value, binary, routine, env, cwd, stdout, stderr):
        # A routing stub, separate from actual-image tests in test_routine_build.
        assert value['kind'] == 'unit-dispatch-observation'
        assert value['plugin'] == str(binary) and value['environment'] == env
        assert b'unit routing observation' in stdout or b'unit dispatch observation' in stdout
        return {'status': 'passed', 'physics_validated': False, 'scope': 'unit routing stub'}
    monkeypatch.setattr(routine_build, 'verify_loader_observation', loader_observation)
    (tmp_path / 'events.hepmc').write_text('''HepMC::Version 3.03.01
HepMC::Asciiv3-START_EVENT_LISTING
W nominal
E 0 1 4
U GEV MM
W 1
P 1 0 2212 0 0 6500 6500 0 4
P 2 0 2212 0 0 -6500 6500 0 4
V -1 0 [1,2]
P 3 -1 11 75 0 0 75 0 1
P 4 -1 -11 -75 0 0 75 0 1
HepMC::Asciiv3-END_EVENT_LISTING
''')
    atomic_json(tmp_path / 'metadata.json', {'schema_version': 1, 'event_level': 'hadron', 'beam_pdg': [2212, 2212],
        'beam_energy_gev': [6500, 6500], 'weight_names': ['nominal'], 'events': 1, 'groups': 'independent',
        'cross_section_pb': 1., 'source': 'synthetic structural fixture, no physics'})
    return root, plugin, source, original, dependency, calls


def test_scalar_is_explicit_on_both_rivet_backends():
    value = task(); adapter.validate(value)
    old = copy.deepcopy(value); old['backend'] = 'rivet'; old['source_root'] = 'upstream'
    old.pop('build_receipt'); old.pop('build_plan')
    old['runtime'].update(executable='rivet', build='rivet-build', artifacts=['library'], environment={})
    adapter.validate(old)
    # Scalar support is now common to the retained and source-built routes.
    # Untyped zero-axis declarations remain ambiguous and must refuse.
    old['observables'][0].pop('quantity_kind')
    with pytest.raises(ValueError, match='one or two explicit continuous axes'):
        adapter.validate(old)
    old['observables'][0]['axes'] = [{'name': 'pT', 'unit': 'GeV'}]
    adapter.validate(old)


@pytest.mark.parametrize('change', [lambda v: v['observables'][0].update(axes=[{'name': 'x', 'unit': '1'}]),
    lambda v: v['observables'][0].update(representation='differential'),
    lambda v: v['observables'][0].update(normalization='normalized'),
    lambda v: v['observables'][0].update(quantity_kind='scalar'),
    lambda v: v['runtime'].update(environment={}), lambda v: v.update(source_root='fallback'),
    lambda v: v.update(seed=True), lambda v: v.update(observables=[])])
def test_closed_built_contract_refuses_ambiguous_overrides(change):
    value = task(); change(value)
    with pytest.raises(ValueError):
        adapter.validate(value)


def test_read_only_inputs_include_retained_and_original_closure(tmp_path, monkeypatch):
    root, plugin, staged, original, dependency, calls = evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: pytest.fail('planning spawned a process'))
    files = adapter.inputs(task(), tmp_path)
    assert {root / 'build-receipt.json', root / 'build-plan.json', root / 'source-inventory.json',
            root / 'probe.log', plugin, staged, original, dependency} <= set(files)
    assert len(files) == len(set(files)) and len(calls) == 1


def test_grounding_is_part_of_input_census_and_rechecked_before_events(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch)
    oracle = tmp_path / 'source-oracle.json'
    oracle.write_text('{"precision":"declared before execution"}')
    value = task()
    value['grounding'] = [{'path': oracle.name, 'sha256': file_hash(oracle)}]
    adapter.validate(value)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: pytest.fail('grounding validation spawned a process'))
    assert oracle in adapter.inputs(value, tmp_path)
    oracle.write_text('{"precision":"changed after admission"}')
    with pytest.raises(ValueError, match='grounding evidence bytes differ'):
        adapter.run(value, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('defect', ['empty', 'bad_digest', 'duplicate', 'extra_field', 'blank_path'])
def test_grounding_rejects_ambiguous_pins(defect):
    value = task()
    pin = {'path': 'oracle.json', 'sha256': 'a' * 64}
    value['grounding'] = [pin]
    if defect == 'empty': value['grounding'] = []
    elif defect == 'bad_digest': pin['sha256'] = 'A' * 64
    elif defect == 'duplicate': value['grounding'].append(dict(pin))
    elif defect == 'extra_field': pin['optional'] = True
    else: pin['path'] = ' '
    with pytest.raises(ValueError, match='grounding'):
        adapter.validate(value)


@pytest.mark.parametrize('defect', ['alias', 'symlink'])
def test_grounding_rejects_resolved_duplicates_and_symlinks(tmp_path, monkeypatch, defect):
    evidence(tmp_path, monkeypatch)
    oracle = tmp_path / 'oracle.json'; oracle.write_text('{}')
    value = task()
    value['grounding'] = [{'path': str(oracle), 'sha256': file_hash(oracle)}]
    if defect == 'alias':
        value['grounding'].append({'path': oracle.name, 'sha256': file_hash(oracle)})
    else:
        link = tmp_path / 'link.json'; link.symlink_to(oracle)
        value['grounding'][0]['path'] = str(link)
    adapter.validate(value)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: pytest.fail('grounding validation spawned a process'))
    refusal = ('duplicate evidence' if defect == 'alias'
               else re.escape(f"input path traverses a symlink: {tmp_path / 'link.json'}"))
    with pytest.raises(ValueError, match=refusal):
        adapter.inputs(value, tmp_path)


@pytest.mark.parametrize('defect', ['routine', 'python', 'binary', 'receipt_path'])
def test_built_binding_rejects_identity_change_without_tool_execution(tmp_path, monkeypatch, defect):
    root, plugin, _, _, _, _ = evidence(tmp_path, monkeypatch)
    value = task()
    if defect == 'routine': value['routine'] = 'Other'
    elif defect == 'python':
        unbound = tmp_path / 'unbound-python'; unbound.write_text('different interpreter'); unbound.chmod(0o755)
        value['runtime']['python'] = str(unbound)
    elif defect == 'binary': plugin.write_bytes(b'changed')
    else: value['build_receipt'] = str(root / 'other.json'); atomic_json(root / 'other.json', {})
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: pytest.fail('planning spawned a process'))
    with pytest.raises(ValueError): adapter.inputs(value, tmp_path)


def test_event_route_reuses_exact_plugin_and_checks_complete_population(tmp_path, monkeypatch):
    root, plugin, _, _, _, verifications = evidence(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='rivet v4.1.3\n'))
    def call(command, cwd, env, log):
        calls.append((command, cwd, env))
        Path(log).write_text('unit routing observation')
        if '--weight-nominal' in command:
            assert command[1] == '-c' and command[2] == routine_build.RIVET_LOADER_OBSERVER
            atomic_json(tmp_path / 'out/loader-event-observation.json', {
                'kind': 'unit-dispatch-observation', 'plugin': str(plugin), 'environment': env,
                'runtime_version': '4.1.3', 'python': {'path': str(Path(sys.executable).resolve()), 'sha256': file_hash(sys.executable)}})
            assert env['RIVET_ANALYSIS_PLUGINS'] == str(plugin)
            assert env['RIVET_DATA_PATH'] == str(root / 'work/source/assets')
            (tmp_path / 'out/histograms.yoda').write_text('unit routing output')
        else:
            atomic_json(tmp_path / 'out/observables.json', {'observables': {'/UnlistedSourceBooked/count': {}},
                'event_counters': {'/RAW/_EVTCOUNT': {'entries': 1, 'sumw': 1, 'sumw2': 1}}})
    monkeypatch.setattr(adapter, '_call', call)
    result = adapter.run(task(), tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False and result['rebuild'] is False
    assert len(calls) == 2 and len(verifications) == 3
    assert result['plugin_sha256'] == file_hash(plugin)
    assert read_json(tmp_path / 'out/build-reuse.json')['rebuild'] is False


def test_failed_integrity_is_delegated_before_any_event_process(tmp_path, monkeypatch):
    evidence(tmp_path, monkeypatch)
    def refused(*args): raise ValueError('original source changed')
    monkeypatch.setattr(routine_build, 'verify_receipt', refused)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: pytest.fail('event process ran'))
    with pytest.raises(ValueError, match='original source changed'):
        adapter.run(task(), tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('defect', ['omitted_output', 'wrong_population', 'changed_binary'])
def test_event_delivery_refuses_partial_population_or_changed_reused_binary(tmp_path, monkeypatch, defect):
    _, plugin, _, _, _, _ = evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='rivet v4.1.3\n'))
    def call(command, cwd, env, log):
        Path(log).write_text('unit dispatch observation')
        if '--weight-nominal' in command:
            atomic_json(tmp_path / 'out/loader-event-observation.json', {
                'kind': 'unit-dispatch-observation', 'plugin': str(plugin), 'environment': env,
                'runtime_version': '4.1.3', 'python': {'path': str(Path(sys.executable).resolve()), 'sha256': file_hash(sys.executable)}})
        else:
            values = {} if defect == 'omitted_output' else {'/UnlistedSourceBooked/count': {}}
            atomic_json(tmp_path / 'out/observables.json', {'observables': values,
                'event_counters': {'/RAW/_EVTCOUNT': {'entries': 0 if defect == 'wrong_population' else 1,
                                                     'sumw': 1, 'sumw2': 1}}})
            if defect == 'changed_binary': plugin.write_bytes(b'changed during events')
    monkeypatch.setattr(adapter, '_call', call)
    with pytest.raises(ValueError): adapter.run(task(), tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out/build-reuse.json').exists()


@pytest.mark.parametrize('defect', ['missing', 'ambiguous', 'version', 'python'])
def test_event_loader_custody_failure_stops_before_export(tmp_path, monkeypatch, defect):
    _, plugin, _, _, _, _ = evidence(tmp_path, monkeypatch)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='rivet v4.1.3\n'))
    exports = []
    def call(command, cwd, env, log):
        if '--weight-nominal' not in command:
            exports.append(command)
            pytest.fail('output export ran despite failed plugin custody')
        Path(log).write_text('unit dispatch observation')
        if defect != 'missing':
            atomic_json(tmp_path / 'out/loader-event-observation.json', {
                'kind': 'unit-dispatch-observation', 'plugin': str(plugin), 'environment': env,
                'runtime_version': '0.0.0' if defect == 'version' else '4.1.3',
                'python': {'path': '/unbound/python' if defect == 'python' else str(Path(sys.executable).resolve()),
                           'sha256': file_hash(sys.executable)}})
    monkeypatch.setattr(adapter, '_call', call)
    if defect == 'ambiguous':
        def refused(*args): raise ValueError('ambiguous loaded same-name plugin')
        monkeypatch.setattr(routine_build, 'verify_loader_observation', refused)
    with pytest.raises((ValueError, FileNotFoundError)):
        adapter.run(task(), tmp_path, tmp_path / 'out')
    assert not exports and not (tmp_path / 'out/build-reuse.json').exists()
