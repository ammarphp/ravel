"""Portable native categorical parser and ordinary product routes; mocked native namespace, no native job."""
import copy,hashlib,json,sys,types
from pathlib import Path
import pytest
from ravel.physics import native_categorical as n,existing_events,rivet_export
from ravel.plotting import science_figures
HERE=Path(__file__).resolve().parent
@pytest.fixture
def sample(tmp_path):
 root=tmp_path.resolve();source=root/'analysis.cc';source.write_text('void finalize() { divide(numerator, denominator, ratio); }\n')
 grammar=root/'ReaderUtils.h';grammar.write_text('Axis<string>: literal categories; index0 OTHER; axis1 fastest.\n')
 def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'first_line':1,'last_line':1,'text':p.read_text().rstrip('\n')}
 path='/ANALYSIS/ratio';raw='/RAW'+path;operand='/RAW/ANALYSIS/TMP/numerator'
 def block(kind,path,columns,rows,errors=True):
  return '\n'.join([f'BEGIN YODA_{kind}_V3 {path}',f'Path: {path}','---','Edges(A1): ["0.125", "1.250000e-01"]']+(['ErrorLabels: [""]'] if errors else [])+['# '+columns,*rows,f'END YODA_{kind}_V3',''])
 text=block('BINNEDESTIMATE<S>',path,'value totalDn totalUp',['nan --- ---','0.75 -0.2 0.3','1 -0 0'])+block('BINNEDESTIMATE<S>',raw,'value totalDn totalUp',['nan --- ---']*3)+block('BINNEDHISTO<S>',operand,'sumW sumW2 numEntries',['0 0 2','-2 4 1','0 8 2'],False)
 yoda=root/'native.yoda';yoda.write_text(text)
 request={'path':path,'axes':[{'name':'native literal category','unit':'1','native_type':'S'}],'representation':'native','normalization':'absolute','unit':'1','quantity_kind':'native_categorical','native_categorical':{'source':pin(source),'source_dependencies':[pin(grammar)],'final_native_type':'BINNEDESTIMATE<S>','raw_objects':[{'id':'ratio_raw','path':raw,'role':'raw_estimate','native_type':'BINNEDESTIMATE<S>','unit':'1'},{'id':'numerator','path':operand,'role':'raw_operand','native_type':'BINNEDHISTO<S>','unit':'1'}],'source_finalization':'Source division; native marginal errors remain separate from group covariance.','native_error_semantics':'Source native signed asymmetric marginal errors, undefined tokens preserved.','flow_policy':'retain_all','group_covariance':'not_supplied','native_weight':{'native':'','suffix':''}}}
 return yoda,request

def task(request,backend='rivet-built'):
 base={'backend':backend,'routine':'ANALYSIS','events':'events.hepmc','metadata':'metadata.json','options':{},'observables':[request],'seed':1}
 if backend=='rivet-built':base.update(build_plan='plan.json',build_receipt='receipt.json',runtime={'python':'python','version':'4.1.3'})
 else:base.update(source_root='source',runtime={'python':'python','executable':'rivet','build':'rivet-build','version':'4.1.3','artifacts':[{'path':'runtime','sha256':'0'*64}],'environment':{}})
 return base

def test_all_private_route_imports_exclusive():
 for module in (n,existing_events,rivet_export,science_figures):assert Path(module.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[2] / 'src')

