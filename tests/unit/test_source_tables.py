import copy,hashlib,json
from pathlib import Path
from decimal import Decimal
import pytest,yaml
from ravel.physics.source_tables import digest,join,number,read_table
H=Path(__file__).parent

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def write(p,v):p.write_text(yaml.safe_dump(v,sort_keys=False));return pin(p)

def make(tmp_path):
 d={'independent_variables':[{'header':{'name':'x','units':'GeV'},'values':[{'low':0,'high':1},{'low':1,'high':3}]}],'dependent_variables':[{'header':{'name':'value','units':'fb/GeV'},'qualifiers':[{'name':'region','value':'A'}],'values':[{'value':2,'errors':[{'label':'source','asymerror':{'minus':'-10%','plus':'20%'}}]},{'value':3,'errors':[{'label':'stat','symerror':.4}]}]}]}
 dp=write(tmp_path/'data.yaml',d);t=read_table(dp)
 m={'independent_variables':[{'header':{'name':'row'},'values':[{'value':1},{'value':1},{'value':2},{'value':2}]},{'header':{'name':'col'},'values':[{'value':1},{'value':2},{'value':1},{'value':2}]}],'dependent_variables':[{'header':{'name':'C','units':'fb^2'},'values':[{'value':2},{'value':-1},{'value':-1},{'value':3}]}]}
 mp=write(tmp_path/'matrix.yaml',m);e=tmp_path/'basis.txt';e.write_text('Source1 maps to A;Source2 maps to B. Fabricated portable source, no physics.')
 c={'kind':'primary-table-basis-join/v2','distributions':[{'id':'d','source':dp,'expected_axes':t['payload']['independent_variables'],'expected_row_count':2,'selections':[{'header':t['payload']['dependent_variables'][0]['header'],'qualifiers':t['payload']['dependent_variables'][0]['qualifiers']}],'bin_ids':['A','B']}],'basis_link':{'matrix_labels':['1','2'],'ordered_bin_ids':['A','B'],'source_evidence':pin(e)|{'interpretation':'Explicit fabricated source ordering.'}},'matrices':[{'id':'C','source':mp,'selection':{'header':{'name':'C','units':'fb^2'},'qualifiers':[]},'axis_headers':[{'name':'row'},{'name':'col'}],'axis_qualifiers':[[],[]],'kind':'covariance','declared_output_unit':'fb^2'}]}
 return c,d,m

def test_literal_source_tokens_and_asymmetric_relative_errors_not_law(tmp_path):
 c,_,_=make(tmp_path);r=join(c,expected_contract_sha256=digest(c))
 assert r['distributions'][0]['selected_columns'][0]['values'][0]['errors'][0]['asymerror']=={'minus':'-10%','plus':'20%'}
 assert not r['covariance_from_marginal_errors'] and not r['joint_matrix_sum_constructed']
 assert r['matrix_components'][0]['literal_matrix'][0][1]=={'literal':'-1','decimal':'-1'}

@pytest.mark.parametrize('fault',['missing_cell','duplicate_cell','unknown_coordinate','asymmetric','marginal_error_cell','wrong_axis','header','qualifier','edge','duplicate_ids','wrong_basis','changed_source','digest'])
def test_closed_census_basis_source_adverse(tmp_path,fault):
 c,d,m=make(tmp_path)
 if fault=='missing_cell':
  for a in m['independent_variables']:a['values'].pop()
  m['dependent_variables'][0]['values'].pop()
 if fault=='duplicate_cell':m['independent_variables'][1]['values'][1]['value']=1
 if fault=='unknown_coordinate':m['independent_variables'][0]['values'][0]['value']=99
 if fault=='asymmetric':m['dependent_variables'][0]['values'][1]['value']=-2
 if fault=='marginal_error_cell':m['dependent_variables'][0]['values'][1]['errors']=[{'symerror':1}]
 if fault=='wrong_axis':m['independent_variables'][0]['header']['name']='wrong'
 if fault=='header':c['distributions'][0]['selections'][0]['header']['units']='pb'
 if fault=='qualifier':c['distributions'][0]['selections'][0]['qualifiers']=[]
 if fault=='edge':c['distributions'][0]['expected_axes'][0]['values'][1]['high']['literal']='3.1'
 if fault=='duplicate_ids':c['distributions'][0]['bin_ids']=['A','A']
 if fault=='wrong_basis':c['basis_link']['ordered_bin_ids']=['A','C']
 if fault in ('missing_cell','duplicate_cell','unknown_coordinate','asymmetric','marginal_error_cell','wrong_axis'):c['matrices'][0]['source']=write(tmp_path/'matrix.yaml',m)
 if fault=='changed_source':(tmp_path/'data.yaml').write_text((tmp_path/'data.yaml').read_text()+'\n')
 with pytest.raises(ValueError):join(c,expected_contract_sha256='0'*64 if fault=='digest' else digest(c))

