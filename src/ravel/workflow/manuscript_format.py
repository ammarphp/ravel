"""Source-bound venue and arbitrary user formatting, with honest pending rules.

EPJC, PRD and Nature are separate profiles/stages/article types. A page-limited
note takes its page ceiling, counted sections, figure/table limits and required
sections from a supplied rule pack; no venue or challenge rule is a constant
here. There is no generic publisher conformance default. A compiler/PDF parser can check a
subset; actual visual and semantic rules remain material independent questions.
"""
from copy import deepcopy
import re
from . import candidate_experiments as ce, report_integrity as custody

PROFILES={'internal-note','research-paper','epjc','prd','nature','page-limited-note','user'}
KINDS={'required_sections','section_order','max_title_characters','max_abstract_words','max_main_words',
    'min_abstract_words','line_numbers','graphics_in_compilation','max_figures','max_tables','max_references','max_main_pages','numeric_appearance','reference_titles','exact_template',
    'layout_instruction','caption_same_page','font_requirement','bibliography_style','appendix_policy',
    'statistical_reporting','authorship_disclosure','instruction','excluded_sections'}

SEMANTICS=('title','abstract','strategy','background','validation','methods','results',
    'discovery-sensitivity','run2-comparison','limitations','appendix','authors','affiliations',
    'data-availability','code-availability','acknowledgements','funding','author-contributions',
    'competing-interests','additional-information','extended-data-legends','other')


def section_layout(contract):
    """Finite literal display/order/semantic mapping, never inferred claim truth.

    Explicit custom headings are preserved. The conventional Introduction and
    Conclusions display names have documented content slots; arbitrary names
    remain possible through the complete source-bound sections mapping.
    """
    required=[]
    for rule in contract['rules']:
        if rule['kind'] in {'required_sections','section_order'}:
            for identity in rule['value']:
                if identity not in required:required.append(identity)
    rows=deepcopy(contract.get('sections'))
    if rows is None:
        rows=[]
        for identity in [*SEMANTICS[:-1],*[x for x in required if x not in SEMANTICS]]:
            aliases={'introduction':['strategy','methods'],'conclusions':['limitations']}
            roles=aliases.get(identity,[identity] if identity in SEMANTICS else ['other'])
            rows.append({'id':identity,'heading':identity.replace('-',' ').replace('_',' ').title(),
                'semantics':roles,'placement':'appendix' if identity=='appendix' else
                    'post-references' if identity in contract['render']['post_reference_sections'] else 'main'})
        post=contract['render']['post_reference_sections']
        rows=[r for r in rows if r['placement']=='main']+[next(r for r in rows if r['id']==identity) for identity in post]+[r for r in rows if r['placement']=='appendix']
    if type(rows) is not list or not 1<=len(rows)<=160:raise ValueError('complete bounded section mapping required')
    ids=set()
    for row in rows:
        ce.keys(row,['id','heading','semantics','placement']);ce.identity(row['id']);custody._text(row['heading'],256)
        if row['id'] in ids or row['placement'] not in {'main','post-references','appendix'}:
            raise ValueError('distinct declared section placement required')
        ids.add(row['id'])
        if (type(row['semantics']) is not list or not row['semantics'] or
                len(set(row['semantics']))!=len(row['semantics']) or not set(row['semantics'])<=set(SEMANTICS)):
            raise ValueError('explicit semantic content obligations required')
        if len(set(row['semantics']) & {'title','authors','affiliations','abstract'})>1:
            raise ValueError('frontmatter section needs at most one native role')
    if not set(required)<=ids or not set(contract['render']['post_reference_sections'])<=ids:
        raise ValueError('requested section or post-reference mapping missing')
    if not {'title','abstract','methods','results','limitations'}<=set(s for row in rows for s in row['semantics']):
        raise ValueError('complete note content must be represented, including methods and limitations')
    if [r['id'] for r in rows if r['placement']=='post-references']!=contract['render']['post_reference_sections']:
        raise ValueError('literal post-reference order and section placement differ')
    if contract['render']['appendices']=='none' and any(r['placement']=='appendix' for r in rows) and contract.get('sections') is not None:
        raise ValueError('declared appendix placement conflicts with source layout')
    for rule in contract['rules']:
        if rule['kind']=='excluded_sections' and not set(rule['value'])<=ids:
            raise ValueError('counting exclusion names a foreign section')
    return rows


