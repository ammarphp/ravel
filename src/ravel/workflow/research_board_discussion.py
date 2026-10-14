"""One revealed-board meeting or matched isolated revision through ordinary Graphs.

This composition owns no journal, scheduler or scientific authority. The existing
cycle reserves every turn before dispatch; Graph/Host retain calls and failures.
Contradiction/missing-premise edges are attributed judgments, never proof or votes.

A meeting on a board season (``research_board``) binds the season: its custody-verified
journal head, its write-once reveal record and its sealing. An unsealed season carries
no independence label into the preparation or the report.
"""
from copy import deepcopy
from . import provider_transport
import base64
import hashlib
import json
from pathlib import Path

from . import agent_graph, hypothesis_board as board, research_board as seasons, research_cycle as cycle
from . import research_followup as follow, state_io

MAX_BYTES = follow.MAX_BYTES
ARMS = ('discussion', 'isolated')


def _write(path, value):
    path = cycle._ordinary(path)
    if path.exists():
        raise ValueError('fresh immutable discussion artifact required')
    raw = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('complete discussion artifact exceeds bound; no truncation')
    expected = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    state_io.atomic_json(path, value)
    follow._bytes(expected, path.parent)
    return expected


def _scientific_state(state):
    return {key: deepcopy(state[key]) for key in ('contract', 'context', 'premises',
        'hypotheses', 'experiments', 'revisions', 'adaptations', 'parent_task') if key in state}


def _view(root, board_root):
    _, state = cycle._load(root)
    view = board.snapshot(board_root)
    if view['phase'] != 'followups_open':
        raise ValueError('all initial commitments and reveals required before discussion')
    ids = [cycle._board_hypothesis_id(view['charter_sha256'], row['actor_id'], row['hypothesis_id'], row['hypothesis_sha256']) for row in view['hypotheses']]
    by_id = {h['id']: h for h in state['hypotheses']}
    if not ids or any(identity not in by_id for identity in ids):
        raise ValueError('import the complete revealed board through cycle.import_board first')
    for identity, row in zip(ids, view['hypotheses']):
        if by_id[identity]['statement'] != row['statement']:
            raise ValueError('cycle hypothesis differs from the original board statement')
    if any(not cycle._fresh(state, h['premise_bindings']) for h in state['hypotheses']):
        raise ValueError('changed premise requires an explicit cycle revision before discussion')
    return state, view


def season_binding(board_root):
    """The season a meeting runs on, or None for a version 1 board."""
    root = cycle._ordinary(board_root)
    view = board.snapshot(root)
    if 'season' not in view:
        return None
    rundir = root.parents[2]
    if root != cycle._ordinary(seasons.journal_root(rundir, view['season'])):
        raise ValueError('a season journal lives at research/board/<season> of its run')
    reveal = seasons.season_record(rundir, view['season'], 'reveal')
    if reveal is None:
        raise ValueError('a meeting needs a season revealed through the board.season graph')
    verified = seasons.season(root, rundir=rundir)
    if verified['charter_sha256'] != reveal['journal_charter_sha256']:
        raise ValueError('the season reveal record belongs to another journal')
    # The independence label is recomputed from the retained worker receipts, never
    # read from the editable reveal record. A record without receipts is unsealed.
    receipts = reveal.get('receipts')
    seal = (seasons.sealing(rundir, verified['charter']['participants'], receipts)
            if isinstance(receipts, dict) else {'status': 'unsealed'})
    if isinstance(receipts, dict) and seal != reveal['sealing']:
        raise ValueError('the season reveal record sealing differs from its worker receipts')
    binding = {'season': view['season'], 'head_sha256': verified['head']['sha256'],
               'reveal_record_sha256': board._digest(reveal), 'no_commit': reveal['no_commit'],
               'unsealed': seal['status'] != 'sealed'}
    if not binding['unsealed']:
        binding['sealed_commit_independence'] = seal['independence']
    return binding


