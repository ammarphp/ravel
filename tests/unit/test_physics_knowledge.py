"""Portable fabricated sources and supplied algebra; zero native/model/provider calls."""
from copy import deepcopy
from fractions import Fraction
import hashlib,json,math
from pathlib import Path
import pytest
from ravel.workflow import physics_knowledge as pk, scientific_context, agent_host, agent_graph
from ravel.workflow.execution import digest


def pin(p):
    p=p.resolve();raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}

def write(p,value):
    p.write_text(json.dumps(value,allow_nan=False)+'\n');return pin(p)

def fixture(base):
    # Resolve macOS temporary aliases before imposing the public no-symlink rule.
    base=base.resolve()
    original=base/'original.txt';original.write_text('Complete supplied scalar amplitude and ordered beams.\n')
    source=base/'source.txt';source.write_text('Final factorial is separate.\nCoherent amplitudes retain signed interference.\nInitial identical beam half is contested.\n')
    def ev(first):
        raw=source.read_bytes().splitlines(keepends=True)[first-1]
        return {'source':'doc','line_start':first,'line_end':first,'excerpt_sha256':hashlib.sha256(raw).hexdigest(),'locator':'Synthetic line'+str(first)}
    def n(i,statement,line,check=None,kind='fact',domain=None):
        return {'id':i,'kind':kind,'statement':statement,'tags':['toy'],'domain':domain or ['toy'],'conventions':['complete supplied amplitude'],'applicability':'Synthetic convention only.','equations':[], 'evidence':[ev(line)] if line else [],'obligations':[] if check is None else [{'id':'test.'+i,'description':'Discriminate the supplied convention.','resource_class':'pure_check','check':check}]}
    graph={'schema_version':1,'id':'toy-catalogue','sources':[{'id':'original','pin':pin(original),'citation':'https://example.invalid/primary','version':'synthetic original','format':'text','parents':[]},{'id':'doc','pin':pin(source),'citation':'https://example.invalid/derived','version':'synthetic derived','format':'text','parents':['original']}], 'nodes':[n('beam','Ordered beams have no blanket initial half.',1,'ordered-beam-prefactor'), n('contested','Source asserts an identical initial half.',3),n('interference','Coherent amplitudes retain signed cross terms.',2,'coherent-amplitude-square'),n('width','Constant complete amplitude on-shell width.',1,'two-body-width'),n('idea','Unproven relative phase hypothesis remains testable.',None,kind='hypothesis',domain=['other'])], 'edges':[{'id':'beam-conflict','kind':'contradicts','source':'beam','target':'contested','statement':'Two source assertions conflict.','assessment':'located_source_conflict'},{'id':'idea-requires','kind':'requires','source':'idea','target':'interference','statement':'Hypothesis requires a coherent construction.','assessment':'exploratory'}]}
    path=base/'knowledge.json';r={'schema_version':1,'knowledge':write(path,graph),'query':{'text':'bounded source question','tags':[],'roots':['beam'],'domain':['absent'],'max_nodes':5}}
    return r,graph,path

def all_packet(base):
    r,_,_=fixture(base);r['query'].update(roots=['beam','interference','width'],domain=['absent'])
    return pk.retrieve(r,base)


def test_conflict_and_complete_derived_parent_census(tmp_path):
    r,_,_=fixture(tmp_path);p=pk.retrieve(r,tmp_path)
    assert p['selection']['selected_ids']==['beam','contested']
    assert p['selection']['dependency_complete'] and len(p['selection']['omitted'])==3
    assert p['contradictions'][0]['id']=='beam-conflict'
    assert {Path(x['path']).name for x in pk.input_pins(r,tmp_path)}=={'knowledge.json','source.txt','original.txt'}
    assert len(p['premises'][0]['basis'])==2
    assert not any(p['claims'].values())


def test_empty_evidence_hypothesis_kept_with_dependency_and_domain(tmp_path):
    r,_,_=fixture(tmp_path);r['query']['roots']=['idea'];p=pk.retrieve(r,tmp_path)
    assert p['selection']['selected_ids']==['idea','interference']
    assert p['premises'][0]['basis']==[]
    assert p['nodes'][0]['kind']=='hypothesis' and p['nodes'][0]['applicability']
    assert p['test_obligations'][0]['check']=='coherent-amplitude-square'


def test_limit_refuses_incomplete_conflict_closure(tmp_path):
    r,_,_=fixture(tmp_path);r['query']['max_nodes']=1
    with pytest.raises(ValueError,match='cannot discard'):pk.retrieve(r,tmp_path)


