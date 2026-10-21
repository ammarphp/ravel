"""Real operator CLI and process restarts with an inert backend at the P05 boundary.

These controls do not claim P01 driver or P04/P05 composition qualification.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p06_support import autonomous, frozen_store, operator_home
from test_p06_request import ci1
from ravel.controller.authority import issuer, operator

HELPER = '''
import json, sys
from pathlib import Path
from test_p06_support import FakeRunStore
from ravel.controller.authority import common, issuer, operator, cli, authorize_effect
root, issuer_root, operator_root, counter, action, *args = sys.argv[1:]
issuer.home = lambda: Path(issuer_root)
operator.controller_home = lambda: Path(operator_root)
store = FakeRunStore('run-0001', root=Path(root))
common.open_store = lambda identifier: store
if action == 'operator':
    raise SystemExit(cli.main(args))
# P05 popen signature, inert scheduler boundary; no scientific command or submission.
def popen(spec, **popen_kwargs):
    with open(counter, 'a') as stream:
        stream.write('effect\\n')
    return {'inert': True}
try:
    authorize_effect(store, {'id': 'nested', 'rung': 'smoke',
                            'pins': {'plan_sha256': 'a'*64}, 'stage': 'derive', 'budget': {'events': 1}})
    popen({'argv': ['inert'], 'env': {}, 'reads': [], 'writes': [], 'limits': {}, 'backend': 'bwrap'})
except common.AuthorityRefused as exc:
    print(str(exc))
    raise SystemExit(2)
'''


def test_F09_A10_B05_C40_cli_stop_resume_revoke_survive_process_restart(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    ci1(store, rung='smoke')
    helper = tmp_path / 'controller_process.py'
    helper.write_text(HELPER)
    counter = tmp_path / 'effects.txt'
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(Path(__file__).parent),
                                                     os.environ.get('PYTHONPATH', '')])}
    def invoke(*args):
        return subprocess.run([sys.executable, str(helper), str(store.root), str(issuer.home()),
                               str(operator.controller_home()), str(counter), *args],
                              env=env, capture_output=True, text=True, timeout=30)
    assert invoke('effect').returncode == 0
    assert counter.read_text().splitlines() == ['effect']
    for command in ('stop', 'pause'):
        result = invoke('operator', command, '--run', store.run_id, '--reason', 'operator control')
        assert result.returncode == 0, result.stderr
        assert invoke('effect').returncode == 2
        assert counter.read_text().splitlines() == ['effect']
        status = invoke('operator', 'status', '--run', store.run_id)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)['control']['state'] == command + '_requested'
        assert invoke('operator', 'resume', '--run', store.run_id, '--reason', 'continue').returncode == 0
    assert invoke('effect').returncode == 0
    assert counter.read_text().splitlines() == ['effect', 'effect']
    assert invoke('operator', 'revoke', '--run', store.run_id, '--reason', 'withdraw delegation').returncode == 0
    assert invoke('effect').returncode == 2
    assert invoke('operator', 'resume', '--run', store.run_id, '--reason', 'resume without delegation').returncode == 0
    assert invoke('effect').returncode == 2
    assert counter.read_text().splitlines() == ['effect', 'effect']
