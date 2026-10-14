"""Fabricated complete-MC join controls; neither observed data nor fits."""
from copy import deepcopy
from fractions import Fraction
import pytest
from ravel.physics import mc_expected_construction as h


def design():
    pars=[{'name':'mu','role':'poi','initial':'1','bounds':['0','5'],'fixed':False}]
    terms=[{'id':'signal','basis':'bsm','coefficients':['0','0'],'powers':{'mu':1},'log_response':[['0'],['0']],'source':'source'},
           {'id':'background','basis':'background','coefficients':['0','0'],'powers':{},'log_response':[['.1'],['.1']],'source':'source'}]
    law={'parameters':pars,'bins':[{'id':'SR','role':'signal_region','observed':None},{'id':'CR','role':'control_region','observed':None}],
         'terms':terms,'sources':[{'id':'source','path':'/source-law','sha256':'0'*64}],
         'auxiliary':{'names':['shared'],'observed':['0'],'factor':[['1']],'eta_bounds':[['-5','5']]}}
    cell={'id':'point1','parameters':[],'law':law,'components':[{'id':'caller-native-extra','source_declared':True}],
          'fit':{'method':'MultiDimFit','data':'source_asimov'},'expected_data':{'kind':'source-graph-asimov/v1','conditioning':'supplied_nominal',
          'point':{'mu':'1','ravel_aux_0':'0'},'source':'source','statement':'Authored engineering Asimov point','fit':None}}
    return {'schema_version':1,'recipe':{'cells':[cell]},'region_roles':{'SR':'signal_region','CR':'control_region','VR':'validation_region'},
        'validation_bins':['VR'],'mc_treatment':'conditional_on_supplied_MC_centrals_moments_retained_no_auxiliary_inferred',
        'missing_validation':['Observed data-dependent closure absent'],'dependencies':[],
        'native_component_treatment':'additional_source_declared_means_require_fresh_joint_review',
        'term_bindings':[{'cell':'point1','term':'signal','sample':'s','quantity':'regions','bin_ids':['SR','CR']},
                         {'cell':'point1','term':'background','sample':'b','quantity':'regions','bin_ids':['SR','CR']}]}


def delivery():
    contract={'representation':'integrated','normalization':{'unit':'events'},'weight_names':['nominal'],
              'bins':[{'id':'SR'},{'id':'CR'},{'id':'VR'}]}
    return {'samples':[{'id':'s','kind':'signal_mc','quantities':{'regions':{'contract':deepcopy(contract),
        'values':{'nominal':[2.5,-.25,1.]},'covariance':[[3.,.4,0.],[.4,.5,0.],[0.,0.,1.]]}}},
        {'id':'b','kind':'background_mc','quantities':{'regions':{'contract':deepcopy(contract),
        'values':{'nominal':[10.,50.,7.]},'covariance':[[20.,2.,0.],[2.,100.,0.],[0.,0.,9.]]}}}]}


def test_nonzero_asimov_sr_cr_signal_signed_centrals_and_auxiliary_once():
    original=design(); data=delivery(); before=deepcopy(data); out=h.project(data,original)
    cell=out['cells'][0]
    assert cell['law']['terms'][0]['coefficients']==['5/2','-1/4']
    assert cell['law']['terms'][1]['coefficients']==['10','50']
    assert all(b['observed'] is None for b in cell['law']['bins'])
    assert cell['law']['auxiliary']==original['recipe']['cells'][0]['law']['auxiliary']
    assert cell['components']==original['recipe']['cells'][0]['components']
    assert data==before and original['recipe']['cells'][0]['law']['terms'][0]['coefficients']==['0','0']
    assert cell['expected_data']['point']['mu']=='1'


@pytest.mark.parametrize('mutation',[lambda d:d['recipe']['cells'][0]['law']['bins'][0].__setitem__('observed',0),
    lambda d:d['recipe']['cells'][0]['expected_data']['point'].__setitem__('mu','0'),
    lambda d:d['recipe']['cells'][0]['fit'].__setitem__('method','AsymptoticLimits'),
    lambda d:d['term_bindings'].pop(),lambda d:d['term_bindings'][0].__setitem__('bin_ids',['CR','SR']),
    lambda d:d['recipe']['cells'][0]['law']['terms'][1].__setitem__('shape',{'invented':'curve'}),
    lambda d:d['recipe']['cells'][0]['law']['auxiliary'].__setitem__('observed',['1']),
    lambda d:d.__setitem__('mc_treatment','sumw2_is_poisson_auxiliary')])
def test_expected_law_and_complete_population_adversaries(mutation):
    d=design();mutation(d)
    with pytest.raises((ValueError,KeyError)):h.project(delivery(),d)


def test_source_integrals_are_not_histogram_densities_or_masses():
    d=delivery();d['samples'][0]['quantities']['regions']['contract']['normalization']['unit']='GeV'
    with pytest.raises(ValueError):h.project(d,design())