def _declarations(view, participant_order, designer, final_reviewers, policy):
    actors = {p['actor_id']: p for p in view['participants']}
    if (type(participant_order) is not list or not 1 <= len(participant_order) <= 8
            or len(set(participant_order)) != len(participant_order)
            or set(participant_order) != set(actors)):
        raise ValueError('complete finite participant order required')
    if type(final_reviewers) is not list or len(final_reviewers) != 2:
        raise ValueError('distinct prospective final critic and verifier declarations required')
    for value in [designer, *final_reviewers]:
        cycle.ce.keys(value, ('actor_id', 'session_id', 'model_id'))
        for key in value: cycle._text(value[key], 200)
    identities = [actors[x] for x in participant_order] + [designer] + final_reviewers
    for key in ('actor_id', 'session_id'):
        if len({row[key] for row in identities}) != len(identities):
            raise ValueError('discussion actors/sessions cannot be independent final reviewers')
    cycle.ce.keys(policy, ('adapter', 'reasoning_effort', 'max_output_tokens', 'max_wall_seconds'))
    if (policy['adapter'] not in provider_transport.MODEL_ACTIONS
            or type(policy['max_output_tokens']) is not int or not 16 <= policy['max_output_tokens'] <= 32000
            or type(policy['max_wall_seconds']) is not int or not 1 <= policy['max_wall_seconds'] <= 3600):
        raise ValueError('finite common per-turn ceilings and ordinary adapter required')
    cycle._text(policy['reasoning_effort'])
    n = len(participant_order) + 1
    return {'calls': n, 'output_tokens': n * policy['max_output_tokens'],
            'wall_seconds': n * policy['max_wall_seconds'], 'native_attempts': 0}


def _model_inputs(experiment, dependencies, base):
    manifest = cycle._exposure_manifest(experiment, dependencies, base)
    if manifest is None:
        return [experiment['study'], *dependencies]
    return [experiment['study'], experiment['input_exposure'], *[
        {k: row[k] for k in ('path', 'sha256', 'size')} for row in manifest['inputs']
        if row['purpose'] == 'model_context']]


def _fresh(root, prepared):
    cycle.ce.keys(prepared, ('schema_version', 'kind', 'cycle_root', 'board_root', 'output_dir', 'board',
        'hypothesis_mapping', 'board_head', 'scientific_state', 'arm', 'participant_order', 'designer',
        'final_reviewers', 'observations', 'candidates', 'model_policy', 'implementation',
        'presentation_isolation_only', 'outside_api_blinding_proven', 'final_review_contexts_created',
        'execution_authorized', 'physics_validated', 'matched_declared_ceiling', 'season'))
    if prepared['cycle_root'] != str(cycle._ordinary(root)):
        raise ValueError('prepared discussion belongs to another original cycle')
    out = cycle._ordinary(prepared['output_dir'])
    if '..' in out.parts or str(out) != prepared['output_dir']:
        raise ValueError('canonical original discussion destination required')
    for original in (cycle._ordinary(root), cycle._ordinary(prepared['board_root'])):
        if out == original or out.is_relative_to(original) or original.is_relative_to(out):
            raise ValueError('discussion destination must stay disjoint from original roots')
    state, view = _view(root, prepared['board_root'])
    if (view != prepared['board'] or _scientific_state(state) != prepared['scientific_state']
            or cycle._pin(__file__) != prepared['implementation']
            or season_binding(prepared['board_root']) != prepared['season']):
        raise ValueError('board, original task, hypotheses, observations or source changed')
    if (prepared['schema_version'] != 1 or prepared['kind'] != 'research_board_discussion_preparation'
            or prepared['arm'] not in ARMS or prepared['presentation_isolation_only'] is not True
            or any(prepared[key] is not False for key in ('outside_api_blinding_proven',
                'final_review_contexts_created', 'execution_authorized', 'physics_validated'))
            or prepared['matched_declared_ceiling'] != _declarations(view,
                prepared['participant_order'], prepared['designer'], prepared['final_reviewers'],
                prepared['model_policy'])):
        raise ValueError('original finite population, ceilings and authority limitations required')
    mapping = [{'actor_id': h['actor_id'], 'hypothesis_id': h['hypothesis_id'],
        'source_sha256': h['hypothesis_sha256'], 'cycle_hypothesis_id': cycle._board_hypothesis_id(view['charter_sha256'], h['actor_id'], h['hypothesis_id'], h['hypothesis_sha256'])}
        for h in view['hypotheses']]
    if prepared['hypothesis_mapping'] != mapping:
        raise ValueError('complete original actor/hypothesis-to-cycle mapping required')
    follow._bytes(prepared['board_head'], state['base_dir'])
    original_pins = {p['id']: p for p in view['artifact_pins']}
    if (len(prepared['observations']) != len(original_pins)
            or {r['id'] for r in prepared['observations']} != set(original_pins)):
        raise ValueError('complete source-observation population required')
    for row in prepared['observations']:
        cycle.ce.keys(row, ('id', 'pin', 'missing_reason', 'content_base64'))
        original = original_pins[row['id']]
        if row['pin'] is not None:
            raw = follow._bytes(row['pin'], state['base_dir'])[1]
            if (row['pin']['sha256'] != original['sha256'] or len(raw) != original['size']
                    or row['missing_reason'] is not None
                    or base64.b64encode(raw).decode('ascii') != row['content_base64']):
                raise ValueError('presented source observation changed')
        else:
            cycle._text(row['missing_reason'])
            if original['custody'] == 'frozen_bytes' or row['content_base64'] is not None:
                raise ValueError('frozen evidence cannot become a missing premise')
    trial = deepcopy(state)
    if type(prepared['candidates']) is not list or len(prepared['candidates']) > 8:
        raise ValueError('bounded complete ordinary candidates required')
    for candidate in prepared['candidates']:
        cycle.ce.keys(candidate, ('experiment', 'input_pins', 'model_input_pins'))
        experiment = candidate['experiment']
        if set(experiment['predictions']) != {h['id'] for h in state['hypotheses']}:
            raise ValueError('complete candidate hypothesis prediction population required')
        cycle._append_design(trial, experiment)
        expected = [experiment['study'], *trial['experiments'][-1]['input_pins']]
        visible = _model_inputs(experiment, expected[1:], state['base_dir'])
        if candidate['input_pins'] != expected or candidate['model_input_pins'] != visible:
            raise ValueError('complete source-bound ordinary candidate input population required')
        for pin in expected: cycle._check_pin(pin, state['base_dir'])
        for pin in visible: follow._bytes(pin, state['base_dir'])
    all_presented = [r['pin'] for r in prepared['observations'] if r['pin'] is not None]
    all_presented += [p for c in prepared['candidates'] for p in c['model_input_pins']]
    for candidate in prepared['candidates']:
        experiment = candidate['experiment']
        cycle._model_input_admission(experiment, candidate['input_pins'][1:],
            all_presented, state['base_dir'])
    return state


