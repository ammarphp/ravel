"""Authored, NOT RUN. Inert role/campaign seams are explicitly synthetic.

These test productive source construction and refusal boundaries, not an actual
model, native renderer, publisher, physics verdict or independent role outcome.
"""
from copy import deepcopy
import json
from pathlib import Path
import hashlib
import pytest
from ravel.workflow import manuscript_production as mp, report_integrity as ri
from ravel.workflow import manuscript_format as mf, research_cycle, scientific_report, state_io
from ravel.physics import manuscript_build as mb


def pin(path):
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def put(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(value if isinstance(value,str) else json.dumps(value,allow_nan=False)+'\n');return pin(p)


def loc(pin_,text):return {'artifact':pin_,'format':'text','location':{'start':0,'end':len(text),'text':text},'value':text}


def setup(root,monkeypatch,profile='research-paper',stage='draft'):
    original=put(root,'original.txt','Produce a reproducible source-grounded research paper for this synthetic score task.')
    source=put(root,'score.py','def square(x):\n    return x*x\n')
    outcome=put(root,'result.json',{'score':4,'physics_validated':False})
    reference=put(root,'primary.txt','Example Author, Toy squares, 2020. Fabricated engineering reference.\n')
    context={'toy_context':True};report=put(root,'quantities.json',{'context':{'path':'synthetic-context'},'toy_request':True})
    monkeypatch.setattr(scientific_report,'compose',lambda *a,**k:{'report_text':'Requested score: 4. Missing fit: unresolved.\n','requested_quantity_completion':False})
    monkeypatch.setattr(scientific_report,'input_pins',lambda *a,**k:[outcome])
    monkeypatch.setattr(scientific_report,'_context',lambda *a,**k:deepcopy(context))
    render={'class':'revtex4-2' if profile=='prd' else 'svjour3' if profile=='epjc' else 'article',
        'frontmatter':'abstract-before-title' if profile=='prd' else 'title-before-abstract','graphics':'separate' if profile=='nature' and stage=='final' else 'inline',
        'citation_style':'numeric-superscript' if profile=='nature' and stage=='final' else 'numeric-brackets','line_numbers':profile=='nature' and stage=='initial','appendices':'after-references',
        'post_reference_sections':['methods','data-availability','code-availability','acknowledgements','funding','author-contributions','competing-interests','additional-information','extended-data-legends'] if profile=='nature' and stage=='final' else [],'quantitative_position':'main'}
    rule={'id':'sections','kind':'required_sections','scope':'main','value':['title','abstract','methods','results','limitations'],'origin':'user','source_basis':None}
    formatting={'schema_version':1,'profile':profile,'stage':stage,'article_type':'research article','render':render,'rules':[rule],'template_assets':[]}
    fmt=put(root,'format.json',formatting)
    request={'schema_version':1,'profile':profile,'author_id':'toy-writer','original_task':original,'quantitative_report':report,
        'source_manifest':put(root,'source-manifest.json',{'schema_version':1,'evidence':[{'id':'score','description':'Supplied toy result only','located':{'artifact':outcome,'format':'json','location':'/score','value':4}}]}),
        'environment':put(root,'env.json',{'schema_version':1,'description':'Synthetic declared environment, not a loaded runtime','assets':[source]}),
        'code_manifest':put(root,'code.json',{'schema_version':1,'git_commit':'a'*40,'dirty':False,'files':[source]}),
        'skills':[put(root,'skill.md','Use the supplied pure square operation; no physical interpretation.')],
        'methods':[{'id':'square','description':'Square supplied x','operations':[{'id':'score','description':'Call square','code':[loc(source,(root/'score.py').read_text())],
            'execution':None,'results':[{'artifact':outcome,'format':'json','location':'/score','value':4}],'differences':['No actual execution in this fixture.']}],'citation_ids':['toy'],'uncertainties':['Fabricated engineering case.']}],
        'citations':[{'id':'toy','bibliography':{'title':'Toy squares','authors':['Example Author'],'year':'2020','identifiers':['example.invalid/toy']},
            'identity_evidence':[{'source_role':'primary-paper','source_url':'https://example.invalid/toy','located':loc(reference,(root/'primary.txt').read_text())}],
            'uncertainties':['Fabricated, not a real publication.']}],
        'figures':[],'runtime':{'model':'synthetic','model_build':'synthetic-build','action':'external','reasoning_effort':'low',
            'max_output_tokens':4096,'max_input_tokens':16000,'max_context_bytes':250000,'max_wall_seconds':60},
        'revision':None,'challenge_requirements':None,'template':None,'formatting':fmt}
    state={'sha256':'0'*64,'context':context,'graphs':[],'contract':{},'parent_task':None}
    monkeypatch.setattr(research_cycle,'_load',lambda *a,**k:(None,deepcopy(state)))
    value={'schema_version':1,'paragraphs':[], 'figures':[]}
    for s in ('title','abstract','methods','results','limitations'):
        value['paragraphs'].append({'id':s,'section':s,'kind':'method' if s=='methods' else 'claim',
            'text':{'title':'Toy source note','abstract':'A synthetic engineering example.','methods':'We square supplied x.',
                'results':'The supplied source reports four, with an unresolved fit.','limitations':'No physics/model/native result is established.'}[s],
            'method_ids':['square'] if s=='methods' else [],'citation_ids':['toy'] if s=='methods' else [],
            'evidence_ids':['score'] if s=='results' else [],'uncertainties':['Synthetic source-only control.']})
    return request,state,value


def completed(binding,state,value,monkeypatch,mode='remote_transport_observed'):
    """An inert retained-response stand-in; NEVER actual model qualification."""
    state['sha256']='1'*64;state['graphs']=[{'root':binding['graph'],'complete':True}]
    receipt={'execution_observation':mode,'public_value':deepcopy(value),'transport':{'observed_model':'synthetic-build','actor_id':'toy-writer'}}
    monkeypatch.setattr(mp.agent_graph,'role_receipt',lambda *a,**k:deepcopy(receipt))
    monkeypatch.setattr(mp.agent_graph,'status',lambda *a,**k:{'nodes':{'author':{'result':'inert'}},'started_epoch':100.0})
    saved={'result':{'usage':{'input_tokens':100,'output_tokens':200,'total_tokens':300},'transport':{'observed_model':'synthetic-build','actor_id':'toy-writer'}},'call_receipts':[]}
    monkeypatch.setattr(mp.agent_graph,'_result',lambda *a,**k:deepcopy(saved))
    return saved,receipt


def test_author_graph_uses_original_full_context_without_manually_written_note(tmp_path,monkeypatch):
    r,state,value=setup(tmp_path,monkeypatch);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert b['spec']['nodes'][0]['role']=='proposer' and b['spec']['budget']['max_calls']==1
    body=Path(b['presentation']['path']).read_text()
    assert 'Missing fit: unresolved' in body and 'Toy squares' in body and 'def square' in body
    assert not b['execution_authorized'] and not (tmp_path/'writer/manuscript.md').exists()


def test_inert_real_consumer_shape_produces_whole_census_exact_quantities_and_source(tmp_path,monkeypatch):
    r,state,v=setup(tmp_path,monkeypatch);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch)
    result=mp.collect(b,tmp_path/'note');p=result['package'];text=Path(p['manuscript']['path']).read_text()
    assert 'Missing fit: unresolved' in text and len(result['integrity_preparation']['units'])>=7
    assert all(not p[k] for k in ('scientific_acceptance','visual_style_accepted','parent_task_accepted','execution_authorized'))
    assert p['author_binding']['sha256']==pin(tmp_path/'writer/binding.json')['sha256']
    assert any(i['kind']=='formatting-instruction' for i in result['integrity_preparation']['items'])
    assert r'\zlabel{ravel-reference-start}' in Path(p['latex']['path']).read_text()