@pytest.mark.parametrize('fault',['unknown-root','bool-limit','duplicate-root','unknown-key','nonfinite','unknown-parent','parent-cycle','bad-span','stale-excerpt','duplicate-node','missing-fact-evidence','executable-check','missing-edge','source-alias'])
def test_invalid_contract_refuses(tmp_path,fault):
    r,g,p=fixture(tmp_path)
    if fault=='unknown-root':r['query']['roots']=['absent']
    elif fault=='bool-limit':r['query']['max_nodes']=True
    elif fault=='duplicate-root':r['query']['roots']*=2
    elif fault=='unknown-key':r['query']['approve']=True
    elif fault=='nonfinite':r['query']['text']=math.nan
    elif fault=='unknown-parent':g['sources'][1]['parents']=['absent']
    elif fault=='parent-cycle':g['sources'][0]['parents']=['doc']
    elif fault=='bad-span':g['nodes'][0]['evidence'][0]['line_end']=999
    elif fault=='stale-excerpt':g['nodes'][0]['evidence'][0]['excerpt_sha256']='f'*64
    elif fault=='duplicate-node':g['nodes'].append(deepcopy(g['nodes'][0]))
    elif fault=='missing-fact-evidence':g['nodes'][0]['evidence']=[]
    elif fault=='executable-check':g['nodes'][0]['obligations'][0]['check']='eval-source-code'
    elif fault=='missing-edge':g['edges'][0]['target']='absent'
    elif fault=='source-alias':g['sources'][0]['pin']=g['sources'][1]['pin']
    r['knowledge']=write(p,g)
    with pytest.raises(ValueError):pk.retrieve(r,tmp_path)


@pytest.mark.parametrize('fault',['content','growth','replacement','symlink','duplicate-json'])
def test_exact_source_read_adversaries(tmp_path,fault):
    r,g,p=fixture(tmp_path);source=tmp_path/'source.txt'
    if fault=='content':source.write_text('Changed source\n')
    elif fault=='growth':source.write_bytes(source.read_bytes()+b'x'*200)
    elif fault=='replacement':
        newer=tmp_path/'new.txt';newer.write_text('Replacement bytes\n');newer.replace(source)
    elif fault=='symlink':
        real=tmp_path/'real.txt';source.rename(real);source.symlink_to(real)
    else:
        raw=p.read_text().replace('"schema_version": 1','"schema_version": 1, "schema_version": 1',1);p.write_text(raw);r['knowledge']=pin(p)
    with pytest.raises(ValueError):pk.retrieve(r,tmp_path)


def test_source_growth_during_descriptor_read_refuses(tmp_path,monkeypatch):
    r,_,_=fixture(tmp_path);source=(tmp_path/'source.txt').resolve();original=pk.os.fdopen
    class Read:
        def __init__(self,fd):self.f=original(fd,'rb')
        def __enter__(self):return self
        def __exit__(self,*a):self.f.close()
        def fileno(self):return self.f.fileno()
        def read(self,n):
            data=self.f.read(n)
            source.write_bytes(source.read_bytes()+b'mutated')
            return data
    # Isolate the actual bounded reader on this declared single source.
    monkeypatch.setattr(pk.os,'fdopen',lambda fd,mode:Read(fd))
    with pytest.raises(ValueError,match='changed during'):pk._snapshot(pin(source),tmp_path)


def test_coherent_complex_arithmetic_independent_fraction_reference(tmp_path):
    p=all_packet(tmp_path);inputs={'amplitudes':[{'real':1.,'imag':.5},{'real':-.5,'imag':.25}], 'basis':'same_external_helicity_colour','amplitude_mass_dimension':0}
    out=pk.check(p,'coherent-amplitude-square',inputs,tmp_path)['values']
    rr,ii=Fraction(1)-Fraction(1,2),Fraction(1,2)+Fraction(1,4)
    expected=rr*rr+ii*ii;diagonal=Fraction(1)+Fraction(1,4)+Fraction(1,4)+Fraction(1,16)
    assert out['coherent_square']==float(expected) and out['incoherent_square']==float(diagonal)
    assert out['interference']==float(expected-diagonal)<0
    inputs['amplitudes']=[{'real':1.,'imag':0.},{'real':-1.,'imag':0.}]
    assert pk.check(p,'coherent-amplitude-square',inputs,tmp_path)['values']['coherent_square']==0


def test_initial_species_does_not_change_flux_but_final_symmetry_does(tmp_path):
    p=all_packet(tmp_path);i={'observable':'ordered_two_beam_cross_section','initial_spin_degeneracies':[2,2],'initial_identical':False,'final_multiplicities':[1,1]}
    a=pk.check(p,'ordered-beam-prefactor',i,tmp_path)['values'];i['initial_identical']=True
    b=pk.check(p,'ordered-beam-prefactor',i,tmp_path)['values'];assert a==b and a['combined']==.25
    i['final_multiplicities']=[2];c=pk.check(p,'ordered-beam-prefactor',i,tmp_path)['values'];assert c['combined']==.125


