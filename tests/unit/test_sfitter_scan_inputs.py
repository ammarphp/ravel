import copy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import sfitter_scan_inputs as s, agent_graph as g
from ravel.workflow.agent_host import AgentHost, HostFailure
from test_sfitter_adapter import workflow_fixture, save, pin, BASIS


def setup(tmp,*,mixed=False):
    base=tmp/'inputs';base.mkdir()
    wf,docs,_=workflow_fixture(base)
    if mixed:
        wf['target']['eft'].update(quadratic=True,mixed_pairs=[[BASIS[0],BASIS[1]]])
    for phase in ('extraction','sm_template'):
        doc=copy.deepcopy(docs[phase]);doc['target_sha256']=g.digest(wf['target'])
        wf['handoffs'][phase]=save(base/(phase+'.json'),doc)
    wp=save(base/'workflow.json',wf)
    card=base/'restrict_default.dat'
    card.write_text('BLOCK MASS\n 25 125.0\nBLOCK DIM6 Q= 1D3\n'+
        ''.join(f' {i} {i}.0 # model parameter {name}\n' for i,name in enumerate(BASIS,1))+
        'BLOCK DIM64F\n 910 7.5 # default contamination outside selected basis\n')
    template=base/'launch.mg5';template.write_text('import model supplied-model\ngenerate p p > t t~\noutput declared-process\nlaunch declared-process\n'+s.MARKER+'\nset run_card nevents 100\n0\n')
    original=save(base/'model-map-source.json',{'source':'Explicit synthetic axis/code premise, no real UFO translation'})
    mapping={'schema_version':1,'model_source':wf['target']['model_source'],'eft':wf['target']['eft'],
        'operators':[{'axis':name,'block':'DIM6','code':i} for i,name in enumerate(BASIS,1)],'sources':[original]}
    mp=save(base/'mapping.json',mapping)
    request={'schema_version':1,'id':'supplied_scan','workflow':wp,'restriction_card':pin(card),
        'launch_template':pin(template),'operator_map':mp,
        'scans':[{'id':'sm','values':{}},{'id':'negative','values':{BASIS[0]:'-2.5D0'}},
                 {'id':'positive','values':{BASIS[0]:'2.5'}}]}
    if mixed:request['scans'].append({'id':'mixed','values':{BASIS[0]:'-2',BASIS[1]:'3'}})
    return base,request,save(base/'request.json',request)


def test_actual_full_model_census_then_activation_and_whole_materialized_population(tmp_path):
    base,request,rp=setup(tmp_path,mixed=True)
    original=Path(request['restriction_card']['path']).read_bytes()
    result=s.compile(request,base)
    assert len(result['dim6_census'])==23 and len(result['scans'])==4
    for row in result['scans']:
        commands=[line for line in row['script'].splitlines() if line.startswith('set param_card')]
        assert commands[:23]==result['zeroing_commands']
        assert commands[23:]==row['active_commands']
        assert 'set param_card dim64f 910 0.0' in commands
        assert hashlib.sha256(row['script'].encode()).hexdigest()==row['script_sha256']
    assert result['scans'][1]['active_commands']==['set param_card dim6 1 -2.5e0']
    assert result['scans'][-1]['active_commands']==['set param_card dim6 1 -2','set param_card dim6 2 3']
    output=s.materialize(rp,base,tmp_path/'generated')
    delivered=json.loads(Path(output['path']).read_bytes())
    assert delivered==result and set(p.name for p in (tmp_path/'generated').iterdir())=={'sm.mg5','negative.mg5','positive.mg5','mixed.mg5','scan-inputs.json'}
    assert Path(request['restriction_card']['path']).read_bytes()==original
    assert delivered['generated_coupling_cleanliness']=='unobserved' and not delivered['execution_authorized']


@pytest.mark.parametrize('kind',['duplicate_code','duplicate_block','empty_block','multidimensional','unbounded_exponent','unbounded_code'])
def test_actual_restriction_grammar_refuses_incomplete_or_ambiguous_census(kind):
    raw={'duplicate_code':'BLOCK DIM6\n1 0\n1 1\n','duplicate_block':'BLOCK DIM6\n1 0\nBLOCK DIM6\n2 0\n',
        'empty_block':'BLOCK DIM6\nBLOCK DIM64F\n1 0\n','multidimensional':'BLOCK DIM6\n1 2 0.0\n',
        'unbounded_exponent':'BLOCK DIM6\n1 1e999999999999999999\n','unbounded_code':'BLOCK DIM6\n99999999999999999 0\n'}[kind]
    with pytest.raises(ValueError):s.restriction_census(raw.encode())


