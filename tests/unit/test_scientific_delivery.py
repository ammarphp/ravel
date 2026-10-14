"""Connected fabricated primary→whole portfolio→typed report/ordinary route controls.
No live HTTP, publication render, provider/model/native/fit or governed study.
"""
from copy import deepcopy
import hashlib,io,json
from pathlib import Path
import pytest
from ravel.physics import scientific_delivery as op
from ravel.workflow import route_prompt,task_completion,science
from ravel.workflow.state_io import atomic_json

PROMPT="Consider a model (say HVT) with a Z'->WW. Construct a summary plot of ATLAS+CMS searches sensitive for m(Zprime)<500 GeV."


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if type(value) is str else json.dumps(value,allow_nan=False)+'\n')
    return op.pin(path,path.read_bytes())


def parent(base,prompt=PROMPT):
    c=route_prompt.route(prompt);r=task_completion.initial_requirements(prompt)
    r['assignments']=[{'id':'delivery','purpose':'Complete supplied source portfolio; no physical claim.',
                      'coverage':[{'obligation_id':'original-request','criteria':{'request':prompt}}]}]
    c['task_requirements']=r
    return {'contract':write(base/'parent/inputs/task_contract.json',c),'assignment_id':'delivery'}


def basis(model='HVT',production='qqA'):
    return {'model':model,'resonance':'Zprime','spin':1,'decay':'WW','production':production,
        'width':'Synthetic narrow-width convention','energy_tev':13,
        'branching_convention':'sigma times BR(Zprime->WW), synthetic', 'interference':'Neglected in synthetic fixture',
        'quantity':'95% CL UL [pb]','unit':'pb','domain':'Synthetic source points, no physics.'}


def data(name='Table 1',rows=2):
    return {'name':name,'x_count':1,'headers':[{'name':'Mass [GeV]','colspan':1},{'name':'Observed [pb]','colspan':1},
            {'name':'Expected [pb]','colspan':1}], 'qualifiers':{'WIDTH':[{'value':'narrow'}]},
            'values':[{'x':[{'value':str(250+250*i)}], 'y':[{'group':0,'value':'0.5' if i%2==0 else '-',
              'errors':[{'asymerror':{'plus':'-.2','minus':'.4'},'label':'Source odd encoding'}]},
              {'group':1,'value':None if i%2 else '0.4'}]} for i in range(rows)]}


def fixture(base,rows=2):
    b=parent(base)
    catalog=write(base/'catalog.txt','FABRICATED ATLAS+CMS discovery record; not an exhaustive current census.')
    p=write(base/'table.json',data(rows=rows))
    assets={'catalog':{'pin':catalog,'format':'text','citation':'Synthetic source discovery'},
            'table':{'pin':p,'format':'hepdata_record_data','citation':'Synthetic complete table'}}
    s=op.Snapshots(base);table=op._table(assets['table'],s)
    studies=[]
    for sid,model,prod in [('A','HVT','qqA'),('C','SPM','VBF')]:
        studies.append({'id':sid,'question_ids':['limits'],'source_ids':['catalog','table'],'basis':basis(model,prod),
            'applicability':{'state':'source_declared','reason':'Synthetic supplied basis, not physical qualification.','evidence_ids':['catalog']},
            'tables':[{'source_id':'table','expected_rows':rows,'expected_axes_sha256':op.digest(table['payload']['independent_variables']),
                       'columns':[{'index':i,'state':'deliver','reason':'Retain complete source column.'} for i in range(2)]}],
            'limitations':['Fabricated values; no actual physics, error law or covariance.']})
    r={'schema_version':1,'kind':'scientific-delivery/v1','parent':b,
       'questions':[{'id':'limits','obligation_ids':['original-request'],'quantity':'Every declared source limit/unknown plus original full question'}],
       'discovery':{'as_of':'2026-10-08','scope':'Complete two-candidate synthetic supplied census; current literature completeness unknown.',
                    'source_ids':['catalog'],'candidate_ids':['A','C']},
       'resources':assets,'acquisition':None,'knowledge':None,'studies':studies,'routes':[],'publication_required':True}
    return r


def task(base,r):
    p=write(base/'request.json',r)
    return {'schema_version':1,'input':p['path'],'input_sha256':p['sha256']}


