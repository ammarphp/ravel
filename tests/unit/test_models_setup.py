"""Guided model setup uses discovery only until live verification is requested."""
import json
import subprocess
from pathlib import Path

import pytest

from test_model_catalogue_cli import transports as catalogue_transports
from ravel.controller.step.seats import wired_transports as governed_inventory
from ravel.workflow import transport_registry as tr


@pytest.fixture
def transports(catalogue_transports, monkeypatch):
    """Use an actual governed worker declaration with inert executor availability."""
    from ravel.paths import package_data_path
    documents = catalogue_transports
    old = documents[-1]
    (tr.BUILTIN_DIR / (old['id'] + '.json')).unlink()
    worker = json.loads((package_data_path('transports') / 'claude-cli-worker.json').read_text())
    documents[-1] = worker
    (tr.BUILTIN_DIR / (worker['id'] + '.json')).write_text(json.dumps(worker))
    monkeypatch.setattr(tr, 'executor_problem', lambda document: None)
    monkeypatch.setattr('ravel.controller.step.seats.wired_transports', governed_inventory)
    return documents


@pytest.fixture
def operator_home(tmp_path, monkeypatch):
    from ravel.workflow.approval_authority import AGENT_MARKERS
    from ravel.controller.authority import issuer, operator
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(issuer, 'home', lambda: operator.controller_home() / 'issuer')
    return operator.controller_home()


def test_setup_yes_writes_ledger(transports, operator_home, monkeypatch, capsys):
    from ravel.setup import models_setup as setup
    from ravel.controller.authority import operator
    monkeypatch.setattr('shutil.which', lambda name, **k: '/bin/true' if name == 'claude' else None)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='auth status', stderr='')
    monkeypatch.setattr('subprocess.run', run)
    assert setup.main(['--yes']) == 0
    out = capsys.readouterr().out
    assert 'balanced' in out and 'ESTIMATED' in out and 'upper bound' in out
    prefs = operator.operator_config()['agent_preferences']
    assert prefs['tier_models']['judgment']
    assert not any('reply with' in ' '.join(argv) for argv in calls)
    assert not any('-w' in argv for argv in calls)


def test_no_provider_gives_fix(transports, monkeypatch, capsys):
    from ravel.setup import models_setup as setup
    monkeypatch.setattr('shutil.which', lambda *a, **k: None)
    monkeypatch.setattr(tr, 'resolve_executable', lambda *a, **k: (None, None))
    assert setup.main(['--yes']) == 2
    out = capsys.readouterr().out
    assert 'install' in out and 'export' in out and 'ravel setup-models' in out


def test_installer_hint():
    from ravel.setup import installer
    assert 'next: ravel setup-models  (choose the models and spending level; ravel setup-models --yes picks a balanced default)' in Path(installer.__file__).read_text()


@pytest.fixture
def offline_setup(transports, monkeypatch):
    """Keep setup controls independent of installed programs and network access."""
    from ravel.setup import models_setup as setup
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout='status private-command-output',
                                           stderr='private-command-output')

    def no_network(*args, **kwargs):
        raise AssertionError('setup must not access the network in this control')

    monkeypatch.setattr('subprocess.run', run)
    monkeypatch.setattr('shutil.which', lambda name, **kwargs: '/bin/true' if name == 'claude' else None)
    monkeypatch.setattr('urllib.request.urlopen', no_network)
    monkeypatch.setattr(setup.models, 'estimate', lambda *args, **kwargs: {})
    monkeypatch.setattr(setup.models, 'print_estimate', lambda record: None)
    return calls


def test_discovery_discards_subprocess_output(offline_setup, capsys):
    from ravel.setup import models_setup as setup
    result = setup.discover_providers()
    output = capsys.readouterr()
    assert result['clis']['claude']['login'] == 'logged_in'
    assert offline_setup
    assert 'private-command-output' not in output.out + output.err + json.dumps(result)


def test_discovery_uses_cli_status_without_credential_store_commands(offline_setup, monkeypatch, capsys):
    from ravel.setup import models_setup as setup
    monkeypatch.setattr(setup.sys, 'platform', 'darwin')
    monkeypatch.setattr('shutil.which', lambda name, **kwargs: '/bin/true' if name == 'security' else None)
    result = setup.discover_providers()
    assert offline_setup == [] and set(result) == {'clis', 'environment'}


def test_explicit_preset_skips_prompts_and_sets_budget(offline_setup, operator_home, monkeypatch):
    from ravel.setup import models_setup as setup
    from ravel.controller.authority import operator

    def no_input(*args, **kwargs):
        raise AssertionError('an explicit preset must not prompt')

    monkeypatch.setattr('builtins.input', no_input)
    assert setup.main(['--preset', 'economy', '--cost-cap-usd', '1.25']) == 0
    config = operator.operator_config()
    assert config['source'] == 'operator_ledger'
    assert config['budgets']['cost_usd'] == 1.25
    assert config['agent_preferences']['tier_models']['judgment']
    assert not any('reply with' in ' '.join(argv) for argv, _ in offline_setup)


