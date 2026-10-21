"""Transport registry: declarations, probe, selection and model-class routes (stub CLIs only)."""
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from ravel.workflow import transport_registry as tr

HELP_STUB = '''#!{python}
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, 'probe-calls.log'), 'a').write(' '.join(sys.argv[1:]) + '\\n')
if '--version' in sys.argv:
    print('stubcli 9.9.9')
else:
    print(open(os.path.join(here, 'help.txt')).read())
'''


def card(**changes):
    value = {'schema_version': 1, 'kind': 'role-card', 'id': 'synthetic-critic', 'family': 'specialist-review',
             'requires': {'tools': 'none', 'structured_output': True, 'isolation_min': 'none',
                          'attestation_min': 'transport', 'blind': False, 'parallel_safe': True},
             'model': {'tier': 'judgment', 'effort': 'high', 'distinct_family_from': []}}
    for key, update in changes.items():
        value[key] = {**value[key], **update} if type(update) is dict else update
    return value


def preferences(order, tier_models=None, family='specialist-review', model_families=None):
    value = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {family: order},
             'tier_models': tier_models or {}}
    if model_families:
        value['model_families'] = model_families
    return value


def declare(directory, identity, *, kind='cli-oneshot', launcher='stubcli', argv=None, family='anthropic',
            tools='none', isolation='cli-policy', blind=False, billing='subscription', auth_kind='login',
            env_names=(), pass_env=(), effort=True, endpoint=None, models=None):
    document = {'schema_version': 1, 'kind': 'transport', 'id': identity, 'transport_kind': kind,
                'launcher': launcher if kind in tr.CLI_KINDS else None,
                'argv_template': (argv or [launcher, '-p', '--model', '{model}', '--effort', '{effort}', '--json-schema', '{schema}',
                          '--isolate'])
                if kind in tr.CLI_KINDS else [],
                'models': models or [{'id': '{configured}', 'family': family, 'tiers': ['judgment', 'agent', 'cheap']}],
                'auth': {'kind': auth_kind, 'env_names': list(env_names), 'command': None,
                         'header_style': 'bearer' if kind == 'http-model' and auth_kind != 'none' else None},
                'pass_env': list(pass_env), 'billing': billing,
                'capabilities': {'tools': tools, 'isolation': isolation, 'attestation': 'transport',
                                 'structured_output': True, 'blind_capable': blind, 'effort_control': effort,
                                 'session_id': True, 'usage_report': True},
                'max_concurrent': 2, 'qualification': {'status': 'stub_tested', 'record': None}}
    if endpoint:
        document['endpoint'] = endpoint
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{identity}.json').write_text(json.dumps(document))
    return document


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    directory = tmp_path / 'transports'
    directory.mkdir()
    monkeypatch.setenv('RAVEL_TRANSPORT_PATH', str(directory))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.chdir(tmp_path)
    return directory


@pytest.fixture
def trusted(monkeypatch):
    """Treat the test's user-path declarations as shipped built-ins, to exercise selection mechanics."""
    monkeypatch.setattr(tr, 'origin', lambda document: 'builtin')