def policy():
    return {'schema_version':1,'actors':{'proposer':'worker','executor':'worker','physics_critic':'critic',
        'skeptical_verifier':'skeptic','physics_decider':'physicist'}, 'max_redos':0,
        'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'source','kind':'scientific'}],
        'claim_scopes':{'source_delivery':{'checks':['integrity','source'],'actions':['delivery','reuse']}}}


def spec(task_,binding):
    return {'schema_version':2,'mode':'scientific-delivery','source':'Fabricated primary source portfolio.',
            'assumptions':['No authority, numerical law or scientific qualification from source reporting.'],
            'max_seconds':60,'max_attempts':1,'approval_mode':'scripted_yes','task':task_,'review_policy':{'schema_version':1,'policy':policy(),'correction_contract':{'task_fields':[],'input_slots':[]}},
            'goal_binding':binding}


def test_complete_literal_population_original_task_and_unknowns(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'delivery')
    assert len(result['cells'])==8 and len(result['basis_groups'])==2
    assert {c['status'] for c in result['cells']}=={'unknown','literal_source'}
    assert result['cells'][0]['payload']['errors']==data()['values'][0]['y'][0]['errors']
    assert result['cells'][1]['payload']['value']=='-'
    assert result['cells'][3]['payload']['value'] is None
    assert result['original_task']['original_request']==PROMPT
    assert result['continuation_obligations'][-1]['kind']=='publication_route'
    report=json.loads((tmp_path/'delivery/page-000/report.json').read_text())
    assert len(report['facts'])==24 and len(report['expected_slots'])==24
    assert not report['scientific_acceptance'] and not report['whole_quantity_exposure_checked']
    assert not result['parent_task_complete'] and not result['publication_delivered']
    assert set(op.inputs(task(tmp_path,r),tmp_path))=={tmp_path/'request.json',tmp_path/'table.json',tmp_path/'catalog.txt',Path(r['parent']['contract']['path'])}


def test_pagination_exposes_every_cell_without_truncation(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path,rows=20)
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert len(result['cells'])==80 and [len(p['cell_ids']) for p in result['report_pages']]==[32,32,16]
    exposed=[i for p in result['report_pages'] for i in p['cell_ids']]
    assert exposed==[c['id'] for c in result['cells']]
    assert len(set(exposed))==80


@pytest.mark.parametrize('field,new',[('model','scalar'),('production','ggF'),('width','broad'),('energy_tev',8),
 ('branching_convention','extra W decay BR'),('interference','full interference'),('domain','different fiducial')])
def test_distinct_declared_bases_cannot_merge(tmp_path,field,new):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    r['studies'][1]['basis']=deepcopy(r['studies'][0]['basis']);r['studies'][1]['basis'][field]=new
    _,_,result=op._load(task(tmp_path,r),tmp_path)
    assert len(result['basis_groups'])==2
    assert all(g['common_curve_authorized'] is False for g in result['basis_groups'])


