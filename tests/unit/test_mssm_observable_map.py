"""Synthetic complete MSSM maps; no spectrum, decay or generator execution."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import threading

import pytest
from ravel.physics import mssm_observable_map as m, mssm_llp_handoff as handoff, model_inputs, science_worker
from ravel.workflow import science, agent_host, agent_graph, execution, route_prompt, task_completion as tc





def emit(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=value if type(value) is bytes else (json.dumps(value,indent=2)+'\n').encode()
    path.write_bytes(raw)
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}


def term(block,codes,scale=None,factor='1'):
    return {'selector':{'block':block,'codes':codes,'scale':scale},'factor':factor}


def bind(*terms,origin='input'):
    return {'origin':origin,'terms':list(terms)}


def fixture(base,cp='real-signed',grid=True):
    base.mkdir(parents=True,exist_ok=True)
    evidence=emit(base/'provider-source.json',{'source':'Explicit inert synthetic solver/decay prescription. No numerical or physical qualification.'})
    provider=emit(base/'provider.json',{'schema_version':1,'name':'synthetic-SLHA-source','version':'fixture1','model':'MSSM',
          'spectrum_method':'inert literal complete pole/mixing fixture','decay_method':'inert supplied total widths and incomplete channels',
          'mass_scheme':'pole','mixing_prescription':'source_defined_no_loop_accuracy_claim','source_evidence':[evidence]})
    axes=[{'id':'mu','unit':'GeV','values':['200','250'] if grid else ['200'],'binding':bind(term('EXTPAR',[23]))},
          {'id':'M2','unit':'GeV','values':['100','150'] if grid else ['100'],'binding':bind(term('EXTPAR',[2]))}]
    d={'schema_version':1,'operation':'mssm_slha_observable_map','source':'Supplied ANA-0001 artificial spectrum population; no physics claim',
       'population':{'kind':'cartesian','source':None,'layout':None},'axes':axes,'fixed_parameters':[{'id':'M1_equals_M2','unit':'GeV','binding':bind(term('EXTPAR',[1]),term('EXTPAR',[2],factor='-1')),'value':'0'},
                                     {'id':'tanbeta','unit':'dimensionless','binding':bind(term('MINPAR',[3])),'value':'50'}],
       'conventions':{'basis':'SLHA-MSSM','cp':cp,'mixing_scale':None,'mixing_prescription':'source_defined_no_loop_accuracy_claim','orthogonality_absolute':'0'},
       'species':[{'id':'neutralino','pdg':1000022,'charge_e':'0'},{'id':'chargino','pdg':1000024,'charge_e':'1'},{'id':'heavy_chargino','pdg':1000037,'charge_e':'1'}],
       'components':[{'id':'charged','process':'explicit supplied chargino pair','decay_channels':'literal supplied integrated charged channels','species':['chargino']}],
       'energy_tev':'13','points':[]}
    for index,(mu,M2) in enumerate(__import__('itertools').product(*(a['values'] for a in axes))):
        original=f'BLOCK MODSEL\n 3 0\n 4 0\n 5 {0 if cp=="real-signed" else 2}\nBLOCK EXTPAR\n 1 {M2}\n 2 {M2}\n 23 {mu}\nBLOCK MINPAR\n 3 50\n'.encode()
        masses=[(1000022,100),(1000023,-150 if cp=='real-signed' else 150),(1000025,300),(1000035,-400 if cp=='real-signed' else 400),
                (1000024,150),(1000037,400),(211,.13957),(11,.000511),(12,0)]
        lines=['BLOCK MASS']+[f' {p} {mass}' for p,mass in masses]
        for block,n in [('NMIX',4),('UMIX',2),('VMIX',2)]:
            lines.append('BLOCK '+block)
            for i in range(1,n+1):
                for j in range(1,n+1):
                    value=int(i==j)
                    if block=='NMIX' and i<=2 and j<=2:value={(1,1):.6,(1,2):.8,(2,1):-.8,(2,2):.6}[i,j]
                    if cp=='complex-positive' and block=='NMIX' and i==1:value=0
                    if block=='UMIX' and i==j==1:value=-1
                    lines.append(f' {i} {j} {value}')
            if cp=='complex-positive' and block=='NMIX':
                lines.append('BLOCK IMNMIX')
                for i in range(1,5):
                    for j in range(1,5):lines.append(f' {i} {j} '+str({1:.6,2:.8}.get(j,0) if i==1 else 0))
        lines+=['DECAY 1000024 1e-14',' .25 2 1000022 211','DECAY 1000037 0','BLOCK SPINFO',' 1 Synthetic',' 2 fixture1',
                'BLOCK UNMAPPED Q= 1e3',' 9 literal_opaque_provider_value']
        raw=('\n'.join(lines)+'\n').encode();spec=emit(base/f'p{index}.slha',raw)
        manifest=emit(base/f'p{index}-completeness.json',model_inputs.make_manifest(raw))
        d['points'].append({'id':'p'+str(index),'coordinate':[mu,M2],'spectrum':spec,
             'input_card':emit(base/f'p{index}-input.slha',original),'decay_manifest':manifest,'provider':provider,'origin':{'kind':'supplied_unqualified'}})
    task={'request':emit(base/'request.json',d)['path']}
    return task,d


def save(task,d):emit(Path(task['request']),d)


def change_spectrum(task,d,fn):
    point=d['points'][0];p=Path(point['spectrum']['path']);raw=fn(p.read_bytes());point['spectrum']=emit(p,raw)
    point['decay_manifest']=emit(Path(point['decay_manifest']['path']),model_inputs.make_manifest(raw));save(task,d)


def spec(task):
    from svj_fixtures import policy
    pol=policy();pol['policy']['claim_scopes']={m.SCOPE:{'checks':['integrity','generator-population'],'actions':['delivery']}}
    return {'schema_version':2,'mode':'mssm-observable-map','source':'Synthetic schema/source map control','assumptions':['No solver or physics authority'],
          'max_seconds':30,'max_attempts':1,'approval_mode':'physicist','task':task,'review_policy':pol}


def test_complete_plane_signs_rows_units_and_total_width_lifetime(tmp_path):
    task,d=fixture(tmp_path);r=m.compile_map(task,tmp_path)
    assert r['population']=={'requested_points':4,'delivered_points':4}
    p=r['points'][0]
    assert [q['coordinate'] for q in r['points']]==[q['coordinate'] for q in d['points']]
    assert p['full_spectrum']['original_lines']==Path(d['points'][0]['spectrum']['path']).read_text().splitlines(keepends=True)
    assert p['mixings']['NMIX']['rows'][1]['entries'][0]['real_exact']=='-4/5'
    assert p['mixings']['NMIX']['rows'][0]['entries'][0]['absolute_squared_exact']=='9/25'
    assert next(x for x in p['full_mass_decay_inventory']['masses'] if x['pdg']==1000023)['mass_GeV_exact']=='-150/1'
    c=next(x for x in p['observables'] if x['id']=='chargino')
    assert Fraction(c['lifetime']['proper_ctau_mm_exact'])==model_inputs.HBARC_GEV_FM*model_inputs.FM_TO_MM/Fraction('1e-14')
    assert c['decay']['branching_fraction_sum_exact']=='1/4' and c['decay']['total_width_GeV_exact']=='1/100000000000000'
    assert c['decay']['channel_completeness']=='unresolved_completeness_unknown'
    assert p['observables'][0]['lifetime']['status']=='unknown_missing_total_width'
    assert p['observables'][2]['lifetime']['status']=='stable_by_card'
    assert p['source_transport_accepted'] is False and p['rates_derived_from_mixing_fractions'] is False
    assert r['original_task_complete'] is r['physics_validated'] is r['execution_authorized'] is False
    assert any(t['status']=='open_pole_threshold' for t in p['decay_threshold_diagnostics'])


def test_complex_positive_phase_and_declared_slha_zero_defaults(tmp_path):
    task,_=fixture(tmp_path,'complex-positive',False);r=m.compile_map(task,tmp_path)
    row=r['points'][0]['mixings']['NMIX']['rows'][0]['entries'][0]
    assert row['real_exact']=='0/1' and row['imag_exact']=='3/5' and row['absolute_squared_exact']=='9/25'
    assert r['points'][0]['mixings']['UMIX']['imaginary_source']=='SLHA2_declared_zero_default'


@pytest.mark.parametrize('mutation',[
    lambda d:d['points'].pop(),lambda d:d['points'].reverse(),
    lambda d:d['axes'][0]['values'].append('200'),lambda d:d['points'][0]['coordinate'].__setitem__(0,'201'),
    lambda d:d['fixed_parameters'][1].__setitem__('value','49'),lambda d:d['conventions'].__setitem__('basis','NMSSM'),
    lambda d:d['conventions'].__setitem__('mixing_prescription','different'),lambda d:d['points'][0].__setitem__('origin',{'kind':'accepted_cmssm_spectrum','run':'missing-run'}),
    lambda d:d['axes'][0]['values'].__setitem__(0,'1e99999999'),lambda d:d['conventions'].__setitem__('orthogonality_absolute','0.02')])
def test_complete_population_coordinates_conventions_and_unqualified_origin_refuse(tmp_path,mutation):
    task,d=fixture(tmp_path);mutation(d);save(task,d)
    with pytest.raises((ValueError,FileNotFoundError)):m.compile_map(task,tmp_path)


@pytest.mark.parametrize('before,after',[
    (b' 1 1 0.6',b' 1 1 0.5'),(b' 4 4 1\n',b''),
    (b'BLOCK UMIX',b' 1 1 0.6\nBLOCK UMIX'),(b'DECAY 1000024 1e-14',b'DECAY 1000024 -1e-14'),
    (b' .25 2 1000022 211',b' .25 3 1000022 211'),(b' 1000023 -150',b' 1000023 -500'),
    (b'BLOCK SPINFO',b'BLOCK SPINFO\n 4 NativeFailure'),(b'BLOCK UMIX',b'BLOCK NMIX\n 1 1 1\nBLOCK UMIX')])
def test_invalid_actual_source_population_and_native_failure_refuse(tmp_path,before,after):
    task,d=fixture(tmp_path,grid=False);change_spectrum(task,d,lambda raw:raw.replace(before,after))
    with pytest.raises(ValueError):m.compile_map(task,tmp_path)


def test_real_signed_chargino_is_preserved_with_its_phase_convention(tmp_path):
    task,d=fixture(tmp_path,grid=False);change_spectrum(task,d,lambda raw:raw.replace(b'1000024 150',b'1000024 -150'))
    c=m.compile_map(task,tmp_path)['points'][0]['observables'][1]
    assert c['signed_mass_GeV_exact']=='-150/1' and c['pole_mass_GeV_exact']=='150/1' and c['negative_mass_convention']


def test_missing_daughter_threshold_stays_unknown_and_zero_br_not_dropped(tmp_path):
    task,d=fixture(tmp_path,grid=False);change_spectrum(task,d,lambda raw:raw.replace(b' .25 2 1000022 211',b' .25 2 1000022 900\n 0 2 1000022 -211'))
    r=m.compile_map(task,tmp_path)['points'][0]
    assert [x['status'] for x in r['decay_threshold_diagnostics']]==['unknown_missing_daughter_or_parent_mass','open_pole_threshold']
    assert r['decay_threshold_diagnostics'][1]['zero_branching_ratio'] is True
    assert len(r['full_mass_decay_inventory']['decays'][0]['channels'])==2


def test_running_parameter_occurrence_scale_is_exact(tmp_path):
    task,d=fixture(tmp_path,grid=False);p=d['points'][0]
    original=Path(p['input_card']['path']).read_bytes().replace(b'BLOCK EXTPAR',b'BLOCK EXTPAR Q= 1000')
    p['input_card']=emit(Path(p['input_card']['path']),original)
    for a in d['axes']:
        for t in a['binding']['terms']:t['selector']['scale']='1000'
    for t in d['fixed_parameters'][0]['binding']['terms']:t['selector']['scale']='1000'
    save(task,d);assert m.compile_map(task,tmp_path)['population']['delivered_points']==1
    d['axes'][0]['binding']['terms'][0]['selector']['scale']='1e3';save(task,d)
    with pytest.raises(ValueError,match='source scalar'):m.compile_map(task,tmp_path)


@pytest.mark.parametrize('aba',[False,True])
def test_ending_input_and_restored_byte_drift_refuse(tmp_path,monkeypatch,aba):
    task,d=fixture(tmp_path,grid=False);p=Path(d['points'][0]['input_card']['path']);old=m._derive
    def changed(*args):
        r=old(*args);raw=p.read_bytes();p.write_bytes(raw+b'#drift\n')
        if aba:p.write_bytes(raw)
        return r
    monkeypatch.setattr(m,'_derive',changed)
    with pytest.raises(ValueError):m.compile_map(task,tmp_path)


def test_complete_public_science_mode_and_finite_worker_boundary(tmp_path):
    task,_=fixture(tmp_path,grid=False);s=spec(task)
    science.validate(s);assert science.adapter(s) is m
    assert set(science.task_inputs(s,tmp_path))>=set(m.inputs(task,tmp_path))
    result=m.run(task,tmp_path,tmp_path/'output');assert m.verify_result(task,tmp_path,result)
    assert science_worker.diagnostic_presentation(s['mode'],result)[0]['status_scope']==m.SCOPE
    result['physics_validated']=True
    with pytest.raises(ValueError):science_worker.diagnostic_presentation(s['mode'],result)
    s['review_policy']['policy']['max_redos']=1
    with pytest.raises(ValueError):science.validate(s)


class Control:
    def __init__(self):self.calls=[];self.cancel=threading.Event()
    def cancelled(self):return False
    def call(self,label,kind,request,fn,output_tokens=0):self.calls.append((label,kind));return fn()


def graph_node(base):
    task,_=fixture(base,grid=False)
    pins=[{'id':str(i),'path':str(p),'sha256':execution.file_hash(p)} for i,p in enumerate(m.inputs(task,base))]
    identity=next(p['id'] for p in pins if p['path']==task['request'])
    return {'id':'mssm','kind':'tool','role':'designer','depends_on':[],'inputs':pins,'packet':None,
            'action':'mssm-spectrum-context','parameters':{'request_input':identity},'max_attempts':1}


def test_real_graph_host_context_charge_reuse_and_source_identity(tmp_path):
    node=graph_node(tmp_path/'inputs');graph={'schema_version':1,'graph_id':'physical-mssm-context','nodes':[node],
       'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':20,'max_reworks':0}}
    root=tmp_path/'graph';agent_graph.create(root,graph);host=agent_host.AgentHost()
    state=agent_graph.execute(root,host,workers=1)
    assert state['complete'] and state['usage']['calls']==1 and state['execution_authorized'] is False
    assert agent_graph.execute(root,host,workers=1)['usage']['calls']==1
    assert host.identity['sources'][m.__name__]==execution.file_hash(m.__file__)


def test_host_refuses_missing_source_pin_or_blind_caller(tmp_path):
    node=graph_node(tmp_path/'inputs');request={'schema_version':1,'graph_id':'g','graph_revision':'a'*64,'node_id':node['id'],'generation':1,
       'node_sha256':execution.digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(node['inputs']),'packet':None,'dependencies':[]}
    request['input_artifacts'].pop()
    with pytest.raises(agent_host.HostFailure):agent_host.AgentHost().execute(node,request,Control())
    request['input_artifacts']=deepcopy(node['inputs']);node['role']='critic'
    with pytest.raises(agent_host.HostFailure):agent_host.AgentHost().execute(node,request,Control())


def llp_template(base,d):
    from svj_fixtures import policy
    support=emit(base/'support.json',{'source':'Synthetic full parent analysis/rate law; no calibration'})
    support['size']=Path(support['path']).stat().st_size
    prompt='Project the original complete MSSM mu-M2 plane at M1=M2 and tanbeta50 to 400 fb^-1 with complete charged LLP response.'
    parent=route_prompt.route(prompt);requirements=tc.initial_requirements(prompt)
    requirements['assignments']=[{'id':'plane','purpose':'Original complete physical plane','coverage':[{'obligation_id':'original-request','criteria':{'request':prompt}}]}]
    parent['task_requirements']=requirements;goal={'contract':emit(base/'parent.json',parent),'assignment_id':'plane'}
    goal['contract']['size']=Path(goal['contract']['path']).stat().st_size
    q={'schema_version':1,'source':'Synthetic original whole-plane template','goal_binding':goal,
       'analysis':{'id':'charged-synthetic','energy_tev':13.,'lumi_fb':139.,'bins':[{'id':'s0','channel':'SR','sample':'signal','index':0,'role':'SR'}],
                   'unresolved_bins':[],'sources':[support],'transport':'charged_source_required'},
       'axes':[{k:a[k] for k in ('id','unit')}|{'values':[float(x) for x in a['values']]} for a in d['axes']],
       'points':[{'id':p['id'],'coordinate':[float(x) for x in p['coordinate']],'identity':None,
         'components':[{'id':'charged','rate':{'sigma_pb':.001,'branching_fraction':.25,'source':support},'cohort':None,'response':None,'generation':None}],
         'lifetimes':[{'id':'spectrum_total_width','ctau_mm':None}]} for p in d['points']],
       'projection_scenarios':[{'id':'run3','energy_tev':13.,'lumi_fb':400.,'background_scaling':'stat','signal_MC':'reuse_exact_cohort','sources':[support]}],
       'cells':[{'point_id':p['id'],'lifetime_id':'spectrum_total_width','projection_id':'run3','published_model':None,'template':None,'mc_interpretation':'unqualified'} for p in d['points']],
       'mixture_sampling':{'kind':'independent_component_experiments','source':support},'generation_policy':emit(base/'generation-policy.json',policy()),
       'inference_policy':emit(base/'inference-policy.json',policy()),'child_seconds':{'generation':60,'inference':60},
       'assumptions':['Complete synthetic engineering controls; no charged response calibration or inferred production law.']}
    return emit(base/'llp-template.json',q),q


def test_connected_existing_llp_recipe_keeps_parent_rates_and_full_projection(tmp_path):
    from ravel.physics import llp_plane_recipe
    task,d=fixture(tmp_path/'source');template,q=llp_template(tmp_path/'source',d)
    r=handoff.prepare(task,tmp_path/'source',template['path'],tmp_path/'handoff')
    actual=json.loads(Path(r['recipe']['path']).read_bytes())
    assert r['status']=='prepared' and r['prepared_points']==4 and r['goal_binding']==q['goal_binding']
    assert actual['projection_scenarios']==q['projection_scenarios'] and actual['cells']==q['cells']
    assert [p['components'] for p in actual['points']]==[p['components'] for p in q['points']]
    result=llp_plane_recipe.run(r['ordinary_task'],tmp_path/'handoff',tmp_path/'llp-result')
    assert result['blocked_cells']==4 and result['generated_events']==result['fits']==0 and result['original_task_complete'] is False
    assert r['execution_authorized'] is False and r['production_and_response_supplied_unchanged'] is True


@pytest.mark.parametrize('change',['missing-width','stable-width','partial-plane','wrong-energy','existing-identity'])
def test_llp_missing_physics_never_invented_and_template_never_narrowed(tmp_path,change):
    task,d=fixture(tmp_path/'source',grid=False);template,q=llp_template(tmp_path/'source',d)
    if change in ('missing-width','stable-width'):
        change_spectrum(task,d,lambda raw:raw.replace(b'DECAY 1000024 1e-14\n .25 2 1000022 211\n', b'' if change=='missing-width' else b'DECAY 1000024 0\n'))
        r=handoff.prepare(task,tmp_path/'source',template['path'],tmp_path/'handoff')
        assert r['status']=='blocked' and not (tmp_path/'handoff').exists()
        return
    if change=='partial-plane':q['points']=[]
    if change=='wrong-energy':q['analysis']['energy_tev']=14
    if change=='existing-identity':q['points'][0]['identity']={'path':'already supplied'}
    emit(Path(template['path']),q)
    with pytest.raises(ValueError):handoff.prepare(task,tmp_path/'source',template['path'],tmp_path/'handoff')


@pytest.mark.parametrize('aba',[False,True])
def test_generated_handoff_ending_commitment_refuses_late_copy(tmp_path,monkeypatch,aba):
    task,d=fixture(tmp_path/'source',grid=False);template,_=llp_template(tmp_path/'source',d)
    from ravel.physics import llp_plane_recipe
    original=llp_plane_recipe.inputs;calls=[]
    def changed(*args):
        dependencies=original(*args);calls.append(1)
        if len(calls)==1:
            p=tmp_path/'handoff/p0-identity.json';raw=p.read_bytes();p.write_bytes(raw+b' ')
            if aba:p.write_bytes(raw)
        return dependencies
    monkeypatch.setattr(llp_plane_recipe,'inputs',changed)
    with pytest.raises(ValueError):handoff.prepare(task,tmp_path/'source',template['path'],tmp_path/'handoff')
    assert (tmp_path/'handoff/HANDOFF-FAILED.txt').is_file()


def large_plane(base):
    task,d=fixture(base,grid=False);initial=deepcopy(d['points'][0]);d['points']=[]
    d['axes'][0]['values']=['83','127','211','359','463']; d['axes'][1]['values']=['73','137','281']
    template=Path(initial['input_card']['path']).read_bytes()
    for i,(mu,M2) in enumerate(__import__('itertools').product(*(a['values'] for a in d['axes']))):
        p=deepcopy(initial);p['id']='p'+str(i);p['coordinate']=[mu,M2]
        raw=template.replace(b' 1 100\n',(' 1 '+M2+'\n').encode()).replace(b' 2 100\n',(' 2 '+M2+'\n').encode()).replace(b' 23 200\n',(' 23 '+mu+'\n').encode())
        p['input_card']=emit(base/('input'+str(i)+'.slha'),raw);d['points'].append(p)
    save(task,d);return task,d


def test_large_supplied_plane_handoff_and_construction_budget(tmp_path):
    from ravel.physics import llp_plane_recipe
    task,d=large_plane(tmp_path/'source');template,q=llp_template(tmp_path/'source',d)
    q['construction_limits']={'max_points':128,'max_cells':512};emit(Path(template['path']),q)
    r=handoff.prepare(task,tmp_path/'source',template['path'],tmp_path/'handoff')
    assert r['prepared_points']==15
    actual=json.loads(Path(r['recipe']['path']).read_bytes())
    assert len(actual['points'])==15 and len(actual['cells'])==15
    assert actual['child_seconds']==q['child_seconds'] and actual['goal_binding']==q['goal_binding']
    # Real source-construction adapter, no event generation or inference.
    result=llp_plane_recipe.run(r['ordinary_task'],tmp_path/'handoff',tmp_path/'llp-result')
    assert result['blocked_cells']==15 and result['generated_events']==result['fits']==0
    assert result['original_task_complete'] is False


@pytest.mark.parametrize('attack',['missing','duplicate','nonCartesian','resource','cells'])
def test_supplied_plane_population_and_construction_limits_are_not_relaxed(tmp_path,attack):
    task,d=large_plane(tmp_path/'source');template,q=llp_template(tmp_path/'source',d)
    q['construction_limits']={'max_points':128,'max_cells':512}
    if attack=='resource':q['construction_limits']['max_points']=14
    elif attack=='cells':q['construction_limits']['max_cells']=14
    elif attack=='missing':d['points'].pop()
    elif attack=='duplicate':d['points'][-1]=deepcopy(d['points'][0])
    else:d['points'][1]['coordinate']=['125','100']
    save(task,d);emit(Path(template['path']),q)
    with pytest.raises(ValueError):handoff.prepare(task,tmp_path/'source',template['path'],tmp_path/'handoff')


def test_explicit_nonCartesian_population_is_complete_and_pinned(tmp_path):
    task,d=fixture(tmp_path);d['points'].pop(1)
    source={'schema_version':1,'points':[{k:p[k] for k in ('id','coordinate')} for p in d['points']]}
    d['population']={'kind':'source-listed','source':emit(tmp_path/'population.json',source),'layout':'point-list-v1'}
    save(task,d);assert m.compile_map(task,tmp_path)['population']['delivered_points']==3
    d['points'].pop();save(task,d)
    with pytest.raises(ValueError,match='entire ordered'):m.compile_map(task,tmp_path)



@pytest.mark.parametrize('header',['BLOCK QNUMBERS 1000022','BLOCK QNUMBERS -1000022'])
def test_qnumbers_particle_headers_are_opaque_and_preserved(header):
    raw=(header+'\n 1 0\n 2 2\n 3 1\n 4 0\n').encode();doc=m.slha.inventory(raw)
    assert doc['original_lines']==raw.decode().splitlines(keepends=True) and doc['sections'][0]['kind']=='opaque'
    assert doc['sections'][0]['pdg']==int(header.split()[-1])


@pytest.mark.parametrize('header',['BLOCK QNUMBERS 0','BLOCK QNUMBERS Auto','BLOCK QNUMBERS 1000022 Q= 1000'])
def test_unknown_or_malformed_particle_headers_still_refuse(header):
    with pytest.raises(ValueError):m.slha.inventory((header+'\n 1 0\n').encode())



@pytest.mark.parametrize('extra',[b'BLOCK NMSSMRUN Q= 1000\n 1 .1\n',b'BLOCK MASS\n 1000045 500\n'])
def test_actual_nmssm_content_not_relabelled_by_a_provider_name(tmp_path,extra):
    task,d=fixture(tmp_path,grid=False);change_spectrum(task,d,lambda raw:raw+extra)
    with pytest.raises(ValueError):m.compile_map(task,tmp_path)


def test_context_only_cli_alias_and_real_parser_remain_callable(tmp_path,capsys):
    from ravel import cli
    task,_=fixture(tmp_path,grid=False)
    assert cli.main(['mssm-physical-map','--request',task['request']])==0
    shown=json.loads(capsys.readouterr().out)
    assert shown['mode']=='mssm-observable-map' and shown['execution_authorized'] is False


@pytest.mark.parametrize('attack',['declared-charge','quantum-charge','duplicate-quantum-definition'])
def test_physical_signed_charge_cannot_switch_transport_family(tmp_path,attack):
    task,d=fixture(tmp_path,grid=False)
    if attack=='declared-charge':d['species'][1]['charge_e']='0';save(task,d)
    else:
        extra=b'BLOCK QNUMBERS 1000024\n 1 '+(b'0' if attack=='quantum-charge' else b'3')+b'\n 2 2\n 3 1\n 4 1\n'
        change_spectrum(task,d,lambda raw:raw+extra*(2 if attack=='duplicate-quantum-definition' else 1))
    with pytest.raises(ValueError):m.compile_map(task,tmp_path)


@pytest.mark.parametrize('attack',[None,'NMSSM','wrong-input','changed-result','different-scope'])
def test_accepted_source_join_uses_existing_review_and_actual_cmssm_return(tmp_path,monkeypatch,attack):
    """Inert review/config return stand-ins; real adapter binding checks execute."""
    from ravel.physics import generated_spectrum
    task,d=fixture(tmp_path/'inputs',grid=False);p=d['points'][0]
    rd=tmp_path/'run';out=rd/'outputs/attempt-1';out.mkdir(parents=True)
    p['spectrum']=emit(out/'CMSSM.slha',Path(p['spectrum']['path']).read_bytes())
    p['origin']={'kind':'accepted_cmssm_spectrum','run':str(rd)}
    result={'status':'passed','generated_slha':{'path':p['spectrum']['path'],'sha256':p['spectrum']['sha256']},'solver_input_sha256':p['input_card']['sha256']}
    if attack=='wrong-input':result['solver_input_sha256']='a'*64
    if attack=='changed-result':result['status']='failed'
    emit(out/'generated-spectrum.json',result)
    def accepted(run,scope,session):
        assert run==str(rd) and scope==m.slha.SCOPE
        if attack=='different-scope':raise ValueError('actual ordinary requested scope not accepted')
        return rd,{'explicit_inert_review_standin':True}
    monkeypatch.setattr(tc,'_accepted_review',accepted)
    monkeypatch.setattr(science,'execution_spec',lambda root:{'mode':'generated-spectrum','task':{'config':'inert'}})
    monkeypatch.setattr(generated_spectrum,'_load',lambda task,root:(tmp_path/'inert-config.json',{'schema_version':2 if attack=='NMSSM' else 1}))
    monkeypatch.setattr(execution,'load_execution',lambda root:{'stages':{'science':{'outputs':[str(out)]}}})
    if attack is None:
        assert m._origin(p,tmp_path/'inputs')
    else:
        with pytest.raises(ValueError):m._origin(p,tmp_path/'inputs')