def counted(contract, section, metric):
    row=next((r for r in section_layout(contract) if r['id']==section),None)
    if row is None:raise ValueError('section not in the actual formatting map')
    if row['placement']=='appendix':return False
    if metric=='words' and set(row['semantics'])<= {'title','abstract','authors','affiliations'}:return False
    scope='main-pages' if metric=='pages' else 'main-words'
    return not any(r['kind']=='excluded_sections' and r['scope']==scope and section in r['value'] for r in contract['rules'])


def load(pin,base,consumed):
    value=custody._json(custody._raw(pin,base,consumed))
    ce.keys(value,['schema_version','profile','stage','article_type','render','rules','template_assets']+[k for k in ('sections','rule_pack') if k in value])
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['profile'] not in PROFILES:
        raise ValueError('explicit venue/user formatting contract required')
    for k in ('stage','article_type'):custody._text(value[k])
    render=value['render'];ce.keys(render,['class','frontmatter','graphics','line_numbers','appendices','citation_style','post_reference_sections','quantitative_position'])
    if (render['class'] not in {'article','revtex4-2','svjour3','sn-jnl','source-template'} or render['frontmatter'] not in {'title-before-abstract','abstract-before-title'}
            or render['graphics'] not in {'inline','separate'} or type(render['line_numbers']) is not bool
            or render['appendices'] not in {'none','before-references','after-references'} or render['citation_style'] not in {'numeric-brackets','numeric-superscript','author-year'}):raise ValueError('explicit supported native rendering contract required')
    post=render['post_reference_sections']
    if render['quantitative_position'] not in {'main','appendix'} or (render['quantitative_position']=='appendix' and render['appendices']=='none'):
        raise ValueError('complete quantitative report needs an explicit admitted main/appendix location')
    if type(post) is not list or len(post)!=len(set(post)) or any(type(x) is not str for x in post):raise ValueError('explicit finite post-reference section order required')
    if value['profile']=='prd' and render['class'] not in {'revtex4-2','source-template'}:raise ValueError('PRD native class or authenticated source template required')
    if value['profile']=='epjc' and render['class'] not in {'svjour3','sn-jnl','source-template'}:raise ValueError('EPJC native class or authenticated source template required')
    if value['profile']=='nature' and value['stage']=='final' and (render['graphics']!='separate' or render['citation_style']!='numeric-superscript'):raise ValueError('Nature final graphics separate and numeric superscript citations required')
    if value['profile']=='nature' and value['stage']=='final' and post!=['methods','data-availability','code-availability','acknowledgements','funding','author-contributions','competing-interests','additional-information','extended-data-legends']:
        raise ValueError('Nature final native sequence requires explicit post-reference methods and declarations')
    if render['class']=='sn-jnl':
        if (value['profile']!='epjc' or render['frontmatter']!='title-before-abstract' or
                render['citation_style']!='numeric-brackets'):
            raise ValueError('native sn-jnl recipe requires explicit EPJC title/abstract and numeric reference policy')
        names=[asset['path'].replace('\\','/').rsplit('/',1)[-1] for asset in value['template_assets']]
        if not {'sn-jnl.cls','sn-mathphys-num.bst'}<=set(names):
            raise ValueError('actual source-bound sn-jnl class and selected numeric bibliography style required')
    ids=set()
    for rule in custody._rows(value['rules'],'whole publisher and user rule census',empty=False):
        ce.keys(rule,['id','kind','scope','value','origin','source_basis']);ce.identity(rule['id'])
        if rule['id'] in ids or rule['kind'] not in KINDS:raise ValueError('distinct typed formatting rules required')
        ids.add(rule['id']);custody._text(rule['scope'])
        if rule['origin'] not in {'publisher','challenge','user'}:raise ValueError('located formatting instruction origin required')
        if rule['source_basis'] is None:
            if rule['origin']!='user':raise ValueError('publisher/challenge rule requires actual source content')
        else:custody._located(rule['source_basis'],base,consumed)
        if (rule['kind'].startswith('max_') or rule['kind']=='min_abstract_words') and (type(rule['value']) is not int or rule['value']<=0):raise ValueError('positive formatting count bound required')
        if rule['kind'] in {'required_sections','section_order','excluded_sections'}:
            if type(rule['value']) is not list or not rule['value'] or len(set(rule['value']))!=len(rule['value']) or any(type(x) is not str for x in rule['value']):raise ValueError('ordered full section IDs required')
        elif rule['kind'] in {'numeric_appearance','reference_titles','exact_template','caption_same_page','line_numbers','graphics_in_compilation'}:
            if type(rule['value']) is not bool:raise ValueError('literal formatting requirement required')
        elif not (rule['kind'].startswith('max_') or rule['kind']=='min_abstract_words'):custody._text(rule['value'])
        if rule['kind']=='excluded_sections':
            if rule['scope'] not in {'main-pages','main-words'}:raise ValueError('explicit physical/word counting exclusion required')
            if rule['origin']!='user' and rule['source_basis'] is None:raise ValueError('source-defined counting exclusion required')
    for asset in custody._rows(value['template_assets'],'complete actual template source assets'):
        custody._raw(asset,base,consumed)
    if value['profile']=='page-limited-note' and 'rule_pack' not in value:
        raise ValueError('page-limited note requires a supplied rule pack')
    if 'rule_pack' in value:_apply_rule_pack(value,rule_pack(value,base,consumed))
    section_layout(value) # Reject inconsistent source mappings before a charged author call.
    return value