def test_equal_known_bases_group_but_do_not_gain_conversion_or_acceptance(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    r['studies'][1]['basis']=deepcopy(r['studies'][0]['basis'])
    _,_,result=op._load(task(tmp_path,r),tmp_path)
    assert result['basis_groups'][0]['study_ids']==['A','C'] and len(result['basis_groups'])==1
    assert not result['common_basis_physics_qualified']


def test_unknown_basis_not_coalesced_or_labeled_known(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    for s in r['studies']:
        s['basis']['width']=None;s['applicability']['state']='unresolved'
    _,_,result=op._load(task(tmp_path,r),tmp_path)
    assert len(result['basis_groups'])==2
    r['studies'][0]['applicability']['state']='source_declared'
    with pytest.raises(ValueError,match='unknown basis'):op.inputs(task(tmp_path,r),tmp_path)


@pytest.mark.parametrize('fault',['candidate','column','row','geometry','source','obligation','question','duplicate','unknown-format','unbound-evidence'])
def test_whole_population_and_provenance_refuse(tmp_path,fault):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    if fault=='candidate':r['studies'].pop()
    if fault=='column':r['studies'][0]['tables'][0]['columns'].pop()
    if fault=='row':r['studies'][0]['tables'][0]['expected_rows']=1
    if fault=='geometry':r['studies'][0]['tables'][0]['expected_axes_sha256']='0'*64
    if fault=='source':r['resources']['table']['pin']['sha256']='0'*64
    if fault=='obligation':r['questions'][0]['obligation_ids']=['not-original']
    if fault=='question':r['studies'][0]['question_ids']=['absent']
    if fault=='duplicate':r['discovery']['candidate_ids']=['A','A']
    if fault=='unknown-format':r['resources']['table']['format']='guessed-json'
    if fault=='unbound-evidence':r['studies'][0]['applicability']['evidence_ids']=['missing']
    with pytest.raises(ValueError):op.inputs(task(tmp_path,r),tmp_path)


def test_context_columns_stay_full_source_and_are_not_silently_delivered(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    for study in r['studies']:study['tables'][0]['columns'][1].update(state='context',reason='Retain anomalous original expected bands without plotting.')
    _,_,result=op._load(task(tmp_path,r),tmp_path)
    assert len(result['cells'])==4
    assert len(result['tables'][0]['complete_table']['payload']['dependent_variables'])==2


def test_strict_yaml_parser_reuses_one_snapshot_and_retains_numeric_lexemes(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    raw='''independent_variables:\n- header: {name: x, units: GeV}\n  values: [{value: 2.5000e2}, {value: 500}]\ndependent_variables:\n- header: {name: observed, units: pb}\n  values: [{value: 0.05000}, {value: '-'}]\n'''
    r['resources']['table']={'pin':write(tmp_path/'table.yaml',raw),'format':'hepdata_yaml','citation':'Synthetic literal YAML'}
    table=op._table(r['resources']['table'],op.Snapshots(tmp_path))
    for study in r['studies']:
        study['tables'][0].update(expected_axes_sha256=op.digest(table['payload']['independent_variables']),
                                  columns=[{'index':0,'state':'deliver','reason':'Full literal source'}])
    _,_,result=op._load(task(tmp_path,r),tmp_path)
    assert result['cells'][0]['payload']['value']=={'literal':'0.05000','decimal':'0.05000'}
    r['resources']['table']['pin']=write(tmp_path/'table.yaml',raw+raw)
    with pytest.raises(ValueError,match='unique'):op.inputs(task(tmp_path,r),tmp_path)


@pytest.mark.parametrize('fault',['group','duplicate-group','short-x','short-y','ambiguous-header'])
def test_record_data_exact_group_and_axis_population(tmp_path,fault):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);doc=data()
    if fault=='group':doc['values'][0]['y'][0]['group']=5
    if fault=='duplicate-group':doc['values'][0]['y'][1]['group']=0
    if fault=='short-x':doc['values'][0]['x']=[]
    if fault=='short-y':doc['values'][0]['y'].pop()
    if fault=='ambiguous-header':doc['headers'][1]['colspan']=2
    r['resources']['table']['pin']=write(tmp_path/'table.json',doc)
    with pytest.raises(ValueError):op.inputs(task(tmp_path,r),tmp_path)


def test_source_change_after_report_refuses_without_success_portfolio(tmp_path,monkeypatch):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);original=op._report_pages
    def mutated(result,out):
        value=original(result,out);(tmp_path/'table.json').write_text('{}');return value
    monkeypatch.setattr(op,'_report_pages',mutated)
    with pytest.raises(ValueError,match='source'):op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/portfolio.json').exists()
    assert (tmp_path/'out/page-000/report.json').is_file()  # failed partial evidence retained


def transport_request():
    return {'schema_version':1,'record_url':'https://www.hepdata.net/record/ins1?format=json',
        'expected_recid':9,'expected_version':2,'table_dispositions':[{'id':11,'state':'capture','reason':'Requested original quantity'},
        {'id':12,'state':'context','reason':'Other channel retained in full record census'}], 'assets':[], 'max_total_bytes':100000}


def fake_open(url,timeout=30):
    assert timeout==30
    doc={'recid':9,'version':2,'data_tables':[{'id':11,'name':'Table / 1'},{'id':12,'name':'Table 1'}]} if '/record/ins' in url else data(name='Table / 1')
    return io.BytesIO(json.dumps(doc,allow_nan=False).encode())


def test_primary_capture_uses_original_response_and_complete_unique_id_filenames(tmp_path):
    result=op.acquire(transport_request(),tmp_path/'capture',opener=fake_open)
    assert result['full_record_table_census_retained'] and not result['all_tables_acquired']
    assert [r['id'] for r in result['tables']]==[11,12]
    assert Path(result['tables'][0]['source']['pin']['path']).name=='table-11.json'
    raw=Path(result['tables'][0]['source']['pin']['path']).read_bytes()
    assert raw==json.dumps(data(name='Table / 1'),allow_nan=False).encode()
    assert not result['scientific_acceptance']


@pytest.mark.parametrize('fault',['missing-disposition','duplicate-disposition','version','bool-id','oversize','duplicate-json','bad-name'])
def test_partial_acquisition_keeps_failure_and_no_success_manifest(tmp_path,fault):
    request=transport_request()
    if fault=='missing-disposition':request['table_dispositions'].pop()
    if fault=='duplicate-disposition':request['table_dispositions'][1]['id']=11
    if fault=='version':request['expected_version']=1
    def opener(url,timeout=30):
        if fault=='oversize':return io.BytesIO(b' '*100001)
        if fault=='duplicate-json':return io.BytesIO(b'{"recid":9,"recid":10}')
        if fault=='bool-id' and '/record/ins' in url:return io.BytesIO(json.dumps({'recid':9,'version':2,'data_tables':[{'id':True,'name':'A'}]}).encode())
        if fault=='bad-name' and '/record/data/' in url:return io.BytesIO(json.dumps(data(name='wrong')).encode())
        return fake_open(url,timeout)
    with pytest.raises(ValueError):op.acquire(request,tmp_path/'capture',opener=opener)
    assert (tmp_path/'capture/acquisition-failure.json').is_file()
    assert not (tmp_path/'capture/primary-resources.json').exists()


def test_acquired_primary_capture_connects_directly_to_complete_study_reports(tmp_path):
    tmp_path=tmp_path.resolve();a=op.acquire(transport_request(),tmp_path/'capture',opener=fake_open)
    r=fixture(tmp_path);r['resources']['table']['pin']=a['tables'][0]['source']['pin']
    r['acquisition']=op.pin(tmp_path/'capture/primary-resources.json',(tmp_path/'capture/primary-resources.json').read_bytes())
    table=op._table(r['resources']['table'],op.Snapshots(tmp_path))
    for study in r['studies']:study['tables'][0]['expected_axes_sha256']=op.digest(table['payload']['independent_variables'])
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert len(result['cells'])==8 and len(result['source_copies'])==6


def test_real_ordinary_worker_and_standard_report_route_with_authority_mocked(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    from ravel.workflow import execution
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);t=task(tmp_path,r);s=spec(t,r['parent'])
    rd=tmp_path/'run';rd.mkdir()
    monkeypatch.setattr(science_worker,'verify_worker',lambda rd:{'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':[]}})
    monkeypatch.setattr(science_worker,'execution_spec',lambda rd:s)
    science_worker.main([str(rd)])
    result=json.loads((rd/'outputs/attempt-1/result.json').read_text())
    assert result['status']=='passed' and not result['publication_delivered']
    assert (rd/'outputs/attempt-1/scientific-delivery/page-000/report.json').is_file()
    assert (rd/'outputs/attempt-1/scientific-delivery/scientific-delivery-report.md').is_file()
    assert not list(rd.rglob('*.png')) and not list(rd.rglob('*.pdf'))


def test_v2_required_for_new_mode_without_run_creation(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);s=spec(task(tmp_path,r),r['parent'])
    s.pop('goal_binding');s.pop('review_policy');s.pop('max_attempts');s['schema_version']=1
    p=write(tmp_path/'science.json',s)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'run',p['path'])
    assert not (tmp_path/'run').exists()


