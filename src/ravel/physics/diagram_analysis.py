"""Full enumerated diagram population into source-matched NDA/EDA consumers.

Unsupported diagrams remain explicit rows. No incoherent sum is labelled a
coherent amplitude, process width or physical branching ratio.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from ravel.physics import feyn_graph as fg, model_tool_bridge as custody, ufo_decay
from ravel.workflow.operation_resources import document

SCOPE='model_bound_diagram_analysis_delivery'
def validate(task):return fg.validate(task)
def load(task,base):
    validate(task);p=custody._pin({'path':task['input'],'sha256':task['input_sha256']},base);c=document(p)
    fg.keys(c,('schema_version','source','original_task','enumeration','ufo_request_template','symbolic_template','nda_runtime','heptapod_source','max_seconds','max_ram_mib','max_output_bytes'),'diagram analysis')
    if type(c['schema_version']) is not int or c['schema_version']!=1:raise ValueError('analysis schema1 required')
    fg.text(c['source']);fg.integer(c['max_seconds'],1,3600);fg.integer(c['max_ram_mib'],512,8192);fg.integer(c['max_output_bytes'],1024,256*1024**2)
    return p,c

def enumeration(c,base):
    ep=custody._pin(c['enumeration'],base);e=document(ep)
    if e.get('status')!='passed' or e.get('enumeration_complete') is not True:raise ValueError('complete delivered model-bound enumeration required')
    source=e.get('operation_input');fg.keys(source,('path','sha256'),'original enumeration input')
    p,cfg=fg.load({'input':source['path'],'input_sha256':source['sha256']},base)
    if fg.encoded(cfg)!=fg.encoded(e['configuration']):raise ValueError('whole original enumeration configuration differs')
    if custody._hash(custody._pin(c['original_task'],base))!=custody._hash(custody._pin(cfg['original_task'],p.parent)):raise ValueError('analysis and enumeration original task differ')
    fg.check_delivery(cfg,e['delivery'],ep.parent/'native');return ep,e,p,cfg

def inputs(task,base):
    p,c=load(task,base);ep,e,original,cfg=enumeration(c,p.parent);files=[p,ep,custody._pin(c['original_task'],p.parent),*fg.inputs({'input':str(original),'input_sha256':custody._hash(original)},p.parent)]
    files += [q for q in (ep.parent/'native').rglob('*') if q.is_file()]
    tp=custody._pin(c['ufo_request_template'],p.parent);template=document(tp);files.append(tp)
    # Capture the actual UFO/card source through the existing finite compiler.
    _,_,_,_,captured=ufo_decay._capture({'input':str(tp)},tp.parent);files += [Path(x) for x in captured]
    root,manifest,members=custody._tree(c['heptapod_source'],p.parent);files += [manifest,*members]
    api=document(fg.API)['heptapod']
    for rel,h in api['required_sources'].items():
        if custody._hash(root/rel)!=h:raise ValueError('released NDA dependency differs')
    if c['symbolic_template'] is not None:
        sp=custody._pin(c['symbolic_template'],p.parent)
        from ravel.physics import symbolic_evaluation
        files += symbolic_evaluation.inputs({'input':str(sp),'input_sha256':custody._hash(sp)},sp.parent)
        if custody._hash(custody._pin(document(sp)['original_task'],sp.parent))!=custody._hash(custody._pin(c['original_task'],p.parent)):raise ValueError('symbolic handoff and original diagram task differ')
    if c['nda_runtime'] is not None:
        rf,_,_=fg.runtime({'runtime':c['nda_runtime']},p.parent);files+=rf
    files += [Path(__file__),Path(__file__).with_name('diagram_analysis_worker.py')]
    return sorted(set(files))
def execution_seconds(task,base):return load(task,base)[1]['max_seconds']
def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']:raise ValueError('one-attempt delivery-only diagram-analysis scope required')
    return spec

def source_vertex(diagram,splittings):
    if len(diagram['vertices'])!=1 or diagram['propagators'] or diagram['loops']:raise ValueError('existing decay EDA requires exact one-vertex tree')
    interaction=diagram['vertices'][0]['interaction']['name'];split=[s['name'] for s in splittings if s['splitting'] and interaction in s['splitting']]
    if split:raise ValueError('split Lorentz/color vertex subset needs a separate exact consumer; retain unsupported diagram')
    return interaction

def compile_row(row,process,e,template,tp,work):
    if len(process['incoming'])!=1 or len(process['outgoing'])!=2:raise ValueError('existing EDA/NDA supports source-matched one-to-two decay, no inferred crossing')
    vertex=source_vertex(row,e['delivery']['source_vertex_splittings']);doc=deepcopy(template);doc['vertex']=vertex;doc['parent_pdg']=row['incoming'][0]['particle']['pdg']
    docpath=work/'ufo-request.json'
    # Resolve source locators against their authenticated original base.
    for key in ('parameter_card',):doc[key]={'path':str(custody._pin(doc[key],tp.parent)),'sha256':doc[key]['sha256']}
    root,manifest,_=custody._tree(doc['model_tree'],tp.parent);doc['model_tree']={'root':str(root),'manifest':{'path':str(manifest),'sha256':custody._hash(manifest)}}
    engine_model=e['configuration']['model'];engine_root,_,_=custody._tree(engine_model['tree'],Path(e['operation_input']['path']).parent)
    if engine_model['kind']!='ufo' or root.resolve()!=(engine_root/engine_model['entry']).resolve():raise ValueError('EDA actual whole UFO differs from enumerated model')
    for key,pin in doc['backend_files'].items():doc['backend_files'][key]={'path':str(custody._pin(pin,tp.parent)),'sha256':pin['sha256']}
    fg.write(docpath,doc);compiled,details,_=ufo_decay.prepare({'input':str(docpath)},work)
    source_pdgs=[p['pdg'] for p in details['source_leg_records']]
    native_pdgs=[p['pdg'] for p in row['vertices'][0]['particles_ordered']]
    if source_pdgs!=native_pdgs or sorted(abs(p['pdg']) for p in details['source_leg_records'][:2])!=sorted(abs(x['particle']['pdg']) for x in row['outgoing']):raise ValueError('exact source vertex/external identity differs')
    report=ufo_decay.run({'input':str(docpath)},work,work/'eda');return compiled,details,report

def nda_diagram(compiled,details):
    d=deepcopy(compiled['diagram']);couplings={}
    for k,v in details['coefficient_coordinates'].items():
        if v['imag']!=0:raise ValueError('released NDA real-coupling approximation does not consume complex phases')
        couplings[k]=v['real']
    d['couplings']=couplings;d['topology']='tree_2body';return d

def symbolic_handoff(report, did, template_pin, base, directory):
    """Exact generated script -> existing numeric symbolic consumer; no execution."""
    import re
    from ravel.physics import symbolic_evaluation as symbolic
    tp=custody._pin(template_pin,base);c=deepcopy(document(tp));symbolic.validate_config(c)
    if c['schema_version']!=1:raise ValueError('decay consumer uses original scalar symbolic schema1')
    # Carry the original provider/runtime source identities, resolving locators once.
    for key in ('original_task','kernel','application_metadata'):
        c[key]={'path':str(custody._pin(c[key],tp.parent)),'sha256':c[key]['sha256']}
    for key in ('provider_tree',):
        root,manifest,_=custody._tree(c[key],tp.parent);c[key]={'root':str(root),'manifest':{'path':str(manifest),'sha256':custody._hash(manifest)}}
    for name,pin in c['backend_files'].items():c['backend_files'][name]={'path':str(custody._pin(pin,tp.parent)),'sha256':pin['sha256']}
    rt=c['python_runtime'];rt['python']={'path':str(custody._pin(rt['python'],tp.parent)),'sha256':rt['python']['sha256']}
    for key in ('sympy_tree','mpmath_tree'):
        root,manifest,_=custody._tree(rt[key],tp.parent);rt[key]={'root':str(root),'manifest':{'path':str(manifest),'sha256':custody._hash(manifest)}}
    script=custody._pin({'path':report['supplied_point_script']['path'],'sha256':report['supplied_point_script']['sha256']},directory)
    raw=script.read_bytes();root=directory/'symbolic-handoff-source';root.mkdir();source=root/'decay.wl';fg.write_bytes(source,raw)
    markers={k:[] for k in ('symbolic','numerical','latex')};kinds={'SYMBOLIC_RESULT':'symbolic','NUMERICAL_RESULT':'numerical','LATEX_RESULT':'latex'}
    for kind,key in re.findall(r'Print\["(SYMBOLIC_RESULT|NUMERICAL_RESULT|LATEX_RESULT)\[([^\]]+)\]:',raw.decode()):markers[kinds[kind]].append(key)
    statuses=re.findall(r'Print\["STATUS: ([^"]+)"',raw.decode())
    if statuses!=['complete'] or any(len(set(v))!=len(v) for v in markers.values()):raise ValueError('original scalar marker program not complete/unique')
    markers['status']='complete';manifest=directory/'symbolic-source-manifest.json';fg.write(manifest,custody.source_tree(root));c['script_tree']={'root':str(root),'manifest':{'path':str(manifest),'sha256':custody._hash(manifest)}}
    identity='dg_'+hashlib.sha256(did.encode()).hexdigest()[:24]+'_width';c['scripts']=[{'id':identity,'relative_path':'decay.wl','sha256':custody._hash(source),'markers':markers,'results':[{'id':identity,'symbol':'ravelWidthPoint','variables':[],'units':'GeV','dimension_GeV':1,'conventions':report['supplied_point_substitution_policy'],'assumptions':['Source-selected on-shell decay partial width; tree only; actual complex couplings preserved before substitution.'],'points':[]}]}]
    symbolic.validate_config(c);request=directory/'symbolic-handoff.json';pin=fg.write(request,c)
    return {'mode':'symbolic-evaluation','task':{'input':pin['path'],'input_sha256':pin['sha256']},'result_id':identity,'source_model_and_diagram':did,'execution_authorized':False,'physics_validated':False}

def run(task,base,output):
    out=Path(output).resolve();rd,plan=fg.approved(task,out,'diagram-analysis');p,c=load(task,base);before=fg.identity(inputs(task,base));ep,e,op,cfg=enumeration(c,p.parent)
    if c['max_seconds']>plan['max_seconds'] or out.exists():raise ValueError('fresh admitted analysis output/budget required')
    out.mkdir(parents=True);work=rd/'work/diagram-analysis'/out.name
    if work.exists():raise ValueError('fresh analysis workspace required')
    work.mkdir(parents=True);tp=custody._pin(c['ufo_request_template'],p.parent);template=document(tp);rows=[];nda=[];started=time.monotonic()
    for proc in e['delivery']['processes']:
        for diagram in proc['diagrams']:
            did=proc['request']['id']+'-d'+str(diagram['id']);r={'id':did,'process_id':proc['request']['id'],'diagram_id':diagram['id'],'status':'unsupported','eda':None,'nda':None};rows.append(r);dout=out/did;dout.mkdir()
            try:
                if time.monotonic()-started>=c['max_seconds']:raise ValueError('analysis aggregate budget exhausted')
                compiled,details,report=compile_row(diagram,proc['request'],e,template,tp,dout);r.update(status='constructed',eda=report,source=details)
                if report['status']!='passed':raise ValueError('existing EDA construction failed')
                if c['symbolic_template'] is not None:r['symbolic_handoff']=symbolic_handoff(report,did,c['symbolic_template'],p.parent,dout)
                if c['nda_runtime'] is not None:
                    try:nda.append({'id':did,'diagram':nda_diagram(compiled,details)})
                    except ValueError as ex:r['nda']={'status':'unsupported','reason':str(ex)}
            except Exception as ex:r.update(status='unsupported',reason=type(ex).__name__+': '+str(ex))
    native_receipt=None
    if nda:
        native=out/'nda-native';native.mkdir();source=Path(__file__).with_name('diagram_analysis_worker.py');driver=native/'driver.py';driver.write_bytes(source.read_bytes());root,manifest,members=custody._tree(c['heptapod_source'],p.parent);rf,python,sites=fg.runtime({'runtime':c['nda_runtime']},p.parent);req=native/'request.json';request={'diagrams':nda,'source_root':str(root),'sites':[str(x) for x in sites],'assets':{str(x):custody._hash(x) for x in [*rf,*members]},'driver_sha256':custody._hash(source),'output':str(native)};fg.write(req,request);selected=fg.identity([driver,req])
        try:
            from ravel.physics.reinterpret_db import execute_native
            remaining=c['max_seconds']-(time.monotonic()-started)
            if remaining<=0:raise ValueError('no remaining admitted NDA time')
            native_receipt=execute_native([str(python),'-I','-B',str(driver),str(req)],native,dict(c,max_seconds=remaining));answer=document(native/'nda-result.json')
            if [x['id'] for x in answer['rows']]!=[x['id'] for x in nda] or selected!=fg.identity([driver,req]):raise ValueError('NDA whole population/native selection differs')
            for item in answer['rows']:next(x for x in rows if x['id']==item['id'])['nda']=item
        except Exception as ex:
            for item in nda:next(x for x in rows if x['id']==item['id'])['nda']={'status':'failed','reason':type(ex).__name__+': '+str(ex)}
    initial=fg.members(out);result={'schema_version':1,'status':'passed' if all(x['status']=='constructed' and (x['nda'] is None or x['nda'].get('status')=='delivered') for x in rows) else 'failed','status_scope':SCOPE,'original_task':c['original_task'],'enumeration':c['enumeration'],'requested_diagram_count':sum(x['count'] for x in e['delivery']['processes']),'rows':rows,'nda_native_execution':native_receipt,'physics_validated':False,'original_task_complete':False,'coherent_process_width':None,'branching_ratio':None,'limitations':['NDA is a per-diagram real-coupling scaling estimate, not a coherent amplitude.','EDA uses finite source-backed single-vertex SSS/SFF/VFF only; split/loop/other diagrams remain explicit.','All EDA scripts are unexecuted until separately admitted symbolic-evaluation.','No exact process rate obtained by summing squared diagram results.']}
    return fg.finish(task,base,out,result,initial,before,c['max_output_bytes'],input_loader=inputs)
def finalize(result,output,common=None):return fg.finalize(result,output,common=common)
def context_inputs(task,base):
    inputs(task,base);p,c=load(task,base);ep,e,op,cfg=enumeration(c,p.parent)
    files=[p,ep,fg.API,Path(__file__),Path(__file__).with_name('diagram_analysis_worker.py'),custody._pin(c['original_task'],p.parent),*fg.context_inputs({'input':str(op),'input_sha256':custody._hash(op)},op.parent),custody._pin(c['heptapod_source']['manifest'],p.parent)]
    tp=custody._pin(c['ufo_request_template'],p.parent);t=document(tp);files += [tp,custody._pin(t['model_tree']['manifest'],tp.parent),custody._pin(t['parameter_card'],tp.parent),*[custody._pin(q,tp.parent) for q in t['backend_files'].values()]]
    if c['nda_runtime'] is not None:
        files += [custody._pin(c['nda_runtime']['python'],p.parent),*[custody._pin(t['manifest'],p.parent) for t in c['nda_runtime']['trees']]]
    if c['symbolic_template'] is not None:
        from ravel.physics import symbolic_evaluation
        sp=custody._pin(c['symbolic_template'],p.parent);files += symbolic_evaluation.context_inputs({'input':str(sp),'input_sha256':custody._hash(sp)},sp.parent)
    return sorted(set(files))
def context(task,base):
    p,c=load(task,base);return {'schema_version':1,'mode':'diagram-analysis','configuration':c,'execution_authorized':False,'physics_validated':False}
def write_report(output,result):
    p=Path(output)/'diagram-report.md'
    if not isinstance(result,fg.Delivery) or fg.encoded(dict(result))!=fg.encoded(result.expected):raise ValueError('report requires original analysis result')
    raw=('# Model-bound diagram analysis\n\n'+result['status']+'; '+str(result['requested_diagram_count'])+' requested diagrams retained.\n\n'+'\n'.join(x['id']+': '+x['status']+('; '+x.get('reason','') if 'reason' in x else '') for x in result['rows'])+'\n\nNDA estimates and unexecuted EDA are distinguished. Coherent physical width and BR remain unresolved.\n').encode()
    result.artifacts['diagram-report.md']=hashlib.sha256(raw).hexdigest();fg.write_bytes(p,raw)
    return [{'stem':'diagram-report','files':['diagram-report.md','diagram-result.json'],'kind':'model-bound-diagram-analysis'}]

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('inspect',));parser.add_argument('--input',required=True);parser.add_argument('--input-sha256',required=True);a=parser.parse_args(argv)
    task={'input':a.input,'input_sha256':a.input_sha256};p,c=load(task,Path.cwd());_,e,_,_=enumeration(c,p.parent)
    print(json.dumps({'mode':'diagram-analysis','requested_diagrams':sum(x['count'] for x in e['delivery']['processes']),'inputs':len(inputs(task,Path.cwd())),'execution_authorized':False},indent=2));return 0