def test_agent_setup_refusal_prints_exact_operator_command(offline_setup, operator_home, monkeypatch, capsys):
    import shlex
    from ravel.setup import models_setup as setup
    from ravel.controller.authority import operator
    monkeypatch.setenv('RAVEL_AGENT_ID', 'setup-control')
    ledger = operator.ledger_path()
    assert not ledger.exists()
    assert setup.main(['--preset', 'balanced', '--cost-cap-usd', '2', '--verify']) == 2
    record = json.loads(setup.models.detection_path().read_text())
    preferences, _, _ = setup.models.preferences('balanced', record=record)
    command = 'ravel operator set --agent-preferences ' + shlex.quote(
        json.dumps(preferences, separators=(',', ':')))
    command += ' --budget ' + shlex.quote('cost_usd=2.0')
    assert command in capsys.readouterr().out.splitlines()
    assert not ledger.exists()
    assert not any('reply with' in ' '.join(argv) for argv, _ in offline_setup)


def _verification_preferences(documents):
    from ravel.workflow import model_catalogue as mc
    document = next(row for row in documents if row['id'] == 'claude-cli-worker')
    model = next(row['id'] for row in mc.load()['models'] if row['family'] == 'anthropic')
    return {'transport_preference': [document['id']],
            'tier_models': {tier: {document['id']: model} for tier in tr.TIERS}}, model


@pytest.mark.parametrize(('observed', 'status', 'passed', 'ok'), [
    ('same', 'live_qualified', True, True),
    ('dated', 'live_qualified', True, True),
    ('sibling', 'live_qualified', True, False),
    (None, 'live_qualified', True, False),
    ('other-model', 'live_qualified', True, False),
    ('same', 'ok', True, False),
    ('same', 'live_qualified', False, False),
])
def test_live_verification_uses_qualification_only(offline_setup, transports, operator_home,
                                                  monkeypatch, capsys, observed, status, passed, ok):
    from ravel.setup import models_setup as setup
    from ravel.workflow.transports import cli_worker
    preferences, model = _verification_preferences(transports)
    calls = []
    def qualify(transport, **kwargs):
        assert '8 turns' in capsys.readouterr().out
        calls.append((transport, kwargs))
        return {'status': status, 'transport_id': transport,
                'observed': {'requested_model': model,
                             'model': model if observed == 'same' else model + '-20261019' if observed == 'dated'
                             else model + '-9' if observed == 'sibling' else observed},
                'steps': [{'step': 'receipt_ok', 'passed': passed}]}
    monkeypatch.setattr(cli_worker, 'qualify', qualify)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('no direct model subprocess'))
    assert setup.verify_models(preferences, yes=True, documents=transports) is ok
    assert len(calls) == 1 and calls[0][1]['model'] == model
    assert calls[0][1]['max_cost_usd'] is None
    record = json.loads((tr.state_dir() / 'models-setup.receipt.json').read_text())
    assert record['receipts'][0]['status'] == ('qualified' if ok else 'failed')


def test_declined_live_verification_makes_no_call(offline_setup, transports, operator_home, monkeypatch, capsys):
    from ravel.setup import models_setup as setup
    preferences, _ = _verification_preferences(transports)
    monkeypatch.setattr('builtins.input', lambda *args: 'n')
    assert setup.verify_models(preferences, documents=transports) is True
    assert not offline_setup
    assert not (tr.state_dir() / 'models-setup.receipt.json').exists()
    assert 'Live qualification skipped' in capsys.readouterr().out


def test_setup_models_spelling_dispatches_to_focused_command(monkeypatch):
    from ravel import cli
    from ravel.setup import models_setup
    calls = []
    monkeypatch.setattr(models_setup, 'main', lambda argv: calls.append(argv) or 0)
    assert cli.main(['setup', 'models', '--yes']) == 0
    assert calls == [['--yes']]


def test_verification_uses_primary_model_in_cli_usage(transports):
    from ravel.setup import models_setup as setup
    from ravel.workflow import model_catalogue as mc
    rows = [r for r in mc.load()['models'] if r['family'] == 'anthropic']
    primary, auxiliary = rows[0]['id'], rows[1]['id']
    payload = {'modelUsage': {primary: {'outputTokens': 50}, auxiliary: {'outputTokens': 1}}, 'result': 'ok'}
    assert setup._observed_model(json.dumps(payload), set(), 'claude') == primary


