"""Recorded environments, isolated rebuilds and offline export refusals."""
import json
from pathlib import Path
import subprocess

import pytest

from ravel.workflow import env_snapshot as es


def fixture_lock(tmp_path):
    path = tmp_path / 'wms.lock'
    path.write_text('snakemake==9.27.0 \\\n    --hash=sha256:' + 'a' * 64 + '\npackaging==25.0 \\\n    --hash=sha256:' + 'b' * 64 + '\n')
    return path


def runtime(tmp_path, stage='analysis', packages=None):
    value = es.capture(packages=packages or [{'name': 'numpy', 'version': '1.0'}])
    value.update(stage=stage, attempt='a1')
    value['snapshot_id'] = es.snapshot_id(value)
    path = tmp_path / (stage + '.json')
    path.write_text(json.dumps(value))
    import hashlib
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size': path.stat().st_size, 'snapshot_id': value['snapshot_id']}


def write(tmp_path, pins, lock=None):
    from ravel.workflow import environment_export as ee
    return ee.write(tmp_path / 'package', pins, lock or fixture_lock(tmp_path), allow_fixture_lock=True)


def test_recorded_packages_and_ravel_exclusion(tmp_path):
    pin = runtime(tmp_path, packages=[{'name': 'numpy', 'version': '1.0'}, {'name': 'Ravel', 'version': '9'},
                                      {'name': 'packaging', 'version': '26.3'}])
    pins = write(tmp_path, [pin])
    requirements = (tmp_path / 'package/environment/analysis-requirements.txt').read_text()
    assert requirements == 'numpy==1.0\npackaging==26.3\n'
    assert (tmp_path / 'package/environment/wms-requirements.lock').read_bytes() == fixture_lock(tmp_path).read_bytes()
    assert len(pins) == 4


def test_actual_ravel_distribution_name_is_excluded(tmp_path):
    pin = runtime(tmp_path, packages=[{'name': 'ravel_hep', 'version': '1.0'},
                                      {'name': 'numpy', 'version': '1.0'}])
    write(tmp_path, [pin])
    assert (tmp_path / 'package/environment/analysis-requirements.txt').read_text() == 'numpy==1.0\n'


def test_conflicting_stage_versions_refused_by_name(tmp_path):
    a = runtime(tmp_path, 'first')
    b = runtime(tmp_path, 'second', [{'name': 'NumPy', 'version': '2.0'}])
    with pytest.raises(ValueError, match='numpy'):
        write(tmp_path, [a, b])
    assert not (tmp_path / 'package').exists()


def test_wms_cannot_be_merged_into_analysis(tmp_path):
    pin = runtime(tmp_path, packages=[{'name': 'snakemake', 'version': '9.27.0'},
                                      {'name': 'packaging', 'version': '26.3'}])
    with pytest.raises(ValueError, match='snakemake.*packaging|packaging.*snakemake'):
        write(tmp_path, [pin])


def test_missing_unhashed_and_unapproved_fixture_lock_refused(tmp_path):
    from ravel.workflow import environment_export as ee
    pin = runtime(tmp_path)
    with pytest.raises(ValueError, match='WMS lock'):
        ee.write(tmp_path / 'package', [pin], tmp_path / 'missing.lock')
    lock = fixture_lock(tmp_path)
    with pytest.raises(ValueError, match='fixture'):
        ee.write(tmp_path / 'package', [pin], lock)
    lock.write_text('snakemake==9.27.0\npackaging==25.0\n')
    with pytest.raises(ValueError, match='hash'):
        write(tmp_path, [pin], lock)


def test_setup_syntax_and_two_environments_with_fake_installers(tmp_path, monkeypatch):
    write(tmp_path, [runtime(tmp_path)])
    package = tmp_path / 'package'
    setup = package / 'environment/setup.sh'
    subprocess.run(['/bin/sh', '-n', str(setup)], check=True)
    # The separately owned source/distribution pin is supplied by the next package.
    (package / 'environment/ravel-requirements.txt').write_text('ravel-hep==1.0\n')
    fake = tmp_path / 'bin'; fake.mkdir()
    log = tmp_path / 'calls'
    python = fake / 'python3'
    python.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
