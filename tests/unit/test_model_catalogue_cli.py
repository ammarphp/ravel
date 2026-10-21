"""Model command selection, discovery privacy and transparent estimates."""
from copy import deepcopy
import io
import json
import stat
import urllib.error

import pytest

from ravel.workflow import model_catalogue as mc, transport_registry as tr


@pytest.fixture
def transports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    overlay = mc.load(builtin_only=True)
    overlay.pop('origins', None)
    overlay['models'] = []
    (tmp_path / 'overlay.json').write_text(json.dumps(overlay))
    monkeypatch.setenv('RAVEL_MODEL_CATALOGUE', str(tmp_path / 'overlay.json'))
    directory = tmp_path / 'transports'
    directory.mkdir()
    extra = tmp_path / 'extra-transports'
    extra.mkdir()
    monkeypatch.setenv('RAVEL_TRANSPORT_PATH', str(extra))
    original = tr.BUILTIN_DIR
    monkeypatch.setattr(tr, 'BUILTIN_DIR', directory)
    documents = []
    for name in ('http-anthropic', 'http-responses', 'http-gemini', 'claude-cli-oneshot'):
        doc = json.loads((original / (name + '.json')).read_text())
        documents.append(doc)
        (directory / (name + '.json')).write_text(json.dumps(doc))
        for variable in doc['auth']['env_names']:
            monkeypatch.delenv(variable, raising=False)
    from ravel.controller.step import seats
    monkeypatch.setattr(seats, 'wired_transports', lambda: {'wired': [d['id'] for d in documents],
                        'excluded': [], 'kinds': ['cli-oneshot', 'http-model']})
    monkeypatch.setattr(tr, 'resolve_executable', lambda *a, **k: ('/bin/true', 'digest'))
    return documents


