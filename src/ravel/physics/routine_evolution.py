"""Prospective improvement from a successful incumbent, separate from repair.

An immutable round retains the original measured task and live review state.
The existing graph keeps its cumulative budget and the existing candidate worker
admits a fresh challenger. Missing or failed challenger evidence preserves the
incumbent. Metric comparison is advisory; fresh full-case review remains separate.
"""
from copy import deepcopy
import json
from pathlib import Path

from ravel import analysis_sources as sources
from ravel.workflow import agent_graph, execution, physics_review, science
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, read_json


def _pin(path):
    path = regular(path, Path.cwd())
    return {"path": str(path), "sha256": sources.digest(path)}


def _path_pin(pin, base):
    if type(pin) is not dict or set(pin) != {"path", "sha256"}:
        raise ValueError("exact improvement artifact pin required")
    path = regular(pin["path"], base)
    if sources.digest(path) != pin["sha256"]:
        raise ValueError("incumbent/round evidence changed")
    return path


def _read_pin(pin, base):
    path = _path_pin(pin, base)
    return path, read_json(path)


def _fresh(path):
    path = Path(path).absolute()
    if path.exists() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("immutable improvement round needs a fresh ordinary path")
    return path


def capture_incumbent(rundir, output_path, *, objective, metric, direction,
                      incumbent_score, max_output_tokens=12000):
    """Read-only capture of a successful supervised, reviewed construction.

    The supplied score has an explicit caller-declared meaning; this function
    does not invent a physics metric. A new held-out population stays outside
    proposer context and must be admitted by the challenger scientific study.
    """
    import math
    if any(type(x) is not str or not x.strip() or len(x) > 16000 for x in (objective, metric)):
        raise ValueError("explicit bounded scientific objective and metric required")
    if direction not in ("minimize", "maximize") or type(incumbent_score) not in (int, float):
        raise ValueError("explicit metric direction and finite measured score required")
    try:
        if not math.isfinite(incumbent_score): raise ValueError("finite measured score required")
    except OverflowError:
        raise ValueError("finite representable measured score required") from None
    if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000:
        raise ValueError("bounded model output cost reservation required")
    rd = Path(rundir).resolve(); out = rd / 'outputs/attempt-1'
    science.verify_plan(rd, approved=True)
    if execution.stage_errors(rd, 'science') or physics_review.gate_errors(rd, 'reuse'):
        raise ValueError("successful incumbent requires current supervised and scoped review custody")
    task, result, feedback, admission = [read_json(out / name) for name in
        ('candidate-task.json', 'result.json', 'construction-feedback.json', 'candidate-source-admission.json')]
    if (result != feedback or result.get('candidate_disposition') != 'verified_on_supplied_events' or
            result.get('status') != 'passed' or result.get('prior_reviews_carried') != [] or
            result.get('source_admission_id') != admission.get('source_admission_id') or
            result.get('candidate_id') != task.get('candidate')):
        raise ValueError("improvement requires an actual successful incumbent; failed-parent repair is separate")
    from . import routine_candidate
    config_path = regular(task['input'], rd)
    if (sources.digest(config_path) != result['construction_input_sha256'] or
            sources.digest(out/'candidate-task.json') != result['task_sha256']):
        raise ValueError("incumbent task/result/source association differs")
    # Existing validators check the retained source/event input population. The
    # original implementation receipt is preserved rather than relabelled as
    # execution by the new module's source epoch.
    input_paths = routine_candidate.inputs(task, config_path.parent)
    reg, events = physics_review._read(rd); view = physics_review._view(reg, events)
    protected = [rd/science.SPEC,rd/science.PLAN,rd/science.APPROVAL,out/'candidate-task.json',
        out/'result.json',out/'construction-feedback.json',out/'candidate-source-admission.json',
        out/'checkin2.json',out/'standalone-verifier.json',out/'upstream-comparison.json',
        *input_paths,*[regular(pin['path'],rd) for pin in view['cycle']['snapshots']]]
    protected += sorted((rd/'logs/physics_review/events').glob('*.json'))
    state = execution.load_execution(rd)['stages']['science']
    protected += [regular(state['attempt_record'],rd)]
    round_record = {'schema_version':1,'kind':'successful-incumbent-improvement',
        'rundir':str(rd),'incumbent_task':task,'incumbent_configuration':_pin(config_path),
        'incumbent_result':_pin(out/'result.json'),'incumbent_feedback':_pin(out/'construction-feedback.json'),
        'incumbent_admission':_pin(out/'candidate-source-admission.json'),
        'parent_result_sha256':sources.digest(out/'result.json'),
        'parent_feedback_sha256':sources.digest(out/'construction-feedback.json'),
        'source_scope':result['source_scope'],'source_case_population':result['population_review'],
        'review_state_at_capture':physics_review.status(rd),'cycle_id':view['cycle']['cycle_id'],
        'protected_inputs':[_pin(p) for p in dict.fromkeys(protected)],
        'objective':objective,'metric':{'name':metric,'direction':direction,'incumbent_score':incumbent_score},
        'model_cost_bound':{'max_additional_calls':2,'max_output_tokens_per_call':max_output_tokens,
            'native_attempts_approved':0},
        'evaluation_contract':{'fresh_held_out_required':True,'full_case_required':True,
            'expected_answers_withheld_from_proposer':True,'incumbent_retained_on_failed_challenger':True},
        'prior_reviews_carried':[],'fresh_source_admission_required':True,'fresh_scientific_plan_required':True,
        'execution_authorized':False,'physics_validated':False,
        'limitations':['Captured metric is caller-declared and must be independently checked.',
            'Prior scoped acceptance is history, not acceptance of the new candidate or a broader scope.']}
    path = _fresh(output_path); atomic_json(path,round_record)
    return _pin(path)


