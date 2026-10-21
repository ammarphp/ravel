"""Current same-campaign provenance for an ordinary research delivery.

This is an observation of existing authority. It grants no dispatch, review,
scientific acceptance or whole-parent completion and never repairs records.
"""
from pathlib import Path

from . import research_cycle as cycle, research_protocol as protocol
from . import research_coordinator_decisions as decisions
from . import physics_review, science, final_results_review, rdj_loop
from . import research_evaluation as evaluation

ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration)


def _nested_decisions(value, base):
    """A shaped nested receipt must also be the issuer's actual current authority."""
    found = []
    if isinstance(value, list):
        for row in value:
            found.extend(_nested_decisions(row, base))
    elif isinstance(value, dict):
        if 'rdj_receipt' in value:
            pin = value['rdj_receipt']
            receipt = protocol._method_json(pin, base)
            path = Path(pin['path'])
            if not path.is_absolute(): path = Path(base) / path
            if path.parent.name != 'receipts' or path.parent.parent.name != 'rdj':
                raise ValueError('nested decision is not an original issuer receipt')
            issuer = path.parent.parent.parent
            case = protocol._method_json(receipt['case'], issuer)
            point = case['decision_point']
            action = {'kind': point['action_kind'], 'digest': point['action']['digest'],
                      'pins': point['action']['pins'], 'floor': receipt['class']}
            actual = rdj_loop.authorizing_receipt(issuer, 'research_choice', action)
            if (actual is None or actual['receipt'] != receipt
                    or actual['receipt_sha256'] != pin['sha256']):
                raise ValueError('nested decision lacks matching current issuer custody')
            found.append({'issuer': str(issuer), 'receipt': pin, 'class': receipt['class']})
        for key, row in value.items():
            if key != 'rdj_receipt':
                found.extend(_nested_decisions(row, base))
    return found


def _ci2(state, experiment):
    """Verify the exact accepted CI2, including an authenticated CI3 successor."""
    cycle._current_evidence(state, experiment, accepted=False)
    saved = cycle._read(experiment['adjudication']['snapshot'], state['base_dir'])
    errors = physics_review.validate_snapshot(saved)
    if errors:
        raise ValueError('; '.join(errors))
    reg, events = physics_review._read(physics_review._root(experiment['rundir']))
    if (saved['registration'] != reg or saved['events'] != events[:len(saved['events'])]
            or physics_review._view(reg, saved['events'])['state'] != 'accepted'):
        raise ValueError('ordinary CI2 is not the exact accepted predecessor in current custody')
    errors = physics_review.gate_errors(experiment['rundir'], 'reuse')
    if errors:
        raise ValueError('; '.join(errors))
    return saved


def _dispatch_read(root, state, experiment):
    """Observe the original spent read and its current proposal/RDJ custody."""
    reads = [event['read'] for event in state['events']
             if event['kind'] in {'research_adaptive_read', 'research_confirm_read'}
             and event['read'].get('experiment_id') == experiment['id']]
    metadata = evaluation.declaration(state, experiment)
    bound = protocol._bound(state)
    exempt = (metadata is None or bound and not experiment.get('evaluation')
              and not any(cell['exposure'] == 'withheld_confirmation' for cell in bound[0]['cells']))
    if exempt:
        if reads:
            raise ValueError('unexpected dispatch read outside the original evaluation contract')
        return {'status': 'not_required_by_original_contract'}
    if len(reads) != 1:
        raise ValueError('ordinary experiment lacks its unique original dispatch exposure')
    read = reads[0]
    exposure = {'candidate': metadata['candidate'], **protocol._exposure_identity(metadata),
        'purpose': metadata['purpose'],
        'populations': evaluation.dispatch_populations(metadata, experiment['input_pins'], state['base_dir'])}
    if {pin['sha256'] for pin in metadata['population_pins']} - {
            pin['sha256'] for pin in experiment['input_pins']}:
        raise ValueError('dispatch population is outside the original ordinary inputs')
    selection, _ = protocol._selection_state(state)
    selected = selection['sha256'] if metadata['purpose'] == 'confirm' and selection is not None else None
    if metadata['purpose'] == 'confirm' and selected is None:
        raise ValueError('original confirmation lacks its current committed selection')
    document = evaluation.dispatch_proposal_document(state, experiment, exposure, selection_sha256=selected)
    expected_path = cycle._ordinary(Path(root)/'inputs/research-dispatch'/(
        experiment['id']+'-'+protocol.ce.digest(document)+'.json'))
    pins = read.get('pins')
    if (not isinstance(pins, list) or len(pins) != 1 or pins[0].get('path') != str(expected_path)
            or protocol._method_json(pins[0], root) != document):
        raise ValueError('original dispatch proposal is missing, stale or from another study')
    action = {**exposure, 'kind': 'screening_choice', 'digest': pins[0]['sha256'],
        'pins': pins, 'summary': 'Review the exact prospective study exposure: '+experiment['id']}
    if (any(read.get(key) != value for key, value in action.items())
            or read.get('selection_sha256') != selected):
        raise ValueError('dispatch exposure differs from its immutable prospective action')
    if metadata['purpose'] == 'confirm':
        from ravel.physics.ml_exposure import verify_research_read
        verify_research_read(read)
    authorization = rdj_loop.authorizing_receipt(root, 'research_choice', action)
    if authorization is None:
        raise ValueError('original dispatch lacks current registered RDJ authority')
    return {'status': 'observed', 'proposal': pins[0],
        'decision_receipt_sha256': authorization['receipt_sha256'],
        'decision_case': authorization['receipt']['case']}