def test_noninteractive_candidates_are_honestly_unverified(offline_setup, operator_home, capsys):
    from ravel.setup import models_setup as setup
    assert setup.main(['--preset', 'balanced']) == 0
    out = capsys.readouterr().out
    assert 'unverified candidate' in out
    assert 'ravel transports probe' in out and '--rundir' in out and '--model' in out
    assert 'Listing does not establish qualification' in out


def test_setup_no_wired_route_explains_exclusion(offline_setup, monkeypatch, capsys):
    from ravel.controller.step import seats
    from ravel.setup import models_setup as setup
    monkeypatch.setattr(seats, 'wired_transports', lambda: {
        'wired': [], 'excluded': [{'transport': 'claude-cli-oneshot', 'reason': 'sandbox:unavailable'}], 'kinds': []})
    assert setup.main(['--preset', 'balanced']) == 2
    output = capsys.readouterr().out
    assert 'No wired governed route' in output and 'sandbox:unavailable' in output


def test_doctor_installed_unwired_is_not_ready(monkeypatch):
    from types import SimpleNamespace
    from ravel.setup.doctor import Doctor
    from ravel.controller.step import seats
    monkeypatch.setattr(seats, 'wired_transports', lambda: {'wired': [], 'excluded': [], 'kinds': []})
    doctor = SimpleNamespace(which=lambda name: '/bin/true', _probe=lambda args: (0, '2.1.296'))
    result = Doctor._agent_cli_check(doctor, {})
    assert result['status'] != 'ready'
    assert 'ravel transports probe' in result['fix'] and '--rundir' in result['fix']


@pytest.mark.parametrize('cap', ['0', '-1', 'nan', 'inf'])
def test_verification_cap_must_be_finite_positive(offline_setup, cap, capsys):
    from ravel.setup import models_setup as setup
    assert setup.main(['--preset', 'balanced', '--verification-cost-cap-usd', cap]) == 2
    assert 'finite and positive' in capsys.readouterr().out


@pytest.mark.parametrize(('cap', 'ok'), [(1.0, False), (3.0, True)])
def test_api_verification_discloses_bound_and_enforces_authorised_cap(
        offline_setup, transports, operator_home, monkeypatch, capsys, cap, ok):
    from copy import deepcopy
    from ravel.setup import models_setup as setup
    from ravel.workflow.transports import cli_worker
    documents = deepcopy(transports)
    documents[-1]['billing'] = 'api'
    preferences, model = _verification_preferences(documents)
    monkeypatch.setattr(setup.mc, 'call_bound', lambda value: {'cost_usd': 2.5})
    calls = []
    def qualify(transport, **kwargs):
        disclosure = capsys.readouterr().out
        assert 'context-full call reservation USD 2.5' in disclosure
        assert f'authorised maximum USD {cap}' in disclosure
        calls.append(kwargs)
        return {'status': 'live_qualified', 'transport_id': transport,
                'observed': {'requested_model': model, 'model': model},
                'steps': [{'step': 'receipt_ok', 'passed': True}]}
    monkeypatch.setattr(cli_worker, 'qualify', qualify)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('no direct model subprocess'))
    assert setup.verify_models(preferences, yes=True, documents=documents, cost_cap_usd=cap) is ok
    assert len(calls) == int(ok)
    if ok:
        assert calls[0]['max_cost_usd'] == cap
    else:
        assert '--verification-cost-cap-usd' in capsys.readouterr().out


def _only_setup_transport(documents, name):
    from ravel.paths import package_data_path
    document = json.loads((package_data_path('transports') / (name + '.json')).read_text())
    documents[:] = [document]
    for path in tr.BUILTIN_DIR.glob('*.json'):
        path.unlink()
    (tr.BUILTIN_DIR / (name + '.json')).write_text(json.dumps(document))
    return document


def _static_preferences(document):
    from ravel.workflow import model_catalogue as mc
    tiers, omitted = mc.tier_models('balanced', [document])
    assert not omitted
    return {'schema_version': 1, 'kind': 'agent-preferences',
            'transport_preference': [document['id']], 'tier_models': tiers}


def test_actual_google_capability_gap_fails_before_estimate_or_operator_write(
        offline_setup, transports, operator_home, monkeypatch, capsys):
    from ravel.controller.authority import operator
    from ravel.setup import models_setup as setup
    from ravel.workflow import model_catalogue as mc
    document = _only_setup_transport(transports, 'ravel-loop-gemini')
    assert document['capabilities']['effort_control'] is False
    monkeypatch.setenv(document['auth']['env_names'][0], 'private-google-fixture-key')
    monkeypatch.setattr(setup.models, '_listing', lambda *args: {
        row['id'] for row in mc.load()['models'] if row['family'] == 'google' and row['status'] == 'current'})
    monkeypatch.setattr(setup.models, 'estimate', lambda *a, **k: pytest.fail('coverage must precede estimates'))
    monkeypatch.setattr(setup.models, 'write_preferences', lambda *a, **k: pytest.fail('impossible preferences must not save'))
    assert setup.main(['--preset', 'balanced']) == 2
    output = capsys.readouterr().out
    assert 'Static capability coverage failed:' in output and 'missing: effort' in output
    assert 'required effort=high' in output and 'affected roles:' in output
    assert 'catalogue model row supporting the required tier and effort' in output
    assert 'ravel transports probe TRANSPORT_ID' in output
    assert 'private-google-fixture-key' not in output
    assert not operator.ledger_path().exists()