@pytest.mark.parametrize('mode',['control_only','unestablished'])
def test_control_transport_is_not_relabelled_actual_author(tmp_path,monkeypatch,mode):
    r,state,v=setup(tmp_path,monkeypatch);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch,mode)
    with pytest.raises(ValueError,match='control transport'):mp.collect(b,tmp_path/'note')


@pytest.mark.parametrize('change',['missing-method','missing-section','invented-citation','invented-source','missing-telemetry','model-build','stale-source','uncharged'])
def test_whole_source_budget_and_output_adversaries(tmp_path,monkeypatch,change):
    r,state,v=setup(tmp_path,monkeypatch);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    if change=='missing-method':v['paragraphs'][2]['kind']='claim';v['paragraphs'][2]['method_ids']=[]
    if change=='missing-section':v['paragraphs'].pop()
    if change=='invented-citation':v['paragraphs'][0]['citation_ids']=['missing']
    if change=='invented-source':v['paragraphs'][3]['evidence_ids']=['missing']
    saved,_=completed(b,state,v,monkeypatch)
    if change=='missing-telemetry':saved['result']['usage']['input_tokens']=None
    if change=='model-build':saved['result']['transport']['observed_model']='foreign-build'
    if change=='stale-source':(tmp_path/'score.py').write_text('changed')
    if change=='uncharged':state['graphs']=[]
    with pytest.raises((ValueError,KeyError)):mp.collect(b,tmp_path/'note')


