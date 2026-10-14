"""Synthetic admission/record arithmetic; no MG5/UFO/native execution."""
from copy import deepcopy
import itertools
import math
from pathlib import Path

import pytest
from ravel.physics import model_ward as ward
from ravel.workflow import science

ROOT=Path(__file__).resolve().parents[1]
ZERO='BLOCK MASS\n 6 2\nDECAY 6 0\n'
ORIGINAL='BLOCK MASS\n 6 2\nDECAY 6 1\n'

def complex_value(value):
    return {'real':value,'imag':0.}

def snapshot():
    return {'external_parameters':[
        {'name':'MT','block':'mass','codes':[6],'observed_value':complex_value(2.)},
        {'name':'WT','block':'decay','codes':[6],'observed_value':complex_value(0.)}],
        'parameters':{'MT':complex_value(2.),'WT':complex_value(0.),'ZERO':complex_value(0.)},
        'couplings':{'GC':complex_value(1.)}}

@pytest.fixture
def config():
    return {'energy_gev':10.,'seeds':[19,101], 'processes':[
        {'id':'gg_to_top_pair','initial_pdgs':[21,21],'final_pdgs':[6,-6],
         'orders':{'QCD':2,'QED':0},'forbidden_pdgs':[]}]}

@pytest.fixture
def native(config):
    point=[[5.,0.,0.,5.],[5.,0.,0.,-5.],[5.,math.sqrt(21.),0.,0.],[5.,-math.sqrt(21.),0.,0.]]
    cases=[]
    for seed in config['seeds']:
        for mapping in ward.MAPS:
            evaluations=[]
            for gauge in (True,False):
                evaluations.append({'gauge_check':gauge,'momenta_gev':[point[i-1] for i in mapping],
                    'ordered_leg_pdgs':[21,21,6,-6],'ordered_leg_states':[False,False,True,True],
                    'effective_orders':{'QCD':2,'QED':0},'effective_forbidden_pdgs':[],
                    'effective_perturbation_couplings':[],'effective_masses_gev':{'21':0.,'6':2.,'-6':2.},
                    'model_point':snapshot(),'helicities':list(map(list,itertools.product((-1,1),repeat=4))),
                    'colour_basis':['basis0','basis1'],'sample':{'m2':1e-20 if gauge else 2.,
                        'jamp':[[complex_value(1e-10 if gauge else 1.) for _ in range(2)] for _ in range(16)]}})
            cases.append({'seed':seed,'local_to_original_slots':mapping,'original_momenta_gev':point,
                'actual_ward_calls':[{'local_slot':1,'original_slot':mapping[0],
                    'generated_call':'w[0] = vxxxxx(p[0], ZERO, 4, -1)'}],
                'evaluations':evaluations,'reuse_generated_matrix':False,'discarded_generated_globals':['Matrix_gg_tt','data']})
    return {'restriction_applied':False,'generated_events':0,
        'polarization_normalization':'massless_vxxxxx_nhel4_is_p_over_E',
        'total_ratio_limit':1e-10,'colour_ratio_limit':1e-15,'model_point':snapshot(),'cases':cases}

def test_exact_private_source_and_connected_route():
    expected=(ROOT/'candidate/src/ravel/physics/model_ward.py' if (ROOT/'candidate/src').is_dir()
              else Path(__file__).resolve().parents[2]/'src/ravel/physics/model_ward.py')
    assert Path(ward.__file__).resolve()==expected
    assert science.adapter({'mode':'model-ward','task':{'config':'explicit'}}) is ward
    assert 'model-ward' in science.MODES

def test_complete_synthetic_two_slot_population(native,config):
    answer=ward.adjudicate(native,config,ZERO)
    assert answer['passed'] and len(answer['checks'])==4
    assert answer['observed_original_slots_per_seed']=={'19':[1,2],'101':[1,2]}
    assert answer['physics_validated'] is False

def test_original_installed_thresholds_are_not_relaxed(native,config):
    native['cases'][0]['evaluations'][0]['sample']['m2']=2.0000001e-10
    assert not ward.adjudicate(native,config,ZERO)['passed']
    native['cases'][0]['evaluations'][0]['sample']['m2']=0.
    native['cases'][0]['evaluations'][0]['sample']['jamp'][0][0]['real']=1e-6
    assert not ward.adjudicate(native,config,ZERO)['passed']

@pytest.mark.parametrize('fault',[
    'restriction','events','polarization','total_threshold','colour_threshold','missing_case','duplicate_case',
    'reuse','no_discard','evaluation_order','resampled_point','off_shell','changed_process','changed_mass',
    'changed_card','changed_coupling','changed_internal','missing_helicity','duplicate_helicity','ragged_jamp',
    'missing_colour','duplicate_colour','foreign_colour','missing_call','wrong_original_slot','wrong_call',
    'duplicate_original_slot','foreign_seed','zero_denominator','nan','different_anchor','exchange'])