def prepare(root, board_root, output_dir, *, arm, participant_order, designer,
            final_reviewers, observations, candidates, max_output_tokens,
            max_wall_seconds, reasoning_effort='high', adapter='responses'):
    """Prepare either arm without dispatch. Same ceilings, not measured equal cost.

    observations covers every charter artifact: {id,pin,missing_reason}; absent
    declared-only bytes remain explicit. candidates are complete ordinary cycle
    experiment designs, or [] when missing premises need acquisition first.
    """
    if arm not in ARMS or adapter not in provider_transport.MODEL_ACTIONS:
        raise ValueError('declared discussion/isolated arm and ordinary model adapter required')
    if (type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000
            or type(max_wall_seconds) is not int or not 1 <= max_wall_seconds <= 3600):
        raise ValueError('finite common per-turn ceilings required')
    cycle._text(reasoning_effort)
    state, view = _view(root, board_root)
    policy = {'adapter': adapter, 'reasoning_effort': reasoning_effort,
              'max_output_tokens': max_output_tokens, 'max_wall_seconds': max_wall_seconds}
    ceiling = _declarations(view, participant_order, designer, final_reviewers, policy)
    out = cycle._ordinary(output_dir)
    if '..' in out.parts:
        raise ValueError('canonical fresh discussion destination required')
    for original in (cycle._ordinary(root), cycle._ordinary(board_root)):
        if out == original or out.is_relative_to(original) or original.is_relative_to(out):
            raise ValueError('discussion destination must be disjoint from cycle and board')
    if out.exists(): raise ValueError('fresh arm preparation required; no implicit retry')
    pins = {p['id']: p for p in view['artifact_pins']}
    if (type(observations) is not list or len(observations) != len(pins)
            or {r.get('id') for r in observations} != set(pins)):
        raise ValueError('complete original source-observation population required')
    source_rows = []
    for row in observations:
        cycle.ce.keys(row, ('id', 'pin', 'missing_reason'))
        original = pins[row['id']]
        if row['pin'] is None:
            cycle._text(row['missing_reason'])
            if original['custody'] == 'frozen_bytes':
                raise ValueError('frozen board evidence cannot be declared missing')
            source_rows.append({**deepcopy(row), 'content_base64': None})
        else:
            if row['missing_reason'] is not None:
                raise ValueError('present observations cannot also be missing')
            raw = follow._bytes(row['pin'], state['base_dir'])[1]
            if (row['pin']['sha256'] != original['sha256'] or len(raw) != original['size']):
                raise ValueError('observation must preserve the exact original board artifact')
            source_rows.append({**deepcopy(row), 'content_base64': base64.b64encode(raw).decode('ascii')})
    if type(candidates) is not list or len(candidates) > 8:
        raise ValueError('bounded complete ordinary experiment candidates required')
    trial = deepcopy(state)
    candidate_rows = []
    for experiment in candidates:
        if set(experiment['predictions']) != {h['id'] for h in state['hypotheses']}:
            raise ValueError('every retained hypothesis needs a prediction or explicit unknown')
        cycle._append_design(trial, experiment)
        added = trial['experiments'][-1]
        candidate_rows.append({'experiment': deepcopy(experiment),
                               'input_pins': [experiment['study'], *added['input_pins']],
            'model_input_pins': _model_inputs(experiment, added['input_pins'], state['base_dir'])})
    prepared = {'schema_version': 1, 'kind': 'research_board_discussion_preparation',
        'cycle_root': str(cycle._ordinary(root)), 'board_root': str(cycle._ordinary(board_root)),
        'output_dir': str(out),
        'board': view, 'hypothesis_mapping': [{'actor_id': h['actor_id'],
            'hypothesis_id': h['hypothesis_id'], 'source_sha256': h['hypothesis_sha256'], 'cycle_hypothesis_id': cycle._board_hypothesis_id(view['charter_sha256'], h['actor_id'], h['hypothesis_id'], h['hypothesis_sha256'])}
            for h in view['hypotheses']], 'board_head': cycle._pin(Path(board_root) / 'head.json'),
        'scientific_state': _scientific_state(state), 'arm': arm,
        'participant_order': participant_order, 'designer': deepcopy(designer),
        'final_reviewers': deepcopy(final_reviewers), 'observations': source_rows,
        'candidates': candidate_rows, 'model_policy': policy, 'implementation': cycle._pin(__file__),
        'presentation_isolation_only': True, 'outside_api_blinding_proven': False,
        'final_review_contexts_created': False, 'execution_authorized': False,
        'physics_validated': False, 'season': season_binding(board_root)}
    # Complete budget is matched independently of participant order or arm.
    prepared['matched_declared_ceiling'] = ceiling
    _fresh(root, prepared)
    pin = _write(out / 'preparation.json', prepared)
    _fresh(root, prepared)
    return pin


