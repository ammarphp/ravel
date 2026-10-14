"""Synthetic full-law/width controls, not a published fit or native experiment."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib,json,math
from pathlib import Path
import time
import pytest
from ravel.physics import mass_width_grid as w,statistical_construction as r
from ravel.workflow import route_prompt,task_completion as tc,science,execution
from ravel.workflow.state_io import atomic_json,read_json

PROMPT="Construct the complete supplied ANA-0001 mass and width inputs."
REGIONS=("central_tagged","forward_tagged","central_antitagged","forward_antitagged")
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
def put(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 if isinstance(x,str):p.write_text(x)
 else:atomic_json(p,x)
 return pin(p)
def policy():
 return {'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'diagnostic':{'checks':['integrity'],'actions':['delivery','reuse']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}
def source(pin,id):return {'id':id,**{k:pin[k] for k in ('path','sha256')}}
def par(name,source,initial='1',bounds=None,role='rate'):
 return {'name':name,'role':role,'initial':initial,'bounds':bounds or ['1/100','10000'],'fixed':False,'meaning':'Explicit synthetic source parameter; no measured data.','source':source}
def law_fixture(base,n=2,k=1):
 evidence=put(base/'law-evidence.txt','Synthetic integer counts, correlations, transfer convention and exact four-region disjoint-law fixture.\n')
 windows=[[str(10+2*i),str(12+2*i)] for i in range(n)]
 return {'schema_version':1,'sources':[source(evidence,'lawsrc')],'windows':windows,
 'region_pairs':[{'id':'central','tagged':REGIONS[0],'antitagged':REGIONS[2]},{'id':'forward','tagged':REGIONS[1],'antitagged':REGIONS[3]}],
 'regions':[{'id':name,'role':'signal_region' if name==REGIONS[0] else 'control_region','observed':[10+i]*n if False else [10+i for i in range(n)],'source':'lawsrc'} for name in REGIONS],
 'transfer':{'degree':5,'domain':[windows[0][0],windows[-1][1]],'evaluation':'point','coordinates':[str(11+2*i) for i in range(n)],'coefficients':[par('kappa'+str(j),'lawsrc','1',['1/100','5']) for j in range(6)],'tag_efficiency':'13/100','log_response':[['1/10']*k for _ in range(4*n)],'source':'lawsrc'},
 'latent_rates':{side:[par(side+'_nu'+str(i),'lawsrc',str(100+i)) for i in range(n)] for side in ('central','forward')},
 'resonant_backgrounds':[{'id':'gammaV','expected_events':['5']*(4*n),'log_response':[['1/5']*k for _ in range(4*n)],'source':'lawsrc'}],
 'auxiliary':{'kind':'supplied_gaussian_factor','names':['sys'+str(i) for i in range(k)],'observed':['0']*k,'factor':[['1' if j==i else '1/10' if j<i else '0' for j in range(k)] for i in range(k)],'eta_bounds':[['-3','3'] for _ in range(k)],'source':'lawsrc'},
 'partition':{'kind':'declared_disjoint_poisson_counts','statement':'Synthetic source-declared disjoint tagged/antitagged central/forward integer counts.','source':'lawsrc'},
 'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Fixed exact synthetic response coefficients; no MC sampling law inferred.','source':'lawsrc'},
 'poi':par('strength','lawsrc','1',['0','3'],role='poi'),
 'assumptions':[{'id':'law_assumption','statement':'Supplied synthetic four-region law only.','source':'lawsrc','status':'assumed'}]}
def response_fixture(base,law,coord,signed=False):
 ev=put(base/'response-evidence.txt','Synthetic fixed point-specific full generated cohort/response; no detector or physics qualification.\n')
 m=F(str(coord['mass_GeV']));width=m*F(str(coord['width_over_mass']))
 card=put(base/'param.dat','BLOCK MASS\n 55 '+str(float(m))+'\nDECAY 55 '+str(float(width))+'\n 1.0 2 1 -1\n')
 n=len(law['windows']);k=len(law['auxiliary']['names'])
 comp=[{'basis':'bsm','selected_sumw':['1']*(4*n),'log_response':[['1/10']*k for _ in range(4*n)],'source':'pointsrc'}]
 if signed:comp.append({'basis':'interference','selected_sumw':['-1/2','1/2']*(2*n),'log_response':[['-1/10']*k for _ in range(4*n)],'source':'pointsrc'})
 return {'schema_version':1,'coordinate':coord,'sources':[source(ev,'pointsrc')],'observable':'mass_observable_GeV','windows':law['windows'],'region_ids':list(REGIONS),'energy_tev':13,'lumi_fb':140,
 'normalization':{'cross_section_pb':'1/100','includes_branching':True,'generated_sumw':'1000','accepted_sumw':str(4*n),'acceptance_definition':'accepted_over_complete_generated','efficiency_definition':'fit_bins_over_accepted','population':'All1000synthetic generated weight units; rejected units remain in the denominator.','source':'pointsrc'},
 'components':comp,'model':{'parameter_card':card,'pdg':55,'width_scheme':'fixed_pole_width','interference':'included_signed' if signed else 'neglected_by_assumption','coupling_projection':'none','source':'pointsrc','decay_channels':[[1,-1]]},
 'construction_metadata':{'model_id':'width_'+str(coord['mass_GeV'])+'_'+str(coord['width_over_mass']).replace('.','p'),'question':'Supplied ANA-0001 mass/width construction','energy':'13 TeV','luminosity':'140 fb^-1','scale':'pb x1000 x140fb^-1 /complete generated sumw; acceptance and efficiency applied exactly once through selected_sumw','domain_statement':'Complete supplied positive-mean domain'},
 'assumptions':[{'id':'response_assumption','statement':'Synthetic fixed all-bin response; no physical width or detector qualification.','source':'pointsrc','status':'assumed'}]}
def request_fixture(base,n=2,missing=False):
 base.mkdir(parents=True,exist_ok=True);contract=route_prompt.route(PROMPT);req=tc.initial_requirements(PROMPT);req['assignments']=[{'id':'width-child','purpose':'Full mass/width input construction retaining supplied grid and source population.','coverage':[{'obligation_id':'original-request','criteria':req['obligations'][0]['criteria']}]}];contract['task_requirements']=req;parent=put(base/'parent'/'inputs'/'task_contract.json',contract)
 law=law_fixture(base/'law',n);lp=put(base/'law.json',law)
 coordinates=[{'mass_GeV':40,'width_over_mass':.01},{'mass_GeV':40,'width_over_mass':.3}];cells=[]
 for i,co in enumerate(coordinates):
  rp=put(base/f'point{i}.json',response_fixture(base/f'p{i}',law,co));cells.append({'coordinate':co,'generation_request':None,'response':None if missing else rp,'missing':[]})
 request={'schema_version':2,'goal_binding':{'contract':parent,'assignment_id':'width-child'},'analysis':{'id':'ANA-0001','energy_tev':13,'lumi_fb':140,'observable':'mass_observable_GeV','pdg':55,'references':[pin(base/'law/law-evidence.txt')],'missing':[],'region_ids':list(REGIONS),'generation':{'beam_pdg':[2212,2212],'energy_gev':[6500,6500],'initial':['p','p'],'required_final':['a'],'decay_channels':[[1,-1]]}},'axes':[{'name':'mass_GeV','values':[40]},{'name':'width_over_mass','values':[.01,.3]}],'cells':cells,'regional_input':None if missing else lp,'native_runtime':None,'native_fit':None,'review_policy':None,'child_seconds':60,'output':{'result':{'filename':'mass-width-grid.json','format':'json'},'report':{'filename':'mass-width-grid-population.md','format':'markdown'}},'assumptions':['Supplied synthetic full source/API input construction, no actual generation/fit.']};p=base/'request.json';put(p,request);return p,request,law

@pytest.fixture(autouse=True)
def inert(monkeypatch):
 import subprocess
 monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(OSError('No external/provider/native calls allowed')))
 monkeypatch.setattr(execution,'runtime_context',lambda:{'source_control_inert_runtime':True,'environment_sha256':execution.digest(execution.runtime_environment())})

def test_exact_transfer_and_full_mean_independent_fraction(tmp_path):
 law=law_fixture(tmp_path/'law');co={'mass_GeV':40,'width_over_mass':.3};resp=response_fixture(tmp_path/'response',law,co,signed=True);d=w.construct(law,resp,co)
 values=r.initial_point(d);mean=r.mean_jet(d,values)['means'];n=2
 # Independently evaluate source Bernstein partition at kappa=1, with exact
 # common13/87 and fixed rate, signal amp^2 and signed interference amp.
 for i,row in enumerate(mean):
  side=(i//n)%2;anti=i>=2*n;idx=i%n;nu=F(100+idx);signal=F(7,5);interference=F(-7,10) if i%2==0 else F(7,10)
  expected=nu if anti else F(13,87)*nu
  assert math.isclose(row,float(expected+5+signal+interference),rel_tol=2e-15,abs_tol=2e-14)
 assert len(d['bins'])==8 and len(d['parameters'])==11 and all('central_nu' in str(x['powers']) or 'forward_nu' in str(x['powers']) or x['id'] in ('gammaV','signal_bsm','signal_interference') for x in d['terms'])
 assert d['prediction']['basis'].endswith('strength interference')

def test_bin_average_differs_from_midpoint_and_preserves_partition(tmp_path):
 law=law_fixture(tmp_path);t=law['transfer'];point=w.transfer_basis(t,law['windows']);t['evaluation']='bin_average';t['coordinates']=None;avg=w.transfer_basis(t,law['windows'])
 assert avg!=point and all(sum(row[i] for row in avg)==1 for i in range(2))
 # Independent exact integration of B_0^5 on first half [0,1/2].
 assert avg[0][0]==2*(1-F(1,2)**6)/6

def test_complete_supplied_geometry_native_serialization(tmp_path):
 law=law_fixture(tmp_path/'law',7,k=2);co={'mass_GeV':47,'width_over_mass':.17};resp=response_fixture(tmp_path/'response',law,co)
 d=w.construct(law,resp,co);compiled=r.response(d)
 assert (len(d['bins']),len(d['parameters']),len(d['terms']))==(28,21,100)
 assert len(compiled['functions'])==28 and len(compiled['coordinates'])==23
 assert len(r.datacard(d))>1000 and len(json.dumps(d))<4*1024**2

def test_real_ordinary_plan_pure_constructor_report_and_parent(tmp_path):
 p,d,_=request_fixture(tmp_path/'inputs');spec={'schema_version':2,'mode':'mass-width-grid','source':PROMPT,'assumptions':['Synthetic source/API control only.'],'max_seconds':60,'approval_mode':'scripted_yes','max_attempts':1,'goal_binding':d['goal_binding'],'review_policy':policy(),'task':{'input':str(p)}}
 from ravel.cli import main
 sp=put(tmp_path/'study.json',spec);rd=tmp_path/'ordinary';assert main(['plan','--rundir',str(rd),'--spec',sp['path']])==0;science.verify_plan(rd,approved=False)
 assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
 result=w.run(spec['task'],p.parent,tmp_path/'output');assert len(result['cells'])==2 and all(c['construction'] for c in result['cells'])
 from ravel.physics.science_worker import diagnostic_presentation
 diagnostic_presentation('mass-width-grid',result)
 from ravel.plotting.science_figures import render
 rendered=render(spec,result,p.parent,tmp_path/'output')
 assert rendered['status']=='passed' and not rendered['figures'] and len(rendered['tables'])==1
 text=(tmp_path/'output'/rendered['tables'][0]['files'][0]).read_text();assert '.3' in text and 'No generation' in text
 assert result['original_task_complete'] is False and result['coupling_projection'] is None
 for cell in result['cells']:
  doc=read_json(cell['construction']['path']);assert {'width_request','width_law','width_response','width_parameter_card'}<=set(x['id'] for x in doc['sources'])

@pytest.mark.parametrize('fault',['absent','changed'])
def test_outer_original_goal_cannot_be_removed_or_substituted(tmp_path,fault):
 p,d,_=request_fixture(tmp_path/'input');s={'schema_version':2,'mode':'mass-width-grid','source':PROMPT,'assumptions':['Synthetic only'],'max_seconds':60,'approval_mode':'scripted_yes','max_attempts':1,'task':{'input':str(p)}}
 if fault=='changed':
  _,other,_=request_fixture(tmp_path/'other');s['goal_binding']=other['goal_binding']
 with pytest.raises(ValueError,match='outer parent'):science.task_inputs(s,tmp_path)

def test_all_missing_cells_remain_and_no_zero_limit_or_native_spec(tmp_path):
 p,d,_=request_fixture(tmp_path/'input',missing=True);res=w.run({'input':str(p)},p.parent,tmp_path/'out')
 assert len(res['cells'])==2 and all(c['state']=='blocked' and c['native_specification'] is None and c['construction'] is None for c in res['cells'])
 assert res['fits']==0 and res['generated_events']==0 and res['original_task_complete'] is False

def connected_fixture(base):
 from test_model_events import config as generation_config
 from test_native_likelihood import fixture as native_fixture,fit
 p,d,law=request_fixture(base/'inputs')
 for i,row in enumerate(d['cells']):
  response=read_json(row['response']['path']);root=base/('generator'+str(i));config=generation_config(root)
  config['cards']['parameter']={k:response['model']['parameter_card'][k] for k in ('path','sha256')}
  config['cards']['process']={k:v for k,v in put(root/'photon-process.dat','define p = g u u~ d d~\ngenerate p p > a zp\n').items() if k!='size'}
  cp=put(root/'config.json',config);pol=put(root/'review-policy.json',policy())
  row['generation_request']=put(root/'request.json',{'schema_version':1,'config':{k:cp[k] for k in ('path','sha256')},'review_policy':{k:pol[k] for k in ('path','sha256')},'supervisor_seconds':90,'goal_binding':d['goal_binding']})
 nroot=base/'native';nroot.mkdir();_,native,_,_,_=native_fixture(nroot)
 d['native_runtime']=put(nroot/'runtime.json',native['runtime']);nf=fit('MultiDimFit');nf.update(poi='strength',domain=['0','3'])
 d['native_fit']=put(nroot/'fit.json',nf);d['review_policy']=put(nroot/'policy.json',policy());put(p,d)
 return p,d

def test_each_point_reaches_existing_generation_and_native_ordinary_input(tmp_path):
 p,d=connected_fixture(tmp_path/'source');result=w.run({'input':str(p)},p.parent,tmp_path/'out')
 assert all(row['state']=='prepared_unapproved' and not row['missing'] for row in result['cells'])
 for row in result['cells']:
  assert row['generation_preparation']['new_events_generated']==0
  gs=read_json(row['generation_preparation']['specification']['path']);ns=read_json(row['native_specification']['path'])
  assert gs['mode']=='model-events' and ns['mode']=='native-likelihood' and gs['goal_binding']==ns['goal_binding']==d['goal_binding']
  assert len(science.task_inputs(ns,Path(row['native_specification']['path']).parent))>=10
 assert not result['original_task_complete'] and result['generated_events']==result['fits']==0

@pytest.mark.parametrize('fault',['beam','photon','generator_card','parent'])
def test_generation_changes_cannot_be_hidden_under_a_width_label(tmp_path,fault):
 p,d=connected_fixture(tmp_path/'source');rp=Path(d['cells'][0]['generation_request']['path']);req=read_json(rp);cp=Path(req['config']['path']);cfg=read_json(cp)
 if fault=='beam':cfg['generation']['energy_gev']=[7000,7000]
 elif fault=='photon':cfg['cards']['process']={k:v for k,v in put(cp.parent/'photon-process.dat','generate p p > zp\n').items() if k!='size'}
 elif fault=='generator_card':cfg['cards']['parameter']={k:v for k,v in put(cp.parent/'other-param.dat','BLOCK MASS\n 55 40\nDECAY 55 0.4\n 1.0 2 1 -1\n').items() if k!='size'}
 else:req['goal_binding']=None
 req['config']={k:v for k,v in put(cp,cfg).items() if k!='size'};d['cells'][0]['generation_request']=put(rp,req);put(p,d)
 with pytest.raises(ValueError):w.inputs({'input':str(p)},p.parent)

@pytest.mark.parametrize('fault',['unknown_interference','observable','negative_component'])
def test_missing_data_does_not_disable_provided_response_admission(tmp_path,fault):
 p,d,_=request_fixture(tmp_path/'inputs');d['regional_input']=None;rp=Path(d['cells'][0]['response']['path']);response=read_json(rp)
 if fault=='unknown_interference':response['model']['interference']='unknown'
 elif fault=='observable':response['observable']='parton_mqq_GeV'
 else:response['components'][0]['selected_sumw'][0]='-1'
 d['cells'][0]['response']=put(rp,response);put(p,d)
 with pytest.raises(ValueError):w.inputs({'input':str(p)},p.parent)

@pytest.mark.parametrize('fault',['fractional','auxiliary','transfer_domain','latent_bounds'])
def test_missing_response_does_not_disable_provided_data_law_admission(tmp_path,fault):
 p,d,law=request_fixture(tmp_path/'inputs');d['cells'][0]['response']=d['cells'][1]['response']=None
 if fault=='fractional':law['regions'][0]['observed'][0]=2.125
 elif fault=='auxiliary':law['auxiliary']['factor']=[['-1']]
 elif fault=='transfer_domain':law['transfer']['domain']=['0','1']
 else:law['latent_rates']['central'][0]['bounds']=['-1','1000']
 d['regional_input']=put(Path(d['regional_input']['path']),law);put(p,d)
 with pytest.raises(ValueError):w.inputs({'input':str(p)},p.parent)

def test_supplied_cartesian_population_retains_all_blocked_cells(tmp_path):
 p,d,_=request_fixture(tmp_path/'inputs',missing=True);masses=[17,29,311];widths=[.017,.12,.47]
 d['axes']=[{'name':'mass_GeV','values':masses},{'name':'width_over_mass','values':widths}]
 d['cells']=[{'coordinate':{'mass_GeV':m,'width_over_mass':g},'generation_request':None,'response':None,'missing':[]} for m in masses for g in widths];put(p,d)
 result=w.run({'input':str(p)},p.parent,tmp_path/'out')
 assert len(result['cells'])==9 and all(c['state']=='blocked' for c in result['cells'])
 assert [c['coordinate'] for c in result['cells']]==[c['coordinate'] for c in d['cells']]

@pytest.mark.parametrize('fault',['drop_cell','order','stop_short','duplicate_width','card_width','card_br','region','observable','bin','density','empty_sources','unknown_interference','coupling','negative_bsm','denominator','normalization','no_contamination','bad_shared_response'])
def test_scientific_input_adversaries(tmp_path,fault):
 p,d,law=request_fixture(tmp_path/'input');rp=Path(d['cells'][1]['response']['path']);response=read_json(rp)
 if fault=='drop_cell':d['cells'].pop()
 elif fault=='order':d['cells'].reverse()
 elif fault=='stop_short':d['axes'][1]['values'][-1]=.2
 elif fault=='duplicate_width':d['axes'][1]['values'][-1]=.01
 elif fault=='card_width':
  cp=Path(response['model']['parameter_card']['path']);response['model']['parameter_card']=put(cp,cp.read_text().replace('12.0','4.0'))
 elif fault=='card_br':
  cp=Path(response['model']['parameter_card']['path']);response['model']['parameter_card']=put(cp,cp.read_text().replace('1.0 2 1 -1','0.5 2 1 -1\n 0.5 2 52 -52'))
 elif fault=='region':response['region_ids'].reverse()
 elif fault=='observable':response['observable']='parton_mqq_GeV'
 elif fault=='bin':response['windows'][0][0]='9'
 elif fault=='density':law['regions'][0]['observed'][0]=2.125
 elif fault=='empty_sources':response['sources']=[]
 elif fault=='unknown_interference':response['model']['interference']='unknown'
 elif fault=='coupling':response['model']['coupling_projection']='gq0_sqrt_mu'
 elif fault=='negative_bsm':response['components'][0]['selected_sumw'][0]='-1'
 elif fault=='denominator':response['normalization']['generated_sumw']='0'
 elif fault=='normalization':response['normalization']['includes_branching']=False
 elif fault=='no_contamination':response['components'][0]['selected_sumw']=response['components'][0]['selected_sumw'][:2]
 elif fault=='bad_shared_response':law['transfer']['log_response']=[[]]*8
 d['regional_input']=put(Path(d['regional_input']['path']),law)
 if len(d['cells'])>1:d['cells'][1]['response']=put(rp,response)
 put(p,d)
 with pytest.raises(ValueError):w.inputs({'input':str(p)},p.parent)

@pytest.mark.parametrize('field',['bins', 'parameters','terms'])
def test_dimension_ceilings_still_refuse(tmp_path,field,maximum=None):
 law=law_fixture(tmp_path/'law');co={'mass_GeV':40,'width_over_mass':.3};d=w.construct(law,response_fixture(tmp_path/'response',law,co),co)
 limit={'bins':256,'parameters':128,'terms':1024}[field];d[field]=[deepcopy(d[field][0]) for _ in range(limit+1)]
 with pytest.raises(ValueError,match='bounded'):r.validate(d)

def test_initial_source_and_generated_bytes_changed_at_completion_refuse(tmp_path,monkeypatch):
 p,d,_=request_fixture(tmp_path/'input');old=w._write
 def changed(out,name,value,cap):
  got=old(out,name,value,cap)
  if name=='mass-width-grid.json':
   original=Path(value['cells'][0]['construction']['path']);original.write_text('{}')
  return got
 monkeypatch.setattr(w,'_write',changed)
 with pytest.raises(ValueError,match='changed'):w.run({'input':str(p)},p.parent,tmp_path/'out')
 assert not (tmp_path/'out/mass-width-grid.json').exists() and (tmp_path/'out/failed-mass-width-grid.json').exists()


def test_actual_common_worker_report_tail_retains_complete_conditional_inputs(tmp_path,monkeypatch):
 """Actual adapter/renderer/worker; only existing authority/spec transport inert."""
 from ravel.physics import science_worker
 p,d,_=request_fixture(tmp_path/'inputs')
 spec={'schema_version':2,'mode':'mass-width-grid','source':PROMPT,
       'assumptions':['Artificial source/API worker-tail control; no approval or physics authority.'],
       'max_seconds':60,'max_attempts':1,'approval_mode':'scripted_yes',
       'review_policy':policy(),'goal_binding':d['goal_binding'],'task':{'input':str(p)}}
 science.validate(spec);science.task_inputs(spec,p.parent)
 rd=tmp_path/'ordinary'
 monkeypatch.setattr(science_worker,'verify_worker',lambda root:{'base_dir':str(p.parent),
     'output_directory':'outputs','stage_binding':{'input_snapshot':[]}})
 monkeypatch.setattr(science_worker,'execution_spec',lambda root:spec)
 assert science_worker.main([str(rd)])==0
 out=rd/'outputs';result=read_json(out/'result.json');figures=read_json(out/'figures.json')
 assert result['physics_validated'] is False and result['original_task_complete'] is False
 assert len(result['cells'])==2 and all(c['construction'] for c in result['cells'])
 assert not figures['figures'] and len(figures['tables'])==1
 assert figures['tables'][0]['files']==['mass-width-grid-population.md']
 for name in figures['tables'][0]['files']:
  assert (out/name).is_file() and name in (out/'RESULT.md').read_text()
 assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
 assert read_json(out/'verification.json')['physics_validated'] is False
 assert read_json(out/'recipe.json')['specification']['goal_binding']==d['goal_binding']


@pytest.mark.parametrize('target',['construction','completion'])
@pytest.mark.parametrize('change',['scientific_value','whitespace'])
def test_generated_writer_cannot_change_intended_science_or_exact_bytes(tmp_path,monkeypatch,target,change):
 p,_,_=request_fixture(tmp_path/'inputs');original=w.atomic_json
 def corrupt(path,value):
  affected=(target=='construction' and path.name=='point-0-construction.json') or (target=='completion' and path.name=='mass-width-grid.json')
  changed=deepcopy(value)
  if affected and change=='scientific_value':
   if target=='construction':changed['terms'][-1]['coefficients'][0]='140'
   else:changed['physics_validated']=True
  original(path,changed)
  if affected and change=='whitespace':path.write_bytes(path.read_bytes()+b'\n')
 monkeypatch.setattr(w,'atomic_json',corrupt)
 with pytest.raises(ValueError,match='intended bytes'):
  w.run({'input':str(p)},p.parent,tmp_path/'out')
 assert not (tmp_path/'out/mass-width-grid.json').exists()
 retained=tmp_path/'out'/('point-0-construction.json' if target=='construction' else 'failed-mass-width-grid.json')
 assert retained.is_file()