def test_generated_tex_escapes_actor_source_and_reference_marker_positions(tmp_path,monkeypatch):
    r,state,v=setup(tmp_path,monkeypatch);v['paragraphs'][2]['text']=r'We discuss [1] as a literal array entry; \input{private.tex} is not executed.'
    b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch)
    p=mp.collect(b,tmp_path/'note')['package'];tex=Path(p['latex']['path']).read_text();ir=json.loads(Path(p['integrity_request']['path']).read_text())
    assert r'\input{private.tex}' not in tex and r'\textbackslash{}input' in tex
    occurrence=ir['citations'][0]['occurrences'][0]['span'];text=Path(p['manuscript']['path']).read_text()
    assert text[occurrence['start']-1]==' ' and text[occurrence['end']:].startswith('\n\n')


@pytest.mark.parametrize('profile,stage',[('prd','initial'),('epjc','initial'),('nature','initial'),('nature','final'),('user','draft')])
def test_distinct_native_profiles_not_generic_conformance(tmp_path,monkeypatch,profile,stage):
    r,state,v=setup(tmp_path,monkeypatch,profile,stage);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch)
    p=mp.collect(b,tmp_path/'note')['package'];tex=Path(p['latex']['path']).read_text()
    if profile=='prd':assert tex.index(r'\begin{abstract}')<tex.index(r'\maketitle') and '{revtex4-2}' in tex
    if profile=='epjc':assert '{svjour3}' in tex
    if profile=='nature' and stage=='initial':assert r'\linenumbers' in tex
    if profile=='nature' and stage=='final':assert tex.index(r'\section*{References}')<tex.index(r'\section*{Methods}')
    assert not p['formatting_assessment']['complete_publisher_or_user_conformance']


def test_late_generated_commitment_mutation_refuses(tmp_path,monkeypatch):
    native=mp.integrity._raw
    def mutate(pin_,base,consumed):
        if Path(pin_['path']).name=='note.tex':Path(pin_['path']).write_text('late source rewrite')
        return native(pin_,base,consumed)
    monkeypatch.setattr(mp.integrity,'_raw',mutate)
    with pytest.raises(ValueError):mp._write(tmp_path/'note.tex',b'expected')


def test_final_delivery_cannot_be_inferred_from_unaccepted_author_or_pdf(tmp_path,monkeypatch):
    r,state,v=setup(tmp_path,monkeypatch);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch)
    p=mp.collect(b,tmp_path/'note')['package_pin']
    with pytest.raises(ValueError):mp.finalize(p,[],{}, {}, {},base_dir=tmp_path,rundir=tmp_path)


