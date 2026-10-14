"""Choose the next finite research operation from observed candidate outcomes.

Composes candidate_experiments and constructive_contrast. This is a controller
for immutable rounds, not another model, process runner or acceptance journal.
Development outcomes drive draft/debug/improve and component experiments;
held-out answers stay out of its generation context. Scientific source choices,
actual execution and final acceptance remain with the existing public lifecycle.
"""
from copy import deepcopy
import math
from pathlib import Path
import statistics
from . import candidate_experiments as ce, constructive_contrast as cc


MAX_ROUNDS = 16
MAX_INPUT_PINS = 126  # Ordinary agent graph has128 pins; reserve two request JSONs.


def _text(value):
    if type(value) is not str or not value.strip() or len(value)>8192:
        raise ValueError('bounded explicit research text required')


def validate(contract):
    ce.keys(contract,['schema_version','scope','question','metric','direction','policy',
        'num_seeds','max_debug_depth','component_experiments','proposal_transport',
        'budget','hypotheses','source_obligations'])
    if type(contract['schema_version']) is not int or contract['schema_version']!=1:
        raise ValueError('empirical-search/v1 required')
    for key in ('scope','question','metric'):_text(contract[key])
    if contract['direction'] not in ('minimize','maximize') or contract['policy'] not in ('linear','branch'):
        raise ValueError('explicit metric direction and search policy required')
    if type(contract['num_seeds']) is not int or not 1<=contract['num_seeds']<=4:
        raise ValueError('one to four declared seeds required')
    if type(contract['max_debug_depth']) is not int or not 0<=contract['max_debug_depth']<=4:
        raise ValueError('finite engineering depth required')
    if type(contract['component_experiments']) is not bool:
        raise ValueError('explicit component-experiment policy required')
    if contract['proposal_transport'] not in ('agent_host_external','source_tool'):
        raise ValueError('existing Host or source-tool proposal route required')
    budget=contract['budget']
    ce.keys(budget,['max_rounds','max_candidates','max_model_calls','max_reserved_output_tokens',
        'output_per_proposal','max_experiment_attempts'])
    maxima={'max_rounds':MAX_ROUNDS,'max_candidates':8,'max_model_calls':32,
        'max_reserved_output_tokens':512000,'output_per_proposal':16000,'max_experiment_attempts':128}
    for key,maximum in maxima.items():
        minimum=0 if key in ('max_model_calls','max_reserved_output_tokens') else 1
        if type(budget[key]) is not int or not minimum<=budget[key]<=maximum:
            raise ValueError('finite explicit cumulative search budget required')
    if contract['num_seeds']>budget['max_candidates']:
        raise ValueError('seed pool exceeds candidate ceiling')
    if type(contract['hypotheses']) is not list or not 0<=len(contract['hypotheses'])<=16:
        raise ValueError('bounded constructive hypothesis inventory required')
    ids=set()
    for hypothesis in contract['hypotheses']:
        ce.keys(hypothesis,['id','component','statement','discriminating_experiment','predictions'])
        ce.identity(hypothesis['id']);ce.identity(hypothesis['component'])
        if hypothesis['id'] in ids:raise ValueError('distinct hypotheses required')
        ids.add(hypothesis['id'])
        _text(hypothesis['statement']);_text(hypothesis['discriminating_experiment'])
        if type(hypothesis['predictions']) is not dict or not 2<=len(hypothesis['predictions'])<=8:
            raise ValueError('explicit rival predictions required')
        for rival,prediction in hypothesis['predictions'].items():
            ce.identity(rival);_text(prediction)
    if type(contract['source_obligations']) is not list or not 1<=len(contract['source_obligations'])<=64:
        raise ValueError('complete retained source obligations required')
    ids=set()
    for row in contract['source_obligations']:
        ce.keys(row,['id','description']);ce.identity(row['id']);_text(row['description'])
        if row['id'] in ids:raise ValueError('distinct source obligations required')
        ids.add(row['id'])
    return deepcopy(contract)


