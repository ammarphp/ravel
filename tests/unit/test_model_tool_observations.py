"""Mocked native API transport only; actual MG5/UFO imports are prohibited."""
import json,sys,types
from pathlib import Path
import pytest
from ravel.physics import model_tool_bridge as bridge

def fake_runtime(monkeypatch,permutation,lorentz):
    class Model:
        def get(self,key):return {('external',):[]} if key=='parameters' else {'QED':1} if key=='order_hierarchy' else None
        def get_particle(self,pdg):return object()
    class Reader:
        def __init__(self,model):pass
        def set_parameters_and_couplings(self,*a,**k):pass
    class Evaluator:
        def __init__(self,*a,**k):self.full_model=Model()
        def evaluate_matrix_element(self,*a,**k):return {'m2':1.}
    class Process(dict):
        def nice_string(self):return 'synthetic process, no amplitude'
    checks=types.SimpleNamespace(MatrixElementEvaluator=Evaluator,ADDED_GLOBAL=[],
        clean_added_globals=lambda values:None,
        check_processes=lambda *a,**k:(permutation,[]),check_lorentz=lambda *a,**k:lorentz)
    modules={'models':types.SimpleNamespace(import_ufo=types.SimpleNamespace(import_model=lambda *a,**k:Model())),
        'models.model_reader':types.SimpleNamespace(ModelReader=Reader),
        'madgraph':types.SimpleNamespace(),
        'madgraph.core':types.SimpleNamespace(base_objects=types.SimpleNamespace(Leg=dict,LegList=list,Process=Process)),
        'madgraph.various':types.SimpleNamespace(process_checks=checks)}
    for name,mod in modules.items():monkeypatch.setitem(sys.modules,name,mod)
    monkeypatch.setattr(bridge,'validate_config',lambda c:c)
    monkeypatch.setattr(bridge.witness,'card_values',lambda text:{})
    monkeypatch.setattr(bridge.witness,'effective_card',lambda *a:None)
    monkeypatch.setattr(bridge,'_snapshot',lambda model:{'mock':True})

@pytest.mark.parametrize('permutation,lorentz',[
    ([],[]),([], [{'results':'pass'}]),([{'values':[1.]}],[{'results':'pass'}]),
    ([{'values':[1.]}],[]),([{'values':[1.]}],[{'results':None}])])
def test_nonvacuity_failure_retains_exact_partial_return(monkeypatch,tmp_path,permutation,lorentz):
    fake_runtime(monkeypatch,permutation,lorentz)
    card=tmp_path/'card';card.write_text('synthetic')
    c={'processes':[{'id':'mock_case','initial_pdgs':[-11,11],'final_pdgs':[6,-6],'orders':{'QED':2},'forbidden_pdgs':[]}],
        'seeds':[19],'energy_gev':1000.}
    request={'madgraph':str(tmp_path),'model':str(tmp_path),'card':str(card),'config':c,'source_sha256':'a'*64}
    with pytest.raises(ValueError,match='no nonvacuous'):bridge.native_worker(request,str(tmp_path))
    raw=json.loads((tmp_path/'native-case-observations.json').read_bytes())
    assert raw['completed'] is False and len(raw['cases'])==1
    row=raw['cases'][0]
    assert row['process_id']=='mock_case' and row['seed']==19 and row['phase']=='lorentz_completed'
    assert row['permutation']==permutation and row['lorentz']==lorentz
    assert not (tmp_path/'native-model-checks.json').exists()

def test_native_nonfinite_is_tagged_as_diagnostic_not_accepted_number():
    raw=bridge._diagnostic_value({'zero':0.,'bad':float('nan'),'complex':complex(1.,2.)})
    assert raw['bad']=={'nonfinite_float':'nan'} and raw['complex']=={'real':1.,'imag':2.}
    json.dumps(raw,allow_nan=False)

@pytest.mark.parametrize('value',[list(range(10001)),{str(i):i for i in range(10001)}])
def test_unbounded_diagnostic_population_refuses(value):
    with pytest.raises(ValueError,match='exceeds retained bound'):bridge._diagnostic_value(value)