def publication_fixture(base):
    from test_requested_summary_contract import make as make_publication
    from ravel.physics import published_summary
    r=fixture(base);folder=base/'publication';folder.mkdir()
    _,target,_,_,contract=make_publication(folder)
    # Full source points and all nonnull display series are explicitly identical.
    d=data()
    d['values'][1]['y'][0]['value']='0.2';d['values'][1]['y'][1]['value']='0.1'
    r['resources']['table']['pin']=write(base/'table.json',d)
    for panel in contract['panels']:
        cp=Path(panel['summary']['path']);c=json.loads(cp.read_text())
        mp=Path(c['manifest']['path']);manifest=json.loads(mp.read_text())
        curve=manifest['curves'][0]
        curve['resolved']={'mass_gev':[250,500], 'obs':[.5,.2], 'exp':[.4,.1], 'theory':[None,None], 'theory_label':'Unavailable'}
        survey_path=Path(c['survey']['path']);survey=json.loads(survey_path.read_text())
        survey['candidates'][0]['mass_range_gev']=[250,500]
        c['survey']={k:v for k,v in write(survey_path,survey).items() if k!='size'}
        c['candidate_sources'][0]['mass_range_gev']=[250,500]
        c['manifest']={k:v for k,v in write(mp,manifest).items() if k!='size'}
        c['resolved_series_sha256']={curve['survey_id']:published_summary.digest(curve['resolved'])}
        panel['summary']={k:v for k,v in write(cp,c).items() if k!='size'}
    tp=Path(contract['figure_target']['path']);target=json.loads(tp.read_text())
    for candidate in target['candidates']:candidate['mass_range_gev']=[250,500]
    contract['figure_target']={k:v for k,v in write(tp,target).items() if k!='size'}
    task_pin=write(folder/'contract.json',contract)
    ordinary=spec({'schema_version':2,'input':task_pin['path'],'input_sha256':task_pin['sha256']},r['parent'])
    ordinary['mode']='published-summary'
    route_pin=write(base/'publication.science.json',ordinary)
    binds=[]
    for sid,pid in [('A','qq'),('C','vbf')]:
        for series,column in [('mass_gev',None),('obs',0),('exp',1)]:
            binds.append({'study_id':sid,'panel_id':pid,'curve_id':sid,'series':series,'source_id':'table','column':column})
    r['routes']=[{'id':'publication','study_ids':['A','C'],'role':'publication','spec':route_pin,'quantity_bindings':binds}]
    return r