def _context(prepared, index, previous):
    designer = index == len(prepared['participant_order'])
    actor = (prepared['designer'] if designer else next(p for p in prepared['board']['participants']
             if p['actor_id'] == prepared['participant_order'][index]))
    all_hypotheses = prepared['scientific_state']['hypotheses']
    isolated = prepared['arm'] == 'isolated' and not designer
    ids = {cycle._board_hypothesis_id(prepared['board']['charter_sha256'], actor['actor_id'], h['hypothesis_id'], h['hypothesis_sha256']) for h in prepared['board']['hypotheses']
           if h['actor_id'] == actor['actor_id']} if isolated else {h['id'] for h in all_hypotheses}
    initial = [h for h in prepared['board']['hypotheses'] if not isolated or h['actor_id'] == actor['actor_id']]
    retained = [h for h in all_hypotheses if h['id'] in ids]
    state = prepared['scientific_state']
    return {'kind': 'research_board_turn_context', 'arm': prepared['arm'], 'turn': index,
        'actor': actor, 'designer': designer, 'question': state['contract']['question'],
        'whole_task': state['context'], 'parent_task': state.get('parent_task'),
        'premises': state['premises'], 'retained_hypotheses': retained,
        'original_board_hypotheses': initial,
        'hypothesis_mapping': [r for r in prepared['hypothesis_mapping'] if r['cycle_hypothesis_id'] in ids], 'observations': prepared['observations'],
        'prior_turns': [] if isolated else deepcopy(previous),
        'retained_prior_observations': [{'id': e['id'], 'observation': e['observation'],
            'adjudication': e['adjudication']} for e in state['experiments']],
        'candidates': deepcopy(prepared['candidates']) if designer else [],
        'edge_semantics': 'Attributed review judgments; missing premises/unknowns are not contradictions or proof.',
        'instruction': ('Retain every original and minority explanation. Propose a supplied distinguishing '
            'experiment or an acquisition for a missing premise. Do not invent observations, clear review, '
            'claim consensus as truth or replace the whole task.'),
        'outside_api_blinding_proven': False, 'scientific_acceptance_authorized': False}


