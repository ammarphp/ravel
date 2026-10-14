"""Supplied specification controls; all studies and populations are fictional."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.physics import joint_score, svj_recipe, weak_scale_mssm
from ravel.workflow import model_spectrum_plan
from ravel.workflow import finite_grid


def test_recipe_has_no_stored_axis_or_analysis_population():
    assert not hasattr(svj_recipe, 'AXES')
    source = Path(svj_recipe.__file__).read_text()
    assert "a['id']==" not in source


def test_grid_has_no_stored_population_or_parameter_relation():
    assert not hasattr(weak_scale_mssm, 'P7_VALUES')
    assert not hasattr(model_spectrum_plan, 'grid81')


def test_fit_campaign_has_no_stored_case_or_design_identity():
    assert not hasattr(joint_score, 'CASES')
    assert not hasattr(joint_score, 'DESIGN_SHA256')
    assert not hasattr(joint_score, 'SOLVER_SHA256')


def put(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def grid_document(base, *, second=False):
    source = put(base/'source.json', {'description': 'fictional source', 'values': [1, 2] if second else [1]})
    axes = [{'name': 'u', 'values': ['-2', '3', '7']}]
    if second: axes.append({'name': 'v', 'values': ['11', '12']})
    return {'schema_version': 1, 'study_id': 'STUDY-0002' if second else 'STUDY-0001',
            'axes': axes, 'bindings': [{'parameter': 'u', 'block': 'INPUT', 'codes': [1]},
                                      {'parameter': 'copy', 'block': 'INPUT', 'codes': [2]}],
            'relations': [{'parameter': 'copy', 'operation': 'affine', 'source': 'u', 'scale': '1', 'offset': '0'}],
            'source_evidence': [source], 'dataset_population': [{'id': 'DATA-0002' if second else 'DATA-0001', 'source': source}],
            'delivery': {'format': 'tsv' if second else 'json', 'filename': 'results.tsv' if second else 'results.json'}}


@pytest.fixture
def grid_adapter(monkeypatch):
    """Replace only the native provider's input loader with an inert source reader."""
    calls = []
    def load(request, base):
        pin = request['config']; path = model_spectrum_plan.custody._pin(pin, base)
        return path, json.loads(path.read_text())
    def inputs(task, base):
        path = Path(task['config']); config = json.loads(path.read_text())
        return [path, model_spectrum_plan.custody._pin(config['input_card'], path.parent)]
    monkeypatch.setattr(model_spectrum_plan, '_load', load)
    monkeypatch.setattr(model_spectrum_plan.engine, 'inputs', inputs)
    monkeypatch.setattr(model_spectrum_plan, 'graph_inputs', model_spectrum_plan.request_inputs)
    monkeypatch.setattr(model_spectrum_plan, '_card_witness', lambda config, raw: calls.append(('witness', raw)))
    import subprocess
    import platform
    monkeypatch.setattr(platform._Processor, 'get', staticmethod(lambda: 'synthetic-platform-control'))
    monkeypatch.setattr(platform, 'architecture', lambda *a, **k: ('64bit', 'synthetic-platform-control'))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('no native or external process'))
    original = model_spectrum_plan.prepare
    def prepare(request, **kwargs):
        calls.append(deepcopy(request)); return original(request, **kwargs)
    monkeypatch.setattr(model_spectrum_plan, 'prepare', prepare)
    return calls


def grid_request(base, second=False):
    document = grid_document(base, second=second)
    if second: document['bindings'].append({'parameter': 'v', 'block': 'INPUT', 'codes': [3]})
    card = base/'input.slha'; card.write_bytes(b'BLOCK INPUT # preserved\n  1   0 # coordinate\n 2 0\n 3 0\nBLOCK REMAIN\n 1 17\n')
    card_pin = {'path': str(card), 'sha256': hashlib.sha256(card.read_bytes()).hexdigest()}
    config = put(base/'config.json', {'schema_version': 2, 'profile': model_spectrum_plan.named.NAME,
                                     'source': 'Synthetic selected provider', 'input_card': card_pin, 'runtime': {}})
    from svj_fixtures import policy as review_policy
    policy = put(base/'policy.json', review_policy())
    return {'schema_version': 1, 'operation': 'parameter-grid', 'config': config, 'review_policy': policy,
            'supervisor_seconds': 1440, 'goal_binding': None, 'grid': put(base/'grid.json', document)}, document


