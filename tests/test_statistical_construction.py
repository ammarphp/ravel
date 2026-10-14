"""Pure supplied-algebra, generated-source and inert native-API controls only."""
import ast
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest
from ravel.physics import statistical_construction as c, native_likelihood as native


def fixture(tmp_path, correlated=False):
    src = tmp_path / 'supplied.txt'; src.write_text('Artificial source for arithmetic controls, not experimental data.\n')
    k = 2 if correlated else 0
    par = lambda n, role, v, b, fixed=False: {'name': n, 'role': role, 'initial': v, 'bounds': b, 'fixed': fixed, 'meaning': n, 'source': 's'}
    d = {'schema_version': 1, 'model_id': 'regional', 'question': 'Retain full A/B/C/D signal and transfer inference.',
         'sources': [{'id': 's', 'path': str(src), 'sha256': hashlib.sha256(src.read_bytes()).hexdigest()}],
         'parameters': [par('c', 'poi', '0', ['-2', '2']), par('beta', 'rate', '5', ['0','20']),
                        par('u','rate','2',['0','5']), par('v','rate','3',['0','5']), par('kappa','rate','1',['0','2'],True)],
         'bins': [{'id': n, 'role': 'signal_region' if n=='A' else 'control_region', 'observed': obs, 'observation_id': 'events/'+n, 'source':'s'} for n,obs in zip('ABCD',[30,10,15,5])],
         'terms': c.abcd_terms(list('ABCD'), dict(zip('ABCD','ABCD')), beta='beta', x='u', y='v', closure='kappa',source='s',auxiliary_count=k),
         'auxiliary': {'kind':'supplied_gaussian_factor','names':['shape','transfer'] if k else [], 'observed':['0','0'] if k else [],
                       'factor':[['1','0'],['3/5','4/5']] if k else [],'eta_bounds':[['-3','3'],['-4','4']] if k else [],'source':'s'},
         'partition':{'kind':'declared_disjoint_poisson_counts','source':'s','statement':'Assumed artificial disjoint A/B/C/D observations.'},
         'prediction':{'units':'expected_events','energy':'artificial','luminosity':'artificial','basis':'supplied signed c convention','scale':'same-scale artificial','domain_statement':'Box and positive full means; native domain unqualified.','source':'s'},
         'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Artificial exact inputs; no MC auxiliaries.','source':'s'},
         'assumptions':[{'id':'conditional','statement':'This artificial law is supplied, not a physics claim.','source':'s','status':'assumed'}]}
    for ident,power,coefs in [('linear',1,['-4','1','-2','0']),('square',2,['2','1','3','1'])]:
        d['terms'].append({'id':ident,'basis':'interference' if power==1 else 'bsm','coefficients':coefs,'powers':{'c':power},'log_response':[['0']*k for _ in 'ABCD'],'source':'s'})
    return d


def native_config(tmp_path, d):
    def pin(path): return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    tool = tmp_path/'tool';tool.write_text('#!/bin/sh\nexit 99\n');tool.chmod(0o755)
    lib = tmp_path/'libHiggsAnalysisCombinedLimit.so';lib.write_bytes(b'inert')
    mod = tmp_path/'PhysicsModel.py';mod.write_text('# inert; never imported\n')
    version = tmp_path/'combine.cpp';version.write_text('std::string combineTagString = "v9.2.1";\nif(datacard == "") { cerr << "Missing datacard file" << endl; return 1002; }\nif (seed == -1) {}\ncombiner.applyOptions(vm);\n')
    runtime={'tools':{key:pin(tool) for key in ('combine','text2workspace','python')},'transport':{'kind':'local'},'artifacts':[pin(lib),pin(mod)],'environment':{'PATH':'/usr/bin:/bin'},
             'version_proof':{'kind':'missing_datacard_diagnostic','source':pin(version),'expected_returncode':234},'expected':{'combine_version':'9.2.1','root_version':'6.24/00','cmssw_version':None,'architecture':'x86_64','custom_classes':['RooParametricHist']}}
    fit={'method':'MultiDimFit','data':'observed','poi':'c','domain':['-2','2'],'mass':120,'seed':12345,'points':None,'minimizer':None,'fixed_witness_points':['0','1'],'reference_quantiles':None,
         'saved_fit':{'algorithm':'none','required_object':'multidimfit.ravel.root:fit_mdf','maximum_edm':.001}}
    handoff=c.write_native_bundle(d,tmp_path/'bundle',runtime=runtime,fit=fit,max_seconds=30)
    cp=Path(handoff['task']['input'])
    return cp,json.loads(cp.read_text())