def _charges(ledger,contract,plan,base):
    if type(ledger) is not list or len(ledger)>160:
        raise ValueError('bounded cumulative model/experiment ledger required')
    ids=set();pairs=set();models=set();tokens=0
    candidates={r['id'] for r in plan['candidates']};cases={r['id'] for r in plan['cases']}
    for row in ledger:
        ce.keys(row,['id','kind','candidate_id','case_id','reserved_output_tokens','artifact'])
        ce.identity(row['id'])
        if row['id'] in ids or row['candidate_id'] not in candidates:
            raise ValueError('duplicate or foreign cumulative charge')
        ids.add(row['id']);ce.read_pin(row['artifact'],base)
        if type(row['reserved_output_tokens']) is not int:
            raise ValueError('integer reserved output charge required')
        if row['kind']=='model':
            if row['case_id'] is not None or not 1<=row['reserved_output_tokens']<=contract['budget']['output_per_proposal']:
                raise ValueError('exact bounded model reservation charge required')
            models.add(row['candidate_id']);tokens+=row['reserved_output_tokens']
        elif row['kind']=='experiment':
            pair=(row['candidate_id'],row['case_id'])
            if row['case_id'] not in cases or row['reserved_output_tokens']!=0 or pair in pairs:
                raise ValueError('one declared experiment charge per candidate/case required')
            pairs.add(pair)
        else:raise ValueError('model or experiment charge required')
    for row in plan['trials']:
        if row['result'] is not None and (row['candidate_id'],row['case_id']) not in pairs:
            raise ValueError('every observed trial needs a cumulative experiment charge')
    if contract['proposal_transport']=='agent_host_external' and not candidates<=models:
        raise ValueError('every actual Host candidate needs its retained model charge')
    usage={'model_calls':sum(r['kind']=='model' for r in ledger),
        'reserved_output_tokens':tokens,'experiment_attempts':len(pairs),'candidates':len(candidates)}
    limits={'model_calls':'max_model_calls','reserved_output_tokens':'max_reserved_output_tokens',
        'experiment_attempts':'max_experiment_attempts','candidates':'max_candidates'}
    if any(usage[k]>contract['budget'][v] for k,v in limits.items()):
        raise ValueError('cumulative search budget exhausted')
    return usage


def _development(summary,cases):
    keys=[r['id'] for r in cases if r['partition']=='development']
    rows=[summary['observations'][key] for key in keys]
    # A known full-case/source obligation failure cannot be hidden by a good
    # development score. Its status may guide repair; numerical answers stay out.
    known_failures=[key for key,row in summary['observations'].items() if row['status']=='failed']
    missing=[key for key in keys if summary['observations'][key]['status'] in ('not_observed','unresolved')]
    if not keys:raise ValueError('development population required for generation; held-out answers cannot tune')
    value=None
    if not known_failures and all(r['status']=='passed' for r in rows):
        try:value=statistics.fmean(r['score'] for r in rows)
        except (OverflowError,ValueError):raise ValueError('finite development metric aggregate required') from None
        if not math.isfinite(value):raise ValueError('finite development metric aggregate required')
    return {'score':value,'failed_cases':known_failures,'missing_cases':missing}