def width_inputs():return {'parent_mass':2.,'daughter_masses':[0.,0.],'spin_summed_amplitude_square':4.,'initial_spin_states':1,'identical_final':False,'unit':'GeV','basis':'complete_angle_independent_spin_sum_GeV2'}

def test_width_massless_symmetry_threshold_and_scaling(tmp_path):
    p=all_packet(tmp_path);i=width_inputs();a=pk.check(p,'two-body-width',i,tmp_path)['values']
    assert a['momentum']==1 and math.isclose(a['width'],1/(8*math.pi),rel_tol=1e-15)
    i['identical_final']=True;b=pk.check(p,'two-body-width',i,tmp_path)['values'];assert b['width']==a['width']/2
    i.update(parent_mass=4.,spin_summed_amplitude_square=16.);assert pk.check(p,'two-body-width',i,tmp_path)['values']['width']==a['width']
    i.update(parent_mass=2.,daughter_masses=[1.,1.]);assert pk.check(p,'two-body-width',i,tmp_path)['values']['width']==0
    i['parent_mass']=1.9
    with pytest.raises(ValueError,match='threshold'):pk.check(p,'two-body-width',i,tmp_path)


@pytest.mark.parametrize('field,value',[('unit','MeV'),('basis','unknown-angular-amplitude'),('initial_spin_states',True),('parent_mass',math.inf),('daughter_masses',[0,-1]),('spin_summed_amplitude_square',-1)])
def test_wrong_physics_convention_refuses(tmp_path,field,value):
    p=all_packet(tmp_path);i=width_inputs();i[field]=value
    with pytest.raises(ValueError):pk.check(p,'two-body-width',i,tmp_path)


def test_check_does_not_execute_unselected_or_changed_packet(tmp_path):
    r,_,_=fixture(tmp_path);p=pk.retrieve(r,tmp_path)
    with pytest.raises(ValueError,match='not selected'):pk.check(p,'two-body-width',width_inputs(),tmp_path)
    p['nodes'][0]['conventions']=['silently different']
    with pytest.raises(ValueError,match='packet changed'):pk.check(p,'ordered-beam-prefactor',{},tmp_path)


def test_sources_feed_actual_existing_context_without_new_graph(tmp_path):
    p=all_packet(tmp_path)
    source=tmp_path/'source.txt';request={'schema_version':1,'task_id':'knowledge-construction','task':'Construct a coherent supplied amplitude test.', 'source_capsules':[], 'api_documents':[{'id':'knowledge-source','pin':{k:pin(source)[k] for k in ('path','sha256')},'language':'text','role':'example','version':'Synthetic physics knowledge','dependencies':[]}], 'queries':[{'id':'coherent','symbol':'Coherent','mode':'occurrence','documents':['knowledge-source'],'required':True}], 'requested_quantities':[{'id':'signed-cross-term','artifact':'amplitude-check','pointer':'/values/interference','check':{'kind':'finite'},'meaning':'Supplied algebra, not an executed amplitude model.'}], 'compatibility_groups':[{'id':'same-amplitude','artifacts':['amplitude-check'],'carryover':False,'basis':'Current complete supplied amplitudes.'}], 'max_source_bytes':8000,'max_context_bytes':8000,'max_steps':2}
    result=scientific_context.compile_context(request,tmp_path)
    assert result['context_complete'] and 'signed interference' in result['context_entries'][0]['text']
    assert not result['execution_authorized']


class Control:
    def __init__(self):self.calls=[]
    def cancelled(self):return False
    def check_cancelled(self):pass
    def call(self,label,kind,request,function,output_tokens=0):self.calls.append(label);return function()


def host_fixture(tmp_path,role='proposer'):
    r,_,_=fixture(tmp_path);request=tmp_path/'request.json';write(request,r)
    pins=[{'id':'request','path':str(request.resolve()),'sha256':pin(request)['sha256']}]+[{'id':'source'+str(j),'path':x['path'],'sha256':x['sha256']} for j,x in enumerate(pk.input_pins(r,tmp_path))]
    n={'id':'retrieve','kind':'tool','role':role,'depends_on':[],'inputs':pins,'packet':None,'action':'physics-knowledge','parameters':{'request_input':'request'},'max_attempts':1}
    req={'schema_version':1,'graph_id':'knowledge','graph_revision':'a'*64,'node_id':'retrieve','generation':1,'node_sha256':digest(n),'request_id':'b'*64,'input_artifacts':deepcopy(pins),'packet':None,'dependencies':[]}
    return n,req


