"""Retrieve and instantiate pinned scientific code adaptations as new proposals.

Imports executable-skill reuse from Voyager and file-backed ranked observation
search from the inspected EvoScientist runtime. Typed facets expose transfer
conditions; every supplied outcome and reopening condition remains visible.
This is lexical/facet retrieval, not an embedding model or historical acceptance
validator. New source, execution and scientific review are always required.
"""
from copy import deepcopy
from collections import Counter
import difflib
import json
import math
from pathlib import Path
import re
from . import candidate_experiments as ce, constructive_contrast as cc

TOKEN=re.compile(r'[a-z0-9_]{3,}')
IDENTIFIER=re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}')
MAX_ENTRIES=8
MAX_DEPENDENCIES=126


def _text(value,maximum=8192):
    if type(value) is not str or not value.strip() or len(value.encode())>maximum:
        raise ValueError('bounded explicit adaptation text required')


def _facets(value):
    if type(value) is not dict or not 1<=len(value)<=16:raise ValueError('explicit typed transfer facets required')
    for key,text in value.items():ce.identity(key);_text(text,512)


def _tokens(text):return set(TOKEN.findall(text.casefold()))


def _load(request,base):
    ce.keys(request,['schema_version','catalog','task','top_k','max_context_bytes'])
    if type(request['schema_version']) is not int or request['schema_version']!=1:raise ValueError('adaptation-reuse/v1 required')
    if type(request['top_k']) is not int or not 1<=request['top_k']<=5:raise ValueError('one to five retrieved adaptations required')
    if type(request['max_context_bytes']) is not int or not 256<=request['max_context_bytes']<=65536:raise ValueError('finite source context budget required')
    task=request['task'];ce.keys(task,['id','question','domain','scope','facets','source_obligations'])
    ce.identity(task['id'])
    for key in ('question','domain','scope'):_text(task[key])
    _facets(task['facets'])
    if type(task['source_obligations']) is not list or not 1<=len(task['source_obligations'])<=64:raise ValueError('retained complete task obligations required')
    ids=set()
    for row in task['source_obligations']:
        ce.keys(row,['id','description']);ce.identity(row['id']);_text(row['description'])
        if row['id'] in ids:raise ValueError('distinct source obligations required')
        ids.add(row['id'])
    catalog=ce.read_pin(request['catalog'],base)
    ce.keys(catalog,['schema_version','entries'])
    if type(catalog['schema_version']) is not int or catalog['schema_version']!=1:raise ValueError('adaptation catalog/v1 required')
    if type(catalog['entries']) is not list or not 1<=len(catalog['entries'])<=MAX_ENTRIES:raise ValueError('bounded adaptation library required')
    seen=set();loaded=[];pins=[deepcopy(request['catalog'])];total=request['catalog']['size']
    for row in catalog['entries']:
        ce.keys(row,['id','summary','domain','scope','facets','source','fragment','parameters','observations','reopen_when'])
        ce.identity(row['id'])
        if row['id'] in seen:raise ValueError('unique adaptation IDs required')
        seen.add(row['id'])
        for key in ('summary','domain','scope'):_text(row[key])
        _facets(row['facets'])
        source=cc._read(row['source'],base)
        fragment=row['fragment'];ce.keys(fragment,['first_line','last_line','text'])
        if (type(fragment['first_line']) is not int or type(fragment['last_line']) is not int or
            not 1<=fragment['first_line']<=fragment['last_line']<=len(source.splitlines())):
            raise ValueError('exact original source span required')
        literal=''.join(source.splitlines(keepends=True)[fragment['first_line']-1:fragment['last_line']])
        if literal!=fragment['text']:raise ValueError('adaptation fragment differs from original source')
        _text(literal,65536)
        source_path=Path(row['source']['path']);source_path=source_path if source_path.is_absolute() else base/source_path
        pins.append({'path':str(source_path.resolve()),'sha256':row['source']['sha256'],'size':source_path.stat().st_size})
        total+=source_path.stat().st_size
        if type(row['parameters']) is not list or len(row['parameters'])>16:raise ValueError('finite declared code bindings required')
        pids=set();tokens=[]
        for parameter in row['parameters']:
            ce.keys(parameter,['id','token','kind','expected_occurrences']);ce.identity(parameter['id']);_text(parameter['token'],512)
            if parameter['id'] in pids:raise ValueError('unique binding IDs required')
            pids.add(parameter['id'])
            if parameter['kind'] not in ('identifier','integer','string_literal'):raise ValueError('explicit source parameter kind required')
            if (type(parameter['expected_occurrences']) is not int or not 1<=parameter['expected_occurrences']<=64 or
                literal.count(parameter['token'])!=parameter['expected_occurrences']):raise ValueError('exact source replacement census required')
            if any(t in parameter['token'] or parameter['token'] in t for t in tokens):raise ValueError('overlapping source parameters refused')
            tokens.append(parameter['token'])
        if type(row['observations']) is not list or not 1<=len(row['observations'])<=8:raise ValueError('source-linked observation history required')
        oids=set()
        for observation in row['observations']:
            ce.keys(observation,['id','status','scope','artifact']);ce.identity(observation['id']);_text(observation['scope'])
            if observation['id'] in oids:raise ValueError('distinct observation IDs required')
            oids.add(observation['id'])
            if observation['status'] not in ('reported_success','reported_failure','unresolved','untested'):raise ValueError('explicit supplied outcome required')
            ce.read_pin(observation['artifact'],base);pins.append(deepcopy(observation['artifact']));total+=observation['artifact']['size']
        if type(row['reopen_when']) is not list or not 1<=len(row['reopen_when'])<=16:raise ValueError('explicit scope reopening conditions required')
        for condition in row['reopen_when']:_text(condition)
        loaded.append(deepcopy(row))
    if total>ce.MAX_TOTAL_BYTES:raise ValueError('bounded adaptation custody required')
    unique={}
    for pin in pins:
        p=Path(pin['path']);p=p if p.is_absolute() else base/p
        identity=str(p.resolve());record={'path':identity,'sha256':pin['sha256'],'size':pin['size']}
        if identity in unique and unique[identity]!=record:raise ValueError('one exact adaptation identity per path required')
        unique[identity]=record
    if len(unique)>MAX_DEPENDENCIES:raise ValueError('complete adaptation inventory exceeds ordinary graph capacity')
    return task,loaded,list(unique.values())


