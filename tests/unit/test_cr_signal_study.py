"""Artificial response engine only; no pyhf import or official model calls."""
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from ravel.validation import cr_signal_study as s
from ravel.workflow import science
from test_cr_switch_qualification import ToyEngine, workspace


def put(path, value):
    path.write_bytes(s.raw_json(value))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def forbid_pyhf_import(monkeypatch):
    """Detect imports during the operation even if another file already imported it."""
    import builtins
    import importlib
    original_import, original_dynamic = builtins.__import__, importlib.import_module
    def checked(name, *args, **kwargs):
        if name == 'pyhf' or name.startswith('pyhf.'):
            pytest.fail('inert operation imported the native likelihood engine')
        return original_import(name, *args, **kwargs)
    def dynamic(name, *args, **kwargs):
        if name == 'pyhf' or name.startswith('pyhf.'):
            pytest.fail('inert operation dynamically imported the native likelihood engine')
        return original_dynamic(name, *args, **kwargs)
    already = 'pyhf' in sys.modules
    monkeypatch.setattr(builtins, '__import__', checked)
    monkeypatch.setattr(importlib, 'import_module', dynamic)
    yield
    # Alone in its process the engine was never loaded, and the operation must not load it.
    assert already or 'pyhf' not in sys.modules


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    w = workspace(); m = ToyEngine().describe(None)
    reference = {source: m[target] for source, target in {
        'parameter_names': 'names', 'bounds': 'bounds', 'inits': 'inits', 'fixed': 'fixed',
        'channel_order': 'channels', 'channel_slices': 'channel_slices', 'sample_order': 'samples',
        'observed_and_auxiliary_data': 'data', 'constraints': 'constraint_specs',
        'modifier_settings': 'modifier_settings', 'model_compact_sha256': 'model_compact_sha256'}.items()}
    reference.update(npars=5, nauxdata=3, pyhf_version='0.7.6',
        data_compact_sha256=hashlib.sha256(json.dumps(m['data'], separators=(',', ':')).encode()).hexdigest())
    runtime = tmp_path/'runtime.py'; runtime.write_text('# supplied runtime identity only\n')
    doc = {'schema_version': 1, 'workspace': put(tmp_path/'workspace.json', w),
        'compiled_reference': put(tmp_path/'reference.json', reference),
        'runtime_inventory': put(tmp_path/'runtime.json', {'schema_version': 1, 'files': [
            {'path': str(runtime), 'sha256': hashlib.sha256(runtime.read_bytes()).hexdigest()}]}),
        'measurement': 'M', 'signal': 'signal', 'all_controls': ['CR', 'CR_absent'],
        'expected_membership': s.witness.intervention(w, 'signal', ['CR', 'CR_absent']),
        'protocol': deepcopy(s.PROTOCOL), 'grounding': [put(tmp_path/'source.json', {'artificial': True})]}
    path = tmp_path/'input.json'; put(path, doc)
    monkeypatch.setattr(s.witness, 'PyhfEngine', ToyEngine)
    monkeypatch.setattr(importlib.metadata, 'version', lambda name: '0.7.6')
    # This fixture explicitly substitutes arithmetic and module identity, not native evidence.
    monkeypatch.setattr(s, 'observed_imports', lambda inv: [{'module': 'supplied arithmetic fixture'}])
    return {'input': str(path)}, doc, runtime


