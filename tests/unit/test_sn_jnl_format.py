"""AUTHORED, UNRUN. Pure recipe controls; asset bytes here are disclosed stand-ins.

No TeX/runtime/publisher or scientific qualification. Original author helper uses
explicit inert Graph/campaign transport; all original controls stay byte-exact.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_format as mf, manuscript_production as mp
from test_manuscript_production import setup, completed, put


def contract(root,monkeypatch):
    request,state,value=setup(root,monkeypatch,profile='epjc',stage='submission')
    fmt=json.loads(Path(request['formatting']['path']).read_text())
    fmt['render']['class']='sn-jnl'
    fmt['template_assets']=[put(root,'sn-jnl.cls','% Synthetic class bytes for pin admission only.\n'),
        put(root,'sn-mathphys-num.bst','% Synthetic BST bytes for pin admission only.\n')]
    return request,state,value,fmt


def test_native_current_epjc_reaches_real_author_materializer(tmp_path,monkeypatch):
    request,state,value,fmt=contract(tmp_path/'source',monkeypatch)
    request['formatting']=put(tmp_path/'source','format.json',fmt)
    value['paragraphs'] += [{'id':i,'section':i,'kind':'claim','text':text,
        'method_ids':[],'citation_ids':[],'evidence_ids':[],'uncertainties':[]}
        for i,text in [('authors','Literal Author'),('affiliations','Literal Institute')]]
    binding=mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    completed(binding,state,value,monkeypatch)
    package=mp.collect(binding,tmp_path/'note')['package'];tex=Path(package['latex']['path']).read_text()
    assert r'\documentclass[pdflatex,iicol,sn-mathphys-num]{sn-jnl}' in tex
    author = r'\author{\zlabel{ravel-segment-5-start}Literal Author\zlabel{ravel-segment-5-end}}'
    affiliation = r'\affil{\zlabel{ravel-segment-6-start}Literal Institute\zlabel{ravel-segment-6-end}}'
    assert tex.splitlines().count(author) == tex.splitlines().count(affiliation) == 1
    assert tex.count(r'\author{') == tex.count(r'\affil{') == 1
    assert tex.index(r'\title{') < tex.index(author) < tex.index(affiliation) < tex.index(r'\abstract{')
    assert tex.index(r'\abstract{')<tex.index(r'\maketitle')
    assert r'\begin{abstract}' not in tex and '{svjour3}' not in tex
    assert r'\usepackage{zref-user,zref-abspage}' in tex
    mp.verify_author(package,base_dir=tmp_path/'note')
    assert package['scientific_acceptance'] is False and package['execution_authorized'] is False


@pytest.mark.parametrize('change',['profile','front-order','citation','class-missing','bst-missing','changed-bytes'])
def test_source_recipe_refuses_incompatible_policy_or_actual_asset_drift(tmp_path,monkeypatch,change):
    request,state,value,fmt=contract(tmp_path/'source',monkeypatch)
    if change=='profile':fmt['profile']='nature'
    elif change=='front-order':fmt['render']['frontmatter']='abstract-before-title'
    elif change=='citation':fmt['render']['citation_style']='author-year'
    elif change=='class-missing':fmt['template_assets']=fmt['template_assets'][1:]
    elif change=='bst-missing':fmt['template_assets']=fmt['template_assets'][:1]
    elif change=='changed-bytes':Path(fmt['template_assets'][0]['path']).write_text('different class')
    request['formatting']=put(tmp_path/'source','format.json',fmt)
    with pytest.raises(ValueError):
        mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert not (tmp_path/'writer/graph').exists()


def test_all_literal_author_affiliation_rosters_preserved_without_invented_associations():
    front={k:[{'latex':v} for v in values] for k,values in {'title':['Exact title'],
        'authors':['Alice','Bob'],'affiliations':['Institute A','Institute B'],
        'abstract':['First paragraph.','Second paragraph.']}.items()}
    c={'profile':'epjc','render':{'class':'sn-jnl'}}
    text=mf.frontmatter(front,c,escape=lambda s:s)
    assert text==('\n'.join([r'\title{Exact title}',r'\author{Alice}',r'\author{Bob}',
        r'\affil{Institute A}',r'\affil{Institute B}',
        r'\abstract{First paragraph. Second paragraph.}',r'\maketitle']))
    assert '\\author[' not in text and '\\affil[' not in text


@pytest.mark.parametrize('line_numbers',[False,True])
def test_native_line_number_switch_uses_original_class_vruler_not_generic_linenumbers(line_numbers):
    c={'render':{'class':'sn-jnl','line_numbers':line_numbers,'graphics':'inline'}}
    text=mf.template_source(c,None);runtime=mf.required_runtime(c,has_svg=True)
    assert ('sn-mathphys-num,lineno' in text)==line_numbers
    assert r'\usepackage{lineno}' not in text and r'\linenumbers' not in text
    assert ('vruler.sty' in runtime['asset_basenames'])==line_numbers
    assert 'lineno.sty' not in runtime['asset_basenames']
    assert {'sn-jnl.cls','sn-mathphys-num.bst','article.cls','geometry.sty','natbib.sty'}<=set(runtime['asset_basenames'])
    assert runtime['binaries']==['pdflatex','pdfinfo','rsvg-convert']


@pytest.mark.parametrize('cls,expected',[('svjour3',r'\documentclass[epjc3]{svjour3}'),
    ('revtex4-2',r'\documentclass[aps,prd,preprint]{revtex4-2}'),
    ('article',r'\documentclass[11pt]{article}')])
def test_old_native_preambles_remain_literal(cls,expected):
    text=mf.template_source({'render':{'class':cls,'graphics':'inline','line_numbers':False}},None)
    assert text.startswith(expected) and '{sn-jnl}' not in text


def test_old_explicit_source_template_path_byte_equal():
    supplied='\\usepackage{zref-user,zref-abspage}\n%RAVEL_BODY%\n'
    assert mf.template_source({'render':{'class':'source-template'}},supplied)==supplied
