"""CLI worker adapter controls with fake CLI executables only: no real CLI, no network."""
import json
import os
from pathlib import Path
import sys

import pytest

from ravel.workflow import agent_worker as worker, broker, role_registry, sandbox, transport_registry as tr
from ravel.workflow.transports import cli_worker

FLAGS = {
    'claude': ['-p', '--output-format', '--model', '--effort', '--json-schema', '--setting-sources', '--restricted', '--safe-mode',
               '--strict-mcp-config', '--no-session-persistence', '--tools', '--allowedTools', '--max-budget-usd',
               '--mcp-config'],
    'codex': ['--json', '--skip-git-repo-check', '--sandbox', '--cd', '--model', '-c', '--output-schema',
              '--output-last-message'],
    'gemini': ['-p', '--output-format', '--model', '--sandbox', '--include-directories'],
}

FAKE_CLAUDE = '''#!{python} -B
import json, os, subprocess, sys
from pathlib import Path
here = Path(__file__).resolve().parent
args = sys.argv[1:]
if args == ['--version']:
    print('fake-cli 9.9.9'); sys.exit(0)
if '--help' in args:
    sys.stdout.write((here / 'help.txt').read_text()); sys.exit(0)
mode = (here / 'mode.txt').read_text().strip()
prompt = sys.stdin.read()
Path('scratch/seen.json').write_text(json.dumps({{'argv': args, 'env': sorted(os.environ), 'prompt': prompt,
    'config_dir': os.environ.get('CLAUDE_CONFIG_DIR'), 'user': os.environ.get('USER'),
    'logname': os.environ.get('LOGNAME')}}))
entry = json.loads(Path(args[args.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']
server = subprocess.Popen([entry['command'], *entry['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def rpc(n, method, params):
    server.stdin.write(json.dumps({{'jsonrpc': '2.0', 'id': n, 'method': method, 'params': params}}) + '\\n')
    server.stdin.flush()
    return json.loads(server.stdout.readline())
rpc(1, 'initialize', {{}})
names = [t['name'] for t in rpc(2, 'tools/list', {{}})['result']['tools']]
read = rpc(3, 'tools/call', {{'name': 'ws_read', 'arguments': {{'path': 'inputs/conformance.json'}}}})
nonce = json.loads(read['result']['structuredContent']['stdout_tail'])['nonce']
if mode == 'gate_probe':
    rpc(5, 'tools/call', {{'name': 'read', 'arguments': {{'path': 'inputs/conformance.json'}}}})
    rpc(6, 'tools/call', {{'name': 'knowledge query', 'arguments': {{'op': 'xsec', 'args': {{}}}}}})
    found = rpc(7, 'tools/call', {{'name': 'knowledge_find', 'arguments': {{'text': 'broker workspace'}}}})
    Path('scratch/found.json').write_text(json.dumps(found['result']['structuredContent']))
    Path('outputs/conformance.txt').write_text(nonce)
elif mode != 'skip_write':
    rpc(4, 'tools/call', {{'name': 'ws_write', 'arguments': {{'path': 'outputs/conformance.txt', 'content': nonce}}}})
if 'outputs/surface.txt' in prompt:
    listed = ['mcp__ravel__' + n for n in names] + (['synced-skill-example'] if mode == 'skills_leak' else [])
    rpc(8, 'tools/call', {{'name': 'ws_write', 'arguments': {{'path': 'outputs/surface.txt',
                                                            'content': '\\n'.join(listed)}}}})
server.stdin.close(); server.wait()
print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '',
    'session_id': (here / 'session.txt').read_text().strip(), 'num_turns': 99 if mode == 'over_turns' else 3,
    'total_cost_usd': 0.0123, 'usage': {{'input_tokens': 100, 'output_tokens': 20}},
    'modelUsage': {{'claude-fixture-model': {{'outputTokens': 20}}}},
    'structured_output': {{'completed': True, 'summary': 'conformance written'}}}}))
'''


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """A trusted fake-CLI bin directory, isolated state, a login-only Claude directory and run preferences."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in ('state', 'home', 'claude-login', 'run/inputs'):
        (tmp_path / name).mkdir(parents=True)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('PATH', f'{bin_dir}:/usr/bin:/bin')
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(bin_dir))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'claude-login'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    (bin_dir / 'mode.txt').write_text('ok')
    (bin_dir / 'session.txt').write_text('sess-1')
    return tmp_path


def install(root, launcher, body=None):
    bin_dir = root / 'bin'
    (bin_dir / 'help.txt').write_text('Usage\n' + '\n'.join(f'  {f} <x>' for f in sorted(set(sum(FLAGS.values(), [])))))
    path = bin_dir / launcher
    path.write_text((body or FAKE_CLAUDE).format(python=sys.executable))
    path.chmod(0o755)
    return path


def probe(transport_id, executable):
    record = tr.probe(transport_id, executable=str(executable))
    assert not record['unusable'], record
    return record


def qualification_record(transport_id, record):
    """A synthetic stored qualification bound to this probe (tests only, under tmp)."""
    document = tr.load(transport_id)
    path = tr.qualification_path(transport_id)
    assert path.is_relative_to(Path(os.environ['RAVEL_STATE_DIR']))  # never outside the test's tmp state
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': transport_id,
                                'status': 'live_qualified', 'record_path': str(path),
                                'executable_path': record['executable_path'],
                                'executable_sha256': record['executable_sha256'],
                                'declaration_sha256': tr.declaration_sha256(document),
                                'probe_sha256': tr.digest(record), 'receipt': {}, 'observed': {}, 'steps': [],
                                'rundir': 'synthetic', 'qualified_utc': '2026-10-11T00:00:00Z'}))


def preferences(root, transport_id, model='claude-fixture-model'):
    (root / 'run/inputs/agent_preferences.json').write_text(json.dumps({
        'schema_version': 1, 'kind': 'agent-preferences', 'families': {},
        'tier_models': {tier: {transport_id: model} for tier in tr.TIERS}}))


def spec(root, role='analysis-author', transport='claude-cli-worker', schema='producer.v1', attempt=1, cost=None):
    run = root / 'run'
    (run / 'inputs/conformance.json').write_text(json.dumps({'nonce': 'n-0123456789'}))
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'cli.worker', 'attempt': attempt,
            'role': {'id': role, 'version': role_registry.load(role)['version'],
                     'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': [transport],
            'inputs': [{'pin': {'path': 'inputs/conformance.json', 'sha256': broker.sha(run / 'inputs/conformance.json')},
                        'as': 'inputs/conformance.json'}],
            'declared_outputs': [{'path': 'outputs/conformance.txt', 'kind': 'text', 'required': True}],
            'budgets': {'max_turns': 8, 'max_wall_seconds': 60, 'max_broker_calls': 12, 'max_cost_usd': cost},
            'final_record_schema': schema, 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


def ready(root, transport_id='claude-cli-worker', launcher='claude', body=None):
    record = probe(transport_id, install(root, launcher, body))
    qualification_record(transport_id, record)
    preferences(root, transport_id)
    return record


def real_sandbox_or_skip(tmp_path):
    ws = tmp_path / 'sandbox-check'
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True)
    (tmp_path / 'private').write_text('protected')
    try:
        sandbox.probe(ws, forbidden=tmp_path / 'private', read_paths=sandbox.runtime_paths([sys.executable]))
    except sandbox.SandboxUnavailable:
        pytest.skip('sandbox-blocked: actual OS confinement unavailable here')


# ------------------------------------------------------------------ descriptor

def test_runtime_roots_resolve_system_aliases_before_validation(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(runtime, target_is_directory=True)
    monkeypatch.setattr(sandbox, 'SYSTEM_RUNTIME_ROOTS', (str(runtime), str(alias)))
    roots = sandbox.runtime_paths([sys.executable])
    assert roots.count(str(runtime)) == 1
    assert str(alias) not in roots
    assert all(broker.ordinary(root) == Path(root) for root in roots)


def test_linux_runtime_aliases_are_recreated_only_for_mounted_targets(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(runtime, target_is_directory=True)
    monkeypatch.setattr(sandbox, 'LINUX_RUNTIME_ALIASES', (str(alias),))
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    command = sandbox.linux_command(workspace, ['/usr/bin/true'], read_paths=[runtime])
    index = command.index('--symlink')
    assert command[index + 1:index + 3] == [str(runtime), str(alias)]
    assert '--symlink' not in sandbox.linux_command(workspace, ['/usr/bin/true'])


def test_linux_runtime_alias_with_missing_target_is_not_recreated(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path / 'missing', target_is_directory=True)
    monkeypatch.setattr(sandbox, 'LINUX_RUNTIME_ALIASES', (str(alias),))
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    command = sandbox.linux_command(workspace, ['/usr/bin/true'], read_paths=[runtime])
    assert '--symlink' not in command


def test_descriptor_is_built_in_code_from_declaration_probe_selection_and_schema(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    record = ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    assert tuple(d) == cli_worker.DESCRIPTOR_KEYS
    argv = d['argv']
    assert argv[0] == record['executable_path'] and Path(argv[0]).is_absolute()
    for flag, value in (('--model', 'claude-fixture-model'), ('--effort', 'high'), ('--setting-sources', 'project'),
                        ('--tools', '')):
        assert argv[argv.index(flag) + 1] == value
    assert '--restricted' in argv and '--safe-mode' not in argv and '--strict-mcp-config' in argv and '--bare' not in argv
    assert '--max-budget-usd' not in argv  # null cost budget on the subscription route
    assert json.loads(argv[argv.index('--json-schema') + 1]) == cli_worker.FINAL_JSON_SCHEMAS['producer.v1']
    allowed = argv[argv.index('--allowedTools') + 1].split(',')
    assert allowed and all(name.startswith('mcp__ravel__') for name in allowed) and 'mcp__ravel__ws_write' in allowed
    mcp = json.loads(Path(argv[argv.index('--mcp-config') + 1]).read_text())
    assert list(mcp['mcpServers']) == ['ravel'] and 'work_cli' in ' '.join(mcp['mcpServers']['ravel']['args'])
    # USER and LOGNAME come from the password database in the supervisor, never from the parent.
    assert d['pass_env_names'] == ['CLAUDE_CONFIG_DIR', 'LOGNAME', 'USER']
    transport = d['transport']
    assert transport['probe_sha256'] == tr.digest(record) and transport['executable_sha256'] == record['executable_sha256']
    assert transport['cli_home'] == str(broker.ordinary(cli / 'claude-login')) and transport['cli_home_owned'] is False
    assert transport['verified_env'] == ['CLAUDE_CONFIG_DIR'] and transport['network'] == 'provider'
    runtime = sandbox.runtime_paths(argv)
    assert all(any(Path(p).is_relative_to(r) for r in runtime) for p in d['read_paths'])
    assert set(d['allowed_actions']) >= {'read', 'write'}
    # The complete prompt and its audit are in custody; the prompt goes on stdin, never in argv.
    audit = json.loads(Path(transport['prompt_audit']['path']).read_text())
    prompt = Path(transport['stdin']['path']).read_text()
    assert audit['prompt']['sha256'] == broker.sha(Path(transport['stdin']['path'])) and audit['argv'] == argv
    assert 'analysis-author' in prompt and 'outputs/conformance.txt' in prompt and prompt not in ' '.join(argv)
    assert Path(transport['stdin']['path']).is_relative_to(broker.custody(cli / 'run'))
    assert d['model'] == {'requested': 'claude-fixture-model', 'observed': None, 'family': 'anthropic', 'effort': 'high'}


def test_reviewer_runs_full_tool_but_a_blind_toolbelt_keeps_workspace_tools_only(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    card = role_registry.load('physics-critic')
    assert card['requires']['tools'] == 'none'
    full = cli_worker.toolbelt_for(card, tr.load('claude-cli-worker'), False)
    blind = cli_worker.toolbelt_for(card, tr.load('claude-cli-worker'), True)
    actions = lambda belt: {t['executes_through']['action'] for t in belt['tools']}
    assert {'read', 'write'} <= actions(full) and actions(blind) == {None, 'read', 'write'}
    assert any(row['reason'] == 'blind_role' for row in blind['omitted'])


@pytest.mark.parametrize('case,missing', [
    ('no-probe', ['probe']),
    ('stale-executable', ['probe:stale-executable']),
    ('no-login-dir', ['CLAUDE_CONFIG_DIR']),
    ('user-config-dir', ['claude_config_dir:user-configuration']),
    ('instruction-file', ['workspace:instruction-file']),
    ('no-preferences', ['preferences']),
    ('role-card-changed', ['role_card:changed']),
])
def test_refusals_name_the_missing_item(cli, monkeypatch, case, missing):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    record = ready(cli)
    s = spec(cli)
    if case == 'no-probe':
        tr.probe_path('claude-cli-worker').unlink()
    elif case == 'stale-executable':
        exe = Path(record['executable_path'])
        exe.write_text(exe.read_text() + '\n# upgraded\n')
    elif case == 'no-login-dir':
        monkeypatch.delenv('CLAUDE_CONFIG_DIR')
    elif case == 'user-config-dir':
        (cli / 'claude-login/CLAUDE.md').write_text('user instructions')
    elif case == 'no-preferences':
        (cli / 'run/inputs/agent_preferences.json').unlink()
    elif case == 'role-card-changed':
        s['role']['card_sha256'] = '0' * 64
    ws = worker.materialize(cli / 'run', s)
    if case == 'instruction-file':
        (ws.parent / 'AGENTS.md').write_text('instructions')
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    if case == 'stale-executable':
        # Selection already refuses a stale probe before the adapter reaches its own check.
        assert 'probe:stale-executable' in refused.value.missing
    else:
        assert refused.value.missing == missing


def test_one_shot_or_other_kinds_are_refused_never_a_fallback(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    oneshot = probe('claude-cli-oneshot', cli / 'bin/claude')
    s = spec(cli, transport='claude-cli-oneshot')
    preferences(cli, 'claude-cli-oneshot')
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert 'tools' in refused.value.missing  # selection refuses a toolless one-shot for a producer card
    selection = {'transport_id': 'claude-cli-oneshot', 'model': 'claude-fixture-model', 'effort': None,
                 'probe_sha256': tr.digest(oneshot)}
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s, ws, selection=selection)
    assert refused.value.missing == ['transport_kind:cli-oneshot']


@pytest.mark.parametrize('transport_id,expected', [
    ('codex-cli-worker-azure', 'unimplemented:codex-cli-worker-azure'),
    ('antigravity-cli-worker', 'worker_surface.mcp:probe_required'),
    ('opencode-worker', 'adapter:opencode'),
    ('qwen-worker', 'adapter:qwen'),
    ('codex-oss-worker', 'worker_surface'),
    ('claude-cli-worker', None), ('claude-cli-worker-apikey', None), ('claude-cli-worker-bedrock', None),
    ('claude-cli-worker-vertex', None), ('codex-cli-worker', None),
    # API-billed routes whose CLI enforces no cost ceiling are refused by name, never failed by construction.
    ('codex-cli-worker-apikey', 'cost_unenforceable:codex-cli-worker-apikey'),
    ('gemini-cli-worker', 'cost_unenforceable:gemini-cli-worker'),
])
def test_each_declaration_is_covered_or_refused_by_name(transport_id, expected, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    document = tr.load(transport_id)
    assert cli_worker.unsupported(document) == expected
    assert tr.executor_problem(document) == expected


def test_executor_needs_the_sandbox_backend(monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: None)
    assert tr.executor_problem(tr.load('claude-cli-worker')) == 'sandbox_unavailable'
    assert not tr.executor_available(tr.load('claude-cli-worker'))
    capabilities, reasons = tr.effective_capabilities(tr.load('claude-cli-worker'), None)
    assert capabilities is None and reasons == ['sandbox_unavailable']


def test_api_routes_need_an_enforceable_cost_budget(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-not-a-key')
    record = probe('claude-cli-worker-apikey', install(cli, 'claude'))
    qualification_record('claude-cli-worker-apikey', record)
    preferences(cli, 'claude-cli-worker-apikey')
    s = spec(cli, transport='claude-cli-worker-apikey')
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert refused.value.missing == ['cost_budget']
    s = spec(cli, transport='claude-cli-worker-apikey', attempt=2, cost=0.25)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    assert d['argv'][d['argv'].index('--max-budget-usd') + 1] == '0.2500'
    assert d['pass_env_names'] == ['ANTHROPIC_API_KEY', 'LOGNAME', 'USER'] and 'synthetic-not-a-key' not in json.dumps(d)
    home = Path(d['transport']['cli_home'])
    assert home == sandbox.cli_home_for(ws) and d['transport']['cli_home_owned'] is True
    assert d['transport']['launch_env'] == {'CLAUDE_CONFIG_DIR': str(home / 'claude'),
                                            'CLAUDE_CODE_TMPDIR': str(ws / 'scratch/tmp'), 'TMPDIR': str(ws / 'scratch/tmp'),
                                            'HOME': str(sandbox.user_home_for(ws))}


def _fake_keychains(cli, monkeypatch):
    real = cli / 'account/Library/Keychains'
    real.mkdir(parents=True)
    (real / 'login.keychain-db').write_text('synthetic')
    monkeypatch.setattr(sandbox, 'login_keychains', lambda: real)
    return real


def test_claude_worker_home_holds_only_the_login_keychain_link(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    real = _fake_keychains(cli, monkeypatch)
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    home = sandbox.user_home_for(ws)
    assert d['transport']['user_home'] == str(home) and d['transport']['launch_env']['HOME'] == str(home)
    assert [p.name for p in home.iterdir()] == ['Library'] and [p.name for p in (home / 'Library').iterdir()] == ['Keychains']
    link = home / 'Library/Keychains'
    assert link.is_symlink() and Path(os.readlink(link)) == real
    assert worker._cli_launch(d, ws)[3]['HOME'] == str(home) and worker._user_home(d, ws) == home
    # The profile the supervisor builds from this descriptor reads the keychain directory.
    profile = sandbox.macos_profile(ws, network='provider', keychain_home=worker._user_home(d, ws))
    assert '(allow file-read* (subpath ' + sandbox.quote(str(real)) + ')' in profile
    # A home with anything else in it is refused, not reused.
    (home / 'extra').write_text('x')
    s2 = spec(cli, attempt=1)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s2, ws)
    assert refused.value.missing == ['keychain_home']
    (home / 'extra').unlink()
    cli_worker.remove_home(ws, d)
    assert not home.exists() and (real / 'login.keychain-db').read_text() == 'synthetic'


def test_a_forged_keychain_home_is_refused_by_the_supervisor(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    _fake_keychains(cli, monkeypatch)
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    d['transport']['user_home'] = str(cli / 'home')
    with pytest.raises(ValueError):
        worker._user_home(d, ws)


def test_codex_and_non_macos_claude_workers_get_no_keychain_home(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    _fake_keychains(cli, monkeypatch)
    (cli / 'home/.codex').mkdir()
    (cli / 'home/.codex/auth.json').write_text('{"synthetic": true}')
    qualification_record('codex-cli-worker', probe('codex-cli-worker', install(cli, 'codex')))
    preferences(cli, 'codex-cli-worker', model='gpt-fixture')
    s = spec(cli, transport='codex-cli-worker')
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    assert d['transport']['user_home'] is None and 'HOME' not in d['transport']['launch_env']
    assert not {'USER', 'LOGNAME'} & set(d['pass_env_names'])
    with pytest.raises(ValueError, match='pass_env_names'):
        worker._pass_env_names({**d, 'pass_env_names': ['USER']})
    assert not sandbox.user_home_for(ws).exists() and worker._user_home(d, ws) is None
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    ready(cli)
    s = spec(cli, attempt=2)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    assert d['transport']['user_home'] is None and not sandbox.user_home_for(ws).exists()


def test_codex_home_and_gemini_home_carry_only_login_material_and_the_broker_server(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    codex_home = cli / 'home/.codex'
    codex_home.mkdir()
    (codex_home / 'auth.json').write_text('{"synthetic": true}')
    (codex_home / 'AGENTS.md').write_text('user instructions')
    record = probe('codex-cli-worker', install(cli, 'codex'))
    qualification_record('codex-cli-worker', record)
    preferences(cli, 'codex-cli-worker', model='gpt-fixture')
    s = spec(cli, transport='codex-cli-worker')
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    home = Path(d['transport']['launch_env']['CODEX_HOME'])
    assert sorted(p.name for p in home.iterdir()) == ['auth.json', 'config.toml']
    assert '[mcp_servers.ravel]' in (home / 'config.toml').read_text()
    assert d['argv'][-1] == '-' and d['argv'][d['argv'].index('--cd') + 1] == str(ws)
    assert json.loads(Path(d['argv'][d['argv'].index('--output-schema') + 1]).read_text())['required'] == [
        'completed', 'summary']
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        s2 = spec(cli, transport='codex-cli-worker', attempt=2, cost=1.0)
        cli_worker.prepare_launch(cli / 'run', s2, worker.materialize(cli / 'run', s2))
    assert refused.value.missing == ['cost_unenforceable']
    cli_worker.remove_home(ws, d)
    assert not home.parent.exists()


def test_observe_parses_session_turns_cost_and_enforces_limits(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    isolation = {'profile': 'ravel-sandbox', 'user_configuration_loaded': False, 'evidence': {'confirmed': True}}
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '', 'session_id': 'sess-observe',
                'num_turns': 4, 'total_cost_usd': 0.05, 'usage': {'input_tokens': 10, 'output_tokens': 5},
                'modelUsage': {'claude-observed': {'outputTokens': 5}},
                'structured_output': {'completed': True, 'summary': 'done'}}
    captured = worker.capture_path(cli / 'run', s['node_id'], s['attempt'], 'stdout')
    captured.write_text(json.dumps(envelope))
    seen = cli_worker.observe(cli / 'run', d, ws, s, {'exit_status': 0, 'isolation': isolation})
    assert seen['final'] == {'completed': True, 'summary': 'done'} and seen['session_id'] == 'sess-observe'
    assert seen['usage'] == {'input_tokens': 10, 'output_tokens': 5, 'cost_usd': 0.05, 'reported': True, 'turns': 4}
    assert seen['model']['observed'] == 'claude-observed' and seen['attestation'] == 'transport_attested'
    assert 'budget_exhausted' not in seen
    captured.write_text(json.dumps({**envelope, 'num_turns': 9}))
    seen = cli_worker.observe(cli / 'run', d, ws, s, {'exit_status': 0, 'isolation': isolation})
    assert seen['budget_exhausted'] is True and seen['transport']['observation']['limits']['turns']['within'] is False
    captured.write_text(json.dumps({**envelope, 'is_error': True}))
    seen = cli_worker.observe(cli / 'run', d, ws, s, {'exit_status': 0, 'isolation': isolation})
    assert seen['final'] is None and seen['attestation'] == 'host_attested' and seen['budget_exhausted'] is True
    assert 'envelope:exit' in seen['transport']['observation']['attestation_reasons']
    captured.write_text(json.dumps(envelope))
    loaded = cli_worker.observe(cli / 'run', d, ws, s, {'exit_status': 0, 'isolation': {**isolation,
                                                                                        'user_configuration_loaded': True}})
    assert loaded['attestation'] == 'host_attested'


def test_observe_reads_only_the_supervisor_capture_never_the_workspace(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    captured = worker.capture_path(cli / 'run', s['node_id'], s['attempt'], 'stdout')
    assert not captured.is_relative_to(ws.parent) and not captured.is_relative_to(cli / 'run')
    forged = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '', 'session_id': 'forged',
              'num_turns': 1, 'usage': {'input_tokens': 1, 'output_tokens': 1},
              'structured_output': {'completed': True, 'summary': 'forged'}}
    for name in ('stdout', 'last-message.json'):
        (ws / 'scratch' / name).write_text(json.dumps(forged))
    seen = cli_worker.observe(cli / 'run', d, ws, s, {'exit_status': 0, 'isolation': {}})
    assert seen['session_id'] is None and seen['final'] is None
    assert '--output-last-message' not in tr.load('codex-cli-worker')['argv_template']


@pytest.mark.parametrize('files,admitted', [
    ({'settings.json': '{"theme": "dark"}'}, True),
    ({'plugins/known_marketplaces.json': '{}', 'plugins/marketplaces/catalog/marketplace.json': '{}'}, True),
    ({'settings.json': '{"theme": "dark"}', 'plugins/known_marketplaces.json': '{}',
      'plugins/marketplaces/catalog/README.md': 'x'}, True),
    ({'settings.json': '{"theme": "dark", "hooks": {}}'}, False),
    ({'settings.json': '{"env": {"X": "1"}}'}, False),
    ({'settings.json': '{"permissions": {"allow": ["Bash"]}}'}, False),
    ({'settings.json': '{"enabledPlugins": {"x@y": true}}'}, False),
    ({'plugins/installed_plugins.json': '{}'}, False),
    # An interactive login writes the plugin record with nothing installed.
    ({'plugins/installed_plugins.json': '{"version": 2, "plugins": {}}', 'plugins/known_marketplaces.json': '{}',
      'plugins/synced/org-0000-synthetic/manifest.json': '{}'}, True),
    ({'plugins/installed_plugins.json': '{"version": 2, "plugins": {"x@y": [{"scope": "user"}]}}'}, False),
    ({'plugins/installed_plugins.json': '{"version": 2, "plugins": {}, "enabled": true}'}, False),
    ({'plugins/installed_plugins.json': '{"version": 2, "plugins": []}'}, False),
    ({'plugins/installed_plugins.json': 'not json'}, False),
    ({'plugins/synced/org-0000-synthetic/installed_plugins.json': '{"version": 2, "plugins": {}}'}, False),
    ({'plugins/known_marketplaces.json': '{}', 'plugins/cache/x/plugin.json': '{}'}, False),
    ({'plugins/marketplaces/catalog/installed_plugins.json': '{}'}, False),
    # Account sync writes skills/synced/<org>/<skill>/ and plugins/synced/<org>/ on every real login.
    ({'skills/synced/org-0000-synthetic/example-skill/SKILL.md': 'x',
      'plugins/synced/org-0000-synthetic/manifest.json': '{}', 'plugins/known_marketplaces.json': '{}',
      'plugins/marketplaces/catalog/marketplace.json': '{}', 'settings.json': '{"theme": "dark"}'}, True),
    ({'skills/synced/org-0000-synthetic/example-skill/SKILL.md': 'x',
      'skills/own-skill/SKILL.md': 'x'}, False),
    ({'skills/SKILL.md': 'x'}, False),
    ({'skills/synced': 'a file, not the synced folder'}, False),
    ({'plugins/synced/org-0000-synthetic/installed_plugins.json': '{}'}, False),
    ({'plugins/synced/org-0000-synthetic/manifest.json': '{}', 'plugins/cache/x/plugin.json': '{}'}, False),
    ({'skills/synced/org-0000-synthetic/example-skill/SKILL.md': 'x', 'agents/a.md': 'x'}, False),
    ({'commands/c.md': 'x'}, False),
    ({'output-styles/o.md': 'x'}, False),
    ({'hooks/h.json': '{}'}, False),
    ({'settings.json': '{"theme": "dark", "skills": {}}'}, False),
])
def test_login_folder_admits_what_a_real_login_creates_and_nothing_else(cli, monkeypatch, files, admitted):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    for rel, text in files.items():
        target = cli / 'claude-login' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    if admitted:
        assert cli_worker.prepare_launch(cli / 'run', s, ws)['transport']['cli_home'] == str(cli / 'claude-login')
    else:
        with pytest.raises(cli_worker.LaunchRefused) as refused:
            cli_worker.prepare_launch(cli / 'run', s, ws)
        assert refused.value.missing == ['claude_config_dir:user-configuration']


def test_login_folder_refuses_links_inside_the_synced_folders(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    elsewhere = cli / 'elsewhere'
    elsewhere.mkdir()
    synced = cli / 'claude-login/skills/synced/org-0000-synthetic'
    synced.mkdir(parents=True)
    (synced / 'example-skill').symlink_to(elsewhere, target_is_directory=True)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert refused.value.missing == ['claude_config_dir:user-configuration']
    (synced / 'example-skill').unlink()
    (cli / 'claude-login/plugins').symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(cli_worker.LaunchRefused):
        cli_worker.prepare_launch(cli / 'run', s, ws)


def test_claude_launch_points_its_temporary_directory_at_private_scratch(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    env = d['transport']['launch_env']
    assert env['CLAUDE_CODE_TMPDIR'] == env['TMPDIR'] == str(ws / 'scratch/tmp') and (ws / 'scratch/tmp').is_dir()
    assert worker._cli_launch(d, ws)[3] == env


def test_descriptor_pins_the_toolbelt_the_supervisor_enforces(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws)
    pin = d['transport']['toolbelt']
    assert pin['path'] == str(ws / 'inputs/toolbelt.json')
    tools = worker._worker_tools(d, ws, d['allowed_actions'])
    assert [t['name'] for t in tools] == [t['name'] for t in json.loads((ws / 'inputs/toolbelt.json').read_text())['tools']]
    with pytest.raises(ValueError, match='allowlist'):
        worker._worker_tools(d, ws, sorted(set(d['allowed_actions']) | {'write', 'board read'}))


def test_a_toolbelt_error_at_dispatch_is_a_typed_refusal(cli, monkeypatch):
    from ravel.workflow import toolbelt
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)

    def broken(*args, **kwargs):
        raise toolbelt.ToolbeltError('check check:synthetic has no atlas row')
    monkeypatch.setattr(cli_worker, 'toolbelt_for', broken)
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert refused.value.missing == ['toolbelt'] and 'no atlas row' in str(refused.value)


def test_codex_launch_has_no_native_writes_and_runs_without_an_effort(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    (cli / 'home/.codex').mkdir()
    record = probe('codex-cli-worker', install(cli, 'codex'))
    qualification_record('codex-cli-worker', record)
    preferences(cli, 'codex-cli-worker', model='gpt-fixture')
    assert record['capabilities_confirmed']['effort_control'] is True
    s = spec(cli, transport='codex-cli-worker')
    ws = worker.materialize(cli / 'run', s)
    d = cli_worker.prepare_launch(cli / 'run', s, ws, selection={
        'transport_id': 'codex-cli-worker', 'model': 'gpt-fixture', 'effort': None, 'probe_sha256': tr.digest(record)})
    assert d['argv'][d['argv'].index('--sandbox') + 1] == 'read-only' and '-c' not in d['argv']
    s2 = spec(cli, transport='codex-cli-worker', attempt=2)
    d2 = cli_worker.prepare_launch(cli / 'run', s2, worker.materialize(cli / 'run', s2), selection={
        'transport_id': 'codex-cli-worker', 'model': 'gpt-fixture', 'effort': 'high', 'probe_sha256': tr.digest(record)})
    assert d2['argv'][d2['argv'].index('-c') + 1] == 'model_reasoning_effort="high"'


def test_codex_turns_count_turns_not_completed_items():
    lines = [{'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
             *[{'type': 'item.completed', 'item': {'type': 'reasoning'}}] * 3, {'type': 'turn.completed', 'usage': {}}]
    assert cli_worker._turns('codex', {}, '\n'.join(json.dumps(x) for x in lines)) == 1


# ------------------------------------------------------------------ selection (T-M1 and the owner decision)

def _synthetic_probe(document, sha='5' * 64):
    return {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
            'declaration_sha256': tr.declaration_sha256(document), 'cli_version': 'synthetic', 'help_sha256': '0' * 64,
            'flags': {flag: 'confirmed' for flag in tr.template_flags(document)},
            'capabilities_confirmed': {k: bool(document['capabilities'][k]) for k in tr.BOOLEAN_CAPABILITIES},
            'unusable': [], 'probed_utc': '2026-10-11T00:00:00Z', 'executable_path': '/synthetic/cli',
            'executable_sha256': sha, 'exit_status': 0}


def _select(card, route, probes):
    prefs = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: [route]},
             'tier_models': {'judgment': {route: 'claude-fixture-model'}}}
    return tr.select(card, prefs, probes=probes, executables={route: '5' * 64})


@pytest.mark.parametrize('role', ['physics-critic', 'physics-decider', 'skeptical-verifier'])
def test_voting_roles_on_the_sandbox_worker_miss_only_qualification(cli, monkeypatch, role):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    card = role_registry.load(role)
    worker_probe = _synthetic_probe(tr.load('claude-cli-worker'))
    with pytest.raises(tr.TransportRefusal) as refused:
        _select(card, 'claude-cli-worker', {'claude-cli-worker': worker_probe})
    assert refused.value.missing == ['qualification']
    # Once a live qualification record binds this probe, the voting role is admitted on the worker.
    qualification_record('claude-cli-worker', worker_probe)
    assert _select(card, 'claude-cli-worker', {'claude-cli-worker': worker_probe})['transport_id'] == 'claude-cli-worker'
    # A one-shot under the CLI's own policy is refused for a voting role, qualified or not.
    oneshot_probe = _synthetic_probe(tr.load('claude-cli-oneshot'))
    qualification_record('claude-cli-oneshot', oneshot_probe)
    with pytest.raises(tr.TransportRefusal) as refused:
        _select(card, 'claude-cli-oneshot', {'claude-cli-oneshot': oneshot_probe})
    assert 'isolation' in refused.value.missing


def test_qualification_record_counts_only_for_its_probe_and_executable(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos')
    document = tr.load('claude-cli-worker')
    first = _synthetic_probe(document)
    qualification_record('claude-cli-worker', first)
    assert tr.qualification_status(document, first) == 'live_qualified'
    assert tr.qualification_status(document, _synthetic_probe(document, sha='6' * 64)) == 'declared'
    assert tr.qualification_status(document, None) == 'declared'
    path = tr.qualification_path('claude-cli-worker')
    path.write_text(json.dumps({**json.loads(path.read_text()), 'status': 'probed'}))
    assert tr.qualification_status(document, first) == 'declared'


# ------------------------------------------------------------------ live path with a fake CLI in the real sandbox

def test_dispatch_runs_the_fake_cli_in_the_sandbox_through_the_broker_mcp_face(cli, monkeypatch):
    import pwd
    real_sandbox_or_skip(cli)
    monkeypatch.setenv('USER', 'parent-spoofed-user')
    monkeypatch.setenv('LOGNAME', 'parent-spoofed-user')
    ready(cli)
    s = spec(cli)
    receipt = worker.dispatch(cli / 'run', s)
    ws = worker.workspace(cli / 'run', s['node_id'], s['attempt'])
    assert receipt['status'] == 'ok', receipt['failure']
    assert receipt['session_id'] == 'sess-1' and receipt['attestation'] == 'transport_attested'
    assert receipt['usage'] == {'input_tokens': 100, 'output_tokens': 20, 'cost_usd': 0.0123, 'reported': True,
                                'turns': 3}
    assert receipt['model']['observed'] == 'claude-fixture-model' and receipt['cli_version'] == 'fake-cli 9.9.9'
    assert receipt['isolation']['user_configuration_loaded'] is False
    assert receipt['isolation']['evidence']['confirmed'] is True
    assert receipt['isolation']['evidence']['network'] == 'tcp-443'
    assert receipt['isolation']['evidence']['computed_checks']['other_port_denied'] is True
    assert receipt['isolation']['evidence']['cli_home'] is True
    assert receipt['isolation']['evidence']['login_keychain'] is (sandbox.available() == 'macos')
    assert not sandbox.user_home_for(ws).exists()
    assert (ws / 'outputs/conformance.txt').read_text() == 'n-0123456789'
    calls = [broker.verify_broker_receipt(cli / 'run', {'path': r['record']['path'], 'sha256': r['record']['sha256']},
                                          verify_outputs=False) for r in broker.ledger(cli / 'run', 'broker')]
    assert [c['action'] for c in calls] == ['read', 'write'] and all(c['status'] == 'ok' for c in calls)
    seen = json.loads((ws / 'scratch/seen.json').read_text())
    assert seen['config_dir'] == str(broker.ordinary(cli / 'claude-login'))
    account = pwd.getpwuid(os.getuid()).pw_name
    assert seen['user'] == account and seen['logname'] == account
    assert receipt['pass_env_names'] == ['CLAUDE_CONFIG_DIR', 'LOGNAME', 'USER']
    assert 'ANTHROPIC_API_KEY' not in seen['env'] and 'PYTHONPATH' not in seen['env']
    assert 'outputs/conformance.txt' in seen['prompt']


def test_real_supervisor_gates_every_call_and_credits_only_broker_outputs(cli):
    real_sandbox_or_skip(cli)
    ready(cli)
    (cli / 'bin/mode.txt').write_text('gate_probe')
    s = spec(cli)
    receipt = worker.dispatch(cli / 'run', s)
    ws = worker.workspace(cli / 'run', s['node_id'], s['attempt'])
    calls = [broker.verify_broker_receipt(cli / 'run', {'path': r['record']['path'], 'sha256': r['record']['sha256']},
                                          verify_outputs=False) for r in broker.ledger(cli / 'run', 'broker')]
    by_action = {c['action']: c for c in calls}
    # Unlisted names never alias an allowed action: neither ws_read's action nor the knowledge action.
    assert by_action['tool:read']['status'] == 'refused'
    assert by_action['tool:knowledge query']['reply']['error']['code'] == 'not_allowlisted'
    assert by_action['knowledge query']['status'] == 'ok'  # knowledge_find, in the one {op, args} shape
    assert json.loads((ws / 'scratch/found.json').read_text())['status'] == 'ok'
    # The output exists, written natively, but no broker receipt pins it: it is not credited.
    assert (ws / 'outputs/conformance.txt').read_text() == 'n-0123456789'
    assert receipt['credited_outputs'] == [] and receipt['outcome']['computed_checks']['declared_outputs'] is False
    assert receipt['status'] == 'failed'
    assert not (ws / 'scratch/stdout').exists()


def test_dispatch_over_turn_budget_fails_and_a_reused_session_is_not_transport_attested(cli):
    real_sandbox_or_skip(cli)
    ready(cli)
    (cli / 'bin/mode.txt').write_text('over_turns')
    over = worker.dispatch(cli / 'run', spec(cli))
    assert over['status'] == 'failed' and over['outcome']['computed_checks']['budgets'] is False
    (cli / 'bin/mode.txt').write_text('ok')
    again = worker.dispatch(cli / 'run', spec(cli, attempt=2))
    assert again['status'] == 'ok' and again['attestation'] == 'host_attested'  # same CLI session id as attempt 1


def test_qualify_writes_the_record_only_when_every_step_passed(cli, capsys):
    real_sandbox_or_skip(cli)
    probe('claude-cli-worker', install(cli, 'claude'))
    (cli / 'bin/mode.txt').write_text('skip_write')
    with pytest.raises(cli_worker.QualificationFailed) as failed:
        cli_worker.qualify('claude-cli-worker', rundir=cli / 'q1', model='claude-fixture-model')
    # The surface reply is still written through the broker; the nonce output and the receipt fail.
    assert failed.value.failed == ['receipt_ok', 'output_nonce']
    assert not tr.qualification_path('claude-cli-worker').exists()
    (cli / 'bin/mode.txt').write_text('ok')
    (cli / 'bin/session.txt').write_text('sess-qualify')
    status = tr.main(['qualify', 'claude-cli-worker', '--rundir', str(cli / 'q2'), '--model', 'claude-fixture-model'])
    assert status == 0, capsys.readouterr().out
    record = json.loads(tr.qualification_path('claude-cli-worker').read_text())
    assert record['status'] == 'live_qualified' and set(record) == tr.QUALIFICATION_RECORD_KEYS
    assert record['executable_sha256'] == tr.read_probe('claude-cli-worker')['executable_sha256']
    assert record['probe_sha256'] == tr.digest(tr.read_probe('claude-cli-worker'))
    receipt = json.loads(Path(record['receipt']['path']).read_text())
    assert record['receipt']['digest'] == broker.digest(receipt) and all(s['passed'] for s in record['steps'])
    assert Path(record['record_path']).is_relative_to(cli / 'state')
    assert tr.qualification_status(tr.load('claude-cli-worker'), tr.read_probe('claude-cli-worker')) == 'live_qualified'
    assert tr.main(['qualify', 'claude-cli-worker', '--rundir', str(cli / 'q2'), '--model', 'm']) == 3  # not empty
    # The worker was asked to list its skills and tools; it named only the RAVEL MCP tools.
    surface = record['observed']['surface']
    reply = Path(record['rundir']) / 'agent-work'
    assert surface['request'] == cli_worker.SURFACE_REQUEST and surface['unexpected'] == []
    assert surface['names'] and all(n.startswith('mcp__ravel__') for n in surface['names'])
    assert {'step': 'surface_ravel_only', 'passed': True} in record['steps']
    replies = [p for p in reply.rglob('outputs/surface.txt')]
    assert len(replies) == 1 and surface['reply_sha256'] == broker.sha(replies[0])


def test_qualify_fails_when_the_worker_names_a_skill_or_tool_beyond_the_ravel_tools(cli):
    real_sandbox_or_skip(cli)
    probe('claude-cli-worker', install(cli, 'claude'))
    (cli / 'bin/mode.txt').write_text('skills_leak')
    with pytest.raises(cli_worker.QualificationFailed) as failed:
        cli_worker.qualify('claude-cli-worker', rundir=cli / 'q', model='claude-fixture-model')
    assert failed.value.failed == ['surface_ravel_only']
    assert not tr.qualification_path('claude-cli-worker').exists()


def test_probe_requires_restricted_for_claude_workers(cli):
    path = install(cli, 'claude')
    help_file = cli / 'bin' / 'help.txt'
    help_file.write_text(help_file.read_text().replace('--restricted <x>\n', '').replace('  --restricted <x>', ''))
    record = tr.probe('claude-cli-worker', executable=str(path))
    assert record['flags']['--restricted'] == 'missing' and '--restricted' in record['unusable']


def test_surface_ravel_only_step_needs_names_and_nothing_unexpected(tmp_path):
    ws = tmp_path
    (ws / 'inputs').mkdir()
    (ws / 'inputs' / 'toolbelt.json').write_text(json.dumps({'tools': [{'name': 'mcp__ravel__ws_read'}]}))
    assert cli_worker._surface(ws)['names'] == []  # no reply: step would fail (names empty)
    reply = ws / cli_worker.SURFACE_OUTPUT
    reply.parent.mkdir(parents=True, exist_ok=True)
    reply.write_text('mcp__ravel__ws_read\n')
    s = cli_worker._surface(ws)
    assert s['names'] and s['unexpected'] == []
    reply.write_text('mcp__ravel__ws_read\nBash\n')
    assert cli_worker._surface(ws)['unexpected'] == ['Bash']


def test_surface_reply_parsing_admits_only_ravel_tool_names():
    tools = ['ws_read', 'ws_write']
    assert cli_worker.surface_names('- mcp__ravel__ws_read\n* `ws_write`\n\n', tools) == (
        ['mcp__ravel__ws_read', 'ws_write'], [])
    assert cli_worker.surface_names('mcp__ravel__ws_read\nexample-skill\nBash', tools)[1] == ['example-skill', 'Bash']
    assert cli_worker.surface_names('', tools) == ([], [])


def test_qualify_refuses_before_any_process_without_a_probe(cli, capsys):
    install(cli, 'claude')
    assert tr.main(['qualify', 'claude-cli-worker', '--rundir', str(cli / 'q'), '--model', 'claude-fixture-model']) == 3
    assert json.loads(capsys.readouterr().out)['missing'] == ['probe']
    assert not (cli / 'q').exists() or not any((cli / 'q').iterdir())


def test_surface_admits_the_cli_answer_channel_but_still_needs_a_ravel_tool(tmp_path):
    # Live evidence (Claude Code 2.1.296 with --json-schema): the worker lists StructuredOutput, the CLI's own
    # channel for the schema-bound answer, beside the RAVEL MCP tools. It cannot read, write or run anything.
    ws = tmp_path
    (ws / 'inputs').mkdir()
    (ws / 'inputs' / 'toolbelt.json').write_text(json.dumps({'tools': [{'name': 'ws_read'}, {'name': 'ws_write'}]}))
    reply = ws / cli_worker.SURFACE_OUTPUT
    reply.parent.mkdir(parents=True, exist_ok=True)
    reply.write_text('StructuredOutput\nmcp__ravel__ws_read\nmcp__ravel__ws_write\n')
    s = cli_worker._surface(ws)
    assert s['unexpected'] == [] and s['ravel'] == ['mcp__ravel__ws_read', 'mcp__ravel__ws_write']
    reply.write_text('StructuredOutput\n')
    s = cli_worker._surface(ws)
    assert s['unexpected'] == [] and s['ravel'] == []  # the answer channel alone does not pass the step
    reply.write_text('StructuredOutput\nmcp__ravel__ws_read\nBash\n')
    assert cli_worker._surface(ws)['unexpected'] == ['Bash']