def test_all_three_arms_five_vectors_component_journal_and_no_native(fixture, tmp_path, forbid_pyhf_import):
    result = s.run(fixture[0], tmp_path, tmp_path/'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    report = json.loads((tmp_path/'out/checkpoint.json').read_text())
    assert len(report['calls']) == 45 and len(report['compilations']) == 3 and len(report['rows']) == 5
    assert all(row['status'] == 'completed' for row in report['calls'])
    assert result['checkpoint_sha256'] == hashlib.sha256((tmp_path/'out/checkpoint.json').read_bytes()).hexdigest()
    assert result['optimizer_calls'] == result['generated_events'] == result['root_searches'] == 0


def test_started_and_successful_components_survive_second_half_failure(fixture, tmp_path, monkeypatch):
    monkeypatch.setattr(s.witness, 'PyhfEngine', lambda: ToyEngine(fail_at=2))
    result = s.run(fixture[0], tmp_path, tmp_path/'out')
    report = json.loads((tmp_path/'out/checkpoint.json').read_text())
    assert result['status'] == 'failed'
    assert [r['status'] for r in report['calls']] == ['completed', 'failed']
    assert report['calls'][0]['result'] == report['rows'][0]['values']['original']['by_sample']
    assert result['runtime_after_passed']


@pytest.mark.parametrize('corruption', ['SR', 'tinyCR', 'background', 'density', 'fixed', 'aux'])
def test_scientific_adversaries_are_failed_deliveries(fixture, tmp_path, monkeypatch, corruption):
    monkeypatch.setattr(s.witness, 'PyhfEngine', lambda: ToyEngine(corruption))
    result = s.run(fixture[0], tmp_path, tmp_path/'out')
    assert result['status'] == 'failed' and result['checkpoint']


def test_actual_ending_runtime_drift_retains_complete_return(fixture, tmp_path, monkeypatch):
    class Drift(ToyEngine):
        def evaluate(self, *args):
            value = super().evaluate(*args)
            if self.calls == 45:
                fixture[2].write_text('changed')
            return value
    monkeypatch.setattr(s.witness, 'PyhfEngine', Drift)
    result = s.run(fixture[0], tmp_path, tmp_path/'out')
    assert result['status'] == 'failed' and result['runtime_after_passed'] is False
    assert json.loads((tmp_path/'out/checkpoint.json').read_text())['passed'] is True


@pytest.mark.parametrize('kind', ['membership', 'tolerance', 'source_hash'])
def test_intake_refuses_before_engine(fixture, tmp_path, monkeypatch, kind):
    task, doc, _ = fixture
    if kind == 'membership': doc['expected_membership'][1]['signal_sample_present'] = True
    elif kind == 'tolerance': doc['protocol']['tolerances']['twice_nll_atol'] = 1.
    else: doc['workspace']['sha256'] = '0'*64
    put(Path(task['input']), doc)
    monkeypatch.setattr(s.witness, 'PyhfEngine', lambda: pytest.fail('engine reached'))
    with pytest.raises(ValueError): s.inputs(task, tmp_path)
    assert s.run(task, tmp_path, tmp_path/'out')['status'] == 'failed'


def test_runtime_bytes_enumerated_and_checked_without_import(fixture, tmp_path):
    paths = s.inputs(fixture[0], tmp_path)
    assert fixture[2] in paths and len(paths) == 6
    fixture[2].write_text('drift')
    with pytest.raises(ValueError, match='runtime bytes'): s.inputs(fixture[0], tmp_path)


def test_output_reuse_symlink_and_reader_bound(fixture, tmp_path, monkeypatch):
    out = tmp_path/'out'; out.mkdir(); (out/'original').write_text('retained')
    with pytest.raises(FileExistsError): s.run(fixture[0], tmp_path, out)
    alias = tmp_path/'alias'; alias.symlink_to(Path(fixture[0]['input']))
    with pytest.raises(ValueError): s.read_bytes(alias)
    monkeypatch.setattr(s, 'MAX_FILE_BYTES', 1)
    with pytest.raises(ValueError): s.read_bytes(fixture[0]['input'])
    assert (out/'original').read_text() == 'retained'


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'])
def test_strict_json(text):
    with pytest.raises(ValueError): s.parse(text)


def test_descriptor_growth_reads_only_cap_plus_one(tmp_path, monkeypatch):
    path = tmp_path/'small'; path.write_bytes(b'1')
    monkeypatch.setattr(s, 'MAX_FILE_BYTES', 128)
    real = s.os.fdopen; sizes = []
    class Wrapped:
        def __init__(self, f): self.f = f
        def __enter__(self): return self
        def __exit__(self, *args): self.f.close()
        def fileno(self): return self.f.fileno()
        def read(self, n):
            sizes.append(n)
            with path.open('ab') as f: f.write(b'2'*256)
            return self.f.read(n)
    monkeypatch.setattr(s.os, 'fdopen', lambda *a, **k: Wrapped(real(*a, **k)))
    with pytest.raises(ValueError, match='changed or exceeded'): s.read_bytes(path)
    assert sizes == [129]


def test_import_origin_must_be_a_consumed_runtime_file(tmp_path, monkeypatch):
    path = tmp_path/'scientific.py'; path.write_text('# supplied stub')
    config = tmp_path/'config.py'; config.write_text('# supplied submodule stub')
    # Exercise real observer only with inert namespaces, no optional import.
    monkeypatch.setitem(sys.modules, 'pyhf', SimpleNamespace(__file__=str(path)))
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace(__file__=str(path)))
    monkeypatch.setitem(sys.modules, 'numpy.__config__', SimpleNamespace(__file__=str(config)))
    prefixes = ('pyhf', 'numpy', 'scipy', 'jsonschema', 'jsonpatch', 'jsonpointer', 'iminuit')
    # The observer checks every loaded submodule. Declare the complete current
    # source population, including an explicit inert submodule in this fixture.
    expected = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
                if name.split('.')[0] in prefixes and getattr(module, '__file__', None)}
    inv = {'files': [{'path': value, 'sha256': hashlib.sha256(Path(value).read_bytes()).hexdigest()}
                     for value in sorted(set(expected.values()))]}
    observed = s.observed_imports(inv)
    assert {row['module']: row['path'] for row in observed} == expected
    incomplete = {'files': [row for row in inv['files'] if row['path'] != str(config.resolve())]}
    with pytest.raises(ValueError, match='outside runtime.*numpy.__config__'):
        s.observed_imports(incomplete)
    with pytest.raises(ValueError, match='outside runtime'): s.observed_imports({'files': []})


