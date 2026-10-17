"""Real Snakemake 9.x loading of exported profiles, with no scheduler submission."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

from ravel.workflow.site_profiles import write_profile


def test_real_snakemake_927_profile_load(tmp_path):
    executable = shutil.which('snakemake')
    if executable:
        version = subprocess.run([executable, '--version'], capture_output=True, text=True, check=True).stdout.strip()
    else:
        version = None
    if version != '9.27.0':
        # This regression is mandatory: provision only its disposable test runtime.
        runtime = tmp_path / 'wms'
        subprocess.run([sys.executable, '-m', 'venv', str(runtime)], check=True, timeout=60)
        subprocess.run([str(runtime / 'bin/python'), '-m', 'pip', 'install',
                        '--disable-pip-version-check', 'snakemake==9.27.0',
                        'snakemake-executor-plugin-cluster-generic',
                        'snakemake-interface-executor-plugins>=9.3.2,<10'],
                       check=True, capture_output=True, text=True, timeout=240)
        executable = str(runtime / 'bin/snakemake')
    assert subprocess.run([executable, '--version'], capture_output=True, text=True,
                          check=True).stdout.strip() == '9.27.0'
    snake = tmp_path / 'Snakefile'
    snake.write_text('rule synthetic:\n    output: "result.txt"\n    shell: "touch {output}"\n')
    exported = write_profile(tmp_path / 'profiles', 'htcondor', jobs=1,
                             options={'workflow_dir': str(tmp_path), 'site_options': {'+queue': '"short"'}})
    profile = Path(exported['path'])
    for name in ('ravel-submit.sh', 'ravel-status.sh'):
        assert os.access(profile / name, os.X_OK)
    # Snakemake itself resolves the short filenames against the profile directory.
    done = subprocess.run([executable, '--snakefile', str(snake), '--directory', str(tmp_path),
                           '--profile', str(profile), '--dry-run'],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'synthetic' in done.stdout + done.stderr
    assert not (tmp_path / 'result.txt').exists()
    assert not list(tmp_path.rglob('*.sub'))
