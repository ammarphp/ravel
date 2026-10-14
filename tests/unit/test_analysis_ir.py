"""Executable composition, independent scalar replay, and full-population custody."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.physics import analysis_ir as ir
from ravel.validation.analysis_witness import verify_bundle


def contract():
    return {'schema_version':1,'level':'reconstructed','source':'explicit analytic controls',
            'energy_unit':'GeV','flags':{'electron':{'loose':1},'muon':{'loose':1},'jet':{'b':1}},
            'response_evidence':[],'weight_names':['nominal']}


def obj(pt=30, phi=0, charge=1, eta=0, idbits=1):
    return {'pt':pt,'eta':eta,'phi':phi,'mass':0,'charge':charge,'idbits':idbits}


def events():
    selected = {'electron':[obj(),obj(phi=math.pi,charge=-1)],
                'muon':[obj(pt=50,phi=math.pi/2)],'jet':[obj(pt=100,phi=-1)]}
    return [{'event_id':'a','group_id':'shared','weights':{'nominal':1.5},'objects':deepcopy(selected),'met':{'pt':40,'phi':1}},
            {'event_id':'b','group_id':'shared','weights':{'nominal':-.5},'objects':deepcopy(selected),'met':{'pt':40,'phi':1}},
            {'event_id':'rejected-zero','group_id':'other','weights':{'nominal':0},
             'objects':{'electron':[],'muon':[],'jet':[]},'met':{'pt':0,'phi':0}}]


def program():
    # Closest OSSF mass among all leptons and MET/sqrt(HT) cannot be expressed
    # with the prior fixed reconstructed-selection variable vocabulary.
    nodes = [
        {'id':'el','op':'input','collection':'electron'},
        {'id':'mu','op':'input','collection':'muon'},
        {'id':'jets','op':'input','collection':'jet'},
        {'id':'met','op':'met'},
        {'id':'leptons','op':'concat','args':['el','mu']},
        {'id':'sorted','op':'sort','args':['leptons']},
        {'id':'pairs','op':'ossf_pairs','args':['sorted']},
        {'id':'target','op':'const','value':60,'unit':'GeV'},
        {'id':'pair','op':'best_pair','args':['pairs','target']},
        {'id':'mll','op':'pair_mass','args':['pair']},
        {'id':'pair_defined','op':'defined','args':['pair']},
        {'id':'lo','op':'const','value':59,'unit':'GeV'},
        {'id':'hi','op':'const','value':61,'unit':'GeV'},
        {'id':'low','op':'compare','args':['mll','lo'],'comparison':'ge'},
        {'id':'high','op':'compare','args':['mll','hi'],'comparison':'le'},
        {'id':'ht','op':'sum_pt','args':['jets']},
        {'id':'sqrt_ht','op':'sqrt','args':['ht']},
        {'id':'met_pt','op':'field','args':['met'],'field':'pt'},
        {'id':'recoil','op':'div','args':['met_pt','sqrt_ht']},
        {'id':'minimum','op':'const','value':2,'unit':'sqrt(GeV)'},
        {'id':'recoil_cut','op':'compare','args':['recoil','minimum'],'comparison':'gt'},
    ]
    return {'schema_version':1,'name':'custom_ossf_recoil','nodes':nodes,
            'regions':[{'name':'dilepton','cuts':['pair_defined','low','high','recoil_cut']}]}


def rehash(bundle, name):
    manifest = json.loads((bundle/'manifest.json').read_text())
    manifest['files'][name] = hashlib.sha256((bundle/name).read_bytes()).hexdigest()
    (bundle/'manifest.json').write_text(json.dumps(manifest))


def test_new_executable_pair_and_fractional_unit_composition(tmp_path):
    result = ir.evaluate_program(program(),contract(),events())
    assert result['yields']['nominal'] == [1.]
    assert result['covariance']['nominal'] == [[1.]]  # group, not independent subevent, variance
    assert result['events'] == 3
    assert result['decisions'][0]['nodes']['mll']['value'] == pytest.approx(60.)
    assert result['decisions'][0]['nodes']['recoil']['value'] == 4.
    assert result['decisions'][2]['regions'] == []
    assert result['decisions'][2]['nodes']['mll']['status'] == 'undefined'
    assert result['cutflow']['dilepton'][1]['not_reached'] == 1
    assert ir.write_bundle(result,tmp_path/'bundle')['passed']
    standalone = subprocess.run([sys.executable,'-I',str(tmp_path/'bundle/verify.py'),'--bundle',str(tmp_path/'bundle')],capture_output=True,text=True)
    assert standalone.returncode == 0, standalone.stdout+standalone.stderr
    assert json.loads(standalone.stdout)['checked_nodes'] == 3*len(program()['nodes'])


@pytest.mark.parametrize('unit',['rad','1'])
def test_dimensionally_invalid_comparison_refused_before_execution(unit):
    p = program(); p['nodes'][11]['unit'] = unit
    with pytest.raises(ValueError,match='matching dimensions'):
        ir.compile_program(p,contract())


@pytest.mark.parametrize('mutation',['missing_reject','duplicate_id','forged_mass','forged_lineage','forged_variance','forged_type'])
def test_independent_replay_rejects_coherently_rehashed_evidence(tmp_path,mutation):
    result = ir.evaluate_program(program(),contract(),events())
    bundle = tmp_path/'bundle'
    ir.write_bundle(result,bundle)
    name = 'result.json' if mutation in ('forged_variance','forged_type') else 'trace.json'
    data = json.loads((bundle/name).read_text())
    if mutation == 'missing_reject': data.pop()
    elif mutation == 'duplicate_id': data[-1]['event_id'] = 'a'
    elif mutation == 'forged_mass': data[0]['nodes']['mll']['value'] += 1
    elif mutation == 'forged_lineage': next(iter(data[0]['object_lineage'].values()))['index'] = 999
    elif mutation == 'forged_variance': data['covariance']['nominal'][0][0] = 2.5
    else: data['compiled_plan']['nodes'][9]['type']['dimension'] = ['0','0']
    (bundle/name).write_text(json.dumps(data)); rehash(bundle,name)
    rejected = verify_bundle(bundle)
    assert rejected['status'] == 'failed'
    if mutation == 'forged_mass': assert 'first divergent node: a/mll' in rejected['error']


def test_external_manifest_anchor_and_nonfinite_json(tmp_path):
    bundle = tmp_path/'bundle'
    ir.write_bundle(ir.evaluate_program(program(),contract(),events()),bundle)
    checksum = hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()
    assert verify_bundle(bundle,checksum)['source_custody'] == 'external_manifest_digest_matched'
    assert verify_bundle(bundle,'0'*64)['status'] == 'failed'
    path = bundle/'events.json'; path.write_text(path.read_text().replace('1.5','NaN'))
    rehash(bundle,'events.json')
    assert verify_bundle(bundle)['status'] == 'failed'


def test_first_difference_and_influence_are_observed_not_capacity_claims():
    a = ir.evaluate_program(program(),contract(),events())
    altered = program(); altered['nodes'][11]['value'] = 61
    b = ir.evaluate_program(altered,contract(),events())
    comparison = ir.compare_results(a,b)
    assert comparison['status'] == 'failed'
    assert all(row['first_divergent_node'] == 'lo' for row in comparison['witnesses'])
    assert comparison['change_counts'] == {'numerical_only':1,'predicate_only':0,'selection_changed':2}
    assert comparison['witnesses'][0]['first_divergent_predicate'] == 'low'
    changed_events = events(); changed_events[0]['objects']['electron'][0]['pt'] += 1
    changed = ir.evaluate_program(program(),contract(),changed_events)
    with pytest.raises(ValueError,match='input event content'): ir.compare_results(a,changed)
    closure = ir.influence_closure(a['compiled_plan'],['lo'])
    assert closure['nodes'] == ['lo','low']
    assert closure['regions'] == ['dilepton']


def test_sort_and_pair_ties_use_stable_ids_across_concat_order():
    rows = events(); rows[0]['objects']['muon'][0]['pt'] = 30
    a = program(); b = program(); b['nodes'][4]['args'] = ['mu','el']
    left, right = [ir.evaluate_program(p,contract(),rows)['decisions'][0] for p in (a,b)]
    assert left['nodes']['sorted'] == right['nodes']['sorted']
    assert left['nodes']['pair'] == right['nodes']['pair']


def test_variable_radius_and_id_conditioned_overlap(tmp_path):
    p = {'schema_version':1,'name':'overlap','nodes':[
        {'id':'e','op':'input','collection':'electron'}, {'id':'j','op':'input','collection':'jet'},
        {'id':'base','op':'const','value':.04,'unit':'1'}, {'id':'cap','op':'const','value':.4,'unit':'1'},
        {'id':'scale','op':'const','value':10,'unit':'GeV'},
        {'id':'survivors','op':'overlap_vr','args':['e','j','base','cap','scale'],'flags':{'all':['loose'],'none':[]}},
        {'id':'n','op':'count','args':['survivors']}, {'id':'one','op':'const','value':1,'unit':'1'},
        {'id':'kept','op':'compare','args':['n','one'],'comparison':'eq'}], 'regions':[{'name':'one','cuts':['kept']}]}
    row = events()[0]; row['objects']['electron'] = [obj(pt=30,eta=.2),obj(pt=30,eta=.2,idbits=0)]
    row['objects']['jet'] = [obj(pt=100,phi=0)]
    result = ir.evaluate_program(p,contract(),[row])
    assert result['raw_selected']['one'] == 1
    assert result['decisions'][0]['nodes']['n']['value'] == 1
    assert ir.write_bundle(result,tmp_path/'bundle')['passed']


def test_legacy_lowering_same_full_population_decisions(tmp_path):
    from ravel.physics.reconstructed_events import run as legacy
    definitions = {k:{'pt':20,'eta':2.5,'id':0} for k in ('electron','muon','jet')}
    selection = {'name':'fixed','objects':definitions,'signal':deepcopy(definitions),'overlap_removal':[],
                 'regions':[{'name':'dilepton','cuts':[{'var':'nLep','op':'>=','val':2},{'var':'MET','op':'>','val':30}]}]}
    for name, data in [('events',events()),('selection',selection),('contract',contract())]: (tmp_path/f'{name}.json').write_text(json.dumps(data))
    old = legacy({'events':'events.json','selection':'selection.json','object_contract':'contract.json'},tmp_path,tmp_path/'legacy')
    new = ir.evaluate_program(ir.lower_legacy_selection(selection,contract()),contract(),events())
    assert new['yields'] == old['yields']
    assert new['covariance'] == old['covariance']
    assert [r['regions'] for r in new['decisions']] == [r['regions'] for r in json.loads((tmp_path/'legacy/decisions.json').read_text())]
    assert ir.write_bundle(new,tmp_path/'bundle')['passed']


def test_limits_duplicate_objects_and_unknown_operations_refuse():
    p = program(); p['limits'] = {'max_events':1,'max_objects_per_event':256,'max_pairs_per_event':8192}
    with pytest.raises(ValueError,match='bound'): ir.evaluate_program(p,contract(),events())
    p = program(); p['nodes'][4]['args'] = ['el','el']
    with pytest.raises(ValueError,match='duplicate'): ir.evaluate_program(p,contract(),events())
    p = program(); p['nodes'][9]['op'] = 'arbitrary_cpp'
    with pytest.raises(ValueError,match='unsupported'): ir.compile_program(p,contract())


def test_science_adapter_enters_independent_verification(tmp_path):
    for name, data in [('events',events()),('program',program()),('contract',contract())]: (tmp_path/f'{name}.json').write_text(json.dumps(data))
    task = {'backend':'analysis-ir','program':'program.json','contract':'contract.json','events':'events.json'}
    assert len(ir.inputs(task,tmp_path)) == 3
    result = ir.run(task,tmp_path,tmp_path/'out')
    assert result['status'] == 'passed'
    assert result['independent_verification']['passed']
    assert result['physics_validated'] is False


def test_checker_source_imports_no_producer():
    import ast
    from ravel.validation import analysis_witness
    tree = ast.parse(Path(analysis_witness.__file__).read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert not any(name and name.startswith(('ravel','numpy','uproot')) for name in imports)


def test_independent_aplanarity_replays_three_dimensional_and_planar_events(tmp_path):
    p = {'schema_version':1,'name':'aplanarity_control','nodes':[
        {'id':'jets','op':'input','collection':'jet'},{'id':'ap','op':'aplanarity','args':['jets']},
        {'id':'cut','op':'const','value':.04,'unit':'1'},
        {'id':'pass','op':'compare','args':['ap','cut'],'comparison':'ge'}],
        'regions':[{'name':'nonplanar','cuts':['pass']}]}
    rows = events()[:2]
    rows[0]['objects']['jet'] = [obj(pt=100),obj(pt=100,phi=math.pi/2),obj(pt=1,eta=math.asinh(100))]
    rows[1]['objects']['jet'] = [obj(pt=100),obj(pt=100,phi=math.pi/2),obj(pt=100,phi=math.pi)]
    result = ir.evaluate_program(p,contract(),rows)
    assert .49 < result['decisions'][0]['nodes']['ap']['value'] < .5
    assert result['decisions'][1]['nodes']['ap']['value'] == pytest.approx(0.,abs=1e-12)
    assert result['decisions'][0]['regions'] == ['nonplanar']
    assert result['decisions'][1]['regions'] == []
    assert ir.write_bundle(result,tmp_path/'bundle')['passed']


def test_not_does_not_turn_unavailable_mass_into_acceptance(tmp_path):
    p = program(); p['nodes'].append({'id':'not_low','op':'not','args':['low']})
    p['regions'] = [{'name':'negated_mass','cuts':['not_low']}]
    result = ir.evaluate_program(p,contract(),[events()[-1]])
    assert result['decisions'][0]['nodes']['not_low']['value'] is None
    assert result['decisions'][0]['regions'] == []
    assert result['precision_status']['negated_mass'] == 'zero_selected_precision_unresolved'
    assert ir.write_bundle(result,tmp_path/'bundle')['passed']


def test_retained_near_collinear_mass_replays_declared_binary64_order(tmp_path):
    from ravel.validation import analysis_witness as checker
    # Retained CR005 event 238 exposed cancellation when subtracting a summed
    # momentum square. Preserve the original native signed m2 before sqrt.
    electrons = [
        {'pt':248.7813720703125, 'eta':0.23883743584156036, 'phi':0.1437736451625824,
         'mass':0.00051099891, 'charge':1, 'idbits':1},
        {'pt':5.308045387268066, 'eta':0.2389359325170517, 'phi':0.14374381303787231,
         'mass':0.00051099891, 'charge':-1, 'idbits':1}]
    vector = [a+b for a,b in zip(checker._four(electrons[0]),checker._four(electrons[1]))]
    signed_m2 = vector[0]*vector[0]-vector[1]*vector[1]-vector[2]*vector[2]-vector[3]*vector[3]
    assert signed_m2 == 2.6752467874757713e-05
    assert signed_m2 != vector[0]**2-sum(v*v for v in vector[1:])
    row = events()[0]; row['objects']['electron'] = electrons; row['objects']['muon'] = []
    result = ir.evaluate_program(program(),contract(),[row])
    assert result['decisions'][0]['nodes']['mll']['value'] == 0.005172278789349788
    assert result['decisions'][0]['regions'] == []
    assert ir.write_bundle(result,tmp_path/'bundle')['passed']


@pytest.mark.parametrize('excess',['coordinates','streams','work'])
def test_dense_moment_preflight_refuses_before_any_event_kernel(monkeypatch,excess):
    from ravel.validation import analysis_witness as checker
    p, c = program(), contract()
    if excess == 'coordinates':
        p['regions'] = [{'name':str(i),'cuts':['pair_defined','low','high','recoil_cut']} for i in range(64)]
    elif excess == 'streams': c['weight_names'] = ['w'+str(i) for i in range(17)]
    else:
        p['limits'] = {'max_events':100000,'max_objects_per_event':256,'max_pairs_per_event':8192}
        p['regions'] = [{'name':str(i),'cuts':['pair_defined','low','high','recoil_cut']} for i in range(7)]
    def forbidden(*args): raise AssertionError('kernel must not run before resource preflight')
    monkeypatch.setattr(ir,'_evaluate',forbidden)
    with pytest.raises(ValueError,match='moment resource bound'): ir.evaluate_program(p,c,events())
    with pytest.raises(ValueError,match='moment resource bound'):
        checker._check_contract(c); checker._check_program(p,c)


def test_within_group_catastrophic_cancellation_uses_full_stable_sum(tmp_path):
    from itertools import permutations
    c = contract(); c['weight_names'] = ['nominal','variation']
    rows = [deepcopy(events()[0]) for _ in range(3)]
    for i,row in enumerate(rows):
        row['event_id'] = str(i)
        row['weights'] = {'nominal':[1e16,1.,-1e16][i], 'variation':[-1e16,2.,1e16][i]}
    for i,order in enumerate(permutations(rows)):
        result = ir.evaluate_program(program(),c,list(order))
        assert result['yields'] == {'nominal':[1.], 'variation':[2.]}
        assert result['covariance'] == {'nominal':[[1.]], 'variation':[[4.]]}
        assert result['sumw_all_events'] == [1.,2.]
        assert result['cutflow']['dilepton'][0]['cumulative_sumw'] == {'nominal':1.,'variation':2.}
        assert ir.write_bundle(result,tmp_path/str(i))['passed']


def test_verified_exclusive_projection_keeps_original_zero_and_rejected_rows(tmp_path):
    bundle = tmp_path/'bundle'
    ir.write_bundle(ir.evaluate_program(program(),contract(),events()),bundle)
    checksum = hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()
    census = {'schema_version':1,'kind':'original_event_census',
              'records':[{'event_id':r['event_id'],'group_id':r['group_id'],'shard_id':'original'} for r in events()]}
    exported = ir.project_exclusive_regions([bundle],census,['dilepton'],manifest_sha256s=[checksum])
    assert [r['fills'] for r in exported['arm_records']] == [[[.5]],[[.5]],[]]
    assert [r['weights']['nominal'] for r in exported['arm_records']] == [1.5,-.5,0.]
    assert exported['source_binding']['bundles'][0]['verification']['source_custody'] == 'external_manifest_digest_matched'
    with pytest.raises(ValueError,match='verification failed'):
        ir.project_exclusive_regions([bundle],census,['dilepton'],manifest_sha256s=['0'*64])


def test_projection_refuses_overlapping_chosen_bins(tmp_path):
    p = program(); p['regions'].append({'name':'also','cuts':['pair_defined']})
    bundle = tmp_path/'bundle'
    ir.write_bundle(ir.evaluate_program(p,contract(),events()),bundle)
    checksum = hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()
    census = {'schema_version':1,'kind':'original_event_census',
              'records':[{'event_id':r['event_id'],'group_id':r['group_id'],'shard_id':'original'} for r in events()]}
    with pytest.raises(ValueError,match='bins overlap'):
        ir.project_exclusive_regions([bundle],census,['dilepton','also'],manifest_sha256s=[checksum])


def test_massive_transverse_mass_is_distinct_from_explicit_legacy_massless(tmp_path):
    p = {'schema_version':1,'name':'massive_mt_control','nodes':[
        {'id':'el','op':'input','collection':'electron'},{'id':'lead','op':'leading','args':['el'],'index':0},
        {'id':'met','op':'met'},{'id':'massive','op':'mt','args':['lead','met']},
        {'id':'legacy','op':'mt_massless','args':['lead','met']},{'id':'threshold','op':'const','value':40,'unit':'GeV'},
        {'id':'accept','op':'compare','args':['massive','threshold'],'comparison':'gt'},
        {'id':'old_accept','op':'compare','args':['legacy','threshold'],'comparison':'gt'}],
        'regions':[{'name':'massive','cuts':['accept']},{'name':'legacy','cuts':['old_accept']}]}
    row = events()[0]; particle = obj(pt=100); particle['mass'] = 50
    row['objects']['electron'] = [particle]; row['met'] = {'pt':100,'phi':0}
    result = ir.evaluate_program(p,contract(),[row])
    # Independent analytic case: mT² = 10000 sqrt(5) - 17500 GeV².
    assert result['decisions'][0]['nodes']['massive']['value'] == pytest.approx(math.sqrt(10000*math.sqrt(5)-17500),rel=1e-14)
    assert result['decisions'][0]['nodes']['legacy']['value'] == 0
    assert result['decisions'][0]['regions'] == ['massive']
    assert ir.write_bundle(result,tmp_path/'bundle')['passed']
    p['nodes'][3]['args'][1] = 'lead'
    with pytest.raises(ValueError,match='requires a MET'): ir.compile_program(p,contract())
