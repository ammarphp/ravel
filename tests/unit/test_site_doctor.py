"""Site doctor with mocked environment probes."""
from __future__ import annotations

import json
from pathlib import Path

from ravel.workflow import site_doctor as sd


class FakeHost:
    def __init__(self, tools=(), outputs=None, paths=(), python=(3, 12)):
        self.tools = set(tools)
        self.outputs = outputs or {}
        self.paths = set(paths)
        self.python = python
        self.calls = []

    def which(self, name):
        return f'/usr/bin/{name}' if name in self.tools else None

    def run(self, argv):
        self.calls.append(argv)
        key = ' '.join(argv)
        return self.outputs.get(key, (0, ''))

    def exists(self, path):
        return str(path) in self.paths


LXPLUS_TOOLS = ('python3.12', 'voms-proxy-info', 'klist', 'krenew', 'condor_q', 'pdflatex', 'node', 'claude',
                'rucio', 'apptainer', 'tmux', 'xrdcp')


def lxplus_host(**changes):
    outputs = {'voms-proxy-info --timeleft': (0, '86000\n'), 'klist -s': (0, ''), 'condor_q -totals': (0, 'Total for query: 0 jobs'),
               'node --version': (0, 'v20.11.1\n'), 'pdflatex --version': (0, 'pdfTeX 3.141592653'),
               'claude --version': (0, '2.1.0 (Claude Code)'), 'rucio --version': (0, 'rucio 35.0.0'),
               'apptainer --version': (0, 'apptainer version 1.3.4'), 'xrdcp --version': (0, 'v5.7.1'),
               'python3.12 --version': (0, 'Python 3.12.7')}
    outputs.update(changes.pop('outputs', {}))
    return FakeHost(tools=changes.pop('tools', LXPLUS_TOOLS), outputs=outputs,
                    paths=changes.pop('paths', {'/cvmfs/sft.cern.ch', '/cvmfs/atlas.cern.ch'}), **changes)


def statuses(report):
    return {c['name']: c['status'] for c in report['checks']}


def test_ready_lxplus_profile(tmp_path):
    eos = tmp_path / 'eos'
    eos.mkdir()
    report = sd.doctor(profile='lxplus', eos_dir=eos, host=lxplus_host())
    assert report['ready'] is True, report
    status = statuses(report)
    assert status['grid proxy'] == 'ok' and status['kerberos'] == 'ok' and status['eos write'] == 'ok'
    assert status['cvmfs /cvmfs/sft.cern.ch'] == 'ok' and status['batch scheduler'] == 'ok'
    assert not list(eos.iterdir()), 'the probe file is removed'
    assert 'tmux' in report['long_session']


def test_short_proxy_and_missing_ticket_fail_on_lxplus(tmp_path):
    host = lxplus_host(outputs={'voms-proxy-info --timeleft': (0, '600\n'), 'klist -s': (1, '')})
    report = sd.doctor(profile='lxplus', host=host)
    status = statuses(report)
    assert status['grid proxy'] == 'fail' and status['kerberos'] == 'fail'
    assert report['ready'] is False
    fixes = ' '.join(c.get('fix', '') for c in report['checks'])
    assert 'voms-proxy-init' in fixes and 'kinit' in fixes


def test_missing_tools_are_reported_with_fixes(tmp_path):
    host = lxplus_host(tools=('klist', 'condor_q'), paths=set())
    report = sd.doctor(profile='lxplus', host=host)
    status = statuses(report)
    assert status['python 3.12'] == 'fail'
    assert status['cvmfs /cvmfs/sft.cern.ch'] == 'fail'
    assert status['agent CLI'] == 'warn' and status['node'] == 'warn' and status['TeX'] == 'warn'
    python = next(c for c in report['checks'] if c['name'] == 'python 3.12')
    assert 'miniforge' in python['fix'].lower()


def test_generic_profile_does_not_require_cern_services():
    host = FakeHost(tools=('python3.12', 'sbatch', 'squeue'), outputs={'python3.12 --version': (0, 'Python 3.12.1')})
    report = sd.doctor(profile='generic', host=host)
    status = statuses(report)
    assert report['ready'] is True
    assert status['kerberos'] == 'skip' and status['batch scheduler'] == 'ok'


def test_eos_write_failure_is_reported(tmp_path):
    report = sd.doctor(profile='lxplus', eos_dir=tmp_path / 'missing', host=lxplus_host())
    assert statuses(report)['eos write'] == 'fail'


def test_no_credential_contents_are_printed():
    host = lxplus_host(outputs={'klist -s': (0, ''), 'voms-proxy-info --timeleft': (0, '90000')})
    text = json.dumps(sd.doctor(profile='lxplus', host=host))
    assert not any(['klist'] == call for call in host.calls), 'only klist -s is run'
    assert 'principal' not in text.lower()


def test_cli_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sd, 'Host', lambda: FakeHost(tools=('python3.12',), outputs={'python3.12 --version': (0, 'Python 3.12.0')}))
    code = sd.main(['doctor', '--profile', 'generic', '--json'])
    out = json.loads(capsys.readouterr().out)
    assert out['profile'] == 'generic' and code == 0


def test_install_plan_for_no_root_site():
    plan = sd.install_plan('/afs/cern.ch/work/a/user/ravel-env', '/afs/cern.ch/work/a/user/ravel')
    text = '\n'.join(plan['commands'])
    assert 'Miniforge3' in text and 'python=3.12' in text and 'site_installation.py' in text
    assert plan['root_required'] is False