@pytest.fixture
def stub_cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'trusted-bin'
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(bin_dir))
    bin_dir.mkdir()
    path = bin_dir / 'stubcli'
    path.write_text(HELP_STUB.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    (bin_dir / 'help.txt').write_text('Usage: stubcli\n  -p, --print\n  --model <m>\n  --effort <e>\n  --json-schema <s>\n  --isolate\n')
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
    return bin_dir


def test_every_builtin_declaration_validates_with_unique_ids():
    documents = tr.all_declarations()
    ids = [d['id'] for d in documents]
    assert len(ids) == len(set(ids)) >= 30
    for document in documents:
        assert tr.validate(document) is document
        if document['billing'] == 'api':
            assert document['auth']['kind'] in ('env', 'command', 'login')
        for name in document['pass_env'] + document['auth']['env_names']:
            assert tr.NAME.match(name)
    # The host surfaces this cycle names, including Antigravity beside the API-key Gemini CLI.
    for required in ('claude-cli-oneshot', 'claude-cli-worker', 'codex-cli-oneshot', 'codex-cli-worker',
                     'codex-oss-worker', 'gemini-cli-oneshot', 'gemini-cli-worker', 'antigravity-cli-oneshot',
                     'antigravity-cli-worker', 'opencode-worker', 'qwen-worker', 'http-responses', 'http-anthropic',
                     'http-gemini', 'http-chat', 'external-relay', 'host-subagent-antigravity'):
        assert required in ids


def test_claude_declarations_isolate_without_bare():
    for identity in ('claude-cli-oneshot', 'claude-cli-worker'):
        argv = tr.load(identity)['argv_template']
        assert '--bare' not in argv
        assert argv[argv.index('--setting-sources') + 1] == 'project'
        mode = '--safe-mode' if identity == 'claude-cli-oneshot' else '--restricted'
        other = '--restricted' if mode == '--safe-mode' else '--safe-mode'
        for flag in (mode, '--strict-mcp-config', '--no-session-persistence', '--tools', '--effort', '--json-schema'):
            assert flag in argv
        assert other not in argv
    assert tr.load('claude-cli-worker')['argv_template'][-2:] == ['--max-budget-usd', '{usd}']


def test_every_claude_worker_variant_uses_restricted_so_the_mcp_server_stays_loaded():
    for identity in ('claude-cli-worker', 'claude-cli-worker-apikey', 'claude-cli-worker-bedrock',
                     'claude-cli-worker-vertex'):
        argv = tr.load(identity)['argv_template']
        assert '--restricted' in argv and '--safe-mode' not in argv
        assert '--restricted' in tr.template_flags(tr.load(identity))
        assert '--strict-mcp-config' in argv and '--allowedTools' in argv


def test_antigravity_declaration_uses_the_headless_agy_flags():
    one = tr.load('antigravity-cli-oneshot')
    assert one['launcher'] == 'agy' and one['auth']['kind'] == 'login' and one['billing'] == 'subscription'
    argv = one['argv_template']
    assert argv[:3] == ['agy', '-p', '{prompt}'] and argv[argv.index('--output-format') + 1] == 'json'
    assert argv[argv.index('--mode') + 1] == 'plan'
    worker = tr.load('antigravity-cli-worker')['argv_template']
    assert worker[worker.index('--mode') + 1] == 'accept-edits' and '--sandbox' in worker and '--add-dir' in worker
    assert tr.load('gemini-cli-oneshot')['auth'] == {'kind': 'env', 'env_names': ['GEMINI_API_KEY'],
                                                    'command': None, 'header_style': None}


# The model classes of the agent-layer parity matrix: every one must find a declared route.
MODEL_CLASSES = ['claude-login', 'claude-api-key', 'gpt-login', 'gpt-api-key', 'gemini-login', 'gemini-api-key',
                 'vertex', 'bedrock', 'azure-openai', 'xai', 'openrouter', 'local-tool-calling', 'local-text-only',
                 'fine-tuned']


@pytest.mark.parametrize('class_id', MODEL_CLASSES)
def test_every_model_class_finds_a_declared_route(class_id):
    row = next(r for r in tr.model_classes() if r['id'] == class_id)
    routes = tr.routes(class_id)
    assert routes['worker'] and routes['judgment']
    for role, ids in routes.items():
        for identity in ids:
            document = tr.load(identity)
            families = {m['family'] for m in document['models']}
            assert row['family'] in families or 'any' in families or row['family'] == 'any', (class_id, identity)
            if role == 'worker':
                assert document['transport_kind'] in ('cli-worker', 'ravel-loop', 'host-subagent')
                assert document['capabilities']['tools'] != 'none'
            else:
                assert document['transport_kind'] in ('cli-oneshot', 'http-model', 'ravel-loop')
    if class_id.startswith('local'):
        assert all(any(tr.load(i)['billing'] == 'local' for i in ids) for ids in routes.values())
    keyless = [tr.load(i) for i in routes['worker'] + routes['judgment']]
    if row['keyless']:
        assert any(d['auth']['kind'] in ('login', 'none') for d in keyless)
    # Every route except host subagents is launched by RAVEL itself.
    assert any(tr.load(i)['capabilities']['attestation'] == 'transport' for i in routes['worker'])


def test_model_class_index_covers_exactly_the_matrix():
    assert sorted(r['id'] for r in tr.model_classes()) == sorted(MODEL_CLASSES)


@pytest.mark.parametrize('model,family', [('claude-opus-x', 'anthropic'), ('amazon-bedrock/anthropic.claude-y', 'anthropic'),
                                          ('gpt-9', 'openai'), ('gemini-9-pro', 'google'), ('grok-9', 'xai'),
                                          ('llama-9-70b', 'meta'), ('qwen3-coder', 'alibaba'), ('my-finetune', 'unknown')])
def test_model_family_from_identifier(model, family):
    assert tr.model_family(model) == family


def test_render_argv_drops_unset_optional_flags_and_fills_values():
    document = tr.load('claude-cli-oneshot')
    argv = tr.render_argv(document, {'model': 'm-1', 'effort': None, 'schema': None}, executable='/x/claude')
    assert argv[0] == '/x/claude' and '--effort' not in argv and '--json-schema' not in argv
    assert argv[argv.index('--model') + 1] == 'm-1' and argv[-2:] == ['--tools', '']
    with pytest.raises(KeyError):
        tr.render_argv(document, {'effort': 'high', 'schema': None})


def test_child_environment_passes_declared_names_only():
    document = tr.load('claude-cli-worker-bedrock')
    source = {'PATH': '/bin', 'HOME': '/h', 'FOO_API_KEY': 'planted-secret', 'ANTHROPIC_BASE_URL': 'x',
              'OPENAI_API_KEY': 'other-secret', 'AWS_PROFILE': 'p', 'AWS_REGION': 'r', 'CLAUDE_CODE_USE_BEDROCK': '1',
              'AWS_SECRET_ACCESS_KEY': 'not-declared'}
    env, names = tr.child_environment(document, source)
    assert set(env) == {'PATH', 'HOME', 'AWS_PROFILE', 'AWS_REGION', 'CLAUDE_CODE_USE_BEDROCK'}
    assert names == sorted(env) and 'planted-secret' not in json.dumps(env)


def test_probe_confirms_flags_and_refuses_a_flag_missing_from_help(user_dir, stub_cli):
    declare(user_dir, 'stub-oneshot')
    record = tr.probe('stub-oneshot')
    assert record['cli_version'] == 'stubcli 9.9.9' and record['unusable'] == []
    assert record['flags'] == {'-p': 'confirmed', '--model': 'confirmed', '--effort': 'confirmed',
                               '--json-schema': 'confirmed', '--isolate': 'confirmed'}
    assert record['executable_sha256'] == tr.file_sha256(stub_cli / 'stubcli') and record['exit_status'] == 0
    assert tr.read_probe('stub-oneshot') == record
    chosen = tr.select(card(), preferences(['stub-oneshot'], {'judgment': {'stub-oneshot': 'claude-x'}}))
    assert chosen['transport_id'] == 'stub-oneshot'
    (stub_cli / 'help.txt').write_text('Usage: stubcli\n  -p\n  --model <m>\n  --effort <e>\n  --json-schema <s>\n  --isolated-but-different\n')
    record = tr.probe('stub-oneshot')
    assert record['flags']['--isolate'] == 'missing' and record['unusable'] == ['--isolate']
    assert not any(record['capabilities_confirmed'].values())
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card(), preferences(['stub-oneshot']))
    assert refused.value.missing == ['probe:--isolate']


