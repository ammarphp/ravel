"""Portable delivery controls; no benchmark oracle or physics process."""
from copy import deepcopy
from fractions import Fraction
import hashlib,json,math
from pathlib import Path
import pytest
from ravel.workflow import scientific_artifact as s

def write(path,value):
    path.write_text(value if type(value) is str else json.dumps(value,sort_keys=True,allow_nan=False)+'\n')
    return {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}

def fixture(tmp_path):
    tool={'rows':[{'row':1,'label':'first','eff':'1/2'},{'row':2,'label':'boundary','eff':'6/65'}],
        'winner':[2],'final':{'signal':'48','background':'120','usable':False,'ratio':'4.38'},
        'loss':'59/65'}
    pin=write(tmp_path/'tool.json',tool)
    fields=[{'field':'signal','type':'integer','source':{'kind':'direct','tool_id':'math','pointer':'/final/signal'}},
        {'field':'usable','type':'boolean','source':{'kind':'direct','tool_id':'math','pointer':'/final/usable'}},
        {'field':'efficiency','type':'number','source':{'kind':'unique_row','tool_id':'math','rows_pointer':'/rows',
            'matches_pointer':'/winner','row_key':'row','field':'eff'}},
        {'field':'loss','type':'number','source':{'kind':'direct','tool_id':'math','pointer':'/loss'}},
        {'field':'ratio','type':'number','source':{'kind':'direct','tool_id':'math','pointer':'/final/ratio'}}]
    request={'schema_version':1,'basis':[write(tmp_path/'prompt.txt','Supplied yields only. Status is a string with no enum.')],
        'tools':{'math':pin},'contract':{'source_scope':'Caller-supplied arithmetic only; no discovery significance.',
            'tool_fields':fields,'interpretation_fields':['status','recommendation'],
            'unresolved_semantics':[{'field':'status','reason':'Prompt gives no status vocabulary.'}],
            'max_artifact_bytes':2048},'interpretation':{'status':'below_declared_yield_threshold','recommendation':'Investigate the boundary selection.'}}
    return request,tool

def repin(request,tmp_path,tool):request['tools']['math']=write(tmp_path/'tool.json',tool)

def test_exact_tools_deliver_strict_json_without_model_numeric_rewrite(tmp_path):
    request,_=fixture(tmp_path);out=s.compose(request,base_dir=tmp_path)
    assert json.loads(out['artifact_text'])==out['artifact']
    assert not out['artifact_text'].startswith('```')
    assert out['artifact']['efficiency']==float(Fraction(6,65)) and out['artifact']['loss']==float(Fraction(59,65))
    assert out['artifact']['efficiency']!=.09 and out['artifact']['loss']!=.91
    facts={row['field']:row for row in out['tool_provenance']}
    assert facts['efficiency']['source_exact']=='6/65' and facts['loss']['source_exact']=='59/65'
    assert facts['ratio']['source_exact']=='219/50' and facts['ratio']['decimal_rounding_applied'] is False
    assert out['artifact']['signal']==48 and type(out['artifact']['signal']) is int and out['artifact']['usable'] is False
    assert out['unresolved_semantics']==request['contract']['unresolved_semantics']
    assert all(out[k] is False for k in ('tool_report_truth_verified','interpretation_scientifically_validated','complete_task_semantics_claimed','scientific_acceptance','execution_authorized'))

@pytest.mark.parametrize('value,kind,expected',[('-.125','number',-.125),('3/2','number',1.5),('2e2','integer',200),(0,'number',0.0),(True,'boolean',True),('source label','string','source label')])
def test_typed_values_preserve_declared_source_semantics(tmp_path,value,kind,expected):
    request,tool=fixture(tmp_path);tool['loss']=value;repin(request,tmp_path,tool)
    request['contract']['tool_fields']=[{'field':'value','type':kind,'source':{'kind':'direct','tool_id':'math','pointer':'/loss'}}]
    out=s.compose(request,base_dir=tmp_path);assert out['artifact']['value']==expected