def _spec(context_pin, context, prepared, index):
    policy = prepared['model_policy']
    # Literal complete JSON output; semantic validation occurs before any next turn.
    def obj(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties),
                'additionalProperties': False}
    text = {'type': 'string'}
    strings = {'type': 'array', 'items': text}
    basis = {'type': 'array', 'items': obj({'path': text, 'sha256': text, 'size': {'type': 'integer'}})}
    edge = obj({'kind': {'type': 'string', 'enum': ['contradiction', 'missing_premise']},
                'hypothesis_ids': strings, 'statement': text, 'source_basis': basis})
    proposal = obj({'kind': {'type': 'string', 'enum': ['acquisition', 'experiment']},
        'question': text, 'hypothesis_ids': strings, 'missing_inputs': strings,
        'expected_outcomes': {'type': 'array', 'items': obj({'label': text,
                                      'prediction': {'type': ['string', 'null']}})}, 'source_basis': basis})
    schema = {'type': 'object', 'properties': {
        'retained_hypothesis_ids': strings,
        'edges': {'type': 'array', 'items': edge},
        'proposals': {'type': 'array', 'items': proposal},
        'selected_experiment': {'type': ['string', 'null']},
        'reason': {'type': 'string'}},
        'required': ['retained_hypothesis_ids', 'edges', 'proposals', 'selected_experiment', 'reason'],
        'additionalProperties': False}
    inputs = [{'id': 'discussion-context', **{k: context_pin[k] for k in ('path', 'sha256')}}]
    if context['designer']:
        sources = {p['path']: p for c in prepared['candidates'] for p in c['model_input_pins']}
        inputs += [{'id': 'candidate-' + str(i), **{k: pin[k] for k in ('path', 'sha256')}}
                   for i, pin in enumerate(sources.values())]
    return agent_graph.validate({'schema_version': 1, 'graph_id': 'board-turn-' + str(index),
        'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': policy['max_output_tokens'],
            'max_wall_seconds': policy['max_wall_seconds'], 'max_reworks': 0},
        'nodes': [{'id': 'turn', 'kind': 'model', 'role': 'designer' if context['designer'] else 'proposer',
            'depends_on': [], 'inputs': inputs, 'packet': None, 'action': policy['adapter'],
            'max_attempts': 1, 'parameters': {'model': context['actor']['model_id'],
                'reasoning_effort': policy['reasoning_effort'], 'max_output_tokens': policy['max_output_tokens'],
                'instructions': context['instruction'] + ' Return the complete declared turn JSON. '
                    'Edges are {kind,hypothesis_ids,statement,source_basis}; proposals are '
                    '{kind,question,hypothesis_ids,missing_inputs,expected_outcomes,source_basis}. '
                    'kind is contradiction/missing_premise for edges, acquisition/experiment for proposals. '
                    'Every source_basis pin is {path,sha256,size} from the presented observations; '
                    'expected_outcomes is an array of {label,prediction:string|null}. '
                    'Only the designer may select an exact supplied candidate ID; null stays a proposed acquisition.',
                'output_schema': schema}}]})


