"""Current installed peer sources exercised through inert qualification call paths.

No provider, sandbox, network, executable probe or native process is started.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

from ravel.workflow import agent_worker, broker, gate_wiring, knowledge_broker
from ravel.workflow import review_context, review_independence, transport_registry as tr
from test_p13_blind_transport import BLIND_CARDS, Store, transport  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
PEERS = ('transports/cli_worker.py', 'tool_gate.py', 'toolbelt.py', 'agent_worker.py')


@pytest.fixture
def peers(tmp_path, monkeypatch):
    """Copy the installed source bytes so the controls follow the current implementation."""
    copied = tmp_path / 'copied'
    for name in PEERS:
        source = ROOT / 'src/ravel/workflow' / name
        target = copied / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    config = Path('src/ravel/data/transports/claude-cli-worker.json')
    (copied / config).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / config, copied / config)
    def load(name, relative):
        path = copied / 'src/ravel/workflow' / relative
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    return (load('ravel.workflow.transports._p13_cli', 'transports/cli_worker.py'),
            load('ravel.workflow._p13_gate', 'tool_gate.py'),
            load('ravel.workflow._p13_belt', 'toolbelt.py'), copied)


@pytest.fixture
def step_seats():
    from ravel.controller.step import seats
    from ravel.controller.step.services import StepHold
    return seats, StepHold


@pytest.fixture
def conformance(peers, transport, tmp_path, monkeypatch):
    """Supply observed conformance outcomes; qualify itself constructs its record."""
    cli = peers[0]
    document, probe, _, preferences = transport
    store = Store()
    controlled = tmp_path / 'controlled'
    controlled.mkdir()
    (controlled / 'inputs').mkdir()
    (controlled / 'inputs/agent_preferences.json').write_text(json.dumps(preferences))
    monkeypatch.setattr(review_independence, 'controller_store',
                        lambda run: store if Path(run) == controlled else None)
    monkeypatch.setattr(cli, 'unsupported', lambda doc: None)
    monkeypatch.setattr(cli, 'current_probe', lambda *args: (probe, '/synthetic/cli', 'f' * 64))
    monkeypatch.setattr(tr, 'resolve_executable', lambda doc: ('/synthetic/cli', 'f' * 64))
    monkeypatch.setattr(tr, 'read_probe', lambda ident: probe)
    monkeypatch.setattr(gate_wiring, 'initialize_steering', lambda *args, **kwargs: None)
    observed = {'nonce_ok': True, 'surface_ok': True, 'launches': 0}

    def materialize(run, spec):
        ws = run / 'inert-worker'
        (ws / 'outputs').mkdir(parents=True)
        return ws

    def prepare(run, spec, ws, **kwargs):
        # Conformance has a separate, unblinded role and an explicit trusted selection.
        assert kwargs['card']['requires']['blind'] is False
        assert kwargs['selection']['transport_id'] == document['id']
        return {'synthetic': True}

    def launch(run, spec, *, launch_spec):
        observed['launches'] += 1
        ws = run / 'inert-worker'
        nonce = json.loads((run / cli.CONFORMANCE_INPUT).read_text())['nonce']
        (ws / cli.CONFORMANCE_OUTPUT).write_text(nonce if observed['nonce_ok'] else 'wrong nonce')
        receipt = {'status': 'ok', 'final_record': {'valid': True}, 'session_id': 'inert-new-session',
                   'isolation': {'evidence': {'confirmed': True}, 'user_configuration_loaded': False},
                   'attestation': 'transport_attested', 'model': {'observed': 'claude-synthetic-reviewer'},
                   'usage': {}}
        (ws / 'receipt.json').write_text(json.dumps(receipt))
        return receipt

    monkeypatch.setattr(agent_worker, 'materialize', materialize)
    monkeypatch.setattr(cli, 'prepare_launch', prepare)
    monkeypatch.setattr(agent_worker, 'launch', launch)
    monkeypatch.setattr(broker, 'ledger', lambda *args: [
        {'record': {'path': action, 'sha256': 'a' * 64, 'node_id': 'qualify.conformance', 'attempt': 1}}
        for action in ('read', 'write')])
    monkeypatch.setattr(broker, 'verify_broker_receipt',
                        lambda run, pin, **kwargs: {'action': pin['path'], 'status': 'ok'})
    monkeypatch.setattr(cli, '_surface', lambda ws: {'ravel': ['mcp__ravel__ws_read'],
                        'unexpected': [] if observed['surface_ok'] else ['unrestricted_shell']})
    return cli, store, controlled, observed


@pytest.mark.parametrize('card', BLIND_CARDS, ids=lambda card: card['id'])
def test_G03_all_blind_cards_use_full_controller_qualification(peers, conformance, step_seats, transport, card, tmp_path):
    cli, store, run, observed = conformance
    spec = {'transport_preference': ['claude-cli-worker']}
    seats, StepHold = step_seats
    with pytest.raises(StepHold) as held:
        seats.select(card, transport[3], store=store)
    assert held.value.reason == 'transport_unavailable'
    assert 'qualification' in held.value.evidence['missing']
    with pytest.raises(cli.LaunchRefused) as missing:
        cli._select(run, spec, card)
    assert 'qualification' in missing.value.missing
    assert observed['launches'] == 0
    record = cli.qualify('claude-cli-worker', rundir=tmp_path / 'qualification',
                         model='claude-synthetic-reviewer', controller_rundir=run)
    assert tr.store_qualifications(store) == {tr.digest(record): record}
    assert len(store.scan(tr.QUALIFICATION_KIND)) == 1
    assert cli._select(run, spec, card)['transport_id'] == 'claude-cli-worker'
    assert seats.select(card, transport[3], store=store)['transport_id'] == 'claude-cli-worker'


@pytest.mark.parametrize('failure', ['nonce_ok', 'surface_ok'])
def test_SW09_failed_conformance_never_records_controller_acceptance(conformance, tmp_path, failure):
    cli, store, run, observed = conformance
    observed[failure] = False
    with pytest.raises(cli.QualificationFailed):
        cli.qualify('claude-cli-worker', rundir=tmp_path / 'qualification', model='claude-synthetic-reviewer',
                    controller_rundir=run)
    assert store.scan(tr.QUALIFICATION_KIND) == []
    assert not tr.qualification_path('claude-cli-worker').exists()


def test_SW09_unknown_or_unreadable_controller_fails_before_launch(conformance, tmp_path, monkeypatch):
    cli, store, run, observed = conformance
    qualification = tmp_path / 'qualification'
    with pytest.raises(cli.LaunchRefused):
        cli.qualify('claude-cli-worker', rundir=qualification, model='claude-synthetic-reviewer',
                    controller_rundir=tmp_path / 'unowned')
    assert not qualification.exists() and observed['launches'] == 0

    def unavailable(run):
        raise OSError('controller store unavailable')
    monkeypatch.setattr(review_independence, 'controller_store', unavailable)
    with pytest.raises(OSError):
        cli._select(run, {'transport_preference': ['claude-cli-worker']}, BLIND_CARDS[0])
    with pytest.raises(OSError):
        cli.qualify('claude-cli-worker', rundir=qualification, model='claude-synthetic-reviewer',
                    controller_rundir=run)
    assert not qualification.exists() and store.scan(tr.QUALIFICATION_KIND) == []


def test_SW09_legacy_conformance_keeps_the_same_user_record(conformance, tmp_path):
    cli, store, _, _ = conformance
    record = cli.qualify('claude-cli-worker', rundir=tmp_path / 'legacy', model='claude-synthetic-reviewer')
    assert json.loads(tr.qualification_path('claude-cli-worker').read_text()) == record
    assert store.scan(tr.QUALIFICATION_KIND) == []


def test_G03_review_reader_binds_packet_and_enforces_existing_page_bounds(peers, tmp_path, monkeypatch):
    _, gate, belt, _ = peers
    monkeypatch.setattr(gate, 'toolbelt', belt)
    class InertBroker:
        def __init__(self):
            self.actions = {}
        def register(self, name, handler, **options):
            assert options['read_only'] is True
            self.actions[name] = handler
    monkeypatch.setattr(knowledge_broker, 'create', lambda *args, **kwargs: InertBroker())
    packet = {'path': str(tmp_path / 'trusted-packet'), 'manifest_sha256': 'a' * 64}
    seen = []
    def artifact(path, artifact_id, *, expected_manifest_sha256):
        seen.append((path, artifact_id, expected_manifest_sha256))
        return b'0123456789'
    monkeypatch.setattr(review_context, 'read_artifact', artifact)
    tool = {'name': 'review_read', 'executes_through': {'action': 'review-context read'}}
    made = gate.production_broker(tmp_path, tmp_path, tools=[tool], role='fictional',
        node_id='fictional', attempt=1, max_calls=4, review_packet=packet)
    handler = made.actions['review-context read']
    packet['path'] = '/changed-after-registration'
    result = json.loads(handler({'artifact_id': 'A1', 'offset': 2, 'max_bytes': 3})['stdout'])
    assert result['content'] == '234' and result['bytes'] == 3 and result['next_offset'] == 5
    assert seen == [(str(tmp_path / 'trusted-packet'), 'A1', 'a' * 64)]
    for bad in ({'artifact_id': 'A1', 'path': '/private'}, {'artifact_id': 'A1', 'max_bytes': 65537},
                {'artifact_id': 'A1', 'offset': -1}):
        with pytest.raises(ValueError):
            handler(bad)
    absent = gate.production_broker(tmp_path, tmp_path, tools=[tool], role='fictional',
                                    node_id='fictional', attempt=1, max_calls=4)
    with pytest.raises(ValueError):
        absent.actions['review-context read']({'artifact_id': 'A1'})
    assert 'review-context read' in belt.EXECUTABLE_ACTIONS


def test_G03_restricted_declaration_probe_confirms_actual_template_flags(peers, transport):
    document = json.loads((peers[3] / 'src/ravel/data/transports/claude-cli-worker.json').read_text())
    probe = deepcopy(transport[1])
    probe['declaration_sha256'] = tr.declaration_sha256(document)
    assert '--restricted' in tr.template_flags(document)
    assert '--safe-mode' not in tr.template_flags(document)
    assert tr.probe_problem(probe, document) is None
    probe['flags']['--restricted'] = 'missing'
    probe['unusable'] = ['--restricted']  # the probe's help-derived missing-flag record
    capabilities, reasons = tr.effective_capabilities(document, probe)
    assert capabilities is None and 'probe:--restricted' in reasons


def test_SW09_qualify_cli_passes_the_operator_target(peers, tmp_path, monkeypatch, capsys):
    cli = peers[0]
    seen = []
    def qualify(transport_id, **kwargs):
        seen.append((transport_id, kwargs))
        return {'synthetic': True}
    monkeypatch.setattr(cli, 'qualify', qualify)
    assert cli.main(['claude-cli-worker', '--rundir', str(tmp_path / 'empty'),
                     '--controller-rundir', str(tmp_path / 'controlled'),
                     '--model', 'claude-synthetic-reviewer']) == 0
    assert seen[0][1]['controller_rundir'] == tmp_path / 'controlled'
    assert seen[0][1]['rundir'] == tmp_path / 'empty'
    assert json.loads(capsys.readouterr().out) == {'synthetic': True}