@pytest.mark.parametrize('change',['duplicate-operation','missing-bibliographic-title','missing-author','unknown-evidence-role','foreign-method-citation'])
def test_invalid_source_population_refuses_before_a_model_is_prepared(tmp_path,monkeypatch,change):
    r,state,v=setup(tmp_path,monkeypatch)
    if change=='duplicate-operation':r['methods'][0]['operations'].append(deepcopy(r['methods'][0]['operations'][0]))
    if change=='missing-bibliographic-title':r['citations'][0]['bibliography']['title']=''
    if change=='missing-author':r['citations'][0]['bibliography']['authors']=[]
    if change=='unknown-evidence-role':r['citations'][0]['identity_evidence'][0]['source_role']='hash-proves-truth'
    if change=='foreign-method-citation':r['methods'][0]['citation_ids']=['foreign']
    with pytest.raises(ValueError):mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert not (tmp_path/'writer/graph').exists()


def test_nature_final_method_only_references_follow_online_methods(tmp_path,monkeypatch):
    r,state,v=setup(tmp_path,monkeypatch,'nature','final')
    b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch)
    p=mp.collect(b,tmp_path/'note')['package'];tex=Path(p['latex']['path']).read_text()
    assert tex.index(r'\section*{References}')<tex.index(r'\section*{Methods}')<tex.index(r'\section*{Methods references}')
    assert r'\noindent\textbf{' in tex and r'\begin{abstract}' not in tex


@pytest.mark.parametrize('change',['missing-pdf','unreviewed-pdf-role','foreign-parent','unmet-template','foreign-build-package'])
def test_final_consumer_refusals_with_explicit_inert_review_standins(tmp_path,monkeypatch,change):
    from ravel.workflow import final_results_review,task_completion
    r,state,v=setup(tmp_path,monkeypatch);b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');completed(b,state,v,monkeypatch)
    collected=mp.collect(b,tmp_path/'note');p=collected['package'];pp=collected['package_pin']
    pdf=put(tmp_path,'synthetic.pdf','%PDF-INERT-NOT-A-REAL-BUILD\n')
    build={'status':'passed','kind':'manuscript-pdf-build','package':pp,'pdf':pdf,'pages':{'main_text_pages':1},'figure_conversions':[],'formatting_assessment':{'rules':[]}}
    if change=='unmet-template':build['formatting_assessment']['rules']=[{'state':'unmet_actual_template'}]
    if change=='foreign-build-package':build['package']=r['original_task']
    br=put(tmp_path,'build.json',build)
    required=[pp,p['manuscript'],p['latex'],p['integrity_request'],p['model_provenance'],p['formatting_assessment_pin'],p['author_binding'],br,pdf]
    rows=[{'path':x['path'],'sha256':x['sha256'],'role':'figure' if x==pdf else 'data'} for x in required]
    if change=='missing-pdf':rows.pop()
    if change=='unreviewed-pdf-role':rows[-1]['role']='data'
    manifest=put(tmp_path,'final-manifest.json',{'artifacts':rows})
    completion=put(tmp_path,'completion.json',{'parent_review':{'rundir':str(tmp_path/'foreign' if change=='foreign-parent' else tmp_path)}})
    # These stand-ins ONLY test final-consumer conjunction. No actual vote/CI3,
    # ordinary stage or original-parent acceptance is manufactured as evidence.
    monkeypatch.setattr(mp,'verify_author',lambda *a,**k:{'synthetic':True})
    monkeypatch.setattr(ri,'manuscript',lambda *a,**k:{'report_text':'synthetic','integrity':{'synthetic':True}})
    monkeypatch.setattr(mb,'verified_result',lambda *a,**k:{'result':deepcopy(build),'proof_pins':[]})
    monkeypatch.setattr(final_results_review,'gate',lambda *a,**k:{'synthetic':True})
    monkeypatch.setattr(task_completion,'require_final',lambda *a,**k:{'original_prompt_sha256':r['original_task']['sha256']})
    with pytest.raises(ValueError):mp.finalize(pp,[],{'rundir':str(tmp_path),'receipt':br,'result':br},manifest,completion,base_dir=tmp_path,rundir=tmp_path)