RULE_PACK_FIELDS=('schema_version','kind','id','title','origin','source_basis','max_main_pages',
    'excluded_sections','max_figures','max_tables','required_semantics','main_text_semantics',
    'allow_user_count_exclusions','requires_supplied_requirements')


def validate_rule_pack(value):
    """A supplied page-limited note rule pack: limits and section obligations as data."""
    ce.keys(value,list(RULE_PACK_FIELDS))
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['kind']!='note-rule-pack':
        raise ValueError('note-rule-pack/v1 required')
    ce.identity(value['id']);custody._text(value['title'],256)
    if value['origin'] not in {'publisher','challenge','user'}:raise ValueError('rule pack origin must be publisher, challenge or user')
    if value['origin']!='user' and value['source_basis'] is None:
        raise ValueError('publisher or challenge rule pack requires its located source text')
    for key in ('max_main_pages','max_figures','max_tables'):
        if value[key] is not None and (type(value[key]) is not int or value[key]<=0):
            raise ValueError('rule pack limits are positive integers or null')
    for key in ('excluded_sections','required_semantics','main_text_semantics'):
        rows=value[key]
        if type(rows) is not list or len(set(rows))!=len(rows) or any(type(x) is not str or not x for x in rows):
            raise ValueError('rule pack section lists must be distinct identifiers')
    unknown=(set(value['required_semantics'])|set(value['main_text_semantics']))-set(SEMANTICS)
    if unknown:raise ValueError('rule pack names unknown semantic roles: '+', '.join(sorted(unknown)))
    if not set(value['main_text_semantics'])<=set(value['required_semantics'])|{'title','abstract','methods','results','limitations'}:
        raise ValueError('main-text roles must also be required roles')
    for key in ('allow_user_count_exclusions','requires_supplied_requirements'):
        if type(value[key]) is not bool:raise ValueError('rule pack switches must be literal booleans')
    return value


