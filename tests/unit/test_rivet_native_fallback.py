"""Portable API transport controls; all YODA/runtime values fabricated."""
import json,sys
from types import SimpleNamespace
from copy import deepcopy
import pytest
from ravel.physics import existing_events as events,rivet_export as exporter
from ravel.plotting import science_figures

def request():return {'path':'/CUSTOM/count_SR','quantity_kind':'scalar_counter','axes':[],'representation':'integrated','normalization':'absolute','unit':'1'}
def task(backend):
 t={'backend':backend,'routine':'CUSTOM','events':'supplied.hepmc','metadata':'metadata.json','runtime':{'python':'python','version':'4.1.3'},'observables':[request()],'options':{},'seed':1}
 if backend=='rivet-built':t.update(build_receipt='build.json',build_plan='plan.json')
 else:t.update(source_root='source');t['runtime'].update(executable='rivet',build='rivet-build',artifacts=['native.so'],environment={})
 return t
@pytest.mark.parametrize('backend',['rivet','rivet-built'])
def test_native_scalar_admission(backend):events.validate(task(backend))
@pytest.mark.parametrize('field,value',[('axes',[{'name':'x','unit':'GeV'}]),('representation','differential'),('normalization','normalized')])
@pytest.mark.parametrize('backend',['rivet','rivet-built'])
def test_scalar_has_no_fabricated_geometry_or_normalization(backend,field,value):
 t=task(backend);t['observables'][0][field]=value
 with pytest.raises(ValueError):events.validate(t)
def test_duplicate_counter_refused():
 t=task('rivet');t['observables']*=2
 with pytest.raises(ValueError):events.validate(t)
class Counter:
 def __init__(self,w=-2,q=10,n=3):self.w,self.q,self.n=w,q,n
 def sumW(self):return self.w
 def sumW2(self):return self.q
 def numEntries(self):return self.n
class Estimate0D:
 def val(self):return 4.5
 def quadSum(self):return (-.2,.3)
@pytest.mark.parametrize('backend',['rivet','rivet-built'])
@pytest.mark.parametrize('final',[Counter,Estimate0D])
def test_actual_export_and_native_table_routes(tmp_path,monkeypatch,backend,final):
 q=request();path=q['path'];raw=Counter();objects={path:final(),'/RAW'+path:raw}
 monkeypatch.setitem(sys.modules,'yoda',SimpleNamespace(__version__='2.1.3',read=lambda p:objects))
 exported=exporter.export(tmp_path/'fixture.yoda',[q]);result=exported['observables']
 assert result[path]['raw_counter']=={'sumw':-2.,'sumw2':10.,'entries':3.}
 if final is Estimate0D:assert result[path]['bins'][0]['variance']is None
 (tmp_path/'observables.json').write_text(json.dumps({'observables':result}))
 rendered=science_figures.render({'mode':'analyze','task':task(backend)},{},tmp_path,tmp_path)
 assert rendered['status']=='passed'and rendered['figures']==[]
 assert len(rendered['tables'])==1
 table=json.loads((tmp_path/'scalar-counters.json').read_text());assert table['counters'][0]['observable']==result[path]
 assert table['physics_validated']is False
@pytest.mark.parametrize('raw',[None,Counter(q=-1),Counter(n=4)])
def test_missing_or_invalid_raw_moments_refuse(raw):
 with pytest.raises(ValueError):exporter._scalar_counter(request()['path'],Counter(),raw,request())
