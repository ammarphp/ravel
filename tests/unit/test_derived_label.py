"""Derived label, open route, exit codes and the intake summary."""
import synthetic_identifiers as syn
import ast
import json
import sys
import types
from pathlib import Path

import pytest

from ravel import cli
from ravel.validation import validate_task_contract as vtc
from ravel.workflow import capability_routing as cr, derived_label, intake, request_reading as rr, route_prompt

CORPUS = syn.load_json(Path(__file__).parent / 'fixtures/intake-corpus/requests.json')
CASES = {row['id']: row['prompt'] for row in CORPUS['cases']}
PROBES = ['G1', 'G2', 'G3', 'G4', 'G5']


def initiate(tmp_path, prompt, name='run'):
    output = tmp_path / name
    return cli.main(['initiate', '--prompt', prompt, '--out', str(output)]), output


def stub_plan(reading, contract, nodes):
    """A plan in the section 2.5.2 shape, as `request_plan.draft` returns it."""
    obligations = [o['id'] for o in contract['task_requirements']['obligations']]
    return {'schema_version': 1, 'kind': 'request-plan', 'prompt_sha256': reading['prompt_sha256'],
            'reading': {'path': 'inputs/reading.json', 'sha256': rr.digest(reading)},
            'signatures': {'path': 'src/ravel/data/operation_signatures.json', 'entries': {}},
            'status': 'draft', 'authors': [rr.author('local-proposer')], 'inputs': [],
            'nodes': [{'id': f'N{i + 1}', 'kind': 'operation', 'operation': op, 'implementation': impl,
                       'status': 'available', 'held_by': None, 'covers': obligations[:1], 'fields': [],
                       'rung': 'none', 'budget': {'basis': 'ceiling'}, 'placement': {'backend_plan': None},
                       'fan_out': None, 'spec_template': None,
                       'review': {'claim_scope': f'N{i + 1}', 'actions': ['delivery']}, 'authored': None,
                       'request': None} for i, (op, impl) in enumerate(nodes)],
            'edges': [], 'claims': [], 'waypoints': [], 'boundaries': [],
            'coverage': [{'obligation_id': o, 'by': ['N1']} for o in obligations[:2]],
            'aggregate_budget': {}, 'label': {'task_mode': contract['task_mode'], 'rule': 'D5', 'floor_row': 'research'}}


# ------------------------------------------------------------------ the five probes
@pytest.mark.parametrize('case', PROBES)
def test_the_five_probes_are_parents_with_no_compute_and_exit_zero(tmp_path, case, capsys):
    prompt = CASES[case]
    code, output = initiate(tmp_path, prompt)
    assert code == 0
    contract = vtc.load_contract(output / 'inputs/task_contract.json')
    assert contract['task_mode'] in ('research', 'survey') and contract['compute_plan'] == 'none'
    assert vtc.validate(contract) == [] and contract['blocking'] == []
    reading = json.loads((output / 'inputs/reading.json').read_text())
    assert rr.check(reading, prompt) == []
    out = capsys.readouterr().out
    assert 'Coverage:' in out and 'rule=D5' in out


def test_the_w_mass_question_has_no_generation_and_no_anomaly_route():
    contract, reading, label = route_prompt.route_records(CASES['G5'])
    assert contract['task_mode'] == 'research' and contract['compute_plan'] == 'none'
    assert 'generation' not in {c['value']['stage'] for c in reading['constraints'] if c['type'] == 'requested_stage'}
    assert not [o for o in contract['task_requirements']['obligations'] if o['criteria'].get('stage') == 'generation']
    vetoed = [f['value'] for f in reading['facts'] if f['type'] == 'route_hint' and f['value']['mode'] == 'anomaly_search']
    assert vetoed and all(v['strength'] == 'vetoed' for v in vetoed)
    assert label['rule'] == 'D5' and label['open']


def test_the_method_study_probe_keeps_its_storage_without_the_narrowing_text():
    contract = route_prompt.route(CASES['G4'])
    assert contract['task_mode'] == 'survey' and contract['intake']['kind'] == 'method_study'
    assert not any('Training and final statistical evaluation require' in a for a in contract['assumptions'])


# ------------------------------------------------------------------ stages, statistics and scans
def test_requested_shower_and_detector_stages_are_kept():
    r10 = route_prompt.route(CASES['R10-model-to-xsec'])
    assert r10['task_mode'] == 'research'
    assert 'detector' in {o['criteria'].get('stage') for o in r10['task_requirements']['obligations']}
    r22, _, label = route_prompt.route_records(CASES['R22-generate'])
    assert r22['task_mode'] == 'generate' and label['rule'] == 'D2' and r22['blocking'] == []
    assert 'shower' in {o['criteria'].get('stage') for o in r22['task_requirements']['obligations']}