def test_unprobed_or_changed_cli_declaration_is_unusable(user_dir, stub_cli):
    declare(user_dir, 'stub-oneshot')
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card(), preferences(['stub-oneshot']))
    assert refused.value.missing == ['probe']
    tr.probe('stub-oneshot')
    declare(user_dir, 'stub-oneshot', argv=['stubcli', '-p', '--model', '{model}'])
    with pytest.raises(tr.TransportRefusal):
        tr.select(card(), preferences(['stub-oneshot']))


def test_capability_refusal_names_the_capability_before_any_process(user_dir, stub_cli):
    declare(user_dir, 'stub-oneshot')
    tr.probe('stub-oneshot')
    log = stub_cli / 'probe-calls.log'
    before = log.read_text()
    tools_card = card(requires={'tools': 'broker-readonly'})
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(tools_card, preferences(['stub-oneshot']))
    assert refused.value.missing == ['tools'] and 'tools' in str(refused.value)
    blind_card = card(requires={'blind': True})
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(blind_card, preferences(['stub-oneshot']))
    # A blind card votes; a one-shot under the CLI's own policy is not isolated for it.
    assert refused.value.missing == ['isolation', 'blind']
    assert log.read_text() == before  # selection itself starts no process


def test_first_qualifying_preference_wins_and_unmet_effort_refuses(user_dir, stub_cli, trusted):
    declare(user_dir, 'stub-oneshot')
    declare(user_dir, 'stub-http', kind='http-model', isolation='ravel-sandbox', blind=True, billing='api',
            auth_kind='env', env_names=['STUB_HTTP_KEY'], effort=False, family='openai',
            endpoint='https://models.invalid/v1/chat')
    tr.probe('stub-oneshot')
    blind_card = card(requires={'blind': True}, model={'effort': None})
    chosen = tr.select(blind_card, preferences(['stub-oneshot', 'stub-http'], {'judgment': {'stub-http': 'gpt-x'}}))
    assert chosen['transport_id'] == 'stub-http' and chosen['model'] == 'gpt-x'
    assert chosen['effort'] is None and chosen['probe_sha256'] is None
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card(requires={'blind': True}), preferences(['stub-http'], {'judgment': {'stub-http': 'gpt-x'}}))
    assert refused.value.missing == ['effort']
    assert chosen['declaration_sha256'] == tr.declaration_sha256(tr.load('stub-http'))
    plain = tr.select(card(), preferences(['stub-oneshot', 'stub-http'], {'judgment': {'stub-oneshot': 'claude-x'}}))
    assert plain['transport_id'] == 'stub-oneshot' and plain['effort'] == 'high'
    assert plain['probe_sha256'] == tr.digest(tr.read_probe('stub-oneshot'))
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card(model={'effort': None}), preferences(['stub-http']))
    assert refused.value.missing == ['model:judgment']
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card(family='production'), preferences(['stub-http']))
    assert refused.value.missing == ['preferences:production']