@pytest.mark.parametrize('transport_id', ['claude-cli-worker', 'codex-cli-worker'])
def test_actual_anthropic_and_openai_candidates_cover_effective_roles_without_qualification(
        offline_setup, transports, operator_home, monkeypatch, capsys, transport_id):
    from ravel.setup import models_setup as setup
    document = _only_setup_transport(transports, transport_id)
    monkeypatch.setattr('shutil.which', lambda name, **kwargs: '/bin/true' if name == document['launcher'] else None)
    assert setup.main(['--preset', 'balanced']) == 0
    output = capsys.readouterr().out
    assert 'Static capability coverage:' in output and 'registered roles have a suitable configured candidate' in output
    assert 'unverified candidate' in output and 'live qualification remains required' in output
    assert not any('exec' in argv or '-p' in argv for argv, _ in offline_setup)


def test_static_google_maximum_effort_reports_both_transport_and_catalogue_facts(
        transports, monkeypatch):
    from copy import deepcopy
    from ravel.setup import models_setup as setup
    from ravel.workflow import role_registry
    document = _only_setup_transport(transports, 'ravel-loop-gemini')
    card = deepcopy(next(c for c in role_registry.all_cards() if c['model']['tier'] == 'judgment'))
    card['model']['effort'] = 'max'
    monkeypatch.setattr(role_registry, 'all_cards', lambda: [card])
    result = setup.static_role_coverage(_static_preferences(document), [document])
    assert len(result['uncovered']) == 1 and not result['covered']
    candidate = result['uncovered'][0]['candidates'][0]
    assert {'effort', 'model:effort'} <= set(candidate['missing'])
    assert candidate['effort'] == card['model']['effort'] == 'max'


def test_static_cheap_candidate_without_required_effort_falls_back_to_card_tier(transports, monkeypatch):
    from copy import deepcopy
    from ravel.setup import models_setup as setup
    from ravel.workflow import model_catalogue as mc, role_registry
    document = transports[-1]
    card = deepcopy(next(c for c in role_registry.all_cards()
                         if c['model'].get('cheap_ok') and c['model']['tier'] != 'cheap'))
    card['model']['effort'] = 'max'
    mc.adopt('claude-fixture-cheap-no-effort', family='anthropic', class_='small', tiers=['cheap'])
    preferences = _static_preferences(document)
    preferences['tier_models']['cheap'][document['id']] = 'claude-fixture-cheap-no-effort'
    monkeypatch.setattr(role_registry, 'all_cards', lambda: [card])
    monkeypatch.setattr(tr, 'read_probe', lambda *a: pytest.fail('static coverage needs no probe'))
    monkeypatch.setattr(tr, 'qualification_path', lambda *a: pytest.fail('static coverage needs no qualification custody'))
    result = setup.static_role_coverage(preferences, [document])
    assert not result['uncovered']
    chosen = result['covered'][card['id']]
    assert chosen['tier'] == card['model']['tier'] and chosen['effort'] == 'max'
    assert chosen['model'] == preferences['tier_models'][card['model']['tier']][document['id']]


def test_static_model_tier_gap_is_not_mislabelled_as_missing_qualification(transports, monkeypatch):
    from ravel.setup import models_setup as setup
    from ravel.workflow import model_catalogue as mc, role_registry
    document = transports[-1]
    card = next(c for c in role_registry.all_cards() if c['model']['tier'] == 'judgment')
    preferences = _static_preferences(document)
    small = next(row['id'] for row in mc.load()['models'] if row['family'] == 'anthropic'
                 and row['class'] == 'small' and row['status'] == 'current')
    preferences['tier_models']['judgment'][document['id']] = small
    monkeypatch.setattr(role_registry, 'all_cards', lambda: [card])
    result = setup.static_role_coverage(preferences, [document])
    missing = result['uncovered'][0]['candidates'][0]['missing']
    assert 'model:tier' in missing and 'qualification' not in missing


def test_interactive_setup_keeps_three_questions(offline_setup, operator_home, monkeypatch):
    from ravel.setup import models_setup as setup
    answers = iter(['balanced', '', ''])
    questions = []
    def answer(prompt):
        questions.append(prompt)
        return next(answers)
    monkeypatch.setattr('builtins.input', answer)
    assert setup.main([]) == 0
    assert len(questions) == 3