def _decision(contract,plan,intake,usage):
    summaries={r['candidate']['id']:r for r in intake['candidates']}
    dev={key:_development(value,plan['cases']) for key,value in summaries.items()}
    rows={r['id']:r for r in plan['candidates']}
    outcome=lambda key:dev[key]['score']
    ranked=[key for key in rows if rows[key]['kind']!='ablation' and outcome(key) is not None]
    reverse=contract['direction']=='maximize'
    ranked.sort(key=lambda key:outcome(key),reverse=reverse)
    incumbent=ranked[0] if ranked else None
    public=[{'candidate_id':key,'kind':rows[key]['kind'],'parent':rows[key]['parent'],
        'recipe_sha256':rows[key]['recipe_sha256'],'components':rows[key]['components'],
        **dev[key]} for key in rows]
    def result(kind,parent=None,component=None,reason=''):
        hypotheses=[deepcopy(h) for h in contract['hypotheses'] if h['component']==component]
        return {'kind':kind,'parent_candidate_id':parent,'component_id':component,'reason':reason,
            'parent_recipe_sha256':None if parent is None else rows[parent]['recipe_sha256'],
            'research_incumbent':incumbent,'hypotheses':hypotheses,'development_history':public,
            'source_obligations':deepcopy(contract['source_obligations']),
            'withheld':['held-out outputs','full-case output values','independent review answers'],
            'new_source_admission_required':True,'new_scientific_plan_required':True,
            'prior_reviews_carried':[],'execution_authorized':False,'scientific_acceptance':False}
    def finish(reason):
        if incumbent is not None:
            required=[r['id'] for r in plan['cases'] if r['partition'] in ('held_out','full_case')]
            missing=[key for key in required if summaries[incumbent]['observations'][key]['status'] in ('not_observed','unresolved')]
            if missing and usage['experiment_attempts']+len(missing)<=contract['budget']['max_experiment_attempts']:
                return result('request_validation',incumbent,
                    reason=reason+' Evaluate the selected existing source on both held-out and full-case populations; do not expose answers to the generation context.')
            if summaries[incumbent]['next_action']=='request_full_case_review':
                return result('request_full_case_review',incumbent,
                    reason=reason+' Complete paired evidence exists; request independent review, with no acceptance or old-vote inheritance.')
        return result('stop_budget',reason=reason+' Retain all alternatives and explicitly unserved validation obligations.')
    # Unknowns are constructive evidence requests, never fabricated bugs. A
    # completed unresolved measurement stays immutable: a refined precision
    # experiment needs a new prospective contract, not an overwritten trial.
    pending=[key for key in rows if any(summaries[key]['observations'][case]['status']=='not_observed'
        for case in dev[key]['missing_cases'])]
    if pending:
        missing=sum(summaries[pending[0]]['observations'][case]['status']=='not_observed'
            for case in dev[pending[0]]['missing_cases'])
        if usage['experiment_attempts']+missing>contract['budget']['max_experiment_attempts']:
            return finish('Remaining development evidence does not fit the cumulative attempt ceiling.')
        return result('evaluate_existing',pending[0],reason='Complete declared development evidence before generating a successor.')
    unresolved=[key for key in rows if dev[key]['missing_cases']]
    if unresolved and incumbent is None:
        return result('request_precision_plan',unresolved[0],
            reason='No successful measured branch yet. Preserve the unresolved result and prepare a new bounded discriminating/precision experiment; do not overwrite it or invent an engineering failure.')
    if usage['candidates']>=contract['budget']['max_candidates']:
        return finish('Candidate generation ceiling reached.')
    if (contract['proposal_transport']=='agent_host_external' and
            (usage['model_calls']>=contract['budget']['max_model_calls'] or
             usage['reserved_output_tokens']+contract['budget']['output_per_proposal']>contract['budget']['max_reserved_output_tokens'])):
        return finish('No additional Host proposal fits the cumulative reserved call/output ceiling.')
    if usage['experiment_attempts']>=contract['budget']['max_experiment_attempts']:
        return finish('No new experiment attempt is available.')
    seeds=[r for r in rows.values() if r['kind']=='seed']
    if len(seeds)<contract['num_seeds']:
        return result('draft_seed',reason='Complete the declared initial competing seed pool.')
    def depth(key):
        count=0
        while rows[key]['parent'] is not None and dev[rows[key]['parent']]['failed_cases']:
            count+=1;key=rows[key]['parent']
        return count
    latest=plan['candidates'][-1]['id']
    failed_leaves=[key for key in rows if dev[key]['failed_cases'] and
        not any(row['parent']==key for row in rows.values()) and depth(key)<contract['max_debug_depth']]
    if contract['policy']=='linear':
        if dev[latest]['failed_cases']:
            if latest in failed_leaves:return result('debug',latest,reason='Linear policy revises its latest failed leaf.')
            return result('draft_seed',reason='Latest branch exhausted engineering depth; retain it and draft a fresh alternative.')
        return result('improve',latest,reason='Linear policy improves its latest measured candidate.')
    if incumbent is None:
        if failed_leaves:return result('debug',failed_leaves[0],reason='No successful development candidate; debug an eligible actual failure.')
        return result('draft_seed',reason='No successful or eligible debug branch; generate a new competing hypothesis.')
    components=rows[incumbent]['components']
    contributions={}
    measured_ablations=[]
    for key,row in rows.items():
        if row['kind']!='ablation' or row['parent']!=incumbent:continue
        removed=set(components)-set(row['components'])
        if len(removed)!=1:continue  # Compound intervention is not single-component attribution.
        component=next(iter(removed));measured_ablations.append(component)
        if dev[key]['score'] is not None:
            loss=outcome(incumbent)-outcome(key) if reverse else outcome(key)-outcome(incumbent)
            if not math.isfinite(loss):raise ValueError('finite paired component contribution required')
            # Repeated source contrasts remain separate observations. Use the
            # largest finite matched loss, never the last admitted row. This
            # deliberately conservative targeting heuristic is not an effect
            # estimator; unresolved repeats cannot erase measured contrasts.
            contributions[component]=max(contributions.get(component,loss),loss)
    if contract['component_experiments']:
        unseen=[component for component in components if component not in measured_ablations]
        if unseen:
            return result('ablate_component',incumbent,unseen[0],
                'Measure one unchanged-budget component contrast on the successful branch before choosing a replacement.')
        if contributions:
            # Equal maxima follow the retained incumbent component order.
            target=max((component for component in components if component in contributions),
                key=contributions.get)
            return result('improve_component',incumbent,target,
                'Measured same-development ablations select the maximum finite observed loss per removed component; repeated measurements remain separate, and equal maxima follow retained component order. This is a targeting heuristic, not an effect estimate or causal proof.')
    return result('improve',incumbent,reason='Improve the best successful measured development branch while retaining failed alternatives.')