def _turn_value(value, context, prepared):
    cycle.ce.keys(value, ('retained_hypothesis_ids', 'edges', 'proposals', 'selected_experiment', 'reason'))
    ids = {h['id'] for h in context['retained_hypotheses']}
    if (type(value['retained_hypothesis_ids']) is not list
            or len(value['retained_hypothesis_ids']) != len(ids)
            or set(value['retained_hypothesis_ids']) != ids):
        raise ValueError('complete visible original/minority hypothesis census must be retained')
    cycle._text(value['reason'])
    available = {cycle.ce.digest(r['pin']) for r in prepared['observations'] if r['pin'] is not None}
    for key, allowed in (('edges', {'contradiction', 'missing_premise'}),
                         ('proposals', {'acquisition', 'experiment'})):
        rows = value[key]
        if type(rows) is not list or len(rows) > 32:
            raise ValueError('bounded complete constructive edge/proposal population required')
        for row in rows:
            fields = ('kind', 'hypothesis_ids', 'statement', 'source_basis') if key == 'edges' else (
                'kind', 'question', 'hypothesis_ids', 'missing_inputs', 'expected_outcomes', 'source_basis')
            cycle.ce.keys(row, fields)
            if (row['kind'] not in allowed or type(row['hypothesis_ids']) is not list
                    or not row['hypothesis_ids'] or len(set(row['hypothesis_ids'])) != len(row['hypothesis_ids'])
                    or not set(row['hypothesis_ids']) <= ids):
                raise ValueError('constructive edge/proposal must name visible hypotheses')
            cycle._text(row['statement'] if key == 'edges' else row['question'])
            if type(row['source_basis']) is not list or len(row['source_basis']) > 16:
                raise ValueError('bounded presented source basis required')
            if any(cycle.ce.digest(pin) not in available for pin in row['source_basis']):
                raise ValueError('edge/proposal source was not actually presented')
            if key == 'proposals':
                if type(row['missing_inputs']) is not list or len(row['missing_inputs']) > 16:
                    raise ValueError('explicit missing-premise acquisition population required')
                for missing in row['missing_inputs']: cycle._text(missing)
                if type(row['expected_outcomes']) is not list or len(row['expected_outcomes']) > 16:
                    raise ValueError('declared expected outcomes or explicit unknown required')
                labels = []
                for outcome in row['expected_outcomes']:
                    cycle.ce.keys(outcome, ('label', 'prediction')); cycle._text(outcome['label'])
                    if outcome['prediction'] is not None: cycle._text(outcome['prediction'])
                    labels.append(outcome['label'])
                if len(labels) != len(set(labels)): raise ValueError('distinct prospective outcome labels required')
    selected = value['selected_experiment']
    candidates = {r['experiment']['id']: r for r in prepared['candidates']}
    if selected is not None and (not context['designer'] or selected not in candidates):
        raise ValueError('only designer may select an exact supplied ordinary candidate')
    if context['designer'] and selected is None and not value['proposals']:
        raise ValueError('missing premises need a concrete acquisition/experiment proposal')
    return deepcopy(value)


def _reserve(root, prepared, out):
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        state = _fresh(root, prepared)
        refusal = cycle._clock(state, prepared['matched_declared_ceiling']['wall_seconds'])
        if refusal is not None:
            raise cycle.OperationalBoundaryError('complete meeting cannot fit original campaign deadline')
        policy = prepared['model_policy']
        for i in range(len(prepared['participant_order']) + 1):
            graph = out / ('graph-' + str(i))
            cycle._charge(state, 'graph:' + str(graph), {'calls': 1,
                'output_tokens': policy['max_output_tokens'], 'wall_seconds': policy['max_wall_seconds'],
                'native_attempts': 0}, {'specification_sha256': None,
                'discussion_preparation_sha256': cycle.ce.digest(prepared), 'turn': i})
        return cycle._commit(Path(root), state, 'complete_discussion_sequence_reserved',
            arm=prepared['arm'], output=str(out), all_turns_reserved_before_dispatch=True)


def _bind(root, prepared, graph, spec, index):
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        state = _fresh(root, prepared)
        row = next(r for r in state['resource_ledger'] if r['id'] == 'graph:' + str(graph))
        if (row['basis']['specification_sha256'] is not None
                or row['basis']['discussion_preparation_sha256'] != cycle.ce.digest(prepared)
                or row['basis']['turn'] != index):
            raise ValueError('discussion reservation binds once; no retry or renewed allowance')
        if 'goal_binding' in state['contract']:
            spec = deepcopy(spec); spec['goal_binding'] = deepcopy(state['contract']['goal_binding'])
        agent_graph.create(graph, spec)
        row['basis']['specification_sha256'] = cycle.ce.digest(spec)
        cycle._commit(Path(root), state, 'discussion_reserved_turn_bound', turn=index, graph_root=str(graph))
        return spec


