"""Ordinary preparation of whole-parent review evidence, never parent acceptance.

The readiness request is evaluated by the existing complete task consumer. The
prospective final request can add only its exact future parent-review link. An
ordinary worker binds both requests and every currently consumed source before
independent roles inspect them. No journal, score, scientific vote or CI3 receipt
is manufactured by this producer.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from ravel.workflow import task_completion as tc
from ravel.workflow import candidate_experiments as ce

SCOPE='whole_original_parent_review_context'


def validate(task):
    ce.keys(task,('schema_version','ready_request','final_request','parent_review_root','completion_base'))
    if type(task['schema_version']) is not int or task['schema_version']!=1:
        raise ValueError('task-completion-context/v1 required')
    for key in ('ready_request','final_request'):tc._pin_shape(task[key])
    path=Path(task['parent_review_root'])
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('canonical exact prospective parent-review root required')
    source_base=Path(task['completion_base'])
    if (not source_base.is_absolute() or not source_base.is_dir()
            or any(p.is_symlink() for p in (source_base,*source_base.parents))):
        raise ValueError('exact existing ordinary completion input base required')
    return deepcopy(task)


def _load(task,base):
    task=validate(task);base=Path(task['completion_base']);observed=tc._Inputs(base)
    try:
        ready=observed.document(task['ready_request']);final=observed.document(task['final_request'])
        ce.keys(ready,('schema_version','contract','outcomes','parent_review','report'))
        if ready['parent_review'] is not None or ready['report'] is None:
            raise ValueError('ready request must remain unaccepted and include its exact base report recipe')
        expected={**deepcopy(ready),'parent_review':{'rundir':task['parent_review_root'],
            'claim_scope':tc.PARENT_ACCEPTANCE_SCOPE}}
        if final!=expected or task['ready_request']==task['final_request']:
            raise ValueError('prospective request may add only its exact original-scope parent-review link')
        # Consumes the authenticated readiness buffer through the existing
        # complete current source/review consumer in this same ending session.
        result=tc._evaluate(task['ready_request'],observed,_finish=False)
        if (not result['ready_for_parent_review'] or result['parent_task_accepted']
                or result['unmet_obligation_ids'] or result['unobserved_assignment_ids']):
            raise ValueError('the complete original task is not ready for independent parent review')
        for outcome in final['outcomes']:
            child=Path(outcome['rundir']);child=child if child.is_absolute() else Path(base)/child
            if child.absolute()==Path(task['parent_review_root']):
                raise ValueError('a contributor child review cannot substitute for the separate parent review')
        # The final record is captured independently; readiness never substitutes
        # a modified request when the later public acceptance consumer runs.
        observed.file(task['final_request'])
        # The public caller finishes once, after its complete scope or
        # emitted output is captured in this same current session.
        return task,ready,final,result,observed
    except BaseException:
        observed.close();raise


def inputs(task,base):
    _,_,_,_,observed=_load(task,base)
    try:
        observed.finish();return [Path(p) for p in observed.pins]
    finally:observed.close()


def validate_scope(spec):
    validate(spec['task'])
    if spec.get('schema_version')!=2 or spec.get('mode')!='task-completion-context' or spec.get('max_attempts')!=1:
        raise ValueError('prospective whole-parent context is a one-attempt ordinary reviewed study')
    root=Path(spec['task']['parent_review_root'])
    # All context task pins are absolute to preserve their producer base across
    # ordinary plan copies and worker dispatch. No current-working-dir guessing.
    for key in ('ready_request','final_request'):
        if not Path(spec['task'][key]['path']).is_absolute():raise ValueError('absolute complete request binding required')
    task,ready,_,_,observed=_load(spec['task'],root.parent)
    try:
        if spec.get('goal_binding',{}).get('contract')!=ready['contract']:
            raise ValueError('context study must bind its exact whole original parent')
        projection=tc.binding_projection(spec['goal_binding'],base_dir=task['completion_base'])
        complete=[{'obligation_id':r['id'],'criteria':r['criteria']} for r in projection['original_obligations']]
        if projection['assignment']['coverage']!=complete:
            raise ValueError('context study cannot narrow the original whole-parent assignment')
        if tc.PARENT_ACCEPTANCE_SCOPE not in spec['review_policy']['policy']['claim_scopes']:
            raise ValueError('registered independent whole-original-task review scope required')
        observed.finish()
    finally:observed.close()


def run(task,base,output):
    task,ready,final,result,observed=_load(task,base)
    try:
        # Ordinary science preserves the specification's producer base for
        # task inputs. The worker output belongs to its separate review root.
        # Do not conflate those two locations or require relocating source pins.
        out=Path(output).absolute()
        expected=Path(task['parent_review_root'])/'outputs/attempt-1/task-completion-context'
        if out!=expected:
            raise ValueError('ordinary context output must belong to the exact prospective parent-review attempt')
        if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
            raise ValueError('fresh ordinary whole-parent context destination required')
        out.mkdir(parents=True)
        value={'schema_version':1,'kind':'task-completion-review-context','status':'passed','scope':SCOPE,
            'ready_request':task['ready_request'],'final_request':task['final_request'],
            'parent_review_root':task['parent_review_root'],'completion_base':task['completion_base'],'original_request':result['original_request'],
            'original_prompt_sha256':result['original_prompt_sha256'],'obligation_census':result['obligation_census'],
            'report_recipe_sha256':result['report_recipe_sha256'],'input_pins':list(observed.pins.values()),
            'ready_for_parent_review':True,'parent_task_accepted':False,'original_task_complete':False,
            'physics_validated':False,'benchmark_qualified':False,
            'limitations':['Readiness and exact source custody only; independent whole-parent review and CI3 remain required.',
                'No numerical/scientific validation, semantic entailment, human review or acceptance is inferred.']}
        raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        p=out/'task-completion-context.json';expected={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
        with p.open('xb') as stream:stream.write(raw)
        observed.file(expected);observed.finish()
        return deepcopy(value)
    finally:observed.close()
