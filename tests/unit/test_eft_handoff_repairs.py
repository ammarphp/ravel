"""Desired-behavior projection of independent V1 counterexamples.
Inputs adapted unchanged from RS1's test_independent_algebra.py, SHA 43e9f46f85bd91e7809c1757090257a65c0b1ac52cdd856484d7c3059f173a7e.
No actual SFitter/Torch import or native call.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from ravel.physics import eft_conventions as e

def pin(p):
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def put(p,v):
    p.write_text(json.dumps(v,indent=2)+'\n');return pin(p)

def resave(tmp,r,p,m):
    r['polynomial']=put(tmp/'poly.json',p);r['map']=put(tmp/'map.json',m);put(tmp/'request.json',r)

def load_owner():
    spec=importlib.util.spec_from_file_location('eft_owner_helpers',Path(__file__).with_name('test_eft_conventions.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def full_native_fixture(tmp, reverse=False, tiny=False):
    owner=load_owner();mod,(request,docs,c)=owner.sf_fixture(tmp)
    rp,op,sp=owner.sf_transport(tmp,mod,c)
    rq=json.loads(Path(rp['path']).read_text());p=json.loads(Path(rq['polynomial']['path']).read_text());m=json.loads(Path(rq['map']['path']).read_text())
    axes=mod.BASIS;p['quadratic']=True
    p['observables'][0]['quadratic']=[dict(axes=[a,b],data=['1/'+'1'+'0'*400 if tiny and (i,j)==(0,1) else '1' if reverse and (i,j)==(0,1) else '0']) for i,a in enumerate(axes) for j,b in enumerate(axes) if i<=j]
    resave(tmp,rq,p,m);rp=pin(tmp/'request.json');result=e.compile_transport({'request':rp['path']},tmp);op=put(tmp/'transport-result.json',result)
    target=request['target']['eft'];target['quadratic']=True;target['mixed_pairs']=[[axes[1],axes[0]]] if reverse else []
    sem=json.loads(Path(sp['path']).read_text());sem['eft']['quadratic']=True;sem['eft']['mixed_pairs']=target['mixed_pairs'];sp=put(Path(sp['path']),sem)
    card=json.loads(Path(c['datacard']['path']).read_text())
    card['predictions'][0]['modifiers'] += [dict(name=x+'x'+x,data=[0.]) for x in axes]
    if reverse:card['predictions'][0]['modifiers'].append(dict(name=axes[1]+'x'+axes[0],data=[-1.]))
    cp=put(Path(c['datacard']['path']),card)
    docs['parameterization']['payload']['rows'][0]['modifiers']=card['predictions'][0]['modifiers']
    docs['conventions']['payload']=dict(semantic_manifest=sp,transport_request=rp,transport_result=op)
    docs['datacard']['payload'].update(datacard=cp,semantic_manifest=sp)
    from ravel.workflow.agent_graph import digest
    for phase in mod.w.PHASES:
        docs[phase]['target_sha256']=digest(request['target']);request['handoffs'][phase]=put(tmp/(phase+'.json'),docs[phase])
    return mod,request,result

def test_exact_nonzero_underflow_must_not_be_structurally_omitted(tmp_path):
    mod,request,result=full_native_fixture(tmp_path,tiny=True)
    with pytest.raises(ValueError,match='nonzero transported operator term omitted'):
        mod.w.ready_native(request,tmp_path)

def test_reversed_single_mixed_name_preserves_native_spelling(tmp_path):
    mod,request,result=full_native_fixture(tmp_path,reverse=True)
    before=Path(request['handoffs']['datacard']['path']).read_bytes()
    ready=mod.w.ready_native(request,tmp_path)
    assert ready['execution_authorized'] is False and ready['physics_validated'] is False
    assert Path(request['handoffs']['datacard']['path']).read_bytes()==before
    assert request['target']['eft']['mixed_pairs']==[[mod.BASIS[1],mod.BASIS[0]]]
