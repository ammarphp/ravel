"""Authored NOT RUN: literal source controls and inert native-return stand-ins.

No TeX executable, provider, physics or genuine approval is invoked. The fake
compiler emits labelled synthetic PDF/recorder bytes to test the true consumer.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics import manuscript_build as mb, reinterpret_db
from ravel.workflow import manuscript_format as mf, manuscript_production as mp, science, state_io


def put(root,name,value):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value,allow_nan=False)+'\n')
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def fixture(root,monkeypatch):
    # This inherited build-only fixture isolates renderer/recorder gates. Real
    # writer authentication is exercised without this stand-in in the connected
    # six-finding controls. This never admits an actual writer or ordinary job.
    monkeypatch.setattr(mp,'verify_author',lambda *a,**k:{'synthetic_build_fixture_only':True})
    render={'class':'article','frontmatter':'title-before-abstract','graphics':'inline','line_numbers':False,
        'appendices':'after-references','citation_style':'numeric-brackets','post_reference_sections':[],'quantitative_position':'main'}
    fmt=put(root,'format.json',{'schema_version':1,'profile':'research-paper','stage':'draft','article_type':'synthetic control',
        'render':render,'rules':[{'id':'pages','kind':'max_main_pages','scope':'main','value':10,'origin':'user','source_basis':None}], 'template_assets':[]})
    assessment={'rules':[{'rule':{'id':'pages','kind':'max_main_pages','value':10},'state':'pending_compiled_page_boundary'}]}
    package={'kind':'authored-manuscript-package','profile':'research-paper','scientific_acceptance':False,'execution_authorized':False,
        'latex':put(root,'note.tex','Synthetic source; never compiled.\n'),'manuscript':put(root,'manuscript.md','Synthetic fixture only.\n'),
        'integrity_request':put(root,'integrity.json',{'synthetic':True}),'model_provenance':put(root,'model.json',{'synthetic':True}),
        'formatting_contract':fmt,'formatting_assessment':assessment,'formatting_assessment_pin':put(root,'assessment.json',assessment),
        'source_base':str(root),'page_segments':[{'id':'main','section':'results','start':'main-start','end':'main-end','counted':True},{'id':'refs','section':None,'start':'refs-start','end':'refs-end','counted':False}],
        'author_binding':put(root,'binding.json',{'synthetic':True}),'figures':[],'template_assets':[],'input_pins':[]}
    pkg=put(root,'package.json',package)
    tree=root/'runtime';tree.mkdir()
    for name in ['pdflatex.fmt','zref-user.sty','zref-abspage.sty','article.cls','geometry.sty','graphicx.sty','synthetic.tfm']:
        put(tree,name,'Non-executable synthetic runtime asset: '+name+'\n')
    manifest=put(root,'runtime-manifest.json',{'schema_version':1,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tree.iterdir()}})
    compiler=put(root,'pdflatex','INERT non-executable compiler stand-in\n');pdfinfo=put(root,'pdfinfo','INERT non-executable pdfinfo stand-in\n')
    runtime={'engine':'pdflatex','compiler':{k:compiler[k] for k in ('path','sha256')},'pdfinfo':{k:pdfinfo[k] for k in ('path','sha256')},
        'svg_converter':None,'asset_trees':[{'root':str(tree),'manifest':{k:manifest[k] for k in ('path','sha256')}}],'max_ram_mib':512}
    config={'schema_version':1,'package':pkg,'runtime':runtime,'runtime_base':str(root),'max_seconds':30,'max_ram_mib':512,'max_output_bytes':2*1024*1024,'max_main_pages':10}
    cfg=put(root,'config.json',config)
    return {'config':cfg['path']},config,package


def absolute_aux(reference=11,appendix=None):
    text=r'\zref@newlabel{ravel-reference-start}{\default{999}\page{999}\abspage{'+str(reference)+'}}\n'
    if appendix is not None:text+=r'\zref@newlabel{ravel-appendix-start}{\abspage{'+str(appendix)+'}}\n'
    return text.replace('\\n','\n')


def test_actual_physical_pages_not_logical_source_length():
    pages=mb.page_census('Pages: 15\n',absolute_aux(),max_main_pages=10)
    assert pages['main_text_pages']==10 and pages['reference_and_appendix_pages']==5
    with pytest.raises(ValueError,match='ceiling'):mb.page_census('Pages: 15\n',absolute_aux(12),max_main_pages=10)
    with pytest.raises(ValueError,match='physical-page'):mb.page_census('Pages: 15\n',r'\zref@newlabel{ravel-reference-start}{\page{11}}',max_main_pages=10)


@pytest.mark.parametrize('appendix,expected',[(8,7),(14,10)])
def test_appendix_before_or_after_references_kept_separate(appendix,expected):
    assert mb.page_census('Pages: 16\n',absolute_aux(11,appendix),max_main_pages=10)['main_text_pages']==expected


@pytest.mark.parametrize('bad',['missing','duplicate','past-end','no-pages'])
def test_native_boundary_census_refuses_ambiguous_results(bad):
    aux=absolute_aux();info='Pages: 15\n'
    if bad=='missing':aux=''
    if bad=='duplicate':aux+=aux
    if bad=='past-end':aux=absolute_aux(16)
    if bad=='no-pages':info='Synthetic stdout without PDF census\n'
    with pytest.raises(ValueError):mb.page_census(info,aux,max_main_pages=10)


def test_real_ordinary_intake_lists_complete_runtime_and_author_provenance(tmp_path,monkeypatch):
    task,c,p=fixture(tmp_path,monkeypatch)
    spec={'mode':'manuscript-build','task':task,'max_seconds':30}
    files=science.task_inputs(spec,tmp_path)
    assert {Path(x).name for x in files}>={'note.tex','binding.json','model.json','pdflatex','pdfinfo','pdflatex.fmt','synthetic.tfm','runtime-manifest.json'}
    assert mb.execution_seconds(task,tmp_path)==30
    with pytest.raises(ValueError):science.task_inputs({**spec,'max_seconds':29},tmp_path)


@pytest.mark.parametrize('change',['missing-style','unlisted-leaf','changed-font','alias','missing-font','unqualified-svg'])
def test_required_full_method_assets_are_not_optional_metadata(tmp_path,monkeypatch,change):
    task,c,p=fixture(tmp_path,monkeypatch);tree=tmp_path/'runtime'
    if change=='missing-style':(tree/'article.cls').unlink()
    if change=='unlisted-leaf':(tree/'extra.sty').write_text('new')
    if change=='changed-font':(tree/'synthetic.tfm').write_text('changed')
    if change=='alias':(tree/'alias.sty').symlink_to(tree/'article.cls')
    if change=='missing-font':
        (tree/'synthetic.tfm').unlink();manifest=json.loads((tmp_path/'runtime-manifest.json').read_text());manifest['files'].pop('synthetic.tfm')
        m=put(tmp_path,'runtime-manifest.json',manifest);c['runtime']['asset_trees'][0]['manifest']={k:m[k] for k in ('path','sha256')};put(tmp_path,'config.json',c)
    if change=='unqualified-svg':
        p['figures']=[put(tmp_path,'figure-one.svg','<svg xmlns="http://www.w3.org/2000/svg"/>')];c['package']=put(tmp_path,'package.json',p);put(tmp_path,'config.json',c)
    with pytest.raises(ValueError):mb.inputs(task,tmp_path)


def inert_compiler(monkeypatch,root,*,failure=None):
    """Real build-body consumer, no process or actual approval."""
    monkeypatch.setattr(mb,'_approved',lambda *a,**k:{'max_seconds':30})
    calls=[]
    def fake(argv,out,c):
        out=Path(out);out.mkdir(parents=True,exist_ok=True);calls.append(deepcopy(argv))
        put(out,'native-stdout.log','Synthetic native stdout\n');put(out,'native-stderr.log','Synthetic wrapper stderr\n')
        put(out,'native-process.json',{'synthetic':True});put(out,'native-execution.json',{'synthetic':True})
        if Path(argv[0]).name=='pdflatex':
            if failure=='compile':raise ValueError('synthetic compiler failure')
            (out/'note.pdf').write_bytes(b'%PDF-SYNTHETIC-CONTROL-NOT-A-REAL-PDF\n')
            put(out,'note.aux',absolute_aux()+''.join(r'\zref@newlabel{'+k+r'}{\abspage{'+str(v)+'}}\n' for k,v in [('main-start',1),('main-end',10),('refs-start',11),('refs-end',15)]).replace('\\n','\n'));put(out,'note.log','Synthetic TeX log\n')
            inputs=[str(out/'note.tex'),str(root/'runtime/article.cls')]
            if failure=='undeclared':inputs.append(str(root/'private.sty'))
            if failure=='mutated-note':(out/'note.tex').write_text('changed')
            if failure=='mutated-font':(root/'runtime/synthetic.tfm').write_text('changed')
            put(out,'note.fls','\n'.join('INPUT '+x for x in inputs)+'\n')
        else:put(out,'native-stdout.log','Pages: 15\n')
        return {'command':deepcopy(argv),'synthetic':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    return calls


def test_full_build_body_recorder_census_and_durable_result_inert_only(tmp_path,monkeypatch):
    task,c,p=fixture(tmp_path,monkeypatch);calls=inert_compiler(monkeypatch,tmp_path)
    r=mb.run(task,tmp_path,tmp_path/'output')
    assert len(calls)==3 and all('-no-shell-escape' in a and '-recorder' in a for a in calls[:2])
    assert len(r['tex_input_observations'])==2 and r['pages']['main_text_pages']==10
    assert state_io.read_json(tmp_path/'output/manuscript-build.json')==r
    assert not r['scientific_acceptance'] and not r['visual_style_accepted'] and not r['parent_task_accepted']


@pytest.mark.parametrize('failure',['compile','undeclared','mutated-note','mutated-font'])
def test_native_return_cannot_hide_failed_compile_or_source_consumption(tmp_path,monkeypatch,failure):
    task,c,p=fixture(tmp_path,monkeypatch);put(tmp_path,'private.sty','Unadmitted private file\n');inert_compiler(monkeypatch,tmp_path,failure=failure)
    with pytest.raises(ValueError):mb.run(task,tmp_path,tmp_path/'output')
    assert not (tmp_path/'output/manuscript-build.json').exists()


def test_pdf_file_never_grants_ordinary_authority(tmp_path,monkeypatch):
    task,c,p=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='ordinary approved'):mb.run(task,tmp_path,tmp_path/'unapproved')


def test_exact_delivery_only_policy_cannot_be_relabelled_scientific():
    spec={'schema_version':2,'max_attempts':1,'review_policy':{'policy':{'max_redos':0,'claim_scopes':{mb.SCOPE:{'actions':['delivery']}}}}}
    mb.validate_scope(spec)
    for change in ('attempts','redo','scientific'):
        bad=deepcopy(spec)
        if change=='attempts':bad['max_attempts']=2
        if change=='redo':bad['review_policy']['policy']['max_redos']=1
        if change=='scientific':bad['review_policy']['policy']['claim_scopes'][mb.SCOPE]['actions']=['scientific']
        with pytest.raises(ValueError):mb.validate_scope(bad)