def test_common_worker_uses_dedicated_directory_and_retains_result(fixture, tmp_path, monkeypatch):
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    rd = tmp_path/'worker'; (rd/'inputs').mkdir(parents=True)
    spec = specification(fixture[0])
    proposal = {'attempt': 1, 'output_directory': 'outputs/attempt-1', 'base_dir': str(tmp_path),
                'stage_binding': {'input_snapshot': {}}}
    monkeypatch.setattr(science_worker, 'verify_worker', lambda p: proposal)
    monkeypatch.setattr(science_worker, 'execution_spec', lambda p: spec)
    monkeypatch.setattr(science_figures, 'render', lambda *args: {'figures': [], 'tables': []})
    assert science_worker.main([str(rd)]) == 0
    out = rd/'outputs/attempt-1'
    assert (out/'cr-signal-qualification/checkpoint.json').is_file()
    assert json.loads((out/'result.json').read_text())['scope'] == s.SCOPE
    assert not (rd/'inputs/science-approval.json').exists()  # boundary is mocked, not authorized


def specification(task):
    return {'schema_version': 2, 'mode': 'cr-signal-qualification', 'source': 'Artificial law/custody fixture',
        'assumptions': ['No physical data or native compiler used'], 'max_seconds': 300,
        'approval_mode': 'scripted_yes', 'task': task, 'max_attempts': 1,
        'review_policy': {'schema_version': 1, 'policy': {'schema_version': 1,
            'actors': {'proposer': 'p', 'executor': 'e', 'physics_critic': 'c', 'skeptical_verifier': 'v', 'physics_decider': 'd'},
            'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
            'required_checks': [{'id': 'integrity', 'kind': 'integrity'}, {'id': 'scientific', 'kind': 'scientific'}],
            'claim_scopes': {s.SCOPE: {'checks': ['integrity', 'scientific'], 'actions': ['delivery']}}},
            'correction_contract': {'task_fields': [], 'input_slots': []}}}


def test_genuine_unapproved_ordinary_plan_is_inert(fixture, tmp_path, monkeypatch, forbid_pyhf_import):
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'synthetic-platform')
    monkeypatch.setattr(s.witness, 'PyhfEngine', lambda: pytest.fail('planning compiled a model'))
    spec = specification(fixture[0]); source = tmp_path/'study.json'; put(source, spec)
    rd = tmp_path/'planned'; science.plan(rd, source)
    assert science.adapter(spec) is s and science._new_capability(spec)
    assert (rd/'inputs/checkin1.json').is_file()
    assert not (rd/'inputs/science-approval.json').exists()
