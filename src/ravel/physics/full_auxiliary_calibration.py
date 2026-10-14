"""Ordinary study adapter for complete fixed-truth auxiliary calibration.

The existing native likelihood executor builds the original regional workspace
and owns the bounded native process. This adapter supplies no new optimizer,
scheduler, approval or retry route.
"""
from pathlib import Path
import hashlib
import json
from ravel.physics import native_likelihood as native


def validate(task):
    return native.validate(task)


def _configuration(task, base, *, _session=None):
    value = native._configuration(task, base, _session=_session)
    if 'calibration' not in value[0]:
        raise ValueError('full-auxiliary-calibration requires its explicit repeated-sampling contract')
    return value


def inputs(task, base, *, _session=None):
    from ravel.workflow.science import regular
    from ravel.physics import ma5_saf
    _configuration(task, base, _session=_session)
    return list(dict.fromkeys([*native.inputs(task, base, _session=_session), *[regular(Path(p), base, _session=_session) for p in (__file__, ma5_saf.__file__, ma5_saf.reader.__file__)]]))


def execution_seconds(task, base, *, _session=None):
    return _configuration(task, base, _session=_session)[0]['max_seconds']


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def _validation_execution_seconds(task, base, session):
    return execution_seconds(task, base, _session=session)


def context(task, base, *, _session=None):
    """Complete prospective sampling/fit population for an ordinary Graph tool."""
    from ravel.physics import regional_calibration as c, regional_expected as e
    from ravel.workflow import science
    if _session is None:
        with science._validation_scope(base) as session:
            return context(task, base, _session=session)
    cfg, _, _, _, _, _, _, _, response, response_binding, *_ = _configuration(task, base, _session=_session)
    inputs(task, base, _session=_session)
    request=cfg['calibration'];d=response['document'];n=len(request['truths'])*request['trials_per_truth']
    if response.get('kind')=='native-source-graph/v1':
        from ravel.physics import source_graph_calibration as graph_calibration
        return {**graph_calibration.prospective(request,response),'request':request,'bins':d['bins'],'parameters':d['parameters'],'auxiliary':d['auxiliary'],
                'template_statistics':d['template_statistics'],'profile_policy':e.PROFILE_POLICY,'native_wall_seconds':cfg['max_seconds'],
                'execution_authorized':False,'physics_validated':False,'toys_generated':0,'fits_performed':0,
                'scope':'Prospective complete native-model fixed-truth experiment; generating TOTAL means pending ordinary native admission'}
    result = {'kind':c.KIND,'request':request,'bins':d['bins'],'parameters':d['parameters'],'auxiliary':d['auxiliary'],
            'template_statistics':d['template_statistics'],'truth_means':(response_binding['calibration_reference_admission']['truth_means'] if c.has_dijet(d) else [{'truth_id':t['id'],'point':t['point'],'means':c.means(d,t['point'])} for t in request['truths']]),
            'scheduled_toys':n,'maximum_top_level_profile_requests':2*n,'profile_policy':e.PROFILE_POLICY,
            'native_wall_seconds':cfg['max_seconds'],'execution_authorized':False,'physics_validated':False,
            'toys_generated':0,'fits_performed':0,'coverage_qualified':False,
            'scope':'Prospective complete fixed-truth repeated-sampling contract; existing ordinary science plan/approval/run required'}
    if c.has_dijet(d):
        result['reference_admission']=response_binding['calibration_reference_admission']
    if c.shape_description(d) is not None:
        result['continuous_shapes']=c.shape_description(d)
    return result


def graph(task, base, task_pin):
    """Existing advisory Graph/Host context, followed by ordinary science.plan."""
    from ravel.workflow import science, agent_graph
    with science._validation_scope(base) as session:
        path=science.regular(task_pin['path'], base, _session=session)
        if set(task_pin)!= {'path','sha256'} or session.hash_file(path)!=task_pin['sha256'] or session.read_document(path)!=task:
            raise ValueError('graph must consume the exact declared calibration task bytes')
        dependencies=inputs(task,base,_session=session)
        pins=[{'id':'request','path':str(path),'sha256':session.hash_file(path)}]+[{'id':'source'+str(i),'path':str(p),'sha256':session.hash_file(p)} for i,p in enumerate(dependencies)]
    return agent_graph.validate({'schema_version':1,'graph_id':'full_auxiliary_calibration_context',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':60,'max_reworks':0},
        'nodes':[{'id':'context','kind':'tool','role':'designer','depends_on':[],'inputs':pins,'packet':None,
                  'action':'full-auxiliary-context','parameters':{'request_input':'request'},'max_attempts':1}]})


def run(task, base, out):
    from ravel.physics import regional_calibration as c
    cfg, *_ = _configuration(task, base)
    result=native.run(task, base, out)
    if result['status']=='failed':
        # A failed custody/transport boundary cannot certify provisional fit
        # rows. Preserve them and conservatively retain every scheduled slot.
        request=cfg['calibration']
        rows=[{'truth_id':t['id'],'ordinal':j,'status':'unresolved','reason':'native_attempt_failed_or_ending_custody_incomplete'} for t in request['truths'] for j in range(request['trials_per_truth'])]
        journal=Path(out)/'native-work/ravel_calibration_journal.json'
        witness=None
        if journal.exists() and not any(p.is_symlink() for p in (journal,*journal.parents)):
            # Capture and classify the SAME bounded bytes; failed source remains
            # a raw observation, never current scientific reuse authority.
            from ravel.physics.ma5_saf import Capture
            capture=Capture()
            try:
                _,raw=capture.read(str(journal),journal.parent)
                obj=json.loads(raw)
                if obj.get('request')==request:
                    witness={'path':str(journal),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'raw_slots':obj.get('rows',[]),'raw_status':obj.get('status'), 'reference_admission':obj.get('reference_admission')}
                capture.finish()
            except (ValueError,OSError,KeyError,TypeError):
                witness={'path':str(journal),'classification':'unavailable_or_not_authenticated; original retained'}
        result['calibration_failure_audit']={'request':request,'rows':rows,'raw_journal':witness,'summary':c.summarize(request,rows),'scientific_reuse_authorized':False}
        c._write(Path(out)/'calibration-failure-audit.json',result['calibration_failure_audit'])
    result['status_scope']='pointwise_full_auxiliary_calibration_delivery'
    return result