@pytest.mark.parametrize('kind',['partial_map','wrong_scale','alias_map','stale_source','extra_dim6_set','shorthand_parameter_set','marker_before_launch','duplicate_marker','undeclared_pair','nan','command_injection','duplicate_scan'])
def test_source_coordinate_convention_and_template_adversaries_refuse(tmp_path,kind):
    base,request,_=setup(tmp_path)
    mp=Path(request['operator_map']['path']);mapping=json.loads(mp.read_bytes())
    template=Path(request['launch_template']['path'])
    if kind=='partial_map':mapping['operators'].pop()
    elif kind=='wrong_scale':mapping['eft']['renormalization_scale_gev']='2'
    elif kind=='alias_map':mapping['operators'][1]['code']=1
    elif kind=='stale_source':Path(mapping['sources'][0]['path']).write_text('mutated original mapping evidence')
    elif kind=='extra_dim6_set':template.write_text(template.read_text()+'set param_card dim64f 910 1.0\n')
    elif kind=='shorthand_parameter_set':template.write_text(template.read_text()+'set ctG 1.0\n')
    elif kind=='marker_before_launch':template.write_text(s.MARKER+'\nlaunch process\n')
    elif kind=='duplicate_marker':template.write_text(template.read_text()+s.MARKER+'\n')
    elif kind=='undeclared_pair':request['scans'][1]['values'][BASIS[1]]='2'
    elif kind=='nan':request['scans'][1]['values'][BASIS[0]]='NaN'
    elif kind=='command_injection':request['scans'][1]['values'][BASIS[0]]='1\nlaunch attacker'
    else:request['scans'][1]['id']='sm'
    if kind in ('partial_map','wrong_scale','alias_map'):request['operator_map']=save(mp,mapping)
    if kind in ('extra_dim6_set','shorthand_parameter_set','marker_before_launch','duplicate_marker'):request['launch_template']=pin(template)
    with pytest.raises(ValueError):s.compile(request,base)


def test_real_existing_graph_host_compiles_all_inputs_and_refuses_omission(tmp_path):
    base,request,rp=setup(tmp_path)
    spec=s.graph(request,base,rp);root=tmp_path/'graph';g.create(root,spec)
    host=AgentHost(api_key='not-used')
    assert g.execute(root,host,workers=1)['complete']
    _,state=g._load(root);ref=state['nodes']['scan_inputs']['result'];doc=g._result(root,ref)
    assert doc['result']['kind']=='ravel_tool_result' and doc['result']['value']==s.compile(request,base)
    assert g.status(root)['usage']['calls']==1
    bad=copy.deepcopy(spec);bad['graph_id']='omitted';bad['nodes'][0]['inputs'].pop()
    other=tmp_path/'omitted';g.create(other,bad)
    assert not g.execute(other,host,workers=1)['complete']
    assert g.status(other)['nodes']['scan_inputs']['status']=='failed'


def test_original_input_directory_and_dotdot_aliases_are_preserved(tmp_path):
    base,_,rp=setup(tmp_path);before=set(base.rglob('*'))
    for output in (base/'new',tmp_path/'unused/../inputs/new'):
        with pytest.raises(ValueError):s.materialize(rp,base,output)
        assert set(base.rglob('*'))==before


def test_late_generated_script_drift_cannot_return_delivery(tmp_path,monkeypatch):
    base,_,rp=setup(tmp_path);original=s.atomic_json
    def mutate(path,value):
        original(path,value)
        p=Path(path).parent/'negative.mg5';p.write_bytes(p.read_bytes()+b'set param_card dim64f 910 1\n')
    monkeypatch.setattr(s,'atomic_json',mutate)
    with pytest.raises(ValueError):s.materialize(rp,base,tmp_path/'late')


def test_late_unbound_generated_member_refuses_completion(tmp_path,monkeypatch):
    base,_,rp=setup(tmp_path);original=s.atomic_json
    def add(path,value):
        original(path,value);(Path(path).parent/'extra.mg5').write_text('unbound script\n')
    monkeypatch.setattr(s,'atomic_json',add)
    with pytest.raises(ValueError,match='member census'):s.materialize(rp,base,tmp_path/'late-added')


def test_public_cli_graph_cannot_replace_or_append_into_original_inputs(tmp_path):
    base,_,rp=setup(tmp_path);before=Path(rp['path']).read_bytes();members=set(base.rglob('*'))
    for out in (Path(rp['path']),base/'graph.json'):
        with pytest.raises(ValueError):s.main(['--request',rp['path'],'--output',str(out),'--graph'])
        assert Path(rp['path']).read_bytes()==before and set(base.rglob('*'))==members
    output=tmp_path/'fresh-graph.json'
    assert s.main(['--request',rp['path'],'--output',str(output),'--graph'])==0
    assert json.loads(output.read_bytes())['nodes'][0]['action']=='sfitter-scan-inputs'