def test_list_and_show(transports, capsys):
    assert mc.main(['list', '--family', 'openai', '--json']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and all(r['family'] == 'openai' for r in rows)
    assert mc.main(['show', rows[0]['id']]) == 0
    out = capsys.readouterr().out
    assert rows[0]['id'] in out and 'cost_usd' in out and '1000000' in out


def test_detect_statuses_and_secret_privacy(transports, monkeypatch, capsys):
    from ravel.workflow import models_cli as cli
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private-fixture-value')
    monkeypatch.setenv('OPENAI_API_KEY', 'private-fixture-value')
    def response(request, **kwargs):
        if 'anthropic' in request.full_url:
            assert request.full_url.endswith('/v1/models')
            return io.BytesIO(json.dumps({'data': [{'id': 'claude-opus-5-5'}, {'id': 'private-fixture-value'}]}).encode())
        raise urllib.error.URLError('private-fixture-value')
    monkeypatch.setattr('urllib.request.urlopen', response)
    path = tr.state_dir() / 'seen.receipt.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'transport_id': 'claude-cli-oneshot', 'observed': {'model': 'claude-opus-5-5'}}))
    assert mc.main(['detect', '--json']) == 0
    out = capsys.readouterr()
    record = json.loads(out.out)
    rows = {r['id']: r for r in record['transports']}
    assert any(m['status'] == 'listed' for m in rows['http-anthropic']['models'])
    assert rows['http-responses']['status'] == 'unreachable'
    assert rows['http-responses']['error_class'] == 'URLError'
    assert rows['http-gemini']['status'] == 'no_credential'
    assert any(m['status'] == 'observed' for m in rows['claude-cli-oneshot']['models'])
    assert any(m['status'] == 'declared' for m in rows['claude-cli-oneshot']['models'])
    target = cli.detection_path()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert 'private-fixture-value' not in out.out + out.err + target.read_text()


@pytest.mark.parametrize(('name', 'key', 'body', 'suffix'), [
    ('http-responses', 'OPENAI_API_KEY', {'data': [{'id': 'gpt-6-sol'}]}, '/v1/models'),
    ('http-gemini', 'GEMINI_API_KEY', {'models': [{'name': 'models/gemini-3.8-flash'}]}, '/v1beta/models'),
])
def test_listing_styles(transports, monkeypatch, name, key, body, suffix):
    from ravel.workflow import models_cli as cli
    doc = next(d for d in transports if d['id'] == name)
    monkeypatch.setenv(doc['auth']['env_names'][0], 'private-fixture-value')
    seen = []
    def response(request, **kwargs):
        seen.append(request)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr('urllib.request.urlopen', response)
    record = cli.detect_models([doc])
    assert seen[0].full_url.endswith(suffix)
    assert record['transports'][0]['models'][0]['status'] == 'listed'


def test_adoption_and_resolution_change(transports, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private-fixture-value')
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: io.BytesIO(b'{"data":[{"id":"claude-opus-9-9"}]}'))
    assert mc.main(['detect', '--adopt', '--yes', '--preset', 'balanced']) == 0
    assert mc.lookup('claude-opus-9-9')['class'] == 'strong'
    out = capsys.readouterr().out
    assert 'resolution changed: true' in out


@pytest.mark.parametrize('preset', ['premium', 'balanced', 'economy'])
def test_presets_resolve_reachable_families(transports, preset, capsys):
    assert mc.main(['preset', preset, '--json']) == 0
    out = json.loads(capsys.readouterr().out)
    assert 'families' not in out['agent_preferences']
    tiers = out['agent_preferences']['tier_models']
    assert all(tiers[t] for t in tr.TIERS)
    assert all(mc.lookup(model) for entries in tiers.values() for model in entries.values())


def test_write_and_check_refuse_unknown(transports, monkeypatch, capsys):
    from ravel.workflow import models_cli as cli
    from ravel.controller.authority import operator
    bad = {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': [],
           'tier_models': {'judgment': {'toy': 'gpt-unlisted'}}}
    monkeypatch.setattr(operator, 'operator_config', lambda: {'agent_preferences': bad})
    assert mc.main(['check']) == 2
    assert 'ravel models detect --adopt' in capsys.readouterr().out
    monkeypatch.setattr(cli, 'preferences', lambda *a, **k: (deepcopy(bad), [], None))
    assert mc.main(['preset', 'balanced', '--write']) == 2
    assert 'RAVEL_MODEL_CATALOGUE' in capsys.readouterr().out
    bad['tier_models']['judgment']['toy'] = 'gpt-6-sol'
    assert mc.main(['check']) == 0


def test_estimate_hand_computation(transports, monkeypatch):
    from ravel.workflow import models_cli as cli
    from ravel.controller.engagement import envelope
    project = {'routes': {'toy': {'full': {level: {'input_tokens': n, 'output_tokens': n,
                'sessions': 2, 'calls': 2} for level, n in [('low', 100), ('central', 200), ('high', 400)]}}},
               'packets': {'toy': {'full': [
                   {'category': 'judgment', 'input_tokens': 1, 'output_tokens': 1},
                   {'category': 'producer', 'input_tokens': 1, 'output_tokens': 1}]}}}
    monkeypatch.setattr(envelope, 'installed_projection', lambda: project)
    result = cli.estimate('balanced', route='toy')
    # First reachable family is the installed subscription family. Half of each
    # token pool uses judgment prices 4+20; the rest uses worker prices 2+10.
    assert result['routes']['toy']['central_usd'] == pytest.approx(200 * (24 + 12) / 2e6)
    assert result['routes']['toy']['high_usd'] == pytest.approx(400 * (24 + 12) / 2e6)
    assert 'upper bound' in result['caveat']


def test_local_listing_and_missing_cli(transports, monkeypatch, tmp_path):
    from ravel.workflow import models_cli as cli
    local = deepcopy(transports[0])
    local.update(id='toy-local', endpoint='http://127.0.0.1:11434/v1/chat/completions')
    local['auth'] = {'kind': 'none', 'env_names': [], 'command': None, 'header_style': None}
    local['models'] = [{'id': '{configured}', 'family': 'any', 'tiers': list(tr.TIERS)}]
    requests = []
    def response(request, **kwargs):
        requests.append(request)
        return io.BytesIO(b'{"models":[{"name":"gpt-6-sol"}]}')
    monkeypatch.setattr('urllib.request.urlopen', response)
    monkeypatch.setattr(tr, 'resolve_executable', lambda *a, **k: (None, None))
    record = cli.detect_models([local, transports[-1]])
    assert requests[0].method == 'GET'
    assert requests[0].full_url == 'http://127.0.0.1:11434/api/tags'
    assert record['transports'][0]['models'] == [{'id': 'gpt-6-sol', 'status': 'listed', 'catalogued': True}]
    assert record['transports'][1]['status'] == 'not_installed'


def test_listing_auth_is_not_forwarded_on_redirect(transports, monkeypatch):
    from ravel.workflow import models_cli as cli
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private-fixture-value')
    def response(request, **kwargs):
        assert request.method == 'GET'
        assert 'X-api-key' not in request.headers
        assert request.unredirected_hdrs['X-api-key'] == 'private-fixture-value'
        assert request.unredirected_hdrs['Anthropic-version'] == '2023-06-01'
        return io.BytesIO(b'{"data":[]}')
    monkeypatch.setattr('urllib.request.urlopen', response)
    assert cli.detect_models([transports[0]])['transports'][0]['status'] == 'ok'


def test_observation_keeps_transport_identity(transports, tmp_path):
    from ravel.workflow import models_cli as cli
    path = tr.state_dir() / 'observed.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'transport_id': 'other', 'observed_model': 'gpt-6-sol'}) + '\n' +
                    json.dumps({'transport_id': transports[-1]['id'], 'model_reported': 'claude-opus-5-5'}) + '\n')
    record = cli.detect_models([transports[-1]])
    assert any(m['id'] == 'claude-opus-5-5' and m['status'] == 'observed' for m in record['transports'][0]['models'])
    assert not any(m['id'] == 'gpt-6-sol' for m in record['transports'][0]['models'])


