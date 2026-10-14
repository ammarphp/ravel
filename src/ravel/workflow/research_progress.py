"""Deterministic incomplete research delivery, without new acceptance state."""
from copy import deepcopy
import json
from pathlib import Path
from . import candidate_experiments as ce, state_io


def _render_text(result):
    """Render scientific progress; complete operational records stay typed.

    The returned census is the mandatory companion to this narrative. It retains
    every call, receipt, source pin and event. Rendering those same records again
    as prose is not an additional observation or evidence-reading entitlement.
    """
    from . import research_outcome_metrics
    text = 'Research progress: '+result['question']+'\n\n'
    text += 'Final delivery and parent acceptance remain open.\n'
    report = result['accepted_scoped_facts']
    text += ('No accepted quantitative facts were selected.\n' if report is None else report['report_text']+'\n')
    # Every scientific row and whole original obligation remains explicit here.
    # Only redundant operational instrumentation is rendered by its established
    # summary; its complete source-bound population remains in the same result.
    scientific = {key: result[key] for key in (
        'research_state_sha256', 'question', 'scope', 'context_sha256',
        'requested_quantity_census', 'required_experiments', 'all_experiments',
        'hypotheses', 'premises', 'staged_protocol', 'parent_task',
        'parent_completion_view')}
    text += '\nComplete scientific obligations and evidence census:\n'
    text += json.dumps(scientific, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)+'\n'
    text += '\n'+research_outcome_metrics.markdown(result['outcome_metrics'])
    text += ('\nThe complete authenticated operational provenance is retained in this same typed delivery at '
        '/outcome_metrics/input_pins, /outcome_metrics/resource_use, /outcome_metrics/interventions, '
        '/resource_ledger, /actual_graph_usage, /timing and /operational_boundaries. '
        'These complete histories and source identities are not discarded by rendering; '
        'an inventory or hash does not establish source-content reading, scientific acceptance or authority.\n')
    return text