def validate_lineage(pin, base_dir):
    """Normal worker admission pins the complete incumbent round, not a label."""
    path, record = _read_pin(pin, base_dir)
    fields={'schema_version','kind','rundir','incumbent_task','incumbent_configuration',
        'incumbent_result','incumbent_feedback','incumbent_admission','parent_result_sha256',
        'parent_feedback_sha256','source_scope','source_case_population','review_state_at_capture',
        'cycle_id','protected_inputs','objective','metric','model_cost_bound','evaluation_contract',
        'prior_reviews_carried','fresh_source_admission_required','fresh_scientific_plan_required',
        'execution_authorized','physics_validated','limitations'}
    if (type(record) is not dict or set(record)!=fields or record['schema_version']!=1 or
            type(record['schema_version']) is not int or record['kind']!='successful-incumbent-improvement' or record['prior_reviews_carried'] or
            record['execution_authorized'] is not False or record['physics_validated'] is not False or
            record['fresh_source_admission_required'] is not True or record['fresh_scientific_plan_required'] is not True):
        raise ValueError('closed prospective successful-incumbent lineage required')
    paths=[path]
    if type(record['protected_inputs']) is not list or not 1<=len(record['protected_inputs'])<=4096:
        raise ValueError('bounded complete incumbent input population required')
    for fact in record['protected_inputs']:
        paths.append(_path_pin(fact,path.parent))
    cp,config=_read_pin(record['incumbent_configuration'],path.parent)
    rp,result=_read_pin(record['incumbent_result'],path.parent)
    fp,feedback=_read_pin(record['incumbent_feedback'],path.parent)
    ap,admission=_read_pin(record['incumbent_admission'],path.parent)
    if (result!=feedback or result.get('candidate_disposition')!='verified_on_supplied_events' or
            result.get('candidate_id')!=record['incumbent_task']['candidate'] or
            result.get('construction_input_sha256')!=sources.digest(cp) or
            result.get('source_admission_id')!=admission.get('source_admission_id') or
            sources.digest(rp)!=record['parent_result_sha256'] or sources.digest(fp)!=record['parent_feedback_sha256'] or
            result.get('source_scope')!=record['source_scope'] or result.get('population_review')!=record['source_case_population']):
        raise ValueError('successful incumbent source/result/scope changed')
    rd=Path(record['rundir'])
    science.verify_plan(rd,approved=True)
    if execution.stage_errors(rd,'science') or physics_review.gate_errors(rd,'reuse'):
        raise ValueError('incumbent original execution/review custody is no longer reusable')
    live=physics_review.status(rd)
    if live!=record['review_state_at_capture'] or live['cycle_id']!=record['cycle_id']:
        raise ValueError('incumbent scoped review state changed after round capture')
    contract=record['evaluation_contract']
    if contract!={'fresh_held_out_required':True,'full_case_required':True,
            'expected_answers_withheld_from_proposer':True,'incumbent_retained_on_failed_challenger':True}:
        raise ValueError('fresh evaluation and incumbent retention obligations required')
    return record,list(dict.fromkeys(paths+[cp,rp,fp,ap]))