def test_adverse_retained_population_refusals(native,config,fault):
    row=native['cases'][0]; brs,physical=row['evaluations']
    if fault=='restriction':native['restriction_applied']=True
    elif fault=='events':native['generated_events']=1
    elif fault=='polarization':native['polarization_normalization']='p'
    elif fault=='total_threshold':native['total_ratio_limit']=1e-9
    elif fault=='colour_threshold':native['colour_ratio_limit']=1e-14
    elif fault=='missing_case':native['cases'].pop()
    elif fault=='duplicate_case':native['cases'][-1]=deepcopy(row)
    elif fault=='reuse':row['reuse_generated_matrix']=True
    elif fault=='no_discard':row['discarded_generated_globals']=[]
    elif fault=='evaluation_order':row['evaluations'].reverse()
    elif fault=='resampled_point':brs['momenta_gev']=deepcopy(brs['momenta_gev']);brs['momenta_gev'][2][1]*=-1
    elif fault=='off_shell':brs['effective_masses_gev']['6']=3.
    elif fault=='changed_process':brs['effective_orders']['QCD']=3
    elif fault=='changed_mass':brs['ordered_leg_pdgs'][-1]=5
    elif fault=='changed_card':brs['model_point']['external_parameters'][0]['observed_value']['real']=3.
    elif fault=='changed_coupling':brs['model_point']['couplings']['GC']['real']=2.
    elif fault=='changed_internal':physical['model_point']['parameters']['extra']=complex_value(3.)
    elif fault=='missing_helicity':brs['helicities'].pop()
    elif fault=='duplicate_helicity':brs['helicities'][-1]=brs['helicities'][0]
    elif fault=='ragged_jamp':brs['sample']['jamp'][0].pop()
    elif fault=='missing_colour':brs['colour_basis']=[]
    elif fault=='duplicate_colour':brs['colour_basis']=['basis0','basis0']
    elif fault=='foreign_colour':physical['colour_basis']=['basis0','foreign']
    elif fault=='missing_call':row['actual_ward_calls']=[]
    elif fault=='wrong_original_slot':row['actual_ward_calls'][0]['original_slot']=2
    elif fault=='wrong_call':row['actual_ward_calls'][0]['generated_call']='vxxxxx(p[1], ZERO, 4, -1)'
    elif fault=='duplicate_original_slot':native['cases'][1]['actual_ward_calls'][0].update(local_slot=2,original_slot=1,generated_call='vxxxxx(p[1], ZERO, 4, -1)')
    elif fault=='foreign_seed':row['seed']=20
    elif fault=='zero_denominator':physical['sample']['m2']=0.
    elif fault=='nan':brs['sample']['jamp'][0][0]['real']=float('nan')
    elif fault=='different_anchor':
        other=native['cases'][1]; other['original_momenta_gev']=deepcopy(other['original_momenta_gev'])
        for p in other['original_momenta_gev'][2:]:p[1]*=-1
        for evaluation in other['evaluations']:evaluation['momenta_gev']=[other['original_momenta_gev'][i-1] for i in other['local_to_original_slots']]
    elif fault=='exchange':native['cases'][1]['evaluations'][1]['sample']['m2']=2.1
    with pytest.raises(ValueError):ward.adjudicate(native,config,ZERO)

def test_zero_colour_is_refused_instead_of_skipped(native,config):
    for value in native['cases'][0]['evaluations'][1]['sample']['jamp']:value[0]=complex_value(0.)
    with pytest.raises(ValueError,match='zero columns'):ward.adjudicate(native,config,ZERO)

@pytest.mark.parametrize('zero',[ORIGINAL,'BLOCK MASS\n 6 3\nDECAY 6 0\n','BLOCK MASS\n 6 2\nDECAY 6 0\nDECAY 7 0\n','BLOCK MASS\n 6 2\nDECAY 6 Auto\n'])
def test_width_diagnostic_does_not_silently_change_original_scope(zero):
    with pytest.raises(ValueError):ward.diagnostic_lineage(ORIGINAL,zero)

def test_explicit_distinct_width_diagnostic():
    assert ward.diagnostic_lineage(ORIGINAL,ZERO)==[{'block':'decay','codes':[6],'original':1.,'diagnostic':0.}]

def test_unapproved_run_refuses_before_native_or_source_loading(tmp_path,monkeypatch):
    monkeypatch.setattr(ward,'_load',lambda *args:pytest.fail('source loading reached without supervisor'))
    with pytest.raises(ValueError,match='approved supervised worker'):ward.run({'config':'x'},tmp_path,tmp_path/'out')

def test_native_colour_labels_serialize_numeric_tuple_order():
    import ast
    tree=ast.parse(Path(ward.__file__).read_text())
    values=[value for node in ast.walk(tree) if isinstance(node,ast.Dict)
            for key,value in zip(node.keys,node.values)
            if isinstance(key,ast.Constant) and key.value=='colour_basis']
    assert len(values)==1
    class Matrix:
        def get(self,name):
            assert name=='color_basis'
            return {(('T',(1,-2,3)),):[],(('T',(1,-1,3)),):[]}
    basis=Matrix().get('color_basis')
    actual=eval(compile(ast.Expression(values[0]),'<colour capture>','eval'),
                {'sorted':sorted,'repr':repr,'matrix_element':Matrix()})
    assert actual==[repr(key) for key in sorted(basis)]
    assert actual!=sorted(actual)

def test_nonlexicographic_colour_labels_keep_actual_column_order(native,config):
    keys={(('T',(1,-2,3)),):[],(('T',(1,-1,3)),):[]}
    labels=[repr(key) for key in sorted(keys)]
    assert labels!=sorted(labels)
    for case in native['cases']:
        for evaluation in case['evaluations']:evaluation['colour_basis']=labels[:]
    assert ward.adjudicate(native,config,ZERO)['passed']
    native['cases'][0]['evaluations'][1]['colour_basis'].reverse()
    with pytest.raises(ValueError,match='basis differs'):ward.adjudicate(native,config,ZERO)
