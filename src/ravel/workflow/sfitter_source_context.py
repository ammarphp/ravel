"""Complete SFitter designer custody with explicit bounded byte presentation.

The catalogue authenticates originals and copies, never a review vote or a claim
that a model read deferred scientific evidence. No dispatch or scheduler lives
here. Each reader retains a fresh original-source capture through its ending.
"""
import copy
import hashlib
import json
from pathlib import Path

from ravel.physics.ma5_saf import Capture
from . import review_context, state_io

KIND = 'sfitter_designer_source_packet_v1'
MAX_INPUTS = 4096
MAX_PAGES = 32
MAX_PAGE = 65536
DEFAULT_REQUEST_BYTES = 2_000_000


def _modules():
    from . import sfitter_conductor, sfitter_workflow, sfitter_application, sfitter_phase_continuation, agent_host, agent_graph
    return (sfitter_conductor, sfitter_workflow, sfitter_application, sfitter_phase_continuation, agent_host, agent_graph,
            review_context, __import__(__name__, fromlist=['_']))


def _raw(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False)+'\n').encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _load(context_pin, base):
    from . import sfitter_conductor as c
    capture=Capture();path,raw=capture.pin(context_pin,base);context=c._json(raw)
    request,request_path,capture=c._context(context,path.parent,capture,path)
    return path,context,request,request_path,capture


def _rows(context, capture, request, request_path, purpose):
    from . import sfitter_workflow as w
    if purpose not in ('lead','specialist','assembly'):raise ValueError('known SFitter source-packet purpose required')
    pins=copy.deepcopy(context['inputs'])
    if purpose=='assembly':
        for pin in w.assembly_inputs(request,request_path.parent):
            p,raw=capture.pin(pin,request_path.parent)
            pin={'path':str(p),'sha256':_sha(raw)}
            if pin not in pins:pins.append(pin)
    if not 1 <= len(pins) <= MAX_INPUTS:
        raise ValueError('complete SFitter source catalogue exceeds its declared domain bound')
    return [{'id':'input'+str(i),'pin':copy.deepcopy(pin),
             'size':len(capture.files[Path(pin['path'])][1]),'artifact_id':'source'+str(i)}
            for i,pin in enumerate(pins,1)]


def _core(context, request, request_path, rows):
    from . import sfitter_workflow as w, physics_review as review
    handoffs={}
    for phase,pin in request['handoffs'].items():
        cap=w._source_capture(request,request_path.parent)
        _,raw=cap.pin(pin,request_path.parent);handoffs[phase]=w._strict_document(raw);cap.finish()
    judgments=[]
    for binding in request.get('retained_review_contexts',[]):
        reg,events=review._read(Path(binding['root']));view=review._view(reg,events)
        judgments.append({'root':binding['root'],'cycle_id':view['cycle']['cycle_id'],
            'state':view['state'],'reviews':copy.deepcopy(view['reviews']),
            'findings':copy.deepcopy(view['findings']),'holds':copy.deepcopy(view['holds']),
            'correction':copy.deepcopy(view['correction']),
            'support':copy.deepcopy(binding['support']),
            'provenance_is_not_new_approval':True})
    return {'kind':'sfitter_designer_scientific_core','context':{k:copy.deepcopy(v) for k,v in context.items() if k!='inputs'},
        'completed_handoffs':handoffs,'retained_judgments':judgments,
        'catalogue_sha256':_sha(_raw(rows)),'catalogue':copy.deepcopy(rows),'input_count':len(rows),
        'deferred_content_read':False,'execution_authorized':False,'physics_validated':False,
        'presentation_rule':'Only the final call\'s authenticated complete byte pages support whole-pin evidence references; inventory is custody only.'}


def _selections(selections, rows):
    from . import sfitter_workflow as w
    if type(selections) is not list or len(selections)>MAX_PAGES:
        raise ValueError('at most 32 explicitly selected SFitter byte pages required')
    available={r['id']:r for r in rows};seen=set()
    for row in selections:
        w._closed(row,('input_id','offset','max_bytes'),'SFitter context page selection')
        key=(row['input_id'],row['offset'],row['max_bytes'])
        if (row['input_id'] not in available or type(row['offset']) is not int or
            not 0<=row['offset']<=available[row['input_id']]['size'] or
            type(row['max_bytes']) is not int or not 1<=row['max_bytes']<=MAX_PAGE or key in seen):
            raise ValueError('unique valid original-input byte ranges required')
        seen.add(key)
    return copy.deepcopy(selections)


def _pages(selections, rows, capture):
    available={r['id']:r for r in rows};pages=[]
    for i,selection in enumerate(selections):
        row=available[selection['input_id']];raw=capture.files[Path(row['pin']['path'])][1]
        page=review_context._artifact_page(raw,row['artifact_id'],offset=selection['offset'],max_bytes=selection['max_bytes'])
        pages.append({'id':'selected_page'+str(i),'value':{'kind':'sfitter_selected_source_page',
            'input_id':row['id'],'original_pin':row['pin'],**page,
            'whole_content_presented':page['offset']==0 and page['bytes']==len(raw)}})
    return pages