test "$1 $2" = '-m venv' || exit 2
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'SH'
#!/bin/sh
printf '%s %s\\n' "$0" "$*" >> "$CALLS"
exit 0
SH
chmod +x "$3/bin/python"
touch "$3/bin/ravel" "$3/bin/snakemake"
chmod +x "$3/bin/ravel" "$3/bin/snakemake"
''')
    python.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake) + ':/usr/bin:/bin')
    monkeypatch.setenv('CALLS', str(log))
    result = subprocess.run(['/bin/sh', str(setup)], cwd=tmp_path, check=True, capture_output=True, text=True)
    calls = log.read_text().splitlines()
    assert calls[0] == '-m venv .venv-analysis'
    assert 'analysis-requirements.txt' in calls[1]
    assert 'ravel-requirements.txt' in calls[2]
    assert calls[3] == '-m venv .venv-wms'
    assert '--require-hashes' in calls[4] and 'wms-requirements.lock' in calls[4]
    assert (package / '.bin/ravel').readlink() == Path('../.venv-analysis/bin/ravel')
    assert (package / '.bin/snakemake').readlink() == Path('../.venv-wms/bin/snakemake')
    assert 'export PATH=' in result.stdout
    assert str(tmp_path) not in setup.read_text()
    result = subprocess.run(['/bin/sh', '-c', 'command -v ravel; command -v snakemake'], check=True,
                            capture_output=True, text=True, env={'PATH': str(package / '.bin') + ':/usr/bin:/bin'})
    assert result.stdout.splitlines() == [str(package / '.bin/ravel'), str(package / '.bin/snakemake')]


def test_changed_runtime_content_and_source_bytes_are_refused(tmp_path):
    pin = runtime(tmp_path)
    path = Path(pin['path'])
    value = json.loads(path.read_text())
    value['packages'][0]['version'] = '2.0'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='changed'):
        write(tmp_path, [pin])
    import hashlib
    pin.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size)
    with pytest.raises(ValueError, match='snapshot content changed'):
        write(tmp_path, [pin])


def test_no_runtime_fallback_and_no_overwrite(tmp_path):
    with pytest.raises(ValueError, match='recorded runtime'):
        write(tmp_path, [])
    pin = runtime(tmp_path)
    write(tmp_path, [pin])
    path = tmp_path / 'package/environment/analysis-requirements.txt'
    path.write_text('owner bytes')
    with pytest.raises(ValueError, match='never overwrites'):
        write(tmp_path, [pin])
    assert path.read_text() == 'owner bytes'


def test_lock_conflicting_packaging_and_pip_directives_refused(tmp_path):
    pin = runtime(tmp_path)
    lock = fixture_lock(tmp_path)
    lock.write_text(lock.read_text().replace('packaging==25.0', 'packaging==26.3'))
    with pytest.raises(ValueError, match='packaging<26'):
        write(tmp_path, [pin], lock)
    lock.write_text('--index-url https://invalid.example\n' + fixture_lock(tmp_path).read_text())
    with pytest.raises(ValueError, match='hash'):
        write(tmp_path, [pin], lock)


def test_setup_missing_ravel_pin_never_starts_installer(tmp_path, monkeypatch):
    write(tmp_path, [runtime(tmp_path)])
    package = tmp_path / 'package'
    fake = tmp_path / 'bin'; fake.mkdir()
    marker = tmp_path / 'called'
    python = fake / 'python3'
    python.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
    python.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake) + ':/usr/bin:/bin')
    result = subprocess.run(['/bin/sh', str(package / 'environment/setup.sh')], capture_output=True, text=True)
    assert result.returncode == 1 and 'RAVEL' in result.stderr
    assert not marker.exists()


def test_repository_wms_lock_dependency(tmp_path):
    from ravel.workflow import environment_export as ee
    if not ee.WMS_LOCK.is_file():
        pytest.xfail(reason='awaits SMK-09')
    pins = ee.write(tmp_path / 'package', [runtime(tmp_path)])
    assert any(p['path'] == 'environment/wms-requirements.lock' for p in pins)