def test_adoption_without_a_named_sibling_defaults_to_strong(transports):
    from ravel.workflow import models_cli as cli
    assert cli._proposed('claude-unfamiliar')['class'] == 'strong'
    assert cli._proposed('claude-haiku-next')['class'] == 'small'


def test_declared_catalogue_models_are_only_candidates(transports):
    from ravel.workflow import models_cli as cli
    row = cli.detect_models([transports[-1]])['transports'][0]
    assert row['governed_wired'] is True
    assert row['models'] and all(m['status'] == 'declared' for m in row['models'])


@pytest.mark.parametrize(('suffix', 'qualified'), [
    ('-20261019', True), ('-2026-10-19', True), ('-9', False), ('-pro', False),
])
def test_detection_qualification_accepts_only_same_model_revisions(transports, monkeypatch, suffix, qualified):
    from ravel.workflow import models_cli as cli
    requested = 'claude-opus-5-5'
    monkeypatch.setattr(tr, 'read_qualification', lambda *args: {
        'observed': {'requested_model': requested, 'model': requested + suffix},
        'steps': [{'step': 'receipt_ok', 'passed': True}]})
    row = cli.detect_models([transports[-1]])['transports'][0]
    status = next(model['status'] for model in row['models'] if model['id'] == requested)
    assert status == ('qualified' if qualified else 'declared')


def test_preferences_use_listing_ids_not_newer_catalogue_defaults(transports, monkeypatch):
    from ravel.workflow import models_cli as cli
    document = transports[0]
    monkeypatch.setenv(document['auth']['env_names'][0], 'fictional')
    allowed = next(m['id'] for m in reversed(mc.load()['models'])
                   if m['family'] == 'anthropic' and m['status'] == 'current')
    monkeypatch.setattr(cli, '_listing', lambda *a: {allowed})
    record = cli.detect_models([document])
    prefs, _, _ = cli.preferences('balanced', record=record)
    assert {m for entries in prefs['tier_models'].values() for m in entries.values()} == {allowed}


def test_unwired_discovery_cannot_supply_preferences(transports, monkeypatch):
    from ravel.workflow import models_cli as cli
    from ravel.controller.step import seats
    monkeypatch.setattr(seats, 'wired_transports', lambda: {
        'wired': [], 'excluded': [{'transport': transports[-1]['id'], 'reason': 'sandbox:unavailable'}],
        'kinds': []})
    record = cli.detect_models([transports[-1]])
    assert record['transports'][0]['governed_wired'] is False
    prefs, _, _ = cli.preferences('balanced', record=record)
    assert prefs['transport_preference'] == []


def test_requested_model_is_not_observation(transports):
    from ravel.workflow import models_cli as cli
    path = tr.state_dir() / 'request.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'transport_id': transports[-1]['id'], 'model': 'claude-future-model',
                                'requested_model': 'claude-future-model'}))
    assert 'claude-future-model' not in cli._observed(transports[-1], set())


def test_local_any_family_presets_use_discovered_model(transports, monkeypatch):
    from ravel.workflow import models_cli as cli
    from ravel.controller.step import seats
    local = deepcopy(transports[0])
    local.update(id='fixture-local-loop', transport_kind='ravel-loop',
                 endpoint='http://127.0.0.1:11434/v1/chat/completions')
    local['auth'] = {'kind': 'none', 'env_names': [], 'command': None, 'header_style': None}
    local['models'] = [{'id': '{configured}', 'family': 'any', 'tiers': list(tr.TIERS)}]
    monkeypatch.setattr(tr, 'all_declarations', lambda **kwargs: [local])
    monkeypatch.setattr(seats, 'wired_transports', lambda: {'wired': [local['id']], 'excluded': [], 'kinds': ['ravel-loop']})
    monkeypatch.setattr(tr, 'loop_identity', lambda doc: {})
    monkeypatch.setattr(cli, '_listing', lambda *args: {'gpt-6-sol'})
    record = cli.detect_models([local])
    prefs, _, _ = cli.preferences('balanced', record=record)
    assert {m for entries in prefs['tier_models'].values() for m in entries.values()} == {'gpt-6-sol'}
