"""Synthetic source-custody fixtures; no ROOT or detector calibration claim."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics.source_calibration import recipes as r, provider as p
from ravel.workflow import agent_graph as g
from ravel.workflow.agent_host import AgentHost


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, obj):
    path.write_text(json.dumps(obj, allow_nan=False))
    return pin(path)


def case(tmp, monkeypatch, *, component='Reco', wp=''):
    inputs = tmp/'inputs'; inputs.mkdir()
    sources = {}
    for role in r.SOURCE_HASHES:
        path = inputs/(role+'.cxx')
        path.write_text('SYNTHETIC source token '+role+'; not upstream code\n')
        sources[role] = pin(path)
    monkeypatch.setattr(r, 'SOURCE_HASHES', {key: value['sha256'] for key, value in sources.items()})
    monkeypatch.setattr(p, 'EMPTY_WP_CONFIGURATION_SHA256', sources['tool_configuration']['sha256'])
    root = inputs/(component+'_TrueHadTau_synthetic.root')
    root.write_bytes(b'SYNTHETIC original-container custody token, not ROOT')
    names = ['sf'+('_'+wp if wp else '')+'_'+str(n)+'p' for n in (1,3)]
    objs, aliases = [], {}
    for n, name in zip((1,3), names):
        objs.append({'key': name+';1', 'name': name, 'class': 'TH2F',
            'edges': [[20,25,1000],[-2,0,2]], 'values_without_flow': [[1,1.1],[1.2,1.3]]})
        for direction, value in [('up', .1), ('down', .2)]:
            alias = 'STAT_'+direction+('_'+wp if wp else '')+'_'+str(n)+'p'
            objs.append({'key':alias+';1','name':alias,'class':'TH2F',
                'edges':[[20,25,1000],[-2,0,2]],'values_without_flow':[[value,value],[value,value]]})
    for obj in objs:
        aliases[obj['name']] = {'key':obj['key'],'class':obj['class'],'numeric_supported':True}
    payload = {**pin(root), 'literal_coordinates': {'x':'final_pt','y':'final_eta','x_metadata':None,'y_metadata':None},
               'objects':objs,'source_efficiency_aliases':aliases}
    decoded = inputs/'decoded.json'; dp = save(decoded, {'payloads':[payload]})
    catalog = inputs/'keys.json'
    records = [{'name':obj['name'],'cycle':1,'class':obj['class']} for obj in objs]
    kp = save(catalog, {'payloads':[{**pin(root),'bytes':root.stat().st_size,'records':records}]})
    population = inputs/'population.json'
    pp = save(population, {'status':'synthetic software fixture; no measured population',
        'channels':['QCR1','QCR2','SR1','SR2','WCR'],'eras':['early','late'],
        'required_components':['ID','trigger','isolation','OR','mT2','top veto'],
        'missing_joint_calibration':True})
    spec = {'schema_version':1,'kind':'athena-marginal-calibration-recipes','native_sources':sources,
        'decoded':dp,'root_key_census':kp,'scope':pp,
        'payloads':[{'root':pin(root),'population':pp,'domain':{
            'configuration_namespace':'synthetic configuration','simulation_namespace':'synthetic MC',
            'era_namespace':'synthetic era'}}]}
    request = inputs/'request.json'; save(request,spec)
    return request,spec,payload


def graph(request, output):
    deps=r.input_pins(request)
    return {'schema_version':1,'graph_id':'response_prepare',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':45,'max_reworks':0},
        'nodes':[{'id':'prepare','kind':'tool','role':'designer','depends_on':[],
            'inputs':[{'id':'request' if i==0 else 'input'+str(i),**pin} for i,pin in enumerate(deps)],
            'packet':None,'action':'response-recipes','parameters':{'request_input':'request','output_dir':str(output)},'max_attempts':1}]}


def receipt(result):
    path=Path(result['receipt']['path'])
    assert pin(path)==result['receipt']
    return json.loads(path.read_bytes())


def test_real_graph_prepares_then_existing_provider_uses_native_empty_wp(tmp_path,monkeypatch):
    req,_,_=case(tmp_path,monkeypatch)
    spec=graph(req,tmp_path/'prepared');root=tmp_path/'graph';g.create(root,spec)
    assert g.execute(root,AgentHost(api_key='unused'),workers=1)['complete']
    _,state=g._load(root);result=g._result(root,state['nodes']['prepare']['result'])['result']
    assert result['execution_authorized'] is False and result['physics_validated'] is False
    doc=receipt(result['value']);assert doc['binding_count']==1
    assert doc['population_transform'].startswith('none;') and doc['analysis_approval'] is False
    bp=doc['outputs'][0];binding=json.loads(Path(bp['path']).read_bytes())
    provider=p.CalibrationProvider.load(decoded=p.ArtifactPin(**doc['decoded']),
        original_root=p.ArtifactPin(**doc['primary_census'][0]['root']),binding=p.ArtifactPin(**bp))
    domain=p.SourceDomain(**binding['domain']);event={'truth_category':'had_tau','prongs':3,'pt_final_calib_gev':25,'eta_final_calib':.7}
    assert provider.evaluate(event,context=domain)['value']==1.3
    name='TAUS_TRUEHADTAU_EFF_RECO_STAT'
    assert provider.evaluate(event,context=domain,nuisance=name,direction=-1)['value']==pytest.approx(1.04)
    assert g.status(root)['usage']['calls']==1


@pytest.mark.parametrize('component,wp,tool',[('Reco','','RecoHadTauTool'),('EleOLR','','EleOLRHadTauTool'),
    ('JetID','jetbdtsigmedium',None),('Trigger','all_medium',None)])
def test_native_modes_are_separate_sf_recipes(tmp_path,monkeypatch,component,wp,tool):
    req,_,_=case(tmp_path,monkeypatch,component=component,wp=wp)
    doc=receipt(r.prepare(req,tmp_path/'prepared'))
    binding=json.loads(Path(doc['outputs'][0]['path']).read_bytes())
    assert binding['correction']['quantity']=='marginal_data_over_mc_sf'
    assert binding['domain'].get('empty_wp_tool')==tool
    row=doc['primary_census'][0]['recipes'][0]
    assert row['native_configuration']['working_point']==('medium' if component=='Trigger' else wp)
    assert row['native_configuration']['period_binning']==('all' if component=='Trigger' else None)
    if component=='EleOLR':assert binding['correction']['three_prong_unity'] is True


@pytest.mark.parametrize('kind',['quantity','bool_schema','missing_payload','missing_keys','changed_source',
    'root_drift','duplicate_cycle','omitted_alias_family','asymmetric_omission','wrong_alias','wrong_axis'])
def test_source_census_and_binding_adversaries_refuse_before_writes(tmp_path,monkeypatch,kind):
    req,spec,payload=case(tmp_path,monkeypatch)
    dp=Path(spec['decoded']['path']);kp=Path(spec['root_key_census']['path'])
    if kind=='quantity':spec['quantity']='absolute_detector_efficiency'
    elif kind=='bool_schema':spec['schema_version']=True
    elif kind=='missing_payload':spec['payloads']=[]
    elif kind=='missing_keys':
        keys=json.loads(kp.read_bytes());keys['payloads'][0]['records'].pop();spec['root_key_census']=save(kp,keys)
    elif kind=='changed_source':Path(spec['native_sources']['tool_configuration']['path']).write_text('different source')
    elif kind=='root_drift':Path(spec['payloads'][0]['root']['path']).write_bytes(b'changed root')
    elif kind=='duplicate_cycle':payload['objects'].append({**payload['objects'][0],'key':'sf_1p;2'})
    elif kind=='omitted_alias_family':payload['source_efficiency_aliases']={k:v for k,v in payload['source_efficiency_aliases'].items() if not k.startswith('STAT_')}
    elif kind=='asymmetric_omission':payload['source_efficiency_aliases'].pop('STAT_down_3p')
    elif kind=='wrong_alias':payload['source_efficiency_aliases']['STAT_up_1p']['key']='STAT_down_1p;1'
    elif kind=='wrong_axis':payload['literal_coordinates']['y']='final_abs_eta'
    if kind in ('duplicate_cycle','omitted_alias_family','asymmetric_omission','wrong_alias','wrong_axis'):
        spec['decoded']=save(dp,{'payloads':[payload]})
    save(req,spec)
    with pytest.raises(ValueError):r.prepare(req,tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


def test_empty_wp_requires_exact_released_config_even_for_valid_key_names(tmp_path,monkeypatch):
    req,_,_=case(tmp_path,monkeypatch)
    doc=receipt(r.prepare(req,tmp_path/'prepared'));bp=Path(doc['outputs'][0]['path']);original=json.loads(bp.read_bytes())
    for kind in ('missing','wrong_tool','source','filename'):
        binding=copy.deepcopy(original)
        if kind=='missing':binding.pop('native_configuration')
        elif kind=='wrong_tool':binding['native_configuration']['tool']='JetIDHadTauTool'
        elif kind=='source':binding['native_configuration']['source']['sha256']='0'*64
        else:binding['domain']['empty_wp_tool']='EleOLRHadTauTool';binding['native_configuration']['tool']='EleOLRHadTauTool'
        save(bp,binding)
        with pytest.raises(ValueError):p.CalibrationProvider.load(decoded=p.ArtifactPin(**doc['decoded']),
            original_root=p.ArtifactPin(**doc['primary_census'][0]['root']),binding=p.ArtifactPin(**pin(bp)))
    with pytest.raises(ValueError):p.SourceDomain(p.ATHENA_COMMIT,p.SHARED_FILES_VERSION,'c','s','e','')
    with pytest.raises(ValueError):p.SourceDomain(p.ATHENA_COMMIT,p.SHARED_FILES_VERSION,'c','s','e','medium','RecoHadTauTool')


def test_native_tes_is_retained_and_not_misreported_as_efficiency(tmp_path,monkeypatch):
    req,_,_=case(tmp_path,monkeypatch,component='TES')
    doc=receipt(r.prepare(req,tmp_path/'prepared'))
    assert doc['binding_count']==0 and len(doc['primary_census'])==1
    assert 'smearing' in doc['primary_census'][0]['unsupported'][0]['reason']


@pytest.mark.parametrize('kind',['payload','source','population'])
def test_ordinary_graph_requires_every_source_and_population_pin(tmp_path,monkeypatch,kind):
    req,spec,_=case(tmp_path,monkeypatch)
    graph_spec=graph(req,tmp_path/'output')
    excluded=(spec['decoded']['path'] if kind=='payload' else spec['native_sources']['helper_functions']['path'] if kind=='source' else spec['scope']['path'])
    graph_spec['nodes'][0]['inputs']=[x for x in graph_spec['nodes'][0]['inputs'] if x['path']!=excluded]
    root=tmp_path/'graph';g.create(root,graph_spec)
    assert not g.execute(root,AgentHost(api_key='unused'),workers=1)['complete']
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('target',['binding','receipt','source'])
def test_final_materialization_custody_refuses_late_changes(tmp_path,monkeypatch,target):
    req,spec,_=case(tmp_path,monkeypatch);original=r.atomic_json
    def change(path,value):
        original(path,value)
        if Path(path).name=='preparation.json':
            changed=Path(spec['native_sources']['helper_functions']['path']) if target=='source' else Path(path) if target=='receipt' else Path(value['outputs'][0]['path'])
            changed.write_bytes(changed.read_bytes()+b' ')
    monkeypatch.setattr(r,'atomic_json',change)
    with pytest.raises(ValueError):r.prepare(req,tmp_path/'late')
    assert (tmp_path/'late').exists()  # failed output remains evidence


def test_fresh_disjoint_destination_and_no_hidden_role_authority(tmp_path,monkeypatch):
    req,_,_=case(tmp_path,monkeypatch);before=set(req.parent.rglob('*'))
    for destination in (req.parent/'derived', tmp_path/'other/../inputs/derived'):
        with pytest.raises(ValueError):r.prepare(req,destination)
        assert set(req.parent.rglob('*'))==before
    gs=graph(req,tmp_path/'output');gs['nodes'][0]['role']='verifier'
    root=tmp_path/'graph';g.create(root,gs)
    assert not g.execute(root,AgentHost(api_key='unused'),workers=1)['complete']