def rule_pack(contract,base,consumed):
    """Read and validate the contract's pinned rule pack, or None."""
    pin=contract.get('rule_pack')
    if pin is None:return None
    value=validate_rule_pack(custody._json(custody._raw(pin,base,consumed)))
    if value['source_basis'] is not None:custody._located(value['source_basis'],base,consumed)
    return value


def _apply_rule_pack(contract,pack):
    """A contract may tighten a supplied rule pack but never weaken it."""
    rules=contract['rules']
    for kind,key in (('max_main_pages','max_main_pages'),('max_figures','max_figures'),('max_tables','max_tables')):
        if pack[key] is None:continue
        if not any(r['kind']==kind and r['value']<=pack[key] for r in rules):
            raise ValueError(f'rule pack {key} ceiling of {pack[key]} is missing or weakened')
    if not pack['allow_user_count_exclusions'] and any(r['kind']=='excluded_sections' and r['origin']=='user' for r in rules):
        raise ValueError('user counting exclusions cannot weaken this rule pack')
    represented={s for row in section_layout(contract) for s in row['semantics']}
    missing=set(pack['required_semantics'])-represented
    if missing:raise ValueError('rule pack sections are not mapped: '+', '.join(sorted(missing)))


def note_requirements(contract,base):
    """Semantic roles a note must carry, and those that must stay in the main text."""
    base_roles={'title','abstract','methods','results','limitations'}
    pack=rule_pack(contract,base,{})
    if pack is None:
        return {'required':base_roles,'main_text':set(),'requires_supplied_requirements':False,'rule_pack':None}
    return {'required':base_roles|set(pack['required_semantics']),'main_text':set(pack['main_text_semantics']),
            'requires_supplied_requirements':pack['requires_supplied_requirements'],'rule_pack':pack}


def build_note_contract(pack,pack_pin,*,stage,article_type,render,source_basis=None,template_assets=(),sections=None,extra_rules=()):
    """Write a formatting contract whose limits and section rules come from one rule pack."""
    validate_rule_pack(pack)
    origin=pack['origin'];basis=source_basis if source_basis is not None else pack['source_basis']
    if origin!='user' and basis is None:raise ValueError('publisher or challenge rule needs located source text')
    rules=[]
    def rule(identity,kind,scope,value):
        rules.append({'id':identity,'kind':kind,'scope':scope,'value':value,'origin':origin,'source_basis':basis})
    for kind in ('max_main_pages','max_figures','max_tables'):
        if pack[kind] is not None:rule(kind.replace('_','-'),kind,'main-text' if kind=='max_main_pages' else 'document',pack[kind])
    required=[*['title','abstract'],*[r for r in pack['required_semantics'] if r not in {'title','abstract'}]]
    rule('required-sections','required_sections','main',[*required,*[r for r in ('methods','results','limitations') if r not in required]])
    if pack['excluded_sections']:rule('page-count-exclusions','excluded_sections','main-pages',list(pack['excluded_sections']))
    rules.extend(deepcopy(list(extra_rules)))
    contract={'schema_version':1,'profile':'page-limited-note','stage':stage,'article_type':article_type,
        'render':deepcopy(render),'rules':rules,'template_assets':list(template_assets),'rule_pack':dict(pack_pin)}
    if sections is not None:contract['sections']=deepcopy(sections)
    return contract


