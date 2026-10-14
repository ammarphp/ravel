"""Package drift is content-addressed; capture time does not change identity."""
from copy import deepcopy
import json

import pytest


def test_planted_difference_and_timestamp_independent_identity(tmp_path, capsys):
    from ravel import cli
    from ravel.workflow import env_snapshot as es
    first = es.capture(packages=[{'name': 'synthetic-pkg', 'version': '1'}])
    second = es.capture(packages=[{'name': 'synthetic_pkg', 'version': '2'}, {'name': 'extra', 'version': '1'}])
    same = deepcopy(first); same['captured_utc'] = '2000-01-01T00:00:00Z'
    assert es.snapshot_id(same) == first['snapshot_id']
    a = tmp_path / 'a.json'; a.write_text(json.dumps(first))
    b = tmp_path / 'b.json'; b.write_text(json.dumps(second))
    assert cli.main(['env', 'diff', '--before', str(a), '--after', str(b)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['changed'] == [{'name': 'synthetic-pkg', 'before': '1', 'after': '2'}]
    assert result['added'] == [{'name': 'extra', 'version': '1'}] and not result['identical']
    corrupt = deepcopy(first); corrupt['packages'][0]['version'] = '9'
    with pytest.raises(ValueError, match='snapshot'):
        es.diff(corrupt, second)


def test_duplicate_normalized_package_names_refused():
    from ravel.workflow import env_snapshot as es
    with pytest.raises(ValueError, match='duplicate'):
        es.capture(packages=[{'name': 'synthetic_pkg', 'version': '1'}, {'name': 'synthetic-pkg', 'version': '2'}])


def test_runtime_capture_reads_records_without_executing_native_tools(tmp_path, monkeypatch):
    from pathlib import Path
    import sys
    from ravel.workflow import env_snapshot as es
    marker = tmp_path / 'called'
    binary = tmp_path / 'bin'; binary.mkdir()
    tool = binary / 'root-config'
    tool.write_text('#!/bin/sh\n/usr/bin/touch "' + str(marker) + '"\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary))
    monkeypatch.setenv('APPTAINER_CONTAINER', '/images/synthetic.sif')
    monkeypatch.setenv('SECRET_TOKEN', 'never-copy-this')
    binding = tmp_path / '.ravel-site'; binding.mkdir()
    (binding / 'lcg-view.json').write_text(json.dumps({'view': '/views/synthetic', 'setup': '/views/synthetic/setup.sh'}))
    doctor = tmp_path / 'logs/site-doctor'; doctor.mkdir(parents=True)
    (doctor / 'latest.json').write_text(json.dumps({'versions': {'root-config': 'synthetic 1.2'}}))
    pin = es.capture_runtime(tmp_path, 'analysis', image_record={'path': '/images/synthetic.sif', 'digest': 'sha256:abc'})
    value = json.loads(Path(pin['path']).read_text())
    assert value['python']['executable'] == str(Path(sys.executable).resolve())
    assert 'libc' in value['platform']
    assert value['native_tools'] == {'root-config': 'synthetic 1.2'}
    assert value['facility_view']['view'] == '/views/synthetic'
    assert value['container']['image']['digest'] == 'sha256:abc'
    assert value['container']['markers']['APPTAINER_CONTAINER'] == '/images/synthetic.sif'
    assert 'SECRET_TOKEN' not in json.dumps(value) and not marker.exists()
    assert es.runtime_snapshots(tmp_path) == [pin]
    changed = deepcopy(value); changed['captured_utc'] = 'other'
    assert es.snapshot_id(changed) == value['snapshot_id']
    changed['container']['image']['digest'] = 'changed'
    assert es.snapshot_id(changed) != value['snapshot_id']


def test_runtime_attempts_unknowns_and_explicit_doctor_record(tmp_path):
    from pathlib import Path
    from ravel.workflow import env_snapshot as es
    first = es.capture_runtime(tmp_path, 'analysis')
    value = json.loads(Path(first['path']).read_text())
    assert value['native_tools'] == {} and value['doctor_record_available'] is False
    record = {'checks': [{'name': 'ROOT', 'status': 'ok', 'detail': 'ROOT synthetic'},
                         {'name': 'grid proxy', 'status': 'ok', 'detail': 'private status'}]}
    second = es.capture_runtime(tmp_path, 'analysis', doctor_record=record)
    assert first['path'] != second['path']
    value = json.loads(Path(second['path']).read_text())
    assert value['native_tools'] == {'ROOT': 'ROOT synthetic'}
    assert len(es.runtime_snapshots(tmp_path)) == 2
    with pytest.raises(ValueError, match='safe stage'):
        es.capture_runtime(tmp_path, '../escape')


def test_symlink_runtime_records_refused(tmp_path):
    from pathlib import Path
    from ravel.workflow import env_snapshot as es
    pin = es.capture_runtime(tmp_path, 'analysis')
    path = Path(pin['path'])
    other = tmp_path / 'record.json'; path.rename(other); path.symlink_to(other)
    with pytest.raises(ValueError, match='ordinary'):
        es.runtime_snapshots(tmp_path)
