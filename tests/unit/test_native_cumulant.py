"""Supplied native-format controls, with synthetic source bytes and payloads."""
import copy,json,sys,types
from pathlib import Path
import pytest
from ravel.physics import native_cumulant as n, existing_events, rivet_export
from cumulant_fixture import mapping,payload,block

@pytest.fixture
def sample(tmp_path):
    requests=n.requests_for(mapping(tmp_path/'inputs'));p=tmp_path/'native.yoda';p.write_text(payload(requests));return p,requests

def task(requests,backend='rivet-built'):
    family=requests[0]['native_cumulant']
    t={'backend':backend,'routine':family['routine'],'events':'events.hepmc','metadata':'metadata.json','options':{},'observables':requests,'seed':19}
    if backend=='rivet-built':t.update(build_receipt='receipt.json',build_plan='plan.json',runtime={'python':'python','version':family['runtime_version']})
    else:t.update(source_root='source',runtime={'python':'python','executable':'rivet','build':'rivet-build','version':family['runtime_version'],'artifacts':['runtime'],'environment':{}})
    return t

def test_complete_supplied_sources_and_ordinary_dependencies(sample):
    p,req=sample;files=existing_events._native_derived_inputs(task(req),p.parent)
    assert all(Path(s['path']) in files for s in req[0]['native_cumulant']['sources'])
    assert Path(n.__file__) in files and Path(n.reader.__file__) in files

@pytest.mark.parametrize('backend',['rivet','rivet-built'])
def test_ordinary_admission_export_and_full_table(sample,tmp_path,monkeypatch,backend):
    p,req=sample;existing_events.validate(task(req,backend))
    objects={k:object() for k in n.reader.blocks(p.read_text())}
    objects['/RAW/_EVTCOUNT']=types.SimpleNamespace(sumW=lambda:-2.,sumW2=lambda:4.,numEntries=lambda:3.)
    monkeypatch.setitem(sys.modules,'yoda',types.SimpleNamespace(__version__='2.1.3',read=lambda _:objects))
    delivery=rivet_export.export(p,req);family=delivery['native_cumulant_transport']['families'][0]
    assert len(family['final_outputs'])==2 and len(family['raw_profiles'])==4
    assert delivery['native_cumulant_transport']['complete_native_text']==p.read_text()
    out=tmp_path/'tables';out.mkdir();n.write_report(delivery['observables'],out)
    assert len(json.loads((out/'native-cumulant-observables.json').read_text())['objects'])==2
    assert family['covariance'] is None

@pytest.mark.parametrize('attack',['missing_final','missing_raw','extra_final','geometry','negative_error','nonzero_discarded_error','wrong_path','wrong_columns','missing_flow'])
def test_complete_population_geometry_and_semantics_refuse(sample,attack):
    p,req=sample;objects=n.reader.blocks(p.read_text());family=req[0]['native_cumulant'];final=family['outputs'][0]['path'];raw=family['profiles'][0]['path']
    selected=raw if attack in ('missing_raw','missing_flow') else final
    old=objects[selected];body=old['body'];header='BEGIN YODA_'+old['type']+'_V3 '+selected+'\n';end='END YODA_'+old['type']+'_V3\n'
    if attack.startswith('missing_') and attack!='missing_flow':changed=''
    elif attack=='extra_final':changed=header+body+end+block('SCATTER2D','/'+family['routine']+'/extra',n.SCATTER_COLUMNS,[['1','0','0','2','0','0']])
    else:
        if attack=='geometry':body=body.replace('0.5 0.5 0.5','0.50001 0.5 0.5',1)
        elif attack=='negative_error':body=body.replace('0.0625','-0.0625',1)
        elif attack=='wrong_path':body=body.replace('Path: '+selected,'Path: /wrong',1)
        elif attack=='wrong_columns':body=body.replace('err1-','unknown',1)
        elif attack=='missing_flow':body=body.replace('-2 4 0 0 -1 0 0 1\n','',1)
        else:
            selected=family['outputs'][1]['path'];old=objects[selected];header='BEGIN YODA_SCATTER2D_V3 '+selected+'\n';end='END YODA_SCATTER2D_V3\n';body=old['body'].replace('-0.125 0 0','-0.125 1 0',1)
        changed=header+body+end
    text=p.read_text();p.write_text(text.replace('BEGIN YODA_'+old['type']+'_V3 '+selected+'\n'+old['body']+'END YODA_'+old['type']+'_V3\n',changed))
    with pytest.raises(ValueError):n.export_family(p,req)

