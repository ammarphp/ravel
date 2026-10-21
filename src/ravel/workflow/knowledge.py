"""Deterministic, read-only knowledge queries and atlas-backed mode views.

The query core performs retrieval only. Run restrictions and served logs belong
in knowledge_binding; worker calls must use that broker surface.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys

from .knowledge_atlas import ATLAS, digest, encode, source_root

# Best-BM25-score floor for `find`, calibrated on the battery recorded beside it.
FLOOR = json.loads((Path(__file__).resolve().parents[1]/'data/knowledge/floor.json').read_text())['floor']

OPS = ('find','show','for_node','for_failure','plan_check','coverage','xsec','constants','conventions')


def load_atlas(path=None):
    path=Path(path) if path else Path(__file__).resolve().parents[1]/'data/knowledge/atlas.json'
    value=json.loads(path.read_text())
    if value.get('kind')!='knowledge-atlas' or value.get('schema_version')!=1:
        raise ValueError('unsupported knowledge atlas')
    return value


def _tokens(text):
    # A small morphology rule makes recasting/recast and model/models comparable.
    ignored=set('a an the and or for from to of in with on by as new supplied run retained original source pinned declared operation '
                'is are was be do does how what which who when where why can i me my we you your it this that at if not'.split())
    words=[w for w in re.findall(r'[a-z0-9]+',text.lower()) if w not in ignored]
    return [w[:-3] if w.endswith('ing') and len(w)>5 else w[:-1] if w.endswith('s') and len(w)>3 else w for w in words]


def _rank(rows,text):
    terms=set(_tokens(text)); documents=[]
    for row in rows:
        body=' '.join([row['title']]*3+[row['summary']]*2+row.get('tags',[])+[row.get('search_context','')]+row.get('op',{}).get('use_when',[]))
        documents.append(Counter(_tokens(body)))
    average=sum(sum(d.values()) for d in documents)/max(1,len(documents))
    frequency=Counter(term for d in documents for term in d)
    ranked=[]
    for row,document in zip(rows,documents):
        score=0.0; matched=[]; length=sum(document.values())
        for term in sorted(terms):
            tf=document[term]
            if tf:
                idf=math.log(1+(len(rows)-frequency[term]+0.5)/(frequency[term]+0.5))
                score+=idf*tf*2.2/(tf+1.2*(0.25+0.75*length/max(1,average))); matched.append(term)
        if score:ranked.append((score,row,matched))
    return sorted(ranked,key=lambda item:(-item[0],item[1]['id']))


def rank_literature(rows, text):
    """Score already policy-projected located units with the unchanged scorer.

    ``indexed_text`` contains the title, section path and exact source passage.
    Empty title/summary fields avoid introducing the atlas's field weighting a
    second time. This additive adapter does not change legacy query results.
    """
    projected = [{'id': row['id'], 'title': '', 'summary': '',
                  'search_context': row['indexed_text']} for row in rows]
    originals = {row['id']: row for row in rows}
    if len(originals) != len(projected):
        raise ValueError('unique literature scoring IDs required')
    return [(score, originals[row['id']], matches)
            for score, row, matches in _rank(projected, text)]


def _node(by_id,args):
    facts=args.get('node',args.get('node_facts',args)); operation=facts.get('operation',facts.get('mode'))
    identity=str(operation) if str(operation).startswith('op:') else 'op:'+str(operation)
    row=by_id.get(identity) or by_id.get('op:stage/'+str(operation))
    if not row:return [],['unregistered operation: '+str(operation)]
    identity=row['id']
    ids={identity}; queue=[identity]
    # Follow procedural links; tools carry their doctor checks but do not expand
    # reverse operation links into unrelated modes.
    keys=('handbooks','checks','traps','protocols','conventions','consult_role','executor_role','tools','docs','commands')
    while queue:
        current=by_id[queue.pop()]
        for key in keys:
            values=current.get('links',{}).get(key,[])
            for linked in values if isinstance(values,list) else [values]:
                if linked in by_id and linked not in ids: ids.add(linked); queue.append(linked)
    missing=[]
    if not row['links'].get('handbooks'):missing.append('no handbook bound')
    if not row['op']['examples']:missing.append('no curated executable example')
    required=facts.get('validation_tier')
    if required:
        from .knowledge_atlas import TIERS
        if required not in TIERS:raise ValueError('unknown required validation tier')
        if TIERS.index(row['op']['validation_tier'])<TIERS.index(required):missing.append('validation tier below '+required)
    for key in ('consult_role','executor_role'):
        role=row['links'].get(key)
        if role and by_id[role]['status'].startswith('held:'):missing.append(key+' card not registered')
    for i in ids:
        if by_id[i].get('status')=='declared_term':missing.append(by_id[i]['title']+' review term: no implementing check linked')
    priority = {'op':0, 'hb':1, 'trap':2, 'role':3, 'check':4, 'proto':5, 'conv':6, 'tool':7, 'doc':8, 'cmd':9}
    ordered = sorted(ids, key=lambda i:(priority.get(by_id[i]['kind'],10),i))
    return [(by_id[i],'knowledge linked to '+identity) for i in ordered],missing


def query(op: str, **args) -> dict:
    """Query the atlas. Results follow the atlas query interface and carry a hash.

    ``atlas_path`` permits an explicit frozen atlas. Run binding is supplied by
    the broker, not inferred from shell state. Selection never authorizes compute.
    """
    if op not in OPS:raise ValueError('unknown knowledge query: '+str(op))
    atlas=load_atlas(args.get('atlas_path')); rows=atlas['entries']; by_id={r['id']:r for r in rows}
    selected=[]; missing=[]; nodes=[]; floor_hit=None
    if op=='show':
        identity=args.get('id',args.get('operation'))
        identity=identity if identity in by_id else 'op:'+str(identity)
        if identity not in by_id:raise ValueError('unknown knowledge ID: '+str(identity))
        selected=[(by_id[identity],'exact identity')]
    elif op=='find':
        text=args.get('text',args.get('query',''))
        if not isinstance(text,str) or not text.strip():raise ValueError('find requires nonblank text')
        kinds=args.get('kinds',args.get('kind'))
        kinds=[kinds] if isinstance(kinds,str) else kinds
        candidates=[r for r in rows if not kinds or r['kind'] in kinds]
        ranked=_rank(candidates,text); best=ranked[0][0] if ranked else 0.0
        floor=args.get('floor',FLOOR)
        if type(floor) not in (int,float) or floor<0:raise ValueError('floor must be a nonnegative number')
        if best<floor or not ranked: floor_hit={'value':floor,'best_score':round(best,3)}
        else: selected=[(r,'BM25 terms: '+', '.join(matches)) for _,r,matches in ranked]
    elif op=='for_node':selected,missing=_node(by_id,args)
    elif op=='plan_check':
        plan=args.get('plan',{})
        if isinstance(plan,(str,Path)):plan=json.loads(Path(plan).read_text())
        for node in plan.get('nodes',[]):
            found,gaps=_node(by_id,node)
            nodes.append({'node_id':node.get('id',node.get('node_id')),'served_ids':[r['id'] for r,_ in found],'missing':gaps})
            selected.extend(found)
        selected=list({r['id']:(r,why) for r,why in selected}.values())
    elif op=='for_failure':
        tool=str(args.get('tool','')); failure=str(args.get('failure_class',''))
        hits=_rank([r for r in rows if r['kind'] in ('hb','check','role','trap','doc')],tool+' '+failure)
        selected=[(r,'failure knowledge match: '+', '.join(matches)) for _,r,matches in hits]
        missing=['The atlas holds no authoritative failure-class binding; use the failure-router registry.']
    else:
        missing=[op+' store is not installed; no values are inferred from atlas membership.']
    limit=args.get('limit',50 if op=='find' else len(selected))
    if type(limit)!=int or limit<0:raise ValueError('limit must be a nonnegative integer')
    max_bytes=args.get('max_bytes',32768)
    if type(max_bytes)!=int or max_bytes<1024:raise ValueError('max_bytes must be an integer >= 1024')
    public_args={k:str(v) if isinstance(v,Path) else v for k,v in args.items() if k!='atlas_path'}
    result={'schema_version':1,'kind':'knowledge-result','op':op,'args':public_args,
            'results':[],'served_ids':[],'atlas_sha256':digest(encode(atlas)),
            'omitted':{'count':0,'reasons':{}},'missing':missing}
    if nodes:result['nodes']=nodes
    if floor_hit:result.update(items=[],reason='below_floor',floor=floor_hit)
    if len(encode(result))+160>max_bytes:raise ValueError('query envelope exceeds max_bytes; reduce plan or args')
    accepted=[]
    for row,why in selected[:limit]:
        item={**row,'why':why}; result['results'].append(item); result['served_ids'].append(row['id'])
        if len(encode(result))+100>max_bytes:
            result['results'].pop();result['served_ids'].pop();break
        accepted.append(row)
    limit_omissions=max(0,len(selected)-limit); budget_omissions=len(selected[:limit])-len(accepted)
    result['omitted']={'count':limit_omissions+budget_omissions,'reasons':{k:v for k,v in {'limit':limit_omissions,'budget':budget_omissions}.items() if v}}
    while True:
        result.pop('result_sha256', None)
        result['result_sha256']=digest(encode(result))
        if len(encode(result)) <= max_bytes:
            return result
        if not result['results']:
            raise ValueError('query envelope exceeds max_bytes; reduce plan or args')
        result['results'].pop(); result['served_ids'].pop()
        result['omitted']['count'] += 1
        result['omitted']['reasons']['budget'] = result['omitted']['reasons'].get('budget', 0) + 1


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='action',required=True)
    listing=sub.add_parser('list'); listing.add_argument('--json',action='store_true')
    listing.add_argument('--status'); listing.add_argument('--tool')
    for action in ('show','example'):
        p=sub.add_parser(action);p.add_argument('id');p.add_argument('--json',action='store_true')
    finding=sub.add_parser('find');finding.add_argument('text');finding.add_argument('--kind',action='append');finding.add_argument('--limit',type=int,default=10);finding.add_argument('--max-bytes',type=int,default=32768);finding.add_argument('--json',action='store_true')
    for action in ('for_node','for_failure','plan_check','coverage','xsec','constants','conventions'):
        p=sub.add_parser(action);p.add_argument('--args',type=json.loads,default={});p.add_argument('--operation');p.add_argument('--tool');p.add_argument('--failure-class');p.add_argument('--plan',type=Path);p.add_argument('--max-bytes',type=int,default=32768);p.add_argument('--json',action='store_true')
    for action in ('doctor','check','build'):
        p=sub.add_parser(action);p.add_argument('--json',action='store_true');p.add_argument('--write',action='store_true')
    args=ap.parse_args(argv)
    if args.action=='list':
        modes=[r for r in load_atlas()['entries'] if r['kind']=='op' and r.get('catalogue',{}).get('kind')=='science-mode' and (not args.status or r['status']==args.status) and (not args.tool or any(args.tool.lower() in i.lower() for i in r['links']['tools']))]
        if args.json:print(encode({'schema_version':1,'kind':'knowledge-modes','modes':modes}).decode(),end='')
        else:
            for r in modes:print(f'{r["id"][3:]}\t{r["op"]["validation_tier"]}\t{r["summary"]}')
        return 0
    if args.action in ('check','doctor'):
        from ravel.validation.check_knowledge import report
        try: result=report()
        except FileNotFoundError as exc: print(str(exc),file=sys.stderr);return 2
        print(encode(result).decode(),end='');return 0 if result['valid'] else 1
    if args.action=='build':
        from .knowledge_atlas import main as build
        return build(['--write'] if args.write else [])
    if args.action=='example':
        result=query('show',id=args.id); row=result['results'][0]
        examples=row.get('op',{}).get('examples',[])
        print(encode({'schema_version':1,'kind':'knowledge-example','operation':row['id'],
                      'status':'available' if examples else 'held:curation_missing','examples':examples,
                      'missing':[] if examples else ['No curated executable example yet; inspect the adapter contract.']}).decode(),end='')
        return 0 if examples else 1
    if args.action=='show':result=query('show',id=args.id)
    elif args.action=='find':result=query('find',text=args.text,kinds=args.kind,limit=args.limit,max_bytes=args.max_bytes)
    else:
        facts={**args.args,**{k:v for k,v in vars(args).items() if k not in ('action','args','json') and v is not None}}
        result=query(args.action,**facts)
    print(encode(result).decode(),end='');return 0


if __name__=='__main__':raise SystemExit(main())
