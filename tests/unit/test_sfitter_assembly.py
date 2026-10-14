"""Protocol port controls; supplied numbers/maps are synthetic, no fit runs."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import eft_conventions as eft, sfitter_native
from ravel.workflow import sfitter_workflow as w, agent_graph, science, state_io
from test_sfitter_adapter import workflow_fixture, save, pin, BASIS, UP, specification


def complete_request(tmp_path, *, transported=False):
    request, docs, old_config = workflow_fixture(tmp_path)
    wanted = request['target']['observables'][0]
    wanted.update(bins=['low','middle','high'],representation='differential',normalization='normalized',unit='1/GeV')
    request['target']['observables'].append({'ID':'total','name':'synthetic_absolute',
        'bins':['total'],'representation':'integrated','normalization':'absolute','unit':'pb'})
    target=request['target']['eft'];target.update(quadratic=True,mixed_pairs=[[BASIS[0],BASIS[1]]])
    terms=w._terms(request['target'])
    obs=[];sm=[];poly=[]
    proof=docs['extraction']['sources'][0]
    for row in request['target']['observables']:
        n=len(row['bins'])
        extracted=copy.deepcopy(docs['extraction']['payload']['rows'][0])
        extracted.update(ID=row['ID'],name=row['name'],bin_widths=[2.,3.,4.] if n==3 else [1.])
        extracted['Meas']['data']=[float(i+2) for i in range(n)]
        extracted['Bkg']['data']=[0.]*n
        for location in ['Meas','Bkg']:
            for mod in extracted[location]['modifiers']:mod['data']=[float(mod['data'][0])]*n
        if n==3:extracted['bin_correlation']=[[1.,.2,0.],[.2,1.,.1],[0.,.1,1.]]
        obs.append(extracted)
        sm.append({'ID':row['ID'],'name':row['name'],'data':[float(i+3) for i in range(n)],
            'theory_modifiers':[{'type':'theo','name':'ScaleSim','label':'Theo','data':[5.]*n}],
            'perturbative_order':request['target']['perturbative_order'],'evidence':proof})
        mods=[{'name':name,'data':[(-1. if j==0 else .25) if name==BASIS[0] else
                 (2. if name==BASIS[0]+'x'+BASIS[1] else 0.) for j in range(n)]} for name in terms]
        poly.append({'ID':row['ID'],'name':row['name'],'modifiers':mods,
            'scan_evidence':proof,'coupling_sanity_evidence':proof,'fit_diagnostics':proof})
    for phase,rows in [('extraction',obs),('sm_template',sm),('parameterization',poly)]:
        docs[phase]['payload']['rows']=rows
    sem_path=Path(docs['conventions']['payload']['semantic_manifest']['path'])
    sem=json.loads(sem_path.read_text());sem['observables']=copy.deepcopy(request['target']['observables'])
    sem['eft'].update(quadratic=True,mixed_pairs=target['mixed_pairs'])
    if transported:
        source={'basis':'synthetic_SMEFT_coordinate_source','axes':BASIS,'flavour':target['flavour'],
            'coefficient_unit':'TeV^-2','lambda_unit':'TeV','lambda_gev':'1000',
            'renormalization_scale_gev':'1000','coefficient_kind':'real'}
        native={**source,'basis':'native_top_22'}
        polynomial={'schema_version':1,'convention':source,'quadratic':True,'observables':[],'sources':[proof]}
        for wanted,smrow,p in zip(request['target']['observables'],sm,poly):
            n=len(wanted['bins'])
            polynomial['observables'].append({**{k:wanted[k] for k in ('ID','name','bins','unit')},
                'sm':[str(v) for v in smrow['data']],
                'linear':[{'axis':x,'data':['-2' if x==BASIS[0] else '0']*n} for x in BASIS],
                'quadratic':[{'axes':[a,b],'data':['4' if (a,b)==(BASIS[0],BASIS[1]) else '0']*n}
                    for i,a in enumerate(BASIS) for b in BASIS[i:]]})
        box=[{'axis':x,'lower':'-2','upper':'2'} for x in BASIS]
        mapping={'schema_version':1,'source_convention':source,'target_convention':native,
            'direction':'source_coefficients=matrix*target_coefficients',
            'matrix':[['1/2' if i==j==0 else ('1' if i==j else '0') for j in range(22)] for i in range(22)],
            'source_domain':box,'target_domain':box,'rge_policy':'not_applied_same_scale','sources':[proof]}
        pp=save(tmp_path/'polynomial.json',polynomial);mp=save(tmp_path/'map.json',mapping)
        rp=tmp_path/'transport-request.json'
        save(rp,{'schema_version':1,'source':'Explicit synthetic supplied operator map, not a certified basis map',
            'polynomial':pp,'map':mp,'binary64_policy':'nearest_recorded','max_abs_coefficient_rounding':'1/1000000000000'})
        result=eft.compile_transport({'request':str(rp)},tmp_path)
        resultpin=save(tmp_path/'transport-result.json',result)
        for p,projection in zip(poly,result['binary64_projection']):
            values={tuple(v['axes']):v['data'] for v in projection['terms']}
            p['modifiers']=[{'name':term,'data':values[tuple(term.split('x'))]} for term in terms]
        sem['eft'].update(conversion='preconverted_source_bound_card',source_basis=source['basis'])
        docs['conventions']['payload'].update(transport_request=pin(rp),transport_result=resultpin)
    docs['conventions']['payload']['semantic_manifest']=save(sem_path,sem)
    for phase in w.PHASES[:4]:
        docs[phase]['target_sha256']=agent_graph.digest(request['target'])
        request['handoffs'][phase]=save(tmp_path/(phase+'.json'),docs[phase])
    return request,docs,old_config


def test_whole_native_assembly_preserves_correlations_signed_terms_and_all_bins(tmp_path):
    request,docs,_=complete_request(tmp_path)
    bundle=w.assemble_datacard(request,tmp_path)
    assert bundle['census']['observations']==2 and bundle['census']['bins']==4
    card=bundle['datacard']
    assert card['observations'][0]['bin_correlation']==docs['extraction']['payload']['rows'][0]['bin_correlation']
    assert card['observations'][0]['modifiers']==docs['sm_template']['payload']['rows'][0]['theory_modifiers']
    assert card['predictions'][0]['modifiers']==docs['parameterization']['payload']['rows'][0]['modifiers']
    assert card['predictions'][0]['modifiers'][0]['data'][0]<0
    assert len(card['predictions'][0]['modifiers'])==45
    assert bundle['semantic_manifest']['observables'][0]['unit']=='1/GeV'
    assert bundle['native_score']=='-Q' and bundle['native_profile']=='exp(-Q)'
    assert bundle['native_parser_roundtrip']=='not_executed' and bundle['execution_authorized'] is False


def test_actual_same_scale_operator_projection_reaches_native_bundle(tmp_path):
    request,docs,_=complete_request(tmp_path,transported=True)
    result=w.assemble_datacard(request,tmp_path)
    mods=result['datacard']['predictions'][0]['modifiers']
    assert mods[0]['data']==[-1.]*3
    assert mods[-1]['data']==[2.]*3
    assert result['semantic_manifest']['eft']['conversion']=='preconverted_source_bound_card'
    assert result['census']['population'][0]['native_normalizes_by_prediction_integral'] is True


@pytest.mark.parametrize('change',['unit','scale','omit_operator','pair','transport_value','missing_phase'])
def test_substantive_population_convention_disagreements_refuse(tmp_path,change):
    request,docs,_=complete_request(tmp_path,transported=True)
    if change in ('unit','scale','pair'):
        path=Path(docs['conventions']['payload']['semantic_manifest']['path']);sem=json.loads(path.read_text())
        if change=='unit':sem['observables'][0]['unit']='fb'
        elif change=='scale':sem['eft']['target_scale_gev']=2000.
        else:sem['eft']['mixed_pairs']=[]
        docs['conventions']['payload']['semantic_manifest']=save(path,sem)
        request['handoffs']['conventions']=save(tmp_path/'conventions.json',docs['conventions'])
    elif change in ('omit_operator','transport_value'):
        row=docs['parameterization']['payload']['rows'][0]
        if change=='omit_operator':row['modifiers'].pop()
        else:row['modifiers'][0]['data'][0]=999.
        request['handoffs']['parameterization']=save(tmp_path/'parameterization.json',docs['parameterization'])
    else:request['handoffs'].pop('sm_template')
    with pytest.raises(ValueError):w.assemble_datacard(request,tmp_path)


def test_real_host_graph_tool_requires_exact_consumed_inputs(tmp_path):
    from ravel.workflow.agent_host import AgentHost,HostFailure
    request,docs,_=complete_request(tmp_path)
    rp=save(tmp_path/'request.json',request);graph=w.assembly_graph(request,tmp_path,rp)
    assert len(graph['nodes'])==1 and graph['nodes'][0]['kind']=='tool'
    host=AgentHost(api_key='not-used',bound_roots=[str(tmp_path),str(UP)])
    node=graph['nodes'][0];inputs=node['inputs']
    control=SimpleNamespace(cancelled=lambda:False,call=lambda action,kind,request,operation:operation())
    value=host.execute(node,{'request_id':'actual_tool_control','packet':None,'input_artifacts':inputs},control)
    assert value['value']==w.assemble_datacard(request,tmp_path)
    bad=copy.deepcopy(node);bad['inputs']=bad['inputs'][:-1]
    with pytest.raises(HostFailure):host.execute(bad,{'request_id':'bad','packet':None,'input_artifacts':bad['inputs']},control)


def test_actual_ordinary_graph_records_tool_assembly_without_model_transport(tmp_path):
    from ravel.workflow.agent_host import AgentHost
    request,_,_=complete_request(tmp_path)
    request_pin=save(tmp_path/'request.json',request)
    spec=w.assembly_graph(request,tmp_path,request_pin)
    root=tmp_path/'assembly-graph';agent_graph.create(root,spec)
    status=agent_graph.execute(root,AgentHost(api_key='not-used',bound_roots=[str(tmp_path),str(UP)]),workers=1)
    _,state=agent_graph._load(root)
    node=state['nodes']['assemble_native_card']
    result=agent_graph._result(root,node['result'])['result']['value']
    assert node['status']=='completed' and result['datacard']['predictions'][0]['modifiers'][0]['data'][0]<0
    assert state['usage']['calls']==1 and state['usage']['reserved_output_tokens']==0
    assert result['execution_authorized'] is False and result['native_parser_roundtrip']=='not_executed'


@pytest.mark.parametrize('kind',['semantic','config','added_file','ancestor'])
def test_every_emitted_bundle_member_keeps_original_ending_commitment(tmp_path,monkeypatch,kind):
    request,_,old=complete_request(tmp_path)
    settings={k:old[k] for k in ('source','trusted_upstream_python','runtime','max_seconds','max_ram_mib','max_export_bytes')}
    settings['schema_version']=1;settings_pin=save(tmp_path/'settings.json',settings)
    out=tmp_path/'bundle';original=w.assemble_datacard;calls=0
    def drift(*args,**kwargs):
        nonlocal calls
        result=original(*args,**kwargs);calls+=1
        if calls==2:
            if kind in ('semantic','config'):
                p=out/('semantic.json' if kind=='semantic' else 'native-config.json')
                p.write_bytes(p.read_bytes()+b'\n')
            elif kind=='added_file':(out/'unbound.json').write_text('{}\n')
            else:
                (out/'data').rename(out/'moved-data');(out/'data').symlink_to(out/'moved-data',target_is_directory=True)
        return result
    monkeypatch.setattr(w,'assemble_datacard',drift)
    with pytest.raises(ValueError):w.materialize_datacard(request,tmp_path,out,native_settings=settings_pin)
    assert not (out/'assembly-receipt.json').exists()


def test_public_materialization_and_native_planning_use_generated_card(tmp_path):
    request,docs,old=complete_request(tmp_path)
    settings={key:old[key] for key in ['source','trusted_upstream_python','runtime','max_seconds','max_ram_mib','max_export_bytes']}
    settings['schema_version']=1;sp=save(tmp_path/'settings.json',settings)
    rp=tmp_path/'request.json';save(rp,request);out=tmp_path/'assembled'
    assert w.main(['materialize','--request',str(rp),'--output',str(out),'--native-settings',str(tmp_path/'settings.json')])==0
    receipt=json.loads((out/'assembly-receipt.json').read_text())
    config=json.loads(Path(receipt['native_config']['path']).read_text())
    assert config['operation']=='fit' and config['purpose']=='supplied_full_study' and config['vectors']==[]
    card=Path(config['datacard']['path']);assert json.loads(card.read_text())==w.assemble_datacard(request,tmp_path)['datacard']
    assert w.ready_native(json.loads((out/'workflow.json').read_text()),out)==receipt['native_input']
    actual_inputs=sfitter_native.inputs(receipt['native_task'],out)
    assert card in actual_inputs and Path(config['runtime']['assets'][0]['path']) in actual_inputs
    # Actual ordinary public planning only; no approval, worker or fit.
    spec=specification(receipt['native_task']);save(tmp_path/'study.json',spec)
    science.plan(tmp_path/'ordinary-plan',tmp_path/'study.json')
    assert (tmp_path/'ordinary-plan/inputs/science-plan.json').is_file()
    assert not (tmp_path/'ordinary-plan/inputs/science-approval.json').exists()


@pytest.mark.parametrize('path_kind',['existing','dotdot','source','symlink'])
def test_fresh_output_does_not_overwrite_source_or_existing_bundle(tmp_path,path_kind):
    request,docs,_=complete_request(tmp_path)
    if path_kind=='existing':out=tmp_path/'old';out.mkdir()
    elif path_kind=='dotdot':out=tmp_path/'different/../assembled'
    elif path_kind=='source':out=UP/'new-derived-data'
    else:
        link=tmp_path/'alias';link.symlink_to(tmp_path,target_is_directory=True);out=link/'assembled'
    with pytest.raises(ValueError):w.materialize_datacard(request,tmp_path,out)
    assert not (tmp_path/'assembled').exists() and not (UP/'new-derived-data').exists()


def test_ending_input_change_retains_draft_but_no_completion_receipt(tmp_path,monkeypatch):
    request,docs,_=complete_request(tmp_path)
    original=state_io.atomic_json
    def mutate(path,value):
        original(path,value)
        if Path(path).name=='datacard-handoff.json':
            evidence=Path(docs['extraction']['sources'][0]['path']);evidence.write_text('INTENTIONAL TEST MUTATION')
    monkeypatch.setattr(state_io,'atomic_json',mutate)
    out=tmp_path/'failed-construction'
    with pytest.raises(ValueError):w.materialize_datacard(request,tmp_path,out)
    assert (out/'data/assembled.json').is_file() and not (out/'assembly-receipt.json').exists()


def test_relative_semantic_evidence_preserves_original_bytes_and_resolution(tmp_path):
    request,docs,_=complete_request(tmp_path)
    sem_path=Path(docs['conventions']['payload']['semantic_manifest']['path'])
    sem=json.loads(sem_path.read_text())
    for pinlist in (sem['sources'],sem['eft']['evidence']):
        for ref in pinlist:ref['path']=Path(ref['path']).name
    docs['conventions']['payload']['semantic_manifest']=save(sem_path,sem)
    request['handoffs']['conventions']=save(tmp_path/'conventions.json',docs['conventions'])
    original_bytes=sem_path.read_bytes()
    out=tmp_path/'relative-assembly'
    receipt=w.materialize_datacard(request,tmp_path,out)
    assert (out/'semantic.json').read_bytes()==original_bytes==sem_path.read_bytes()
    assert receipt['native_input']['semantic_manifest']==pin(sem_path)
    assert w.ready_native(json.loads((out/'workflow.json').read_text()),out)==receipt['native_input']


def test_run_template_is_copied_from_authenticated_bytes_without_later_text_read(tmp_path,monkeypatch):
    request,docs,_=complete_request(tmp_path)
    original=Path.read_text;template=UP/'sfitter/params/top_fit.yaml'
    def no_second_template_read(path,*args,**kwargs):
        if path==template:raise AssertionError('construction must use authenticated captured run bytes')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',no_second_template_read)
    bundle=w.assemble_datacard(request,tmp_path)
    assert 'datacard: data/assembled.json' in bundle['run_card']
    assert bundle['semantic_source_text'].encode()==Path(bundle['semantic_source']['path']).read_bytes()
