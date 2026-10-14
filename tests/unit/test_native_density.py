"""Portable transport controls, no native/YODA execution or physics inference."""
import re
from pathlib import Path
import importlib.util,hashlib,json,copy,types,sys
import pytest
B=Path(__file__).parent

def load(name,filename):
    s=importlib.util.spec_from_file_location(name,B/filename);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
from ravel.physics import native_density as n
NAME='/SYN_9052_I1239/d01-x01-y01';RAW='/RAW'+NAME

def estimate(name=NAME,rows=None,labels=('stats',),edges='[100,116,134]'):
    rows=rows or ['nan --- ---','1.25 -.1 .2','0 --- ---','-nan --- ---']
    columns=['value']
    for i,label in enumerate(labels,1):columns+=['totalDn','totalUp'] if label=='' else [f'errDn({i})',f'errUp({i})']
    return f'BEGIN YODA_ESTIMATE1D_V3 {name}\nPath: {name}\nScaledBy: 3.84615384615384637e-01\nTitle: native density\n---\nEdges(A1): '+edges+'\n'+('ErrorLabels: '+json.dumps(list(labels))+'\n' if labels else '')+'# '+' '.join(columns)+'\n'+'\n'.join(rows)+'\nEND YODA_ESTIMATE1D_V3\n\n'

def histogram(name=RAW,edges='[100,116,134]'):
    return f'BEGIN YODA_HISTO1D_V3 {name}\nPath: {name}\n---\nEdges(A1): '+edges+'\n# sumW sumW2 sumW(A1) sumW2(A1) numEntries\n2 4 180 16200 1\n-1 5 -110 -12100 3\n0 0 0 0 1\n1 1 200 40000 1\nEND YODA_HISTO1D_V3\n'

@pytest.fixture
def sample(tmp_path):
    source=tmp_path/'analysis.cc';source.write_text('book(histograms, ybins);\nscale(histograms, xs / W);\ndivByGroupWidth(histograms);\n')
    api=tmp_path/'BinnedDbn.h';api.write_text('mkEstimate(divbyvol=true);\n')
    def fact(p,a,b):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'first_line':a,'last_line':b,'text':'\n'.join(p.read_text().splitlines()[a-1:b])}
    request={'path':NAME,'axes':[{'name':'jet_pT','unit':'GeV'}],'representation':'native','normalization':'absolute','unit':'pb/GeV','quantity_kind':'native_density_estimate','native_density':{'operation':'histogram_density','source':fact(source,2,3),'source_dependencies':[fact(source,1,1),fact(api,1,1)],'native_error_semantics':'Native labeled marginal errors; no event-group covariance.','raw_histogram_path':RAW,'integrated_unit':'pb','raw_weight_unit':'1','normalization_expression':'xs_pb/W divided by group_width; native finite density perGeV','group_width':{'axis':'absolute_rapidity','low':'0.0','high':'0.5','unit':'1','operation':'divide_by_group_width'},'flow_policy':'retain_all','group_covariance':'not_supplied'}}
    path=tmp_path/'native.yoda';path.write_text(estimate()+histogram())
    return path,request

def test_untransformed_nonuniform_density_with_signed_raw_and_full_flows(sample):
    p,r=sample;v=n.transport(p,r)
    assert [b['value'] for b in v['bins']]==[1.25,0]
    assert v['bins'][0]['error_low']==.1 and v['bins'][0]['error_high']==.2
    assert all(b['variance'] is None and b['integrated_sumw'] is None and b['entries'] is None for b in v['all_native_bins'])
    assert len(v['all_native_bins'])==4 and len(v['raw_histogram']['bins'])==4
    assert v['raw_histogram']['bins'][1]['sumw']==-1 and v['raw_histogram']['bins'][1]['sumw2']==5
    assert v['raw_histogram']['bins'][1]['coordinate_squared_sumw']==-12100
    assert v['raw_histogram']['bins'][0]['sumw']==2 and v['raw_histogram']['bins'][-1]['sumw']==1
    assert v['all_native_bins'][0]['value_token']=='nan' and v['all_native_bins'][-1]['value_token']=='-nan'
    assert v['bins'][1]['status']=='undefined_native_errors' and v['bins'][1]['error_low'] is None
    assert v['covariance'] is None and not v['variance_from_error_bars'] and not v['integral_reconstructed']
    assert v['yoda_text_sha256']==hashlib.sha256(p.read_bytes()).hexdigest() and v['native_final_path']==NAME and v['native_raw_path']==RAW