@pytest.mark.parametrize('attack',['subset','duplicate','unit','axis','protocol','runtime','routine','source','operand','profile'])
def test_mapping_and_source_contract_refusals(sample,attack):
    p,req=sample;bad=copy.deepcopy(req)
    if attack=='subset':bad.pop()
    elif attack=='duplicate':bad.append(copy.deepcopy(bad[0]))
    elif attack=='unit':bad[0]['unit']='changed'
    elif attack=='axis':bad[0]['axes']=[{'name':'changed','unit':'1'}]
    else:
        for r in bad:
            f=r['native_cumulant']
            if attack in ('protocol','runtime','routine'):f[{'runtime':'runtime_version'}.get(attack,attack)]='changed'
            elif attack=='source':f['sources'][0]['sha256']='0'*64
            elif attack=='operand':f['outputs'][0]['operands']=['unknown']
            else:f['profiles'].pop()
    with pytest.raises(ValueError):
        if attack in ('runtime','routine'):
            t=task(req);t['observables']=bad;existing_events.validate(t)
        else:n.export_family(p,bad)

def test_native_nonfinite_scalars_masks_and_no_inferred_covariance(sample):
    p,req=sample;p.write_text(p.read_text().replace('-0.125','nan',1));out=n.export_family(p,req)
    obj=next(iter(out['observables'].values()));assert obj['bins'][0]['cells']['val2']['state']=='nan' and obj['covariance'] is None
    profile=next(iter(out['transport']['families'][0]['raw_profiles'].values()))
    assert profile['rows'][0]['flow']=='underflow' and profile['rows'][-1]['flow']=='overflow' and profile['rows'][1]['masked']

@pytest.mark.parametrize('mutation',['source','output','alias'])
def test_ending_custody_refuses(sample,monkeypatch,mutation):
    p,req=sample;original=n.parse_scatter;done=[]
    def changed(*args):
        result=original(*args)
        if not done:
            target=Path(req[0]['native_cumulant']['sources'][0]['path']) if mutation!='output' else p
            if mutation=='alias':raw=target.read_bytes();target.unlink();target.symlink_to(p)
            else:target.write_bytes(target.read_bytes()+b'\n')
            done.append(True)
        return result
    monkeypatch.setattr(n,'parse_scatter',changed)
    with pytest.raises(ValueError):n.export_family(p,req)

def test_two_supplied_contracts_change_identity_grid_population_and_format(tmp_path):
    outputs=[]
    for ident,count,edges,subsamples,weight,suffix in [('ANA_0001',2,[0,1,3],2,'',''),('ANA_0002',3,[0,2,5,9],3,'variation','[variation]')]:
        family=mapping(tmp_path/ident,ident,count,edges,subsamples,weight,suffix);family['study']['output']={'stem':ident+'-table','formats':['json'] if ident=='ANA_0001' else ['markdown']};req=n.requests_for(family);p=tmp_path/(ident+'.yoda');p.write_text(payload(req));out=n.export_family(p,req)
        assert list(out['observables'])==[r['path']+suffix for r in family['outputs']]
        assert len(out['transport']['families'][0]['raw_profiles'])==count*subsamples
        assert all(len(o['bins'])==len(edges)-1 for o in out['observables'].values())
        report_dir=tmp_path/(ident+'-report');report_dir.mkdir();files=n.write_report(out['observables'],report_dir)
        assert files==[ident+'-table.'+('json' if ident=='ANA_0001' else 'md')]
        outputs.append(out)
    assert outputs[0]!=outputs[1]
    with pytest.raises(n.NativeCumulantError) as caught:n.validate_request({'native_cumulant':{}})
    assert caught.value.reason=='missing_input'

def test_supplied_report_formats_cross_existing_renderer_with_table_metadata(sample,tmp_path):
    from ravel.plotting.science_figures import render
    p,req=sample
    for formats in (['json'],['markdown']):
        family=copy.deepcopy(req[0]['native_cumulant']);family['study']['output']={'stem':'supplied-table','formats':formats};requests=n.requests_for(family)
        result=n.export_family(p,requests);out=tmp_path/formats[0];out.mkdir();(out/'observables.json').write_text(json.dumps(result))
        report=render({'mode':'analyze','task':task(requests)},result,tmp_path,out)
        assert report['tables']==[{'stem':'supplied-table','files':['supplied-table.'+('json' if formats==['json'] else 'md')],'normalization':'Untransformed source-native cumulants and complete RAW operands; no inferred covariance'}]