def state(d, point=None):
    point=point or c.initial_point(d)
    s={p['name']:{'value':float(F(point[p['name']])),'minimum':float(F(p['bounds'][0])),'maximum':float(F(p['bounds'][1])),'constant':p['fixed']} for p in d['parameters']}
    for i,b in enumerate(d['auxiliary']['eta_bounds']):
        n='ravel_aux_'+str(i);s[n]={'value':float(F(point[n])),'minimum':float(F(b[0])),'maximum':float(F(b[1])),'constant':False}
    return s


def test_abcd_full_controls_signed_cancellation_and_zero_safe_derivatives(tmp_path):
    d=fixture(tmp_path); p=c.initial_point(d);p['c']='1'
    j=c.mean_jet(d,p)
    assert j['means']==[28,12,16,6]
    assert j['term_values'][0][-2:]==[-4,2] and j['clipping_applied'] is False
    # Independent direct monomial derivatives, all control signal terms retained.
    assert [row[0] for row in j['jacobian']]==[0,3,4,2]
    assert [row[1] for row in j['jacobian']]==[6,2,3,1]
    p.update(beta='0',u='0',c='0')
    j=c.mean_jet(d,p)
    assert j['means']==[0,0,0,0] and not j['strictly_positive_total']
    assert [row[1] for row in j['jacobian']]==[0,0,3,1]


def test_fraction_transfer_joint_parameter_and_signed_interference(tmp_path):
    d=fixture(tmp_path)
    d['parameters']=[p for p in d['parameters'] if p['name'] in ('beta','c')]
    d['terms']=c.transfer_terms(list('ABCD'),['beta'],[['1/3'],['2/7'],['1'],['0']],source='s')+d['terms'][-2:]
    p=c.initial_point(d);p['c']='-1'
    j=c.mean_jet(d,p)
    assert j['means']==pytest.approx([float(F(5,3)+6),float(F(10,7)),10,1])
    assert [row[1] for row in j['jacobian']]==pytest.approx([1/3,2/7,1,0])
    with pytest.raises(ValueError): c.transfer_terms(['A'],['beta'],[['-1']],source='s')


def test_shared_factor_whitening_and_one_auxiliary_population(tmp_path):
    d=fixture(tmp_path,True)
    d['terms'][0]['log_response'][0]=['2','-1']
    j=c.mean_jet(d,c.initial_point(d))
    assert j['jacobian'][0][-2:]==pytest.approx([42,-24])
    compiled=c.response(d)
    assert compiled['law']['supplied_auxiliary_covariance']==[['1','3/5'],['3/5','1']]
    card=c.datacard(d).decode()
    assert card.count(' param ') == 2
    assert card.count('ravel_aux_0 param')==1 and '[-3,3]' in card
    assert '[-8,8]' not in card
    assert 'kappa flatParam' not in card and card.count('beta flatParam')==1


@pytest.mark.parametrize('mutate',[
    lambda d:d['terms'][-1]['coefficients'].pop(),
    lambda d:d['bins'][1].update(observation_id=d['bins'][0]['observation_id']),
    lambda d:d['bins'][0].update(observed=.5),
    lambda d:d['partition'].update(kind='assumed_independent_SR_table'),
    lambda d:d['template_statistics'].update(kind='sumw2_is_gaussian'),
    lambda d:d['parameters'][0].update(name='MH'),
    lambda d:d['terms'][0]['powers'].update(unknown=1),
    lambda d:d['terms'][0]['powers'].update(beta=-1),
    lambda d:d['parameters'][0].update(fixed=True),
    lambda d:d['sources'][0].update(sha256='invalid'),
])
def test_complete_law_refusals(tmp_path,mutate):
    d=fixture(tmp_path);mutate(d)
    with pytest.raises(ValueError):c.validate(d)


def test_negative_component_is_allowed_but_negative_total_is_not_clipped(tmp_path):
    d=fixture(tmp_path);d['terms'][-2]['coefficients'][0]='-100'
    p=c.initial_point(d);p['c']='1'
    j=c.mean_jet(d,p)
    assert j['means'][0]==-68 and not j['strictly_positive_total']
    with pytest.raises(ValueError,match='total-mean'):c.native_witness(c.response(d),state(d,p))


