"""Complete model-bound FeynGraph enumeration and original rendered exports.

Planning imports no diagram engine. Native calls use the existing ordinary
owner; diagrams are structural results, not validated amplitudes.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from ravel.physics import model_tool_bridge as custody
from ravel.physics.finite_integrals import runtime_tree, identity
from ravel.workflow.operation_resources import document

COMMIT='15afe2f2c701331c76a0f5d55a752dca099104be'
SCOPE='complete_model_bound_diagram_delivery'
API=Path(__file__).parents[1]/'data/diagram_tools/upstream-api.json'


def keys(d,n,label='record'):
    if type(d) is not dict or set(d)!=set(n):raise ValueError('closed '+label+' required')
def text(x):
    if type(x) is not str or not x.strip() or len(x.encode())>8192:raise ValueError('bounded explicit text required')
    return x
def integer(x,lo,hi):
    if type(x) is not int or not lo<=x<=hi:raise ValueError('bounded literal integer required')
    return x
def name(x):
    if type(x) is not str or re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}',x) is None:raise ValueError('unique simple identity required')
    return x
def encoded(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def write(p,x):
    raw=(json.dumps(x,indent=2,allow_nan=False)+'\n').encode();return write_bytes(p,raw)
def write_bytes(p,raw):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as s:s.write(raw)
    if p.read_bytes()!=raw:raise ValueError('intended emitted bytes differ')
    return {'path':str(p.absolute()),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
def validate(task):
    keys(task,('input','input_sha256'),'diagram task');text(task['input'])
    if type(task['input_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',task['input_sha256']) is None:raise ValueError('exact input digest required')
    return deepcopy(task)
def config(c):
    keys(c,('schema_version','source','original_task','trusted_native_sources','engine_commit','engine_source','runtime','model','processes','conventions','render','max_diagrams','max_seconds','max_ram_mib','max_output_bytes'),'enumeration request')
    if type(c['schema_version']) is not int or c['schema_version']!=1 or c['engine_commit']!=COMMIT or c['trusted_native_sources'] is not True:raise ValueError('exact released engine and explicit trusted runtime required')
    text(c['source']);text(c['conventions'])
    keys(c['runtime'],('python','trees','site_roots','engine_module'),'runtime')
    if c['runtime']['engine_module']!='feyngraph':raise ValueError('released feyngraph module required')
    if type(c['runtime']['trees']) is not list or not 1<=len(c['runtime']['trees'])<=16 or type(c['runtime']['site_roots']) is not list or not c['runtime']['site_roots']:raise ValueError('complete bounded native runtime required')
    m=c['model'];keys(m,('kind','tree','entry','gauge','source_vertex_names'),'model')
    if m['kind'] not in ('ufo','qgraf','builtin-sm-feynman'):raise ValueError('explicit actual model format required')
    text(m['gauge'])
    if m['kind']=='builtin-sm-feynman':
        if m['tree'] is not None or m['entry'] is not None or m['gauge']!='Feynman' or m['source_vertex_names']!=[]:raise ValueError('builtin model only by explicit selection')
    else:
        text(m['entry']);rp=Path(m['entry'])
        if rp.is_absolute() or '..' in rp.parts:raise ValueError('model entry must be inside admitted tree')
    if type(m['source_vertex_names']) is not list or len(m['source_vertex_names'])>20000 or len(set(m['source_vertex_names']))!=len(m['source_vertex_names']):raise ValueError('complete original vertex-name roster required')
    for v in m['source_vertex_names']:text(v)
    if type(c['processes']) is not list or not 1<=len(c['processes'])<=16:raise ValueError('finite full process population required')
    ids=[]
    for p in c['processes']:
        keys(p,('id','incoming','outgoing','loops','momentum_labels','selectors'),'process');ids.append(name(p['id']));integer(p['loops'],0,3)
        for k in ('incoming','outgoing'):
            if type(p[k]) is not list or not 1<=len(p[k])<=8:raise ValueError('complete ordered external states required')
            for q in p[k]:text(q)
        labels=p['momentum_labels']
        if type(labels) is not list or len(labels)!=len(p['incoming'])+len(p['outgoing'])+p['loops'] or len(set(labels))!=len(labels):raise ValueError('full unique external/loop momentum roster required')
        for q in labels:name(q)
        if type(p['selectors']) is not list or len(p['selectors'])>32:raise ValueError('explicit finite selector program required')
        for s in p['selectors']:
            keys(s,('method','arguments'),'selector')
            arities={'select_opi_components':1,'select_self_loops':1,'select_tadpoles':1,'select_on_shell':0,'select_coupling_power':2,'select_coupling_power_list':2,'select_propagator_count':2,'select_vertex_count':2,'select_vertex_degree':2}
            if s['method'] not in arities or type(s['arguments']) is not list or len(s['arguments'])!=arities[s['method']]:raise ValueError('source-defined selector only; no executable callbacks')
            args=s['arguments']
            if len(args)==1:integer(args[0],0,1024)
            if len(args)==2:
                if s['method']=='select_vertex_degree':integer(args[0],1,32)
                elif s['method']=='select_vertex_count':
                    if type(args[0]) is not list or not 1<=len(args[0])<=32:raise ValueError('ordered vertex field query required')
                    for a in args[0]:text(a)
                else:text(args[0])
                if s['method']=='select_coupling_power_list':
                    if type(args[1]) is not list or not 1<=len(args[1])<=64:raise ValueError('coupling power list required')
                    for a in args[1]:integer(a,0,1024)
                else:integer(args[1],0,1024)
    if len(set(ids))!=len(ids):raise ValueError('duplicate process')
    keys(c['render'],('formats','max_visualize'),'render')
    if type(c['render']['formats']) is not list or not c['render']['formats'] or len(set(c['render']['formats']))!=len(c['render']['formats']) or any(x not in ('svg','tikz') for x in c['render']['formats']):raise ValueError('original SVG/TikZ formats required')
    integer(c['render']['max_visualize'],1,256);integer(c['max_diagrams'],1,20000);integer(c['max_seconds'],1,3600);integer(c['max_ram_mib'],512,8192);integer(c['max_output_bytes'],1024,256*1024**2)
    return deepcopy(c)
def load(task,base):
    validate(task);p=custody._pin({'path':task['input'],'sha256':task['input_sha256']},base);return p,config(document(p))
def runtime(c,base):
    files=[];roots=[]
    for tree in c['runtime']['trees']:
        root,manifest,members=runtime_tree(tree,base);roots.append(root);files += [manifest,*members]
    if len(set(roots))!=len(roots) or any(a!=b and a.is_relative_to(b) for a in roots for b in roots):raise ValueError('disjoint runtime trees required')
    sites=[custody._regular(x,base,directory=True) for x in c['runtime']['site_roots']]
    if len(set(sites))!=len(sites) or any(not any(s==r or s.is_relative_to(r) for r in roots) for s in sites):raise ValueError('import sites must belong to complete runtime closure')
    python=custody._pin(c['runtime']['python'],base)
    if not os.access(python,os.X_OK):raise ValueError('admitted Python executable required')
    return sorted(set([python,*files])),python,sites

def source_vertex_name(source,node):
    """Admit only a literal whose Python and released Rust name are identical.

    The native UFO parser keeps the quoted interior without decoding escapes.
    Keep the original source; incompatible spellings require a new input.
    """
    if not isinstance(node,ast.Constant) or type(node.value) is not str:
        raise ValueError('source UFO vertex names must be literal')
    spelling=ast.get_source_segment(source,node)
    literal=re.fullmatch(r"r?(['\"])([^\\\r\n]*)\1",spelling or '')
    if literal is None or literal[1] in literal[2] or literal[2]!=node.value:
        raise ValueError('source UFO vertex name must match native quoted interior without escapes')
    return text(literal[2])

def inputs(task,base):
    p,c=load(task,base);files=[p,API,custody._pin(c['original_task'],p.parent)];source,manifest,members=custody._tree(c['engine_source'],p.parent);files += [manifest,*members]
    api=document(API)
    for rel,digest in api['feyngraph']['required_sources'].items():
        if custody._hash(source/rel)!=digest:raise ValueError('actual released FeynGraph source differs: '+rel)
    rf,_,_=runtime(c,p.parent);files+=rf
    if c['model']['kind']!='builtin-sm-feynman':
        root,manifest,members=custody._tree(c['model']['tree'],p.parent);files += [manifest,*members];entry=root/c['model']['entry']
        if not entry.is_relative_to(root) or (c['model']['kind']=='ufo' and not entry.is_dir()) or (c['model']['kind']=='qgraf' and not entry.is_file()):raise ValueError('actual model entry missing')
        if c['model']['kind']=='ufo':
            vertices=[]
            for module,factory in (('vertices.py','Vertex'),('CT_vertices.py','CTVertex')):
                q=entry/module
                if q.is_file():
                    source_text=q.read_text();tree=ast.parse(source_text)
                    for n in tree.body:
                        if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and getattr(n.value.func,'id',None)==factory:
                            names=[x.value for x in n.value.keywords if x.arg=='name']
                            if len(names)!=1:raise ValueError('one literal source UFO vertex name required')
                            vertices.append(source_vertex_name(source_text,names[0]))
            if len(set(vertices))!=len(vertices):raise ValueError('duplicate source UFO vertex names')
            if vertices!=c['model']['source_vertex_names']:raise ValueError('complete source UFO vertex-name roster differs')
    files += [Path(__file__),Path(__file__).with_name('feyn_graph_worker.py')]
    return sorted(set(files))
def execution_seconds(task,base):return load(task,base)[1]['max_seconds']
def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']:raise ValueError('one-attempt delivery-only diagram scope required')
    return spec

def approved(task,out,mode):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd)
            if spec['mode']!=mode or spec['task']!=task or out!=(rd/plan['output_directory']/mode).resolve():raise ValueError('actual ordinary diagram task/output differs')
            return rd,plan
    raise ValueError('approved ordinary diagram worker required')
def members(out):
    result={}
    for p in sorted(Path(out).rglob('*')):
        if p.is_symlink():raise ValueError('aliased diagram output')
        if p.is_file():result[p.relative_to(out).as_posix()]=custody._hash(p)
        elif not p.is_dir():raise ValueError('nonregular diagram output')
    return result
class Delivery(dict):pass

def finish(task,base,out,result,initial,before,maxbytes,input_loader=inputs):
    intended=encoded(result);pin=write(out/'diagram-result.json',json.loads(intended));expected=dict(initial);expected['diagram-result.json']=pin['sha256']
    if members(out)!=expected or encoded(result)!=intended or before!=identity(input_loader(task,base)):raise ValueError('diagram ending result/output/input correspondence differs')
    if sum((out/k).stat().st_size for k in expected)>maxbytes:raise ValueError('full diagram output exceeds bound')
    d=Delivery(json.loads(intended));d.expected=json.loads(intended);d.artifacts=expected;d.inputs_before=before;d.task=deepcopy(task);d.base=Path(base);d.output=out;d.maxbytes=maxbytes;d.input_loader=input_loader;return d

def finalize(result,output,common=None):
    if not isinstance(result,Delivery) or Path(output).resolve()!=result.output or encoded(dict(result))!=encoded(result.expected):raise ValueError('original diagram delivery required')
    observed=members(result.output)
    if observed!=result.artifacts:raise ValueError('diagram publication changed original artifacts or complete membership')
    common=Path(common if common is not None else output)
    if encoded(document(common/'result.json'))!=encoded(result.expected):raise ValueError('common and original diagram result differ')
    if result.inputs_before!=identity(result.input_loader(result.task,result.base)):raise ValueError('diagram ending inputs changed')
    if sum((result.output/k).stat().st_size for k in observed)>result.maxbytes:raise ValueError('published diagram storage bound exceeded')
def run(task,base,output):
    out=Path(output).resolve();rd,plan=approved(task,out,'feyn-graph');p,c=load(task,base);before=identity(inputs(task,base))
    if c['max_seconds']>plan['max_seconds']:raise ValueError('native budget exceeds admitted stage')
    if out.exists():raise ValueError('fresh diagram output required')
    out.mkdir(parents=True);work=rd/'work/feyn-graph'/out.name
    if work.exists():raise ValueError('fresh diagram workspace required')
    work.mkdir(parents=True);model=None
    if c['model']['kind']!='builtin-sm-feynman':
        custody._copy(c['model']['tree'],p.parent,work/'model');model=str(work/'model'/c['model']['entry'])
    staged=custody.source_tree(work/'model') if model else None
    files,python,sites=runtime(c,p.parent);native=out/'native';native.mkdir();source=Path(__file__).with_name('feyn_graph_worker.py');driver=native/'driver.py';driver.write_bytes(source.read_bytes());req=native/'request.json'
    request={'configuration':c,'model_entry':model,'sites':[str(x) for x in sites],'assets':{str(x):custody._hash(x) for x in files},'driver_sha256':custody._hash(source),'output':str(native)};write(req,request);selected=identity([driver,req]);errors=[];receipt=None;delivery=None
    from ravel.physics.reinterpret_db import execute_native
    try:
        receipt=execute_native([str(python),'-I','-B',str(driver),str(req)],native,c)
        delivery=document(native/'enumeration.json');check_delivery(c,delivery,native)
    except Exception as e:errors.append(type(e).__name__+': '+str(e))
    initial=members(out)
    if selected!=identity([driver,req]) or before!=identity(inputs(task,base)) or model and staged!=custody.source_tree(work/'model'):errors.append('ending source/runtime/staged model changed')
    result={'schema_version':1,'status':'failed' if errors else 'passed','status_scope':SCOPE,'configuration':c,'operation_input':{'path':str(p),'sha256':custody._hash(p)},'delivery':delivery,'native_execution':receipt,'errors':errors,'physics_validated':False,'original_task_complete':False,'enumeration_complete':bool(delivery and delivery.get('complete') is True and not errors),'limitations':['Enumeration does not establish model/gauge/amplitude correctness.','QGraf parser supports only the released compatibility dialect.','Rendered subset is presentation only; structured population remains whole.','No coherent amplitudes, widths or loop integrals inferred from topology.']}
    return finish(task,base,out,result,initial,before,c['max_output_bytes'])
def check_delivery(c,d,out):
    keys(d,('schema_version','engine_commit','model','model_particles','model_vertices','source_vertex_splittings','processes','complete','imports'),'engine delivery')
    if type(d['schema_version']) is not int or d['schema_version']!=1 or d['engine_commit']!=COMMIT or encoded(d['model'])!=encoded(c['model']) or d['complete'] is not True or type(d['processes']) is not list or len(d['processes'])!=len(c['processes']):raise ValueError('complete exact model/process native delivery required')
    if type(d['source_vertex_splittings']) is not list:raise ValueError('complete source vertex splitting roster required')
    for row in d['source_vertex_splittings']:keys(row,('name','splitting'),'source vertex splitting')
    if [row['name'] for row in d['source_vertex_splittings']]!=c['model']['source_vertex_names']:raise ValueError('complete ordered source vertex splitting roster differs')
    from .feyn_graph_worker import check_source_membership
    check_source_membership(c['model'],d['model_vertices'],d['source_vertex_splittings'])
    for p,s in zip(d['processes'],c['processes']):
        if encoded(p['request'])!=encoded(s) or type(p['count']) is not int or type(p['diagrams']) is not list or p['count']!=len(p['diagrams']) or p['count']>c['max_diagrams'] or p['complete'] is not True or [x['id'] for x in p['diagrams']]!=list(range(p['count'])):raise ValueError('full native diagram census differs')
        for row in p['diagrams']:
            if type(row['id']) is not int:raise ValueError('literal ordered native diagram index required')
            if [x['particle']['name'] for x in row['incoming']]!=s['incoming'] or [x['particle']['name'] for x in row['outgoing']]!=s['outgoing']:raise ValueError('native external state/order differs')
        expected=[(i,f) for i in range(min(p['count'],c['render']['max_visualize'])) for f in c['render']['formats']]
        if [(x['diagram_id'],x['format']) for x in p['renders']]!=expected:raise ValueError('complete requested rendered subset differs')
        for a in p['renders']:
            q=custody._regular(a['relative_path'],out)
            if not q.is_relative_to(out) or custody._hash(q)!=a['sha256'] or q.stat().st_size!=a['size'] or a['size']==0:raise ValueError('rendered native export differs')
    return d

def context_inputs(task,base):
    # Manifest pins bind whole verified trees without requiring >128 Graph inputs.
    inputs(task,base);p,c=load(task,base)
    files=[p,API,Path(__file__),Path(__file__).with_name('feyn_graph_worker.py'),custody._pin(c['original_task'],p.parent),custody._pin(c['engine_source']['manifest'],p.parent),custody._pin(c['runtime']['python'],p.parent)]
    files += [custody._pin(t['manifest'],p.parent) for t in c['runtime']['trees']]
    if c['model']['kind']!='builtin-sm-feynman':files.append(custody._pin(c['model']['tree']['manifest'],p.parent))
    return sorted(set(files))
def context(task,base):
    p,c=load(task,base);return {'schema_version':1,'mode':'feyn-graph','configuration':c,'original_task':c['original_task'],'scope':SCOPE,'execution_authorized':False,'physics_validated':False}
def write_report(output,result):
    out=Path(output);path=out/'diagram-report.md';rows=['# Model-bound diagrams','','Status: '+result['status']+'. Physics qualification remains separate.','']
    if result.get('delivery'):
        for p in result['delivery']['processes']:
            rows+=['## '+p['request']['id'],'',str(p['count'])+' diagrams; complete structured population retained.','']
            for r in p['renders']:
                if r['format']=='svg':rows+=['![Diagram '+str(r['diagram_id'])+'](native/'+r['relative_path']+')','']
    rows += [str(e) for e in result.get('errors',[])];raw=('\n'.join(rows)+'\n').encode()
    if not isinstance(result,Delivery) or encoded(dict(result))!=encoded(result.expected):raise ValueError('report requires original diagram result')
    result.artifacts['diagram-report.md']=hashlib.sha256(raw).hexdigest();write_bytes(path,raw)
    exports=['native/'+r['relative_path'] for p in (result.get('delivery') or {}).get('processes',[]) for r in p['renders']]
    return [{'stem':'diagram-report','files':['diagram-report.md','diagram-result.json',*exports],'kind':'model-bound-diagram-census'}]
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('inspect',));parser.add_argument('--input',required=True);parser.add_argument('--input-sha256',required=True);a=parser.parse_args(argv);task={'input':a.input,'input_sha256':a.input_sha256};p,c=load(task,Path.cwd());print(json.dumps({'mode':'feyn-graph','processes':len(c['processes']),'inputs':len(inputs(task,Path.cwd())),'execution_authorized':False,'next':'Use this task in an ordinary schema2 science plan, research_cycle blueprint or Graph science operation.'},indent=2));return 0
