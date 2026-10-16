"""Fictional convention records and inert generation/statistics boundary checks."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.physics import generation_conventions as g


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.write_text(json.dumps(value))
    return pin(path)


def record(tmp_path, constraint='NP<=1', groups=None):
    path = tmp_path / 'process.dat'
    raw = 'generate a a > b b ' + constraint + '\n'
    path.write_text(raw)
    return g.build(raw, pin(path), {'identifier': 'model_alpha', 'pin': '1'*64, 'restriction': 'full'},
                   {'basis_identifier': 'basis_alpha', 'ew_input_scheme': 'scheme_alpha',
                    'validity_cutoff': 'none declared', 'operator_groups': groups or {'NP': ['ca', 'cb']}})


def semantic(tmp_path, rec, quadratic=True):
    return {'eft': {'target_basis': ['ca', 'cb'], 'linear': True, 'quadratic': quadratic,
                    'mixed_pairs': [['ca', 'cb']] if quadratic else [],
                    'basis_identifier': 'basis_alpha', 'ew_input_scheme': 'scheme_alpha',
                    'validity_cutoff': 'none declared'},
            'generation_coherence': {'record': save(tmp_path / 'record.json', rec), 'exception': None}}


@pytest.mark.parametrize('syntax,level,comparison,value,terms', [
    ('NP^2==1', 'squared', '==', 1, [['ca'], ['cb']]),
    ('NP^2<=1', 'squared', '<=', 1, [[], ['ca'], ['cb']]),
    ('NP^2<=2', 'squared', '<=', 2, [[], ['ca'], ['cb'], ['ca','ca'], ['ca','cb'], ['cb','cb']]),
    ('NP<=1', 'amplitude', '<=', 1, [[], ['ca'], ['cb'], ['ca','ca'], ['ca','cb'], ['cb','cb']]),
    ('NP=1', 'amplitude', '<=', 1, [[], ['ca'], ['cb'], ['ca','ca'], ['ca','cb'], ['cb','cb']]),
    ('NP==1', 'amplitude', '==', 1, [['ca','ca'], ['ca','cb'], ['cb','cb']]),
    ('NP^2==2', 'squared', '==', 2, [['ca','ca'], ['ca','cb'], ['cb','cb']]),
    ('NP=0', 'amplitude', '<=', 0, [[]]),
])
def test_literal_order_semantics(tmp_path, syntax, level, comparison, value, terms):
    rec = record(tmp_path, syntax)
    order = rec['processes'][0]['constraints'][0]
    assert order == {'group':'NP', 'level':level, 'comparison':comparison, 'value':value, 'raw':syntax}
    assert rec['terms'] == terms
    assert syntax in rec['raw_process_card']


def test_continuations_comments_multiple_processes_and_orders():
    raw = 'import model model_alpha\r\ngenerate a a > b b QCD=2 NP^2\\\r\n==0 # NP<=7\r\nadd process a a > b b NP ^ 2 <= 1 @2\n'
    rows = g.parse_process_card(raw)
    assert len(rows) == 2
    assert rows[0]['constraints'][1]['level'] == 'squared'
    assert rows[1]['constraints'][0]['value'] == 1
    assert g.implied_terms(rows, {'NP':['ca']}) == [[], ['ca']]


@pytest.mark.parametrize('syntax', ['NP^3==1', 'NP^2==1.5', 'NP<=1 NP=0'])
def test_unparsed_or_duplicate_constraint_refused(syntax):
    with pytest.raises(ValueError):
        g.parse_process_card('generate a a > b b ' + syntax)


def test_decay_chain_subprocess_orders_recorded_but_undeclared():
    rows = g.parse_process_card('generate a a > b b QED=0, b > c d QED=1 NP<=1\n')
    assert [o['raw'] for o in rows[0]['constraints']] == ['QED=0', 'QED=1', 'NP<=1']
    assert g.implied_terms(rows, {'NP':['ca']}) is None


def test_amplitude_and_squared_constraints_intersect(tmp_path):
    rec = record(tmp_path, 'NP<=1 NP^2<=1')
    assert rec['terms'] == [[], ['ca'], ['cb']]


def test_unbounded_or_joint_higher_orders_are_flagged(tmp_path):
    assert record(tmp_path, 'NP<=2')['terms'] is None
    assert record(tmp_path, 'NP<=1 NX<=1', {'NP':['ca'], 'NX':['cb']})['terms'] is None
    assert record(tmp_path, 'NP<=1', {'NX':['ca']})['terms'] is None


def test_matching_generation_and_fit(tmp_path):
    sem = semantic(tmp_path, record(tmp_path))
    verdict = g.check_fit(sem, tmp_path)
    assert verdict['status'] == 'matched'
    assert set(verdict['paths']) == {tmp_path/'record.json', tmp_path/'process.dat'}


@pytest.mark.parametrize('generation,quadratic,pattern', [
    ('NP^2<=1', True, 'fit adds'), ('NP<=1', False, 'fit omits'),
    ('NP^2==1', False, 'fit adds'),
])
def test_term_population_mismatch_refused(tmp_path, generation, quadratic, pattern):
    sem = semantic(tmp_path, record(tmp_path, generation), quadratic)
    with pytest.raises(ValueError, match=pattern):
        g.check_fit(sem, tmp_path)


def test_declared_truncation_must_record_exact_effect(tmp_path):
    rec = record(tmp_path)
    sem = semantic(tmp_path, rec, False)
    ex = {'kind':'declared_truncation', 'generation_sha256':g.digest(rec), 'fit':g.fit_convention(sem),
          'reason':'Study retains response through degree one.',
          'effect':'Drops ca squared, cb squared and ca cb response; higher order sensitivity is excluded.'}
    sem['generation_coherence']['exception'] = save(tmp_path/'exception.json', ex)
    verdict = g.check_fit(sem, tmp_path)
    assert 'terms' in verdict['differences']
    assert ex['effect'] in verdict['flags'][0]
    ex['effect'] = ''
    sem['generation_coherence']['exception'] = save(tmp_path/'exception.json', ex)
    with pytest.raises(ValueError, match='effect'):
        g.check_fit(sem, tmp_path)


def test_truncation_cannot_add_terms(tmp_path):
    rec = record(tmp_path, 'NP^2<=1'); sem = semantic(tmp_path, rec)
    ex = {'kind':'declared_truncation', 'generation_sha256':g.digest(rec), 'fit':g.fit_convention(sem),
          'reason':'Fictional control.', 'effect':'Adds missing terms.'}
    sem['generation_coherence']['exception'] = save(tmp_path/'exception.json', ex)
    with pytest.raises(ValueError, match='only remove'):
        g.check_fit(sem, tmp_path)


@pytest.mark.parametrize('field,new', [('ew_input_scheme','scheme_beta'), ('basis_identifier','basis_beta'),
                                      ('validity_cutoff','energy < 900 GeV')])
def test_convention_mismatch_refused(tmp_path, field, new):
    sem = semantic(tmp_path, record(tmp_path)); sem['eft'][field] = new
    with pytest.raises(ValueError, match=field):
        g.check_fit(sem, tmp_path)


@pytest.mark.parametrize('side', ['generation', 'fit', 'both'])
def test_undeclared_scheme_is_flag_not_match(tmp_path, side):
    rec = record(tmp_path)
    if side in ('generation','both'):
        rec['ew_input_scheme'] = None
    sem = semantic(tmp_path, rec)
    if side in ('fit','both'):
        del sem['eft']['ew_input_scheme']
    result = g.check_fit(sem, tmp_path)
    assert result['status'] == 'flagged'
    assert 'ew_input_scheme undeclared' in result['flags'][0]


def test_undeclared_generation_and_model_name_do_not_fill_scheme(tmp_path):
    rec = record(tmp_path)
    raw = rec['raw_process_card']
    empty = g.build(raw, rec['process_card'], rec['model'])
    assert empty['basis_identifier'] is empty['ew_input_scheme'] is empty['validity_cutoff'] is empty['terms'] is None
    sem = semantic(tmp_path, empty)
    assert g.check_fit(sem, tmp_path)['status'] == 'flagged'
    del sem['generation_coherence']
    assert 'record undeclared' in g.check_fit(sem, tmp_path)['flags'][0]


def test_changed_generation_card_and_forged_terms_refused(tmp_path):
    rec = record(tmp_path); sem = semantic(tmp_path, rec)
    (tmp_path/'process.dat').write_text('generate a a > b b NP^2<=1\n')
    with pytest.raises(ValueError, match='pin changed'):
        g.check_fit(sem, tmp_path)
    rec = record(tmp_path); rec['terms'] = [[], ['ca'], ['cb']]
    sem = semantic(tmp_path, rec, False)
    with pytest.raises(ValueError, match='differs from actual'):
        g.check_fit(sem, tmp_path)


def test_receipt_embeds_same_record(tmp_path):
    rec = record(tmp_path); sem = semantic(tmp_path, rec)
    sem['generation_coherence']['record'] = save(tmp_path/'receipt.json', {'generation_convention':rec})
    assert g.check_fit(sem, tmp_path)['status'] == 'matched'


def test_recorded_deviation_is_exact_and_disclosed(tmp_path):
    rec = record(tmp_path); sem = semantic(tmp_path, rec)
    sem['eft']['ew_input_scheme'] = 'scheme_beta'
    ex = {'kind':'deviation', 'generation_sha256':g.digest(rec), 'fit':g.fit_convention(sem),
          'reason':'Supplied study exception.', 'effect':'Retains the declared scheme inconsistency in the result scope.'}
    sem['generation_coherence']['exception'] = save(tmp_path/'exception.json', ex)
    assert 'recorded deviation' in g.check_fit(sem, tmp_path)['flags'][0]
    sem['eft']['ew_input_scheme'] = 'scheme_gamma'
    with pytest.raises(ValueError, match='bind exact'):
        g.check_fit(sem, tmp_path)


def test_transport_requires_existing_ordinary_approval(tmp_path, monkeypatch):
    from ravel.workflow import science
    from ravel.physics import eft_conventions
    from test_eft_conventions import fixture
    rd = tmp_path/'transport'
    task, _, poly, mapping = fixture(rd)
    (rd/'outputs').mkdir()
    result = eft_conventions.compile_transport(task, rd)
    outcome = rd/'outputs/eft-convention-transport.json'
    save(outcome, result)
    rec = record(tmp_path, groups={'NP':['c1','c2']})
    rec['basis_identifier'] = poly['convention']['basis']
    sem = semantic(tmp_path, rec)
    sem['eft'].update(target_basis=['a','b'], mixed_pairs=[['a','b']],
                      basis_identifier=mapping['target_convention']['basis'])
    fit = g.fit_convention(sem)
    ex = {'kind':'convention_transport', 'generation_sha256':g.digest(rec), 'fit':fit,
          'reason':'Supplied real invertible coordinate map.', 'effect':'Changes declared coordinate basis.',
          'approval_run':str(rd), 'transport_request':pin(Path(task['request'])), 'transport_result':pin(outcome)}
    sem['generation_coherence']['exception'] = save(tmp_path/'exception.json', ex)
    # Only ordinary lifecycle authority is an inert seam; actual algebra is recomputed.
    def approved(root, approved=False):
        assert root == rd and approved is True
        return {'output_directory':'outputs'}
    monkeypatch.setattr(science, 'verify_plan', approved)
    monkeypatch.setattr(science, 'execution_spec', lambda root:{'mode':'eft-convention-transport','task':task})
    assert g.check_fit(sem, tmp_path)['status'] == 'flagged'
    result['observables'][0]['linear'][0]['data'] = ['123']
    ex['transport_result'] = save(outcome, result)
    sem['generation_coherence']['exception'] = save(tmp_path/'exception.json', ex)
    with pytest.raises(ValueError, match='current exact source'):
        g.check_fit(sem, tmp_path)
    def refused(*args, **kwargs):
        raise ValueError('missing or stale study approval')
    monkeypatch.setattr(science, 'verify_plan', refused)
    with pytest.raises(ValueError, match='stale study approval'):
        g.check_fit(sem, tmp_path)


def test_native_model_events_card_builder_records_squared_syntax(tmp_path):
    from test_model_events import config, texts
    from ravel.physics import model_events
    c = config(tmp_path)
    path = Path(c['cards']['process']['path'])
    path.write_text(path.read_text().rstrip() + ' NP^2<=1\n')
    c['cards']['process'] = pin(path)
    c['conventions'] = {'operator_groups':{'NP':['ca']}}
    assert model_events.process_commands(texts(c)['process'], c)
    assert g.model_events_record(c, texts(c)['process'])['terms'] == [[], ['ca']]


def test_checkin_discloses_generation_and_missing_fit_record(tmp_path):
    from test_model_events import config
    c = config(tmp_path)
    cp = tmp_path/'configuration.json'; save(cp, c)
    result = g.checkin({'mode':'model-events','task':{'config':str(cp)}}, tmp_path)
    assert result['generation_convention']['model']['restriction'] == 'full'
    assert any('ew_input_scheme' in flag for flag in result['flags'])


def test_convention_handoff_refuses_generation_square_with_linear_fit(tmp_path):
    from test_sfitter_adapter import workflow_fixture
    from ravel.workflow import sfitter_workflow as workflow
    request, docs, config = workflow_fixture(tmp_path)
    sp = Path(config['semantic_manifest']['path']); sem = json.loads(sp.read_text())
    rec = record(tmp_path, groups={'NP':sem['eft']['target_basis']})
    sem['eft'].update(basis_identifier='basis_alpha', ew_input_scheme='scheme_alpha', validity_cutoff='none declared')
    sem['generation_coherence'] = {'record':save(tmp_path/'generation.json', rec), 'exception':None}
    docs['conventions']['payload']['semantic_manifest'] = save(sp, sem)
    with pytest.raises(ValueError, match='fit omits'):
        workflow._handoff(request, docs['conventions'], tmp_path, 'conventions')


def test_native_statistics_refuses_square_population_even_with_valid_card(tmp_path, monkeypatch):
    import test_sfitter_adapter as fixture
    from ravel.physics import sfitter_native
    monkeypatch.setenv(sfitter_native.UPSTREAM_CENSUS_ENV, str(fixture._CENSUS))
    task, config, card, sem, _ = fixture.fixture(tmp_path)
    rec = record(tmp_path, groups={'NP':sem['eft']['target_basis']})
    sem['eft'].update(basis_identifier='basis_alpha', ew_input_scheme='scheme_alpha', validity_cutoff='none declared')
    sem['generation_coherence'] = {'record':save(tmp_path/'generation.json', rec), 'exception':None}
    config['semantic_manifest'] = save(Path(config['semantic_manifest']['path']), sem)
    save(Path(task['config']), config)
    with pytest.raises(ValueError, match='fit omits'):
        sfitter_native.inputs(task, tmp_path)


def test_complete_statistics_uses_same_coherence_check(tmp_path):
    from sfitter_complete_fixture import source, configuration
    from ravel.physics import sfitter_complete_native
    root = source(tmp_path)
    task, config = configuration(tmp_path, root)
    sp = Path(config['semantic_manifest']['path']); sem = json.loads(sp.read_text())
    rec = record(tmp_path, groups={'NP':sem['eft']['target_basis']})
    sem['eft'].update(basis_identifier='basis_alpha', ew_input_scheme='scheme_alpha', validity_cutoff='none declared')
    sem['generation_coherence'] = {'record':save(tmp_path/'generation.json', rec), 'exception':None}
    config['semantic_manifest'] = save(sp, sem)
    save(Path(task['config']), config)
    with pytest.raises(ValueError, match='fit omits'):
        sfitter_complete_native.inputs(task, tmp_path)


def test_scoped_card_planning_and_receipt_retain_conventions(tmp_path):
    from test_scoped_generation_front_end import native, lepton_spec, plan, execute
    from ravel.workflow.state_io import read_json
    runtime = native(tmp_path)
    spec = lepton_spec(runtime, process='e+ u > e+ u NP=1', conventions={
        'basis_identifier':'basis_alpha', 'ew_input_scheme':'scheme_alpha',
        'validity_cutoff':'none declared', 'operator_groups':{'NP':['ca']}})
    rd, proposal = plan(tmp_path, spec)
    assert proposal['generation_convention']['terms'] == [[], ['ca'], ['ca','ca']]
    assert proposal['generation_convention']['model']['pin'] == proposal['model_source_sha256']
    execute(rd)
    receipt = read_json(rd/'outputs/generation-receipt.json')
    assert receipt['generation_convention']['terms'] == [[], ['ca'], ['ca','ca']]
    assert receipt['generation_convention']['model'] == proposal['generation_convention']['model']
    assert pin(Path(receipt['generation_convention']['process_card']['path'])) == receipt['generation_convention']['process_card']


def test_card_cannot_claim_squares_in_manifest_and_ignore_them(tmp_path):
    rec = record(tmp_path); sem = semantic(tmp_path, rec)
    card = {'predictions':[{'modifiers':[{'name':'ca'}, {'name':'cb'}]}]}
    with pytest.raises(ValueError, match='card omits declared semantic terms'):
        g.check_fit(sem, tmp_path, card=card)
    card['predictions'][0]['modifiers'] += [{'name':name} for name in ('caxca','caxcb','cbxcb')]
    assert g.check_fit(sem, tmp_path, card=card)['status'] == 'matched'
