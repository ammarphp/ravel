"""`ravel literature`, `literature models`, `literature-query`, `literature-score` and `output-contract`
reach their owning modules; legacy literature subcommands keep `workflow.literature`. Fictional only;
no model call, index, network or acquisition."""
import json
import socket

import pytest

from ravel import cli
from ravel.workflow import literature, literature_cli, literature_evidence_scoring, literature_models
from ravel.workflow import literature_query, literature_serving, literature_settings, output_contract

SERVING = ['search', 'get-paper', 'locate', 'list-papers', 'compare-measurements', 'replay']


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """Every owner records its argv; the installation has no retrieval settings."""
    monkeypatch.setenv(literature_settings.SETTINGS_ENV, str(tmp_path / 'absent-settings.json'))
    calls = []
    monkeypatch.setattr(literature_cli, 'main', lambda argv, *, serving: calls.append(('serving', argv, serving)) or 0)
    monkeypatch.setattr(literature, 'main', lambda argv=None: calls.append(('legacy', argv)) or 0)
    monkeypatch.setattr(literature_models, 'main', lambda argv=None: calls.append(('models', argv)) or 0,
                        raising=False)
    for module, label in ((literature_query, 'query'), (literature_evidence_scoring, 'score'),
                          (output_contract, 'output')):
        monkeypatch.setattr(module, 'main', lambda argv=None, label=label: calls.append((label, argv)) or 0)
    return calls


@pytest.mark.parametrize('command', [*SERVING, 'audit'])
def test_serving_subcommands_reach_the_governed_cli_with_trusted_serving(recorded, command):
    assert cli.main(['literature', command, '--rundir', 'run']) == 0
    assert recorded == [('serving', [command, '--rundir', 'run'], None)]


@pytest.mark.parametrize('legacy', [['check-cards', '--help'], ['follow', 'x'], ['resolve-title', 'x'], ['tier'],
                                    ['--help'], []])
def test_legacy_literature_subcommands_keep_their_module(recorded, legacy):
    assert cli.main(['literature', *legacy]) == 0
    assert recorded == [('legacy', legacy)]


@pytest.mark.parametrize('argv', [['inspect'], ['prefetch', '--root', 'models'], ['qualify', 'model-a', '--threads', '2']])
def test_model_subcommands_reach_the_model_installation(recorded, argv):
    assert cli.main(['literature', 'models', *argv]) == 0
    assert recorded == [('models', argv)]


@pytest.mark.parametrize('command,label', [('literature-query', 'query'), ('literature-score', 'score'),
                                           ('output-contract', 'output')])
def test_focused_literature_and_output_contract_commands_dispatch(recorded, command, label):
    assert cli.main([command, 'prepare', '--x']) == 0
    assert recorded == [(label, ['prepare', '--x'])]


def test_serving_receives_only_the_installation_configuration(recorded, monkeypatch, tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': literature_settings.SETTINGS_KIND,
                                'retrieval': {'provider': 'local', 'index_root': str(tmp_path / 'missing')}}))
    monkeypatch.setenv(literature_settings.SETTINGS_ENV, str(path))
    assert cli.main(['literature', 'search', '--rundir', 'run', '--request', 'r.json']) == 0
    configured = recorded[-1][2]
    assert isinstance(configured, literature_serving.ConfigurationRefusal) and configured.code == 'provider_unqualified'
    # Help and the audit never load the installation's index or models.
    assert cli.main(['literature', 'search', '--help']) == 0 and recorded[-1][2] is None
    assert cli.main(['literature', 'audit', '--rundir', 'run']) == 0 and recorded[-1][2] is None


def test_new_literature_commands_stay_behind_the_controller_command_policy(recorded, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_policy_refusal', lambda arguments: 'fictional policy refusal')
    for argv in (['literature', 'search', '--rundir', 'run'], ['literature', 'models', 'prefetch']):
        assert cli.main(argv) == 2
    assert recorded == [] and 'fictional policy refusal' in capsys.readouterr().err


def test_model_prefetch_dispatch_opens_no_network(recorded, monkeypatch):
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError('the CLI dispatch must not open a connection')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
    from ravel.setup import fetch
    monkeypatch.setattr(fetch, 'Fetcher', refuse)
    assert cli.main(['literature', 'models', 'prefetch', '--root', 'models']) == 0
    assert attempts == [] and recorded == [('models', ['prefetch', '--root', 'models'])]