@pytest.mark.parametrize('text',['x: 1\nx: 2\n','x: &a [1,2]\ny: *a\n','x: .nan\n','x: !!python/object:os.system {}\n'])
def test_ambiguous_unsafe_yaml_refuses(tmp_path,text):
 p=tmp_path/'bad.yaml';p.write_text(text)
 with pytest.raises(ValueError):read_table(pin(p))

def test_subset_reorders_by_explicit_labels_and_retains_full_parent(tmp_path):
 c,_,_=make(tmp_path)
 for row in c['distributions']:
  row['bin_ids']=['B','A']
 c['basis_link']['ordered_bin_ids']=['A','B']
 r=join(c,expected_contract_sha256=digest(c));m=r['matrix_components'][0]
 assert m['source_indices']==[1,0]
 assert number(m['literal_matrix'][0][0])==3
 assert number(m['literal_full_source_matrix'][0][0])==2



@pytest.mark.parametrize('literal,expected',[('yes',True),('on',True),('no',False),('off',False),('true',True),('false',False)])
def test_yaml11_qualifier_booleans_correct(tmp_path,literal,expected):
    p=tmp_path/'bool.yaml'
    p.write_text('independent_variables: [{header: {name: x}, values: [{value: 1}]}]\ndependent_variables: [{header: {name: y}, qualifiers: [{name: active, value: '+literal+'}], values: [{value: 2}]}]\n')
    t=read_table(pin(p));assert t['payload']['dependent_variables'][0]['qualifiers'][0]['value'] is expected

@pytest.mark.parametrize('literal',['012','0x10','1_000','0b10'])
def test_ambiguous_yaml_integer_refusal(tmp_path,literal):
    p=tmp_path/'int.yaml';p.write_text('independent_variables: [{header: {name: x}, values: [{value: '+literal+'}]}]\ndependent_variables: [{header: {name: y}, values: [{value: 2}]}]\n')
    with pytest.raises(ValueError,match='decimal integer'):read_table(pin(p))

def test_axis_qualifiers_preserved_and_exactly_compared(tmp_path):
    c,d,m=make(tmp_path);d['independent_variables'][0]['qualifiers']=[{'name':'era','value':'Run2'}]
    c['distributions'][0]['source']=write(tmp_path/'data.yaml',d)
    c['distributions'][0]['expected_axes']=read_table(c['distributions'][0]['source'])['payload']['independent_variables']
    r=join(c,expected_contract_sha256=digest(c));assert r['distributions'][0]['axes'][0]['qualifiers']==[{'name':'era','value':'Run2'}]
    c['distributions'][0]['expected_axes'][0].pop('qualifiers')
    with pytest.raises(ValueError,match='geometry'):join(c,expected_contract_sha256=digest(c))

def test_matrix_axis_qualifiers_preserved_and_exactly_compared(tmp_path):
    c,d,m=make(tmp_path);m['independent_variables'][0]['qualifiers']=[{'name':'era','value':'Run2'}]
    c['matrices'][0]['source']=write(tmp_path/'matrix.yaml',m)
    with pytest.raises(ValueError,match='matrix geometry'):join(c,expected_contract_sha256=digest(c))
    c['matrices'][0]['axis_qualifiers']=[[{'name':'era','value':'Run2'}],[]]
    r=join(c,expected_contract_sha256=digest(c));assert r['matrix_components'][0]['source_axes'][0]['qualifiers']==c['matrices'][0]['axis_qualifiers'][0]

def test_stated_source_unit_mismatch_refuses_and_blank_is_unadmitted(tmp_path):
    c,d,m=make(tmp_path);c['matrices'][0]['declared_output_unit']='pb^2'
    with pytest.raises(ValueError,match='unit mismatch'):join(c,expected_contract_sha256=digest(c))
    m['dependent_variables'][0]['header']['units']='';c['matrices'][0]['source']=write(tmp_path/'matrix.yaml',m);c['matrices'][0]['selection']['header']['units']=''
    r=join(c,expected_contract_sha256=digest(c));assert not r['matrix_components'][0]['declared_output_unit_admitted']
    assert r['matrix_components'][0]['unit_semantics']=='unadmitted_caller_annotation_source_unit_empty'


