"""AUTHORED NOT RUN: connected six-finding projections, with disclosed inert gates.

No provider, TeX, ROOT, process, actual scientific vote or submission. The
inherited actual consumer shapes exercise ordinary source APIs, while every
synthetic authority hook is local and explicitly labelled below.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_production as mp, manuscript_format as mf
from ravel.workflow import report_integrity as ri, final_results_review as fr, science
from ravel.physics import manuscript_build as mb, root_stream, reinterpret_db
from test_manuscript_production import setup, completed, pin, put
from test_manuscript_build import fixture as build_fixture
from test_manuscript_build import absolute_aux


def authored(root, monkeypatch, *, change=None):
    request,state,value=setup(root/'original',monkeypatch)
    if change:change(request,value,root/'original')
    binding=mp.prepare_writer(request,root/'writer',base_dir=root/'original',campaign=root/'campaign')
    completed(binding,state,value,monkeypatch)
    return request,binding,mp.collect(binding,root/'note')


def test_original_relative_format_and_nested_assets_survive_different_build_base(tmp_path,monkeypatch):
    def relative(request,value,base):
        fmt=json.loads(Path(request['formatting']['path']).read_text())
        asset=put(base,'house.sty','% Fabricated, literal inert template asset.\n')
        fmt['template_assets']=[{**asset,'path':'house.sty'}]
        primary='Source formatting instruction, synthetic only.'
        evidence=put(base,'instruction.txt',primary)
        fmt['rules'][0]['source_basis']={'artifact':{**evidence,'path':'instruction.txt'},'format':'text',
            'location':{'start':0,'end':len(primary),'text':primary},'value':primary}
        request['formatting']={**put(base,'format.json',fmt),'path':'format.json'}
    request,binding,collected=authored(tmp_path,monkeypatch,change=relative)
    assert collected['package']['source_base']==str(tmp_path/'original')
    mp.verify_author(collected['package'],base_dir=tmp_path/'note')
    verify=mp.verify_author
    task,config,_=build_fixture(tmp_path/'runtime-origin',monkeypatch)
    monkeypatch.setattr(mp,'verify_author',verify) # Real materialization verifier restored.
    runtime=deepcopy(config['runtime'])
    for key in ('compiler','pdfinfo'):runtime[key]['path']=Path(runtime[key]['path']).name
    runtime['asset_trees'][0]['root']='runtime';runtime['asset_trees'][0]['manifest']['path']='runtime-manifest.json'
    monkeypatch.setattr(science,'plan',lambda *a,**k:{'synthetic_plan_only':True})
    prepared=mp.prepare_build(collected['package_pin'],tmp_path/'build',base_dir=tmp_path/'runtime-origin',runtime=runtime,
        review_policy={'synthetic':True},goal_binding={'synthetic':True},max_seconds=30)
    spec=json.loads(Path(prepared['specification']['path']).read_text())
    _,actual,package=mb.load(spec['task'],tmp_path/'build')
    assert actual['runtime_base']==str(tmp_path/'runtime-origin')
    assert {'house.sty','instruction.txt','pdflatex'}<={p.name for p in mb.inputs(spec['task'],tmp_path/'build')}
    (tmp_path/'original/instruction.txt').write_text('A changed instruction is not recaptured.')
    with pytest.raises(ValueError):mb.load(spec['task'],tmp_path/'build')


def aux(rows):
    return ''.join(r'\zref@newlabel{'+name+r'}{\abspage{'+str(page)+'}}'+'\n' for name,page in rows)


@pytest.mark.parametrize('methods_counted',[True,False])
def test_main_pages_follow_all_physical_sections_and_source_venue_exclusion(methods_counted):
    segments=[{'id':'body','section':'results','start':'body-start','end':'body-end','counted':True},
        {'id':'references','section':None,'start':'refs-start','end':'refs-end','counted':False},
        {'id':'methods','section':'methods','start':'method-start','end':'method-end','counted':methods_counted}]
    raw=aux([('ravel-reference-start',9),('body-start',1),('body-end',8),('refs-start',9),('refs-end',10),('method-start',11),('method-end',14)])
    if methods_counted:
        with pytest.raises(ValueError,match='post-reference'):mb.page_census('Pages: 14\n',raw,max_main_pages=10,segments=segments)
    else:
        census=mb.page_census('Pages: 14\n',raw,max_main_pages=10,segments=segments)
        assert census['main_physical_pages']==list(range(1,9)) and census['main_text_pages']==8


def test_shared_page_and_unknown_physical_pages_cannot_hide_main_content():
    segments=[{'id':'body','section':'results','start':'b-start','end':'b-end','counted':True},
        {'id':'refs','section':None,'start':'r-start','end':'r-end','counted':False}]
    raw=aux([('ravel-reference-start',2),('b-start',1),('b-end',2),('r-start',2),('r-end',3)])
    result=mb.page_census('Pages: 4\n',raw,max_main_pages=3,segments=segments)
    assert result['main_physical_pages']==[1,2,4] and result['unclassified_pages_conservatively_counted']==[4]
    with pytest.raises(ValueError):mb.page_census('Pages: 4\n',raw,max_main_pages=2,segments=segments)


def test_custom_literal_headings_and_semantic_roles_drive_author_and_renderer(tmp_path,monkeypatch):
    def custom(request,value,base):
        fmt=json.loads(Path(request['formatting']['path']).read_text())
        fmt['sections']=[{'id':identity,'heading':heading,'semantics':roles,'placement':'main'} for identity,heading,roles in
            [('title','Exact title',['title']),('abstract','Abstract',['abstract']),
             ('introduction','Our introductory conventions',['strategy','methods']),('results','Measured outcomes',['results']),
             ('conclusions','Conclusions and remaining uncertainty',['limitations'])]]
        fmt['rules'][0]['value']=['title','abstract','introduction','results','conclusions']
        fmt['rules'].append({**fmt['rules'][0],'id':'order','kind':'section_order'})
        request['formatting']=put(base,'format.json',fmt)
        value['paragraphs'][2]['section']='introduction';value['paragraphs'][-1]['section']='conclusions'
    _,binding,collected=authored(tmp_path,monkeypatch,change=custom)
    choices=binding['spec']['nodes'][0]['parameters']['output_schema']['properties']['paragraphs']['items']['properties']['section']['enum']
    assert 'introduction' in choices and 'conclusions' in choices and 'methods' not in choices
    tex=Path(collected['package']['latex']['path']).read_text()
    assert r'\section*{Our introductory conventions}' in tex
    assert tex.index('Our introductory conventions')<tex.index('Measured outcomes')<tex.index('Conclusions and remaining uncertainty')
    mp.verify_author(collected['package'],base_dir=tmp_path/'note')


def vector_figure(request,value,base):
    image=put(base,'supplied.svg','<svg xmlns="http://www.w3.org/2000/svg"><text>toy</text></svg>')
    request['figures']=[{'id':'toy','image':image,'contract':put(base,'figure-contract.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None}]
    value['figures']=[{'id':'toy','caption':'Synthetic source diagram, no physical result.','citation_ids':[],'uncertainties':['Toy only.']}]


def test_vector_author_figure_without_conversion_custody_never_reaches_the_writer(tmp_path,monkeypatch):
    # An SVG or JPEG figure reaches the author only through a recorded conversion to a native view.
    with pytest.raises(ValueError,match='actual complete ordinary conversion'):authored(tmp_path,monkeypatch,change=vector_figure)
    assert not (tmp_path/'writer/graph').exists() and not (tmp_path/'note').exists()
    def unconverted(request,value,base):
        vector_figure(request,value,base);source=request['figures'][0]['image']
        request['author_visuals']=[{'figure_id':'toy','source':source,'image':source,'conversion':None}]
    with pytest.raises(ValueError,match='lacks conversion custody'):authored(tmp_path/'declared',monkeypatch,change=unconverted)
    assert not (tmp_path/'declared/writer/graph').exists() and not (tmp_path/'declared/note').exists()


@pytest.mark.parametrize('change',['latex','manuscript','author-request','figure','format-assessment'])
def test_rehashed_materialization_cannot_borrow_original_author_transport(tmp_path,monkeypatch,change):
    # A native PNG figure with the author's actual visual wire: the note this test rehashes
    # carries figure pixels, so every author consumer is bound to an observed presentation.
    from test_manuscript_revision_live_authority import visual_author
    _,_,binding,_,_=visual_author(tmp_path,monkeypatch)
    collected=mp.collect(binding,tmp_path/'note')
    assert len(collected['package']['figures'])==1
    mp.verify_author(collected['package'],base_dir=tmp_path/'note')
    package=deepcopy(collected['package'])
    if change=='author-request':
        original=json.loads(Path(binding['request']['path']).read_text());original['runtime']['model']='foreign'
        binding['request']=put(Path(binding['request']['path']).parent,'production-request.json',original)
        put(Path(package['author_binding']['path']).parent,'binding.json',binding)
        package['author_binding']=pin(Path(package['author_binding']['path']));package['production_request']=binding['request']
    else:
        key={'latex':'latex','manuscript':'manuscript','format-assessment':'formatting_assessment_pin'}.get(change)
        target=Path(package['figures'][0]['path'] if change=='figure' else package[key]['path'])
        target.write_bytes(target.read_bytes()+b'\nForged replacement content.\n')
        if change=='figure':package['figures'][0]=pin(target)
        else:package[key]=pin(target)
    put(tmp_path/'note','package.json',package)
    with pytest.raises(ValueError):mp.verify_author(package,base_dir=tmp_path/'note')


def template(request,value,base):
    before=r'\documentclass{article}\usepackage{zref-user,zref-abspage}\begin{document}'+'\n'
    claim='Supplied template makes an unqualified scientific assertion.\n'
    after='%RAVEL_BODY%\n'+r'\end{document}'+'\n';source=before+claim+after
    request['template']=put(base,'house.tex',source)
    value['template_units']=[{'id':identity,'kind':kind,'start':a,'end':b,'rendered_section':section,
        'evidence_ids':['score'] if kind=='claim' else [],'citation_ids':[],'method_ids':[],
        'uncertainties':['This is a fabricated supplied assertion; the independent reviewer must assess it.']} for identity,kind,a,b,section in
        [('preamble','other',0,len(before),None),('template-assertion','claim',len(before),len(before)+len(claim),'results'),
         ('tail','other',len(before)+len(claim),len(source),None)]]


def test_supplied_template_prose_is_presented_and_fully_censused(tmp_path,monkeypatch):
    _,binding,collected=authored(tmp_path,monkeypatch,change=template)
    package=collected['package'];ir=json.loads(Path(package['integrity_request']['path']).read_text())
    assert 'Supplied template makes' in Path(binding['presentation']['path']).read_text()
    assert any(c['id']=='template-assertion' for c in ir['claims'])
    assert package['template_census'][-1]['end']==len(Path(package['template']['path']).read_text())
    assert any(s['section']=='template-prefix' and s['counted'] for s in package['page_segments'])
    mp.verify_author(package,base_dir=tmp_path/'note')


@pytest.mark.parametrize('change',['gap','omit','body-straddle'])
def test_template_census_cannot_drop_prose_or_its_physical_classification(tmp_path,monkeypatch,change):
    r,state,value=setup(tmp_path/'original',monkeypatch);template(r,value,tmp_path/'original')
    if change=='gap':value['template_units'][1]['start']+=1
    elif change=='omit':value['template_units'].pop()
    else:value['template_units'][-1]['rendered_section']='results'
    binding=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path/'original',campaign=tmp_path/'campaign');completed(binding,state,value,monkeypatch)
    with pytest.raises(ValueError):mp.collect(binding,tmp_path/'note')


@pytest.mark.parametrize('suffix',['svg','jpeg'])
@pytest.mark.parametrize('change',[None,'source','preview','role','omit','foreign-build'])
def test_actual_normalized_preview_mandatory_and_original_media_gate_strict(tmp_path,monkeypatch,suffix,change):
    raw=b'<svg xmlns="http://www.w3.org/2000/svg"/>' if suffix=='svg' else b'\xff\xd8\xffINERT-IMAGE'
    original=tmp_path/('figure.'+suffix);original.write_bytes(raw);source=pin(original)
    preview=put(tmp_path,'preview.pdf','%PDF-INERT-NOT-RENDERED\n');receipt=put(tmp_path,'receipt.json',{'synthetic':True})
    binding={'rundir':str(tmp_path),'receipt':receipt,'result':receipt}
    built={'result':{'figure_conversions':[{'source':source,'pdf':preview}]},'proof_pins':[]}
    monkeypatch.setattr(mb,'verified_result',lambda *a,**k:deepcopy(built)) # Exact actual-build API shape, no native authority.
    manifest={'artifacts':[{'path':source['path'],'sha256':source['sha256'],'role':'source_output'},
        {'path':preview['path'],'sha256':preview['sha256'],'role':'figure'}],
        'visual_derivations':[{'source':source,'preview':preview,'build':binding}]}
    if change=='source':original.write_bytes(raw+b'CHANGED')
    if change=='preview':Path(preview['path']).write_text('%PDF-CHANGED\n')
    if change=='role':manifest['artifacts'][1]['role']='source_output'
    if change=='omit':manifest['artifacts'].pop()
    if change=='foreign-build':built['result']['figure_conversions']=[]
    if change:
        with pytest.raises(ValueError):fr._manuscript_visual_sources(tmp_path,manifest)
    else:
        allowed,_=fr._manuscript_visual_sources(tmp_path,manifest);assert allowed=={str(original):source}
    # Merely changing the caller's role cannot bypass the generic gate.
    with pytest.raises(ValueError):fr._visual_media(original,raw,'source_output')


def projection_fixture(root,monkeypatch):
    """Faithful public-byte reader with explicitly inert projection authority."""
    policy=put(root,'policy.json',{'synthetic_blind_domain':True})
    destination=root/'stream/native';destination.mkdir(parents=True)
    result={'status':'passed','delivery':{'score':4},'limitations':['Synthetic projection; no ROOT.']}
    paths=[destination.parent/'result.json',destination.parent/'root-stream-report.json',destination.parent/'root-stream-report.md']
    raws=[root_stream.encoded(result),root_stream.encoded({'status':'passed','delivery':result['delivery'],'physics_validated':False}),root_stream.report_bytes(result)]
    for p,raw in zip(paths,raws):p.write_bytes(raw)
    monkeypatch.setattr(root_stream,'blinding_check',lambda r,d,p,pol:{'status':'pass','sr_data_exposed':False,'checked_paths':p})
    return policy,[{'result':pin(paths[0]),'destination':str(destination),'public_paths':[str(p) for p in paths]}],pin(paths[0])


@pytest.mark.parametrize('change',[None,'missing-data','foreign-policy','foreign-product','no-review'])
def test_writer_blinding_lineage_keeps_projected_data_and_actual_review_boundary(tmp_path,monkeypatch,change):
    policy,projections,safe=projection_fixture(tmp_path,monkeypatch)
    artifact=put(tmp_path,'manuscript.md','Inert writer result: no real model or judgment.\n')
    package=put(tmp_path,'package.json',{'synthetic':True})
    admitted={'outputs':{artifact['path']:artifact},'data':[safe],'support':[],'machinery':[],'custody_only':[],
        'proof_pins':[package,artifact],'assessment':{'synthetic':True}}
    def verified(*a,**k):
        if change=='no-review':raise ValueError('actual independent integrity review remains unresolved')
        if k['base_dir']!=tmp_path or a[2]!=policy:raise ValueError('foreign policy')
        return deepcopy(admitted)
    monkeypatch.setattr(mp,'verified_products',verified) # Isolates final producer/data join; no fabricated real review.
    producer={'kind':'authored_manuscript','package':package,'bindings':[{'synthetic':True}]}
    data=[safe]
    if change=='missing-data':data=[]
    if change=='foreign-policy':policy={**policy,'sha256':'0'*64}
    if change=='foreign-product':admitted['outputs']={}
    evidence={'schema_version':2,'kind':'source_bound_final_blinding','policy':policy,'projections':projections,
        'lineage':[{'artifact':artifact,'producer':producer,'inputs':data}]}
    policy2={k:policy[k] for k in ('path','sha256')}
    rows=[{'path':artifact['path'],'sha256':artifact['sha256'],'role':'source_output'}]
    if change:
        with pytest.raises(ValueError):fr._source_blinding(tmp_path,evidence,policy2,rows)
    else:assert fr._source_blinding(tmp_path,evidence,policy2,rows)


def test_blinded_writer_cannot_enter_charged_graph_without_upstream_projections(tmp_path,monkeypatch):
    r,_,_=setup(tmp_path,monkeypatch);r['blinding_policy']=put(tmp_path,'policy.json',{'synthetic':True})
    with pytest.raises(ValueError,match='before its charged call'):mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert not (tmp_path/'writer/graph').exists()


def test_verified_writer_products_never_accept_missing_original_policy_or_review(tmp_path,monkeypatch):
    _,_,collected=authored(tmp_path,monkeypatch)
    policy=put(tmp_path,'policy.json',{'synthetic':True})
    with pytest.raises(ValueError,match='original-policy'):mp.verified_products(collected['package_pin'],[],policy,base_dir=tmp_path)


def test_blinded_support_cannot_enter_writer_before_current_source_role_acceptance(tmp_path,monkeypatch):
    request,_,_=setup(tmp_path,monkeypatch)
    request['blinding_policy']=put(tmp_path,'policy.json',{'synthetic':True})
    request['blinding_sources']=put(tmp_path,'projection-proof.json',{'lineage':[]})
    monkeypatch.setattr(fr,'_source_blinding',lambda *a,**k:[]) # Isolates pre-source role admission, not real projection safety.
    source=mp.prepare_source_review(request,tmp_path/'source',base_dir=tmp_path)
    assert not source['blinding_accepted'] and not source['execution_authorized']
    with pytest.raises(ValueError,match='pre-author'):mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    request['source_review']={'request':source['request'],'bindings':[{'synthetic':True}]}
    monkeypatch.setattr(ri,'assess',lambda *a,**k:{'scoped_integrity_review_complete':False})
    with pytest.raises(ValueError,match='unresolved'):mp.prepare_writer(request,tmp_path/'writer2',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert not (tmp_path/'writer/graph').exists() and not (tmp_path/'writer2/graph').exists()


def test_source_review_reconsumes_the_complete_context_not_a_safe_flag(tmp_path,monkeypatch):
    request,_,_=setup(tmp_path,monkeypatch)
    request['blinding_policy']=put(tmp_path,'policy.json',{'synthetic':True})
    request['blinding_sources']=put(tmp_path,'projection-proof.json',{'lineage':[]})
    monkeypatch.setattr(fr,'_source_blinding',lambda *a,**k:[])
    source=mp.prepare_source_review(request,tmp_path/'source',base_dir=tmp_path)
    request['source_review']={'request':source['request'],'bindings':[]}
    ir=json.loads(Path(source['request']['path']).read_text())
    text=Path(ir['manuscript']['path']).read_text()
    assert 'Missing fit: unresolved' in text and 'Fabricated engineering reference' in text
    assert ri.prepare(ir,base_dir=tmp_path)['items'][0]['id']=='blinding-source-census'
    ir['blinding_census']['support']=[];request['source_review']['request']=put(tmp_path/'source','changed-review.json',ir)
    with pytest.raises(ValueError,match='exact current'):mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')


@pytest.mark.parametrize('suffix',['svg','jpeg'])
def test_full_native_build_body_emits_bound_visual_preview_inert_only(tmp_path,monkeypatch,suffix):
    task,config,package=build_fixture(tmp_path,monkeypatch)
    image=tmp_path/('figure-toy.'+suffix)
    image.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><text>toy</text></svg>' if suffix=='svg' else b'\xff\xd8\xffINERT-NOT-A-DECODED-JPEG')
    package['figures']=[pin(image)]
    if suffix=='svg':
        converter=put(tmp_path,'rsvg-convert','INERT non-executable conversion stand-in.\n')
        config['runtime']['svg_converter']={k:converter[k] for k in ('path','sha256')}
    config['package']=put(tmp_path,'package.json',package);put(tmp_path,'config.json',config)
    monkeypatch.setattr(mb,'_approved',lambda *a,**k:{'max_seconds':30})
    calls=[]
    def inert(argv,out,bounds):
        out=Path(out);calls.append(deepcopy(argv))
        for name in ('native-stdout.log','native-stderr.log'):put(out,name,'INERT process text; no native call.\n')
        for name in ('native-process.json','native-execution.json'):put(out,name,{'synthetic':True})
        if Path(argv[0]).name=='rsvg-convert':Path(next(a.split('=',1)[1] for a in argv if a.startswith('--output='))).write_bytes(b'%PDF-INERT-PREVIEW\n')
        elif Path(argv[0]).name=='pdflatex':
            entry=Path(argv[-1]);preview=entry.name=='preview.tex';stem='preview' if preview else 'note'
            (out/(stem+'.pdf')).write_bytes(b'%PDF-INERT-PREVIEW-OR-PAPER\n')
            labels=absolute_aux()+aux([('main-start',1),('main-end',10),('refs-start',11),('refs-end',15)])
            put(out,stem+'.aux',labels);put(out,stem+'.log','INERT TeX log\n')
            consumed=[str(entry),str(tmp_path/'runtime/article.cls')]
            if preview:consumed.append(str(out.parent/'source'/image.name))
            put(out,stem+'.fls','\n'.join('INPUT '+x for x in consumed)+'\n')
        else:put(out,'native-stdout.log','Pages: 15\n')
        return {'command':deepcopy(argv),'synthetic':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',inert)
    result=mb.run(task,tmp_path,tmp_path/'output');row=result['figure_conversions'][0]
    assert row['source']==pin(image) and Path(row['pdf']['path']).read_bytes().startswith(b'%PDF-')
    assert row['kind']==('rsvg-pdf' if suffix=='svg' else 'pdflatex-jpeg-pdf')
    assert row['command'] in calls and result['scientific_acceptance'] is False
