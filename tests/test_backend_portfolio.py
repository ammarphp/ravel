"""Portable source/native-format/ordinary-plan controls; no native execution.

PAD process and completed review seams are explicit stand-ins. Genuine source
booking/SAF decoding, adapter admission, public planning and context completion
are exercised. These tests do not qualify installed backends or physicist review.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import pytest
from ravel.physics import ma5_bookings as book, ma5_family as family, ma5_pad as pad, ma5_saf as saf
from ravel.workflow import science, backend_portfolio as portfolio, scientific_context as sc, agent_host as host
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.execution import digest


def pin(p): return {'path':str(p.absolute()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def put(p,s): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s);return pin(p)
def write(p,v): atomic_json(p,v);return pin(p)
def framed(s): return '<SAFheader>\n</SAFheader>\n'+s+'\n<SAFfooter>\n</SAFfooter>\n'
SOURCE='''bool Arbitrary::Initialize(const Configuration& cfg) {
Manager()->AddRegionSelection("SR low");
Manager()->AddRegionSelection("CR");
Manager()->AddRegionSelection("SR high");
std::string selected[] = {"SR low","SR high"};
Manager()->AddCut("shared cut");
Manager()->AddCut("signal cut",selected);
Manager()->AddHisto("signed eta",2,-2e0,+2.0);
return true;
}
bool Arbitrary::Execute() { return true; }
'''
EXPECTED={'regions':['SR low','CR','SR high'],'cuts':{'SR low':['shared cut','signal cut'],'CR':['shared cut'],'SR high':['shared cut','signal cut']},
 'histograms':[{'name':'signed eta','nbins':2,'xmin':-2.,'xmax':2.,'regions':['SR low','CR','SR high']}]}

# Literal API fixture from the pinned native writer, never compiled.
CORE_SOURCE = 'inline void ReplaceAll(std::string &name, const std::string &In, const std::string &Out)\n{\n  size_t pos = name.find(In);\n  while(pos!=std::string::npos)\n  {\n    name.replace(pos,In.size(),Out);\n    pos = name.find(In);\n  }\n}\n\ninline std::string CleanName(const std::string &name)\n{\n  std::string tmp=name;\n  ReplaceAll(tmp, "/",  "_slash_");\n  ReplaceAll(tmp, "->", "_to_");\n  ReplaceAll(tmp, ">=", "_greater_than_or_equal_to_");\n  ReplaceAll(tmp, ">",  "_greater_than_");\n  ReplaceAll(tmp, "<=", "_smaller_than_or_equal_to_");\n  ReplaceAll(tmp, "<",  "_smaller_than_");\n  ReplaceAll(tmp, " ",  "_");\n  ReplaceAll(tmp, ",",  "_");\n  ReplaceAll(tmp, "+",  "_");\n  ReplaceAll(tmp, "-",  "_");\n  ReplaceAll(tmp, "(",  "_lp_");\n  ReplaceAll(tmp, ")",  "_rp_");\n  return tmp;\n}\n\n\nvoid source_writer_roles() {\n std::string a = analyzers_[i]->Output() + "/" + analyzers_[i]->name() + ".saf";\n std::string b = analyzers_[i]->Output() + "/Histograms/histos.saf";\n std::string c = myanalysis->Output() + "/Cutflows/" + CleanName(myRS->GetName()) + ".saf";\n}\n'

def histogram():
 return framed('''<Histo>
<Description>
"signed eta"
2 -2 2
SR low
CR
SR high
</Description>
<Statistics>
8 3
12.5 4.25
6 2
9.25 3.5
20.125 7.75
-2.5 -1.0
48.0 13.25
</Statistics>
<Data>
1.25 0.25
2.5 1.0
4.0 1.5
1.5 0.75
</Data>
</Histo>''')

def view(root):
 texts={'Arbitrary.saf':framed('<RegionSelection>\n"SR low"\n"CR"\n"SR high"\n</RegionSelection>'),'Histograms/histos.saf':histogram()}
 for r in EXPECTED['regions']:
  text='<InitialCounter>\n"Initial number of events"\n8 3\n12.5 4.25\n20.125 7.75\n</InitialCounter>'
  for cut in EXPECTED['cuts'][r]: text+='\n<Counter>\n"'+cut+'"\n6 2\n9.25 3.5\n18.0 7.0\n</Counter>'
  texts['Cutflows/'+r.replace(' ','_')+'.saf']=framed(text)
 for rel,text in texts.items():put(root/rel,text)
 return {rel:pin(root/rel)['sha256'] for rel in texts}

def family_fixture(base,views=1):
 source=put(base/'analysis.cc',SOURCE)
 bookings=write(base/'bookings.json',{**EXPECTED,'source':source,'scope':'Exact synthetic literal source denominator'})
 api=put(base/'manager.h','// Synthetic declared API bytes, not native runtime\n'); core=put(base/'core.cpp',CORE_SOURCE)
 doc={'schema_version':2,'analysis':'Arbitrary','source':source,'bookings':bookings,
 'upstream':{'manager':api,'saf_writer':api,'core':core,'revision':'Synthetic format/source control'},
 'views':{str(i):{'root':str(base/('view'+str(i))),'files':view(base/('view'+str(i))), 'expected_initial_entries':11,'population_description':'8 positive3 negative; exact synthetic sign-channel fixture'} for i in range(views)},
 'population_scope':'Complete independent named supplied populations; no common-event join'}
 write(base/'family.json',doc);return {'input':str(base/'family.json')},doc


def policy():
 return {'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},
 'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],
 'claim_scopes':{'diagnostic':{'checks':['integrity'],'actions':['delivery','reuse']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}

def spec(task,mode='ma5-saf',seconds=40):
 return {'schema_version':2,'mode':mode,'source':'Explicitly synthetic portable configured provider source control',
 'assumptions':['No native runtime or physics validation'],'max_seconds':seconds,'approval_mode':'scripted_yes','task':task,
 'max_attempts':1,'review_policy':policy()}

def original(base):
 api=put(base/'original-api.py','def requested(data):\n    return data\n')
 request={'schema_version':1,'task_id':'original','task':'Deliver complete three-region records preserving the supplied model and sign channels.',
 'source_capsules':[],'api_documents':[{'id':'api','pin':api,'language':'python','role':'api','version':'Synthetic','dependencies':[]}],
 'queries':[{'id':'requested','symbol':'requested','mode':'definition','documents':['api'],'required':True}],
 'requested_quantities':[{'id':'all-regions','artifact':'records','pointer':'/views/0/regions','check':{'kind':'record-census','id_field':'id','expected_ids':['SR low','CR','SR high'],'finite_fields':[]},'meaning':'Complete source region population'}],
 'compatibility_groups':[{'id':'one','artifacts':['records'],'carryover':False,'basis':'Current complete source population'}],
 'max_source_bytes':128000,'max_context_bytes':16000,'max_steps':4}
 # The context has a direct complete primitive census check for region strings.
 request['requested_quantities'][0].update(pointer='/views/0/regions',check={'kind':'exact','value':EXPECTED['regions']})
 return write(base/'original.json',request)

def portfolio_fixture(base):
 task,doc=family_fixture(base/'ma5');source=doc['source'];study=write(base/'study-offer.json',spec(task))
 req={'schema_version':1,'original_context':original(base),'model':put(base/'model.slha','BLOCK MASS\n  1001 100\n'),
 'signal_basis':'signed_interference','energy_tev':13.,'studies':[{'id':'ma5-full','backend':'ma5','study':study,
 'applicability':{'routine_ids':['Arbitrary'],'energy_tev':13.,'model_bases':['signed_interference'],'source_basis':[source], 'unresolved':[]},
 'outputs':{'records':{'pointer':'','quantity_ids':['all-regions']}},'handoff_inputs':[doc['source']], 'claim_scope':'diagnostic'}]}
 path=base/'portfolio.json';write(path,req);return path,req


def test_exact_literal_three_region_bookings(): assert book.compile_source(SOURCE)==EXPECTED
@pytest.mark.parametrize('before,after',[
 ('Manager()->AddCut("shared cut");','if (flag) Manager()->AddCut("shared cut");'),
 ('Manager()->AddHisto','Manager()->AddHistoLogX'),
 ('2,-2e0,+2.0','bins,-2e0,+2.0'),
 ('2,-2e0,+2.0','2,0,0'),
 ('2,-2e0,+2.0','2,-1e999,2'),
 ('std::string selected[]','std::string selected[3]'),
 ('Manager()->AddCut("shared cut");','selected[0]="CR"; Manager()->AddCut("shared cut");'),
 ('Manager()->AddCut("shared cut");','mutate(selected); Manager()->AddCut("shared cut");'),
 ('"SR high"};','"missing"};'),
 ('Manager()->AddCut("shared cut");','Manager()->AddCut("shared cut"); Manager()->AddCut("shared cut");')])
def test_bookings_refuse_dynamic_incomplete_or_ambiguous_population(before,after):
 with pytest.raises(ValueError):book.compile_source(SOURCE.replace(before,after))
def test_comment_only_fake_booking_ignored_but_late_booking_refused():
 assert book.compile_source('// AddHisto("fake",1,0,1)\n'+SOURCE)==EXPECTED
 with pytest.raises(ValueError):book.compile_source(SOURCE.replace('return true; }','Manager()->AddCut("late");return true; }'))

@pytest.mark.parametrize('views',[1,3])
def test_arbitrary_named_view_family_complete( tmp_path,views):
 task,doc=family_fixture(tmp_path,views);files=saf.inputs(task,tmp_path);assert Path(doc['source']['path']) in files
 result=saf.run(task,tmp_path,tmp_path/'output')
 assert len(result['views'])==views and result['source_bookings']==EXPECTED
 h=result['views']['0']['histograms'][0]
 assert h['negative']['array']==[1.,1.5] and h['positive']['underflow']==1.25
 assert h['positive']['sumwx']==-2.5 and h['per_bin_sumw2'] is None
 assert not result['native_engine_executed'] and not result['same_event_population_validated']
@pytest.mark.parametrize('fault',['extra','missing','rebook','denominator','alias','partial','nonfinite','mixed-initial'])
def test_family_complete_census_and_raw_semantics_refuse(tmp_path,fault):
 task,d=family_fixture(tmp_path,2);root=Path(d['views']['0']['root'])
 if fault=='extra':put(root/'Cutflows/extra.saf','extra')
 elif fault=='missing':(root/'Cutflows/CR.saf').unlink()
 elif fault=='rebook':
  q=read_json(d['bookings']['path']);q['cuts']['CR']=[];d['bookings']=write(Path(d['bookings']['path']),q)
 elif fault=='denominator':d['views']['0']['expected_initial_entries']=10
 elif fault=='alias':d['views']['1']['root']=d['views']['0']['root']
 else:
  p=root/('Histograms/histos.saf' if fault in ('partial','nonfinite') else 'Cutflows/CR.saf')
  text=p.read_text().replace('1.5 0.75\n','') if fault=='partial' else p.read_text().replace('9.25 3.5','nan 3.5') if fault=='nonfinite' else p.read_text().replace('12.5 4.25','13.5 4.25')
  p.write_text(text);d['views']['0']['files'][str(p.relative_to(root))]=pin(p)['sha256']
 write(Path(task['input']),d)
 with pytest.raises(ValueError):saf.inputs(task,tmp_path)

def pad_fixture(base):
 _,family_doc=family_fixture(base/'sources');d={k:deepcopy(family_doc[k]) for k in ('analysis','source','bookings')}
 exe=base/'SampleAnalyzer';put(exe,'#!/bin/sh\n# NEVER EXECUTED\n');exe.chmod(0o700)
 main=put(base/'main.cpp','manager.Initialize(argc,argv,"pdg.ma5"); manager.InitializeAnalyzer("Arbitrary","analysis.saf",parameters);')
 api=family_doc['upstream']['manager'];asset=put(base/'pdg.ma5','Synthetic PDG source\n');empty=base/'__init__.py';empty.write_bytes(b'')
 d.update(schema_version=1,upstream={**family_doc['upstream'],'configuration':api},events=[put(base/'events.hepmc','Synthetic file not a physics event\n')],staged_assets={'pdg.ma5':asset},
 population={'expected_initial_entries':11,'description':'Complete synthetic signed records','basis':'signed_interference','weight_convention':'Raw sign channels preserved','response':'Declared detector response unqualified'},max_seconds=1,max_ram_mib=512)
 runtime_files=[pin(empty),api];receipt=write(base/'build-receipt.json',{'executable':pin(exe),'main':main,'source':d['source'],'assets':d['staged_assets'],'runtime_files':runtime_files,'scope':'Declared synthetic build only; no source-consumption proof'})
 d['runtime']={'executable':pin(exe),'main':main,'build_receipt':receipt,'files':runtime_files};task={'input':str(base/'pad.json')};write(Path(task['input']),d);return task,d

def test_pad_general_admission_streams_large_events_and_empty_runtime(tmp_path):
 task,d=pad_fixture(tmp_path);path=Path(d['events'][0]['path']);path.write_bytes(b'x'*(saf.MAX_FILE+1));d['events']=[pin(path)];write(Path(task['input']),d)
 assert path in pad.inputs(task,tmp_path) and pad.execution_seconds(task,tmp_path)==31
 science.validate(spec(task,'ma5-pad'))
@pytest.mark.parametrize('fault',['source','runtime','basis','assets','main','eventduplicate','injection','budget'])
def test_pad_stale_or_incomplete_handoff_refuses(tmp_path,fault):
 task,d=pad_fixture(tmp_path)
 if fault=='source':Path(d['source']['path']).write_text(SOURCE+'\n// drift')
 elif fault=='runtime':d['runtime']['files']=[]
 elif fault=='basis':d['population']['basis']='unknown'
 elif fault=='assets':d['staged_assets']['../pdg.ma5']=d['staged_assets'].pop('pdg.ma5')
 elif fault=='main':d['runtime']['main']=put(Path(d['runtime']['main']['path']),'InitializeAnalyzer("Other","analysis.saf",p);')
 elif fault=='eventduplicate':d['events']*=2
 elif fault=='injection':d['events']=[put(tmp_path/'event\ninjected','event')]
 else:d['max_seconds']=3601
 write(Path(task['input']),d)
 with pytest.raises(ValueError):pad.inputs(task,tmp_path)

def test_pad_existing_supervisor_command_and_complete_readback(tmp_path,monkeypatch):
 task,d=pad_fixture(tmp_path/'source');rd=tmp_path/'run';out=rd/'outputs/attempt-1';rd.mkdir();write(rd/science.PLAN,{'synthetic':True});calls=[]
 monkeypatch.setattr(science,'verify_worker',lambda _: {'output_directory':'outputs/attempt-1','max_seconds':40})
 monkeypatch.setattr(science,'execution_spec',lambda _:spec(task,'ma5-pad'))
 def inert(command,cwd,document):
  calls.append((command,cwd));assert (cwd/'pdg.ma5').read_bytes()==Path(d['staged_assets']['pdg.ma5']['path']).read_bytes()
  assert Path(command[1]).read_text()==d['events'][0]['path']+'\n'
  view(cwd.parent/'Output/SAF/supplied/Arbitrary_0');return {'exit_code':0,'scope':'Explicit inert process seam, no native call'}
 from ravel.physics import reinterpret_db
 monkeypatch.setattr(reinterpret_db,'execute_native',inert)
 result=pad.run(task,tmp_path,out);assert len(calls)==1 and calls[0][0][0]==d['runtime']['executable']['path']
 assert result['views']['native']['regions']==EXPECTED['regions'] and result['population']['basis']=='signed_interference'
 assert result['source_consumption_verified'] is False
 with pytest.raises(FileExistsError):pad.run(task,tmp_path,out)

def test_pad_public_boundary_requires_real_ordinary_worker(tmp_path):
 task,d=pad_fixture(tmp_path)
 with pytest.raises(ValueError,match='approved'):pad.run(task,tmp_path,tmp_path/'output')

def test_portfolio_choice_complete_scoped_handoff_and_public_plan(tmp_path):
 path,r=portfolio_fixture(tmp_path);before=read_json(r['studies'][0]['study']['path']);decision=portfolio.assess(path)
 assert decision['studies'][0]['applicable'] and decision['cross_backend_combination'] is None
 bundle=portfolio.prepare(path,['ma5-full'],tmp_path/'handoff');new=read_json(bundle['branches'][0]['study']['path']);science.validate(new)
 assert before==read_json(r['studies'][0]['study']['path']) and 'backend_handoff' in new
 files=science.task_inputs(new,Path(bundle['branches'][0]['study']['path']).parent)
 assert path in files and Path(r['model']['path']) in files and Path(r['original_context']['path']) in files
 planned=science.plan(tmp_path/'ordinary',bundle['branches'][0]['study']['path'])
 assert planned['schema_version']==2 and not (tmp_path/'ordinary'/science.APPROVAL).exists()
@pytest.mark.parametrize('fault',['energy','basis','unresolved','quantity','scope','route','source'])
def test_portfolio_explicit_inapplicability_and_scope_refusals(tmp_path,fault):
 path,r=portfolio_fixture(tmp_path);row=r['studies'][0]
 if fault=='energy':row['applicability']['energy_tev']=8
 elif fault=='basis':row['applicability']['model_bases']=['bsm']
 elif fault=='unresolved':row['applicability']['unresolved']=['Missing detector applicability review']
 elif fault=='quantity':row['outputs']['records']['quantity_ids']=['foreign']
 elif fault=='scope':row['claim_scope']='physics'
 elif fault=='route':row['backend']='contur'
 else:Path(row['applicability']['source_basis'][0]['path']).write_text('changed')
 write(path,r)
 if fault in ('energy','basis','unresolved'):
  assert not portfolio.assess(path)['studies'][0]['applicable']
  with pytest.raises(ValueError,match='inapplicable'):portfolio.prepare(path,['ma5-full'],tmp_path/'handoff')
 else:
  with pytest.raises(ValueError):portfolio.assess(path)

def test_rehashed_handoff_cannot_change_provider_scope(tmp_path):
 path,r=portfolio_fixture(tmp_path);bundle=portfolio.prepare(path,['ma5-full'],tmp_path/'handoff');s=read_json(bundle['branches'][0]['study']['path']);s['max_seconds']+=1
 with pytest.raises(ValueError,match='scope'):science.task_inputs(s,tmp_path)

def terminal_standin(tmp_path,monkeypatch,accepted):
 path,r=portfolio_fixture(tmp_path);bundle=portfolio.prepare(path,['ma5-full'],tmp_path/'handoff');s=read_json(bundle['branches'][0]['study']['path']);rd=tmp_path/'finished';out=rd/'outputs/attempt-1';out.mkdir(parents=True)
 write(rd/science.PLAN,{'synthetic':True});write(rd/'attempt.json',{'status':'succeeded'});result=saf.run(s['task'],tmp_path,out/'ma5-saf');write(out/'result.json',result)
 monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{});monkeypatch.setattr(science,'execution_spec',lambda _:s)
 monkeypatch.setattr(science,'packet',lambda _: {'execution':{'status':'succeeded'},'errors':[]})
 monkeypatch.setattr(science.execution,'load_execution',lambda _:{'stages':{'science':{'attempt_record':'attempt.json'}}})
 monkeypatch.setattr(science,'_selected',lambda *a:({'outputs':['outputs/attempt-1']},40,{}))
 monkeypatch.setattr(portfolio.physics_review,'active',lambda _:accepted)
 monkeypatch.setattr(portfolio.physics_review,'status',lambda _:{'state':'accepted','claim_scope':'diagnostic','live_errors':[]})
 monkeypatch.setattr(portfolio.physics_review,'snapshot',lambda *a,**k:{'explicit':'inert accepted-review seam'})
 monkeypatch.setattr(portfolio.physics_review,'validate_snapshot',lambda _:[])
 return path,rd
@pytest.mark.parametrize('accepted',[False,True])
def test_original_context_continues_only_from_scoped_accepted_complete_result(tmp_path,monkeypatch,accepted):
 path,rd=terminal_standin(tmp_path,monkeypatch,accepted)
 result=portfolio.ingest(path,{'ma5-full':str(rd)},tmp_path/'delivery')
 assert result['quantity_completion'] is accepted and result['studies'][0]['scientific_accepted'] is accepted
 assert result['studies'][0]['complete_native_result']['views']['0']['histograms'][0]['negative']['array']==[1,1.5]
 assert result['cross_backend_combination'] is None and result['physics_validated'] is False

def test_wrong_branch_or_changed_terminal_custody_cannot_complete(tmp_path,monkeypatch):
 path,rd=terminal_standin(tmp_path,monkeypatch,True)
 monkeypatch.setattr(science,'packet',lambda _:{'execution':{'status':'succeeded'},'errors':['Output changed']})
 with pytest.raises(ValueError,match='invalid'):portfolio.ingest(path,{'ma5-full':str(rd)},tmp_path/'delivery')

class Control:
 def __init__(self):self.calls=[]
 def cancelled(self):return False
 def check_cancelled(self):pass
 def call(self,label,kind,request,function,output_tokens=0):self.calls.append(label);return function()
def host_request(paths,role='proposer'):
 inputs=[{'id':str(i),**pin(p)} for i,p in enumerate(paths)]
 node={'id':'backend','kind':'tool','role':role,'depends_on':[],'inputs':inputs,'packet':None,'action':'backend-portfolio','parameters':{'request_input':'0'},'max_attempts':1}
 req={'schema_version':1,'graph_id':'backend-control','graph_revision':'a'*64,'node_id':'backend','generation':1,'node_sha256':digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(inputs),'packet':None,'dependencies':[]}
 return node,req

def test_real_host_action_requires_all_graph_inputs_and_rejects_blind_role(tmp_path):
 path,r=portfolio_fixture(tmp_path);n,req=host_request([path]);ctl=Control()
 with pytest.raises(host.HostFailure,match='unbound'):host.AgentHost().execute(n,req,ctl)
 assert not ctl.calls
 files=[path,*[Path(p['path']) for p in portfolio.input_pins(path) if Path(p['path'])!=path]]
 n,req=host_request(files);result=host.AgentHost().execute(n,req,ctl)
 assert result['value']['studies'][0]['applicable'] and ctl.calls==['backend-portfolio']
 n,req=host_request(files,'verifier')
 with pytest.raises(host.HostFailure):host.AgentHost().execute(n,req,Control())

def test_host_identity_binds_new_portfolio_and_general_ma5_sources():
 sources=host.AgentHost().identity['sources']
 for module in (portfolio,pad,family,book,saf): assert module.__name__ in sources


def add_offer(path,r,identity,backend,configuration,task,mode,bases):
 study=write(path.parent/(identity+'-study.json'),spec(task,mode,120))
 r['studies'].append({'id':identity,'backend':backend,'study':study,
  'applicability':{'routine_ids':[identity],'energy_tev':13.,'model_bases':bases,'source_basis':[pin(configuration)],'unresolved':[]},
  'outputs':deepcopy(r['studies'][0]['outputs']),'handoff_inputs':[pin(configuration)],'claim_scope':'diagnostic'})
 write(path,r)


def test_all_existing_provider_families_expand_complete_inputs_without_execution(tmp_path):
 from ravel.physics import reinterpret_db,contur_import
 from ravel.setup import manifest as mf
 from fixtures_backend_portfolio_contur import contract as contur_contract
 from fixtures_backend_portfolio_provider import catalogue as cm_catalogue
 from fixtures_backend_portfolio_checkmate import contract as cm_contract
 path,r=portfolio_fixture(tmp_path);r['signal_basis']='bsm';r['studies'][0]['applicability']['model_bases']=['bsm']
 smdir=tmp_path/'sm';smdir.mkdir();model=r['model'];api=put(smdir/'api.py','# Inert installed-source capsule fixture\n');python=put(smdir/'python','NEVER EXECUTED')
 runtime=write(smdir/'runtime.json',{'smodels_version':'3.1.1','files':[api]})
 db=put(smdir/'db.pcl','NEVER UNPICKLED')
 sm={'schema_version':1,'source':'Synthetic SModelS metadata source control','model_input':{'file':model,'format':'slha'},'database':{'file':db,'version':'3.1.1','source_url':'https://example.org/synthetic.pcl','trusted_pickle':True},
 'runtime':{'python':python,'manifest':runtime,'smodels_version':'3.1.1'},'model':{'kind':'mssm','file':None},'settings':deepcopy(reinterpret_db.SETTINGS),'max_seconds':60,'max_ram_mib':512}
 smp=smdir/'input.json';write(smp,sm);add_offer(path,r,'smodels','smodels',smp,{'input':str(smp)},'model-portfolio',['bsm']);r['studies'][-1]['applicability']['routine_ids']=['all'];write(path,r)
 cdir=tmp_path/'contur';cdir.mkdir();cp,cdoc=contur_contract(cdir);add_offer(path,r,'contur','contur',cp,{'schema_version':1,'input':str(cp)},'contur-import',['bsm'])
 # The CheckMATE family is offered exactly where the tree declares its toolchain group and so its operation.
 families={'ma5','smodels','contur'};selected=['ma5-full','smodels','contur']
 assert ('checkmate-events' in science.MODES)==('checkmate' in mf.by_id(mf.load()[0]))
 if 'checkmate-events' in science.MODES:
  mdir=tmp_path/'cm';mdir.mkdir();cat=cm_catalogue.__wrapped__(mdir);cm=cm_contract.__wrapped__(mdir,cat);config=mdir/'config.json';add_offer(path,r,'checkmate','checkmate',config,cm['task'],'checkmate-events',['bsm']);r['studies'][-1]['applicability']['routine_ids']=[cm['request']['routine']];write(path,r)
  families.add('checkmate');selected.append('checkmate')
 result=portfolio.assess(path)
 assert {x['backend'] for x in result['studies']}==families
 assert all(x['applicable'] and x['complete_adapter_input_count']>0 for x in result['studies'])
 # An offer from a backend outside the released census has no rank and sorts after every ranked one.
 ranked={x['backend'] for x in result['backend_ranking']['ranking']}
 assert all((x['census_rank'] is None)==(x['backend'] not in ranked) and x['ranking_reasons'] for x in result['studies'])
 order=[x['census_rank'] is None for x in result['studies']]
 assert order==sorted(order)
 bundle=portfolio.prepare(path,selected,tmp_path/'all-handoffs')
 for branch in bundle['branches']:
  s=read_json(branch['study']['path']);files=science.task_inputs(s,Path(branch['study']['path']).parent)
  assert path in files and Path(model['path']) in files and Path(branch['handoff']['path']) in files
  assert s['review_policy']['policy']['actors']==policy()['policy']['actors']
 assert not any(Path(x['ordinary_rundir']).exists() for x in bundle['branches'])
 assert result['cross_backend_combination'] is None
 # The SModelS decomposed model must remain the exact original input even if
 # producer rehashes its separate model document and configured offer.
 other=put(smdir/'other.slha','BLOCK MASS\n  1001 101\n');sm['model_input']['file']=other;write(smp,sm)
 row=r['studies'][1];row['study']=write(Path(row['study']['path']),spec({'input':str(smp)},'model-portfolio',120));row['applicability']['source_basis']=[pin(smp)];row['handoff_inputs']=[pin(smp)];write(path,r)
 # Studies are listed in census-rank order; address the SModelS offer by id.
 assert not next(x for x in portfolio.assess(path)['studies'] if x['study_id']==row['id'])['applicable']


def test_coupled_original_artifacts_are_not_spliced_across_providers(tmp_path):
 path,r=portfolio_fixture(tmp_path);cp=Path(r['original_context']['path']);c=read_json(cp)
 c['requested_quantities'].append({'id':'other','artifact':'other','pointer':'','check':{'kind':'finite'},'meaning':'Distinct coupled partner'})
 c['compatibility_groups']=[{'id':'coupled','artifacts':['records','other'],'carryover':True,'basis':'Explicit matched current pair'}]
 r['original_context']=write(cp,c);write(path,r)
 result=portfolio.assess(path);assert not result['studies'][0]['applicable']
 assert 'Coupled' in result['studies'][0]['blockers'][0]


def test_alternative_accepted_results_remain_whole_and_are_not_combined(tmp_path,monkeypatch):
 path,rd=terminal_standin(tmp_path,monkeypatch,True);r=read_json(path);other=deepcopy(r['studies'][0]);other['id']='alternative';r['studies'].append(other);write(path,r)
 # Fresh bundle binds both aliases to this exact complete configured request.
 bundle=portfolio.prepare(path,['ma5-full','alternative'],tmp_path/'second-handoff')
 specs={x['study_id']:read_json(x['study']['path']) for x in bundle['branches']}
 second=tmp_path/'second-finished';shutil.copytree(rd,second)
 monkeypatch.setattr(science,'execution_spec',lambda root:specs['ma5-full' if root==rd else 'alternative'])
 result=portfolio.ingest(path,{'ma5-full':str(rd),'alternative':str(second)},tmp_path/'delivery')
 assert result['quantity_completion'] and len(result['context']['steps'])==1
 assert all(x['scientific_accepted'] and x['complete_native_result'] for x in result['studies'])
 assert any('Alternative' in x for x in result['studies'][1]['continuation_obligations'])
 assert result['cross_backend_combination'] is None


def test_failed_partial_result_remains_in_denominator_without_completion(tmp_path,monkeypatch):
 path,rd=terminal_standin(tmp_path,monkeypatch,False)
 monkeypatch.setattr(science,'packet',lambda _: {'execution':{'status':'failed'},'errors':[]})
 result=portfolio.ingest(path,{'ma5-full':str(rd)},tmp_path/'delivery')
 assert result['studies'][0]['state']=='failed' and result['studies'][0]['result_pins']
 assert not result['quantity_completion'] and result['context']['steps']==[]


def test_intake_refuses_writing_into_preserved_original_run(tmp_path,monkeypatch):
 path,rd=terminal_standin(tmp_path,monkeypatch,True)
 with pytest.raises(ValueError,match='preserve'):portfolio.ingest(path,{'ma5-full':str(rd)},rd/'new-intake')
 assert not (rd/'new-intake').exists()


def test_source_routine_selector_mismatch_blocks_despite_same_bytes(tmp_path):
 path,r=portfolio_fixture(tmp_path);r['studies'][0]['applicability']['routine_ids']=['different-analysis'];write(path,r)
 result=portfolio.assess(path);assert not result['studies'][0]['applicable']
 assert any('native source routine' in x for x in result['studies'][0]['blockers'])


def test_source_cutflow_only_single_region_and_no_histograms(tmp_path):
 source=put(tmp_path/'one.cc','bool Single::Initialize() { Manager()->AddRegionSelection("Only"); Manager()->AddCut("Cut"); return true; }')
 expected={'regions':['Only'],'cuts':{'Only':['Cut']},'histograms':[]}
 assert book.compile_source(Path(source['path']).read_text())==expected
 root=tmp_path/'view';texts={'Single.saf':framed('<RegionSelection>\n"Only"\n</RegionSelection>'),
 'Histograms/histos.saf':framed(''),'Cutflows/Only.saf':framed('<InitialCounter>\n"Initial"\n1 0\n1 0\n1 0\n</InitialCounter>\n<Counter>\n"Cut"\n1 0\n1 0\n1 0\n</Counter>')}
 for rel,text in texts.items():put(root/rel,text)
 booking=write(tmp_path/'book.json',{**expected,'source':source,'scope':'Complete synthetic source'})
 api=put(tmp_path/'api.h','synthetic');core=put(tmp_path/'core.cpp',CORE_SOURCE)
 doc={'schema_version':2,'analysis':'Single','source':source,'bookings':booking,'upstream':{'manager':api,'saf_writer':api,'core':core,'revision':'Synthetic'},
 'views':{'single':{'root':str(root),'files':{rel:pin(root/rel)['sha256'] for rel in texts},'expected_initial_entries':1,'population_description':'Synthetic'}},'population_scope':'Synthetic one-region cutflow, no booked plots'}
 task={'input':str(tmp_path/'input.json')};write(Path(task['input']),doc)
 assert saf.run(task,tmp_path,tmp_path/'output')['views']['single']['histograms']==[]


def configured_host_node(paths,action,selection_index,destination):
 node,request=host_request(paths)
 node['action']=action
 node['parameters'].update(selection_input=str(selection_index),output_dir=str(destination))
 request['node_sha256']=digest(node)
 return node,request


def test_real_host_handoff_keeps_exact_provider_and_original_task(tmp_path):
 path,r=portfolio_fixture(tmp_path)
 selection=tmp_path/'selected.json';write(selection,['ma5-full'])
 files=[path,*[Path(p['path']) for p in portfolio.input_pins(path) if Path(p['path'])!=path],selection]
 node,request=configured_host_node(files,'backend-handoff',len(files)-1,tmp_path/'host-handoff')
 ctl=Control();result=host.AgentHost(bound_roots=[tmp_path,Path(portfolio.__file__).parents[2]]).execute(node,request,ctl)['value']
 assert result['task_id']=='original' and ctl.calls==['backend-handoff']
 study=read_json(result['branches'][0]['study']['path'])
 assert science.task_inputs(study,tmp_path) and not Path(result['branches'][0]['ordinary_rundir']).exists()


def test_real_host_result_intake_requires_whole_terminal_graph_population(tmp_path,monkeypatch):
 path,rd=terminal_standin(tmp_path,monkeypatch,True)
 selection=tmp_path/'branches.json';write(selection,{'ma5-full':str(rd)})
 files=[path,*[Path(p['path']) for p in portfolio.delivery_pins(path,{'ma5-full':str(rd)}) if Path(p['path'])!=path],selection]
 node,request=configured_host_node(files,'backend-results',len(files)-1,tmp_path/'host-delivery')
 ctl=Control();result=host.AgentHost(bound_roots=[tmp_path,Path(portfolio.__file__).parents[2]]).execute(node,request,ctl)['value']
 assert result['quantity_completion'] and ctl.calls==['backend-results']
 row=result['studies'][0]
 assert row['study']['sha256'] and row['mode']=='ma5-saf' and row['energy_tev']==13
 assert {p['path'] for p in row['output_inventory']}=={str(p) for p in (rd/'outputs/attempt-1').rglob('*') if p.is_file()}
 # A result-only pin cannot replace the full terminal evidence population.
 files=[path,rd/'outputs/attempt-1/result.json',selection]
 node,request=configured_host_node(files,'backend-results',2,tmp_path/'incomplete-delivery')
 ctl=Control()
 with pytest.raises(host.HostFailure,match='unbound'):host.AgentHost().execute(node,request,ctl)
 assert not ctl.calls and not (tmp_path/'incomplete-delivery').exists()


def test_native_writer_roles_and_all_ordered_cleanname_rules():
 regions=['a/b->c>=d>e<=f<g h,i+j-k(l)', 'SR low', 'SR high']
 mapping=family.native_paths('Arbitrary',regions,CORE_SOURCE)
 assert mapping['analysis_file']=='Arbitrary.saf'
 assert mapping['cutflow_files'][regions[0]]=='Cutflows/a_slash_b_to_c_greater_than_or_equal_to_d_greater_than_e_smaller_than_or_equal_to_f_smaller_than_g_h_i_j_k_lp_l_rp_.saf'
 assert mapping['cutflow_files']['SR low']=='Cutflows/SR_low.saf'
 assert len(mapping['cleaning_rules'])==12
 assert list(mapping['cutflow_files'])==regions


@pytest.mark.parametrize('regions,source',[
 (['A B','A_B'],CORE_SOURCE),
 (['A'*252],CORE_SOURCE),
 (['A'],CORE_SOURCE.replace('pos = name.find(In);','pos += Out.size();')),
 (['A'],CORE_SOURCE.replace('analyzers_[i]->name()','"analysis"')),
 (['A'],CORE_SOURCE.replace('return tmp;','mutate(tmp); return tmp;')),
 (['A'],CORE_SOURCE.replace('ReplaceAll(tmp, " ",  "_");','ReplaceAll(tmp, " ",  " ");')),
 (['A\\B'],CORE_SOURCE),
])
def test_native_filename_collision_unsupported_algorithm_and_component_refuse(regions,source):
 with pytest.raises(ValueError):family.native_paths('Arbitrary',regions,source)


def test_general_requires_exact_core_pin_and_native_physical_layout(tmp_path):
 task,doc=family_fixture(tmp_path)
 result=saf.run(task,tmp_path,tmp_path/'delivered')
 assert result['native_file_mapping']['analysis_file']=='Arbitrary.saf'
 assert result['native_file_mapping']['cutflow_files']['SR low']=='Cutflows/SR_low.saf'
 assert result['views']['0']['regions']==EXPECTED['regions']
 doc['upstream'].pop('core');write(Path(task['input']),doc)
 with pytest.raises(ValueError):saf.inputs(task,tmp_path)


@pytest.mark.parametrize('fault',['literal-analysis','literal-region'])
def test_historical_filename_alias_cannot_replace_source_native_members(tmp_path,fault):
 task,doc=family_fixture(tmp_path);root=Path(doc['views']['0']['root'])
 old,new=('Arbitrary.saf','analysis.saf') if fault=='literal-analysis' else ('Cutflows/SR_low.saf','Cutflows/SR low.saf')
 (root/old).rename(root/new);doc['views']['0']['files'][new]=doc['views']['0']['files'].pop(old)
 write(Path(task['input']),doc)
 with pytest.raises(ValueError,match='membership'):saf.inputs(task,tmp_path)


@pytest.mark.parametrize('fault',['snapshot','held','inactive','scope'])
def test_ending_review_authority_refuses_late_change_and_retains_partial(tmp_path,monkeypatch,fault):
 path,rd=terminal_standin(tmp_path,monkeypatch,True);changed={'value':False};counts={'validate':0,'status':0}
 old=pad.InputCapture.finish
 def finish(c):
  if any(str(p).endswith('/outputs/attempt-1/result.json') for p in c.streams):changed['value']=True
  return old(c)
 def validate(s):
  counts['validate']+=1
  return ['new hold'] if changed['value'] and fault=='snapshot' else []
 def status(r):
  counts['status']+=1
  return {'state':'held' if changed['value'] and fault=='held' else 'accepted',
   'claim_scope':'other' if changed['value'] and fault=='scope' else 'diagnostic','live_errors':[]}
 monkeypatch.setattr(pad.InputCapture,'finish',finish)
 monkeypatch.setattr(portfolio.physics_review,'validate_snapshot',validate)
 monkeypatch.setattr(portfolio.physics_review,'status',status)
 monkeypatch.setattr(portfolio.physics_review,'active',lambda _:not(changed['value'] and fault=='inactive'))
 with pytest.raises(ValueError,match='ending scoped review'):portfolio.ingest(path,{'ma5-full':str(rd)},tmp_path/'delivery')
 assert counts['validate']>=2 and not (tmp_path/'delivery/backend-portfolio.json').exists()
 assert (tmp_path/'delivery/ma5-full-review.json').is_file()
 assert (tmp_path/'delivery/ma5-full-artifact-0.json').is_file()