def test_the_prescription_stays_primary():
    contract = route_prompt.route(CASES['R13-mono-tau'])
    assert contract['stat_mode'] == 'prescribed-statistic'
    assert '2-sigma excluded region' in contract['stat_mode_note']
    assert contract['escalate'][0].startswith('requested statistic:')


def test_a_measurement_fit_has_no_generation_scan():
    contract = route_prompt.route(CASES['R08-smeft-fit'])
    assert contract['compute_plan'] == 'none' and 'cost_estimate' not in contract or \
        contract['cost_estimate']['mode'] == 'none'


def test_unrequested_default_compute_is_gone():
    scan = route_prompt.route(('Reproduce the exclusion contour of ' + syn.analysis(1) + ' in the mass plane.'))
    assert scan['compute_plan'] == 'scan' and scan['cost_estimate']['points'] == 1
    assert scan['cost_estimate']['events_per_point'] is None
    assert any(e.startswith('scan grid: the request states no grid') for e in scan['escalate'])
    stated = route_prompt.route(CASES['Q38'])
    assert stated['cost_estimate']['points'] == 21


def test_no_signal_yields_value_exists():
    assert 'signal-yields' not in vtc.STAT_MODES
    source = Path(route_prompt.__file__).read_text(encoding='utf-8')
    assert 'signal-yields' not in source


# ------------------------------------------------------------------ genuine holds
@pytest.mark.parametrize('prompt,klass', [
    ('Never claim discovery.', 'no_scientific_object'),
    ('Claim discovery of a new resonance.', 'unsupportable_claim'),
    (('Context label: particle-level\nReproduce ' + syn.analysis(1) + '.'), 'ungrounded_identifier'),
    ('Use ATLAS internal Run-3 data to measure the Higgs width.', 'inaccessible_input'),
])
def test_genuine_holds_stay_unsupported_exit_one_and_say_what_would_make_them_possible(tmp_path, capsys, prompt, klass):
    contract, reading, label = route_prompt.route_records(prompt)
    assert contract['task_mode'] == 'unsupported' and label['rule'] == 'D1' and contract['blocking']
    assert klass in {b['class'] for b in reading['boundaries']}
    assert label['would_make_possible'] and all(text.strip() for text in label['would_make_possible'])
    code, output = initiate(tmp_path, prompt)
    assert code == 1
    captured = capsys.readouterr()
    assert 'would make it possible' in captured.out and 'compute_authorized=false' in captured.err
    assert (output / 'inputs/reading.json').is_file()


@pytest.mark.parametrize('case', CORPUS['cases'], ids=[row['id'] for row in CORPUS['cases']])
def test_the_router_never_emits_an_invalid_contract(case):
    contract, reading, label = route_prompt.route_records(case['prompt'])
    assert vtc.validate(contract) == []
    assert label['rule'] in derived_label.RULES
    assert (contract['task_mode'] == 'unsupported') == (label['rule'] == 'D1')


def test_only_the_six_boundary_classes_hold_the_corpus():
    held = [row['id'] for row in CORPUS['cases'] if route_prompt.route(row['prompt'])['task_mode'] == 'unsupported']
    assert held == ['Q32']


# ------------------------------------------------------------------ neutrality
@pytest.mark.parametrize('plain,labelled', [('R14-yield-template', 'R14b-yield-template-labelled'),
                                            ('U05', 'U05b'),
                                            ('R04-reinterpret', 'R24-autonomous-variant')])
def test_identity_and_delegation_phrases_do_not_change_the_label(plain, labelled):
    a = derived_label.derive(rr.document(CASES[plain]))
    b = derived_label.derive(rr.document(CASES[labelled]))
    assert a == b


def test_the_label_function_never_reads_identity_context_or_request_text():
    tree = ast.parse(Path(derived_label.__file__).read_text(encoding='utf-8'))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    constants = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docstrings]
    assert 'identity_context' not in constants
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {'neutral_text', 'routing_text', 'actionable_text'}


# ------------------------------------------------------------------ plan-aware rules
def test_the_plan_refines_the_label():
    prompt = CASES['R22-generate']
    contract, reading, _ = route_prompt.route_records(prompt)
    one = stub_plan(reading, contract, [('model-events', 'scoped')])
    two = stub_plan(reading, contract, [('model-events', 'scoped'), ('event-production', 'science-mode')])
    assert derived_label.derive(reading, one)['rule'] == 'D2'
    assert derived_label.derive(reading, two)['rule'] == 'D5'
    reproduce = ('Reproduce Figure 3 of ' + syn.analysis(1) + ' for a slepton-bino model.')
    contract, reading, label = route_prompt.route_records(reproduce)
    assert label['rule'] == 'D3' and contract['task_mode'] == 'reproduce'
    lifecycle = stub_plan(reading, contract, [('routine-recast', 'lifecycle-stage')])
    assert derived_label.derive(reading, lifecycle)['task_mode'] == 'reproduce'
    split = stub_plan(reading, contract, [('routine-recast', 'lifecycle-stage'), ('figure-comparison', 'science-mode')])
    assert derived_label.derive(reading, split)['rule'] == 'D5'