def test_generated_bridge_uses_exact_full_means_and_existing_nuisance_api(tmp_path,monkeypatch):
    d=fixture(tmp_path,True);r=c.response(d);raw=c.native_bridge_source(r)
    # Our generated Python executes only against inert builder objects, no ROOT/Combine.
    module=ModuleType('HiggsAnalysis.CombinedLimit.PhysicsModel');module.PhysicsModel=type('PhysicsModel',(),{})
    monkeypatch.setitem(sys.modules,'HiggsAnalysis.CombinedLimit.PhysicsModel',module)
    env={};exec(compile(raw,'generated_source','exec'),env)
    vars_,calls,sets={},[],{}
    class Var:
        def setConstant(self,x):self.constant=x
    class Builder:
        extraNuisances=[]
        out=SimpleNamespace(var=lambda n:vars_[n])
        def doVar(self,s):vars_[s.split('[')[0]]=Var();calls.append(s)
        def doSet(self,n,v):sets[n]=v
        def factory_(self,s):calls.append(s)
    builder=Builder();model=env['model'];model.modelBuilder=builder;model.doParametersOfInterest()
    assert sets=={'POI':'c'} and builder.doModelBOnly is False
    assert vars_['kappa'].constant is True and vars_['c'].constant is False
    assert builder.extraNuisances==[vars_[n] for n in ('beta','u','v')]
    assert all(model.getYieldScale(b,'ravel_full')=='ravel_mean_'+str(i) for i,b in enumerate('ABCD'))
    assert model.getYieldScale('A','ravel_dummy')==0
    assert 'max(' not in raw and 'abs(' not in raw
    assert set(r['functions'])=={'ravel_mean_'+str(i) for i in range(4)}
    assert any('pow(@0,2)' in x for x in calls)
    assert 'fitTo' not in raw and 'createNLL' not in raw


def test_ordinary_native_input_connects_complete_source_and_preserves_saved_fit(tmp_path,monkeypatch):
    d=fixture(tmp_path);cp,cfg=native_config(tmp_path,d)
    def forbidden(*a,**k):raise AssertionError('native/fit forbidden')
    monkeypatch.setattr(native.subprocess,'run',forbidden);monkeypatch.setattr(native.subprocess,'Popen',forbidden)
    parsed=native._configuration({'input':str(cp)},tmp_path)
    paths=native.inputs({'input':str(cp)},tmp_path)
    from ravel.workflow import science
    assert science.task_inputs({'mode':'native-likelihood','task':{'input':str(cp)},'max_seconds':30},tmp_path)==paths
    assert Path(d['sources'][0]['path']) in paths and Path(c.__file__) in paths
    assert parsed[8]['kind']==c.KIND and parsed[7]==c.datacard(d)
    build,fit=native.commands(cfg,parsed[3],tmp_path,has_response=True)
    assert build[-2:]==['-P','ravel_source_response:model']
    assert '--saveFitResult' in fit and '--saveWorkspace' in fit and '--saveSpecifiedNuis' in fit and 'all' in fit
    assert fit[fit.index('--algo')+1]=='none'
    Path(d['sources'][0]['path']).write_text('changed')
    with pytest.raises(ValueError,match='source changed'):native.inputs({'input':str(cp)},tmp_path)


def test_constructed_native_grid_uses_existing_profile_route(tmp_path):
    d=fixture(tmp_path);cp,cfg=native_config(tmp_path,d)
    cfg['schema_version']=1;cfg['fit'].pop('saved_fit');cfg['fit']['points']=5;cp.write_text(json.dumps(cfg))
    parsed=native._configuration({'input':str(cp)},tmp_path)
    _,cmd=native.commands(cfg,parsed[3],tmp_path,has_response=True)
    assert cmd[cmd.index('--algo')+1]=='grid' and '--saveNLL' in cmd
    cfg['fit']['method']='AsymptoticLimits';cfg['fit']['points']=None;cfg['fit']['domain']=['0','2'];cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):native.inputs({'input':str(cp)},tmp_path)