def test_per_role_models_and_same_family_selection(user_dir):
    declare(user_dir, 'stub-anthropic', kind='http-model', isolation='ravel-sandbox', blind=True, billing='api',
            auth_kind='env', env_names=['STUB_A_KEY'], family='anthropic', endpoint='https://a.invalid/v1/messages')
    declare(user_dir, 'stub-openai', kind='http-model', isolation='ravel-sandbox', blind=True, billing='api',
            auth_kind='env', env_names=['STUB_O_KEY'], family='openai', endpoint='https://o.invalid/v1/responses')
    models = {'judgment': {'stub-anthropic': 'claude-x', 'stub-openai': 'gpt-x'},
              'agent': {'stub-anthropic': 'claude-y'}}
    producer = tr.select(card(id='producer', family='production', model={'tier': 'agent', 'effort': None}),
                         preferences(['stub-anthropic'], models, family='production'))
    critic_card = card(model={'effort': None})
    critic = tr.select(critic_card, preferences(['stub-anthropic', 'stub-openai'], models))
    assert (producer['model'], critic['model']) == ('claude-y', 'claude-x')
    assert producer['family'] == critic['family'] == 'anthropic'


def test_local_only_selection_refuses_remote_and_unlisted_models(user_dir):
    declare(user_dir, 'stub-remote', kind='http-model', isolation='ravel-sandbox', blind=True, billing='api',
            auth_kind='env', env_names=['STUB_KEY'], family='any', endpoint='https://remote.invalid/v1/chat')
    declare(user_dir, 'stub-lan', kind='http-model', isolation='ravel-sandbox', blind=True, billing='local',
            auth_kind='none', family='any', endpoint='https://10.0.0.5/v1/chat')
    declare(user_dir, 'stub-local', kind='http-model', isolation='ravel-sandbox', blind=True, billing='local',
            auth_kind='none', family='any', endpoint='http://127.0.0.1:8000/v1/chat')
    models = {'judgment': {'stub-remote': 'local-x', 'stub-lan': 'local-x', 'stub-local': 'local-x'}}
    bound = {'local-x': 'meta'}
    plain = card(model={'effort': None})
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(plain, preferences(['stub-remote', 'stub-lan'], models, model_families=bound), local_models=['local-x'])
    assert refused.value.missing == ['local_only']
    assert tr.select(plain, preferences(['stub-remote', 'stub-local'], models, model_families=bound),
                     local_models=['local-x'])['transport_id'] == 'stub-local'
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(plain, preferences(['stub-local'], models, model_families=bound), local_models=['other'])
    assert refused.value.missing == ['local_models']