def prepare_improvement_request(lineage_pin, graph_root, output_packet, *, model, reasoning_effort):
    """Revise the same graph after success, without a fabricated failure trigger."""
    lineage,_=validate_lineage(lineage_pin,Path.cwd())
    config=read_json(lineage['incumbent_configuration']['path'])
    construction=config.get('model_construction')
    if construction is None:
        raise ValueError('successful model-led incumbent source packet required')
    _,panel=_read_pin(construction['source_panel'],Path(lineage['incumbent_configuration']['path']).parent)
    _,receipt=_read_pin(construction['receipt'],Path(lineage['incumbent_configuration']['path']).parent)
    packet=deepcopy(panel)
    packet['kind']='successful-incumbent-improvement-request'
    packet['revision_type']='improve_successful_incumbent'
    packet['improvement_lineage']=deepcopy(lineage_pin)
    packet['improvement_objective']=lineage['objective']
    packet['previous_public_candidate']=receipt['result']['value']
    packet['observed_incumbent']={'result_sha256':lineage['parent_result_sha256'],
        'feedback_sha256':lineage['parent_feedback_sha256'],'source_scope':lineage['source_scope'],
        'candidate_disposition':'verified_on_supplied_events','metric':lineage['metric']}
    packet['actual_feedback']=None;packet['counterexample_events']=[]
    packet['withheld']=list(dict.fromkeys(packet['withheld']+['fresh held-out/full-case events and expected answers']))
    packet['prior_reviews_carried']=[]
    output=_fresh(output_packet);atomic_json(output,packet)
    state=agent_graph.status(graph_root)
    calls=state['usage']['calls']
    if (not state['complete'] or not 1<=calls<3 or state['budget']['max_calls']!=3 or
            state['budget']['max_reworks']!=2):
        raise ValueError('existing complete graph with remaining cumulative construction budget required')
    from .routine_candidate import construction_output_schema
    node={'id':'construct','kind':'model','role':'improver','depends_on':[],
        'inputs':[{'id':'construction-source',**_pin(output)}],'packet':None,'action':'external','max_attempts':1,
        'parameters':{'instructions':'Improve the successful incumbent for the explicit scientific objective. Preserve original source obligations and candidly declare unserved scope. This is a new challenger, not a failed-parent repair. Return structured public JSON; do not execute tools or infer withheld fresh evaluation answers.',
            'model':model,'reasoning_effort':reasoning_effort,
            'max_output_tokens':lineage['model_cost_bound']['max_output_tokens_per_call'],
            'output_schema':construction_output_schema(c['id'] for c in config['claims'])}}
    specification={'schema_version':1,'graph_id':state['graph_id'],'budget':state['budget'],'nodes':[node]}
    agent_graph.revise(graph_root,specification,reason='Prospective successful-incumbent scientific improvement; original outcome retained')
    return {**agent_graph.prepare_external(graph_root,'construct'),'lineage':deepcopy(lineage_pin),
        'prior_calls_retained':calls,'revision_type':'improve_successful_incumbent','model_executed':False}