def observe(rundir, artifacts, admissibility):
    """Recompute all original stages and ordinary children of this campaign."""
    rd = Path(rundir).resolve()
    result = {'status': 'unknown', 'campaign': None, 'stages': [], 'experiments': [],
              'final_checkpoint': None, 'complete': False, 'errors': [],
              'scientific_acceptance': 'not_assessed', 'parent_task_accepted': False}
    if not (rd / cycle.CHILD_CONTRACT_ORIGIN).exists():
        result['errors'].append('no bound research campaign origin')
        return result
    try:
        cycle.verify_experiment_contract(rd)
        origin = cycle.state_io.read_json(rd / cycle.CHILD_CONTRACT_ORIGIN)
        root, state = cycle._load(origin['root'])
        result['campaign'] = str(root)
        methodology = protocol.methodology_status(root)
        if not methodology['complete']:
            raise ValueError('original research methodology has incomplete stages')
        from . import review_points
        facts = review_points._facts(root)
        if facts['agent_layer_epoch'] != 2:
            raise ValueError('research decision authority requires source epoch-two custody')
        for row in methodology['record']['stages']:
            if row['status'] == 'not_applicable' and row.get('applicability') == 'computed':
                if not protocol.stage_inapplicable(row['id'], root):
                    raise ValueError('computed stage applicability changed')
                result['stages'].append({'stage': row['id'], 'status': 'computed_not_applicable', 'roles': []})
                continue
            if row['status'] not in {'done', 'not_applicable'}:
                raise ValueError('required dispatched stage is incomplete: ' + row['id'])
            models, roles, receipts = {}, [], {}
            for role in row['roles']:
                receipt = decisions.bound_stage_receipt(root, role, stage_id=row['id'], state=state)
                models[role] = receipt['transport'].get('observed_model')
                receipts[role] = receipt
                roles.append({'role': role, 'receipt': row['worker_receipts'][role],
                              'observed_model': models[role]})
            families = decisions.stage_family_check(root, row['id'], models, receipts=receipts)
            action = protocol.stage_action(row['id'], row['artifact'])
            errors = protocol.decision_errors(root, action)
            if errors:
                raise ValueError('; '.join(e.code for e in errors))
            authorization = rdj_loop.authorizing_receipt(root, 'research_choice', action)
            if authorization is None:
                raise ValueError('stage has no current registered decision authorization')
            artifact = protocol._method_json(row['artifact'], root)
            if row['id'] == 'ideas':
                protocol.verify_idea_dispatches(state, artifact, base_dir=root)
            nested = _nested_decisions(artifact, root)
            result['stages'].append({'stage': row['id'], 'status': 'observed',
                'declared_status': row['status'], 'roles': roles,
                'families': families, 'decision_receipt_sha256': authorization['receipt_sha256'],
                'nested_decisions': nested})
        if not state['experiments']:
            raise ValueError('research has no ordinary experiment population')
        for experiment in state['experiments']:
            if (experiment.get('rundir') is None or experiment.get('adjudication') is None
                    or experiment['observation'] is None):
                raise ValueError('original ordinary experiment remains incomplete: ' + experiment['id'])
            child = Path(experiment['rundir'])
            cycle.verify_experiment_contract(child)
            saved = _ci2(state, experiment)
            dispatch = _dispatch_read(root, state, experiment)
            from .architecture_receipt import scientific_admissibility
            pin = experiment['observation']['result']
            if pin is None:
                raise ValueError('ordinary result is unresolved: ' + experiment['id'])
            governed = scientific_admissibility(child, [{'path': pin['path'], 'sha256': pin['sha256'], 'kind': 'number'}])
            if not governed['governed']:
                raise ValueError('ordinary result lacks current approved governed execution: ' + experiment['id'])
            result['experiments'].append({'experiment': experiment['id'], 'run': str(child),
                'approval_inputs': science.approval_input_paths(child), 'result': pin,
                'ci2_cycle_id': physics_review._view(saved['registration'], saved['events'])['cycle']['cycle_id'],
                'dispatch': dispatch,
                'execution': experiment['observation']['receipt']})
        delivered = next(e for e in state['experiments'] if e['id'] == origin['experiment_id'])
        if Path(delivered['rundir']).resolve() != rd:
            raise ValueError('delivery belongs to another campaign child')
        pin = delivered['observation']['result']
        if not admissibility['governed'] or not admissibility['artifacts']:
            raise ValueError('delivered numerical/figure population is not governed')
        if not any(r['sha256'] == pin['sha256'] and
                   (rd / r['path']).resolve() == Path(pin['path']).resolve()
                   for r in admissibility['artifacts']):
            raise ValueError('delivery does not contain this campaign child result')
        reg, events = physics_review._read(rd)
        final = physics_review._view(reg, events)['cycle'].get('final_results')
        if final is None:
            raise ValueError('current final CHECK-IN 3 is missing')
        result['final_checkpoint'] = final_results_review.gate(rd, final['manifest'])
        # Close the complete campaign read after the last review callback.
        if cycle._load(root)[1]['sha256'] != state['sha256']:
            raise ValueError('campaign changed during architecture observation')
        result.update(status='observed', complete=True)
    except ERRORS as exc:
        result['errors'].append(str(exc))
    return result