def test_declarations_are_closed_and_user_ids_cannot_shadow_builtins(user_dir):
    document = declare(user_dir, 'stub-x')
    document['secret_value'] = 'x'
    with pytest.raises(ValueError, match='unknown'):
        tr.validate(document)
    (user_dir / 'stub-x.json').unlink()
    declare(user_dir, 'claude-cli-oneshot')
    with pytest.raises(ValueError, match='declared twice'):
        tr.all_declarations()


def test_transport_command_lists_shows_and_probes(user_dir, stub_cli, capsys):
    declare(user_dir, 'stub-oneshot')
    assert tr.main(['list', '--json']) == 0
    rows = {r['id']: r for r in json.loads(capsys.readouterr().out)}
    assert rows['stub-oneshot']['probe'] == 'unprobed' and rows['http-anthropic']['probe'] == 'n/a'
    assert tr.main(['probe', 'stub-oneshot']) == 0
    assert json.loads(capsys.readouterr().out)[0]['unusable'] == []
    assert tr.main(['show', 'stub-oneshot']) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown['probe']['transport_id'] == 'stub-oneshot' and shown['declaration']['id'] == 'stub-oneshot'


def _catalogue_stub(monkeypatch, known):
    """A stand-in model catalogue listing ``known``; None removes the catalogue module."""
    import types
    if known is None:
        monkeypatch.setitem(sys.modules, 'ravel.workflow.model_catalogue', None)
        return
    module = types.ModuleType('ravel.workflow.model_catalogue')
    module.problem = lambda model_id: None if model_id in known else 'model:uncatalogued'
    module.remedy = lambda model_id: f'add {model_id} to the catalogue'
    module.lookup = lambda model_id: {'id': model_id, 'tiers': list(tr.TIERS),
                                     'efforts': ['low', 'medium', 'high', 'xhigh', 'max']} if model_id in known else None
    monkeypatch.setitem(sys.modules, 'ravel.workflow.model_catalogue', module)


def _http_route(user_dir, identity='stub-route'):
    declare(user_dir, identity, kind='http-model', isolation='ravel-sandbox', blind=True, billing='api',
            auth_kind='env', env_names=['STUB_KEY'], family='anthropic', endpoint='https://a.invalid/v1/messages')
    return identity