def test_background_does_not_gain_signal_strength():
    d=design();d['recipe']['cells'][0]['law']['terms'][1]['powers']={'mu':1}
    with pytest.raises(ValueError):h.project(delivery(),d)


def selection_recipe():
    source={'path':'/fabricated-physical-event-law','sha256':'0'*64,'size':1}
    return {'schema_version':1,'objects':[{'name':'j','prefix':'jet','selection':'stored',
        'pt_min_GeV':20,'abs_eta_max':4.5,'scale_factors':[],'tagger':None}],
        'overlap_removal':'none','met':'Baseline','trigger_by_year':{'2018':['trigPassed_met']},
        'scalar_scale_factors':[], 'sf_applicability':[{'subject':'none','source':source,
        'treatment':'declared_conditional_not_calibration_qualification','limitations':['fabricated']}],
        'regions':[{'id':'SR','role':'signal','counts':{},'ht':None,'met_GeV':[50,None]},
                   {'id':'CR','role':'control','counts':{},'ht':None,'met_GeV':[0,50]},
                   {'id':'VR','role':'validation','counts':{},'ht':None,'met_GeV':[25,75]}],
        'uncertainty_policy':'nominal_only_missing_variations_explicit',
        'fitted_categories':{'bins':['SR','CR'],'source':source,
            'semantics':'source_declared_disjoint_independent_poisson',
            'independent_unit':'source_entry_declared_independent_physical_event_group'}}


def guarded_config_and_capture(recipe, raw=None):
    generated=h.h.kernel_bytes(recipe)
    pin={'path':'/fabricated-kernel','sha256':'0'*64,'size':len(generated)}
    config={'bundle':{'entry':'kernel.py','blind_entry':None,'files':{'kernel.py':pin}}}
    class Capture:
        def read(self, fact, base):
            return fact['path'], (generated if raw is None else raw) if fact==pin else b'1'
    return config,Capture()


def canonical_analysis(r,config):
    return h.h.analysis_document(r,[{'name':n} for n in h.h.required_branches(r)],
        {'path':'/fabricated-goal','sha256':'0'*64,'size':1},config['bundle']['files']['kernel.py'])


def test_exact_guarded_kernel_and_full_original_roles_required_for_expected_law():
    r=selection_recipe();config,cap=guarded_config_and_capture(r)
    assert h.fitted_kernel(r,config,design(),cap,'/',canonical_analysis(r,config))==r['fitted_categories']


@pytest.mark.parametrize('mutation',[lambda d:d['region_roles'].__setitem__('VR','control_region'),
    lambda d:d['region_roles'].pop('VR'),
    lambda d:d['recipe']['cells'][0]['law']['bins'].reverse()])
def test_expected_guard_refuses_original_role_loss_and_fitted_reordering(mutation):
    r=selection_recipe();config,cap=guarded_config_and_capture(r);d=design();mutation(d)
    with pytest.raises(ValueError):h.fitted_kernel(r,config,d,cap,'/',canonical_analysis(r,config))


def test_expected_guard_refuses_unguarded_or_changed_executed_kernel():
    r=selection_recipe();config,cap=guarded_config_and_capture(r,b'pass\n')
    with pytest.raises(ValueError,match='exact unweighted'):h.fitted_kernel(r,config,design(),cap,'/',canonical_analysis(r,config))
    unguarded=deepcopy(r);del unguarded['fitted_categories']
    with pytest.raises(ValueError,match='guarded fitted categories'):
        h.fitted_kernel(unguarded,config,design(),cap,'/',canonical_analysis(r,config))


@pytest.mark.parametrize('bins',[['SR'],['CR','SR'],['SR','CR','VR']])
def test_complete_original_fitted_roster_cannot_omit_control_or_relabel_validation(bins):
    r=selection_recipe();r['fitted_categories']['bins']=bins
    with pytest.raises(ValueError,match='complete ordered'):h.h.validate_recipe(r)


@pytest.mark.parametrize('mutation',[
    lambda a:a['weight_contract'].pop('derived_factor'),
    lambda a:a['weight_contract'].__setitem__('raw_mc_weight',None),
    lambda a:a['quantities'][0]['contract']['bins'][0].__setitem__('id','CR'),
    lambda a:a['quantities'][0]['contract']['bins'].reverse(),
    lambda a:a['weight_contract']['derived_factor'].__setitem__('semantics','ignore_sf')])
def test_actual_expected_admission_refuses_missing_sf_or_region_map(mutation):
    r=selection_recipe();config,cap=guarded_config_and_capture(r);a=canonical_analysis(r,config);mutation(a)
    with pytest.raises(ValueError,match='canonical nominal'):h.fitted_kernel(r,config,design(),cap,'/',a)