def assess(contract,value,*,template,compiled_pages=None):
    paragraphs=value['paragraphs'];figures=value['figures'];citations=value['citations']
    order=[]
    for p in paragraphs:
        if p['section'] not in order:order.append(p['section'])
    texts={k:' '.join(p['text'] for p in paragraphs if p['section']==k) for k in order}
    rows=[]
    for rule in contract['rules']:
        k=rule['kind'];expected=rule['value'];observed=None;state='pending_actual_visual_or_semantic_review'
        if k=='required_sections':observed=order;state='mechanically_passed' if set(expected)<=set(order) else 'mechanically_failed'
        elif k=='section_order':
            observed=[x for x in order if x in expected];state='mechanically_passed' if observed==expected else 'mechanically_failed'
        elif k=='max_title_characters':observed=sum(len(p['text']) for p in paragraphs if 'title' in next(r for r in section_layout(contract) if r['id']==p['section'])['semantics'])
        elif k=='min_abstract_words':observed=sum(len(p['text'].split()) for p in paragraphs if 'abstract' in next(r for r in section_layout(contract) if r['id']==p['section'])['semantics']);state='mechanically_passed' if observed>=expected else 'mechanically_failed'
        elif k=='line_numbers':observed=contract['render']['line_numbers'];state='source_render_join_only' if observed==expected else 'mechanically_failed'
        elif k=='graphics_in_compilation':observed=contract['render']['graphics']=='inline';state='source_render_join_only' if observed==expected else 'mechanically_failed'
        elif k=='max_abstract_words':observed=sum(len(p['text'].split()) for p in paragraphs if 'abstract' in next(r for r in section_layout(contract) if r['id']==p['section'])['semantics'])
        elif k=='max_main_words':observed=sum(len(p['text'].split()) for p in paragraphs if counted(contract,p['section'],'words'))+(len(value.get('quantitative_text','').split()) if contract['render']['quantitative_position']=='main' else 0)+sum(len(p['text'].split()) for p in value.get('template_visible_text',[]) if counted(contract,p['section'],'words'))
        elif k=='max_figures':observed=len(figures)
        elif k=='max_tables':
            if 'tables' in value:observed=len(value['tables'])
            else:state='pending_actual_visual_or_semantic_review'
        elif k=='max_references':observed=len(citations)
        elif k=='max_main_pages':
            if compiled_pages is not None:observed=compiled_pages['main_text_pages']
            else:state='pending_compiled_page_boundary'
        elif k=='reference_titles':observed=all(bool(c['bibliography']['title'].strip()) for c in citations);state='mechanically_passed' if observed or not expected else 'mechanically_failed'
        elif k=='numeric_appearance':
            observed=value.get('citation_style')=='numeric-appearance';state='mechanically_passed' if observed or not expected else 'mechanically_failed'
        elif k=='exact_template':
            observed=template is not None
            # A declared template is only an exact asset join; venue authenticity is reviewed.
            state='source_asset_join_only' if observed else 'unmet_actual_template' if expected else 'not_required'
        if k.startswith('max_') and observed is not None:state='mechanically_passed' if observed<=expected else 'mechanically_failed'
        rows.append({'rule':deepcopy(rule),'state':state,'observed':observed,
            'limit':'Literal counts/source assets only; publisher applicability/layout/scientific interpretation require actual evidence-bound independent review.'})
    return {'kind':'manuscript-format-assessment','profile':contract['profile'],'stage':contract['stage'],'article_type':contract['article_type'],
        'rules':rows,'mechanical_failures':[r['rule']['id'] for r in rows if r['state']=='mechanically_failed'],
        'pending_rule_ids':[r['rule']['id'] for r in rows if r['state'] not in {'mechanically_passed','not_required'}],
        'complete_publisher_or_user_conformance':False,'visual_review_complete':False,'publication_accepted':False}


def template_source(contract, supplied):
    """Native class recipe or exact provided template; neither implies venue acceptance."""
    render=contract['render']
    if supplied is not None:
        if r'\usepackage{zref-user,zref-abspage}' not in supplied:raise ValueError('source template must bind native absolute-page census packages explicitly')
        return supplied
    if render['class']=='source-template':raise ValueError('actual source template unavailable')
    if render['class']=='article':preamble=r'\documentclass[11pt]{article}\usepackage[margin=25mm]{geometry}'
    elif render['class']=='revtex4-2':preamble=r'\documentclass[aps,prd,preprint]{revtex4-2}'
    elif render['class']=='sn-jnl':
        options='pdflatex,iicol,sn-mathphys-num'+(',lineno' if render['line_numbers'] else '')
        preamble=r'\documentclass['+options+r']{sn-jnl}'
    else:preamble=r'\documentclass[epjc3]{svjour3}'
    preamble+=r'\usepackage{zref-user,zref-abspage}'
    if render['graphics']=='inline':preamble+=r'\usepackage{graphicx}'
    if render['line_numbers'] and render['class']!='sn-jnl':preamble+=r'\usepackage{lineno}'
    return preamble+r'\begin{document}'+('\n'+r'\linenumbers' if render['line_numbers'] and render['class']!='sn-jnl' else '')+'\n%RAVEL_BODY%\n'+r'\end{document}'+'\n'