@pytest.mark.parametrize('value,kind',[('3/2','integer'),(True,'integer'),(False,'number'),('nan','number'),('inf','number'),('1/0','number'),('1e1025','number'),('1e-1000','number'),('1e1000','number'),(1,'boolean'),(1,'string')])
def test_undefined_or_mistyped_tool_values_refuse_without_invented_rounding(tmp_path,value,kind):
    request,tool=fixture(tmp_path);tool['loss']=value;repin(request,tmp_path,tool)
    request['contract']['tool_fields'][3]['type']=kind
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_source_float_is_retained_with_token_enclosure_unproved(tmp_path):
    request,tool=fixture(tmp_path);tool['loss']=.1;repin(request,tmp_path,tool)
    out=s.compose(request,base_dir=tmp_path);row=next(x for x in out['tool_provenance'] if x['field']=='loss')
    assert out['artifact']['loss']==.1 and row['conversion']=='unchanged_source_binary64' and row['source_numeric_token_enclosure_proved'] is False

@pytest.mark.parametrize('field',['signal','scientific_acceptance','execution_authorized','physics_validated'])
def test_model_interpretation_cannot_replace_numeric_fields_or_authorize(tmp_path,field):
    request,_=fixture(tmp_path);request['contract']['interpretation_fields'].append(field);request['interpretation'][field]='yes'
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

@pytest.mark.parametrize('matches',[[],[1,2],['2'],[999]])
def test_tied_absent_or_mistyped_selected_rows_preserve_ambiguity_as_refusal(tmp_path,matches):
    request,tool=fixture(tmp_path);tool['winner']=matches;repin(request,tmp_path,tool)
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_duplicate_row_identity_refuses(tmp_path):
    request,tool=fixture(tmp_path);tool['rows'][0]['row']=2;repin(request,tmp_path,tool)
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

@pytest.mark.parametrize('pointer',['','/rows/01/eff','/rows/-1/eff','/rows/2/eff','/loss/nested','/bad~2key'])
def test_missing_nonliteral_or_invalid_paths_refuse(tmp_path,pointer):
    request,_=fixture(tmp_path);request['contract']['tool_fields'][3]['source']['pointer']=pointer
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_literal_pointer_escapes_select_actual_source(tmp_path):
    request,tool=fixture(tmp_path);tool['a/b~c']='1/3';repin(request,tmp_path,tool)
    request['contract']['tool_fields'][3]['source']['pointer']='/a~1b~0c'
    assert s.compose(request,base_dir=tmp_path)['artifact']['loss']==float(Fraction(1,3))

@pytest.mark.parametrize('path',['tool.json','prompt.txt'])
def test_changed_source_or_tool_refuses(tmp_path,path):
    request,_=fixture(tmp_path);(tmp_path/path).write_text('changed')
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_symlink_cannot_hide_tool_substitution(tmp_path):
    request,_=fixture(tmp_path);target=tmp_path/'tool.json';raw=target.read_bytes();target.unlink();other=tmp_path/'elsewhere.json';other.write_bytes(raw);target.symlink_to(other)
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_complete_json_output_bound_refuses_truncation(tmp_path):
    request,_=fixture(tmp_path);request['contract']['max_artifact_bytes']=128
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_independent_scan_and_lhe_reports_use_same_delivery_api(tmp_path):
    request,_=fixture(tmp_path)
    scan={'fits':[{'id':'first','xsec_pb':'0.01'},{'id':'selected','xsec_pb':'0.003'}],'selected':['selected']}
    lhe={'events':20,'negative_weight_events':3,'weights_sum':'-7/2'}
    request['tools']={'scan':write(tmp_path/'scan.json',scan),'lhe':write(tmp_path/'lhe.json',lhe)}
    request['contract']['tool_fields']=[{'field':'xsec_pb','type':'number','source':{'kind':'unique_row','tool_id':'scan','rows_pointer':'/fits','matches_pointer':'/selected','row_key':'id','field':'xsec_pb'}},
        {'field':'events','type':'integer','source':{'kind':'direct','tool_id':'lhe','pointer':'/events'}},
        {'field':'signed_sumw','type':'number','source':{'kind':'direct','tool_id':'lhe','pointer':'/weights_sum'}}]
    out=s.compose(request,base_dir=tmp_path);assert out['artifact']['xsec_pb']==.003 and out['artifact']['events']==20 and out['artifact']['signed_sumw']==-3.5
    assert len(s.input_pins(request,base_dir=tmp_path))==3

