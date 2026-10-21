"""Bounded execution/delivery compositions on fictional inputs; no live providers.

These are engineering probes, not scientific certification. Recovery uses the real
store and entry API. Delivery uses P07's strict interface world and the real sink.
The last probe uses the P01 tier-composition harness (its documented stand-in
step/ledger/authority services), but actually calls the registered finite arithmetic
implementation when the controller dispatches its calculation role. It does not
qualify a native tool, OS confinement, a model, or autonomous scientific judgment.
"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from ravel.controller import entry, execution_manifest, graph
from ravel.controller.authority import mode, operator
from ravel.controller.step.services import StepHold
from ravel.workflow import provider_policy, sandbox, transport_registry
from test_p06_support import operator_home  # noqa: F401


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'size': len(raw)}


def _retained_work(tmp_path):
    """Pre-existing accepted work is a fixture premise, not a newly certified claim."""
    store = entry.start(b'Calculate a fictional supplied scalar with a fixed procedure.', channel='terminal',
                        rundir=tmp_path / 'run', root=tmp_path / 'store')
    procedure = _json(store.run_dir / 'inputs' / 'procedure.json', {
        'seed': 314159, 'algorithm': 'fixed finite enumeration', 'ordered_inputs': [3, 1, 4]})
    result = _json(store.run_dir / 'steps' / 'enumerate' / 'outputs' / 'value.json', {
        'value': 8, 'seed': 314159, 'procedure_sha256': procedure['sha256']})
    custody = store.append('custody', {'artifact': 'enumerate:outputs/value.json', 'step_id': 'enumerate',
        'path': 'outputs/value.json', 'destination': 'steps/enumerate/outputs/value.json',
        'sha256': result['sha256'], 'status': 'accepted', 'inputs': [], 'attempt': 1})
    return store, procedure, result, custody


def _identity():
    return {'schema_version': 1, 'source': {'digest': 'tree:' + 'a' * 64, 'package_dir': '/opt/fixture'},
        'dependencies': [{'name': 'fixture-runtime', 'version': '1'}],
        'python': {'executable': sys.executable}, 'thread_id': 'b' * 64, 'graph_id': entry.GRAPH_ID,
        'closure': [['controller.run', 1]], 'runtime': {'version': '1'}}


def test_interrupted_resume_preserves_accepted_bytes_seed_and_procedure(tmp_path):
    store, procedure, result, custody = _retained_work(tmp_path)
    original_request = store.latest('request')
    head = store.head()
    with (store.root / 'journal.jsonl').open('ab') as journal:
        journal.write(b'{"kind":"unacknowledged-tail')
    recovered = entry.open_for_resume(store.run_id, root=store.store_root)
    assert recovered.verify() == []
    assert recovered.count('journal-recovery') == 1
    assert recovered.head()['seq'] == head['seq'] + 1
    assert recovered.latest('request') == original_request and recovered.count('request') == 1
    assert recovered.read('custody', custody)['record']['status'] == 'accepted'
    assert recovered.count('custody') == 1
    assert sha256(Path(procedure['path']).read_bytes()).hexdigest() == procedure['sha256']
    assert sha256(Path(result['path']).read_bytes()).hexdigest() == result['sha256']
    assert json.loads(Path(result['path']).read_text())['seed'] == 314159
    assert json.loads(Path(result['path']).read_text())['procedure_sha256'] == procedure['sha256']
    again = entry.open_for_resume(store.run_id, root=store.store_root)
    assert again.count('journal-recovery') == 1 and again.count('custody') == 1


def test_upgrade_while_paused_holds_with_original_environment_remedy(tmp_path, monkeypatch):
    store, procedure, result, custody = _retained_work(tmp_path)
    pinned = _identity()
    monkeypatch.setattr(execution_manifest, 'current', lambda *args: deepcopy(pinned))
    execution_manifest.ensure(store, entry.GRAPH_ID)
    head = store.head()
    upgraded = deepcopy(pinned)
    upgraded['runtime']['version'] = '2'
    monkeypatch.setattr(execution_manifest, 'current', lambda *args: upgraded)
    admissions = []
    monkeypatch.setattr(entry, 'admit', lambda *args, **kwargs: admissions.append(args))
    with pytest.raises(execution_manifest.ExecutionRefused) as caught:
        entry.drive(store, resume=True)
    assert caught.value.code == 'execution_environment_mismatch'
    assert 'runtime changed' in str(caught.value)
    assert execution_manifest.resume_command(store, pinned) in caught.value.remedy
    assert 'restore the pinned environment' in caught.value.remedy
    assert admissions == [] and store.head() == head
    assert execution_manifest.original(store) == pinned
    assert store.read('custody', custody)['record']['sha256'] == result['sha256']
    for pin in (procedure, result):
        assert sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']


def test_budget_exhaustion_delivers_qualified_prior_work_and_blocked_duties(tmp_path, monkeypatch):
    from ravel.controller import sink
    from p07_support import Run
    run = Run(tmp_path, monkeypatch)
    run.add_step('compute', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('report', ['outputs/report.md'], kind='synthesize', inputs=['compute:outputs/value.json'],
                 deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan()
    source = run.adopt('compute', 'outputs/value.json', {'value': 7, 'qualification': 'Finite toy only.'})
    raw = source.read_bytes()
    run.authority_record('approve_plan', 'approve')
    run.satisfy_upstream()
    run.ledger.covered = {'d-value'}
    run.store.append('step-outcome', {'schema_version': 1, 'step_id': 'report', 'attempt': 1,
                                     'status': 'budget_exhausted', 'reason': 'budget_exhausted'})
    dispatched_before = run.store.scan('step-dispatch')
    receipt = sink.bounded_end(run.store, 'budget exhausted: tokens; report remains blocked')
    assert receipt['qualified'] is True and receipt['accepted'] is False
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert {o['id']: o['state'] for o in ending['obligations']} == {
        'd-value': 'satisfied', 'd-report': 'blocked'}
    assert ending['parent_task_accepted'] is False and ending['scientific_claims_adopted'] == []
    assert run.delivered('artifacts/compute/outputs/value.json').read_bytes() == raw == source.read_bytes()
    assert 'Qualified ending' in run.delivered('DELIVERY.md').read_text()
    assert run.store.scan('step-dispatch') == dispatched_before


def test_restrictive_supplied_data_stays_restricted_before_external_provider(tmp_path, operator_home):
    operator.init(mode='physicist-in-the-loop', store_root=tmp_path / 'store')
    supplied = _json(tmp_path / 'supplied.json', {'fictional_private_values': [2, 5]})
    rows = entry._supplied([supplied['path']], tmp_path)
    request = b'Calculate a fictional quantity from supplied private data.'
    store = entry.start(request, channel='terminal',
                        rundir=tmp_path / 'run', root=tmp_path / 'store', supplied=rows)
    pinned = store.latest('supplied')['record']['inputs']
    staged = graph.stage_supplied_inputs(store.run_dir, pinned)
    frozen = mode.freeze_mode(store, {'prompt': request.decode()}, run_dir=store.run_dir,
                              project=tmp_path)['provider_policy']
    assert frozen['record']['data_classification'] == provider_policy.RESTRICTED
    assert frozen['policy_sha256'] == provider_policy.digest(frozen['record'])
    route = transport_registry.load('http-responses')
    before = store.head()
    with pytest.raises(provider_policy.PolicyRefused, match='refuses transport') as caught:
        provider_policy.admission(store.run_dir, route, provider_policy.account_class(route), input_pins=staged)
    assert caught.value.not_dispatched is True
    assert store.head() == before and store.count('step-dispatch') == 0
    assert all(row['restricted'] and row['data_classification'] == provider_policy.RESTRICTED for row in staged)
    assert sha256((store.run_dir / 'inputs' / 'supplied.json').read_bytes()).hexdigest() == supplied['sha256']


def test_broken_sandbox_keeps_prior_work_and_names_review_remedy(tmp_path, monkeypatch, operator_home):
    from ravel.controller.step import graph as step_graph
    operator.init(mode='autonomous', review_sandbox_fallback='none')
    store, procedure, result, custody = _retained_work(tmp_path)
    mode.freeze_mode(store, {'prompt': 'Check a fictional supplied calculation.'}, project=tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: None)
    with pytest.raises(StepHold) as caught:
        step_graph._review_sandbox(store, {'purpose': 'review', 'role': 'fictional-critic'},
            {'id': 'verify', 'kind': 'review'}, selection={'transport_id': 'fictional-worker'})
    hold = caught.value
    assert hold.reason == 'worker_sandbox_unavailable'
    assert hold.would_make_possible.startswith('INDEPENDENT REVIEW INCOMPLETE: ')
    assert '--review-sandbox-fallback restricted-unsandboxed' in hold.would_make_possible
    assert hold.evidence['driver_self_review'] == 'never'
    assert store.scan(step_graph.REVIEW_FALLBACK) == [] and store.count('step-dispatch') == 0
    assert store.read('custody', custody)['record']['status'] == 'accepted'
    for pin in (procedure, result):
        assert sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']


def test_forwarded_pdf_carries_visible_qualification_without_receipt_directory(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from ravel.controller.sink import render
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    writer.add_blank_page(width=300, height=200)
    output = BytesIO()
    writer.write(output)
    source = tmp_path / 'calculation.pdf'
    source.write_bytes(output.getvalue())
    original = source.read_bytes()
    limitation = 'Missing independent validation; finite fictional calculation only.'
    row = {'destination': source.name, 'step': 'calculate', 'output': source.name,
           'artifact': 'calculate:calculation.pdf', 'status': 'accepted',
           'sha256': sha256(original).hexdigest(), 'deliverables': ['plot'], 'qualification': limitation}
    staging = tmp_path / 'delivery'
    staging.mkdir()
    reference = 'ravel-delivery-0123456789abcdef'
    [delivered] = render.copy_artifacts(tmp_path, staging, {'declared': []}, SimpleNamespace(labels=[]),
        'qualified', [], qualified=[row], receipt_reference=reference)
    forwarded = tmp_path / 'forwarded' / 'calculation.pdf'
    forwarded.parent.mkdir()
    shutil.copyfile(staging / delivered['path'], forwarded)
    assert sorted(p.name for p in forwarded.parent.iterdir()) == ['calculation.pdf']
    pdf = PdfReader(forwarded)
    assert len(pdf.pages) == 2 and pdf.metadata['/Label'] == 'QUALIFIED'
    assert pdf.metadata['/ReceiptReference'] == reference
    for page in pdf.pages:
        visible = ''.join(page.extract_text().split())
        assert 'QUALIFIED' in visible and ''.join(limitation.split()) in visible and reference in visible
    assert delivered['visible_notice'] is True and delivered['presentation_derivative'] is True
    assert source.read_bytes() == original
    assert sha256(forwarded.read_bytes()).hexdigest() == delivered['sha256']


def test_operator_minimum_tier_override_preserves_tool_specialist_and_review_duties():
    from ravel.controller.engagement import policy
    from ravel.controller.engagement.builder import build_tier, installed_instructions
    from ravel.controller.engagement.records import data
    from ravel.controller import instructions
    from test_engagement_tier_cost import inert_plan
    from test_p18_policy import fakes
    plan = inert_plan(required=True)
    cards, ins = policy.role_cards(), installed_instructions()
    rules = fakes.policy_for(plan, cards)
    selected = policy.raise_only('lean', 'standard')
    assert selected == 'standard'
    seats = policy.seat_plan(plan, selected, rules, cards=cards, instructions=ins)
    assert seats['errors'] == []
    _, sessions = build_tier(plan, plan, selected, cards, ins, rules, data('calibration.json'))
    assert any(s['key'] == 'producer:s1:generator' for s in sessions)
    fired = [c for c in cards['generator']['knowledge']['consult'] if c['when'] == 'before_first_smoke']
    assert fired
    for consult in fired:
        assert any(s['key'] == f"consult:s1:{consult['role']}:before_first_smoke" for s in sessions)
    full = policy.seat_plan(plan, 'full', rules, cards=cards, instructions=ins)
    assert {k for s in seats['seats'] for k in s['source_seats']} == set(full['bindings'])
    # Folding can retain the same source seat more than once. Every original
    # source and its actual review items must still reach the mapped carrier.
    for source_key, full_target in full['bindings'].items():
        original = next(s for s in full['seats'] if s['key'] == full_target)
        carrier = next(s for s in seats['seats'] if s['key'] == seats['bindings'][source_key])
        assert source_key in carrier['source_seats']
        owed_items = {i['id'] for i in original['items']}
        assert owed_items <= {i['id'] for i in carrier['items']}
    source = 'checkin:checkin3:normalization-auditor'
    carried = next(s for s in seats['seats'] if s['key'] == seats['bindings'][source])
    packet = instructions.packet(ins.manifest(carried['step'], carried['card']), carried['card'], carried['step'], [])
    declared = next(s for s in policy.declared_seats(plan, cards) if s['key'] == source)
    owed = ins.manifest(declared['step'], cards[declared['role']])
    assert {u['id'] for u in owed['units'] if u['kind'] == 'duty'} <= set(packet['units'])


# The controller fixture's substitutions are documented in test_composition_tiers.
# Import helper fixtures, never an existing test function.
from test_p01_graph import controller, real_authority  # noqa: E402, F401


def test_lean_required_operation_is_executed_by_dispatched_calculation_role(
        controller, real_authority, capfd, monkeypatch):
    import fakes
    import test_composition_tiers as tiers
    from ravel.physics import literal_calculation
    from ravel.workflow import route_prompt
    from ravel.controller.step import operations
    request = b'Calculate 0.1+0.2'
    monkeypatch.setattr(tiers, 'SIMPLE', request)
    parent = _json(controller / 'arithmetic-parent' / 'inputs' / 'task_contract.json',
                   route_prompt.route(request.decode()))
    task = {'parent_contract': parent, 'expression': '0.1+0.2', 'unit': '1'}
    actual_step = fakes.step_run
    calls = []

    def operation(store, step, context):
        outcome = actual_step(store, step, context)
        if step['id'] == 's1':
            assert step['role'] == 'calculation' and step['operation'] == 'literal-calculation'
            assert operations.executor_errors(step) == []
            value = literal_calculation.run(task, controller, None)
            pin = _json(Path(context['run_dir']) / 'steps' / 's1' / 'outputs' / 'result.json', value)
            outcome['outputs'] = [{'artifact': 's1:outputs/result.json', 'path': 'outputs/result.json',
                                   'sha256': pin['sha256']}]
            calls.append((deepcopy(step), value, pin))
        return outcome

    def calculation_spec():
        return fakes._spec('calculation', 7, {'field': 'task_mode', 'eq': 'calculation'},
            [fakes.make_step('s1', kind='operate', role='calculation', operation='literal-calculation',
                             outputs=['outputs/result.json'])],
            [{'match': {'any': True}, 'step': 's1', 'output': 'outputs/result.json'}])

    monkeypatch.setattr(fakes, 'step_run', operation)
    monkeypatch.setattr(tiers, 'calculation_spec', calculation_spec)
    store, observation, _admitted, _services = tiers._drive_tier(controller, real_authority, capfd, monkeypatch,
        method=tiers.method_decision(request))
    assert tiers._decision(store)['tier'] == 'lean'
    assert len(calls) == 1
    _step, value, pin = calls[0]
    assert ('s1', 1) in fakes.DISPATCHED
    assert any(s['id'] == 's1' and s['role'] == 'calculation' for s, _ in fakes.PACKETS)
    assert value['quantity'] == {'numerator': '3', 'denominator': '10', 'unit': '1',
                                'representation': 'exact_rational', 'rounding': 'none'}
    assert value['physics_validated'] is False and value['calibration_claimed'] is False
    assert sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']
    assert observation['terminal'] is None and not observation.get('interrupts')