def task(tmp_path):
    c,_,_=make(tmp_path);p=tmp_path/'contract.json';p.write_text(json.dumps(c,sort_keys=True))
    return {'schema_version':1,'input':p.name,'contract_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def test_normal_task_full_source_graph_fresh_delivery(tmp_path):
    from ravel.physics.source_tables import inputs,run,validate
    spec=task(tmp_path);before={str(p):p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert {p.name for p in inputs(spec,tmp_path)}=={'contract.json','basis.txt','data.yaml','matrix.yaml'}
    out=tmp_path/'delivery';r=run(spec,tmp_path,out)
    assert r==json.loads((out/'source-tables.json').read_text())
    assert r['status']=='passed' and r['physics_validated'] is False and r['statistical_inference'] is None
    assert before=={str(p):p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    snapshot=(out/'source-tables.json').read_bytes()
    with pytest.raises(ValueError,match='fresh'):run(spec,tmp_path,out)
    assert snapshot==(out/'source-tables.json').read_bytes()
    with pytest.raises(ValueError):validate({**spec,'infer_error_law':True})
    spec['contract_sha256']='0'*64
    with pytest.raises(ValueError,match='digest'):inputs(spec,tmp_path)


def test_ordinary_dispatch_and_actual_worker_filesystem(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    from ravel.workflow import science
    from ravel.workflow.state_io import atomic_json,read_json
    from test_science_capability_integration import specification
    t=task(tmp_path);spec=specification('source-tables',t)
    assert science.adapter(spec).__name__=='ravel.physics.source_tables'
    assert {p.name for p in science.task_inputs(spec,tmp_path)}=={'contract.json','basis.txt','data.yaml','matrix.yaml'}
    assert science._new_capability(spec) is True
    rd=tmp_path/'worker-run';(rd/'inputs').mkdir(parents=True)
    atomic_json(rd/'inputs/science.json',spec)
    atomic_json(rd/'inputs/science-plan.json',{'schema_version':2,'execution_task':t,'mutable_inputs':[]})
    atomic_json(rd/'inputs/science-execution-task.json',{'schema_version':1,'task':t})
    proposal={'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}}
    # Authorization and optional rendering are mocked. Real worker dispatch,
    # adapter semantics/output and exact repeat-refusal filesystem remain real.
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal)
    monkeypatch.setattr(science_figures,'render',lambda *_:{'figures':[],'tables':[]})
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';result=read_json(out/'result.json')
    assert result==read_json(out/'source-tables/source-tables.json')
    assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
    snapshot={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
    assert snapshot=={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}


def test_relative_nested_sources_bound_under_contract_directory(tmp_path):
    from ravel.physics.source_tables import inputs
    c,_,_=make(tmp_path)
    for d in c['distributions']:d['source']['path']=Path(d['source']['path']).name
    for m in c['matrices']:m['source']['path']=Path(m['source']['path']).name
    c['basis_link']['source_evidence']['path']='basis.txt'
    p=tmp_path/'relative-contract.json';p.write_text(json.dumps(c))
    t={'schema_version':1,'input':str(p),'contract_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    assert {x.name for x in inputs(t,tmp_path)}=={p.name,'basis.txt','data.yaml','matrix.yaml'}


def test_actual_renderer_literal_table_not_histogram(tmp_path):
    from ravel.physics.source_tables import run
    from ravel.plotting.science_figures import render
    t=task(tmp_path);r=run(t,tmp_path,tmp_path/'delivery')
    spec={'mode':'source-tables','task':t}
    report=render(spec,r,tmp_path,tmp_path)
    assert report['status']=='passed' and not report['figures']
    assert json.loads((tmp_path/'source-table-report.json').read_text())==r
    text=(tmp_path/'source-table-report.md').read_text()
    assert '-10%' in text and '20%' in text and 'fb/GeV' in text
    assert 'No' not in report['tables'][0]['normalization']


def test_descriptor_size_bound_and_initial_ancestor_link(tmp_path):
    from ravel.physics.source_tables import bounded_read
    big=tmp_path/'big';big.touch()
    with big.open('r+b') as stream:stream.truncate(4*1024*1024+1)
    with pytest.raises(ValueError,match='bounded'):bounded_read(big)
    folder=tmp_path/'ordinary';folder.mkdir();leaf=folder/'leaf';leaf.write_bytes(b'one')
    alias=tmp_path/'alias';alias.symlink_to(folder,target_is_directory=True)
    with pytest.raises(ValueError,match='ordinary'):bounded_read(alias/'leaf')


def test_real_ending_ancestor_swap_refuses_same_leaf_inode(tmp_path,monkeypatch):
    import os
    from ravel.physics.source_tables import bounded_read
    folder=tmp_path/'original';folder.mkdir();leaf=folder/'leaf';leaf.write_bytes(b'one')
    moved=tmp_path/'moved';native=os.fdopen
    class Observed:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def fileno(self):return self.stream.fileno()
        def read(self,size):
            data=self.stream.read(size);folder.rename(moved);folder.symlink_to(moved,target_is_directory=True);return data
    monkeypatch.setattr(os,'fdopen',lambda *args,**kw:Observed(native(*args,**kw)))
    with pytest.raises(ValueError,match='ending'):bounded_read(leaf)