@pytest.mark.parametrize('backend',['rivet','rivet-built'])
def test_real_admission_export_full_states_and_portable_table(sample,tmp_path,monkeypatch,backend):
 path,request=sample;existing_events.validate(task(request,backend))
 generic=n.validate_request(request);objects={o['path']:object() for o in generic['objects']}
 counter=types.SimpleNamespace(sumW=lambda:2.,sumW2=lambda:6.,numEntries=lambda:3.)
 objects['/RAW/_EVTCOUNT']=counter
 yoda=types.SimpleNamespace(__version__='2.1.3',read=lambda _:objects);monkeypatch.setitem(sys.modules,'yoda',yoda)
 exported=rivet_export.export(path,[request]);obj=exported['observables'][request['path']]
 assert obj['all_native_rows'][0]['tokens']['value']=='nan' and obj['all_native_rows'][0]['flow']
 assert obj['bins'][0]['coordinates'][0]['category']=='0.125';assert obj['bins'][1]['coordinates'][0]['category']=='1.250000e-01'
 assert obj['raw_objects'][1]['object']['rows'][2]['primitive_moments']=={'sumW':0.,'sumW2':8.,'numEntries':2.}
 assert obj['covariance'] is None and exported['event_counters']['/RAW/_EVTCOUNT']=={'sumw':2.,'sumw2':6.,'entries':3.}
 out=tmp_path/'output';out.mkdir();(out/'observables.json').write_text(json.dumps({'observables':{request['path']:obj}}));monkeypatch.setitem(sys.modules,'matplotlib',None)
 rendered=science_figures.render({'mode':'analyze','task':task(request,backend)},{},tmp_path,out)
 assert rendered['status']=='passed' and rendered['figures']==[]
 report=json.loads((out/'native-categorical-observables.json').read_text());assert report['objects'][0]['observable']==obj
 table=(out/'native-categorical-observables.md').read_text();assert all(token in table for token in ('nan','otherflow','1.250000e-01'))
 yoda.__version__='2.1.4'
 with pytest.raises(ValueError,match='2.1.3'):rivet_export.export(path,[request])

def test_real_input_pins_and_source_mutation_refusal(sample):
 path,request=sample;files=existing_events._native_derived_inputs(task(request),path.parent)
 for source in [request['native_categorical']['source'],*request['native_categorical']['source_dependencies']]:assert Path(source['path']) in files
 assert Path(n.__file__).resolve() in files and Path(rivet_export.__file__).resolve() in files
 Path(request['native_categorical']['source']['path']).write_text('changed')
 with pytest.raises(ValueError,match='digest'):existing_events._native_derived_inputs(task(request),path.parent)

@pytest.mark.parametrize('edit',[lambda r:r.update(normalization='normalized'),lambda r:r['axes'][0].update(unit='GeV'),lambda r:r['native_categorical'].update(group_covariance='inferred'),lambda r:r['native_categorical']['raw_objects'][0].update(role='raw_operand'),lambda r:r['native_categorical'].update(native_weight={'native':'up','suffix':'[up]'})])
def test_no_native_statistical_or_numeric_label_reinterpretation(sample,edit):
 _,request=sample;bad=copy.deepcopy(request);edit(bad)
 with pytest.raises(ValueError):existing_events.validate(task(bad))

def test_full_path_and_mask_identity_control(sample):
 path,request=sample;text=path.read_text().replace('Path: /ANALYSIS/ratio','Path: /OTHER',1);path.write_text(text)
 with pytest.raises(ValueError,match='identity'):n.export_quantity(path,request)

def test_duplicate_output_refused(sample):
 _,request=sample;t=task(request);t['observables'].append(request)
 with pytest.raises(ValueError,match='duplicate'):existing_events.validate(t)


def test_finite_masked_value_retains_tokens_but_is_explicit_table_state(sample,tmp_path):
 path,request=sample;text=path.read_text().replace('---\nEdges(A1):','---\nMaskedBins: [1]\nEdges(A1):',1);path.write_text(text)
 obj=n.export_quantity(path,request);row=obj['all_native_rows'][1]
 assert row['value']==.75 and row['masked'] is True and row['status']=='masked_defined'
 assert row['tokens']=={'value':'0.75','totalDn':'-0.2','totalUp':'0.3'}
 out=tmp_path/'table';out.mkdir();n.write_report({request['path']:obj},out)
 table=(out/'native-categorical-observables.md').read_text();assert '| Masked | Status |' in table and '| True | masked_defined |' in table
 assert obj['native_weight_identity_observed'] is False
