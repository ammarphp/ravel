"""Fabricated exact reference decks; no fit/model/native/provider evaluation."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import pytest

from ravel.validation import numerical_reference as n


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    return pin(path)


def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def ball(mid, radius=0):
    return {'mid': mid, 'radius': radius}


def fixture(tmp_path):
    tmp_path = tmp_path.resolve()
    evidence = tmp_path / 'source.txt'
    evidence.write_text('Artificial exact arithmetic reference; no physical oracle or fitted model.\n')
    deck = {'schema_version': 1, 'kind': 'numerical-reference-deck',
        'context': {'quantity': 'two supplied response components', 'model': 'fabricated',
                    'process': 'none', 'normalization': 'literal', 'domain': '0 <= x <= 1',
                    'basis': 'artificial one-coefficient basis'},
        'axes': [{'id': 'x', 'unit': '1'}],
        'components': [{'id': c, 'unit': '1', 'convention': 'exact source response', 'atol': '0', 'rtol': '0'} for c in ('positive', 'signed')],
        'training_points': [{'id': 'train0', 'coordinates': ['0']}, {'id': 'train1', 'coordinates': ['1']}],
        'heldout_points': [{'id': 'h1', 'coordinates': ['1/4']}, {'id': 'h2', 'coordinates': ['1/2']}, {'id': 'h3', 'coordinates': ['3/4']}]}
    doc = {'schema_version': 1, 'kind': 'numerical-point-values', 'context': deepcopy(deck['context']),
           'axes': deepcopy(deck['axes']), 'components': [{k:c[k] for k in ('id','unit','convention')} for c in deck['components']],
           'rows': [{'id': p['id'], 'coordinates': p['coordinates'], 'values': {'positive': ball(v), 'signed': ball(s)}}
                    for p, v, s in zip(deck['training_points'] + deck['heldout_points'],
                        ['1','2','17/16','5/4','25/16'], ['0','-1','-1/4','-1/2','-3/4'])]}
    ref = deepcopy(doc); ref['rows'] = ref['rows'][2:]
    config = {'schema_version': 1, 'kind': 'heldout-numerical-reference-check',
        'deck': save(tmp_path/'deck.json', deck),
        'candidate': {'id': 'candidate', 'format': 'point-values/v1', 'file': save(tmp_path/'candidate.json',doc),
                      'evidence': [pin(evidence)], 'projection': None},
        'references': [{'id': 'reference', 'file': save(tmp_path/'reference.json',ref), 'evidence': [pin(evidence)]}],
        'duplicate_reference_policy': 'report'}
    save(tmp_path/'comparison.json', config)
    return {'input':'comparison.json'}, config, deck, doc, ref


def update(tmp_path, config, key, doc):
    if key == 'candidate':
        config['candidate']['file'] = save(tmp_path/'candidate.json', doc)
    elif key == 'reference':
        config['references'][0]['file'] = save(tmp_path/'reference.json', doc)
    elif key == 'deck':
        config['deck'] = save(tmp_path/'deck.json', doc)
    save(tmp_path/'comparison.json', config)


def test_complete_positive_and_independent_fraction_cell_census(tmp_path):
    task,*_ = fixture(tmp_path)
    result, _ = n.compare(task, tmp_path)
    assert result['status'] == 'passed' and result['coverage']['checked_comparisons'] == 6
    assert result['coverage']['training_ids'] == ['train0','train1']
    for cell in result['cells']:
        residual = Fraction(cell['candidate']['mid']) - Fraction(cell['reference_value']['mid'])
        assert residual == Fraction(cell['residual']) == 0
        assert Fraction(cell['excursion']) <= Fraction(cell['allowance'])
    assert not result['oracle_independence_proven'] and not result['withholding_chronology_verified']
    assert len(result['shared_candidate_reference_evidence'])==1
    assert result['configuration_source']['path']==str(tmp_path/'comparison.json')


def test_training_exact_but_heldout_wrong_is_failed_complete_population(tmp_path):
    task, config, _, doc, _ = fixture(tmp_path)
    # Only a withheld point changed. Matching all training rows does not hide it.
    doc['rows'][3]['values']['positive']['mid'] = '126/100'
    update(tmp_path, config, 'candidate', doc)
    result = n.run(task,tmp_path,tmp_path/'out')
    assert result['status'] == 'failed' and len(result['cells']) == 6
    assert result['coverage']['failed_cells'] == [{'reference':'reference','point':'h2','component':'positive'}]
    assert (tmp_path/'out/numerical-reference.json').is_file()
    assert not result['physics_validated']


def test_supplied_linear_reconstruction_matches_training_but_full_holdout_rejects(tmp_path):
    task,config,_,doc,_=fixture(tmp_path)
    # Retained table for the line through (0,1),(1,2), against the independent
    # fabricated 1+x^2 table. No regression or function evaluator is called.
    for row,value in zip(doc['rows'][2:],('5/4','3/2','7/4')):
        row['values']['positive']['mid']=value
    update(tmp_path,config,'candidate',doc)
    result,_=n.compare(task,tmp_path)
    residuals=[Fraction(c['residual']) for c in result['cells'] if c['component']=='positive']
    assert residuals==[Fraction(3,16),Fraction(1,4),Fraction(3,16)]
    assert result['status']=='failed' and len(result['coverage']['failed_cells'])==3
    assert result['coverage']['checked_comparisons']==6


@pytest.mark.parametrize('fault', ['missing_point','foreign_point','duplicate_point','wrong_coordinates','missing_component','extra_component','unit','basis','normalization','convention','extra_field'])
def test_complete_quantity_point_component_contract_refusals(tmp_path,fault):
    task,config,_,doc,_ = fixture(tmp_path)
    if fault=='missing_point': doc['rows'].pop()
    if fault=='foreign_point': doc['rows'][0]['id']='other'
    if fault=='duplicate_point': doc['rows'][1]=deepcopy(doc['rows'][0])
    if fault=='wrong_coordinates': doc['rows'][2]['coordinates']=['0.26']
    if fault=='missing_component': doc['rows'][0]['values'].pop('signed')
    if fault=='extra_component': doc['rows'][0]['values']['invented']=ball(1)
    if fault=='unit': doc['axes'][0]['unit']='GeV'
    if fault=='basis': doc['context']['basis']='different basis'
    if fault=='normalization': doc['context']['normalization']='pb instead of 1'
    if fault=='convention': doc['components'][0]['convention']='different convention'
    if fault=='extra_field': doc['rows'][0]['extra']='unserved'
    update(tmp_path,config,'candidate',doc)
    with pytest.raises(ValueError): n.inputs(task,tmp_path)


@pytest.mark.parametrize('coordinate', ['0.00','0/17','-0.0','0e-128'])
def test_physical_training_heldout_overlap_under_renamed_labels_refuses(tmp_path,coordinate):
    task,config,deck,*_ = fixture(tmp_path)
    deck['heldout_points'][0]['coordinates']=[coordinate]
    update(tmp_path,config,'deck',deck)
    with pytest.raises(ValueError,match='overlap'): n.inputs(task,tmp_path)


def test_renamed_references_and_decimal_order_changes_share_numeric_identity(tmp_path):
    task,config,_,_,ref = fixture(tmp_path)
    renamed=deepcopy(ref)
    renamed['rows'].reverse()
    for row in renamed['rows']:
        row['coordinates']=[str(float(Fraction(row['coordinates'][0])))]
        for value in row['values'].values(): value['mid']=str(float(Fraction(value['mid'])))
    config['references'].append({'id':'renamed_oracle','file':save(tmp_path/'another.json',renamed),
                                  'evidence':config['references'][0]['evidence']})
    save(tmp_path/'comparison.json',config)
    result,_=n.compare(task,tmp_path)
    assert result['duplicate_reference_payloads']==[['reference','renamed_oracle']]
    assert result['numerical_passed'] and result['status']=='passed'
    config['duplicate_reference_policy']='refuse'; save(tmp_path/'comparison.json',config)
    result,_=n.compare(task,tmp_path)
    assert result['numerical_passed'] and not result['content_policy_passed'] and result['status']=='failed'


def test_distinct_high_precision_references_do_not_collapse_through_float(tmp_path):
    task,config,_,_,ref=fixture(tmp_path)
    ref2=deepcopy(ref);ref2['rows'][0]['values']['positive']['mid']='1.0625000000000000000000000000000000000001'
    config['references'].append({'id':'tiny_shift','file':save(tmp_path/'shift.json',ref2),
                                 'evidence':config['references'][0]['evidence']})
    save(tmp_path/'comparison.json',config)
    result,_=n.compare(task,tmp_path)
    assert result['duplicate_reference_payloads']==[] and result['status']=='failed'
    shifted=next(c for c in result['cells'] if c['reference']=='tiny_shift' and c['point']=='h1' and c['component']=='positive')
    assert Fraction(shifted['residual']) == -Fraction('1e-40')


def test_relabelled_master_components_with_same_values_are_reported(tmp_path):
    task,config,_,doc,ref=fixture(tmp_path)
    for row in ref['rows']:
        row['values']['signed']=deepcopy(row['values']['positive'])
    for row in doc['rows'][2:]:
        row['values']['signed']=deepcopy(row['values']['positive'])
    update(tmp_path,config,'candidate',doc);update(tmp_path,config,'reference',ref)
    result,_=n.compare(task,tmp_path)
    assert result['status']=='passed'
    assert result['references'][0]['duplicate_component_payloads']==[['positive','signed']]
    assert not result['oracle_independence_proven']


def test_exact_zero_enclosure_zero_compatible_and_nonzero_are_distinct(tmp_path):
    task,config,_,doc,ref=fixture(tmp_path)
    for p,d in zip(ref['rows'],doc['rows'][2:]):
        p['values']['positive']=deepcopy(d['values']['positive'])
    ref['rows'][0]['values']['positive']=ball(0)
    ref['rows'][1]['values']['positive']=ball('1e-50','2e-50')
    doc['rows'][2]['values']['positive']=ball(0)
    doc['rows'][3]['values']['positive']=ball(0)
    update(tmp_path,config,'candidate',doc);update(tmp_path,config,'reference',ref)
    result,_=n.compare(task,tmp_path)
    assert result['references'][0]['zero_census']=={'exact_zero':1,'zero_compatible_enclosure':1,'nonzero':4}
    assert result['status']=='passed'
    # A large candidate radius must not get an automatic free comparison pass.
    doc['rows'][2]['values']['positive']['radius']='10';update(tmp_path,config,'candidate',doc)
    assert n.compare(task,tmp_path)[0]['status']=='failed'


def test_fixed_band_exact_boundary_and_negative_reference_relative_scale(tmp_path):
    task,config,deck,doc,ref=fixture(tmp_path)
    deck['components'][1]['atol']='.01';deck['components'][1]['rtol']='.1'
    doc['rows'][3]['values']['signed']['mid']='-0.56'
    update(tmp_path,config,'deck',deck);update(tmp_path,config,'candidate',doc)
    result,_=n.compare(task,tmp_path);assert result['status']=='passed'
    cell=next(c for c in result['cells'] if c['point']=='h2' and c['component']=='signed')
    assert Fraction(cell['engineering_band'])==Fraction('0.06')
    doc['rows'][3]['values']['signed']['mid']='-0.560000000000000001'
    update(tmp_path,config,'candidate',doc)
    assert n.compare(task,tmp_path)[0]['status']=='failed'


@pytest.mark.parametrize('value', [True,None,0.1,'NaN','1/0','1e1000000','1+0j',{'mid':'1','radius':'-1'}])
def test_numeric_grammar_and_absolute_radius_refuse(tmp_path,value):
    task,config,_,doc,_=fixture(tmp_path)
    doc['rows'][0]['values']['positive']=value if type(value) is dict else ball(value)
    update(tmp_path,config,'candidate',doc)
    with pytest.raises(ValueError): n.inputs(task,tmp_path)


@pytest.mark.parametrize('payload', ['{"schema_version":1,"schema_version":1}', '{"x":NaN}', '[[]'] )
def test_strict_json_duplicate_and_nonfinite_refuse(tmp_path,payload):
    task,config,*_=fixture(tmp_path)
    path=tmp_path/'candidate.json';path.write_text(payload)
    config['candidate']['file']=pin(path);save(tmp_path/'comparison.json',config)
    with pytest.raises(ValueError): n.inputs(task,tmp_path)


def test_complete_source_closure_changed_evidence_and_bool_size_refuse(tmp_path):
    task,config,*_=fixture(tmp_path)
    observed=n.inputs(task,tmp_path)
    assert {p.name for p in observed}=={'comparison.json','deck.json','candidate.json','reference.json','source.txt'}
    (tmp_path/'source.txt').write_text('Changed independently supplied source.')
    with pytest.raises(ValueError,match='changed'): n.inputs(task,tmp_path)
    config['candidate']['evidence'][0]=pin(tmp_path/'source.txt')
    config['references'][0]['evidence'][0]=pin(tmp_path/'source.txt')
    config['candidate']['file']['size']=True;save(tmp_path/'comparison.json',config)
    with pytest.raises(ValueError): n.inputs(task,tmp_path)


def test_changed_reference_after_classification_cannot_replace_checked_bytes(tmp_path,monkeypatch):
    task,config,*_=fixture(tmp_path)
    original=n._numeric_payload
    def mutate(*args):
        result=original(*args)
        (tmp_path/'reference.json').write_text('{}')
        return result
    monkeypatch.setattr(n,'_numeric_payload',mutate)
    with pytest.raises(ValueError,match='changed'): n.run(task,tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/numerical-reference.json').exists()


def test_postwrite_input_drift_retains_uncommitted_evidence(tmp_path,monkeypatch):
    task,*_=fixture(tmp_path);write=n.atomic_json
    def mutate(*args):
        write(*args);(tmp_path/'candidate.json').write_text('{}')
    monkeypatch.setattr(n,'atomic_json',mutate)
    with pytest.raises(ValueError,match='changed'): n.run(task,tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/numerical-reference.json').exists()
    assert (tmp_path/'out/uncommitted-numerical-reference.json').is_file()


def test_resource_caps_refuse_before_comparison(tmp_path,monkeypatch):
    task,*_=fixture(tmp_path)
    monkeypatch.setattr(n,'MAX_CELLS',9)
    with pytest.raises(ValueError,match='cell budget'):n.inputs(task,tmp_path)
    monkeypatch.setattr(n,'MAX_CELLS',64000);monkeypatch.setattr(n,'TOTAL_LIMIT',10)
    with pytest.raises(ValueError,match='resource bounds'):n.inputs(task,tmp_path)


def test_linked_or_oversized_reference_refuses(tmp_path,monkeypatch):
    task,config,*_=fixture(tmp_path)
    linked=tmp_path/'linked.json';linked.symlink_to(tmp_path/'reference.json')
    config['references'][0]['file']=pin(linked);save(tmp_path/'comparison.json',config)
    with pytest.raises(ValueError,match='ordinary'):n.inputs(task,tmp_path)
    config['references'][0]['file']=pin(tmp_path/'reference.json');save(tmp_path/'comparison.json',config)
    monkeypatch.setattr(n,'FILE_LIMIT',10)
    with pytest.raises(ValueError):n.inputs(task,tmp_path)


def eft_fixture(tmp_path):
    task,config,deck,_,_=fixture(tmp_path)
    # Existing public eft-functions result schema, fabricated retained values.
    # No source parser/evaluator or model code is invoked in this test.
    source=tmp_path/'model.py';source.write_text('# Fabricated source identity only; never executed.\n')
    card=tmp_path/'card.txt';card.write_text('Fabricated card identity only; never parsed.\n')
    def oldpin(p):return {k:v for k,v in pin(p).items() if k!='size'}
    cfg={'schema_version':1,'model':oldpin(source),'cards':[oldpin(card)],'coefficient_unit':'1',
         'one_coefficient_basis':deck['context']['basis'],
         'evaluation_points':['0','1','1/4','1/2','3/4']}
    cp=save(tmp_path/'eft-config.json',cfg)
    doc=json.loads((tmp_path/'candidate.json').read_text())
    eft={'status':'passed','physics_validated':False,'scope':'Retained fabricated exact response',
         'coefficient_unit':'1','one_coefficient_basis':deck['context']['basis'],
         'model':{'source_sha256':pin(source)['sha256'],'domain':{'name':'x'},'functions':{'f':{},'g':{}}},
         'cards':[{'sha256':pin(card)['sha256']}], 'algebra_witness':{'passed':True},
         'evaluations':[{'point':r['coordinates'][0],'scales':{'f':r['values']['positive']['mid'],'g':r['values']['signed']['mid']}} for r in doc['rows']],
         'limitations':['Fabricated public format control']}
    config['candidate']['format']='eft-functions/v1'
    config['candidate']['projection']={'configuration':cp,'component_map':{'positive':'f','signed':'g'}}
    update(tmp_path,config,'candidate',eft)
    return task,config,eft,cfg


def test_real_existing_eft_delivery_format_consumer_without_evaluator(tmp_path):
    task,*_=eft_fixture(tmp_path)
    result,_=n.compare(task,tmp_path)
    assert result['status']=='passed' and result['coverage']['checked_comparisons']==6
    assert {p.name for p in n.inputs(task,tmp_path)} >= {'eft-config.json','model.py','card.txt'}


@pytest.mark.parametrize('fault',['omitted_scale','foreign_point','source','card','mapping','configured_deck','unit','basis'])
def test_eft_retained_complete_mapping_and_origin_refusals(tmp_path,fault):
    task,config,doc,cfg=eft_fixture(tmp_path)
    if fault=='omitted_scale':doc['evaluations'][0]['scales'].pop('g')
    if fault=='foreign_point':doc['evaluations'][0]['point']='2'
    if fault=='source':doc['model']['source_sha256']='0'*64
    if fault=='card':doc['cards'][0]['sha256']='0'*64
    if fault=='mapping':config['candidate']['projection']['component_map']['signed']='f'
    if fault=='configured_deck':cfg['evaluation_points'].pop()
    if fault=='unit':doc['coefficient_unit']='TeV^-4'
    if fault=='basis':doc['one_coefficient_basis']='different'
    config['candidate']['projection']['configuration']=save(tmp_path/'eft-config.json',cfg)
    update(tmp_path,config,'candidate',doc)
    with pytest.raises(ValueError):n.inputs(task,tmp_path)


def specification(task):
    return {'schema_version':2,'mode':'numerical-reference-check','source':'Fabricated exact reference-deck control',
      'assumptions':['Supplied point values only; no model evaluation or independence proof'],
      'max_seconds':30,'max_attempts':1,'approval_mode':'scripted_yes','task':task,
      'review_policy':{'schema_version':1,'policy':{'schema_version':1,
        'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'numeric','kind':'scientific'}],
        'claim_scopes':{n.SCOPE:{'checks':['integrity','numeric'],'actions':['delivery','reuse']}}},
        'correction_contract':{'task_fields':[],'input_slots':[]}}}


def test_actual_ordinary_plan_has_complete_graph_and_requires_v2(tmp_path):
    from ravel.workflow import science
    task,*_=fixture(tmp_path);spec=specification(task)
    save(tmp_path/'science.json',spec)
    result=science.plan(tmp_path/'planned',tmp_path/'science.json')
    assert science.adapter(spec) is n and science._new_capability(spec)
    assert not (tmp_path/'planned/inputs/science-approval.json').exists()
    captured=json.loads((tmp_path/'planned/inputs/science-plan.json').read_text())
    captured_paths = captured['stage_binding']['input_snapshot']
    assert {str(p) for p in n.inputs(task,tmp_path)} <= set(captured_paths)
    spec.pop('review_policy');spec['schema_version']=1;save(tmp_path/'old.json',spec)
    with pytest.raises(ValueError):science.plan(tmp_path/'old',tmp_path/'old.json')


@pytest.mark.parametrize('wrong', [False,True])
@pytest.mark.parametrize('format', ['generic','eft'])
def test_real_worker_adapter_report_lifecycle_with_mocked_authority_only(tmp_path,monkeypatch,wrong,format):
    from ravel.workflow import science
    from ravel.physics import science_worker
    if format=='eft':
        task,config,doc,_=eft_fixture(tmp_path)
    else:
        task,config,_,doc,_=fixture(tmp_path)
    if wrong:
        if format=='eft':doc['evaluations'][2]['scales']['f']='999'
        else:doc['rows'][2]['values']['positive']['mid']='999'
        update(tmp_path,config,'candidate',doc)
    spec=specification(task);rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    proposal={'schema_version':2,'base_dir':str(tmp_path.resolve()),'attempt':1,
              'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}}
    save(rd/'inputs/science-plan.json',proposal);save(rd/'inputs/science.json',spec)
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal)
    monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    code=science_worker.main([str(rd),'--attempt','1'])
    assert code==(3 if wrong else 0)
    out=rd/'outputs/attempt-1'
    result=json.loads((out/'result.json').read_text())
    assert result==json.loads((out/'numerical-reference-check/numerical-reference.json').read_text())
    assert (out/'numerical-reference-report.md').is_file()
    ci=json.loads((out/'checkin2.json').read_text())
    assert ci['sections']['waypoint']['status_scope']==n.SCOPE
    assert not ci['sections']['waypoint']['oracle_independence_proven']
    assert json.loads((out/'figures.json').read_text())['figures']==[]
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])


def test_no_implicit_physics_oracle_authority_transfer(tmp_path):
    from ravel.physics.science_worker import diagnostic_presentation
    task,*_=fixture(tmp_path);result,_=n.compare(task,tmp_path)
    for key in ('physics_validated','oracle_independence_proven','withholding_chronology_verified'):
        bad=deepcopy(result);bad[key]=True
        with pytest.raises(ValueError):diagnostic_presentation('numerical-reference-check',bad)
