"""Explicit fabricated engineering controls; no ROOT data are used."""
from copy import deepcopy
import hashlib
import pytest
from ravel.physics import columnar_ntuple_recipe as h, ntuple_inventory as intake, root_stream_core as core
from ravel.workflow import science

PIN = {'path': '/supplied-input-description', 'sha256': '0'*64, 'size': 1}
# Fabricated format roles: the code holds no format table, so a test supplies its own.
ROLES = {'schema_version':1,'kind':'columnar-branch-roles','name':'fabricated-flat-ntuple',
    'source':'fabricated engineering control','branches':[
        {'name':'weight_pileup_NOSYS','role':'scale_weight','shape':'scalar','unit':'1'},
        {'name':'weight_beamspot','role':'scale_weight','shape':'scalar','unit':'1'}],
    'families':[{'pattern':'[A-Za-z]+_[A-Za-z]*SF_NOSYS','role':'object_scale_weight','shape':'jagged','unit':'1'}],
    'periods':['2017','2018','2023'],'period_scoped_weights':{'weight_beamspot':['2017','2018']}}


def recipe():
    return {'schema_version':1, 'objects':[{'name':'leptons','prefix':'el','selection':'baseline',
        'pt_min_GeV':20,'abs_eta_max':2.5,'scale_factors':['el_recoSF_NOSYS'],'tagger':None}],
        'overlap_removal':'standard','met':'Baseline','trigger_by_year':{'2018':['trigPassed_electron']},
        'scalar_scale_factors':['weight_pileup_NOSYS','weight_beamspot'],
        'sf_applicability':[{'subject':'el_recoSF_NOSYS','source':PIN,
            'treatment':'declared_conditional_not_calibration_qualification','limitations':['fabricated source; not calibrated']}],
        'regions':[{'id':'SR','role':'signal','counts':{'leptons':[2,None]},'ht':{'object':'leptons','range_GeV':[60,None]},'met_GeV':[50,None]},
                   {'id':'VR','role':'validation','counts':{'leptons':[0,1]},'ht':None,'met_GeV':[0,50]}],
        'uncertainty_policy':'nominal_only_missing_variations_explicit','branch_roles':deepcopy(ROLES)}


def event():
    return {'year':2018,'mcChannelNumber':801174,'trigPassed_electron':True,
        'el_pt_NOSYS':[21000,50000,50000,9000], 'el_eta':[.2,1.,2.,.1],
        'el_select_baseline_NOSYS':[1,1,1,1],'el_select_passesOR_NOSYS':[1,1,0,1],
        'el_recoSF_NOSYS':[.9,1.1,4.,5.], 'metBaseline_met_NOSYS':60000,
        'weight_mc_NOSYS':-3.,'weight_pileup_NOSYS':2.,'weight_beamspot':1.}


def test_source_indices_unsorted_mev_and_conditional_factor():
    r=h.validate_recipe(recipe()); view=h.event_view(event(),r)
    assert view['objects']['leptons']=={'indices':[1,0],'pt_GeV':[50.,21.]}
    assert view['object_factor']==pytest.approx(.99)
    assert view['met_GeV']==60.
    rows=h.records([event()], [23], {'dsid':801174},r)
    assert rows==[{'source_entry':23,'fills':{'regions':[[.5]]}}]


def test_equal_pt_stable_native_indices():
    e=event();e['el_select_passesOR_NOSYS'][2]=1
    assert h.event_view(e,recipe())['objects']['leptons']['indices']==[1,2,0]


def test_rejected_event_stays_in_original_entry_population():
    e=event();e['trigPassed_electron']=False
    assert h.records([e],[29],{'dsid':801174},recipe())==[{'source_entry':29,'fills':{'regions':[]}}]


@pytest.mark.parametrize('mutation',[lambda e:e['el_eta'].pop(),lambda e:e['el_select_passesOR_NOSYS'].__setitem__(0,2),
    lambda e:e.__setitem__('year',2023),lambda e:e.__setitem__('metBaseline_met_NOSYS',-1)])
def test_literal_schema_alignment_flags_year_met(mutation):
    e=event();mutation(e)
    with pytest.raises(ValueError):h.event_view(e,recipe())


def test_dsid_does_not_follow_order_or_run_number():
    with pytest.raises(ValueError):h.records([event()],[0],{'dsid':999999},recipe())


