"""Physical balanced-transverse events retain strict RISR boundaries through CSV.

This integration test builds only a new temporary resolver. It never replaces an
installed/campaign binary, and skips when the optional local RestFrames toolchain
is absent. No generated events, showering, detector work or fits are performed.
"""
from pathlib import Path
import csv
import os
import subprocess
import sys

import pytest

from ravel.paths import native_build_root


@pytest.fixture(scope='module')
def resolver(tmp_path_factory):
    repo = Path(__file__).resolve().parents[2]
    build = native_build_root()
    recast = build/'tools/miniforge3/envs/recast'
    conda = build/'tools/miniforge3/bin/conda'
    restframes = build/'tools/restframes-native'
    if sys.platform != 'darwin' or not all(p.is_file() for p in (
            conda, recast/'bin/root-config', restframes/'lib/libRestFrames.dylib',
            repo/'native/src/rjr_resolve.cc')):
        pytest.skip('optional native ROOT/RestFrames build toolchain unavailable')
    target = tmp_path_factory.mktemp('rjr-precision')/'rjr_resolve'
    cmd = [str(conda),'run','--no-capture-output','--prefix',str(recast),'python','-B',
           str(repo/'scripts/run.py'),'ravel.physics.native_build','rjr','--prefix',str(recast),
           '--restframes',str(restframes),'--out',str(target)]
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}
    result = subprocess.run(cmd,cwd=repo,env=environment,text=True,capture_output=True,timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.is_file()
    return target


def test_balanced_physical_events_preserve_risr_boundary(resolver, tmp_path):
    # In each event transverse momenta sum to zero, so CM is the lab frame.
    # One jet forces its ISR assignment and RISR = |MET| / 200 GeV.
    # Physical electron masses avoid relying on a degenerate massless limit.
    path = tmp_path/'objects.txt'
    path.write_text(
        '1 199.99998 3.141592653589793 1 200 0 10 2 '
        '5.00002 3.141592653589793 0.00051099891 5 0 0.00051099891\n'
        '2 199.98 3.141592653589793 1 200 0 10 2 '
        '5.02 3.141592653589793 0.00051099891 5 0 0.00051099891\n'
        '3 200.00002 3.141592653589793 1 200 0 10 2 '
        '5 3.141592653589793 0.00051099891 5.00002 0 0.00051099891\n')
    output = tmp_path/'risr.csv'
    result = subprocess.run([str(resolver),'--objects',str(path),str(output)],
                            text=True,capture_output=True,timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    with output.open() as stream: rows = list(csv.DictReader(stream))
    assert len(rows) == 3 and [int(row['Event']) for row in rows] == [1,2,3]
    ratios = [float(row['RISR']) for row in rows]
    assert all(int(row['solved']) == 1 and int(row['NjISR']) == 1 and int(row['NjV']) == 0 for row in rows)
    assert ratios == pytest.approx([.9999999,.9999,1.0000001],abs=1e-12,rel=0.)
    assert ratios[0] < 1. and ratios[1] < 1. and ratios[2] > 1.
