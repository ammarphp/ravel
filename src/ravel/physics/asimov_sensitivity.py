"""Ordinary same-source Asimov discovery diagnostic, using the native executor.

This adapter adds no optimizer, process launcher, sampler or approval route.
Its preparation is native_statistical_construction; all cells retain separate
ordinary budgets, source reviews and failed/unissued profile denominators.
"""
from pathlib import Path
from ravel.physics import native_likelihood as native, discovery_heldout as d

SCOPE='source_asimov_paired_profile_delivery'


def validate(task):
    return native.validate(task)


def _configuration(task,base,*,_session=None):
    value=native._configuration(task,base,_session=_session)
    if 'discovery_diagnostic' not in value[0]:raise ValueError('explicit same-data source discovery contract required')
    return value


def inputs(task,base,*,_session=None):
    from ravel.workflow.science import regular
    _configuration(task,base,_session=_session)
    return list(dict.fromkeys([*native.inputs(task,base,_session=_session),
        *[regular(Path(p),base,_session=_session) for p in (__file__,d.__file__)]]))


def execution_seconds(task,base,*,_session=None):
    return _configuration(task,base,_session=_session)[0]['max_seconds']


def _validation_inputs(task,base,session):return inputs(task,base,_session=session)
def _validation_execution_seconds(task,base,session):return execution_seconds(task,base,_session=session)


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{})
    if spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or set(policy.get('claim_scopes',{}))!={SCOPE} or policy['claim_scopes'][SCOPE].get('actions')!=['delivery']:
        raise ValueError('single ordinary diagnostic delivery; no physics/observed discovery authority')
    return spec


def context(task,base,*,_session=None):
    from ravel.workflow import science
    from ravel.physics import regional_expected
    if _session is None:
        with science._validation_scope(base) as session:return context(task,base,_session=session)
    cfg,*rest=_configuration(task,base,_session=_session);response=rest[7]
    inputs(task,base,_session=_session)
    cell=next(c for c in response['recipe']['cells'] if c['id']==response['cell'])
    return {'kind':d.KIND,'request':cfg['discovery_diagnostic'],'cell':cell,
        'complete_source_recipe':response['recipe'],'same_generated_dataset':cell['expected_data'],
        'source_law':cell['law'],'profile_policy':regional_expected.PROFILE_POLICY,
        'native_wall_seconds':cfg['max_seconds'],'fits_performed':0,'execution_authorized':False,
        'physics_validated':False,'coverage_qualified':False,'observed_significance':None,'global_significance':None,
        'scope':'One nonzero-signal source-generated Asimov experiment, same-NLL null/free profiles with complete raw fit/status/state/reset evidence. Local expected asymptotic proxy only; ordinary approval still required.'}


def graph(task,base,task_pin):
    from ravel.workflow import science,agent_graph
    with science._validation_scope(base) as session:
        path=science.regular(task_pin['path'],base,_session=session)
        if set(task_pin)!={'path','sha256'} or session.hash_file(path)!=task_pin['sha256'] or session.read_document(path)!=task:raise ValueError('exact declared discovery task required')
        dependencies=inputs(task,base,_session=session)
        pins=[{'id':'request','path':str(path),'sha256':session.hash_file(path)}]+[{'id':'source'+str(i),'path':str(p),'sha256':session.hash_file(p)} for i,p in enumerate(dependencies)]
    return agent_graph.validate({'schema_version':1,'graph_id':'discovery_heldout_context',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':60,'max_reworks':0},
        'nodes':[{'id':'context','kind':'tool','role':'designer','depends_on':[],'inputs':pins,'packet':None,
            'action':'asimov-sensitivity-context','parameters':{'request_input':'request'},'max_attempts':1}]})


def run(task,base,out):
    from ravel.physics import root_stream as stream,root_stream_core as c
    from ravel.workflow import science
    out=Path(out).absolute();owner=next((rd for rd in (out,*out.parents) if (rd/science.PLAN).is_file()),None)
    c.require(owner is not None,'ordinary approved sensitivity worker required')
    science.verify_worker(owner);spec=science.execution_spec(owner);validate_scope(spec)
    c.require(spec['mode']=='asimov-sensitivity' and spec['task']==task,'same actual diagnostic task required')
    cfg,*_=_configuration(task,base)
    dependencies=inputs(task,base)
    c.require(not any(out.is_relative_to(p.parent) for p in dependencies),'native diagnostic output must be disjoint from original source/runtime directories')
    result=native.run(task,base,out)
    result['status_scope']=SCOPE;result['original_task_complete']=False
    if result['status']=='failed':
        request=cfg['discovery_diagnostic'];witness=None
        journal=out/'native-work/ravel_discovery_heldout_journal.json'
        capture=c.Capture()
        if journal.exists():
            try:
                _,raw=capture.read({'path':str(journal),'sha256':native._hash(journal),'size':journal.stat().st_size},journal.parent)
                obj=c.strict(raw)
                if obj.get('request')==request:witness={'raw_status':obj.get('status'),'raw_profiles':obj.get('profiles',[]),'raw_error':obj.get('error')}
                capture.finish()
            except (ValueError,OSError,KeyError,TypeError):witness={'status':'unavailable_or_ending_custody_incomplete; raw original retained'}
        result['failure_population']={'request':request,
            'profiles':[{'id':role+'_'+str(i),'role':role,'point':point,'status':'unresolved','reason':'native_delivery_or_ending_custody_failed'} for role in ('free','null') for i,point in enumerate(request['starts'][role])],
            'raw_journal':witness,'scientific_reuse_authorized':False}
    else:
        inference=result['inference'];c.require(inference['kind']==d.KIND and inference['passed'],'complete paired diagnostic required')
        result['diagnostic']=inference['delivery']['diagnostic']
    stream.write_new(out/'asimov-sensitivity-result.json',result)
    return result


def write_report(result,out):
    from ravel.physics import root_stream as stream
    pin=stream.write_new(Path(out)/'asimov-sensitivity-report.json',result)
    return [{'stem':'asimov-sensitivity-report','files':['asimov-sensitivity-report.json'],'normalization':'Same full source Asimov experiment and auxiliary expectations; local expected proxy only','intended_commitments':[pin]}]