@pytest.mark.parametrize('mutation',[lambda r:r['objects'][0].__setitem__('selection','signal'),
    lambda r:r.__setitem__('met','Signal'),lambda r:r.__setitem__('uncertainty_policy','full_systematics'),
    lambda r:r['objects'][0]['scale_factors'].append('el_trigSF_NOSYS'),
    lambda r:r['trigger_by_year'].__setitem__('2023',['trigPassed_electron'])])
def test_source_applicability_refusals(mutation):
    r=recipe();mutation(r)
    with pytest.raises(ValueError):h.validate_recipe(r)


def test_period_and_weight_scope_come_from_the_supplied_descriptor_only():
    r=recipe();r['trigger_by_year']['2016']=['trigPassed_electron']
    with pytest.raises(ValueError):h.validate_recipe(r)  # not a declared period
    r['branch_roles']['periods'].append('2016')
    with pytest.raises(ValueError,match='supplied only for periods'):h.validate_recipe(r)
    r['branch_roles']['period_scoped_weights']['weight_beamspot'].append('2016')
    assert h.validate_recipe(r)['trigger_by_year']['2016']==['trigPassed_electron']
    # Without a descriptor nothing format-specific is assumed: any four-digit period and any
    # literal scalar weight; their existence is the supplied branch schema's to establish.
    bare=recipe();del bare['branch_roles'];bare['trigger_by_year']['2031']=['trigPassed_electron']
    assert h.validate_recipe(bare)['scalar_scale_factors']==['weight_pileup_NOSYS','weight_beamspot']
    bare['trigger_by_year']['Run2']=['trigPassed_electron']
    with pytest.raises(ValueError):h.validate_recipe(bare)


@pytest.mark.parametrize('change',[lambda d:d.__setitem__('kind','columnar-format'),
    lambda d:d['branches'].append(dict(d['branches'][0])),
    lambda d:d['families'].append({'pattern':'([','role':'object_scale_weight','shape':'jagged','unit':'1'}),
    lambda d:d['branches'][0].__setitem__('shape','tensor'),
    lambda d:d.__setitem__('extra',1)])
def test_branch_role_descriptor_is_closed_and_typed(change):
    d=deepcopy(ROLES);change(d)
    with pytest.raises(ValueError):h.branch_roles(d)


def test_scalar_weight_cannot_be_retyped_against_its_supplied_role():
    r=recipe();r['branch_roles']['branches'][0]['role']='object_pt'
    with pytest.raises(ValueError,match='scale-weight role'):h.validate_recipe(r)


def test_schema1_branch_descriptions_follow_roles_then_recipe_consumption():
    r=recipe()
    assert h.descriptor_role(r['branch_roles'],'el_recoSF_NOSYS')==('object_scale_weight','jagged','1')
    assert h.branch_description(r,'el_recoSF_NOSYS')==('jagged','1')
    assert h.branch_description(r,'metBaseline_met_NOSYS')==('scalar','MeV')
    assert h.branch_description(r,'trigPassed_electron')==('scalar','1')
    assert h.branch_description(r,'el_pt_NOSYS')==('jagged','MeV')
    assert h.bit_branches(r)=={'el_select_baseline_NOSYS','el_select_passesOR_NOSYS'}


def test_signal_selection_allowed_only_without_claiming_baseline_or():
    r=recipe();r['overlap_removal']='none';r['met']='Signal';r['objects'][0]['selection']='signal'
    assert h.validate_recipe(r)['objects'][0]['selection']=='signal'


def test_tagger_did_not_run_is_not_a_scientific_zero_score():
    r=recipe();r['overlap_removal']='largeR';r['objects']=[{'name':'leptons','prefix':'largeRjet','selection':'stored',
        'pt_min_GeV':200,'abs_eta_max':2.,'scale_factors':[],
        'tagger':{'tagged':'largeRjet_TopTagged','valid':'largeRjet_TopValidKinRange','score':'largeRjet_TopScore','mass':None}}]
    e={'year':2018,'trigPassed_electron':True,'largeRjet_pt_NOSYS':[300000],'largeRjet_eta':[.2],
       'largeRjet_select_passesORLargeR_NOSYS':[1],'largeRjet_TopTagged':[1],'largeRjet_TopValidKinRange':[0],
       'largeRjet_TopScore':[-666],'metBaseline_met_NOSYS':0}
    assert h.event_view(e,r)['objects']['leptons']['indices']==[]
    e['largeRjet_TopValidKinRange']=[1]
    with pytest.raises(ValueError):h.event_view(e,r)


