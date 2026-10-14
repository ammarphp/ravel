"""Supplied AgentRivet source -> ordinary study -> fresh routine-build preparation.

The upstream extraction and reviews remain supplier declarations. This adapter
does not import AgentRivet, dispatch a provider, compile, or carry its verdicts.
"""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import time
from ravel import analysis_sources
from ravel.physics import agentrivet_candidate as candidate
from ravel.workflow.state_io import atomic_json


def _pin(path):
    return {'path':str(Path(path).absolute()),'sha256':analysis_sources.digest(path)}


def _document(pin, base):
    path, raw = candidate._snapshot(pin, base)
    return path, candidate._json(raw)


def _emit(path, value):
    """Authenticate intended fresh preparation bytes before their first write."""
    path=Path(path).absolute()
    raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>candidate.MAX_FILE_BYTES or path.exists():
        raise ValueError('fresh bounded ordinary preparation output required')
    pin={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    atomic_json(path,value)
    if candidate._snapshot(pin,path.parent)[1]!=raw:
        raise ValueError('intended ordinary preparation bytes changed')
    return pin


def prepare_source_study(request, *, base_dir, output_dir, review_policy,
                         approval_mode='physicist'):
    """Write the ordinary version-2 study input; no plan or authority is made.

    A caller may pass literal outputs from the unchanged upstream ReviewLoop.
    Provider settings/transport and generation budgets are separate contracts.
    """
    from ravel.workflow import science
    out=Path(output_dir).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('fresh ordinary preparation directory required')
    request=deepcopy(request)
    # Normalize explicit input pins for relocation; parse the same authenticated
    # bytes now, without loading generated code or accepting domain declarations.
    for pin in [*[request[k] for k in ('translation_unit','memory','paper')],
                *[row['input'] for row in request['assets']]]:
        path,_=candidate._snapshot(pin,base_dir);pin['path']=str(path)
    out.mkdir(parents=True)
    request_path=out/'source-request.json';request_pin=_emit(request_path,request)
    task={'backend':'agentrivet-source','request':request_pin}
    _load(task,out)
    spec={'schema_version':2,'mode':'analyze',
        'source':'Caller-supplied AgentRivet candidate and domain declarations',
        'assumptions':['Source materialization does not qualify paper fidelity, native execution or physics.',
            'Upstream reviews remain producer annotations; ordinary scientific roles and approvals are separate.'],
        'max_seconds':60,'max_attempts':1,'approval_mode':approval_mode,
        'task':task,'review_policy':deepcopy(review_policy)}
    science.validate(spec)
    path=out/'science-spec.json';spec_pin=_emit(path,spec)
    _document(request_pin,out)
    return {'specification':spec_pin,'request':request_pin,'task':task,
        'execution_authorized':False,'physics_validated':False,'prior_reviews_carried':[]}


def validate(task):
    candidate._closed(task, {'backend','request'})
    if task['backend']!='agentrivet-source':
        raise ValueError('supplied AgentRivet source backend required')
    candidate._closed(task['request'], {'path','sha256'})


def _load(task, base):
    validate(task)
    path, request = _document(task['request'], base)
    candidate._closed(request, candidate.request_fields(request))
    pins=[task['request'],*[request[k] for k in ('translation_unit','memory','paper')]]
    if type(request['assets']) is not list or len(request['assets'])>32:
        raise ValueError('bounded asset population required')
    pins += [row['input'] for row in request['assets']]
    files=[]
    for pin in pins:
        # Embedded paths use the request document's directory, including when
        # the top-level request is addressed relative to the study base.
        q,_=candidate._snapshot(pin, base if pin is task['request'] else path.parent)
        files.append(q)
    return path, request, files


def inputs(task, base):
    _,_,files=_load(task, base)
    return list(dict.fromkeys([Path(__file__).absolute(),Path(candidate.__file__).absolute(),*files]))


def execution_seconds(task, base):
    _load(task, base)
    return 60


def run(task, base, out, *, worker_started=None):
    started=time.monotonic() if worker_started is None else worker_started
    request_path,request,_=_load(task,base)
    files=inputs(task,base);before={str(p):analysis_sources.digest(p) for p in files}
    result=candidate.import_candidate(request,base_dir=request_path.parent,output_dir=Path(out)/'candidate')
    if time.monotonic()-started>60:
        raise ValueError('source materialization deadline exceeded')
    for p in files:
        candidate._snapshot({'path':str(p),'sha256':before[str(p)]},base)
    _,proposal=_document(result['proposal'],out)
    if time.monotonic()-started>60:
        raise ValueError('source materialization deadline exceeded after custody')
    return {'status':'passed','kind':'agentrivet-source-materialization',
        'scope':'Exact supplier source and domain-declaration materialization; no paper or native qualification',
        'candidate_disposition':'unreviewed_source','prior_reviews_carried':[],
        **result,'domain_obligations':proposal['obligations'],
        'outstanding_obligations':proposal['outstanding_obligations'],
        'cached_paper_component_only':True,'provider_model_calls_authenticated':False,
        'model_calls':0,'native_calls':0,'execution_authorized':False,'physics_validated':False}


def run_in_worker(task,base,out,*,worker_started):
    return run(task,base,out,worker_started=worker_started)


def write_report(result,out):
    """Deliver all domain declarations without optional plotting dependencies."""
    out=Path(out)
    rows=['# Supplied routine domain declarations','',
        'These are unverified supplier declarations. Paper, API, native output and scientific reviews remain required.','']
    for row in result['domain_obligations']:
        rows += ['- '+row['id']+' (`'+row['selector']+'`): '+repr(row['declaration'])]
    rows += ['','Outstanding obligations:','',*['- '+x for x in result['outstanding_obligations']],'']
    (out/'domain-declarations.md').write_text('\n'.join(rows))
    return [{'stem':'domain-declarations','files':['domain-declarations.md']}]


def prepare_build(result_pin, reviewed_capsule_pin, closure_pin, runtime_pin, *, probe, base_dir, output_dir):
    """Prepare a fresh existing routine-build config; never approve or launch.

    The caller supplies a complete dependency declaration and a source report
    covering every domain obligation. A represented declaration still needs
    independent paper and native-event review. No source-stage acceptance is
    invented or required to be inherited as build authority.
    """
    from ravel.physics import routine_build
    rp,result=_document(result_pin,base_dir)
    if (result.get('kind')!='agentrivet-source-materialization' or result.get('status')!='passed'
            or result.get('candidate_disposition')!='unreviewed_source'
            or result.get('physics_validated') is not False or result.get('execution_authorized') is not False):
        raise ValueError('exact unreviewed source materialization result required')
    original_path,original=_document(result['capsule'],rp.parent)
    proposal_path,proposal=_document(result['proposal'],rp.parent)
    reviewed_path,reviewed=_document(reviewed_capsule_pin,base_dir)
    closure_path,closure=_document(closure_pin,base_dir)
    runtime_path,template=_document(runtime_pin,base_dir)
    analysis_sources.inventory(original,original_path.parent)
    analysis_sources.inventory(reviewed,reviewed_path.parent)
    old={f['path']:f for f in original['files']};new={f['path']:f for f in reviewed['files']}
    if (proposal.get('kind')!='imported-unqualified-agentrivet-source-proposal'
            or proposal['routine']!=original['routine']
            or result['domain_obligations']!=proposal['obligations']
            or result['outstanding_obligations']!=proposal['outstanding_obligations']
            or result.get('prior_reviews_carried')!=[]):
        raise ValueError('source materialization and pinned domain proposal differ')
    if (reviewed['routine']!=original['routine'] or reviewed['framework']!='rivet'
            or any(new.get(k)!=f for k,f in old.items())
            or not reviewed['dependency_review']['complete']
            or any(d['status']!='resolved' for d in reviewed['dependencies'])):
        raise ValueError('fresh complete capsule must retain every imported source/provenance fact')
    candidate._closed(closure, {'schema_version','kind','proposal','reviewed_capsule','reviewer','declarations','limitations'})
    if (type(closure['schema_version']) is not int or closure['schema_version']!=1 or closure['kind']!='agentrivet-source-closure-declaration'
            or closure['proposal']!=result['proposal'] or closure['reviewed_capsule']!=reviewed_capsule_pin
            or type(closure['reviewer']) is not str or not closure['reviewer'].strip()
            or type(closure['limitations']) is not list or not closure['limitations']
            or any(type(s) is not str or not s.strip() for s in closure['limitations'])):
        raise ValueError('explicit matching source review declaration required')
    expected={r['id']:r for r in proposal['obligations']};seen=set()
    if type(closure['declarations']) is not list:
        raise ValueError('complete domain source review census required')
    for row in closure['declarations']:
        candidate._closed(row,{'id','status','evidence'})
        if (row['id'] not in expected or row['id'] in seen
                or row['status'] not in ('represented','requires_event_test','unserved')
                or type(row['evidence']) is not str or not row['evidence'].strip()):
            raise ValueError('unique explicit domain review row required')
        seen.add(row['id'])
    if seen!=set(expected):raise ValueError('source review must cover every imported declaration')
    if template.get('kind')=='agentrivet-runtime-declaration':
        # A genuinely new paper-first routine needs no unrelated source capsule
        # or successful predecessor. Bind the complete supplied tool/artifact/
        # environment declaration when sealing THIS new source below.
        candidate._closed(template,{'schema_version','kind','runtime'})
        if type(template['schema_version']) is not int or template['schema_version']!=1:
            raise ValueError('explicit fresh runtime declaration version1 required')
    else:
        if (template.get('schema_version')!=2 or template.get('recipe',{}).get('name')!='rivet-plugin'
                or not template.get('execution_identity')):
            raise ValueError('sealed runtime template or explicit fresh runtime declaration required')
        if routine_build.seal_configuration({'backend':'routine-build','input':str(runtime_path)},runtime_path.parent)!=template:
            raise ValueError('selected runtime template no longer matches its source/tool identity')
    # Absolute pins permit relocation without changing runtime meaning. Never
    # copy the parent's execution_identity or source capsule into the new arm.
    runtime=deepcopy(template['runtime'])
    for f in [*runtime['tools'].values(),*runtime['artifacts']]:
        # Native artifacts retain the existing routine-build byte/alias checks;
        # the importer text-file cap is not a native binary/runtime policy.
        q=Path(f['path']);f['path']=str((q if q.is_absolute() else runtime_path.parent/q).absolute())
    draft={'schema_version':1,'source_capsule':str(reviewed_path),
        'recipe':deepcopy(proposal['next_build_recipe']),'runtime':runtime,'probe':deepcopy(probe)}
    # The new routine's exact arguments/denominator must be supplied; old
    # source-specific probe arguments cannot be silently transplanted.
    candidate._closed(probe,{'executable','arguments','expected_exit_code','stdout_contains'})
    if probe['stdout_contains']!=[original['routine']]:
        raise ValueError('new build requires its exact routine probe denominator')
    out=Path(output_dir).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('fresh ordinary preparation directory required')
    out.mkdir(parents=True)
    raw=out/'build-draft.json';draft_pin=_emit(raw,draft)
    sealed=routine_build.seal_configuration({'backend':'routine-build','input':str(raw)},out)
    _document(draft_pin,out)
    for pin in (result_pin,result['capsule'],result['proposal'],reviewed_capsule_pin,closure_pin,runtime_pin):
        _document(pin,base_dir if pin not in (result['capsule'],result['proposal']) else rp.parent)
    config=out/'build-sealed.json';sealed_pin=_emit(config,sealed)
    binding={'schema_version':1,'kind':'agentrivet-fresh-build-preparation',
        'source_result':result_pin,'original_capsule':result['capsule'],'proposal':result['proposal'],
        'reviewed_capsule':reviewed_capsule_pin,'closure_declaration':closure_pin,'runtime_template':runtime_pin,
        'draft':draft_pin,'sealed':sealed_pin,'task':{'backend':'routine-build','input':str(config)},
        'review_declaration_is_supplier_assertion':True,'unserved_domain_ids':[r['id'] for r in closure['declarations'] if r['status']=='unserved'],
        'prior_reviews_carried':[],'execution_authorized':False,'physics_validated':False}
    binding_pin=_emit(out/'build-binding.json',binding)
    for pin in (draft_pin,sealed_pin,binding_pin):_document(pin,out)
    return binding