def test_primary_tables_connect_to_existing_full_task_publication_recipe(tmp_path):
    tmp_path=tmp_path.resolve();r=publication_fixture(tmp_path)
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert len(result['routes'])==1 and result['routes'][0]['specification']['mode']=='published-summary'
    assert not any(o['kind']=='publication_route' for o in result['continuation_obligations'])
    assert not result['publication_delivered'] and not result['parent_task_complete']
    assert not list((tmp_path/'out').rglob('*.png'))


@pytest.mark.parametrize('fault',['series','missing-join','wrong-study','drop-candidate','basis','interference','goal'])
def test_valid_figure_contract_cannot_bypass_delivery_quantity_or_parent_join(tmp_path,fault):
    tmp_path=tmp_path.resolve();r=publication_fixture(tmp_path)
    if fault=='series':r['routes'][0]['quantity_bindings'][1]['column']=1
    if fault=='missing-join':r['routes'][0]['quantity_bindings'].pop()
    if fault=='wrong-study':r['routes'][0]['quantity_bindings'][0]['study_id']='C'
    if fault=='drop-candidate':r['routes'][0]['study_ids']=['A']
    if fault=='basis':r['studies'][1]['basis']['width']='different width'
    if fault=='interference':
        # Cannot smuggle unknown interference into publication candidate metadata.
        r['studies'][1]['basis']['interference']=None
    if fault=='goal':
        p=Path(r['routes'][0]['spec']['path']);d=json.loads(p.read_text());d.pop('goal_binding');r['routes'][0]['spec']=write(p,d)
    with pytest.raises(ValueError):op.inputs(task(tmp_path,r),tmp_path)


def test_source_underflow_not_lost_during_publication_display_projection():
    with pytest.raises(ValueError,match='underflow'):op._source_number('1e-400')
    assert op._source_number('0')==0.0 and op._source_number('-') is None


def test_original_contract_is_preserved_in_real_v2_ordinary_metadata_plan(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);s=spec(task(tmp_path,r),r['parent'])
    p=write(tmp_path/'science.json',s)
    result=science.plan(tmp_path/'planned',p['path'])
    assert (tmp_path/'planned/inputs/checkin1.json').is_file()
    assert json.loads((tmp_path/'planned/inputs/science.json').read_text())['goal_binding']==r['parent']
    assert not (tmp_path/'planned/execution_attempt.json').exists()