def test_multiple_labels_do_not_infer_quadrature_or_group_covariance(sample):
    p,r=sample;p.write_text(estimate(rows=['nan --- --- --- ---','1.25 -.1 .2 -.3 .4','0 -0 +0 --- ---','nan --- --- --- ---'],labels=('stats','scale'))+histogram())
    v=n.transport(p,r);assert v['bins'][0]['error_low'] is None and v['bins'][0]['error_high'] is None
    assert v['bins'][1]['native_errors'][0]['down_token']=='-0' and v['bins'][1]['native_errors'][0]['up_token']=='+0'
    assert len(v['bins'][0]['native_errors'])==2 and v['covariance'] is None


def test_dimensionless_group_and_explicit_nontrivial_group_units(sample):
    _,r=sample;n.validate_request(r)
    r['native_density']['group_width']['unit']='GeV';r['unit']='pb/GeV/GeV';n.validate_request(r)
    r['native_density']['group_width']=None;r['unit']='pb/GeV';n.validate_request(r)

@pytest.mark.parametrize('mutation',[
 lambda r:r.update(quantity_kind='native_derived_estimate'),lambda r:r.update(representation='differential'),lambda r:r.update(normalization='normalized'),lambda r:r.update(unit='pb/TeV'),lambda r:r.update(axes=r['axes']*2),lambda r:r['native_density'].update(operation='ratio'),lambda r:r['native_density'].update(raw_histogram_path=NAME),lambda r:r['native_density'].update(flow_policy='drop'),lambda r:r['native_density'].update(group_covariance='independent'),lambda r:r['native_density'].update(source_dependencies=[]),lambda r:r['native_density']['group_width'].update(high='0.0'),lambda r:r['native_density']['group_width'].update(low=True),lambda r:r['native_density']['group_width'].update(high='nan'),lambda r:r['native_density']['group_width'].update(high='1e1000000'),lambda r:r['native_density']['group_width'].update(high='1e-1000000')])
def test_contract_refusals(sample,mutation):
    _,r=sample;mutation(r)
    with pytest.raises(n.Error):n.validate_request(r)

@pytest.mark.parametrize('mutation',[
 lambda s:s.replace('Path: '+NAME,'Path: /wrong',1),lambda s:s.replace('1.25 -.1 .2','1.25 +.1 .2',1),lambda s:s.replace('0 --- ---\n','',1),lambda s:s.replace('Edges(A1): [100,116,134]','Edges(A1): [100,117,134]',1),lambda s:s.replace('-1 5 -110','-1 -5 -110'),lambda s:s.replace('errDn(1) errUp(1)','totalDn totalUp',1),lambda s:s.replace('END YODA_ESTIMATE1D_V3','END YODA_HISTO1D_V3',1),lambda s:s+histogram(),lambda s:s.replace('1.25 -.1 .2','inf -.1 .2',1),lambda s:s.replace('1.25 -.1 .2','1.25 --- .2',1)])
def test_full_native_population_refusals(sample,mutation):
    p,r=sample;p.write_text(mutation(p.read_text()))
    with pytest.raises(n.Error):n.transport(p,r)


def test_decimal_distinction_not_hidden_by_binary64_edge_rounding(sample):
    p,r=sample;p.write_text(estimate(edges='[0.1,0.2,0.3]')+histogram(edges='[0.100000000000000001,0.2,0.3]'))
    with pytest.raises(n.Error,match='literal decimal geometry'):n.transport(p,r)


def test_sources_are_real_inputs_and_source_excerpt_or_alias_changes_refuse(sample,tmp_path):
    p,r=sample;files=n.inputs(r);assert len(files)==4
    source=Path(r['native_density']['source_dependencies'][1]['path']);source.write_text('changed\n')
    with pytest.raises(n.Error,match='hash'):n.transport(p,r)
    source.write_text('mkEstimate(divbyvol=true);\n');r['native_density']['source']['text']='other normalization'
    with pytest.raises(n.Error,match='excerpt'):n.transport(p,r)


