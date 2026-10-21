"""``ravel site init``: one observation of the host saved as a reusable site profile, read back by the site doctor
and by a controller run.

Every probe is injected; nothing probes the network, runs a scheduler client or starts the doctor's tool checks.
"""
import json
from pathlib import Path

import pytest

from ravel.setup import environment_profile as ep
from ravel.workflow import site_doctor as sd


def probes(*, schedulers=(), inside=None):
    def batch(**kwargs):
        available = list(schedulers)
        system = kwargs.get('scheduler') or inside or (available[0] if len(available) == 1 else
                                                       'multiple' if available else 'none')
        return {'system': system, 'available': available, 'inside_job': inside,
                'source': 'site-profile' if kwargs.get('scheduler') else 'detected'}
    return {'host': lambda: {'system': 'Fictional', 'release': '1', 'machine': 'x', 'python': '3.12'},
            'platform': lambda: 'linux-x86_64',
            'resources': lambda roots: {'cpus': 8, 'cpus_usable': 8, 'memory_bytes': 1 << 34, 'disk': []},
            'gpus': lambda: {'count': 0, 'source': 'none-detected', 'names': []},
            'network': lambda: {'egress': 'available', 'source': 'probe', 'checks': []},
            'batch': batch, 'sandbox': lambda: {'backend': 'linux', 'backends': {'bwrap': 'available'}},
            'containers': lambda: {'podman': None, 'apptainer': '/usr/bin/apptainer', 'singularity': None,
                                   'docker': None},
            'tools': lambda **_: {'observed': True, 'source': 'doctor-census', 'prefix': '/fictional/prefix',
                                  'reason': None, 'rows': {'census-snakemake-9-27-0': {
                                      'readiness': 'ready', 'status': 'qualified', 'version': '9.27.0',
                                      'licence': 'not_applicable', 'platform_qualification': ''}}}}


def test_init_saves_a_profile_that_round_trips(tmp_path):
    out = tmp_path / 'site' / 'profile.json'
    found = sd.site_init(name='lab', seed='generic', network='offline', mirror=tmp_path / 'mirror',
                         output=out, probes=probes(schedulers=['slurm']))
    document, pin = ep.load_site_profile(out)
    assert document == found['profile'] and pin == found['pin']
    assert document['settings']['scheduler'] == 'slurm' and document['network'] == {'policy': 'offline'}
    assert document['sources']['mirror'] == str(tmp_path / 'mirror')
    observed = document['observed']
    assert observed['network'] == {'egress': 'none', 'source': 'site-profile', 'checks': []}
    assert observed['batch']['system'] == 'slurm' and observed['batch']['source'] == 'site-profile'
    assert observed['tools']['rows']['census-snakemake-9-27-0']['version'] == '9.27.0'
    # A second init of the same host and settings replaces the file with the same settings.
    again = sd.site_init(name='lab', seed='generic', network='offline', mirror=tmp_path / 'mirror',
                         output=out, probes=probes(schedulers=['slurm']))
    assert again['profile']['settings'] == document['settings'] and ep.load_site_profile(out)[0] == again['profile']


@pytest.mark.parametrize('schedulers, inside, expected', [
    ([], None, None), (['htcondor'], None, 'htcondor'), (['htcondor', 'slurm'], 'slurm', 'slurm')])
def test_the_scheduler_is_detected(tmp_path, schedulers, inside, expected):
    found = sd.site_init(output=tmp_path / 'p.json', probes=probes(schedulers=schedulers, inside=inside))
    assert found['profile']['settings']['scheduler'] == expected


def test_an_ambiguous_scheduler_must_be_named(tmp_path):
    with pytest.raises(ValueError, match='name the site scheduler'):
        sd.site_init(output=tmp_path / 'p.json', probes=probes(schedulers=['htcondor', 'slurm']))
    found = sd.site_init(output=tmp_path / 'p.json', scheduler='htcondor',
                         probes=probes(schedulers=['htcondor', 'slurm']))
    assert found['profile']['settings']['scheduler'] == 'htcondor'


def test_a_seed_supplies_requirements_that_flags_replace(tmp_path):
    found = sd.site_init(seed='analysis-facility', scheduler='none', output=tmp_path / 'p.json',
                         requires={'requires_proxy': False}, cvmfs=['/cvmfs/fictional.repo'], probes=probes())
    settings = found['profile']['settings']
    assert settings == {'scheduler': None, 'requires_proxy': False, 'requires_kerberos': True,
                        'requires_afs': False, 'cvmfs': ['/cvmfs/fictional.repo']}
    with pytest.raises(ValueError, match='requirement'):
        sd.site_init(output=tmp_path / 'p.json', requires={'requires_wings': True}, probes=probes())


def test_the_cli_init_and_show_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ep, 'PROBES', {**ep.PROBES, **probes(schedulers=['htcondor'])})
    monkeypatch.setattr(ep, 'site_profile_path', lambda: tmp_path / 'home' / 'site' / 'profile.json')
    assert sd.main(['init', '--name', 'lab', '--network', 'offline', '--json']) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved['pin']['path'] == str(tmp_path / 'home' / 'site' / 'profile.json')
    assert sd.main(['show', '--json']) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown == saved
    assert sd.main(['show']) == 0 and 'scheduler: htcondor; network policy: offline' in capsys.readouterr().out
