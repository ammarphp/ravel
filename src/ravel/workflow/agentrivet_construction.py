"""Paper-first original AgentRivet construction through ordinary RAVEL services.

The supplied external source is never distributed here. Generation uses original
Agents/ReviewLoop, charged research Graphs and the configured Host. Build/event
execution, failed-stage diagnosis and independent final acceptance use existing
services. Preparation grants no launch, scientific vote or automatic redo.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
from types import ModuleType

from ravel.physics import agentrivet_candidate as candidate, agentrivet_source, hepdata_table_map, rivet_sample_checks
from . import agent_graph, agentrivet_brief, agentrivet_checks, agentrivet_pins, agentrivet_runtime, research_cycle, science, state_io
from .agentrivet_provider import GraphLLM

MAX_MEMBER = 1024**2
MAX_SOURCE = 8*1024**2
MAX_REQUEST = 8*1024**2


def _path(path, base):
    p = Path(path); return research_cycle._ordinary(p if p.is_absolute() else Path(base)/p)


def _bytes(pin, base, maximum=MAX_REQUEST):
    candidate._closed(pin, {'path','sha256'})
    p, raw = research_cycle._bounded_source_snapshot(_path(pin['path'],base),maximum)
    if hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise ValueError('consumed construction input differs from its original commitment')
    return p, raw


def _document(pin, base):
    p, raw = _bytes(pin,base); return p,candidate._json(raw)


def _pin(path):
    p, raw = research_cycle._bounded_source_snapshot(path,MAX_REQUEST)
    return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()}


def _emit(path, value):
    """Commit intended serialization before writing, never changed reread bytes."""
    p = research_cycle._ordinary(path)
    raw = (json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>MAX_REQUEST or p.exists(): raise ValueError('fresh bounded construction output required')
    pin = {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()}
    state_io.atomic_json(p,value)
    if _bytes(pin,p.parent)[1]!=raw: raise ValueError('intended construction output changed')
    return pin


def _source(root, declared):
    root = research_cycle._ordinary(root)
    if type(declared) is not list or not 7<=len(declared)<=64:
        raise ValueError('complete bounded external source population required')
    expected={}; buffers={}
    for row in declared:
        candidate._closed(row,{'path','sha256'})
        name=row['path']; p=Path(name)
        if (type(name) is not str or p.is_absolute() or p.as_posix()!=name or '..' in p.parts
                or name in expected or p.suffix not in ('.py','.toml','.md') and name!='COPYING'):
            raise ValueError('distinct canonical original source/license members required')
        _,raw=_bytes({'path':str(root/p),'sha256':row['sha256']},root,MAX_MEMBER)
        expected[name]=row['sha256']; buffers[name]=raw
    required={'agentrivet/__init__.py','agentrivet/core.py','agentrivet/memory.py','pyproject.toml','COPYING',
              *['agentrivet/'+v[0] for v in agentrivet_runtime.ROLES.values()]}
    actual=set()
    for p in (root/'agentrivet').rglob('*'):
        if p.is_symlink(): raise ValueError('external source aliases are unsupported')
        if p.is_file() and p.suffix=='.py': actual.add(p.relative_to(root).as_posix())
    if not required<=set(expected) or actual!={n for n in expected if n.startswith('agentrivet/') and n.endswith('.py')}:
        raise ValueError('complete original Python source and license census required')
    if sum(map(len,buffers.values()))>MAX_SOURCE: raise ValueError('external source byte ceiling exceeded')
    # The bridge's loop/Memory invariants hold only for allowed upstream commits.
    agentrivet_pins.admit_census(declared)
    return buffers


REQUEST_FIELDS={'schema_version','campaign','upstream','paper','hepdata','metadata',
                'provider','initial_rounds','max_native_repairs','review_policy','approval_mode'}
IDENTIFIER='[A-Za-z][A-Za-z0-9_]{0,127}'


def _routine_name(request):
    """The original Memory routine name, checked before any role call is charged."""
    with _modules(request) as (core,roles,mm,pins,mp):
        memory=mm.Memory('')
        for k,v in request['metadata'].items():
            if v is not None: memory.set(k,v)
        with agentrivet_pins.no_subprocess('original Memory routine name'):
            routine=memory.rivetName()
    if type(routine) is not str or not re.fullmatch(IDENTIFIER,routine):
        raise ValueError(f'original Memory routine name {routine!r} is not a native identifier; '
                         'supply the inspire_id, collaboration and preprint_year metadata that name it')
    return routine


def _construction_inputs(construction, routine, base, rounds):
    """Validate the optional RAVEL construction inputs before any capture."""
    if construction is None: return None
    candidate._closed(construction,{'analysis_spec','hepdata_record','normalization','checks'})
    result={'spec':None,'spec_raw':None,'spec_sources':[],'table_map':None,'record_raw':None,'contract':[],'checks':None}
    if construction['analysis_spec'] is not None:
        result['spec']=agentrivet_brief.load_spec(construction['analysis_spec'],base,sources=result['spec_sources'])
        result['spec_raw']=_bytes(construction['analysis_spec'],base)[1]
    if construction['hepdata_record'] is not None:
        _,raw=_bytes(construction['hepdata_record'],base); record=candidate._json(raw)
        result['table_map']=hepdata_table_map.build(record); result['record_raw']=raw
    if construction['normalization'] is not None:
        result['contract']=rivet_sample_checks.validate_contract(construction['normalization'])
    elif result['spec'] is not None:
        result['contract']=rivet_sample_checks.contract_from_spec(result['spec'])
    if construction['checks'] is not None:
        result['checks']=agentrivet_checks.normalize(construction['checks'],base=base,rounds=rounds)
    return result


def _capture_construction(extra, routine, out, hep):
    """Write the captured construction inputs and the record-derived HEPData context."""
    captured={'analysis_spec':None,'hepdata_record':None,'table_map':None,'reference':None,
              'normalization':extra['contract'],'checks':extra['checks']}
    if extra['spec_raw'] is not None:
        (out/'analysis-spec.json').write_bytes(extra['spec_raw'])
        captured['analysis_spec']={'path':str(out/'analysis-spec.json'),'sha256':hashlib.sha256(extra['spec_raw']).hexdigest()}
        captured['analysis_spec_sources']=extra['spec_sources']
    if extra['table_map'] is not None:
        (out/'hepdata-record.json').write_bytes(extra['record_raw'])
        captured['hepdata_record']={'path':str(out/'hepdata-record.json'),'sha256':hashlib.sha256(extra['record_raw']).hexdigest()}
        captured['table_map']=_emit(out/'hepdata-map.json',extra['table_map'])
        record=extra['table_map'].get('record')
        hep['context']=_emit(out/'hepdata-context.json',{'hepdata_info':record if isinstance(record,str) else None,
            'hepdata_map':hepdata_table_map.upstream_map(extra['table_map'])})
        try:
            text=hepdata_table_map.reference_yoda(extra['table_map'],routine)
        except ValueError:
            text=None
        if text is not None:
            raw=text.encode(); target=out/'assets'/'reference.yoda'; target.parent.mkdir(exist_ok=True); target.write_bytes(raw)
            captured['reference']={'path':str(target),'sha256':hashlib.sha256(raw).hexdigest()}
            hep['assets'].append({'path':routine+'.yoda','role':'reference','input':dict(captured['reference'])})
    return captured


def _construction_pins(request):
    construction=request.get('construction') or {}
    return [construction[k] for k in ('analysis_spec','hepdata_record','table_map','reference') if construction.get(k)]


def prepare(request, *, base_dir, output_dir):
    """Capture complete source, paper/HEPData inputs and original parent scope.

    No existing routine/catalogue capsule is needed. Sources and model inputs
    are captured from one admitted byte buffer; the operation is still only a
    prospective proposal and does not make an ordinary scientific plan.
    """
    request=deepcopy(request)
    candidate._closed(request,REQUEST_FIELDS|({'construction'} if type(request) is dict and 'construction' in request else set()))
    if type(request['schema_version']) is not int or request['schema_version']!=1:
        raise ValueError('paper construction version1 required')
    campaign=_path(request['campaign'],base_dir); _,state=research_cycle._load(campaign)
    if 'goal_binding' not in state['contract']:
        raise ValueError('original parent assignment must be bound in the research campaign')
    candidate._closed(request['upstream'],{'root','files'})
    upstream=_path(request['upstream']['root'],base_dir); buffers=_source(upstream,request['upstream']['files'])
    candidate._closed(request['provider'],{'model','reasoning_effort','max_calls','max_output_tokens','max_wall_seconds'})
    initial=request['initial_rounds']; repairs=request['max_native_repairs']; provider=request['provider']
    # Repairs have their own triplets; they never consume an initial review round.
    if (type(initial) is not int or not 1<=initial<=3 or type(repairs) is not int or not 0<=repairs<=2
            or type(provider['max_calls']) is not int
            or provider['max_calls']!=1+3*(initial+repairs)
            or type(provider['max_output_tokens']) is not int or not 16<=provider['max_output_tokens']<=32000
            or type(provider['max_wall_seconds']) is not int or not provider['max_calls']<=provider['max_wall_seconds']<=7200
            or any(type(provider[k]) is not str or not provider[k].strip() for k in ('model','reasoning_effort'))):
        raise ValueError('complete Analyst/triplet population and finite total role budget required')
    candidate._closed(request['metadata'],{'arxiv_id','inspire_id','collaboration','preprint_year'})
    for k,v in request['metadata'].items():
        if v is not None and (type(v) is not str or not v.strip() or len(v)>256):
            raise ValueError('literal source analysis metadata required')
    if request['metadata']['arxiv_id'] is None: raise ValueError('original paper identifier required')
    paper_path,paper=_bytes(request['paper'],base_dir); paper.decode('utf-8')
    if not paper.strip(): raise ValueError('complete nonempty extracted paper text required')
    candidate._closed(request['hepdata'],{'context','assets'})
    hep=request['hepdata']; context=None; context_bytes=None
    if hep['context'] is not None:
        _,context_bytes=_bytes(hep['context'],base_dir); context=candidate._json(context_bytes)
        candidate._closed(context,{'hepdata_info','hepdata_map'})
        if ((context['hepdata_info'] is not None and type(context['hepdata_info']) is not str)
                or type(context['hepdata_map']) is not dict): raise ValueError('literal original HEPData context required')
    if type(hep['assets']) is not list or len(hep['assets'])>32: raise ValueError('complete finite HEPData/reference asset population required')
    from ravel.analysis_sources import relative_path
    assets=[]; asset_buffers=[]; asset_names=set()
    for row in hep['assets']:
        candidate._closed(row,{'path','role','input'}); _,raw=_bytes(row['input'],base_dir)
        if row['role'] not in {'header','reference','configuration','model','preprocessing','data','license'}:
            raise ValueError('explicit original asset purpose required')
        relative_path(row['path'])
        if row['path'] in asset_names: raise ValueError('distinct original asset paths required')
        asset_names.add(row['path'])
        assets.append(deepcopy(row)); asset_buffers.append(raw)
    routine=_routine_name(request)
    extra=_construction_inputs(request.get('construction'),routine,base_dir,initial+repairs)
    if extra is not None and extra['table_map'] is not None:
        if hep['context'] is not None: raise ValueError('supply a HEPData context or a HEPData record, not both')
        if routine+'.yoda' in asset_names: raise ValueError('the record-derived reference file would replace a supplied asset')
    out=research_cycle._ordinary(output_dir)
    if out.exists(): raise ValueError('fresh construction preparation directory required')
    out.mkdir(parents=True); captured=out/'external-source'; captured.mkdir()
    for name,raw in buffers.items():
        p=captured/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
        _bytes({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()},out,MAX_MEMBER)
    (out/'paper.txt').write_bytes(paper); request['paper']={'path':str(out/'paper.txt'),'sha256':hashlib.sha256(paper).hexdigest()}
    if context_bytes is not None:
        (out/'hepdata-context.json').write_bytes(context_bytes)
        hep['context']={'path':str(out/'hepdata-context.json'),'sha256':hashlib.sha256(context_bytes).hexdigest()}
    for index,(row,raw) in enumerate(zip(assets,asset_buffers)):
        target=out/'assets'/f'{index:02d}'; target.parent.mkdir(exist_ok=True); target.write_bytes(raw)
        row['input']={'path':str(target),'sha256':hashlib.sha256(raw).hexdigest()}
    hep['assets']=assets
    if extra is not None:
        request['construction']=_capture_construction(extra,routine,out,hep)
    request['routine_name']=routine
    request['campaign']=str(campaign); request['upstream']['root']=str(captured)
    request['upstream_commit']=agentrivet_pins.admit_census(request['upstream']['files'])
    request['goal_binding']=deepcopy(state['contract']['goal_binding'])
    request['campaign_contract_sha256']=agent_graph.digest(state['contract'])
    request['original_sources']={'root':str(upstream),'files':deepcopy(request['upstream']['files']),
        'paper':{'path':str(paper_path),'sha256':hashlib.sha256(paper).hexdigest()}}
    # Retain full scope and actual current review policy through ordinary validation.
    check={'schema_version':2,'mode':'analyze','task':{'backend':'agentrivet-source','request':{'path':str(out/'not-yet-generated.json'),'sha256':'0'*64}},
        'source':'Original external AgentRivet source-bound paper construction','assumptions':['Generation is a proposal; independent source/native/paper review is required.'],
        'max_seconds':60,'max_attempts':1,'review_policy':request['review_policy'],
        'approval_mode':request['approval_mode'],'goal_binding':request['goal_binding']}
    science.validate(check)
    if _source(upstream,request['original_sources']['files'])!=buffers or _source(captured,request['upstream']['files'])!=buffers:
        raise ValueError('original or captured source changed during preparation')
    pin=_emit(out/'construction-request.json',request)
    _load(pin,out)
    return {'kind':'agentrivet-paper-first-preparation','request':pin,'execution_authorized':False,'physics_validated':False}


def _load(pin, base):
    p,request=_document(pin,base)
    if request.get('schema_version')!=1 or 'goal_binding' not in request: raise ValueError('prepared original construction request required')
    _,state=research_cycle._load(request['campaign'])
    if (agent_graph.digest(state['contract'])!=request['campaign_contract_sha256']
            or state['contract'].get('goal_binding')!=request['goal_binding']):
        raise ValueError('original campaign/parent assignment changed')
    _source(request['upstream']['root'],request['upstream']['files'])
    for item in [request['paper'],*([request['hepdata']['context']] if request['hepdata']['context'] else []),
                 *[r['input'] for r in request['hepdata']['assets']],*_construction_pins(request)]: _bytes(item,p.parent)
    return p,request


def input_pins(request, base):
    """Complete source/preparation dependencies for ordinary Host tools."""
    root=_path(request['upstream']['root'],base)
    _source(root,request['upstream']['files'])
    result=[{'path':str(root/row['path']),'sha256':row['sha256']} for row in request['upstream']['files']]
    result += [request['paper'],*([request['hepdata']['context']] if request['hepdata']['context'] else []),
               *[row['input'] for row in request['hepdata']['assets']],*_construction_pins(request)]
    campaign=_path(request['campaign'],base); _,state=research_cycle._load(campaign)
    # The original contract is immutable. A charged preparation Graph advances
    # the campaign head before Host dispatch; that mutable head is not an input.
    result.append(_pin(campaign/'history/0000.json'))
    goal=state['contract'].get('goal_binding')
    if goal is None: raise ValueError('original parent assignment required')
    result.append({k:goal['contract'][k] for k in ('path','sha256')})
    normalized=[]; seen=set()
    for pin in result:
        p,_=_bytes(pin,base)
        if str(p) in seen: continue
        seen.add(str(p)); normalized.append({'path':str(p),'sha256':pin['sha256']})
    return normalized


def context(request_pin, *, base_dir):
    p,request=_load(request_pin,base_dir)
    return {'kind':'agentrivet-ordinary-construction-context','request':request_pin,
        'original_parent':deepcopy(request['goal_binding']), 'paper':deepcopy(request['paper']),
        'source_members':deepcopy(request['upstream']['files']), 'provider':deepcopy(request['provider']),
        'initial_rounds':request['initial_rounds'],'max_native_repairs':request['max_native_repairs'],
        'source_inputs':input_pins(request,p.parent),
        'construction':deepcopy(request.get('construction')),'routine_name':request.get('routine_name'),
        'next_operations':[*(['approve-checks (once, before generation)'] if (request.get('construction') or {}).get('checks') else []),
            'generate through research_cycle.execute_graph','ordinary agentrivet-source plan/approve/run',
            'source closure and fresh runtime declaration','prepare-build then ordinary plan/approve/run',
            'prepare-events then ordinary plan/approve/run','current failed diagnostic or scientific send-back to repair',
            'independent source/event/paper reviews and task-completion require_final'],
        'prior_reviews_carried':[],'execution_authorized':False,'physics_validated':False}


@contextmanager
def _modules(request):
    """Load only captured original core/roles/Memory under an isolated name.

    The original provider modules are retained as source inputs but never
    imported here. Runtime dependency availability and arbitrary upstream import
    behavior still require the actual supplied runtime; this is not a sandbox.
    """
    root=Path(request['upstream']['root']); buffers=_source(root,request['upstream']['files'])
    prefix='_ravel_agentrivet_'+hashlib.sha256(str(root).encode()).hexdigest()[:20]
    if any(n==prefix or n.startswith(prefix+'.') for n in sys.modules): raise ValueError('external original module binding already active')
    package=ModuleType(prefix); package.__path__=[str(root/'agentrivet')]; sys.modules[prefix]=package
    def load(name):
        path=root/'agentrivet'/(name+'.py'); spec=importlib.util.spec_from_file_location(prefix+'.'+name,path)
        module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module
        # Execute the admitted buffer, never a second mutable pathname read.
        exec(compile(buffers['agentrivet/'+name+'.py'],str(path),'exec',dont_inherit=True),module.__dict__)
        return module
    try:
        features=agentrivet_pins.features(agentrivet_pins.admit_census(request['upstream']['files']))
        if features['compile_gate']:
            # The compile-gated core imports utils (for detect_rivet only) and
            # build. RAVEL supplies utils: the gate is on exactly when approved
            # construction checks are declared; build_routine is rebound later.
            shim=ModuleType(prefix+'.utils'); gate=bool((request.get('construction') or {}).get('checks'))
            shim.detect_rivet=lambda: gate
            shim.__doc__='RAVEL binding of the upstream compile-gate detection; no upstream utils code runs.'
            sys.modules[shim.__name__]=shim; package.utils=shim
        with agentrivet_pins.no_subprocess('original module import'):
            if features['compile_gate']: load('build')
            core=load('core'); roles={r:load(v[0][:-3]) for r,v in agentrivet_runtime.ROLES.items()}; memory=load('memory')
        pins={k:{'path':str(root/'agentrivet'/name),'sha256':hashlib.sha256(buffers['agentrivet/'+name]).hexdigest()}
              for k,name in [('core','core.py'),*[(r,v[0]) for r,v in agentrivet_runtime.ROLES.items()]]}
        yield core,roles,memory,pins,{'path':str(root/'agentrivet/memory.py'),'sha256':hashlib.sha256(buffers['agentrivet/memory.py']).hexdigest()}
        if _source(root,request['upstream']['files'])!=buffers: raise ValueError('external source changed during operation')
    finally:
        for name in list(sys.modules):
            if name==prefix or name.startswith(prefix+'.'): del sys.modules[name]


def _provider(request_path, request_pin, request, host):
    pins=[{'path':str(Path(request['upstream']['root'])/r['path']),'sha256':r['sha256']} for r in request['upstream']['files']]
    pins+=[deepcopy(request_pin),request['paper'],*([request['hepdata']['context']] if request['hepdata']['context'] else []),
           *[row['input'] for row in request['hepdata']['assets'] if row['input']['path'] not in {r['path'] for r in _construction_pins(request)}],
           *_construction_pins(request)]
    # The adapter/runtime implementation is retained in custody; role calls
    # present only their messages, the operation contract and a RAVEL brief.
    for path in (Path(__file__),Path(agentrivet_runtime.__file__)):
        if str(path.absolute()) not in {p['path'] for p in pins}: pins.append(_pin(path.absolute()))
    return GraphLLM.campaign(request_path.parent/'role-graphs',request['campaign'],host,
                             source_inputs=pins,**request['provider'])


class _Construction:
    """RAVEL construction context of one operation: briefs, checks and the compile gate."""

    def __init__(self, request, request_pin, construction_dir, routine, features):
        construction = request.get('construction') or {}
        self.routine, self.features = routine, features
        self.table_map = _document(construction['table_map'], construction_dir)[1] if construction.get('table_map') else None
        self.spec = _document(construction['analysis_spec'], construction_dir)[1] if construction.get('analysis_spec') else None
        self.contract = construction.get('normalization') or []
        reference = construction.get('reference')
        self.reference = _bytes(reference, construction_dir)[1].decode('utf-8') if reference else None
        self.histograms = []
        self.session = None
        if construction.get('checks') is not None:
            self.session = agentrivet_checks.Session(request, request_pin, construction_dir, routine,
                table_map=self.table_map, contract=self.contract, histograms=lambda: self.histograms,
                reference=self.reference).start()
        self.briefs = agentrivet_brief.Briefs(routine=routine, table_map=self.table_map, spec=self.spec,
                                              contract=self.contract, checks=self.session)

    @property
    def compile_gate(self):
        return self.features['compile_gate'] and self.session is not None

    def observer(self, code):
        return None if self.session is None else self.session.observe(code)

    def observed(self):
        if self.session is None: return None
        return {sha: agentrivet_checks.result_of(record) for sha, record in self.session.records.items()}

    def compiled(self, code):
        return self.session is not None and self.session.compiled(self.session.record_for(code))

    def track(self, memory):
        """Analyst histograms, for booking checks against the declared tables."""
        model = memory.get('analysis_model')
        data = model.model_dump(mode='json') if hasattr(model, 'model_dump') else None
        if isinstance(data, dict) and isinstance(data.get('histograms'), list):
            self.histograms[:] = data['histograms']


def _evidence(context, memory_data, generated_result, out):
    """Construction evidence for the independent review: checks, bookings and contracts."""
    selection = generated_result.get('selection') or generated_result['raw_request'].get('selection') or \
        {'draft_index': len(memory_data['code_draft']) - 1, 'basis': 'upstream_accepted' if memory_data.get('accepted_code') else 'last_draft'}
    selected = memory_data['code_draft'][selection['draft_index']]
    histograms = ((memory_data.get('analysis_model') or {}).get('data') or {}).get('histograms') or []
    booked = hepdata_table_map.bookings(selected)
    records = context.session.records if context.session is not None else {}
    drafts = [{'draft_index': k, 'sha256': hashlib.sha256(d.encode()).hexdigest(),
               'check': ({'path': str(Path(r['source']['path']).parent / 'record.json'),
                          'sha256': hashlib.sha256((Path(r['source']['path']).parent / 'record.json').read_bytes()).hexdigest()}
                         if (r := records.get(hashlib.sha256(d.encode()).hexdigest())) else None)}
              for k, d in enumerate(memory_data['code_draft'])]
    value = {'schema_version': 1, 'kind': 'agentrivet-construction-evidence', 'routine': context.routine,
             'selection': selection, 'drafts': drafts,
             'selected_check': agentrivet_checks.summary(records.get(hashlib.sha256(selected.encode()).hexdigest())),
             'selected_bookings': {'booked': booked,
                                   'findings': hepdata_table_map.verify_bookings(context.table_map, booked, histograms)},
             'review_checklist': agentrivet_brief.guidance()['checklist'],
             'ambiguities': agentrivet_brief.ambiguities(context.spec) if context.spec is not None else None,
             'normalization_contract': context.contract,
             'checks_approval': context.session.approval if context.session is not None else None,
             'scope': 'Construction feedback for review. Not a sealed build, a full event run, or scientific acceptance.',
             'physics_validated': False}
    return _emit(Path(out) / 'construction-evidence.json', value)


def _materialize(core,roles,llm,memory_module,memory,pins,memory_pin,request,out,context, *, predecessor=None,feedback=None,repair_count=0):
    routine=memory.rivetName()
    if not re.fullmatch(IDENTIFIER,routine): raise ValueError('original Memory routine identity is not an admitted native identifier')
    if request.get('routine_name',routine)!=routine: raise ValueError('original Memory routine name changed after preparation')
    result=agentrivet_runtime.prepare_source_study(core,roles,llm,memory_module,memory,source_pins=pins,
        memory_pin=memory_pin,routine=routine,assets=request['hepdata']['assets'],output_dir=out,
        review_policy=request['review_policy'],approval_mode=request['approval_mode'],
        compile_gate=context.compile_gate,observed=context.observed(),draft_compiled=context.compiled)
    spec_path=Path(result['source_study']['specification']['path']); spec=_document(result['source_study']['specification'],out)[1]
    # The source preparer preserves its legacy API. This new operation emits a
    # distinct parent-bound spec rather than rewriting that preparer's result.
    spec['goal_binding']=deepcopy(request['goal_binding']); science.validate(spec)
    result['source_study']['specification']=_emit(Path(out)/'parent-science-spec.json',spec)
    generated=_document(result['generation'],out)[1]
    result.update({'operation':'agentrivet-paper-first','predecessor':deepcopy(predecessor),'native_feedback':deepcopy(feedback),
        'generation_rounds':memory.get('iteration'),'native_repair_count':repair_count,
        'selection':deepcopy(generated['selection']),'compile_gate':context.compile_gate,
        'construction_evidence':_evidence(context,memory.to_dict(),{'selection':generated['selection'],'raw_request':result['raw_request']},out),
        'campaign_root':request['campaign'],'goal_binding':request['goal_binding']})
    return _emit(Path(out)/'generation-result.json',result)


def generate(request_pin, *, base_dir, host):
    p,request=_load(request_pin,base_dir)
    with state_io.file_lock(p.parent/'operation.lock',blocking=False),_modules(request) as (core,roles,mm,pins,mp):
        llm=_provider(p,request_pin,request,host)
        if llm.steps: raise ValueError('initial generation already attempted; use retained outcomes, never restart')
        memory=mm.Memory('')
        for k,v in request['metadata'].items():
            if v is not None: memory.set(k,v)
        memory.set('paper_text',_bytes(request['paper'],p.parent)[1].decode('utf-8'))
        if request['hepdata']['context']:
            for k,v in _document(request['hepdata']['context'],p.parent)[1].items(): memory.set(k,v)
        routine=memory.rivetName()
        if request.get('routine_name',routine)!=routine or not re.fullmatch(IDENTIFIER,routine):
            raise ValueError('original Memory routine name differs from its prepared native identifier')
        features=agentrivet_pins.features(request['upstream_commit'])
        context=_Construction(request,request_pin,p.parent,routine,features)
        def observe(code):
            context.track(memory)
            return context.observer(code)
        loop,_=agentrivet_runtime.instantiate(core,roles,llm,source_pins=pins,provider='ravel-graph',
                 model=request['provider']['model'],max_iterations=request['initial_rounds'],
                 brief_source=context.briefs,observer=observe)
        if bool(getattr(loop,'compiler',False))!=context.compile_gate:
            raise ValueError('upstream compile gate differs from the approved RAVEL construction checks')
        with agentrivet_runtime.bind_compile(core,context.session),agentrivet_pins.no_subprocess('original ReviewLoop.run'):
            loop.run(memory)
        result=_materialize(core,roles,llm,mm,memory,pins,mp,request,p.parent/'generations/initial',context)
        _load(request_pin,base_dir); return result


def _ordinary_result(rundir, backend):
    """Existing approved execution/current-census law, with no acceptance vote."""
    from . import execution
    rd=science.root(rundir)
    session=execution._validation_session(rd)
    try:
        plan=science.verify_plan(rd,approved=True,_session=session)
        stage,_,_=science._selected(rd,plan,_session=session)
        errors=execution.validate_completed_execution(rd,[stage],_session=session)
        if errors: raise ValueError('; '.join(errors))
        spec=science.execution_spec(rd,_proposal=plan,_session=session)
        if spec['task']['backend']!=backend: raise ValueError('actual ordinary stage has another backend')
        out=rd/stage['outputs'][0]; result=session.read_document(out/'result.json')
        if result.get('status')!='passed' or result.get('physics_validated') is not False:
            raise ValueError('ordinary adapter postconditions did not pass')
        verification=session.read_document(out/'verification.json')
        if (verification.get('passed') is not True or verification.get('scope')!=spec['mode']
                or verification.get('result_sha256')!=session.hash_file(out/'result.json')
                or verification.get('physics_validated') is not False or verification.get('expert_review') is not False):
            raise ValueError('ordinary verification does not bind the actual delivered result')
        pin={'path':str(out/'result.json'),'sha256':session.hash_file(out/'result.json')}
        ending=session.finish()
        if ending: raise ValueError('; '.join(ending))
        return spec,out,result,pin
    finally:
        session.close()


def _generation(request, pin, base):
    p,generation=_document(pin,base)
    if (generation.get('operation')!='agentrivet-paper-first' or generation.get('campaign_root')!=request['campaign']
            or generation.get('goal_binding')!=request['goal_binding'] or generation.get('physics_validated') is not False):
        raise ValueError('exact original operation generation required')
    _,memory=_document(generation['raw_request']['memory'],p.parent)
    selection=generation['raw_request'].get('selection') or {'draft_index':len(memory['code_draft'])-1}
    if _bytes(generation['raw_request']['translation_unit'],p.parent)[1]!=memory['code_draft'][selection['draft_index']].encode():
        raise ValueError('generation translation unit/Memory differs')
    llm=GraphLLM.retained_campaign(Path(request['upstream']['root']).parent/'role-graphs',request['campaign'])
    actual=agentrivet_runtime.generation_outputs(llm)
    _,raw_generation=_document(generation['generation'],p.parent)
    if (raw_generation['transcript']!=actual or memory.get('analysis_model',{}).get('data')!=actual['steps'][0]['value']):
        raise ValueError('generation differs from the complete actual source-role history')
    compile_gate=bool(generation.get('compile_gate'))
    observed=None
    if compile_gate:
        observed={sha:agentrivet_checks.result_of(r) for sha,r in agentrivet_checks.retained(Path(request['upstream']['root']).parent).items()}
    agentrivet_runtime.verify_memory(memory,actual['steps'],compile_gate=compile_gate,observed=observed)
    if memory.get('paper_text')!=_bytes(request['paper'],base)[1].decode('utf-8'):
        raise ValueError('generation replaces the original full paper')
    return p,generation,memory


def _workload(request_pin, request, workload_pin, operation, base):
    """Admit a pinned prospective ceiling without reserving or renewing it."""
    path, workload = _document(workload_pin, base)
    candidate._closed(workload, {'schema_version','kind','operation','construction_request','max_seconds'})
    if (type(workload['schema_version']) is not int or workload['schema_version'] != 1
            or workload['kind'] != 'agentrivet-ordinary-workload' or workload['operation'] != operation):
        raise ValueError('explicit original build/event workload declaration required')
    original_path, original_raw = _bytes(request_pin, base)
    selected_path, selected_raw = _bytes(workload['construction_request'], path.parent)
    if selected_path != original_path or selected_raw != original_raw:
        raise ValueError('workload belongs to another construction request')
    seconds = workload['max_seconds']
    if type(seconds) is not int or not 1 <= seconds <= 86400:
        raise ValueError('explicit finite whole ordinary workload ceiling required')
    _, state = research_cycle._load(request['campaign'])
    if (agent_graph.digest(state['contract']) != request['campaign_contract_sha256']
            or state['contract'].get('goal_binding') != request['goal_binding']):
        raise ValueError('original workload campaign/parent changed')
    usage = research_cycle._usage(state); budget = state['contract']['budget']
    if (seconds > budget['wall_seconds'] - usage['wall_seconds']
            or usage['native_attempts'] + 1 > budget['native_attempts']):
        raise ValueError('ordinary workload exceeds remaining original campaign budget')
    timing = state['timing']
    if timing['started_epoch'] is not None and seconds > max(0.0, timing['deadline_epoch'] - time.time()):
        raise ValueError('ordinary workload exceeds the original campaign deadline')
    return path, workload, seconds


def _study(request, task, source, assumption, *, base_dir, max_seconds):
    # Adapter execution_seconds may be an inner admission sentinel. The caller's
    # pinned complete ordinary ceiling, not that sentinel, owns this study.
    spec = {'schema_version':2,'mode':'analyze','source':source,'assumptions':[assumption],
        'task':deepcopy(task),'max_seconds':max_seconds,'max_attempts':1,
        'review_policy':deepcopy(request['review_policy']),
        'approval_mode':request['approval_mode'],'goal_binding':deepcopy(request['goal_binding'])}
    science.validate(spec)
    required = science.adapter(spec).execution_seconds(task, Path(base_dir))
    if type(required) is not int or not 1 <= required <= max_seconds:
        raise ValueError('declared whole workload omits the existing adapter execution budget')
    return spec


def _input_census(paths, base, session):
    """Use the existing descriptor observation for complete, possibly large inputs."""
    result = {}
    for value in paths:
        p = science.regular(value, base, _session=session)
        result[str(p)] = session.hash_file(p)
    return result


def _event_pin(pin, base, session):
    candidate._closed(pin, {'path','sha256'})
    if (type(pin['path']) is not str or not pin['path'].strip()
            or type(pin['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',pin['sha256']) is None):
        raise ValueError('exact original event input commitment required')
    p = science.regular(pin['path'], base, _session=session)
    if session.hash_file(p) != pin['sha256']:
        raise ValueError('original event input bytes differ from their commitment')
    return {'path':str(p),'sha256':pin['sha256']}


def _relocate_event_task(task, base, session):
    """Rebase only the existing typed filesystem slots, never native object paths."""
    from ravel.physics import existing_events
    original = deepcopy(task); existing_events.validate(original)
    observed = _input_census(existing_events.inputs(original, base), base, session)
    relocated = deepcopy(original)
    for key in ('events','metadata','build_plan','build_receipt'):
        relocated[key] = str(science.regular(original[key], base, _session=session))
    # Existing runtime admission resolves executable aliases and pins their
    # targets; scientific data/source slots retain the no-alias law above.
    python = (Path(base)/original['runtime']['python']).resolve()
    relocated['runtime']['python'] = str(science.regular(python, base, _session=session))
    if 'grounding' in original:
        relocated['grounding'] = [_event_pin(pin,base,session) for pin in original['grounding']]
    for key in ('improvement_lineage','improvement_evaluation'):
        if key in original: relocated[key] = _event_pin(original[key],base,session)
    if 'centrality_preload' in original:
        preload = relocated['centrality_preload']
        preload['path'] = _event_pin({k:preload[k] for k in ('path','sha256')},base,session)['path']
        preload['origin'] = _event_pin(preload['origin'],base,session)
        for source in [preload['routine_source'],*preload['source_dependencies']]:
            source['path'] = _event_pin({k:source[k] for k in ('path','sha256')},base,session)['path']
    for quantity in relocated['observables']:
        if 'native_derived' in quantity: sources = [quantity['native_derived']['source']]
        elif 'native_density' in quantity:
            law = quantity['native_density']; sources = [law['source'],*law['source_dependencies']]
        elif 'native_categorical' in quantity:
            law = quantity['native_categorical']; sources = [law['source'],*law['source_dependencies']]
        elif 'native_cumulant' in quantity: sources = quantity['native_cumulant']['sources']
        else: sources = []
        for source in sources:
            source['path'] = _event_pin({k:source[k] for k in ('path','sha256')},base,session)['path']
    existing_events.validate(relocated)
    return original, relocated, observed


def _ground_event_task(task, additions, base, session):
    """Retain identical operation provenance once; conflicting identities refuse."""
    pins = list(task.get('grounding', [])); current = {row['path']:row for row in pins}
    for pin in additions:
        admitted = _event_pin(pin,base,session); old = current.get(admitted['path'])
        if old is not None and old != admitted:
            raise ValueError('conflicting original grounding identity')
        if old is None: pins.append(admitted); current[admitted['path']] = admitted
    task['grounding'] = pins


def prepare_build(request_pin, generation_pin, source_rundir, reviewed_capsule, closure, runtime, workload, *, probe, base_dir, output_dir):
    from . import execution
    p,request = _load(request_pin,base_dir); gp,generation,_ = _generation(request,generation_pin,base_dir)
    wp,workload_doc,seconds = _workload(request_pin,request,workload,'build',base_dir)
    spec,_,result,rp = _ordinary_result(source_rundir,'agentrivet-source')
    generated_spec = _document(generation['source_study']['specification'],gp.parent)[1]
    if spec != generated_spec: raise ValueError('ordinary materialization belongs to another generation')
    binding = agentrivet_source.prepare_build(rp,reviewed_capsule,closure,runtime,probe=probe,base_dir=base_dir,output_dir=output_dir)
    session = execution._validation_session(Path(output_dir))
    try:
        task = binding['task']
        before = _input_census(science.adapter({'mode':'analyze','task':task}).inputs(task,output_dir),output_dir,session)
        _input_census([p,gp,wp],base_dir,session)
        build_spec = _study(request,task,'Build the exact newly generated routine with supplied source/runtime',
            'Source closure declarations and native compilation are not paper fidelity or physics acceptance.',
            base_dir=output_dir,max_seconds=seconds)
        binding['workload'] = _event_pin(workload,base_dir,session)
        binding['source_inputs'] = [{'path':path,'sha256':sha} for path,sha in sorted(before.items())]
        binding['specification'] = _emit(Path(output_dir)/'science-spec.json',build_spec)
        binding['generation'] = _event_pin(generation_pin,base_dir,session)
        binding['construction_request'] = _event_pin(request_pin,base_dir,session)
        _load(request_pin,base_dir); _generation(request,generation_pin,base_dir)
        _ordinary_result(source_rundir,'agentrivet-source')
        if _workload(request_pin,request,workload,'build',base_dir)[1] != workload_doc:
            raise ValueError('original build workload changed')
        after = _input_census(science.task_inputs(build_spec,output_dir,_session=session),output_dir,session)
        if any(after.get(path) != sha for path,sha in before.items()):
            raise ValueError('complete original build input population changed')
        result_pin = _emit(Path(output_dir)/'ordinary-build-preparation.json',binding)
        _input_census([binding['specification']['path'],result_pin['path']],output_dir,session)
        errors = session.finish()
        if errors: raise ValueError('; '.join(errors))
        return result_pin
    finally: session.close()


def prepare_events(request_pin, generation_pin, build_rundir, event_task, histogram_mapping, workload, *, base_dir, output_dir):
    from ravel.physics import existing_events,routine_build
    from . import execution
    p,request = _load(request_pin,base_dir); gp,generation,memory = _generation(request,generation_pin,base_dir)
    wp,workload_doc,seconds = _workload(request_pin,request,workload,'events',base_dir)
    _,out,_,_ = _ordinary_result(build_rundir,'routine-build')
    plan_pin = _pin(out/'build-plan.json'); receipt_pin = _pin(out/'build-receipt.json')
    plan = _document(plan_pin,out)[1]; receipt = _document(receipt_pin,out)[1]
    routine = generation['raw_request']['routine']; routine_build.verify_receipt(receipt,plan,plan['base_dir'],out)
    source = routine_build.bound_routine(receipt,plan,out,routine)
    code_sha = generation['raw_request']['translation_unit']['sha256']
    if not any(row['sha256'] == code_sha for row in source['source_files']):
        raise ValueError('actual built source differs from the generated draft')
    task = deepcopy(event_task)
    for k,v in {'backend':'rivet-built','routine':routine,'build_plan':plan_pin['path'],'build_receipt':receipt_pin['path']}.items():
        if k in task and task[k] != v: raise ValueError('event request replaces its observed generated plugin')
        task[k] = v
    session = execution._validation_session(_path(base_dir,Path.cwd()))
    session.track(event_task); session.track(histogram_mapping)
    try:
        original,task,before = _relocate_event_task(task,base_dir,session)
        histograms = candidate._model(memory)['histograms']
        if (type(histogram_mapping) is not list or len(histogram_mapping) != len(histograms)
                or any(type(row) is not dict or set(row) != {'index','path'} for row in histogram_mapping)
                or any(type(row['index']) is not int or type(row['path']) is not str or not row['path'] for row in histogram_mapping)
                or [row['index'] for row in histogram_mapping] != list(range(len(histograms)))
                or len({r['path'] for r in histogram_mapping}) != len(histograms)
                or not {r['path'] for r in histogram_mapping} <= {r['path'] for r in task['observables']}):
            raise ValueError('complete original histogram-to-native-output census required')
        # Reviewers see the construction evidence: checks, bookings, checklist, contracts.
        evidence=[generation['construction_evidence']] if generation.get('construction_evidence') else []
        _ground_event_task(task,[request_pin,generation_pin,generation['raw_request']['paper'],workload,*evidence],base_dir,session)
        study = _study(request,task,'Evaluate the observed newly built routine on complete supplied events',
            'Event and paper/reference equivalence requires independent review; successful execution is not scientific acceptance.',
            base_dir=base_dir,max_seconds=seconds)
        out_new = research_cycle._ordinary(output_dir)
        if out_new.exists(): raise ValueError('fresh event-study preparation required')
        out_new.mkdir(parents=True)
        after = _input_census(science.task_inputs(study,out_new,_session=session),out_new,session)
        expected = dict(before)
        expected.update(_input_census([row['path'] for row in task['grounding']],base_dir,session))
        # Parent-contract inputs are a separate existing ordinary obligation.
        expected.update(_input_census(science.task_inputs(study,base_dir,_session=session),base_dir,session))
        if after != expected: raise ValueError('relocated event study changed its complete original input population')
        binding = {'kind':'agentrivet-ordinary-event-preparation',
            'construction_request':_event_pin(request_pin,base_dir,session),'generation':_event_pin(generation_pin,base_dir,session),
            'build_plan':plan_pin,'build_receipt':receipt_pin,'workload':_event_pin(workload,base_dir,session),
            'source_inputs':[{'path':path,'sha256':sha} for path,sha in sorted(after.items())],
            'histogram_mapping':deepcopy(histogram_mapping),'specification':_emit(out_new/'science-spec.json',study),
            'execution_authorized':False,'physics_validated':False}
        _load(request_pin,base_dir); _generation(request,generation_pin,base_dir)
        _ordinary_result(build_rundir,'routine-build')
        if (_workload(request_pin,request,workload,'events',base_dir)[1] != workload_doc
                or _input_census(existing_events.inputs(original,base_dir),base_dir,session) != before):
            raise ValueError('original event workload/input population changed')
        result_pin = _emit(out_new/'event-preparation.json',binding)
        _input_census([binding['specification']['path'],result_pin['path']],out_new,session)
        errors = session.finish()
        if errors: raise ValueError('; '.join(errors))
        return result_pin
    finally: session.close()


def repair(request_pin, generation_pin, feedback_pin, *, base_dir, host):
    """Actual retained failure/send-back -> one original coder call with its text, then reviews.

    The coder receives RAVEL's revision request: the selected draft, the
    compiler/build log text or the review findings, and its RAVEL brief.
    Repairs have their own prospectively reserved triplets and never consume an
    initial round. A compile-gated loop skips both reviews, as upstream does,
    when RAVEL's check of the new draft fails. Compiler success never supplies
    physics-review acceptance or a new budget.
    """
    from . import failed_stage_review,physics_review,execution
    p,request=_load(request_pin,base_dir); gp,generation,data=_generation(request,generation_pin,base_dir)
    fp,feedback=_document(feedback_pin,base_dir)
    if feedback.get('kind')=='failed_stage_diagnostic_intake':
        observed=failed_stage_review.verify(feedback,base_dir=feedback['run_dir'])
        inputs=failed_stage_review._files(observed['source_inputs'])
        kind,text=agentrivet_brief.failure_feedback(observed)
    else:
        candidate._closed(feedback,{'kind','rundir','claim_scope','summary'})
        if feedback['kind']!='agentrivet-current-review-send-back' or type(feedback['summary']) is not str or not feedback['summary'].strip():
            raise ValueError('actual failed-stage diagnostic or current scientific send-back required')
        rd=_path(feedback['rundir'],base_dir); view=physics_review.status(rd)
        if view['state']!='send_back' or view['claim_scope']!=feedback['claim_scope']:
            raise ValueError('current independent review send-back required')
        spec,_,_,_=_ordinary_result(rd,'rivet-built')
        # The ordinary verifier above authenticated the complete input census,
        # including large event/native assets. Do not apply this adapter's text
        # input cap to those existing native inputs.
        record=execution.load_execution(rd)['stages']['science']
        inputs=failed_stage_review._files(record['input_snapshot'])
        kind,text=agentrivet_brief.send_back_feedback(feedback['summary'],view)
    if generation['raw_request']['translation_unit']['sha256'] not in {r['sha256'] for r in inputs}:
        raise ValueError('actual feedback is not bound to the generated source')
    draft=_bytes(generation['raw_request']['translation_unit'],gp.parent)[1].decode('utf-8')
    with state_io.file_lock(p.parent/'operation.lock',blocking=False),_modules(request) as (core,roles,mm,pins,mp):
        llm=_provider(p,request_pin,request,host); transcript=agentrivet_runtime.generation_outputs(llm)
        if (llm.steps!=len(transcript['steps']) or type(generation.get('native_repair_count')) is not int
                or generation['native_repair_count']>=request['max_native_repairs']
                or llm.steps+3>llm.calls):
            raise ValueError('feedback predecessor is superseded or original repair budget exhausted')
        if (data['analysis_model'].get('data')!=transcript['steps'][0]['value']
                or data['paper_text']!=_bytes(request['paper'],p.parent)[1].decode('utf-8')):
            raise ValueError('feedback predecessor changed its original Analyst/paper input')
        if not request['max_native_repairs']: raise ValueError('native feedback was not prospectively admitted')
        features=agentrivet_pins.features(request['upstream_commit'])
        context=_Construction(request,request_pin,p.parent,generation['raw_request']['routine'],features)
        if context.compile_gate!=bool(generation.get('compile_gate')):
            raise ValueError('repair compile gate differs from its generation')
        # Preserve the earlier raw file/marker. A new draft cannot inherit it.
        state=deepcopy(data); state.pop('accepted_code',None); memory=mm.Memory.from_dict(state)
        context.track(memory)
        loop,_=agentrivet_runtime.instantiate(core,roles,llm,source_pins=pins,provider='ravel-graph',model=request['provider']['model'],
                                             max_iterations=1,brief_source=context.briefs,observer=context.observer)
        llm.last_draft=draft
        memory.set('iteration',data['iteration']+1)
        prompt=agentrivet_brief.repair_prompt(memory,generation['raw_request']['routine'],draft,kind,text)
        with agentrivet_pins.no_subprocess('original repair coder and reviewers'):
            memory.append('code_draft',loop.coder.run(prompt).strip())
            reviews=True
            if context.compile_gate:
                returncode,output=context.session.build_result(memory.get('code_draft')[-1])
                build=sys.modules[core.build_routine.__module__].BuildResult(returncode=returncode,output=output)
                memory.append('build_result',build); reviews=returncode==0
            if reviews:
                memory.append('code_review',loop.code_reviewer.run(loop._build_code_reviewer_prompt(memory)))
                memory.append('physics_review',loop.physics_reviewer.run(loop._build_physics_reviewer_prompt(memory)))
            else:
                memory.append('code_review',None); memory.append('physics_review',None)
        _bytes(feedback_pin,base_dir)
        if feedback.get('kind')=='failed_stage_diagnostic_intake': failed_stage_review.verify(feedback,base_dir=feedback['run_dir'])
        else:
            if physics_review.status(rd)!=view: raise ValueError('independent send-back changed during repair')
            _ordinary_result(rd,'rivet-built')
        result=_materialize(core,roles,llm,mm,memory,pins,mp,request,p.parent/f'generations/repair-{data["iteration"]:02d}',context,
                            predecessor=generation_pin,feedback=feedback_pin,repair_count=generation['native_repair_count']+1)
        _load(request_pin,base_dir); return result


def close(request_pin, generation_pin, completion_pin, *, base_dir):
    """Require real independent whole-parent acceptance through the public gate."""
    from . import task_completion
    p,request=_load(request_pin,base_dir); gp,generation,_=_generation(request,generation_pin,base_dir)
    candidate._closed(completion_pin,{'path','sha256','size'})
    completion_path,completion_raw=_bytes({k:completion_pin[k] for k in ('path','sha256')},base_dir)
    if type(completion_pin['size']) is not int or completion_pin['size']!=len(completion_raw):
        raise ValueError('original size-bound public task-completion input required')
    completion=candidate._json(completion_raw)
    if completion['contract']!=request['goal_binding']['contract']:
        raise ValueError('final completion must use the original parent contract')
    outcomes=[row for row in completion['outcomes'] if row['assignment_id']==request['goal_binding']['assignment_id']]
    if len(outcomes)!=1: raise ValueError('exact original routine assignment outcome required')
    event_root=_path(outcomes[0]['rundir'],base_dir)
    spec,_,_,_=_ordinary_result(event_root,'rivet-built')
    from ravel.physics import existing_events,routine_build
    rp,_,receipt,plan,_,_,_=existing_events._built_evidence(spec['task'],event_root)
    source=routine_build.bound_routine(receipt,plan,rp.parent,generation['raw_request']['routine'])
    if generation['raw_request']['translation_unit']['sha256'] not in {r['sha256'] for r in source['source_files']}:
        raise ValueError('whole-parent outcome is not the selected generated routine')
    result=task_completion.require_final(completion_pin,base_dir=base_dir)
    if not result['parent_task_accepted']: raise ValueError('original routine task remains open')
    _load(request_pin,base_dir); _generation(request,generation_pin,base_dir)
    _ordinary_result(event_root,'rivet-built')
    if _bytes({k:completion_pin[k] for k in ('path','sha256')},base_dir)[1]!=completion_raw:
        raise ValueError('original public completion bytes changed')
    return {'kind':'agentrivet-independent-parent-closure','generation':generation_pin,'completion':completion_pin,
        'parent_task_accepted':True,'whole_parent':result,'upstream_reviews_carried':[],
        'execution_authorized':False,'physics_validated':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); subs=parser.add_subparsers(dest='action',required=True)
    for name in ('prepare','context','approve-checks','generate','repair','prepare-build','prepare-events','close'):
        ap=subs.add_parser(name); ap.add_argument('--request',type=Path,required=True); ap.add_argument('--base',type=Path,default=Path.cwd())
        if name=='approve-checks':
            ap.add_argument('--quote',required=True,help='the approver\'s exact assent text')
            ap.add_argument('--scripted',action='store_true',help='scripted assent for a scripted_yes request; never human approval')
        if name in ('prepare','prepare-build','prepare-events'): ap.add_argument('--out',type=Path,required=True)
        if name in ('generate','repair'): ap.add_argument('--host-config',type=Path,required=True)
    args=parser.parse_args(argv); value=research_cycle._cli_document(args.request)
    if args.action=='prepare': result=prepare(value,base_dir=args.base,output_dir=args.out)
    elif args.action=='context': result=context(value,base_dir=args.base)
    elif args.action=='approve-checks': result=agentrivet_checks.approve(value,base_dir=args.base,quote=args.quote,scripted=args.scripted)
    elif args.action in ('generate','repair'):
        from .agent_host import AgentHost
        host=AgentHost.from_config(research_cycle._cli_document(args.host_config))
        if args.action=='generate': result=generate(value,base_dir=args.base,host=host)
        else: result=repair(value['request'],value['generation'],value['feedback'],base_dir=args.base,host=host)
    elif args.action=='prepare-build': result=prepare_build(value['request'],value['generation'],value['source_rundir'],value['reviewed_capsule'],value['closure'],value['runtime'],value['workload'],probe=value['probe'],base_dir=args.base,output_dir=args.out)
    elif args.action=='prepare-events': result=prepare_events(value['request'],value['generation'],value['build_rundir'],value['event_task'],value['histogram_mapping'],value['workload'],base_dir=args.base,output_dir=args.out)
    else: result=close(value['request'],value['generation'],value['completion'],base_dir=args.base)
    print(json.dumps(result,indent=2,allow_nan=False)); return 0


if __name__=='__main__': raise SystemExit(main())