def materialize_improvement_candidate(lineage_pin, graph_root, output_config, *, candidate_id, evaluation_task):
    """Fresh challenger plus normally admitted lineage; no repair edge or votes."""
    lineage,_=validate_lineage(lineage_pin,Path.cwd())
    from . import routine_candidate
    evaluation_path=regular(evaluation_task['input'],Path.cwd())
    evaluation=read_json(evaluation_path)
    previous=read_json(lineage['incumbent_configuration']['path'])
    if evaluation['source_capsule']!=previous['source_capsule'] or evaluation['claims']!=previous['claims']:
        raise ValueError('improvement needs the same requested source claims; a new scientific scope needs a separate task')
    state=agent_graph.status(graph_root)
    saved=agent_graph._result(Path(graph_root),state['nodes']['construct']['result'])
    panel=_read_pin({'path':saved['request']['input_artifacts'][0]['path'],
                     'sha256':saved['request']['input_artifacts'][0]['sha256']},evaluation_path.parent)[1]
    if panel.get('revision_type')!='improve_successful_incumbent' or panel.get('improvement_lineage')!=lineage_pin:
        raise ValueError('actual reply is not bound to this prospective improvement round')
    result=routine_candidate.materialize_agent_candidate(graph_root,source_task=evaluation_task,
        base_dir=evaluation_path.parent,
        output_config=output_config,candidate_id=candidate_id)
    config=read_json(output_config)
    panel=read_json(config['model_construction']['source_panel']['path'])
    if panel.get('revision_type')!='improve_successful_incumbent' or panel.get('improvement_lineage')!=lineage_pin:
        raise ValueError('actual reply is not bound to this prospective improvement round')
    config['improvement_lineage']=deepcopy(lineage_pin)
    atomic_json(output_config,config)
    # Rebuild the materialization receipt after attaching the admitted lineage.
    binding=result['model_binding'];binding['construction_input_sha256']=sources.digest(output_config)
    binding['improvement_lineage']=deepcopy(lineage_pin);binding['original_incumbent_retained']=True
    atomic_json(Path(output_config).with_suffix('.model-receipt.json'),binding)
    routine_candidate.inputs(result['task'],Path(output_config).parent)
    return result


def retain_or_compare(lineage_pin, *, challenger_disposition, challenger_score=None,
                      held_out_verified=False, full_case_verified=False):
    """Advisory selection requiring held-out and full-case declarations.

    The declarations and metric remain caller-supplied; separate supervised
    study custody and independent review must establish their truth.
    """
    import math
    if type(held_out_verified) is not bool or type(full_case_verified) is not bool:
        raise ValueError('explicit held-out and full-case completion declarations required')
    lineage,_=validate_lineage(lineage_pin,Path.cwd())
    if challenger_disposition not in ('not_observed','typed_compiler_refused','native_compiler_refused',
            'event_mismatch','verified_on_supplied_events'):
        raise ValueError('explicit challenger construction outcome required')
    favorable=False
    if (challenger_disposition=='verified_on_supplied_events' and
            held_out_verified and full_case_verified):
        try:
            if type(challenger_score) not in (int,float) or not math.isfinite(challenger_score):
                raise ValueError('finite challenger metric required')
        except OverflowError:
            raise ValueError('finite representable challenger metric required') from None
        own,parent=challenger_score,lineage['metric']['incumbent_score']
        favorable=own<parent if lineage['metric']['direction']=='minimize' else own>parent
    return {'kind':'advisory_successful_incumbent_comparison','incumbent_result':lineage['incumbent_result'],
        'challenger_disposition':challenger_disposition,'incumbent_retained':not favorable,
        'held_out_completion_declared':held_out_verified,'full_case_completion_declared':full_case_verified,
        'next_action':'request_fresh_full_case_review' if favorable else 'retain_incumbent_and_continue_declared_experiments',
        'scientific_acceptance':False,'execution_authorized':False,'physics_validated':False,
        'limitations':['Score, held-out and full-case completion are caller declarations, not independently authenticated evidence.',
            'This advisory comparison does not replace the original incumbent or carry its votes.']}