def _report_value(root, prepared, out, turns, failure, preparation_pin):
    _, state = cycle._load(root)
    result = {'schema_version': 1, 'kind': 'research_board_discussion_report',
        'preparation': deepcopy(preparation_pin), 'arm': prepared['arm'], 'season': deepcopy(prepared['season']),
        'complete': failure is None, 'failure': failure, 'original_board': prepared['board'],
        'hypothesis_mapping': prepared['hypothesis_mapping'],
        'all_original_hypotheses': prepared['scientific_state']['hypotheses'],
        'whole_task': prepared['scientific_state']['context'],
        'original_experiment_history': prepared['scientific_state']['experiments'],
        'observations': prepared['observations'], 'turns': turns,
        'raw_turns': [cycle._pin(p) for p in sorted(out.glob('raw-turn-*.json'))],
        'checked_turns': [cycle._pin(p) for p in sorted(out.glob('checked-turn-*.json'))],
        'reserved_ceiling': prepared['matched_declared_ceiling'],
        'actual_graph_observations': [g for g in state['graphs'] if Path(g['root']).parent == out],
        'reserved_turns': [r for r in state['resource_ledger'] if Path(r['id'].removeprefix('graph:')).parent == out],
        'matched_declared_not_measured_equal_cost': True, 'minority_explanations_retained': True,
        'edge_judgments_not_automated_proof': True, 'final_review_contexts_created': False,
        'outside_api_blinding_proven': False, 'scientific_acceptance_authorized': False,
        'execution_authorized': False, 'physics_validated': False, 'retry_attempts': 0}
    return result


def _report(root, prepared, out, turns, failure, preparation_pin):
    return _write(out / 'report.json', _report_value(root, prepared, out, turns, failure, preparation_pin))


def run(root, preparation_pin, *, host):
    """Actual model dispatch entry; software tests supply an explicit fake Host.

    Preparation creates no calls. This entry reserves ALL participant+designer
    turns in the existing ledger first, then uses unchanged execute_graph. A
    failed/invalid turn stops once; every later reservation and raw result stays.
    """
    _, state = cycle._load(root)
    prepared = follow._json(preparation_pin, state['base_dir'])
    path = follow._bytes(preparation_pin, state['base_dir'])[0]
    out = path.parent
    if path != Path(prepared['output_dir']) / 'preparation.json':
        raise ValueError('original committed preparation location required')
    if prepared['cycle_root'] != str(cycle._ordinary(root)):
        raise ValueError('prepared discussion belongs to another original cycle')
    _fresh(root, prepared)
    if (out / 'report.json').exists(): raise ValueError('completed/failed meeting is immutable; no implicit retry')
    _reserve(root, prepared, out)
    turns = []
    for index in range(len(prepared['participant_order']) + 1):
        try:
            _fresh(root, prepared)
            follow._bytes(preparation_pin, state['base_dir'])
            context = _context(prepared, index, turns)
            context_pin = _write(out / ('context-' + str(index) + '.json'), context)
            spec = _spec(context_pin, context, prepared, index)
            graph = out / ('graph-' + str(index))
            spec = _bind(root, prepared, graph, spec, index)
            observed = cycle.execute_graph(root, graph, spec, host, prepared=True)
            if not observed['complete']:
                return _report(root, prepared, out, turns, {'turn': index, 'kind': 'ordinary_graph_incomplete'}, preparation_pin)
            origin = cycle._graph_result(graph, 'turn')
            _write(out / ('raw-turn-' + str(index) + '.json'),
                   {'index': index, 'context': context_pin, 'origin': origin})
            if origin['value'].get('kind') != 'model_result':
                raise ValueError('structured model result required; control results are not scientific efficacy')
            value = _turn_value(origin['value']['value'], context, prepared)
            turns.append({'index': index, 'actor': context['actor'], 'context': context_pin,
                          'origin': origin, 'judgment': value})
            _fresh(root, prepared)
            follow._bytes(preparation_pin, state['base_dir'])
            _write(out / ('checked-turn-' + str(index) + '.json'), turns[-1])
        except Exception as exc:
            return _report(root, prepared, out, turns, {'turn': index, 'kind': type(exc).__name__, 'message': str(exc)}, preparation_pin)
    return _report(root, prepared, out, turns, None, preparation_pin)