def test_acquisition_resealed_manifest_cannot_drop_original_record_table(tmp_path):
    tmp_path=tmp_path.resolve();a=op.acquire(transport_request(),tmp_path/'capture',opener=fake_open)
    r=fixture(tmp_path);r['resources']['table']['pin']=a['tables'][0]['source']['pin']
    a['tables'].pop();a['all_tables_acquired']=True
    r['acquisition']=write(tmp_path/'capture/primary-resources.json',a)
    with pytest.raises(ValueError,match='census'):op.inputs(task(tmp_path,r),tmp_path)


def test_prepared_route_uses_existing_ordinary_planner_and_holds_source_drift(tmp_path):
    tmp_path=tmp_path.resolve();r=publication_fixture(tmp_path)
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    op.plan_route(result,'publication',tmp_path/'planned-publication')
    assert (tmp_path/'planned-publication/inputs/science-plan.json').is_file()
    assert not (tmp_path/'planned-publication/execution_attempt.json').exists()
    Path(r['resources']['table']['pin']['path']).write_text('{}')
    with pytest.raises(ValueError):op.plan_route(result,'publication',tmp_path/'stale-plan')
    assert not (tmp_path/'stale-plan').exists()


def test_existing_knowledge_conflict_closure_is_retained_without_basis_truth_transfer(tmp_path):
    from test_physics_knowledge import fixture as knowledge_fixture
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);k=tmp_path/'knowledge';k.mkdir()
    kr,_,_=knowledge_fixture(k)
    r['knowledge']=write(k/'request.json',kr)
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert result['knowledge_context']['selection']['selected_ids']==['beam','contested']
    assert result['knowledge_context']['contradictions'][0]['id']=='beam-conflict'
    assert not any(result['knowledge_context']['claims'].values())
    assert not result['common_basis_physics_qualified']
    assert {Path(x['original']['path']).name for x in result['source_copies']} >= {'knowledge.json','source.txt','original.txt'}


@pytest.mark.parametrize('fault',['wrong-unit','missing-unit'])
def test_source_unit_is_not_synthesized_from_basis_label(tmp_path,fault):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    if fault=='wrong-unit':r['studies'][0]['basis']['unit']='fb'
    else:
        d=data();d['headers'][1]['name']='Observed';r['resources']['table']['pin']=write(tmp_path/'table.json',d)
    with pytest.raises(ValueError,match='source unit'):op.inputs(task(tmp_path,r),tmp_path)
    r['studies'][0]['applicability']['state']='unresolved'
    if fault=='missing-unit':r['studies'][1]['applicability']['state']='unresolved'
    _,_,result=op._load(task(tmp_path,r),tmp_path)
    assert any(o['kind']=='applicability' for o in result['continuation_obligations'])


def test_short_response_reads_capture_whole_payload_with_single_classified_snapshot(tmp_path):
    class Short(io.BytesIO):
        def read(self,n=-1):return super().read(min(n,7))
    def short(url,timeout=30):return Short(fake_open(url,timeout).read())
    result=op.acquire(transport_request(),tmp_path/'capture',opener=short)
    assert json.loads(Path(result['tables'][0]['source']['pin']['path']).read_bytes())==data(name='Table / 1')


@pytest.mark.parametrize('fault',['url','bool-version','missing-table','changed-total'])
def test_resealed_acquisition_metadata_internal_associations_refuse(tmp_path,fault):
    tmp_path=tmp_path.resolve();a=op.acquire(transport_request(),tmp_path/'capture',opener=fake_open)
    r=fixture(tmp_path);r['resources']['table']['pin']=a['tables'][0]['source']['pin']
    if fault=='url':a['tables'][0]['source']['requested_url']='https://www.hepdata.net/record/data/9/999/2'
    if fault=='bool-version':a['version']=True
    if fault=='missing-table':a['tables'].pop()
    if fault=='changed-total':a['total_bytes']+=1
    r['acquisition']=write(tmp_path/'capture/primary-resources.json',a)
    with pytest.raises(ValueError):op.inputs(task(tmp_path,r),tmp_path)


def test_generated_report_mutation_retains_partial_and_refuses_success(tmp_path,monkeypatch):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);original=op._report_pages
    def mutate(result,out):
        pages=original(result,out);(out/'page-000/report.md').write_text('Unbound replacement');return pages
    monkeypatch.setattr(op,'_report_pages',mutate)
    with pytest.raises(ValueError,match='generated report'):op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/portfolio.json').exists()