def _budget(core, pages, maximum):
    if type(maximum) is not int or not 1<=maximum<=DEFAULT_REQUEST_BYTES:
        raise ValueError('bounded SFitter model request bytes required')
    # This is the actual Host entry encoding/cost, including JSON wrappers and
    # escaping; source byte limits alone do not bound a serialized text page.
    entries=[('public_case',_raw(core)),*[(p['id'],_raw(p['value'])) for p in pages]]
    from . import agent_host
    cost=sum(len(agent_host._json_bytes({'id':i,'content':raw.decode()})) for i,raw in entries)
    if cost>maximum//4:raise ValueError('mandatory scientific core and selected pages exceed Host inline allowance')
    return entries


def prepare_lead_packet(context_pin, base, output, *, selections=None,
                        max_request_bytes=DEFAULT_REQUEST_BYTES, purpose='lead'):
    """Copy all authenticated sources; present only the declared core/pages."""
    from . import sfitter_conductor as c, sfitter_workflow as w
    path,context,request,rp,capture=_load(context_pin,base)
    rows=_rows(context,capture,request,rp,purpose);selections=_selections([] if selections is None else selections,rows)
    core=_core(context,request,rp,rows);pages=_pages(selections,rows,capture)
    inline=_budget(core,pages,max_request_bytes)
    out=c._fresh(output)
    c._protect(out,path.parent,Path(request['upstream_tree']['root']),context['consultation_graph'])
    for original in capture.files:
        if original.is_relative_to(out):raise ValueError('packet output must not contain an original source')
    sources=[]
    for module in _modules():
        p,raw=capture.pin(w._pin(Path(module.__file__)),base)
        sources.append({'path':str(p),'sha256':_sha(raw)})
    generated={};artifacts=[]
    def add(identity,raw,presentation,original=None):
        rel='artifacts/'+identity+'.txt'
        entry={'id':identity,'path':rel,'sha256':_sha(raw),'presentation':presentation,
               'projection':'exact bytes' if original else 'deterministic bounded SFitter material'}
        # Every artifact carries a source identity for the Host's producer-artifact check;
        # generated material names its own packet copy, never an original source.
        if original:entry.update(source_path=original['path'],source_sha256=original['sha256'])
        else:entry.update(source_path=str(out/rel),source_sha256=entry['sha256'])
        artifacts.append(entry);generated[rel]=raw
    for row in rows:add(row['artifact_id'],capture.files[Path(row['pin']['path'])][1],'on_demand',row['pin'])
    add('source_catalogue',_raw(rows),'on_demand')
    for identity,raw in inline:add(identity,raw,'inline')
    manifest={'schema_version':1,'kind':KIND,'role':'designer','purpose':purpose,'context':w._pin(path),
        'inputs':rows,'selections':selections,'max_request_bytes':max_request_bytes,
        'transport_sources':sources,'artifacts':artifacts,'omissions':[],
        'index_limits':review_context._index_limits(None),
        'execution_authorized':False,'physics_validated':False}
    if len(artifacts)>manifest['index_limits']['max_artifacts']:
        raise ValueError('complete SFitter packet exceeds artifact bound')
    manifest['sha256']=review_context.execution.digest(manifest)
    generated['manifest.json']=_raw(manifest)
    if (len(generated['manifest.json'])>review_context._MANIFEST_MAX_BYTES or
        sum(map(len,generated.values()))>64*1024**2):
        raise ValueError('complete SFitter packet exceeds byte bounds')
    capture.finish();out.mkdir(parents=True);(out/'artifacts').mkdir()
    for relative,raw in generated.items():(out/relative).write_bytes(raw)
    # These original emitted byte commitments survive all later callbacks.
    index=review_context._PacketIndex(out,manifest['sha256'])
    if index.manifest!=manifest or index.manifest_file_sha256!=_sha(generated['manifest.json']):raise ValueError('generated SFitter manifest differs from intended bytes')
    for entry in artifacts:
        if index.read(entry)!=generated[entry['path']]:raise ValueError('generated SFitter source/material changed')
    capture.finish();index.finish()
    return {'path':str(out),'manifest_sha256':manifest['sha256']}


