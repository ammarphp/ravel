from workflow_instruction_inventory_fixture import FINAL_INVENTORY, assert_inventory
"""Source/API software controls; reader mocked, no ROOT or training calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from ravel.physics import tree_array_export as a

# Explicit synthetic migration layout, selected only by these fixtures.
IDS = ('ANA-0001-data.bin', 'ANA-0001-signal.bin')
OUTPUTS = ('arrays/left.npy', 'arrays/right.npy')
SCALARS = ('met_et', 'met_phi', 'mcWeight', 'SumWeights', 'XSection',
           'scaleFactor_PILEUP', 'scaleFactor_PHOTON', 'scaleFactor_PhotonTRIGGER',
           'scaleFactor_ELE', 'scaleFactor_MUON', 'scaleFactor_LepTRIGGER', 'scaleFactor_BTAG')
FAMILIES = (('photon', 2, 0), ('lep', 2, 6), ('jet', 6, 12))
BRANCHES = tuple(f'{family}_{coordinate}' for family, _, _ in FAMILIES
                 for coordinate in ('pt', 'eta', 'phi')) + ('photon_isTightID',) + SCALARS
COLUMNS = tuple(f'{family}_{coordinate}[{index}]' for family, count, _ in FAMILIES
                for index in range(count) for coordinate in ('pt', 'eta', 'phi')) + (
    *SCALARS[:5], 'photon_isTightID[0]', 'photon_isTightID[1]', *SCALARS[5:],
    'reserved-first', 'reserved-second')


def migration_layout():
    columns = [{'name': f'{family}_{coordinate}[{index}]', 'kind': 'jagged',
                'branch': family + '_' + coordinate, 'index': index, 'unit': '1'}
               for family, count, _ in FAMILIES for index in range(count) for coordinate in ('pt', 'eta', 'phi')]
    columns += [{'name': name, 'kind': 'scalar', 'branch': name, 'unit': '1'} for name in SCALARS[:5]]
    columns += [{'name': f'photon_isTightID[{index}]', 'kind': 'jagged', 'branch': 'photon_isTightID', 'index': index, 'unit': '1'} for index in (0, 1)]
    columns += [{'name': name, 'kind': 'scalar', 'branch': name, 'unit': '1'} for name in SCALARS[5:]]
    columns += [{'name': name, 'kind': 'constant', 'value': None, 'unit': '1'} for name in COLUMNS[-2:]]
    groups = [[family + '_' + coordinate for coordinate in ('pt', 'eta', 'phi')] for family, _, _ in FAMILIES]
    groups[0].append('photon_isTightID')
    return {'dtype': 'float64', 'columns': columns, 'jagged_groups': groups, 'padding': None, 'overflow': 'truncate'}


def pin(p):
    return {'path':str(p), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def fixture(tmp_path):
    roots=[]
    for name in IDS:
        p=tmp_path/name;p.write_bytes(b'INERT, NOT ROOT: '+name.encode());roots.append(p)
    authority=tmp_path/'authority.txt';authority.write_text('Synthetic source premises only')
    d={'schema_version':2,'study_id':'ANA-0001',
       'parameter_grid':{'axes':[{'name':'scale','unit':'1'}],'points':[{'scale':1}]},
       'sources':[pin(authority)], 'layout':migration_layout(),
       'datasets':[{'id':name,'pin':pin(p),'tree':'mini','destination':destination,'format':'npy','consumer':'downstream/'+str(i)}
                   for i,(name,p,destination) in enumerate(zip(IDS,roots,OUTPUTS))],
       'source_premises':{'units':'Synthetic unchanged source units','ordering':'Source positional indices unchanged',
                          'weight_semantics':'Separate raw signed weight and scale values'},
       'max_seconds':20,'max_ram_mib':128}
    path=tmp_path/'producer.json';path.write_bytes(a.encode(d))
    return {'input':str(path),'input_sha256':pin(path)['sha256']},d,roots


def branches(count=3):
    result={}
    lengths=[1,0,8][:count]
    for family,_,_ in FAMILIES:
        for coordinate in ('pt','eta','phi'):
            # Deliberately increasing pT: the producer must preserve tuple order.
            seed=BRANCHES.index(family+'_'+coordinate)*100
            result[family+'_'+coordinate]=[[seed+entry*10+i+1 for i in range(n)] for entry,n in enumerate(lengths)]
    result['photon_isTightID']=[[1,0,1,0,1,0,1,0][:n] for n in lengths]
    for i,name in enumerate(SCALARS):result[name]=np.array([i+entry/10 for entry in range(count)])
    if count==3:result['mcWeight']=np.array([-2.,0.,3.]);result['scaleFactor_ELE']=np.array([7.,8.,9.])
    return result


class FakeAk:
    """Explicit tiny reader-boundary double, not an Awkward qualification."""
    @staticmethod
    def num(v,axis):assert axis==1;return np.array([len(row) for row in v],dtype=int)
    @staticmethod
    def flatten(v,axis):assert axis==1;return [x for row in v for x in row]
    @staticmethod
    def to_numpy(v):return np.asarray(v)
    @staticmethod
    def is_none(v,axis):assert axis==0;return np.array([x is None for x in v],dtype=bool)
    @staticmethod
    def any(v):return np.any(v)
    @staticmethod
    def pad_none(v,slots,axis,clip):
        assert axis==1 and clip is True
        out=np.full((len(v),slots),np.nan)
        for i,row in enumerate(v):out[i,:min(len(row),slots)]=row[:slots]
        return out
    @staticmethod
    def fill_none(v,replacement):assert np.isnan(replacement);return v


class FakeUproot:
    def __init__(self, values=None, count=3):self.values=branches(count) if values is None else values;self.count=count;self.calls=[]
    def open(self,stream):
        assert hasattr(stream,'fileno') and not isinstance(stream,(str,Path))
        assert stream.read().startswith(b'INERT, NOT ROOT:');stream.seek(0)
        owner=self
        class Root:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def __getitem__(self,key):
                assert key=='mini'
                def arrays(names,**kwargs):
                    assert len(names)==len(BRANCHES) and set(names)==set(BRANCHES) and kwargs=={'library':'ak'}
                    owner.calls.append((key,len(names)));return deepcopy(owner.values)
                return SimpleNamespace(num_entries=owner.count,arrays=arrays)
        return Root()


def mock_runtime(monkeypatch,**kwargs):
    reader=FakeUproot(**kwargs);monkeypatch.setattr(a,'_runtime',lambda:(np,FakeAk,reader));return reader


def test_every46_column_allrows_raw_weight_and_corresponding_tuple_order(tmp_path,monkeypatch):
    task,d,roots=fixture(tmp_path);reader=mock_runtime(monkeypatch)
    result=a.run(task,tmp_path,tmp_path/'out')
    assert reader.calls==[('mini',22),('mini',22)]
    for index,record in enumerate(result['arrays']):
        arr=np.load(record['artifact']['path'],allow_pickle=False)
        assert arr.shape==(3,46) and arr.dtype==np.float64
        b=reader.values
        for family,slots,offset in FAMILIES:
            for slot in range(slots):
                for axis,coord in enumerate(('pt','eta','phi')):
                    value=b[family+'_'+coord][2][slot]
                    assert arr[2,offset+3*slot+axis]==value
        for name,col in zip(SCALARS,(30,31,32,33,34,37,38,39,40,41,42,43)):
            np.testing.assert_array_equal(arr[:,col],b[name])
        assert arr[2,35]==1 and arr[2,36]==0
        assert np.isnan(arr[:,44:]).all() and np.isnan(arr[1,:30]).all()
        assert arr[2,0]<arr[2,3]  # No implicit leading/subleading sort.
        assert record['nan_counts']==np.isnan(arr).sum(axis=0).tolist()
        assert record['padding_nan_counts'][3]==2
    assert len(result['file_census'])==len(d['datasets'])
    assert [x['consumer'] for x in result['filename_handoff']]==[x['consumer'] for x in d['datasets']]
    assert not (tmp_path/'solution').exists()
    assert all(result[k] is False for k in ('physics_validated','preprocessing_executed','training_executed','inference_executed','original_task_complete'))
    a.finalize(result,tmp_path/'out')


@pytest.mark.parametrize('count',[0,1,2,3])
def test_complete_tree_count_and_nan_padding(count):
    arr,m=a.convert(branches(count),count,np=np,ak=FakeAk,max_ram_mib=1,layout=migration_layout())
    assert arr.shape==(count,46) and m['constant_nan_counts'][-2:]==[count,count]


def test_source_nan_remains_distinct_from_missing_object():
    b=branches();b['photon_pt'][0][0]=np.nan;b['XSection'][0]=np.nan
    arr,m=a.convert(b,3,np=np,ak=FakeAk,max_ram_mib=1,layout=migration_layout())
    assert m['source_nan_counts'][0]==m['source_nan_counts'][34]==1
    assert m['padding_nan_counts'][0]==1 and np.isnan(arr[0,0])


@pytest.mark.parametrize('value',[np.ma.array([1.],mask=[True]),np.array([2**53+1],dtype=np.int64),np.array([float('inf')]),np.array(['1'])])
def test_no_silent_numeric_cast_or_missing_scalar(value):
    with pytest.raises(ValueError):a._vector(value,np)


@pytest.mark.parametrize('damage',['branch','row','length','scalar','inf','complex','null','wrong_count','memory'])
def test_full_branch_shape_numeric_and_population_refusals(damage):
    b=branches();count=3;ram=1
    if damage=='branch':b.pop('lep_phi')
    elif damage=='row':b['jet_pt'].pop()
    elif damage=='length':b['photon_eta'][0].append(1)
    elif damage=='scalar':b['met_et']=np.ones((3,2))
    elif damage=='inf':b['mcWeight'][0]=np.inf
    elif damage=='complex':b['met_phi']=np.ones(3,dtype=complex)
    elif damage=='null':b['jet_phi'][0][0]=None
    elif damage=='wrong_count':count=4
    elif damage=='memory':ram=0
    with pytest.raises(ValueError):a.convert(b,count,np=np,ak=FakeAk,max_ram_mib=ram,layout=migration_layout())


@pytest.mark.parametrize('damage',['selected_missing','duplicate_pin','record','handoff','list','source','input_sha'])
def test_original_file_id_complete_source_and_filename_laws(tmp_path,damage):
    task,d,roots=fixture(tmp_path)
    if damage=='selected_missing':d.pop('datasets')
    elif damage=='duplicate_pin':d['datasets'][1]['pin']=d['datasets'][0]['pin']
    elif damage=='record':d['datasets'][0]['id']=d['datasets'][1]['id']
    elif damage=='handoff':d['datasets'][0]['destination']='../foreign.npy'
    elif damage=='list':d['sources'][0]['sha256']='0'*64
    elif damage=='source':d['sources'][0]['path']=str(roots[0])
    p=Path(task['input']);p.write_bytes(a.encode(d));task['input_sha256']=pin(p)['sha256']
    if damage=='input_sha':task['input_sha256']='0'*64
    with pytest.raises(ValueError):a.inputs(task,tmp_path)


@pytest.mark.parametrize('damage',['new_file','remove','content','move','result','source','late_new_file','symlink'])
def test_ending_complete_source_output_and_returned_commitments(tmp_path,monkeypatch,damage):
    task,d,roots=fixture(tmp_path);mock_runtime(monkeypatch);out=tmp_path/'out';result=a.run(task,tmp_path,out)
    if damage=='new_file':(out/'unselected.bin').write_bytes(b'late')
    elif damage=='remove':(out/'filename-handoff.json').unlink()
    elif damage=='content':(out/OUTPUTS[0]).write_bytes(b'changed')
    elif damage=='move':out.rename(tmp_path/'relocated')
    elif damage=='result':result['arrays'][0]['shape'][0]+=1
    elif damage=='source':roots[1].write_bytes(b'changed')
    elif damage=='symlink':
        p=out/'filename-handoff.json';p.rename(out/'elsewhere');p.symlink_to(out/'elsewhere')
    elif damage=='late_new_file':
        original=a._check_pin
        def attacked(p):
            original(p)
            if p['path']==result['input_pins'][-1]['path']:(out/'unselected.bin').write_bytes(b'late')
        monkeypatch.setattr(a,'_check_pin',attacked)
    with pytest.raises((ValueError,OSError)):a.finalize(result,out)


def test_descriptor_input_alias_refuses_and_runtime_unavailable_before_output(tmp_path,monkeypatch):
    task,d,roots=fixture(tmp_path)
    before=a._identity(roots[0].lstat());other=tmp_path/'replacement';other.write_bytes(roots[0].read_bytes())
    roots[0].unlink();roots[0].symlink_to(other)
    with pytest.raises(ValueError):a._read_tree(roots[0],before,np=np,ak=FakeAk,uproot=FakeUproot(),max_ram_mib=1,tree='mini',layout=migration_layout())
    roots[0].unlink();roots[0].write_bytes(other.read_bytes());task,d,roots=fixture(tmp_path)
    def missing(name):raise ImportError('software control required runtime absent')
    monkeypatch.setattr(a.importlib,'import_module',missing)
    with pytest.raises(ValueError,match='requires'):a.run(task,tmp_path,tmp_path/'absent')
    assert not (tmp_path/'absent').exists()


def test_actual_descriptor_identity_is_required_before_reader(tmp_path,monkeypatch):
    import os
    task,d,roots=fixture(tmp_path);other=tmp_path/'foreign';other.write_bytes(roots[0].read_bytes())
    before=a._identity(roots[0].lstat());real_open=os.open;calls=[]
    def substitution(path,flags):
        calls.append(flags)
        return real_open(other,flags)
    monkeypatch.setattr(a.os,'open',substitution)
    reader=FakeUproot()
    with pytest.raises(ValueError,match='descriptor'):
        a._read_tree(roots[0],before,np=np,ak=FakeAk,uproot=reader,max_ram_mib=1,tree='mini',layout=migration_layout())
    assert reader.calls==[] and calls[0]&os.O_NOFOLLOW and calls[0]&os.O_NONBLOCK


def test_same_bytes_relocated_input_allowed_with_explicit_record_binding(tmp_path,monkeypatch):
    task,d,roots=fixture(tmp_path);p=tmp_path/'relocated-data.bin';p.write_bytes(roots[0].read_bytes())
    d['datasets'][0]['pin']=pin(p);request=Path(task['input']);request.write_bytes(a.encode(d));task['input_sha256']=pin(request)['sha256']
    mock_runtime(monkeypatch);result=a.run(task,tmp_path,tmp_path/'out')
    assert result['arrays'][0]['source']['path']==str(p)
    assert result['arrays'][0]['file_id']==IDS[0]


def test_new_operation_keeps_existing73_instruction_inventory_and_matching_mirrors():
    from ravel import paths
    C=Path(__file__).parents[2]
    assert set(FINAL_INVENTORY) <= set(paths.WORKFLOW_INSTRUCTIONS)
    for rel in ('docs/cli.md','docs/workflow/start.md'):
        assert (C/rel).read_bytes()==(C/'src/ravel/data/workflow'/rel).read_bytes()
        assert 'tree-array-export' in (C/rel).read_text()


def specification(task):
    actors={k:'synthetic-'+k for k in ('proposer','executor','physics_critic','skeptical_verifier','physics_decider')}
    return {'schema_version':2,'mode':'tree-array-export','source':'Explicit synthetic source/API control, no actual ROOT',
        'assumptions':['Object order and units are source premises, not independent qualification'], 'max_seconds':20,
        'max_attempts':1,'approval_mode':'physicist','task':task,
        'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':actors,'max_redos':0,'allowed_changed_paths':[],
            'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],
            'claim_scopes':{a.SCOPE:{'checks':['integrity'],'actions':['delivery']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}}


def test_real_ordinary_unapproved_plan_and_focused_cli(tmp_path,capsys):
    from ravel.workflow import science
    from ravel import cli
    task,d,roots=fixture(tmp_path);spec=specification(task);p=tmp_path/'spec.json';p.write_bytes(a.encode(spec))
    rd=tmp_path/'ordinary';planned=science.plan(rd,p)
    assert planned['schema_version']==2 and all(str(x) in planned['stage_binding']['inputs'] for x in roots)
    assert not (rd/science.APPROVAL).exists() and science.packet(rd)['lifecycle_verdict']=='PENDING'
    tp=tmp_path/'task.json';tp.write_bytes(a.encode(task))
    assert cli.main(['tree-array-export','inspect','--task',str(tp)])==0
    assert 'raw_array_delivery' in capsys.readouterr().out


def test_real_graph_host_full_source_context_and_stale_refusal(tmp_path):
    from ravel.workflow import agent_graph as graph, agent_host as host, execution
    task,d,roots=fixture(tmp_path);tp=tmp_path/'task.json';tp.write_bytes(a.encode(task))
    pins=[{'id':'task','path':str(tp),'sha256':pin(tp)['sha256']}]
    pins += [{'id':'d'+str(i),'path':str(p),'sha256':execution.file_hash(p)} for i,p in enumerate(a.inputs(task,tmp_path))]
    node={'id':'array-context','kind':'tool','role':'executor','depends_on':[],'inputs':pins,'packet':None,
          'action':'tree-array-context','parameters':{'request_input':'task'},'max_attempts':1}
    spec={'schema_version':1,'graph_id':'llm-array-context','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':20,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';graph.create(root,spec);result=graph.execute(root,host.AgentHost(),workers=1)
    assert result['complete'] and result['execution_authorized'] is False
    roots[0].write_bytes(b'changed')
    with pytest.raises(graph.GraphError):graph.execute(root,host.AgentHost(),workers=1)


@pytest.mark.parametrize('late',['none','report','source','new_file','result'])
def test_actual_common_worker_result_report_and_ending_recheck(tmp_path,monkeypatch,late):
    from ravel.physics import science_worker as w
    task,d,roots=fixture(tmp_path);mock_runtime(monkeypatch);rd=tmp_path/'run';spec=specification(task)
    # Actual common worker body, only the approval/runtime boundary is inert.
    monkeypatch.setattr(w,'verify_worker',lambda _: {'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
    monkeypatch.setattr(w,'execution_spec',lambda _:spec)
    original=Path.write_text
    def last_write(p,text,*args,**kwargs):
        value=original(p,text,*args,**kwargs)
        if p.name=='RESULT.md':
            out=p.parent
            if late=='report':(out/'tree-array-report.json').write_bytes(b'{}')
            elif late=='source':roots[0].write_bytes(b'changed')
            elif late=='new_file':(out/'tree-array-export/late.txt').write_bytes(b'late')
            elif late=='result':(out/'result.json').write_bytes(b'{}')
        return value
    monkeypatch.setattr(Path,'write_text',last_write)
    if late=='none':
        assert w.main([str(rd)])==0
        result=json.loads((rd/'outputs/attempt-1/result.json').read_text())
        assert result['status']=='passed' and result['physics_validated'] is False
    else:
        with pytest.raises(ValueError):w.main([str(rd)])