def test_non_original_hypothesis_question_uses_same_generic_source_delivery(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    prompt='Study a toponium hypothesis and a semi-visible-jet alternative using exact primary resources and explicit applicability.'
    r['parent']=parent(tmp_path,prompt)
    r['questions'][0]['quantity']='Complete supplied candidate diagnostics; no significance or inference claim.'
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert result['original_task']['original_request']==prompt and len(result['cells'])==8
    assert any(o['kind']=='publication_route' for o in result['continuation_obligations'])
    assert not result['parent_task_complete']


def test_top_report_links_exact_page_files_from_separate_report_directory(tmp_path):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path)
    result=op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    report=tmp_path/'ordinary-report';report.mkdir()
    op.write_report(result,report)
    assert f'](<{tmp_path}/out/page-000/report.md>)' in (report/'scientific-delivery-report.md').read_text()
    assert {Path(f['path']).name for f in result['report_pages'][0]['files']}=={
        'basis.txt','cells.json','report-request.json','report.json','report.md'}
    (tmp_path/'out/page-000/report.md').write_text('changed')
    refused=tmp_path/'refused-report'
    with pytest.raises(ValueError,match='page report changed'):op.write_report(result,refused)
    assert not (refused/'scientific-delivery-report.json').exists()


@pytest.mark.parametrize('name',['basis.txt','cells.json'])
def test_generated_report_source_swap_cannot_publish_portfolio(tmp_path,monkeypatch,name):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);original=op._report_pages
    def swap(result,out):
        pages=original(result,out);(out/'page-000'/name).write_text('changed');return pages
    monkeypatch.setattr(op,'_report_pages',swap)
    with pytest.raises(ValueError,match='generated report'):op.run(task(tmp_path,r),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/portfolio.json').exists()


def test_resealed_record_mirror_mismatch_refuses_on_retained_intake(tmp_path):
    tmp_path=tmp_path.resolve();a=op.acquire(transport_request(),tmp_path/'capture',opener=fake_open)
    record=json.loads(Path(a['record']['pin']['path']).read_bytes());record['record']={'recid':99,'version':2}
    previous=a['record']['pin']['size'];a['record']['pin']=write(Path(a['record']['pin']['path']),record)
    a['total_bytes']+=a['record']['pin']['size']-previous
    r=fixture(tmp_path);r['resources']['table']['pin']=a['tables'][0]['source']['pin']
    r['acquisition']=write(tmp_path/'capture/primary-resources.json',a)
    with pytest.raises(ValueError,match='mirror'):op.inputs(task(tmp_path,r),tmp_path)


def test_publication_role_cannot_be_disguised_as_ordinary_study(tmp_path):
    tmp_path=tmp_path.resolve();r=publication_fixture(tmp_path)
    r['routes'][0].update(role='study',study_ids=['A'],quantity_bindings=[])
    with pytest.raises(ValueError,match='publication mode'):op.inputs(task(tmp_path,r),tmp_path)


@pytest.mark.parametrize('fault',['absent','different'])
def test_outer_ordinary_goal_must_match_exact_inner_parent_before_plan(tmp_path,fault):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);s=spec(task(tmp_path,r),r['parent'])
    if fault=='absent':s.pop('goal_binding')
    else:s['goal_binding']=parent(tmp_path/'other','An unrelated valid original task.')
    f=write(tmp_path/'science.json',s)
    with pytest.raises(ValueError,match='exact original parent'):science.plan(tmp_path/'planned',f['path'])
    assert not (tmp_path/'planned').exists()


@pytest.mark.parametrize('name',['basis.txt','cells.json','report-request.json','report.json','report.md'])
def test_final_report_attachment_guards_complete_page_graph(tmp_path,name):
    tmp_path=tmp_path.resolve();r=fixture(tmp_path);result=op.run(task(tmp_path,r),tmp_path/'',tmp_path/'out')
    (tmp_path/'out/page-000'/name).write_bytes(b'changed')
    dest=tmp_path/'report'
    with pytest.raises(ValueError,match='page report changed'):op.write_report(result,dest)
    assert not (dest/'scientific-delivery-report.json').exists()