def test_finite_grid_two_contracts_and_typed_missing_input(tmp_path, grid_adapter):
    for second in (False, True):
        base = tmp_path/('second' if second else 'first'); base.mkdir()
        request, document = grid_request(base, second)
        result = model_spectrum_plan.prepare_grid(request, base_dir=base, output_dir=base/'out')
        assert result['study_id'] == document['study_id']
        assert result['dataset_population'] == document['dataset_population']
        expected = finite_grid.parameter_grid(document)
        assert [p['coordinate'] for p in result['points']] == expected
        assert result['point_count'] == len(expected) and result['native_calls'] == 0
        assert result['resources']['aggregate_proposed_max_seconds'] == len(expected)*1440
        exported = base/'out'/document['delivery']['filename']
        if second: assert len(exported.read_text().splitlines()) == len(expected)+1
        else: assert json.loads(exported.read_text()) == result
        for point in result['points']:
            raw = Path(point['input_card']['path']).read_bytes()
            assert b'BLOCK REMAIN\n 1 17\n' in raw and b'# preserved' in raw and b'# coordinate' in raw
            assert point['coordinate']['u'] == point['coordinate']['copy']
            spec = json.loads(Path(point['specification']['path']).read_text())
            assert spec['approval_mode'] == 'physicist' and spec['max_attempts'] == 1
    bad = tmp_path/'bad'; bad.mkdir(); request, document = grid_request(bad)
    del document['bindings']; request['grid'] = put(bad/'grid.json', document)
    with pytest.raises(finite_grid.SpecificationError) as refused:
        model_spectrum_plan.prepare_grid(request, base_dir=bad, output_dir=bad/'out')
    assert refused.value.reason == 'missing_input' and refused.value.field == 'bindings'
    assert not (bad/'out').exists() and len([c for c in grid_adapter if type(c) is dict]) == 9
    assert len([c for c in grid_adapter if type(c) is tuple]) == 9


def test_grid_cards_pass_selected_provider_before_output(tmp_path, grid_adapter, monkeypatch):
    request, document = grid_request(tmp_path)
    def witness(config, raw):
        if b' 1   7 ' in raw: raise ValueError('provider refused edited card')
    monkeypatch.setattr(model_spectrum_plan, '_card_witness', witness)
    with pytest.raises(ValueError, match='provider refused'):
        model_spectrum_plan.prepare_grid(request, base_dir=tmp_path, output_dir=tmp_path/'out')
    assert not (tmp_path/'out').exists() and grid_adapter == []


def test_explicit_card_relation_migration_identity():
    raw = b'BLOCK A\n 1 17 # retained\n 2 -3\n 3 8\nBLOCK MATRIX\n 1 2 14\nDECAY 25 1e-3\n 1 2 11 -11\n'
    bindings = [{'parameter': 'p', 'block': 'A', 'codes': [1]}, {'parameter': 'q', 'block': 'A', 'codes': [2]},
                {'parameter': 'r', 'block': 'MATRIX', 'codes': [1, 2]}]
    result, changes = finite_grid.edit_card(raw, bindings, {'p': '4', 'q': '4', 'r': '-2'})
    assert result == raw.replace(b'1 17 #', b'1 4 #').replace(b'2 -3\n', b'2 4\n').replace(b'1 2 14', b'1 2 -2')
    assert len(changes) == len(bindings)


@pytest.mark.parametrize('mutation', ['duplicate_address', 'unknown_relation', 'missing_address', 'duplicate_coordinate'])
def test_finite_grid_refuses_ambiguous_inputs(tmp_path, mutation):
    document = grid_document(tmp_path)
    if mutation == 'duplicate_address': document['bindings'][1]['codes'] = [1]
    elif mutation == 'unknown_relation': document['relations'][0]['source'] = 'absent'
    elif mutation == 'duplicate_coordinate': document['axes'][0]['values'] = ['1', '1.0']
    else:
        with pytest.raises(finite_grid.SpecificationError) as refused:
            finite_grid.edit_card(b'BLOCK A\n 1 0\n', document['bindings'], {'u': '1', 'copy': '1'})
        assert refused.value.reason == 'missing_input'; return
    with pytest.raises(finite_grid.SpecificationError): finite_grid.parameter_grid(document)