def count_product_fixture(d, witnesses):
    """Supplied graph/data observations, not a ROOT result or runtime qualification.

    CountingModelBuilder represents all disjoint-bin counts in one data row.
    Its model_s multiplies their Poissons by the single nuisance factor product.
    """
    bins=d['bins']; count_names=['pdf_bin'+b['id'] for b in bins]
    aux_names=['ravel_aux_'+str(i)+'_Pdf' for i in range(len(d['auxiliary']['names']))]
    leaves=[]; rows=[]
    def proxy(roles,servers):
        codes={roles['x']:1,roles['mean']:2}
        if 'sigma' in roles:codes[roles['sigma']]=0
        return {'method':'ROOT6.22/getAnalyticalIntegral-name-match/v1','roles':roles,
                'queries':[{'server':n,'code':codes[n],'selected':[n] if codes[n] else []} for n in servers]}
    # Independent ABCD means at the fixture's c=eta=0: beta=5,u=2,v=3,kappa=1.
    initial_means=[30.,10.,15.,5.]
    for i,b in enumerate(bins):
        ident=b['id'];mean='n_exp_bin'+ident;full=mean+'_proc_ravel_full';dummy=mean+'_proc_ravel_dummy';fn='ravel_mean_'+str(i)
        pdf={'name':'pdf_bin'+ident,'class':'RooPoisson','servers':['n_obs_bin'+ident,mean]}
        pdf['proxy_identity']=proxy({'x':'n_obs_bin'+ident,'mean':mean},pdf['servers'])
        leaves.append(pdf)
        rows.append({'channel':ident,'declared_role':b['role'],'pdf':pdf,'pdf_observables':['n_obs_bin'+ident],
            'mean':{'name':mean,'class':'RooAddition','servers':[full,dummy]},
            'full_process':{'name':full,'class':'ProcessNormalization','servers':[fn]},'count_function':fn,
            'dummy':{'name':dummy,'constant':True,'value':0.},'initial_total_mean':initial_means[i],
            'initial_count_function':initial_means[i]})
    widths={}
    for i,name in enumerate(aux_names):
        leaves.append({'name':name,'class':'SimpleGaussianConstraint','servers':['ravel_aux_'+str(i),'ravel_aux_'+str(i)+'_In','1']})
        leaves[-1]['proxy_identity']=proxy({'x':'ravel_aux_'+str(i),'mean':'ravel_aux_'+str(i)+'_In','sigma':'1'},leaves[-1]['servers'])
        widths[name]={'name':'1','constant':True,'value':1.}
    domains={n:{k:v[k] for k in ('minimum','maximum','constant')} for n,v in state(d).items()}
    q={'representation':'regional_count_product/v1','coordinate_domains':domains,
       'root':{'name':'model_s','class':'RooProdPdf','servers':['modelObs_s','nuisancePdf']},
       'products':[{'name':'model_s','class':'RooProdPdf','factors':['modelObs_s','nuisancePdf']},
                   {'name':'modelObs_s','class':'RooProdPdf','factors':count_names},
                   {'name':'nuisancePdf','class':'RooProdPdf','factors':aux_names}],
       'leaves':leaves,'rows':rows,'constant_width_reads':len(aux_names),'auxiliary_widths':widths,
       'extra_initial_mean_evaluations':2*len(bins),'constant_dummy_reads':len(bins),
       'semantic_proxy_queries':3*len(aux_names)+2*len(bins)}
    globals_=['ravel_aux_'+str(i)+'_In' for i in range(len(aux_names))]
    return {'workspace':{'pois':['c'],'channels':[],'data_entries':1,'observables':['n_obs_bin'+b['id'] for b in bins],
             'poi_domain':[-2.,2.],'nuisances':['beta','u','v','ravel_aux_0','ravel_aux_1'],'global_observables':globals_},
            'fixed_witnesses':witnesses,'construction_linkage':q,
            'construction_global_ranges':{n:{'has_min':False,'has_max':False} for n in globals_},
            'construction_observations':{'counts':{b['id']:b['observed'] for b in bins},'dataset_weight':1.,
                'auxiliary':{n:{'value':0.,'constant':True} for n in globals_}}}