def compose(root, *, base_dir=None, report_request=None, render_text=True):
    if type(render_text) is not bool:
        raise ValueError('explicit progress render_text boolean required')
    from . import research_cycle as cycle, scientific_report, task_completion
    _, state = cycle._load(root)
    base = Path(base_dir or state['base_dir'])
    view = cycle.status(root)
    completion = None
    if state.get('parent_task') is not None:
        if report_request is not None and 'task_completion' in report_request:
            completion_pin = report_request['task_completion']
        else:
            projection = {'schema_version': 1, 'contract': state['parent_task']['contract'],
                          'outcomes': [], 'parent_review': None, 'report': None}
            path = Path(root)/'synthesis-context'/(ce.digest(projection)+'-parent-progress.json')
            if not path.exists(): state_io.atomic_json(path, projection)
            completion_pin = cycle._pin(path)
        request = cycle._read(completion_pin, base)
        if request.get('contract') != state['parent_task']['contract']:
            raise ValueError('progress must retain the exact original parent contract')
        completion = task_completion.evaluate(completion_pin, base_dir=base)
    elif report_request is not None and 'task_completion' in report_request:
        raise ValueError('unbound parent completion cannot become research progress')
    report = None; fact_experiments = []
    if report_request is not None:
        supplied = cycle._read(report_request['context'], base)
        if supplied != state['context']: raise ValueError('exact current scientific context required')
        quantities = {q['id']: q for q in state['context']['requested_quantities']}
        outputs = {r['id']: r for r in state['context']['effective_outputs']}
        experiments = {e['id']: e for e in state['experiments']}
        from . import scientific_artifact
        delivered = scientific_artifact.compose(report_request['artifact_request'], base_dir=base)
        provenance = {r['field']: r for r in delivered['tool_provenance']}
        for fact in report_request['facts']:
            q = quantities.get(fact['quantity_id'])
            if q is None or q['artifact'] not in outputs:
                raise ValueError('progress facts must name a current requested quantity')
            output = outputs[q['artifact']]; identity = output['source_step']
            e = experiments.get(identity)
            if e is None or not cycle._applicability(state, e)['measurement']:
                raise ValueError('progress fact has no current accepted experiment')
            cycle._current_evidence(state, e, accepted=True)
            field = fact['selector']['pointer'][1:].split('/')[0].replace('~1','/').replace('~0','~')
            proof = provenance.get(field)
            if proof is None: raise ValueError('delivered tool field provenance absent')
            tool_id = proof['source']['tool_id']
            pin = report_request['artifact_request']['tools'][tool_id]
            path = Path(pin['path']); path = path if path.is_absolute() else base/path
            if (str(cycle._ordinary(path)) != str(cycle._ordinary(output['path']))
                    or pin['sha256'] != output['sha256']):
                raise ValueError('same-value foreign tool cannot replace accepted quantity source')
            fact_experiments.append(identity)
        recipe = deepcopy(report_request)
        if 'task_completion' in recipe: recipe['delivery'] = 'progress'
        report = scientific_report.compose(recipe, base_dir=base)
    by_id = {r['id']: r for r in view['experiments']}
    rows = []
    for e in state['experiments']:
        row = {'id': e['id'], 'question': e['question'], 'predictions': deepcopy(e['predictions']),
               'premise_bindings': deepcopy(e['premise_bindings']), 'observation': deepcopy(e['observation']),
               'adjudication': deepcopy(e['adjudication']), 'failed_intake': deepcopy(e.get('failed_intake')),
               'diagnostic_feedback': deepcopy(e.get('diagnostic_feedback')), **deepcopy(by_id[e['id']])}
        # Pre-existing stale acceptance remains historical. Fresh failed/unreviewed
        # observations also have custody checks, never acceptance by result label.
        if e['observation'] is not None and not row['current_scoped_reuse_clear']:
            try:
                cycle._current_evidence(state, e)
                row['observation_custody'] = 'current_authenticated_observation_only'
            except (ValueError, OSError) as exc:
                row['observation_custody'] = {'status': 'current_refusal', 'type': type(exc).__name__, 'message': str(exc)}
        rows.append(row)
    present = set(by_id)
    rows.extend({'id': identity, 'status': 'not_designed', 'observation': None, 'scientific_acceptance': False}
                for identity in state['contract']['required_experiments'] if identity not in present)
    measured = {r['id']: r for r in state['context']['measured_quantities']}
    quantity_rows = [{'request': deepcopy(q), 'measurement': deepcopy(measured.get(q['id'])),
                      'status': 'unmeasured' if q['id'] not in measured else
                          'passed_operational_quantity_check' if measured[q['id']]['passed'] else 'failed_quantity_check'}
                     for q in state['context']['requested_quantities']]
    result = {'kind': 'research_progress_synthesis', 'delivery': 'progress',
        'research_state_sha256': state['sha256'], 'question': state['contract']['question'], 'scope': state['contract']['scope'],
        'context_sha256': state['context']['context_sha256'], 'requested_quantity_census': quantity_rows,
        'required_experiments': deepcopy(state['contract']['required_experiments']), 'all_experiments': rows,
        'hypotheses': deepcopy(state['hypotheses']), 'premises': deepcopy(state['premises']),
        'staged_protocol': view['staged_protocol'], 'parent_task': deepcopy(state.get('parent_task')),
        'parent_completion_view': completion, 'resource_ledger': deepcopy(state['resource_ledger']),
        'actual_graph_usage': deepcopy(state['graphs']), 'timing': deepcopy(state['timing']),
        'operational_boundaries': deepcopy(state['operational_boundaries']), 'outcome_metrics': view['outcome_metrics'],
        'accepted_scoped_facts': report, 'final_delivery': False, 'parent_task_accepted': False,
        'execution_authorized': False, 'physics_validated': False, 'benefit_measured': False}
    # Machine consumers receive exactly one complete census under their existing
    # transport limits. The human route retains its original text limit, without
    # serializing complete operational histories twice or truncating science.
    if render_text:
        text = _render_text(result)
        if len(text.encode()) > scientific_report.MAX_TEXT_BYTES:
            raise ValueError('complete progress report exceeds existing text budget; no truncation')
        result['report_text'] = text
    if cycle.status(root) != view:
        raise ValueError('current evidence/review census changed during progress synthesis')
    if cycle._load(root)[1]['sha256'] != state['sha256']:
        raise ValueError('research state changed during progress synthesis')
    for identity in set(fact_experiments):
        cycle._current_evidence(state, next(e for e in state['experiments'] if e['id']==identity), accepted=True)
    if completion is not None and task_completion.evaluate(completion_pin, base_dir=base) != completion:
        raise ValueError('parent evidence changed during progress synthesis')
    return result