def test_output_strings_are_preserved_not_executed(tmp_path):
    request,_=fixture(tmp_path);request['interpretation']['recommendation']='```json\nmodel prose with $(command)\n```'
    out=s.compose(request,base_dir=tmp_path)
    assert json.loads(out['artifact_text'])['recommendation']==request['interpretation']['recommendation']

def test_duplicate_json_source_keys_refuse(tmp_path):
    request,_=fixture(tmp_path);request['tools']['math']=write(tmp_path/'tool.json','{"loss":1,"loss":2}')
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_complete_numeric_plot_arrays_and_metadata_are_typed_from_tools(tmp_path):
    request,tool=fixture(tmp_path);tool['plot']={'x':['-1','0','1'],'y':['-3/2','0','7/2'],'unit':'pb'};repin(request,tmp_path,tool)
    schema={'type':'object','properties':{'x':{'type':'array','items':'number','max_items':3},
        'y':{'type':'array','items':'number','max_items':3},'unit':'string'}}
    request['contract']['tool_fields']=[{'field':'plot','type':schema,'source':{'kind':'direct','tool_id':'math','pointer':'/plot'}}]
    out=s.compose(request,base_dir=tmp_path)
    assert out['artifact']['plot']=={'x':[-1.,0.,1.],'y':[-1.5,0.,3.5],'unit':'pb'}
    assert out['tool_provenance'][0]['properties']['y']['items'][0]['source_exact']=='-3/2'

@pytest.mark.parametrize('variant',['extra','missing','too_many','wrong_type','fractional_integer','authorizing_property','unbounded_array','deep'])
def test_structured_source_shape_refuses_incomplete_or_unbounded_delivery(tmp_path,variant):
    request,tool=fixture(tmp_path);tool['plot']={'y':['1','2']};schema={'type':'object','properties':{'y':{'type':'array','items':'integer','max_items':2}}}
    if variant=='extra':tool['plot']['other']=3
    elif variant=='missing':tool['plot']={}
    elif variant=='too_many':tool['plot']['y'].append('3')
    elif variant=='wrong_type':tool['plot']['y']='1,2'
    elif variant=='fractional_integer':tool['plot']['y'][0]='1/3'
    elif variant=='authorizing_property':schema['properties']['physics_validated']='boolean'
    elif variant=='unbounded_array':schema['properties']['y']['max_items']=0
    else:
        nested='number'
        for _ in range(5):nested={'type':'array','items':nested,'max_items':1}
        schema=nested
    repin(request,tmp_path,tool);request['contract']['tool_fields']=[{'field':'plot','type':schema,'source':{'kind':'direct','tool_id':'math','pointer':'/plot'}}]
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)


@pytest.mark.parametrize('token',['١','１','01','+1','-0','1.0',' 1',''])
def test_array_pointer_requires_literal_ascii_index(tmp_path,token):
    request,_=fixture(tmp_path)
    request['contract']['tool_fields'][3]['source']['pointer']='/rows/'+token+'/eff'
    with pytest.raises(ValueError):s.compose(request,base_dir=tmp_path)

def test_ascii_pointer_and_unicode_object_key_are_distinct(tmp_path):
    assert s._pointer({'rows':[3,7]},'/rows/1')==7
    assert s._pointer({'١':9},'/١')==9

def test_basis_alias_is_not_a_second_independent_source(tmp_path):
    request,_=fixture(tmp_path)
    alias=deepcopy(request['basis'][0]);alias['path']='./'+alias['path']
    request['basis'].append(alias)
    with pytest.raises(ValueError,match='canonical source basis'):s.compose(request,base_dir=tmp_path)

def test_basis_literal_alias_remains_attributed_when_unique(tmp_path):
    request,_=fixture(tmp_path);request['basis'][0]['path']='./prompt.txt'
    assert s.compose(request,base_dir=tmp_path)['basis'][0]['path']=='./prompt.txt'
