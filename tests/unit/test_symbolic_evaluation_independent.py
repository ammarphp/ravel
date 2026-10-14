"""Independent inert EDA API/result controls; no symbolic engine or native work."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import test_symbolic_evaluation as fixtures
from ravel.physics import symbolic_evaluation as se


def witness(tmp_path, name, value):
    p=tmp_path/name
    p.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


class InvalidPython(fixtures.Converter):
    def mathematica_to_python_source(self, expr, names, **kwargs):
        return 'def result_width(:\n    return 0\n'


class WrongFunction(fixtures.Converter):
    def mathematica_to_python_source(self, expr, names, **kwargs):
        return 'def another_result():\n    return 0\n'


@pytest.mark.parametrize('converter', [InvalidPython, WrongFunction])
def test_unusable_generated_python_is_not_delivered(tmp_path, converter):
    d=fixtures.result_decl()
    d['points']=[]  # Explicit symbolic-to-Python-only request.
    try:
        result=se.convert_result({'id':'width','symbol':'width','formula':'0'}, d, converter())
    except ValueError:
        return
    witness(tmp_path,'generated-python-accepted.json',result)
    pytest.fail('Unusable or mismatched generated Python was marked delivered')


def test_python_keyword_coordinate_is_not_a_valid_generated_signature(tmp_path,monkeypatch):
    c,_=fixtures.configuration(tmp_path,monkeypatch)
    r=c['scripts'][0]['results'][0]
    r['variables']=[{'name':'class','domain':'real','units':'1','dimension_GeV':0}]
    r['points']=[]
    try:
        se.validate_config(c)
    except ValueError:
        return
    witness(tmp_path,'python-keyword-request-accepted.json',c)
    pytest.fail('Python keyword coordinate accepted for generated function argument')


def test_canonical_formula_and_checked_document_remain_bound_through_conversion(tmp_path,monkeypatch):
    original=fixtures.Converter
    changed=[]
    class SidecarChange(original):
        def mathematica_to_python_source(self,expr,names,**kwargs):
            p=tmp_path/'run/outputs/attempt-1/script0/canonical-symbolic.json'
            if not changed:
                doc=json.loads(p.read_text())
                doc['results'][0]['formula']='999'
                p.write_text(json.dumps(doc)+'\n')
                changed.append(str(p))
            return super().mathematica_to_python_source(expr,names,**kwargs)
    monkeypatch.setattr(fixtures,'Converter',SidecarChange)
    try:
        rd,code,calls,c,task=fixtures.inert_worker(tmp_path,monkeypatch)
    except ValueError:
        return
    out=rd/'outputs/attempt-1'
    result=json.loads((out/'result.json').read_text())
    raw=json.loads((out/'script0/canonical-symbolic.json').read_text())
    witness(tmp_path,'canonical-to-result-correspondence.json',{'ordinary_exit':code,
        'result_status':result['status'],'delivered_formula':result['results'][0]['formula'],
        'canonical_formula':raw['results'][0]['formula'],
        'reported_canonical_source':result['results'][0].get('canonical_source'),
        'actual_pin':fixtures.pin(out/'script0/canonical-symbolic.json'),
        'native_calls':0,'converter':'explicit inert fixture'})
    assert code != 0 or result['status'] != 'passed', 'Changed canonical formula accepted by real common worker/finalizer'


def test_generated_module_cannot_change_before_final_result_commitment(tmp_path,monkeypatch):
    original=fixtures.Converter
    changed=[]
    class PriorModuleChange(original):
        def mathematica_to_python_source(self,expr,names,**kwargs):
            p=tmp_path/'run/outputs/attempt-1/script0/width0.py'
            if p.exists() and not changed:
                p.write_text('def result_width0():\n    return 999\n')
                changed.append(str(p))
            return super().mathematica_to_python_source(expr,names,**kwargs)
    monkeypatch.setattr(fixtures,'Converter',PriorModuleChange)
    try:
        rd,code,calls,c,task=fixtures.inert_worker(tmp_path,monkeypatch)
    except ValueError:
        return
    out=rd/'outputs/attempt-1'; result=json.loads((out/'result.json').read_text())
    witness(tmp_path,'generated-source-to-result-correspondence.json',{'ordinary_exit':code,
        'result_status':result['status'],'reported_python_source':result['results'][0]['python_source'],
        'actual_pin':fixtures.pin(out/'script0/width0.py'),'native_calls':0})
    assert code != 0 or result['status'] != 'passed', 'Changed generated module accepted with stale delivered source pin'


@pytest.mark.parametrize('change', ['missing','extra','reordered','duplicate'])
def test_canonical_exact_ordered_population(tmp_path,monkeypatch,change):
    c,_=fixtures.configuration(tmp_path,monkeypatch)
    s=c['scripts'][0]
    s['results'].append(fixtures.result_decl('other'))
    value=fixtures.sidecar(c,s,tmp_path/'staged')
    if change=='missing': value['results'].pop()
    if change=='extra': value['results'].append(dict(value['results'][0],id='extra'))
    if change=='reordered': value['results'].reverse()
    if change=='duplicate': value['results'][1]=dict(value['results'][0])
    with pytest.raises(ValueError): se.validate_sidecar(value,c,s,tmp_path/'staged',123)


def test_distinct_masses_and_complex_domain_are_retained_in_lower_api():
    d=fixtures.result_decl()
    d['variables']=[{'name':'M','domain':'positive_real','units':'GeV','dimension_GeV':1},
        {'name':'m1','domain':'nonnegative_real','units':'GeV','dimension_GeV':1},
        {'name':'m2','domain':'nonnegative_real','units':'GeV','dimension_GeV':1},
        {'name':'g','domain':'complex','units':'1','dimension_GeV':0}]
    d['points']=[{'id':'distinct','values':{n:{'real':x,'imag':y} for n,x,y in
        [('M',9,0),('m1',2,0),('m2',3,0),('g',1,2)]}}]
    converter=fixtures.Converter(symbols=['M','m1','m2','g'],value=5+6j)
    result=se.convert_result({'id':'width','symbol':'width','formula':'synthetic'},d,converter)
    assert ('evaluate',(9,2,3,1+2j)) in converter.calls
    assert result['variables']==d['variables'] and result['points'][0]['values']==d['points'][0]['values']
    assert (result['points'][0]['real'],result['points'][0]['imag'])==(5,6)
    assert result['physics_validated'] is False