def test_actual_native_witness_census_means_bounds_and_raw_diagnostics(tmp_path):
    d=fixture(tmp_path,True);cp,cfg=native_config(tmp_path,d);r=c.response(d)
    witnesses=[]
    for text in ['0','1']:
        p=c.initial_point(d);p['c']=text;s=state(d,p)
        witnesses.append({'point':text,'raw_nll_at_source_nuisance_values':123.,'construction_state':s,'scales':c.native_witness(r,s)})
    probe=count_product_fixture(d,witnesses)
    assert len(native._check_workspace(probe,cfg,r))==8
    bad=deepcopy(probe);bad['construction_observations']['counts']['B']=11
    with pytest.raises(ValueError,match='observed counts'):native._check_workspace(bad,cfg,r)
    bad=deepcopy(probe);bad['construction_observations']['auxiliary']['ravel_aux_0_In']['value']=.5
    with pytest.raises(ValueError,match='auxiliary values'):native._check_workspace(bad,cfg,r)
    bad=deepcopy(probe);bad['workspace']['nuisances'].remove('beta')
    with pytest.raises(ValueError,match='regional ModelConfig nuisance/global population differs'):native._check_workspace(bad,cfg,r)
    bad=deepcopy(probe);bad['fixed_witnesses'][0]['construction_state']['kappa']['value']=1.1
    with pytest.raises(ValueError,match='fixed parameter'):native._check_workspace(bad,cfg,r)
    bad=deepcopy(probe);bad['fixed_witnesses'][0]['construction_state']['beta']['minimum']=-1
    with pytest.raises(ValueError,match='bounds'):native._check_workspace(bad,cfg,r)
    bad=deepcopy(probe);bad['fixed_witnesses'][0]['scales']['ravel_mean_0']+=1
    with pytest.raises(ValueError,match='differs'):native._check_workspace(bad,cfg,r)


def test_changed_card_or_legacy_source_coercion_refuses(tmp_path):
    d=fixture(tmp_path);cp,cfg=native_config(tmp_path,d)
    card=Path(cfg['model']['files'][0]['path']);card.write_bytes(card.read_bytes().replace(b'observation 30',b'observation 29'))
    cfg['model']['files'][0]['sha256']=hashlib.sha256(card.read_bytes()).hexdigest();cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='complete declared'):native.inputs({'input':str(cp)},tmp_path)


def test_generated_probe_records_complete_actual_state_without_additional_nll_call():
    tree=ast.parse(native.NATIVE_PROBE)
    loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and ast.unparse(n.iter)=="cfg['fit']['fixed_witness_points']")
    calls=[n for n in ast.walk(loop) if isinstance(n,ast.Call) and ast.unparse(n.func)=='nll.getVal']
    assert len(calls)==1
    assert 'construction_state' in ast.unparse(loop)


def test_zero_nominal_shared_auxiliary_polynomial_shape_and_chain_rule(tmp_path):
    d=fixture(tmp_path,True)
    d['terms'].append({'id':'zero_nominal_migration','basis':'bsm','coefficients':['2','0','1','0'],
                      'powers':{'shape':1,'transfer':1},'log_response':[['0','0'] for _ in 'ABCD'],'source':'s'})
    p=c.initial_point(d);j=c.mean_jet(d,p)
    assert j['term_values'][0][-1]==0 and j['jacobian'][0][-2:]==[0,0]
    p.update(ravel_aux_0='1',ravel_aux_1='1/2')
    j=c.mean_jet(d,p)
    # theta=(1,1), d[2 theta0 theta1]/deta=(16/5,8/5).
    assert j['term_values'][0][-1]==2
    assert j['jacobian'][0][-2:]==pytest.approx([16/5,8/5])
    raw=c.native_bridge_source(c.response(d))
    assert 'zero_nominal' not in raw # term identities remain in complete source document
    assert 'pow((0+(1)*@5),1)' in raw


def test_additive_shape_times_log_response_uses_both_product_rule_terms(tmp_path):
    d=fixture(tmp_path,True)
    d['terms'].append({'id':'mixed_shape','basis':'bsm','coefficients':['1','0','0','0'],
                      'powers':{'shape':2},'log_response':[['1','0'] for _ in 'ABCD'],'source':'s'})
    p=c.initial_point(d);p['ravel_aux_0']='1'
    j=c.mean_jet(d,p)
    assert j['term_values'][0][-1]==pytest.approx(math.e)
    assert j['jacobian'][0][-2:]==pytest.approx([3*math.e,0])


def test_generated_formula_algebra_at_full_off_nominal_point(tmp_path):
    d=fixture(tmp_path,True)
    d['auxiliary']['observed']=['1/4','-1/2']
    d['terms'][0]['log_response'][0]=['1/3','-1/5']
    d['terms'][-1]['powers']['transfer']=2
    r=c.response(d);p=c.initial_point(d);p.update(c='-1/2',ravel_aux_0='1/3',ravel_aux_1='-1/4')
    values={};coords=[float(F(p[n])) for n in r['coordinates']]
    for factory in r['factories']:
        if factory.startswith('expr::'):
            name,tail=factory[6:].split('(',1)
            expression=ast.literal_eval(tail.split(',',1)[0]) if '\\"' in tail else tail.split('"')[1]
            expression=re.sub(r'@(\d+)',lambda m:repr(coords[int(m.group(1))]),expression)
            tree=ast.parse(expression,mode='eval')
            assert not any(isinstance(n,(ast.Attribute,ast.Subscript)) for n in ast.walk(tree))
            values[name]=eval(compile(tree,'synthetic_algebra','eval'),{'__builtins__':{},'pow':pow,'exp':math.exp})
        else:
            name,args=factory[5:].split('(',1);values[name]=sum(values[n] for n in args[:-1].split(','))
    expected=c.mean_jet(d,p)['means']
    assert [values[n] for n in r['functions']]==pytest.approx(expected,rel=1e-13,abs=1e-13)