def _previous(pin,base,contract,*,depth=0):
    if pin is None:return None
    if depth>=MAX_ROUNDS:raise ValueError('bounded immutable round ancestry required')
    prior=ce.read_pin(pin,base)
    ce.keys(prior,['schema_version','kind','round','contract','plan','previous','ledger','usage','intake','decision',
        'declared_budget_checked','execution_identity_checked','scientific_acceptance'])
    validate(prior['contract'])
    if (type(prior['schema_version']) is not int or prior['schema_version']!=1
            or type(prior['round']) is not int or not 1<=prior['round']<=MAX_ROUNDS
            or prior['declared_budget_checked'] is not True
            or prior['execution_identity_checked'] is not False or prior['scientific_acceptance'] is not False
            or prior['kind']!='empirical_search_round' or prior['contract']!=contract):
        raise ValueError('same immutable scientific/search contract required')
    ancestor=_previous(prior['previous'],base,contract,depth=depth+1)
    expected=advance(contract,prior['plan'],prior['ledger'],base_dir=base,previous=prior['previous'],_ancestor=ancestor)
    if prior!=expected:raise ValueError('round state differs from pinned empirical history')
    return prior


def advance(contract,plan_pin,ledger,*,base_dir,previous=None,_ancestor=None):
    """Make the next immutable round from real result/check artifacts.

    Exact bytes and declared resource charges are checked. Caller authentication
    of supervisor/review identities remains outside this controller. No model,
    scientific operation or next attempt is dispatched here.
    """
    contract=validate(contract);base=Path(base_dir).resolve(strict=True)
    plan=ce.read_pin(plan_pin,base)
    if any(plan[k]!=contract[k] for k in ('scope','metric','direction')):
        raise ValueError('same scientific score/scope required across rounds')
    intake=ce.summarize(plan,base_dir=base)
    if not {'development','held_out','full_case'}<={row['partition'] for row in plan['cases']}:
        raise ValueError('declared development, held-out and full-case populations required')
    prior=_ancestor if _ancestor is not None else _previous(previous,base,contract)
    round_number=1 if prior is None else prior['round']+1
    if round_number>contract['budget']['max_rounds']:
        raise ValueError('immutable search round ceiling exhausted')
    if prior is not None:
        old=ce.read_pin(prior['plan'],base)
        if plan['cases']!=old['cases'] or ledger[:len(prior['ledger'])]!=prior['ledger']:
            raise ValueError('case denominator or cumulative charge history changed')
        if plan['candidates'][:len(old['candidates'])]!=old['candidates']:
            raise ValueError('original candidate/source lineage changed')
        trials={(r['candidate_id'],r['case_id']):r for r in plan['trials']}
        if any(trials.get((r['candidate_id'],r['case_id']))!=r for r in old['trials'] if r['result'] is not None):
            raise ValueError('observed outcome was removed or overwritten')
    usage=_charges(ledger,contract,plan,base)
    return {'schema_version':1,'kind':'empirical_search_round','round':round_number,
        'contract':contract,'plan':deepcopy(plan_pin),'previous':deepcopy(previous),
        'ledger':deepcopy(ledger),'usage':usage,'intake':intake,
        'decision':_decision(contract,plan,intake,usage),'declared_budget_checked':True,
        'execution_identity_checked':False,'scientific_acceptance':False}