def frontmatter(front, contract, *, escape):
    def latex(key):return ' '.join(x['latex'] for x in front.get(key,[]))
    title=r'\title{'+latex('title')+'}'
    cls=contract['render']['class']
    if cls=='sn-jnl':
        # The current source schema supplies literal names/affiliations, without
        # IDs, email or corresponding-author links. Preserve unindexed rosters;
        # never infer associations. Native sn-jnl stores abstract before title.
        authors='\n'.join(r'\author{'+x['latex']+'}' for x in front.get('authors',[]))
        affiliations='\n'.join(r'\affil{'+x['latex']+'}' for x in front.get('affiliations',[]))
        return '\n'.join([title,authors,affiliations,r'\abstract{'+latex('abstract')+'}',r'\maketitle'])
    authors=('\n'.join(r'\author{'+x['latex']+'}' for x in front.get('authors',[])) if cls=='revtex4-2'
        else r'\author{'+r'\and '.join(x['latex'] for x in front.get('authors',[]))+'}')
    if cls=='revtex4-2':affiliations='\n'.join(r'\affiliation{'+x['latex']+'}' for x in front.get('affiliations',[]))
    elif cls=='svjour3':affiliations=r'\institute{'+r'\and '.join(x['latex'] for x in front.get('affiliations',[]))+'}'
    else:affiliations='\n'.join(r'\begin{center}'+x['latex']+r'\end{center}' for x in front.get('affiliations',[]))
    abstract=(r'\noindent\textbf{'+latex('abstract')+'}' if contract['profile']=='nature' and contract['stage']=='final'
        else r'\begin{abstract}'+latex('abstract')+r'\end{abstract}')
    if contract['render']['frontmatter']=='abstract-before-title':return '\n'.join([title,authors,affiliations,abstract,r'\maketitle'])
    if cls=='svjour3':return '\n'.join([title,authors,affiliations,r'\maketitle',abstract])
    return '\n'.join([title,authors,r'\maketitle',affiliations,abstract])


def required_runtime(contract, *, has_svg):
    render=contract['render'];assets=['pdflatex.fmt','zref-user.sty','zref-abspage.sty']
    if render['class']=='article':assets+=['article.cls','geometry.sty']
    elif render['class']=='revtex4-2':assets+=['revtex4-2.cls','aps4-2.rtx','natbib.sty','url.sty','textcase.sty','bm.sty']
    elif render['class']=='svjour3':assets+=['svjour3.cls']
    elif render['class']=='sn-jnl':
        # Selected native class/style dependencies; this is a source readiness
        # list, not the complete dynamic recorder/font/ABI closure.
        assets+=['sn-jnl.cls','sn-mathphys-num.bst','article.cls','setspace.sty',
            'geometry.sty','cuted.sty','rotating.sty','threeparttable.sty',
            'appendix.sty','hyperref.sty','wrapfig.sty','amsthm.sty','fix-cm.sty','natbib.sty']
    else:assets+=[] # Exact supplied template and its included assets remain input commitments.
    if render['graphics']=='inline':assets+=['graphicx.sty']
    if render['line_numbers']:assets+=['vruler.sty' if render['class']=='sn-jnl' else 'lineno.sty']
    return {'binaries':['pdflatex','pdfinfo']+(['rsvg-convert'] if has_svg else []),
        'asset_basenames':assets,'font_population_required':True,'required_for_selected_full_method':True,
        'scope':'Required route dependencies, not optional complete-install extras; native runtime/loaded ABI qualification remains separate.'}
