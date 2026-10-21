"""Inert inventory, delivery-integrity and fictional applicability controls."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import platform
import subprocess

import pytest

from ravel.controller import instructions as ins
from ravel.workflow import capability_catalogue as ca


ROOT = Path(__file__).resolve().parents[3]
SEATS = (
    'intake', 'planning', 'research-coordination', 'experiment-design',
    'recovery', 'judgment', 'future-unrecognized-seat',
)


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False,
    ).encode()).hexdigest()


@pytest.fixture(autouse=True)
def metadata_only(monkeypatch):
    # Some import-time platform descriptions query the host processor through
    # subprocess. Supply that descriptive field without weakening the sentinel.
    monkeypatch.setattr(platform, 'processor', lambda: 'inert-metadata-control')

    def forbidden(*args, **kwargs):
        pytest.fail('metadata controls must not launch native or provider processes')

    monkeypatch.setattr(subprocess, 'Popen', forbidden)


def test_complete_catalogue_against_independent_source_inventories():
    from ravel.setup import manifest as setup_manifest
    from ravel.workflow import science
    from ravel.workflow.knowledge import load_atlas
    from ravel.workflow.operation_registration import read_signatures
    from ravel.workflow.tool_census import load_census

    select = importlib.import_module('ravel.controller.routes.select')
    catalogue = ca.catalogue()
    rows = {row['id']: row for row in catalogue['entries']}
    assert len(rows) == len(catalogue['entries'])
    assert {'op:' + mode for mode in science.MODES} <= rows.keys()
    signatures = read_signatures(ROOT / 'src/ravel/data/operation_signatures.json')
    assert {'op:' + mode for mode in signatures} <= rows.keys()
    assert {'route:' + spec['id'] for spec in [*select.load_specs(), *select.BUILTIN]} <= rows.keys()
    atlas = load_atlas(ROOT / 'src/ravel/data/knowledge/atlas.json')
    assert {row['id'] for row in atlas['entries'] if row['kind'] in ('op', 'tool', 'cmd')} <= rows.keys()
    groups = setup_manifest.view(ROOT)['groups']
    assert {'tool:' + group['id'] for group in groups} <= rows.keys()
    census = load_census(catalog=None)
    assert {'tool:' + tool['id'] for tool in census['tools']} <= rows.keys()
    from ravel.workflow.toolbelt import census as affordance_census
    assert {'tool:affordance/' + row['tool'] for row in affordance_census()['rows']} <= rows.keys()
    sources = {source['path'] for source in catalogue['sources']}
    for row in rows.values():
        assert {'applicability', 'prerequisites', 'produces', 'cost_class', 'source'} <= row.keys()
        assert isinstance(row['applicability'], dict) and row['applicability']
        assert row['produces'] is not None
        assert isinstance(row['cost_class'], str) and row['cost_class']
        assert row['source']['path'] in sources
        assert set(row['prerequisites']) == {'ref'}
        prerequisites = catalogue['prerequisite_sets'][row['prerequisites']['ref']]
        assert prerequisites['installed'] == 'not_observed'
        assert prerequisites['qualified'] == 'not_observed'
        assert prerequisites['licensed'] == (
            'not_observed' if prerequisites['licenses'] else 'no_requirement_declared'
        )
        # Historical qualification is retained as its own scoped statement,
        # never promoted to current readiness, installation or license evidence.
        assert isinstance(prerequisites['qualification'], dict)
        assert prerequisites['qualification']
        assert prerequisites['qualification'] != prerequisites['qualified']
    assert catalogue['compute_authorized'] is False
    assert catalogue['physics_validated'] is False


@pytest.mark.parametrize('seat', SEATS)
def test_every_deciding_seat_gets_complete_context_even_with_zero_inline_budget(seat):
    step = {'id': 'catalogue-control', 'kind': 'author', 'parameters': {'seat_kind': seat}}
    full_catalogue = ca.catalogue()
    for lean in (False, True):
        current = deepcopy(step)
        if lean:
            current['engagement'] = {'inline_context_tokens': 0}
        manifest = ins.manifest(current, None)
        packet = ins.packet(manifest, None, current, [])
        context = packet['capability_context']
        assert context['seat_kind'] == seat
        assert context['catalogue'] == full_catalogue
        assert context['catalogue_sha256'] == _digest(full_catalogue)
        assert context['catalogue_sha256'] in packet['text']
        for row in full_catalogue['entries']:
            assert row['id'] + ' | ' in packet['text']
        assert ins.check_packet(packet, manifest, None, current, []) == []


@pytest.mark.parametrize('tamper', ('missing-context', 'forged-catalogue', 'changed-digest'))
def test_dispatch_refuses_tampered_capability_context(tamper):
    step = {'id': 'catalogue-integrity', 'kind': 'author', 'parameters': {'seat_kind': 'planning'}}
    manifest = ins.manifest(step, None)
    packet = ins.packet(manifest, None, step, [])
    if tamper == 'missing-context':
        del packet['capability_context']
    elif tamper == 'forged-catalogue':
        packet['capability_context']['catalogue']['entries'].pop()
        # A self-consistent attacker digest still differs from the real packet.
        packet['capability_context']['catalogue_sha256'] = _digest(packet['capability_context']['catalogue'])
    else:
        packet['capability_context']['catalogue_sha256'] = '0' * 64
    assert ins.check_packet(packet, manifest, None, step, [])


@pytest.fixture
def fictional_context():
    from ravel.workflow.capability_routing import _descriptors

    modes = {
        'velvet-weave': {
            'summary': 'Weave amber threads into a mosaic.', 'operations': ['weaving'],
            'tools': ['velvet shuttle'], 'inputs': ['amber thread'],
            'observables': ['braid density'], 'outputs': ['mosaic'], 'context': ['loom'],
            'applicability': {
                'scope': 'source-bound', 'bound_to': 'copper orchard',
                'select_when': [['copper orchard']], 'general_operation': 'plain-weave',
            },
        },
        'plain-weave': {
            'summary': 'Construct an ordinary textile.', 'operations': ['weaving'],
            'tools': ['wooden spindle'], 'inputs': ['linen'], 'observables': ['stitch count'],
            'outputs': ['tapestry'], 'context': ['workroom'], 'applicability': {'scope': 'general'},
        },
    }
    descriptors = _descriptors({
        'schema_version': 1, 'weights': dict.fromkeys(
            ('tools', 'inputs', 'observables', 'outputs', 'context'), 2,
        ), 'threshold': 2, 'modes': modes,
    }, modes)
    prerequisites = {
        'installed': 'not_observed', 'licensed': 'not_observed', 'qualified': 'not_observed',
        'groups': ['fictional-weaving-kit'], 'licenses': ['fictional-permission'],
        'qualification': {'status': 'registered', 'scope': 'fictional metadata only'},
        'inputs': ['amber thread'],
    }
    catalogue = {
        'schema_version': 1, 'kind': 'deciding-capability-catalogue',
        'prerequisite_sets': {'fictional': prerequisites},
        'entries': [{
            'id': 'op:' + mode, 'kind': 'operation', 'summary': descriptor['summary'],
            'descriptor': descriptor, 'applicability': deepcopy(descriptor['applicability']),
            'prerequisites': {'ref': 'fictional'}, 'produces': descriptor['outputs'],
            'cost_class': 'low', 'source': {'path': 'fictional/metadata.json'}, 'links': {},
        } for mode, descriptor in descriptors.items()],
        'sources': [], 'compute_authorized': False, 'physics_validated': False,
    }
    return {
        'schema_version': 1, 'kind': 'seat-capability-context', 'seat_kind': 'planning',
        'catalogue': catalogue, 'catalogue_sha256': _digest(catalogue), 'policy': dict(ca.POLICY),
    }


REQUEST = 'Use a velvet shuttle with amber thread for a mosaic from the copper orchard.'
READY = {'op:velvet-weave': {'installed': True, 'licensed': True, 'qualified': True}}


def test_fictional_recall_matches_relevant_operation_and_retains_original_request(fictional_context):
    result = ca.recall(REQUEST, context=fictional_context, availability=READY)
    assert result['original_request'] == REQUEST
    assert [step['capability'] for step in result['steps']] == ['op:velvet-weave']
    assert result['steps'][0]['status'] == 'candidate'
    assert result['steps'][0]['fallback'] is None
    assert result['compute_authorized'] is False
    assert result['physics_validated'] is False


@pytest.mark.parametrize('prompt', (
    'Arrange pebbles around a wooden bowl.',
    'Do not use a velvet shuttle with amber thread for a mosaic from the copper orchard.',
    'Use a velvet shuttle with amber thread for a mosaic.',
))
def test_fictional_recall_excludes_unrelated_negated_or_inapplicable_requests(fictional_context, prompt):
    assert ca.recall(prompt, context=fictional_context, availability=READY)['steps'] == []


def test_high_cost_never_removes_relevant_fictional_capability(fictional_context):
    before = ca.recall(REQUEST, context=fictional_context, availability=READY)
    fictional_context['catalogue']['entries'][0]['cost_class'] = 'high'
    fictional_context['catalogue_sha256'] = _digest(fictional_context['catalogue'])
    after = ca.recall(REQUEST, context=fictional_context, availability=READY)
    assert [step['capability'] for step in before['steps']] == [step['capability'] for step in after['steps']]
    assert after['steps'][0]['cost_class'] == 'high'


@pytest.mark.parametrize('prerequisite', ('installed', 'licensed', 'qualified'))
@pytest.mark.parametrize('state', (False, None))
def test_unavailable_or_unknown_prerequisite_preserves_capability_with_qualified_fallback(
    fictional_context, prerequisite, state,
):
    evidence = deepcopy(READY)
    evidence['op:velvet-weave'][prerequisite] = state
    result = ca.recall(REQUEST, context=fictional_context, availability=evidence)
    step, = result['steps']
    assert step['capability'] == 'op:velvet-weave'
    assert step['status'] == 'requires_qualification'
    fallback = step['fallback']
    assert fallback['requires'] == [prerequisite]
    assert fallback['qualification_required'] is True
    assert fallback['preserves_required_capability'] == step['capability']
    assert fallback['candidate'] == 'op:plain-weave'
    assert fallback['candidate'] in {row['id'] for row in fictional_context['catalogue']['entries']}


def test_absent_availability_evidence_does_not_inherit_historical_qualification(fictional_context):
    prerequisites = fictional_context['catalogue']['prerequisite_sets']['fictional']
    prerequisites['qualification']['status'] = 'qualified'
    fictional_context['catalogue_sha256'] = _digest(fictional_context['catalogue'])
    step, = ca.recall(REQUEST, context=fictional_context, availability={})['steps']
    assert step['fallback']['requires'] == ['installed', 'licensed', 'qualified']
    assert step['fallback']['qualification_required'] is True


def test_each_seat_gets_independent_catalogue_data():
    first = ca.for_seat('planning')
    first['catalogue']['entries'].clear()
    later = ca.for_seat('recovery')
    assert later['catalogue']['entries']
    assert later['catalogue_sha256'] == _digest(later['catalogue'])


def test_new_route_registration_is_visible_without_editing_a_seat_allowlist():
    select = importlib.import_module('ravel.controller.routes.select')
    before = ca.for_seat('planning')
    spec = deepcopy(select.load_specs()[0])
    spec['id'] = 'fictional-route'
    with select.registered(spec):
        context = ca.for_seat('future-decider')
        assert 'route:fictional-route' in context['catalogue']['coverage']['route']
        assert context['catalogue_sha256'] != before['catalogue_sha256']
    assert 'route:fictional-route' not in ca.for_seat('planning')['catalogue']['coverage']['route']


def test_controller_materializes_the_complete_packet_data_and_pins_it_for_the_worker(tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from test_p04_support import FakeStore
    run = tmp_path / 'run'
    run.mkdir()
    store = FakeStore(tmp_path / 'store', run_dir=run)
    step = {'id': 'planning-control', 'kind': 'author', 'depends_on': [], 'inputs': [],
            'parameters': {'seat_kind': 'planning'}}
    state = {'branch': 'worker', 'step': step, 'acting': step, 'context': {'attempt': 1}}
    monkeypatch.setattr(graph, '_store', lambda state: store)
    monkeypatch.setattr(graph, '_run_dir', lambda state: run)
    result = graph.packet(state)['packet']
    retained = store.read('instruction-packet', result['commitment'])['record']['packet']['capability_context']
    attachment = run / result['capability_context']['path']
    assert json.loads(attachment.read_bytes()) == retained
    assert hashlib.sha256(attachment.read_bytes()).hexdigest() == result['capability_context']['sha256']
    pins = graph._capability_inputs(result, store=store, run_dir=run)
    assert pins == result['capability_context']['shards']
    from ravel.workflow import broker
    pieces = []
    for pin in pins:
        raw = (run / pin['pin']['path']).read_bytes()
        assert len(raw) < broker.MAX_MESSAGE // 2
        pieces.append(json.loads(raw))
    assert ca.assemble(pieces) == retained
    assert ins.receipt(store.read('instruction-packet', result['commitment'])['record']['manifest'],
                       store.read('instruction-packet', result['commitment'])['record']['packet'],
                       session='inert-session')['capability_catalogue_sha256'] == retained['catalogue_sha256']


@pytest.mark.parametrize('damage', ('missing', 'bytes', 'pin', 'path', 'catalogue', 'stale'))
def test_controller_refuses_missing_changed_or_stale_capability_attachments(tmp_path, monkeypatch, damage):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    from test_p04_support import FakeStore
    run = tmp_path / 'run'
    folder = run / 'inputs/packet'
    folder.mkdir(parents=True)
    store = FakeStore(tmp_path / 'store', run_dir=run)
    context = ca.for_seat('planning')
    raw = ca.encode(context)
    (folder / 'capabilities.json').write_bytes(raw)
    info = {'path': 'inputs/packet/packet.md',
            'commitment': store.append('instruction-packet', {'packet': {'capability_context': context}}),
            'capability_context': {'path': 'inputs/packet/capabilities.json',
                                   'sha256': hashlib.sha256(raw).hexdigest(),
                                   'catalogue_sha256': context['catalogue_sha256']}}
    info['capability_context']['shards'] = []
    for part in ca.shards(context):
        name = f"capabilities-{part['part']:03d}.json"
        raw = ca.encode(part)
        (folder / name).write_bytes(raw)
        info['capability_context']['shards'].append({
            'pin': {'path': 'inputs/packet/' + name, 'sha256': hashlib.sha256(raw).hexdigest()}, 'as': 'inputs/' + name})
    if damage == 'missing':
        del info['capability_context']
    elif damage == 'bytes':
        (folder / 'capabilities.json').write_bytes(b'{}')
    elif damage == 'pin':
        info['capability_context']['sha256'] = '0' * 64
    elif damage == 'path':
        info['capability_context']['path'] = 'inputs/elsewhere.json'
    elif damage == 'catalogue':
        info['capability_context']['catalogue_sha256'] = '0' * 64
    else:
        replacement = deepcopy(context)
        replacement['catalogue']['entries'].pop()
        replacement['catalogue_sha256'] = _digest(replacement['catalogue'])
        monkeypatch.setattr(ca, 'for_seat', lambda seat: replacement)
    with pytest.raises(StepHold, match='capability'):
        graph._capability_inputs(info, store=store, run_dir=run)


@pytest.mark.parametrize('damage', ('missing', 'source', 'traversal'))
def test_budget_projection_rejects_capability_provenance_drift(monkeypatch, damage):
    from ravel.controller.engagement import envelope
    from ravel.controller.engagement.records import EngagementRefused, data, digest
    installed = deepcopy(data('envelopes.json'))
    original = envelope.data
    if damage == 'missing':
        del installed['source_pins']['capabilities']
        reason = 'source inventory unavailable'
    elif damage == 'source':
        installed['source_pins']['capabilities']['workflow/capability_catalogue.py'] = '0' * 64
        reason = 'capability source stale'
    else:
        installed['source_pins']['capabilities']['../outside'] = '0' * 64
        reason = 'capability inventory invalid'
    installed['sha256'] = digest({key: value for key, value in installed.items() if key != 'sha256'})
    monkeypatch.setattr(envelope, 'data', lambda name: installed if name == 'envelopes.json' else original(name))
    with pytest.raises(EngagementRefused, match=reason):
        envelope.installed_projection()


def test_projection_contains_complete_broker_readable_capability_data_without_raw_input_exceptions(tmp_path):
    from ravel.workflow import broker, review_projection
    run = tmp_path / 'run'
    (run / 'outputs').mkdir(parents=True)
    (run / 'outputs/producer.json').write_text('{"interpretation":"hidden-run-value-482"}')
    manifest, files = review_projection.build(run, 'plan-critic')
    context = ca.for_seat('plan-critic')
    assert manifest['capability_catalogue_sha256'] == context['catalogue_sha256']
    pieces = []
    for name, raw in files:
        if name.startswith('artifacts/capabilities-'):
            assert len(raw) < broker.MAX_MESSAGE // 2
            assert b'hidden-run-value-482' not in raw
            pieces.append(json.loads(raw))
    assert ca.assemble(pieces) == context
    assert not any(row['source_path'].endswith('producer.json') for row in manifest['subjects'])


@pytest.mark.parametrize('damage', ('missing', 'duplicate', 'changed', 'policy'))
def test_incomplete_or_changed_capability_shards_never_reconstruct_as_complete(damage):
    context = ca.for_seat('planning')
    parts = ca.shards(context)
    assert len(parts) > 1
    if damage == 'missing':
        parts.pop()
    elif damage == 'duplicate':
        parts[-1] = deepcopy(parts[0])
    elif damage == 'policy':
        fragment = next(fragment for part in parts for fragment in part['fragments'] if fragment['path'] == ['policy'])
        fragment['value']['cost'] = 'Changed planning policy.'
    else:
        fragment = next(fragment for part in parts for fragment in part['fragments']
                        if fragment['path'] == ['catalogue', 'compute_authorized'])
        fragment['value'] = True
    with pytest.raises(ValueError, match='capability'):
        ca.assemble(parts)


def test_shards_survive_the_protected_store_canonical_json_roundtrip():
    context = ca.for_seat('planning')
    # Protected stores deserialize canonical JSON; dictionary insertion order
    # must not change the actual input bytes or their preflight commitments.
    stored = json.loads(json.dumps(context, sort_keys=True))
    before = ca.shards(context)
    after = ca.shards(stored)
    assert [ca.encode(part) for part in before] == [ca.encode(part) for part in after]
    assert ca.assemble(after) == context


def test_new_registration_files_invalidate_a_cached_inventory(tmp_path):
    package = tmp_path / 'src/ravel'
    directory = package / 'data/roles/registration'
    directory.mkdir(parents=True)
    before = ca._fingerprint(tmp_path, package, {'sources': []})
    (directory / 'fictional-registration.json').write_text('{}')
    assert ca._fingerprint(tmp_path, package, {'sources': []}) != before
