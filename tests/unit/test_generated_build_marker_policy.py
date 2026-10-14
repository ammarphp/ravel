"""Synthetic declaration/census controls; real template authentication is separate."""
from copy import deepcopy
import hashlib
from pathlib import Path
import pytest
from ravel.workflow import validation_io as v, execution as e

TARGET='outputs/attempt-1/finite-integrals/native/finite_integral/finite_integral_integral/codegen'
SOURCE_SHA='eaea4f42389af4011cb858ded7dc41f155958ba031e9240f24e86100ca97f9fa'

def fixture(tmp):
    source=tmp/'pySecDec/code_writer/templates/make_package/Makefile'
    pin={'path':str(source),'sha256':SOURCE_SHA,'size':100}
    item={'path':TARGET,'role':'generated_build_marker_family','marker_class':'pysecdec166_sector_codegen_done','source':pin,'max_sectors':2}
    capture={str(source):{'kind':'file','files':[{'name':'.','size':100,'sha256':SOURCE_SHA}]}}
    return source,item,capture

def rows():return [{'name':'sector1.h','size':9},{'name':'sector1.info','size':4},{'name':'sector1.done','size':0},{'name':'sector1.d','size':3}]

def test_exact_declaration_needs_no_future_output_or_live_source(tmp_path):
    src,item,snapshot=fixture(tmp_path)
    assert v._generated_sector_declaration(item,snapshot,[str(src)],tmp_path,True)==item['source']
    assert not src.exists()

@pytest.mark.parametrize('kind',['directory','missing','wrong_hash','not_declared','bool_size'])
def test_captured_singleton_source_identity_is_required(tmp_path,kind):
    src,item,snapshot=fixture(tmp_path);paths=[str(src)]
    if kind=='directory':snapshot[str(src)]['kind']='directory'
    elif kind=='missing':snapshot={}
    elif kind=='wrong_hash':snapshot[str(src)]['files'][0]['sha256']='0'*64
    elif kind=='not_declared':paths=[]
    elif kind=='bool_size':snapshot[str(src)]['files'][0]['size']=True
    with pytest.raises(ValueError):v._generated_sector_declaration(item,snapshot,paths,tmp_path,True)

@pytest.mark.parametrize('kind',['missing_header','missing_info','missing_stamp','nonempty_stamp','foreign_empty','leading_zero','duplicate','bool_size','exceeds'])
def test_exact_family_census_refuses_broader_empty_role(tmp_path,kind):
    src,item,snapshot=fixture(tmp_path);r=rows()
    if kind.startswith('missing_'):r=[x for x in r if x['name']!='sector1.'+{'missing_header':'h','missing_info':'info','missing_stamp':'done'}[kind]]
    elif kind=='nonempty_stamp':r[2]['size']=1
    elif kind=='foreign_empty':r.append({'name':'unlisted.empty','size':0})
    elif kind=='leading_zero':r[2]['name']='sector01.done'
    elif kind=='duplicate':r.append(deepcopy(r[0]))
    elif kind=='bool_size':r[0]['size']=True
    elif kind=='exceeds':item['max_sectors']=1;r.extend([{'name':'sector2.h','size':9},{'name':'sector2.info','size':4},{'name':'sector2.done','size':0}])
    with pytest.raises(ValueError):v._generated_sector_indices(item,r)

def test_family_does_not_waive_empty_scientific_json(tmp_path,monkeypatch):
    src,item,snapshot=fixture(tmp_path);root=tmp_path/TARGET;root.mkdir(parents=True)
    for r in rows():(root/r['name']).write_bytes(b'x'*r['size'])
    (tmp_path/'outputs/attempt-1/result.json').write_bytes(b'')
    # This test isolates generic output admission. The real producer bytes are
    # authenticated by the separate directed upstream-source controls.
    monkeypatch.setattr(v,'_source_pin_bytes',lambda *a,**k:b'synthetic custody stand-in')
    pol={'schema_version':1,'allow_empty_directory_members':[item]}
    with pytest.raises(ValueError,match='empty output'):e.snapshot(tmp_path,['outputs/attempt-1'],outputs=True,output_policy=pol,input_snapshot=snapshot,input_paths=[str(src)])