def test_signed_zero_generator_weights_and_nominal_sf_do_not_change_law():
    contract={'raw_mc_weight':'raw','scale_factors':['pileup'],'variations':[],
        'derived_factor':{'entry':'kernel.py','source':PIN,'semantics':'source_declared_nominal_event_sf'}}
    sample={'kind':'signal_mc'}
    assert core.weights(sample,contract,{'raw':-3.,'pileup':2.,'__ravel_derived_nominal_factor__':.5})=={'nominal':-3.}
    assert core.weights(sample,contract,{'raw':0.,'pileup':2.,'__ravel_derived_nominal_factor__':.5})=={'nominal':0.}
    with pytest.raises(ValueError):core.weights(sample,contract,{'raw':1.,'pileup':1.,'__ravel_derived_nominal_factor__':-1.})
    old={'raw_mc_weight':'raw','scale_factors':[],'variations':[]}
    assert core.weights(sample,old,{'raw':-1.})=={'nominal':-1.}


def test_deterministic_kernel_retains_declared_conditional_scope():
    raw=h.kernel_bytes(recipe())
    assert b'def event_factors' in raw and b'def analyze' in raw and b'calibration_qualification' in raw
    assert raw==h.kernel_bytes(deepcopy(recipe()))


def test_original_inventory_identity_not_rounded_bytes_or_prefix_subset():
    rows=[{'did':'user.a:user.a.801174.file.root','guid':'6AFFAA85-1644-44AC-A7A7-3019A10A46FC',
           'adler32':'ad:b29246d7','display_size':'3.678 GB','events':12345}]
    assert intake.inventory(rows)==rows
    with pytest.raises(ValueError):intake.inventory(rows+deepcopy(rows))
    r=deepcopy(rows);r[0]['size_bytes']=3678000000
    with pytest.raises(ValueError):intake.inventory(r)


def test_ordinary_registry_reaches_both_source_operations_without_new_runner():
    assert science.adapter({'mode':'ntuple-inventory'}) is intake
    assert science.adapter({'mode':'mc-expected-construction'}).__name__.endswith('mc_expected_construction')
    assert 'root-stream' in science.MODES and 'ntuple-inventory' in science.MODES and 'mc-expected-construction' in science.MODES


def fitted_recipe():
    r=recipe(); cr=deepcopy(r['regions'][0]);cr.update(id='CR',role='control')
    r['regions'].insert(1,cr)
    r['fitted_categories']={'bins':['SR','CR'],'source':PIN,
        'semantics':'source_declared_disjoint_independent_poisson',
        'independent_unit':'source_entry_declared_independent_physical_event_group'}
    return r


@pytest.mark.parametrize('raw_weight',[0.,-3.,1e-320])
def test_unweighted_fitted_overlap_cannot_hide_in_signed_zero_or_underflow(raw_weight):
    r=h.validate_recipe(fitted_recipe());e=event();e['weight_mc_NOSYS']=raw_weight
    with pytest.raises(ValueError,match='unweighted fitted-category co-fill'):
        h.records([e],[7],{'dsid':801174},r)


def test_disjoint_fit_preserves_overlapping_validation_and_rejected_entries():
    r=fitted_recipe();r['regions'][1]['met_GeV']=[0,50]
    vr=deepcopy(r['regions'][0]);vr.update(id='VR',role='validation');r['regions'][2]=vr
    r=h.validate_recipe(r);rejected=event();rejected['trigPassed_electron']=False
    assert h.records([event(),rejected],[3,4],{'dsid':801174},r)==[
        {'source_entry':3,'fills':{'regions':[[.5],[2.5]]}},
        {'source_entry':4,'fills':{'regions':[]}}]


@pytest.mark.parametrize('change',[lambda f:f.__setitem__('bins',['SR','VR']),
    lambda f:f.__setitem__('bins',['SR','SR']),lambda f:f.__setitem__('bins',[]),
    lambda f:f.__setitem__('independent_unit','unknown'),
    lambda f:f.__setitem__('semantics','weighted_covariance_zero_certifies_disjointness')])
def test_source_disjointness_is_not_a_weighted_covariance_or_region_name_waiver(change):
    r=fitted_recipe();change(r['fitted_categories'])
    with pytest.raises(ValueError):h.validate_recipe(r)


def test_legacy_generic_region_delivery_still_permits_explicit_overlap():
    r=fitted_recipe();del r['fitted_categories']
    assert h.records([event()],[0],{'dsid':801174},h.validate_recipe(r))[0]['fills']['regions']==[[.5],[1.5]]