def prepare_component_followup(round_record,request,*,base_dir):
    """Produce a literal controlled source from the measured component choice.

    The caller supplies the competing source proposal/predictions. The selected
    source must match the actual chosen parent recipe and component. This emits
    executable source for separate evaluation without promoting the ablation.
    """
    validate(round_record['contract'])
    refreshed=advance(round_record['contract'],round_record['plan'],round_record['ledger'],
        base_dir=base_dir,previous=round_record['previous'])
    if refreshed!=round_record:raise ValueError('fresh exact empirical round required')
    decision=round_record['decision']
    if decision['kind'] not in ('ablate_component','improve_component'):
        raise ValueError('measured component selection required')
    if (request['component']['id']!=decision['component_id'] or
            request['baseline']['sha256']!=decision['parent_recipe_sha256']):
        raise ValueError('controlled edit must target the measured parent source and component')
    prep=cc.prepare(request,base_dir)
    return {'kind':'empirical_component_followup','round_sha256':ce.digest(round_record),
        'selected_action':deepcopy(decision),'preparation':prep,
        'retained_incumbent_recipe_sha256':decision['parent_recipe_sha256'],
        'fresh_source_and_evaluation_required':True,'old_votes_carried':[],
        'execution_authorized':False,'scientific_acceptance':False}


def advance_request(request, *, base_dir):
    """Ordinary Host-facing request; all previous results remain explicit inputs."""
    ce.keys(request,['schema_version','contract','plan','ledger','previous'])
    if type(request['schema_version']) is not int or request['schema_version']!=1:
        raise ValueError('empirical-search request/v1 required')
    return advance(request['contract'],request['plan'],request['ledger'],
        base_dir=base_dir,previous=request['previous'])


def generation_view(round_record):
    """Context for a subsequent proposer, without held-out numerical answers.

    The internal round includes complete checker reports for accountability. A
    model must receive this projection instead of those reports, not the raw
    round. This function establishes a data projection, not an OS sandbox or a
    claim that the proposer has never seen the cases elsewhere.
    """
    return {'kind':'empirical_next_proposal','round_sha256':ce.digest(round_record),
        'round':round_record['round'],'usage':deepcopy(round_record['usage']),
        'decision':deepcopy(round_record['decision']),
        'budget':deepcopy(round_record['contract']['budget']),
        'question':round_record['contract']['question'],
        'metric':round_record['contract']['metric'],'direction':round_record['contract']['direction'],
        'scientific_acceptance':False,'execution_authorized':False,
        'context_projection_checked':True,'independent_context_or_os_blinding_checked':False}


def input_pins(request, *, base_dir):
    """Complete finite nested JSON inventory for normal graph input admission.

    Checkers, results, charge receipts and every immutable predecessor must be
    graph inputs. Returning paths alone is insufficient: the Host compares these
    exact pins with its explicit node inventory before invoking the operation.
    Candidate source checks and authentic execution/review remain outside this
    report intake; component source tools additionally bind actual source files.
    """
    ce.keys(request,['schema_version','contract','plan','ledger','previous'])
    if type(request['schema_version']) is not int or request['schema_version']!=1:
        raise ValueError('empirical-search request/v1 required')
    validate(request['contract'])
    base=Path(base_dir).resolve(strict=True);found={};total=0
    def add(pin):
        nonlocal total
        value=ce.read_pin(pin,base)
        previous=found.get(pin['path'])
        if previous is not None and previous!=pin:
            raise ValueError('one exact identity per nested artifact path required')
        if previous is None:
            found[pin['path']]=deepcopy(pin);total+=pin['size']
            if total>ce.MAX_TOTAL_BYTES or len(found)>MAX_INPUT_PINS:
                raise ValueError('empirical input inventory exceeds the ordinary graph capacity; narrow the prospective population instead of dropping evidence')
        return value
    def visit(plan_pin,ledger,prior,depth):
        if depth>=MAX_ROUNDS:raise ValueError('bounded immutable round ancestry required')
        plan=add(plan_pin)
        if type(ledger) is not list or len(ledger)>160:
            raise ValueError('bounded cumulative charge inventory required')
        for trial in plan['trials']:
            for key in ('result','check'):
                if trial[key] is not None:add(trial[key])
        for charge in ledger:add(charge['artifact'])
        if prior is not None:
            ancestor=add(prior)
            if ancestor['contract']!=request['contract']:
                raise ValueError('same scientific/search contract required')
            visit(ancestor['plan'],ancestor['ledger'],ancestor['previous'],depth+1)
    visit(request['plan'],request['ledger'],request['previous'],0)
    return list(found.values())