def test_positive_host_retrieval_and_missing_derivation_parent(tmp_path):
    n,r=host_fixture(tmp_path);ctl=Control();result=agent_host.AgentHost().execute(n,r,ctl)
    assert result['value']['contradictions'] and ctl.calls==['physics-knowledge']
    # Remove original parent, while keeping graph and extracted doc pinned.
    n['inputs']=[x for x in n['inputs'] if not x['path'].endswith('original.txt')];r['input_artifacts']=deepcopy(n['inputs']);ctl=Control()
    with pytest.raises(agent_host.HostFailure,match='unbound'):agent_host.AgentHost().execute(n,r,ctl)
    assert ctl.calls==[]


@pytest.mark.parametrize('role',['critic','verifier'])
def test_no_blinding_from_source_retrieval(tmp_path,role):
    n,r=host_fixture(tmp_path,role)
    with pytest.raises(agent_host.HostFailure):agent_host.AgentHost().execute(n,r,Control())


def test_actual_existing_graph_retrieval_reuse_and_kernel_identity(tmp_path,monkeypatch):
    n,_=host_fixture(tmp_path);spec={'schema_version':1,'graph_id':'knowledge','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]}
    root=tmp_path/'graph';agent_graph.create(root,spec);adapter=agent_host.AgentHost()
    out=agent_graph.execute(root,adapter,workers=1);assert out['complete'] and out['usage']['calls']==1
    assert agent_graph.execute(root,adapter,workers=1)['usage']['calls']==1
    replacement=tmp_path/'other-kernel.py';replacement.write_bytes(Path(pk.__file__).read_bytes()+b'\n# identity change\n');monkeypatch.setattr(pk,'__file__',str(replacement))
    retained=agent_graph.status(root)
    with pytest.raises(agent_graph.GraphError,match='^completed generation source/request/host differs; explicit rework required$'):agent_graph.execute(root,adapter,workers=1)
    # The refusal precedes any reservation: no call is charged and the completed generation is untouched.
    assert agent_graph.status(root)==retained and retained['usage']['calls']==1


def test_nonrepresentable_coherent_results_and_legitimate_exact_zero(tmp_path):
    p=all_packet(tmp_path)
    i={'amplitudes':[{'real':math.ulp(0.),'imag':0.}], 'basis':'same_external_helicity_colour','amplitude_mass_dimension':0}
    with pytest.raises(ValueError,match='representable'):pk.check(p,'coherent-amplitude-square',i,tmp_path)
    i['amplitudes']=[{'real':1e308,'imag':0.}]
    with pytest.raises(ValueError):pk.check(p,'coherent-amplitude-square',i,tmp_path)
    i['amplitudes']=[{'real':0.,'imag':0.}]
    assert pk.check(p,'coherent-amplitude-square',i,tmp_path)['values']['coherent_square']==0


def test_gas_pair_counting_requires_a_distinct_observable(tmp_path):
    p=all_packet(tmp_path)
    i={'observable':'unordered_collision_pairs_in_gas','initial_spin_degeneracies':[1,1],'initial_identical':True,'final_multiplicities':[1,1]}
    with pytest.raises(ValueError,match='different quantity'):pk.check(p,'ordered-beam-prefactor',i,tmp_path)


def test_entirely_exploratory_graph_needs_no_prior_source_proof(tmp_path):
    r,g,path=fixture(tmp_path)
    g['sources']=[];g['nodes']=[g['nodes'][-1]];g['edges']=[]
    r['knowledge']=write(path,g);r['query']['roots']=['idea']
    p=pk.retrieve(r,tmp_path)
    assert p['premises']==[{'id':'idea','statement':'Unproven relative phase hypothesis remains testable.','basis':[]}]
    assert not p['claims']['physics_verified']


@pytest.mark.parametrize('invalid',[None,False,0,[],{},'unknown-check'])
def test_only_explicit_named_check_may_execute(tmp_path,invalid):
    r,g,path=fixture(tmp_path)
    g['nodes'][0]['obligations'][0]['check']=None
    r['knowledge']=write(path,g)
    packet=pk.retrieve(r,tmp_path)
    assert packet['test_obligations'][0]['check'] is None
    with pytest.raises(ValueError,match='explicit supported named'):
        pk.check(packet,invalid,width_inputs(),tmp_path)


def test_null_pending_obligation_does_not_select_width(tmp_path):
    r,g,path=fixture(tmp_path)
    g['nodes'][0]['obligations'][0]['check']=None
    r['knowledge']=write(path,g)
    packet=pk.retrieve(r,tmp_path)
    assert packet['nodes'][0]['obligations'][0]['check'] is None
    with pytest.raises(ValueError,match='not selected'):
        pk.check(packet,'two-body-width',width_inputs(),tmp_path)