def test_legacy_configuration_absent_field_and_source_relative_scope(tmp_path):
    d=fixture(tmp_path);cp,cfg=native_config(tmp_path,d)
    cfg['model'].pop('construction');cp.write_text(json.dumps(cfg))
    parsed=native._configuration({'input':str(cp)},tmp_path)
    assert parsed[8] is None and parsed[5] is None
    paths=native.inputs({'input':str(cp)},tmp_path)
    assert Path(c.__file__) not in paths and Path(d['sources'][0]['path']) not in paths


def test_fresh_bundle_refuses_symlink_alias_before_output(tmp_path):
    d=fixture(tmp_path);cp,cfg=native_config(tmp_path,d)
    link=tmp_path/'alias';link.symlink_to(tmp_path/'bundle',target_is_directory=True)
    with pytest.raises(ValueError,match='nonsymlink'):
        c.write_native_bundle(d,link/'new',runtime=cfg['runtime'],fit=cfg['fit'],max_seconds=30)
    assert not (tmp_path/'bundle/new').exists()


def test_literal_zero_coefficient_does_not_create_spurious_exp_overflow(tmp_path):
    d=fixture(tmp_path,True)
    d['terms'][-1]['coefficients']=['0']*4
    d['terms'][-1]['log_response']=[['10000','0'] for _ in 'ABCD']
    p=c.initial_point(d);p['ravel_aux_0']='1'
    j=c.mean_jet(d,p)
    assert j['means']==[30,10,15,5]
    assert all(row[-1]==0 for row in j['term_values'])


@pytest.mark.parametrize('mutation',[
    lambda p:p['workspace'].update(channels=list('ABCD')),
    lambda p:p['workspace'].update(data_entries=4),
    lambda p:p['workspace']['observables'].pop(),
    lambda p:p.pop('construction_linkage'),
    lambda p:p['construction_linkage']['rows'].pop(),
    lambda p:p['construction_linkage']['products'][1]['factors'].pop(),
    lambda p:p['construction_linkage']['products'][2]['factors'].append('ravel_aux_0_Pdf'),
    lambda p:p['construction_linkage']['leaves'][-1]['servers'].__setitem__(0,'ravel_aux_0'),
    lambda p:p['construction_linkage']['auxiliary_widths']['ravel_aux_0_Pdf'].update(value=2.),
    lambda p:p['construction_global_ranges']['ravel_aux_0_In'].update(has_min=True),
    lambda p:p['construction_observations'].update(dataset_weight=2.),
    lambda p:p['construction_observations']['counts'].pop('D'),
    lambda p:p['construction_observations']['auxiliary']['ravel_aux_0_In'].update(constant=False),
    lambda p:p['fixed_witnesses'][0].update(raw_nll_at_source_nuisance_values=float('nan')),
    lambda p:p['construction_linkage']['leaves'][0]['proxy_identity']['roles'].update(x='n_exp_binA',mean='n_obs_binA'),
    lambda p:p['construction_linkage']['leaves'][-1]['proxy_identity']['queries'].pop(),
])
def test_complete_vector_witness_refuses_altered_data_graph_auxiliary_or_raw_diagnostics(tmp_path,mutation):
    d=fixture(tmp_path,True);_,cfg=native_config(tmp_path,d);r=c.response(d)
    point=c.initial_point(d);s=state(d,point)
    probe=count_product_fixture(d,[{'point':'0','raw_nll_at_source_nuisance_values':123.,'construction_state':s,'scales':c.native_witness(r,s)},
                                 {'point':'1','raw_nll_at_source_nuisance_values':123.,'construction_state':state(d,{**point,'c':'1'}),'scales':c.native_witness(r,state(d,{**point,'c':'1'}))}])
    assert len(native._check_workspace(probe,cfg,r))==8
    mutation(probe)
    with pytest.raises(ValueError):native._check_workspace(probe,cfg,r)
