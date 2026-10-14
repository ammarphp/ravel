"""Synthetic public fixtures and supplied numerical references preserve their boundaries."""
import hashlib
import importlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_retired_case_ids_are_absent():
    retired = {'B05', 'B06', 'B07', 'B15', 'B16', 'B16b', 'P06', 'G6'}
    prefixes = ('R05-', 'R06-', 'R07-', 'R15-', 'R16-', 'R16b-')
    for relative in ('tests/replay/cases/ported.json', 'tests/replay/cases/probes.json',
                     'tests/unit/fixtures/intake-corpus/requests.json'):
        document = json.loads((REPO / relative).read_text())
        assert not [r['id'] for r in document['cases']
                    if r['id'] in retired or r['id'].startswith(prefixes)]


def test_addon_record_has_no_unused_measurement_blocks_and_matches_pin():
    roots = list((REPO / 'addons/gpl').glob('*/upstream-api.json'))
    assert len(roots) == 1
    record = roots[0]
    assert not {'measurement_table', 'rivet_cut_source'} & json.loads(record.read_text()).keys()
    pins = json.loads(record.with_name('addon.json').read_text())['files']
    assert pins[record.name] == hashlib.sha256(record.read_bytes()).hexdigest()


def test_absent_registered_module_refuses_registry_and_admission():
    """A selection without a supplied analysis package is refused with a typed reason; nothing is built in."""
    from ravel.physics import native_capabilities as cap
    from ravel.physics import sa_routines as routines
    from ravel.physics.analysis_packages import PackageInputError
    name = 'FictionalRoutine700'
    with pytest.raises(routines.RoutineUnavailable) as error:
        routines.REGISTRY[name]
    assert error.value.reason == 'missing_analysis_package'
    with pytest.raises(PackageInputError) as error:
        cap.resolve_capability(name, 'fictional-model', 'explicit-cards', 'simpleanalysis-delphes', 'yields')
    assert error.value.reason == 'missing_analysis_package'
    for module in ('native_pipeline', 'native_simpleanalysis', 'native_capabilities'):
        assert importlib.import_module('ravel.physics.' + module)


def test_fit_without_selected_reference_refuses(monkeypatch, capsys):
    from ravel.physics import pyhf_exclude as exclude
    from ravel import paths
    monkeypatch.setattr(paths, 'package_data_path', lambda *parts: pytest.fail('implicit source input'))
    with pytest.raises(exclude.MissingReferenceInput) as error:
        exclude._retained_freefit_selftest()
    assert error.value.reason == 'missing_reference_input'
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize("include_declarations", [False, True])
def test_blocked_private_assets_leave_all_registry_consumers_importable(tmp_path, include_declarations):
    """A fresh interpreter observes absence, without editing private scientific records."""
    import subprocess
    import sys
    # A source tree blocks the private modules its distribution record lists; a released tree carries
    # no such list because those modules are absent from it.
    patterns = json.loads((REPO / 'distribution.json').read_text())['distribution'].get('internal', [])
    modules = [p.removeprefix('src/').removesuffix('.py').replace('/', '.')
               for p in patterns if p.startswith('src/ravel/physics/') and p.endswith('.py')]
    if not include_declarations:
        modules = [name for name in modules if '.sa_routines.' in name]
    code = '''
import importlib, importlib.abc, importlib.util, json, sys
blocked = set(json.loads(sys.argv[1]))
class Absent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise ModuleNotFoundError(fullname, name=fullname)
sys.meta_path.insert(0, Absent())
from ravel.physics import sa_routines as routines
from ravel.physics import native_capabilities as cap
for module in ('native_pipeline', 'native_simpleanalysis', 'native_capabilities'):
    importlib.import_module('ravel.physics.' + module)
from ravel import paths
paths.package_data_path = lambda *parts: __import__('pathlib').Path(sys.argv[2]) / 'absent'
from ravel.physics import pyhf_exclude as exclude
try:
    exclude._retained_freefit_selftest()
except exclude.MissingReferenceInput as error:
    assert error.reason == 'missing_reference_input'
else:
    raise AssertionError('implicit reference selected')
for routine, module in dict.items(routines.REGISTRY):
    if module not in blocked and importlib.util.find_spec(module) is not None:
        continue
    row = cap.CAPABILITIES[routine]
    try:
        routines.REGISTRY[routine]
    except routines.RoutineUnavailable as error:
        assert error.reason == 'routine_module_absent'
    else:
        raise AssertionError('absent registry module admitted')
    try:
        cap.resolve_capability(routine, row['models'][0], row['preparations'][0],
                               row['detector'], row['statistics'][0])
    except routines.RoutineUnavailable as error:
        assert error.reason == 'routine_module_absent'
    else:
        raise AssertionError('absent registered adapter admitted')
try:
    cap.resolve_capability('FictionalAbsent700', 'fictional-model', 'explicit-cards',
                           'simpleanalysis-delphes', 'yields')
except ValueError as error:
    assert getattr(error, 'reason', None) == 'missing_analysis_package', error
else:
    raise AssertionError('absent adapter admitted')
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, json.dumps(modules), str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''


def test_fit_missing_selected_input_has_typed_reason(tmp_path, monkeypatch, capsys):
    from ravel.physics import pyhf_exclude as exclude
    from ravel import paths
    monkeypatch.setattr(paths, 'package_data_path', lambda *parts: tmp_path / 'absent')
    with pytest.raises(exclude.MissingReferenceInput) as error:
        exclude._retained_freefit_selftest()
    assert error.value.reason == 'missing_reference_input'
    assert capsys.readouterr().out == ''