# ------------------------------------------------------------------ open route and handoff
def test_an_open_parent_takes_the_open_route_only_with_its_reading(tmp_path):
    prompt = CASES['G1']
    code, output = initiate(tmp_path, prompt)
    assert code == 0
    contract = vtc.load_contract(output / 'inputs/task_contract.json')
    reading = json.loads((output / 'inputs/reading.json').read_text())
    assert intake.handoff_route(contract) == 'research'
    assert intake.handoff_route(contract, reading) == 'open'
    handoff = json.loads((output / 'inputs/intake_handoff.json').read_text())
    assert handoff['route'] == 'open' and handoff['reading'] == 'inputs/reading.json'
    assert handoff['compute_authorized'] is False and handoff['parent_task_accepted'] is False
    assert cr.plan(prompt, contract=contract, reading=reading)['classification_status'] == 'open_parent'


def test_a_recognised_research_request_keeps_the_research_route(tmp_path):
    code, output = initiate(tmp_path, CASES['G2'])
    assert code == 0
    assert json.loads((output / 'inputs/intake_handoff.json').read_text())['route'] == 'research'


def test_a_reading_for_another_request_is_refused_by_the_handoff(tmp_path):
    code, output = initiate(tmp_path, CASES['G1'])
    other = rr.document(CASES['G3'])
    (output / 'inputs/reading.json').write_text(json.dumps(other))
    with pytest.raises(ValueError, match='does not read this request'):
        intake.read_reading(output, CASES['G1'])


# ------------------------------------------------------------------ plan seam and host additions
def test_initiate_writes_the_draft_plan_through_request_plan_draft(tmp_path, monkeypatch, capsys):
    calls = []

    def draft(reading, contract):
        calls.append((reading['prompt_sha256'], contract['task_mode']))
        return stub_plan(reading, contract, [('literature-census', 'science-mode')])
    module = types.ModuleType('ravel.workflow.request_plan')
    module.draft = draft
    monkeypatch.setitem(sys.modules, 'ravel.workflow.request_plan', module)
    import ravel.workflow
    monkeypatch.setattr(ravel.workflow, 'request_plan', module, raising=False)
    code, output = initiate(tmp_path, CASES['G3'])
    assert code == 0 and len(calls) == 1
    plan = json.loads((output / 'inputs/plan.json').read_text())
    assert plan['kind'] == 'request-plan' and plan['reading']['sha256'] == rr.digest(
        json.loads((output / 'inputs/reading.json').read_text()))
    out = capsys.readouterr().out
    assert 'covered by the draft plan' in out


def test_initiate_without_the_plan_module_refuses_before_creating_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, 'ravel.workflow.request_plan', None)
    code, output = initiate(tmp_path, CASES['G1'])
    assert code == 2 and not output.exists()
    assert 'requires a request plan' in capsys.readouterr().err


def test_reading_additions_through_interpretation_are_merged_add_only(tmp_path):
    prompt = CASES['G1']
    floor = rr.document(prompt)
    start = prompt.index('Higgs self-coupling')
    additions = {'schema_version': 1, 'kind': 'request-reading-additions', 'prompt_sha256': floor['prompt_sha256'],
                 'author': rr.author('host-agent', model='a-model'),
                 'facts': [{'id': f'F{len(floor["facts"]) + 1}', 'type': 'quantity_of_interest',
                            'value': {'text': 'Higgs self-coupling'},
                            'evidence': [rr.span(prompt, start, start + 19)], 'authority': 'user_quoted',
                            'witness': None, 'physics_critical': False}],
                 'constraints': [], 'deliverables': [], 'ambiguities': []}
    path = tmp_path / 'additions.json'
    path.write_text(json.dumps(additions))
    output = tmp_path / 'run'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(output), '--interpretation', str(path)]) == 0
    reading = json.loads((output / 'inputs/reading.json').read_text())
    assert reading['authors'][1]['model'] == 'a-model' and rr.check(reading, prompt, floor=floor) == []
    weakened = json.loads(json.dumps(reading))
    weakened['facts'] = weakened['facts'][1:]
    path.write_text(json.dumps(weakened))
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(tmp_path / 'run2'),
                     '--interpretation', str(path)]) != 0