def retrieve(request,*,base_dir):
    """Return relevant executable source context and explicit scope differences.

    All entries remain eligible, including failed/unknown ones. Ranking is a
    declared weighted lexical/facet heuristic, not semantic equivalence. Outcome
    authenticity is delegated to the ordinary scientific lifecycle; it is never
    inferred from a supplied label or acceptance-looking JSON file.
    """
    base=Path(base_dir).resolve(strict=True);task,entries,_=_load(request,base)
    documents={row['id']:_tokens(' '.join([row['id'],row['summary'],row['fragment']['text'],row['domain'],row['scope']])) for row in entries}
    counts=Counter(token for tokens in documents.values() for token in tokens)
    idf={token:math.log((len(entries)+1)/(count+0.5))+1 for token,count in counts.items()}
    query=_tokens(' '.join([task['question'],task['domain'],task['scope'],*task['facets'].values()]))
    ranked=[]
    for row in entries:
        fields=[(5,_tokens(row['id'])),(3,_tokens(row['summary'])),(1,_tokens(row['fragment']['text'])),
                (0.5,_tokens(row['domain']+' '+row['scope']))]
        terms=sorted(query & documents[row['id']])
        lexical=sum(idf[token]*weight for token in terms for weight,tokens in fields if token in tokens)
        matched=sorted(key for key,value in row['facets'].items() if task['facets'].get(key)==value)
        score=lexical+10*len(matched)
        differences=[{'facet':key,'origin':row['facets'].get(key),'target':task['facets'].get(key)}
            for key in sorted(set(row['facets'])|set(task['facets'])) if row['facets'].get(key)!=task['facets'].get(key)]
        candidate={'id':row['id'],'summary':row['summary'],'source':row['source'],'fragment':row['fragment'],
            'parameters':row['parameters'],'origin_scope':row['scope'],'target_scope':task['scope'],
            'matched_terms':terms,'matched_facets':matched,'scope_differences':differences,
            'reported_observations':row['observations'],'reopen_when':row['reopen_when'],'retrieval_score':score,
            'source_obligations':deepcopy(task['source_obligations']),'new_source_admission_required':True,
            'fresh_execution_and_full_scope_review_required':True,'old_votes_carried':[],
            'scientific_acceptance':False,'execution_authorized':False}
        ranked.append(candidate)
    ranked.sort(key=lambda row:(-row['retrieval_score'],row['id']))
    selected=[];omitted=[];used=0
    for row in ranked:
        size=len(json.dumps(row,sort_keys=True,allow_nan=False).encode())
        reason=('no_matching_terms_or_facets' if row['retrieval_score']==0 else
            'top_k' if len(selected)>=request['top_k'] else 'context_byte_bound' if used+size>request['max_context_bytes'] else None)
        if reason:omitted.append({'id':row['id'],'reason':reason,'source_context_bytes':size})
        else:selected.append(row);used+=size
    return {'kind':'adaptation_retrieval','request':deepcopy(request),'selected':selected,'omitted':omitted,
        'selection_policy':'weighted_ASCII_lexical_IDF_plus_exact_typed_facets; ties by adaptation ID',
        'selected_context_bytes':used,'new_task_obligations':deepcopy(task['source_obligations']),
        'supplied_report_truth_verified':False,'semantic_equivalence_proved':False,
        'independent_context_or_OS_blinding_checked':False,'scientific_acceptance':False,'execution_authorized':False}