def packet_capture(index):
    """Hard-coded _PacketIndex hook, holding originals until reader finish."""
    from . import sfitter_workflow as w
    m=index.manifest
    w._closed(m,('schema_version','kind','role','purpose','context','inputs','selections','max_request_bytes',
        'transport_sources','artifacts','omissions','index_limits','execution_authorized','physics_validated','sha256'),
        'SFitter designer source packet')
    if (m['schema_version']!=1 or m['kind']!=KIND or m['role']!='designer' or
        m['execution_authorized'] is not False or m['physics_validated'] is not False or m['omissions']!=[]):
        raise ValueError('SFitter source packet is designer custody only')
    path,context,request,rp,capture=_load(m['context'],index.root)
    if path.is_relative_to(index.root) or any(p.is_relative_to(index.root) for p in capture.files):
        raise ValueError('recursive SFitter packet source dependency refused')
    rows=_rows(context,capture,request,rp,m['purpose'])
    if m['inputs']!=rows:raise ValueError('whole original SFitter input catalogue differs')
    selections=_selections(m['selections'],rows);pages=_pages(selections,rows,capture)
    inline=_budget(_core(context,request,rp,rows),pages,m['max_request_bytes'])
    expected={r['artifact_id']:capture.files[Path(r['pin']['path'])][1] for r in rows}
    expected.update(source_catalogue=_raw(rows));expected.update(inline)
    if set(index.entries)!=set(expected):raise ValueError('complete SFitter packet artifact population differs')
    for identity,raw in expected.items():
        entry=index.entries[identity]
        original=next((r['pin'] for r in rows if r['artifact_id']==identity),None)
        intended={'id':identity,'path':'artifacts/'+identity+'.txt','sha256':_sha(raw),
            'presentation':'inline' if identity in dict(inline) else 'on_demand',
            'projection':'exact bytes' if original else 'deterministic bounded SFitter material'}
        if original:intended.update(source_path=original['path'],source_sha256=original['sha256'])
        else:intended.update(source_path=str(index.root/intended['path']),source_sha256=intended['sha256'])
        if entry!=intended or index.read(entry)!=raw:raise ValueError('SFitter copied scientific material differs from current original')
    sources=[]
    for module in _modules():
        p,raw=capture.pin(w._pin(Path(module.__file__)),index.root)
        sources.append({'path':str(p),'sha256':_sha(raw)})
    if m['transport_sources']!=sources:raise ValueError('current SFitter transport source epoch changed')
    return capture


def verified_lead_sources(node, context_pin, base, *, model_result=None):
    """One logical resolver shared by adoption and production, no read credit."""
    from . import sfitter_workflow as w
    if node['packet'] is None:
        return ({p['id']:{k:p[k] for k in ('path','sha256')} for p in node['inputs']},
                {(p['path'],p['sha256']) for p in node['inputs']})
    index=review_context._PacketIndex(node['packet']['path'],node['packet']['manifest_sha256'])
    m=index.manifest
    if m.get('kind')!=KIND or m['purpose']!='lead' or m['context']!=context_pin or node['role']!='designer':
        raise ValueError('one current SFitter designer packet bound to raw input0 required')
    if node['inputs']!=[{'id':'input0',**context_pin}]:raise ValueError('SFitter packet raw input0 differs')
    mapping={'input0':copy.deepcopy(context_pin),**{r['id']:copy.deepcopy(r['pin']) for r in m['inputs']}}
    full={(context_pin['path'],context_pin['sha256'])};required={index.entries['public_case']['sha256']}
    for selection in m['selections']:
        i=m['selections'].index(selection);entry=index.entries['selected_page'+str(i)]
        required.add(entry['sha256']);value=w._strict_document(index.read(entry))
    if model_result is not None:
        presentation=model_result.get('isolation',{}).get('evidence_presentation',{})
        actual=presentation.get('presented_subject_sha256s')
        if (presentation.get('manifest_sha256')!=m['sha256'] or type(actual) is not list or
            not required<=set(actual) or presentation.get('deferred_content_read') is not False):
            raise ValueError('mandatory SFitter core and every selected page must actually be presented in this call')
        # Merge intervals only for pages actually presented in the final call.
        for row in m['inputs']:
            intervals=[]
            for i,s in enumerate(m['selections']):
                if s['input_id']==row['id']:
                    page=w._strict_document(index.read(index.entries['selected_page'+str(i)]))
                    intervals.append((page['offset'],page['next_offset']))
            ending=0
            for start,stop in sorted(intervals):
                if start>ending:break
                ending=max(ending,stop)
            if intervals and ending==row['size']:full.add((row['pin']['path'],row['pin']['sha256']))
    index.finish();return mapping,full


def verified_packet_sources(packet_pin, request_pin, base, *, purpose):
    """Complete deterministic tool/specialist allowlist, without model credit."""
    from . import sfitter_workflow as w
    index=review_context._PacketIndex(packet_pin['path'],packet_pin['manifest_sha256'])
    m=index.manifest
    if m.get('kind')!=KIND or m['purpose']!=purpose:
        raise ValueError('matching source-bound SFitter packet purpose required')
    path,context,request,rp,capture=_load(m['context'],base)
    actual=w.custody._pin(request_pin,base)
    if rp!=actual or context['request']['sha256']!=request_pin['sha256']:
        raise ValueError('SFitter packet belongs to another workflow request')
    for entry in index.entries.values():index.read(entry)
    capture.finish();index.finish()
    return copy.deepcopy(m['context']),[copy.deepcopy(r['pin']) for r in m['inputs']]