def test_cheap_ok_card_selects_the_cheap_model_mapped_to_the_transport(user_dir, monkeypatch):
    _catalogue_stub(monkeypatch, {'claude-small'})
    route = _http_route(user_dir)
    models = {'agent': {route: 'claude-mid'}, 'cheap': {route: 'claude-small'}}
    mechanical = card(model={'tier': 'agent', 'effort': None, 'cheap_ok': True})
    selection = tr.select(mechanical, preferences([route], models))
    assert (selection['model'], selection['tier'], selection['card_tier']) == ('claude-small', 'cheap', 'agent')
    assert selection['catalogue'] == 'catalogued'
    for key in ('transport_id', 'family', 'effort', 'declaration_sha256', 'declaration_origin', 'probe_sha256'):
        assert key in selection


def test_cheap_ok_card_without_a_cheap_mapping_keeps_its_card_tier(user_dir, monkeypatch):
    _catalogue_stub(monkeypatch, set())
    route = _http_route(user_dir)
    other = _http_route(user_dir, 'stub-other')
    mechanical = card(model={'tier': 'agent', 'effort': None, 'cheap_ok': True})
    for models in ({'agent': {route: 'claude-mid'}},
                   {'agent': {route: 'claude-mid'}, 'cheap': {other: 'claude-small'}}):
        selection = tr.select(mechanical, preferences([route], models))
        assert (selection['model'], selection['tier'], selection['card_tier']) == ('claude-mid', 'agent', 'agent')
        assert selection['catalogue'] == 'uncatalogued'


def test_a_card_without_cheap_ok_ignores_the_cheap_mapping(user_dir, monkeypatch):
    _catalogue_stub(monkeypatch, {'claude-mid'})
    route = _http_route(user_dir)
    models = {'agent': {route: 'claude-mid'}, 'cheap': {route: 'claude-small'}}
    for spec in ({'tier': 'agent', 'effort': None}, {'tier': 'agent', 'effort': None, 'cheap_ok': False}):
        selection = tr.select(card(model=spec), preferences([route], models))
        assert (selection['model'], selection['tier'], selection['card_tier']) == ('claude-mid', 'agent', 'agent')
        assert selection['catalogue'] == 'catalogued'


def test_catalogue_label_is_unavailable_without_a_catalogue_and_never_refuses(user_dir, monkeypatch):
    route = _http_route(user_dir)
    models = {'judgment': {route: 'claude-unlisted'}}
    _catalogue_stub(monkeypatch, None)
    assert tr.select(card(model={'effort': None}), preferences([route], models))['catalogue'] == 'unavailable'
    _catalogue_stub(monkeypatch, set())
    selection = tr.select(card(model={'effort': None}), preferences([route], models))
    assert (selection['model'], selection['catalogue']) == ('claude-unlisted', 'uncatalogued')


def test_catalogue_capabilities_refuse_unsupported_effort_and_cheap_falls_back():
    assert tr.catalogue_requirement_problem('gpt-5.4-mini', 'cheap', 'max') == 'model:effort'
    assert tr.catalogue_requirement_problem('claude-fable-5-1', 'cheap', 'high') == 'model:tier'
    assert tr.catalogue_requirement_problem('gpt-6.1-sol', 'agent', 'max') is None
    route = tr.load('codex-cli-worker')
    role = card(model={'tier': 'agent', 'effort': 'max', 'cheap_ok': True})
    prefs = {'tier_models': {'cheap': {route['id']: 'gpt-5.4-mini'},
                             'agent': {route['id']: 'gpt-6.1-sol'}}}
    assert tr.effective_tier(role, route, prefs) == 'agent'
    prefs['tier_models']['cheap'][route['id']] = 'gpt-6-luna'
    assert tr.effective_tier(role, route, prefs) == 'cheap'