def test_recipe_two_contracts_and_typed_missing_convention(tmp_path, monkeypatch):
    import test_svj_recipe as fixture
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('no native or external process'))
    for second in (False, True):
        base = tmp_path/('second' if second else 'first')
        document = fixture.fixture(base)
        if second:
            document['study_id'] = 'STUDY-0002'; document['analysis'].update(id='ANA-0002', energy_tev=9, lumi_fb=23)
            document['axes'] = [{'name': 'coordinate', 'values': [2, 5]}]
            document['coordinate_constraints'] = [{'axis': 'coordinate', 'min': 1, 'max': 10}]
            points = []
            for i, value in enumerate((2, 5)):
                p = deepcopy(document['points'][0]); p.update(id='POINT-'+str(i), coordinate={'coordinate': value})
                points.append(p)
            document['points'] = points
            document['templates'] = [{**deepcopy(c), 'point_id': p['id']} for p in points for c in document['templates']]
            # Add a rejected zero-weight original event at every response anchor.
            pin = points[0]['response']; response = json.loads(Path(pin['path']).read_text())
            for anchor in response['anchors']:
                events = json.loads(Path(anchor['events']['path']).read_text())
                event = deepcopy(events[-1]); event.update(event_id='fictional-extra', group_id='fictional-extra')
                events.append(event); anchor['events'] = fixture.ref(Path(anchor['events']['path']), events)
            updated = fixture.emit(Path(pin['path']), response)
            for point in points: point['response'] = updated
            document['delivery'] = {'format': 'tsv', 'filename': 'cells.tsv'}
        result = svj_recipe.run(fixture.task(base, document), base, base/'out')
        assert result['study_id'] == document['study_id'] and result['axes'] == document['axes']
        assert result['analysis'] == document['analysis']
        assert len(result['cells']) == len(document['templates']) and result['prepared_cells'] == len(document['templates'])
        assert result['points'][0]['response']['events'] == (6 if second else 5)
        if second: assert len((base/'out/cells.tsv').read_text().splitlines()) == len(result['cells'])+1
        else: assert json.loads((base/'out/supplied-results.json').read_text())['study_id'] == document['study_id']
    base = tmp_path/'missing'; document = fixture.fixture(base); del document['generation_conventions']
    with pytest.raises(finite_grid.SpecificationError) as refused:
        svj_recipe.run(fixture.task(base, document), base, base/'out')
    assert refused.value.reason == 'missing_input' and not (base/'out').exists()


def test_fit_campaign_two_contracts_and_typed_missing_objectives(tmp_path, monkeypatch):
    import test_joint_score_lifecycle as fixture
    for second in (False, True):
        _, fits, calls, _, capture = fixture.harness(monkeypatch)
        design = capture['design']
        if second:
            design.update(study_id='STUDY-0002', parameter_grid=[{'name': 'a', 'values': [3]}],
                          dataset_population=['DATA-0002'], delivery={'format': 'tsv', 'filename': 'fits.tsv'})
            capture['cases'] = capture['cases'][:1]; design['cases'] = design['cases'][:1]
            design['cases'][0].update(parameter_point={'a': 3}, dataset_id='DATA-0002')
            design['objectives'][1].update(id='fixed_other', fixed_mu=2.)
            design['cases'][0]['expected_free_coordinates'] = {'free_mu': 5, 'fixed_other': 4}
            design['comparisons'][0]['right'] = 'fixed_other'
        design.update(schema_version=1, solver={'path': '/synthetic/solver.py', 'sha256': 'a'*64},
                      measurement='synthetic-measurement', background_source={'path':'/synthetic/background.json','sha256':'b'*64},
                      qualification_scope={'fixed_vector_count':2, 'central_steps':[2e-5, 1e-5], 'budget_used':{}},
                      source_relocations={})
        for case in design['cases']:
            for seed in case['original_named_seeds']:
                seed['points'] = {o['id']:{'mu':o['fixed_mu'] if o['fixed_mu'] is not None else 1.,'source':{},'latent':{}} for o in design['objectives']}
        joint_score._design(design)
        out = tmp_path/('second' if second else 'first'); out.mkdir()
        result = joint_score.run({'input': 'supplied'}, tmp_path, out)
        assert result['status'] == 'passed' and result['study_id'] == design['study_id']
        assert result['parameter_grid'] == design['parameter_grid'] and result['dataset_population'] == design['dataset_population']
        assert len(fits) == len(design['cases'])*len(design['objectives'])
        assert len(calls) == result['original_seed_denominator']
        assert all(row['value'] == .5 for row in result['contrasts'])
        assert (out/design['delivery']['filename']).is_file()
    missing = deepcopy(design); del missing['objectives']
    with pytest.raises(finite_grid.SpecificationError) as refused: joint_score._design(missing)
    assert refused.value.reason == 'missing_input' and refused.value.field == 'objectives'


def test_named_seed_mapping_preserves_return_index_and_literal_coordinates():
    class Problem:
        axes = ['mu', 'source:alpha', 'mc:first']
        source = {'active_parameter_names':['alpha']}
        document = {'classes':[{'id':'first'}, {'id':'last'}]}
        def parameters(self, vector):
            return {'mu':float(vector[0]), 'source':{'alpha':float(vector[1])},
                    'latent':{'first':float(vector[2]), 'last':1.-float(vector[2])}}
    case = {'original_named_seeds':[{'id':identity, 'points':{'free':
            {'mu':1.+i, 'source':{'alpha':0.}, 'latent':{'first':.25,'last':.75}}}}
            for i,identity in enumerate(('SEED-0001','SEED-0002','SEED-0003','SEED-0004'))]}
    vectors, mapping = joint_score._starts(Problem(), case, 'free')
    assert vectors == [[1.+i,0.,.25] for i in range(4)]
    assert [r['original_seed_id'] for r in mapping] == list(range(4))
    assert [r['declared_seed_id'] for r in mapping] == [r['id'] for r in case['original_named_seeds']]
    assert all(r['declared_point'] == r['mapped_point'] for r in mapping)