def prepare(record,entry_id,bindings,*,base_dir):
    """Instantiate a retrieved source fragment with exact declared substitutions.

    Emits a literal proposal and source diff; no source is compiled/executed.
    A fragment must be composed into its complete target source and requalified.
    """
    actual=retrieve(record['request'],base_dir=base_dir)
    if actual!=record:raise ValueError('exact current retrieval context required')
    selected=[row for row in actual['selected'] if row['id']==entry_id]
    if len(selected)!=1:raise ValueError('selected adaptation required')
    row=selected[0]
    if type(bindings) is not dict or set(bindings)!={p['id'] for p in row['parameters']}:raise ValueError('complete exact adaptation bindings required')
    replacements={}
    for parameter in row['parameters']:
        value=bindings[parameter['id']]
        if parameter['kind']=='identifier':
            if type(value) is not str or not IDENTIFIER.fullmatch(value):raise ValueError('source identifier required')
            text=value
        elif parameter['kind']=='integer':
            if type(value) is not int or not -1000000<=value<=1000000:raise ValueError('bounded source integer required')
            text=str(value)
        else:
            if type(value) is not str or not value.isascii() or not 1<=len(value)<=256:raise ValueError('bounded ASCII source string required')
            text=json.dumps(value)
        replacements[parameter['token']]=text
    before=row['fragment']['text']
    pattern='|'.join(re.escape(token) for token in sorted(replacements,key=lambda token:(-len(token),token)))
    after=re.sub(pattern,lambda match:replacements[match.group()],before) if pattern else before
    return {'kind':'adaptation_proposal','retrieval_sha256':ce.digest(record),'adaptation_id':entry_id,
        'source':deepcopy(row['source']),'bindings':deepcopy(bindings),'controlled_source':after,
        'literal_source_diff':''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='original-adaptation',tofile='new-proposal')),
        'source_obligations':deepcopy(record['new_task_obligations']),'scope_differences':deepcopy(row['scope_differences']),
        'reopen_when':deepcopy(row['reopen_when']),'observations':deepcopy(row['reported_observations']),
        'fresh_complete_source_composition_required':True,'new_scientific_plan_required':True,
        'fresh_execution_and_full_scope_review_required':True,'old_votes_carried':[],
        'scientific_acceptance':False,'execution_authorized':False}


def input_pins(request,*,base_dir):
    """All catalog, program and observation inputs for ordinary Host admission."""
    return _load(request,Path(base_dir).resolve(strict=True))[2]