def adopt(root, report_pin):
    """Rebind real charged turns and add the selected prospective ordinary design.

    A missing-premise-only report remains a retained acquisition proposal. No
    scientific review, model efficacy, execution approval or parent acceptance is
    manufactured. Use existing cycle.select/prepare and ordinary review afterward.
    """
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = cycle._load(root)
        report = follow._json(report_pin, state['base_dir'])
        prepared = follow._json(report['preparation'], state['base_dir'])
        state = _fresh(root, prepared)
        if not report['complete'] or report['failure'] is not None:
            raise ValueError('failed/incomplete discussion cannot supply an adopted design')
        if (len(report['turns']) != len(prepared['participant_order']) + 1
                or len(report['raw_turns']) != len(report['turns'])
                or len(report['checked_turns']) != len(report['turns'])):
            raise ValueError('complete sequential participant+designer population required')
        previous = []
        for index, turn in enumerate(report['turns']):
            context = _context(prepared, index, previous)
            if follow._json(turn['context'], state['base_dir']) != context:
                raise ValueError('context disclosure changed or lost earlier discussion')
            graph = Path(turn['origin']['root'])
            if (graph != Path(prepared['output_dir']) / ('graph-' + str(index))
                    or turn['index'] != index or turn['actor'] != context['actor']):
                raise ValueError('exact sequential original turn identity required')
            origin = cycle._graph_result(graph, 'turn')
            spec, _ = agent_graph._load(graph)
            expected = _spec(turn['context'], context, prepared, index)
            if 'goal_binding' in state['contract']:
                expected['goal_binding'] = deepcopy(state['contract']['goal_binding'])
            charged = next((r for r in state['resource_ledger'] if r['id'] == 'graph:' + str(graph)), None)
            if (origin != turn['origin'] or spec != expected or charged is None
                    or charged['basis']['discussion_preparation_sha256'] != cycle.ce.digest(prepared)
                    or charged['basis']['turn'] != index
                    or origin['role'] != ('designer' if context['designer'] else 'proposer')):
                raise ValueError('actual original charged Graph turns required')
            raw_pin = report['raw_turns'][index]
            checked_pin = report['checked_turns'][index]
            if (follow._bytes(raw_pin, state['base_dir'])[0] != graph.parent / ('raw-turn-' + str(index) + '.json')
                    or follow._bytes(checked_pin, state['base_dir'])[0] != graph.parent / ('checked-turn-' + str(index) + '.json')
                    or follow._json(raw_pin, state['base_dir']) != {'index': index, 'context': turn['context'], 'origin': origin}
                    or follow._json(checked_pin, state['base_dir']) != turn):
                raise ValueError('intended raw and checked turn commitments differ from actual Graph')
            value = _turn_value(origin['value']['value'], context, prepared)
            if value != turn['judgment']: raise ValueError('retained judgment differs from actual raw response')
            previous.append(turn)
        out = Path(prepared['output_dir'])
        if follow._bytes(report['preparation'], state['base_dir'])[0] != out / 'preparation.json':
            raise ValueError('original committed preparation location required')
        if report != _report_value(root, prepared, out, previous, None, report['preparation']):
            raise ValueError('whole retained report, raw turns, usage and limitations must remain exact')
        # Ending snapshot precedes every return/commit, including acquisition-only.
        _fresh(root, prepared)
        follow._bytes(report_pin, state['base_dir'])
        follow._bytes(report['preparation'], state['base_dir'])
        for pin in [*report['raw_turns'], *report['checked_turns']]:
            follow._bytes(pin, state['base_dir'])
        selected = previous[-1]['judgment']['selected_experiment']
        if selected is None:
            return {'kind': 'research_board_acquisition_proposal', 'report': deepcopy(report_pin),
                    'proposals': previous[-1]['judgment']['proposals'], 'design_adopted': False,
                    'execution_authorized': False, 'physics_validated': False}
        experiment = next(r['experiment'] for r in prepared['candidates'] if r['experiment']['id'] == selected)
        trial = deepcopy(state)
        cycle._append_design(trial, experiment)
        added = trial['experiments'][-1]
        cycle._model_input_admission(added, added['input_pins'], previous[-1]['origin']['inputs'], state['base_dir'])
        added['constructive_origin'] = {'kind': 'revealed_board_discussion', 'report': deepcopy(report_pin),
            'designer_origin': previous[-1]['origin'], 'all_original_hypotheses_retained': True,
            'independent_scientific_review': False, 'old_votes_carried': []}
        _fresh(root, prepared)
        follow._bytes(report_pin, state['base_dir'])
        return cycle._commit(Path(root), trial, 'board_discussion_prospective_design_adopted',
                             experiment_id=selected, arm=prepared['arm'])