def test_matching_conventions_refuse_incompatible_order_before_assets():
    convention = {'generation':{'beam_pdg':[2212,2212], 'energy_gev':[4500,4500],
                  'order':'LO', 'scheme':'fxfx','jet_multiplicities':[0,1]},
                  'shower':{'backend':'PYTHIA8','merging_scale_gev':27,'max_jets':1}}
    with pytest.raises(ValueError): svj_recipe._conventions(convention)


def test_generic_law_identity_keeps_every_qualification_and_graph_binding():
    ids = ['CASE-0001','CASE-0002','CASE-0003']
    cases = [{'id':identity,'signal_samples':{'A':['signal']},'source_bin_map':[],
              'source_bound_semantics':{},'expected_source_coordinates':2,
              'expected_free_coordinates':{'floating':4,'conditional':3}} for identity in ids]
    design = {'cases':cases,'measurement':'synthetic',
              'objectives':[{'id':'floating','fixed_mu':None},{'id':'conditional','fixed_mu':.7}],
              'qualification_scope':{'fixed_vector_count':1,'central_steps':[.00003,.00001],
                                     'budget_used':{'calls':37}}}
    law = {'schema_version':2,'execution_scope':'law_only','model_id':'MODEL-0001',
           'measurement':'synthetic','cases':[{**c,'expected_free_coordinates':4} for c in cases],
           'qualification':{'steps':[.00003,.00001]}}
    compiled = [{'case':identity,'joint':{'id':identity}} for identity in ids]
    result = {'schema_version':2,'execution_scope':'law_only','status':'passed',
              'law_qualification_passed':True,'profile_qualification_performed':False,
              'planned_fit_denominator':0,'fits':[],'model_id':'MODEL-0001',
              'qualification_budget_used':{'calls':37},
              'qualification':[{'case':identity,'passed':True,'fixed_vectors':[{'passed':True}],
                  'gradient_columns':[{'passed':True,'steps':[{'h':.00003},{'h':.00001}]} for _ in range(4)]} for identity in ids]}
    prerequisite = {'joint_contract_sha256_per_case':{r['case']:joint_score._digest(r['joint']) for r in compiled}}
    def check(design, law, result):
        compatibility = joint_score._SourceCompatibility(joint_score._COMPATIBILITY_SEAL, design, law, {}, {})
        return joint_score._law_identity(design, prerequisite, {'input':law,'result':result,'compiled':compiled}, compatibility, {})
    assert check(design, law, result) == law
    broken = deepcopy(result); broken['qualification'][1]['gradient_columns'].pop()
    with pytest.raises(ValueError, match='qualification scope'): check(design, law, broken)
    broken = deepcopy(design); broken['cases'][1]['expected_free_coordinates']['conditional'] = 2
    with pytest.raises(ValueError, match='dimensions'): check(broken, law, result)
    broken = deepcopy(result); broken['qualification_budget_used']['calls'] += 1
    with pytest.raises(ValueError, match='call census'): check(design, law, broken)


def test_incomplete_solver_seed_population_is_retained_and_refused(tmp_path, monkeypatch):
    import test_joint_score_lifecycle as fixture
    fixture.harness(monkeypatch)
    solver = joint_score._solver_module({})
    original = solver.ScoreContinuation.fit
    def omit(self, *args, **kwargs):
        returned = original(self, *args, **kwargs)
        returned['attempts'].pop()
        return returned
    monkeypatch.setattr(solver.ScoreContinuation, 'fit', omit)
    result = joint_score.run({'input':'supplied'}, tmp_path, tmp_path)
    assert result['status'] == 'unresolved'
    assert 'seed census' in result['fatal']['error']
    raw = list(tmp_path.glob('*--raw.json'))
    assert len(raw) == 1 and len(json.loads(raw[0].read_text())['attempts']) == 2
    assert not list(tmp_path.glob('*--checked.json'))




@pytest.mark.parametrize('fmt', ['json', 'tsv'])
def test_delivery_never_replaces_an_existing_output(tmp_path, fmt):
    existing = tmp_path/'journal.jsonl'; existing.write_text('custody\n')
    spec = finite_grid.delivery({'format': fmt, 'filename': 'journal.jsonl'})
    with pytest.raises(finite_grid.SpecificationError) as refused:
        finite_grid.write_delivery(tmp_path, spec, {'study_id': 'STUDY-0001'}, [{'id': 'p'}])
    assert refused.value.reason == 'invalid_input' and existing.read_text() == 'custody\n'