def test_regular_native_input_required(sample,tmp_path):
    p,r=sample;alias=tmp_path/'alias.yoda';alias.symlink_to(p)
    with pytest.raises(n.Error,match='regular'):n.transport(alias,r)

@pytest.fixture
def integrated(monkeypatch):
    import ravel.physics as physics
    monkeypatch.setitem(sys.modules,'ravel.physics.native_density',n);monkeypatch.setattr(physics,'native_density',n,raising=False)
    from importlib import import_module
    exporter=import_module('ravel.physics.rivet_export');adapter=import_module('ravel.physics.existing_events');figures=import_module('ravel.plotting.science_figures')
    monkeypatch.setitem(sys.modules,'ravel.physics.rivet_export',exporter);monkeypatch.setattr(physics,'rivet_export',exporter,raising=False)
    return exporter,adapter,figures

def task(r,backend='rivet-built'):
    t={'backend':backend,'routine':'SYN_9052_I1239','events':'events.hepmc','metadata':'metadata.json','runtime':{'python':'python','version':'4.1.3'},'options':{},'observables':[r],'seed':1}
    if backend=='rivet-built':t.update(build_plan='build-plan.json',build_receipt='build-receipt.json')
    else:
        t['source_root']='source';t['runtime'].update(executable='rivet',build='build',artifacts=[{'path':'lib','sha256':'0'*64}],environment={})
    return t

@pytest.mark.parametrize('backend',['rivet','rivet-built'])
def test_private_real_admission_inputs_export_render_routes(sample,tmp_path,monkeypatch,integrated,backend):
    p,r=sample;exporter,adapter,figures=integrated;objects={NAME:object(),RAW:object()}
    monkeypatch.setitem(sys.modules,'yoda',types.SimpleNamespace(__version__='2.1.3',read=lambda _:objects))
    t=task(r,backend);adapter.validate(t)
    if backend=='rivet-built':monkeypatch.setattr(adapter,'_built_inputs',lambda *_:[])
    else:
        monkeypatch.setattr(adapter,'_grounding_inputs',lambda *_:[])
        # Complete runtime acquisition is outside the pure integration fixture.
    files=adapter._native_derived_inputs(t,tmp_path)
    assert Path(r['native_density']['source']['path']) in files and Path(r['native_density']['source_dependencies'][1]['path']) in files
    assert any(f.name=='native_density.py' for f in files) and any(f.name=='native_estimate.py' for f in files) and any(f.name=='rivet_export.py' for f in files)
    v=exporter.export(p,[r]);out=tmp_path/'output';out.mkdir();(out/'observables.json').write_text(json.dumps(v));monkeypatch.setitem(sys.modules,'matplotlib',None)
    report=figures.render({'mode':'analyze','task':t},{},tmp_path,out)
    assert report['status']=='passed' and report['figures']==[]
    exact=json.loads((out/'native-density-estimates.json').read_text());assert exact['estimates'][0]['observable']==v['observables'][NAME]
    table=(out/'native-density-estimates.md').read_text();assert 'pb/GeV' in table and 'underflow' in table and 'overflow' in table and '-nan' in table and '---' in table
    assert len([line for line in table.splitlines() if re.match(r'\| /[A-Z][A-Z0-9]*_\d{4}_I\d+', line)])==4
    assert exact['covariance'] is None and exact['physics_validated'] is False
    t['observables'].append(r)
    with pytest.raises(ValueError,match='duplicate'):adapter.validate(t)


def test_private_export_version_and_report_fabrication_refuse(sample,tmp_path,monkeypatch,integrated):
    p,r=sample;exporter,_,_=integrated;monkeypatch.setitem(sys.modules,'yoda',types.SimpleNamespace(__version__='2.1.4',read=lambda _:{NAME:object(),RAW:object()}))
    with pytest.raises(ValueError,match='2.1.3'):exporter.export(p,[r])
    v=n.transport(p,r);v['all_native_bins'][1]['variance']=.01
    with pytest.raises(n.Error,match='moments'):n.write_report({NAME:v},tmp_path)
