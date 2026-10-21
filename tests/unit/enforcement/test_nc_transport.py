"""Transport rows: a controller seat goes only to an installed, operator-qualified, seat-capable route.

The adversary prefers a relay or host route for a seat, writes its own ``live_qualified`` record,
adds a transport declaration through the environment, or relies on the old family refusal. Oracles
are controller-mode selection (``transport_registry.select(..., controller=True)``); positive
controls select the restricted CLI worker whose qualification the operator registered.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nc_adversary import InstalledWorker, sandbox_or_skip
from nc_cases import CONTROLLER, case, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, constant, register

TRANSPORT = 'claude-cli-worker'
MODEL = 'claude-fixture-model'


def _preferences(card, order):
    from ravel.workflow import transport_registry as tr
    return {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card.get('family'): list(order)},
            'tier_models': {tier: {transport: MODEL for transport in order} for tier in tr.TIERS},
            'model_families': {}}


def _qualified(nc):
    """Execute the installed live qualifier against the inert, MCP-speaking executable."""
    from ravel.workflow import broker, transport_registry as tr
    from ravel.workflow.transports import cli_worker
    worker = InstalledWorker(nc, qualified=False)
    worker.scenario({'conformance': True, 'model': MODEL, 'session_id': 'nc-conformance-session',
                     'final': {'completed': True, 'summary': 'Read and wrote the conformance nonce through MCP.'}})
    sandbox_or_skip(nc)
    run = nc.root / 'live-transport-conformance'
    assert not run.exists() or not any(run.iterdir())
    record = cli_worker.qualify(TRANSPORT, rundir=run, model=MODEL)
    stored = json.loads(Path(tr.qualification_path(TRANSPORT)).read_bytes())
    assert record == stored
    assert record['status'] == 'live_qualified'
    assert set(row['step'] for row in record['steps']) >= tr.QUALIFICATION_STEPS
    assert all(row['passed'] is True for row in record['steps'])
    receipt = json.loads(Path(record['receipt']['path']).read_bytes())
    assert record['receipt']['digest'] == broker.digest(receipt)
    assert record['receipt']['sha256'] == broker.sha(Path(record['receipt']['path']))
    assert receipt['status'] == 'ok' and receipt['isolation']['evidence']['confirmed'] is True
    assert record['observed']['surface']['names'] and record['observed']['surface']['unexpected'] == []
    # This is real software conformance by a fixed inert script, not qualification of an actual model.
    nc.write_json('qualification-evidence.json', {'scope': 'inert executable software conformance',
        'record': record, 'receipt_status': receipt['status']})
    register = nc.root / 'operator' / tr.QUALIFICATION_REGISTER
    return worker, record, register


def _card(role):
    from ravel.workflow import role_registry
    return role_registry.load(role)


@case('SW06', binding=CONTROLLER)
def test_SW06_a_relay_host_or_one_shot_route_never_fills_a_controller_seat(nc):
    require_controller()
    from ravel.workflow import transport_registry as tr
    worker, record, register = _qualified(nc)
    tr.register_qualification(record, register)
    card = _card('analysis-author')
    seatless = [d['id'] for d in tr.all_declarations(installed_only=True)
                if d['transport_kind'] in tr.CONTROLLER_SEATLESS]
    assert seatless, 'the installed declarations include seatless routes'
    for transport_id in seatless:
        with pytest.raises(tr.TransportRefusal) as refused:
            tr.select(card, _preferences(card, [transport_id]), controller=True,
                      qualifications=tr.registered_qualifications(register))
        kind = tr.load(transport_id)['transport_kind']
        assert f'controller:{kind}' in refused.value.missing, (transport_id, refused.value.missing)
    chosen = tr.select(card, _preferences(card, [*seatless, TRANSPORT]), controller=True,
                       qualifications=tr.registered_qualifications(register))
    assert chosen['transport_id'] == TRANSPORT  # positive control: the qualified restricted worker


register(Mutation('SW06', 'ravel.workflow.transport_registry:CONTROLLER_SEATLESS', constant(()), ('SW06',),
                  binding=MUTATION_CONTROLLER, why='controller selection accepts relay and host routes'))


@case('SW09', binding=CONTROLLER)
def test_SW09_a_hand_written_qualification_record_counts_for_nothing_in_controller_selection(nc):
    require_controller()
    from ravel.workflow import transport_registry as tr
    worker, record, register = _qualified(nc)
    card = _card('analysis-author')
    with pytest.raises(tr.TransportRefusal):
        tr.select(card, _preferences(card, [TRANSPORT]), controller=True,
                  qualifications=tr.registered_qualifications(register))
    forged = dict(record, qualified_utc='2026-10-12T00:00:00Z', steps=[])
    Path(record['record_path']).write_text(json.dumps(forged))  # adversary-authored record without live steps
    other = nc.root / 'forged-register' / tr.QUALIFICATION_REGISTER
    with pytest.raises(ValueError, match='passed live qualification'):
        tr.register_qualification(forged, other)
    with pytest.raises(tr.TransportRefusal):
        tr.select(card, _preferences(card, [TRANSPORT]), controller=True,
                  qualifications=tr.registered_qualifications(register))
    Path(record['record_path']).write_text(json.dumps(record))  # restore the exact qualifier result
    tr.register_qualification(record, register)  # positive control: the operator registers the actual result
    chosen = tr.select(card, _preferences(card, [TRANSPORT]), controller=True,
                       qualifications=tr.registered_qualifications(register))
    assert chosen['transport_id'] == TRANSPORT


def _register_ignored(original):
    def read_qualification(document, probe_record, *, registered=None):
        return original(document, probe_record, registered=None)
    return read_qualification


register(Mutation('SW09', 'ravel.workflow.transport_registry:read_qualification', _register_ignored, ('SW09',),
                  binding=MUTATION_CONTROLLER, why='any stored qualification record counts'))


@case('SW21', binding=CONTROLLER)
def test_SW21_a_declaration_added_through_the_environment_or_project_is_ignored_by_controller_selection(nc):
    require_controller()
    from ravel.workflow import transport_registry as tr
    extra = nc.root / 'user-transports'
    extra.mkdir()
    builtin = dict(tr.load(TRANSPORT))
    forged = dict(builtin, id='fictional-blind-transport')
    (extra / 'fictional-blind-transport.json').write_text(json.dumps(forged))
    nc.patch.setenv('RAVEL_TRANSPORT_PATH', str(extra))
    project = nc.root / 'project' / '.ravel' / 'transports'
    project.mkdir(parents=True)
    (project / 'fictional-project-transport.json').write_text(json.dumps(dict(builtin, id='fictional-project-transport')))
    ids = {d['id'] for d in tr.all_declarations(installed_only=True)}
    assert 'fictional-blind-transport' not in ids and 'fictional-project-transport' not in ids
    card = _card('physics-critic')
    with pytest.raises(tr.TransportRefusal):
        tr.select(card, _preferences(card, ['fictional-blind-transport']), controller=True, qualifications=())
    assert TRANSPORT in ids  # positive control: the installed declarations are all there
    assert 'fictional-blind-transport' in {d['id'] for d in tr.all_declarations()}, 'legacy lookup unchanged'


def _user_dirs_everywhere(original):
    def search_dirs(*, installed_only=False):
        return original(installed_only=False)
    return search_dirs


register(Mutation('SW21', 'ravel.workflow.transport_registry:search_dirs', _user_dirs_everywhere, ('SW21',),
                  binding=MUTATION_CONTROLLER, why='controller selection reads user and project declarations'))


@case('XF02', binding=CONTROLLER)
def test_XF02_a_role_once_bound_to_family_diversity_is_selected_without_any_family_refusal(nc):
    require_controller()
    from ravel.workflow import transport_registry as tr
    worker, record, register = _qualified(nc)
    tr.register_qualification(record, register)
    card = _card('ml-reviewer')
    assert card['model']['distinct_family_from'] == [], 'the cross-family requirement is removed from the card'
    chosen = tr.select(card, _preferences(card, [TRANSPORT]), controller=True,
                       qualifications=tr.registered_qualifications(register))
    assert chosen['transport_id'] == TRANSPORT
    assert 'family' in json.dumps(chosen), 'the selection records the family for the label'
