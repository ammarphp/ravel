"""Derived research outcome and resource instrumentation, never a truth score.

Uses the original task, cycle, Graph call receipts and ordinary attempt records.
No dispatch, additional journal, acceptance gate, actor authentication or default
reward is introduced. Historical acceptance is reported within its exact scope.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from . import agent_graph, candidate_experiments as ce, state_io

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 512


class _Evidence:
    """Reuse the cycle's bounded descriptor reader; parse its exact byte snapshot."""
    def __init__(self):
        self.files = {}; self.directories = {}; self.total = 0

    def document(self, path, pin=None):
        from .research_cycle import _bounded_source_snapshot
        path = Path(path).absolute()
        if str(path) in self.files:
            actual, raw = self.files[str(path)]
        else:
            path, raw = _bounded_source_snapshot(path, MAX_DOCUMENT_BYTES)
            actual = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
            self.total += len(raw)
            if len(self.files) >= MAX_FILES or self.total > MAX_TOTAL_BYTES:
                raise ValueError('metrics evidence census exceeds512 files/64MiB; never truncate')
            self.files[str(path)] = (actual, raw)
        if pin is not None and actual != pin:
            raise ValueError('metrics evidence differs from committed source pin')
        from .agent_host import _loads, HostFailure
        try:
            return _loads(raw)
        except HostFailure as exc:
            raise ValueError('strict metrics JSON required') from exc

    def membership(self, directory, *, directories=False):
        from .research_cycle import _ordinary
        directory = _ordinary(directory)
        if not directory.is_dir():
            return None
        names = tuple(sorted(p.name for p in directory.iterdir()))
        if len(names) > MAX_FILES:
            raise ValueError('metrics directory census exceeds512; never truncate')
        for name in names:
            p = _ordinary(directory / name)
            if not (p.is_dir() if directories else p.is_file()):
                raise ValueError('ordinary complete metrics receipt directory required')
        self.directories[str(directory)] = names
        return names

    def finish(self):
        from .research_cycle import _bounded_source_snapshot
        for pin, raw in self.files.values():
            _, ending = _bounded_source_snapshot(Path(pin['path']), MAX_DOCUMENT_BYTES)
            if ending != raw: raise ValueError('metrics source changed before return')
        for directory, names in self.directories.items():
            if tuple(sorted(p.name for p in Path(directory).iterdir())) != names:
                raise ValueError('metrics receipt membership changed before return')


def _number(value, name, integer=False):
    if value is None: return None
    if (type(value) is not int if integer else type(value) not in (int, float)) or value < 0 or type(value) is float and not math.isfinite(value):
        raise ValueError('finite nonnegative receipted ' + name + ' required')
    return value


def _aggregate(rows, field):
    values = [r[field] for r in rows if r[field] is not None]
    return {'observed_subtotal': sum(values), 'total': sum(values) if len(values) == len(rows) else None,
            'observed_records': len(values), 'unknown_records': len(rows) - len(values), 'denominator': len(rows)}


def _seconds(record):
    if record.get('finished_utc') is None or record.get('started_utc') is None: return None
    try:
        start = datetime.fromisoformat(record['started_utc'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(record['finished_utc'].replace('Z', '+00:00'))
        if start.tzinfo is None or end.tzinfo is None: raise ValueError('timezone absent')
        return _number((end - start).total_seconds(), 'attempt duration')
    except (TypeError, AttributeError) as exc:
        raise ValueError('receipted UTC attempt times required') from exc


def _graphs(state, evidence):
    # A reservation can precede dispatch or survive an ambiguous dispatch. It is
    # part of the denominator even without a saved successful graph observation.
    roots = {g['root'] for g in state['graphs']}
    roots.update(r['id'][6:] for r in state['resource_ledger'] if r['id'].startswith('graph:'))
    graphs, calls, histories = [], [], []
    seen_instances, seen_calls = set(), set()
    for root_name in sorted(roots):
        root = Path(root_name)
        if not (root / agent_graph.STATE).exists():
            graphs.append({'root': root_name, 'state': 'unobserved', 'observed_calls': None})
            continue
        spec = evidence.document(root / agent_graph.SPEC)
        current = evidence.document(root / agent_graph.STATE)
        if (current.get('spec_sha256') != agent_graph.digest(spec)
                or current.get('graph_id') != spec.get('graph_id')
                or set(current.get('nodes', {})) != {n['id'] for n in spec['nodes']}):
            raise ValueError('metrics Graph differs from exact specification')
        instance = current.get('instance_id')
        if type(instance) is not str or not instance or instance in seen_instances:
            raise ValueError('duplicate or absent Graph instance; copies/aliases are not extra calls')
        seen_instances.add(instance)
        if type(current['usage']['calls']) is not int or current['usage']['calls'] != len(current['calls']):
            raise ValueError('Graph call debit differs from complete call census')
        names = evidence.membership(root / 'calls')
        expected = {identity + '.json' for identity in current['calls']}
        if names is not None and set(names) - expected:
            raise ValueError('unaccounted Graph call receipt; preserve whole call denominator')
        for identity, row in current['calls'].items():
            if identity in seen_calls: raise ValueError('duplicate actual call identity across Graph roots')
            seen_calls.add(identity)
            if row['status'] not in ('started', 'ambiguous', 'completed', 'failed'):
                raise ValueError('known Graph call disposition required')
            path = root / 'calls' / (identity + '.json')
            receipt = evidence.document(path) if path.exists() else None
            if receipt is None and row['status'] not in ('started', 'ambiguous'):
                raise ValueError('terminal Graph call receipt absent')
            if receipt is not None:
                if (receipt.get('call_id') != identity or receipt.get('request_sha256') != row['request_sha256']
                        or receipt.get('kind') != row['kind'] or receipt.get('status') != row['status']
                        or receipt.get('output_tokens_reserved') != row['output_tokens_reserved']
                        or row.get('receipt_sha256') is not None and agent_graph.digest(receipt) != row['receipt_sha256']):
                    raise ValueError('Graph call receipt correlation changed')
                if receipt.get('status') == 'completed' and agent_graph.digest(receipt.get('result')) != receipt.get('result_sha256'):
                    raise ValueError('Graph call result changed')
            result = {} if receipt is None else receipt.get('result', {})
            usage = result.get('usage', {}) if type(result) is dict and result.get('kind') == 'model_result' else {}
            tokens = {k: _number(usage.get(k), k, integer=True) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
            if all(v is not None for v in tokens.values()) and tokens['input_tokens'] + tokens['output_tokens'] != tokens['total_tokens']:
                raise ValueError('receipted token total inconsistent')
            resolved = receipt is not None and row['status'] in ('completed', 'failed')
            calls.append({'graph_root': root_name, 'call_id': identity, 'node_id': row['node_id'],
                'attempt_id': row['attempt_id'], 'kind': row['kind'], 'status': row['status'],
                'observation_state': ('resolved_outcome_receipt' if resolved else
                    'ambiguous_outcome_receipt' if receipt is not None and row['status'] == 'ambiguous' else
                    'started_receipt_only' if receipt is not None else 'debited_without_receipt'),
                'resolved_outcome': resolved,
                'provider_invocations': None,
                'reconciliation': None if receipt is None else deepcopy(receipt.get('reconciliation')),
                'output_token_ceiling': _number(row['output_tokens_reserved'], 'output token reservation', integer=True), **tokens,
                'elapsed_seconds': _number(None if receipt is None else receipt.get('elapsed_seconds'), 'call duration'),
                'billed_cost': None, 'usage_scope': 'Individual receipt-reported measurements, including partial ambiguous outcomes. A debit/start is not a dispatched provider call; provider invocation, billing and actor origin are not authenticated.',
                'receipt': None if receipt is None else evidence.files[str(path.absolute())][0]})
        if (type(current['usage']['reserved_output_tokens']) is not int or current['usage']['reserved_output_tokens']
                != sum(r['output_tokens_reserved'] for r in current['calls'].values())):
            raise ValueError('Graph output reservation differs from whole call census')
        graph_calls = [row for row in calls if row['graph_root'] == root_name]
        graphs.append({'root': root_name, 'state': 'observed',
            'observation_scope': 'Complete Graph checkpoint, not complete provider-dispatch observation',
            'debited_calls': len(graph_calls),
            'observed_calls': sum(row['resolved_outcome'] for row in graph_calls),
            'unresolved_calls': sum(not row['resolved_outcome'] for row in graph_calls),
            'reserved_output_tokens': current['usage']['reserved_output_tokens'],
            'reworks': current['reworks'], 'cancelled': current['cancelled'],
            'nodes': deepcopy(current['nodes'])})
        histories.extend({'source': root_name, **deepcopy(event)} for event in current['history'])
    return graphs, calls, histories


def _attempts(state, evidence):
    attempts, approvals, unavailable = {}, [], []
    for experiment in state['experiments']:
        root_name = experiment.get('rundir')
        if root_name is None: continue
        root = Path(root_name)
        from . import science
        approval = root / science.APPROVAL
        if approval.exists():
            document = evidence.document(approval)
            if document.get('approval_mode') not in ('scripted_yes', 'physicist') or document.get('expert_review') is not False:
                raise ValueError('known ordinary approval observation required')
            approvals.append({'experiment_id': experiment['id'], 'approval': evidence.files[str(approval.absolute())][0],
                'declared_mode': document['approval_mode'], 'quote': document.get('quote'),
                'classification': 'machine_scripted_assent' if document['approval_mode'] == 'scripted_yes' else 'declared_physicist_mode',
                'expert_review_recorded': False, 'human_origin_authenticated': False})
        paths = []
        observation = experiment.get('observation')
        if observation is not None and observation.get('receipt') is not None:
            paths.append((Path(observation['receipt']['path']), observation['receipt']))
        # Old failed/retried records stay alongside the current attempt. Enumerate
        # the ordinary science attempt directory, never only the last success.
        directory = root / 'logs/execution/science'
        from .research_cycle import _ordinary
        if directory.exists():
            directory = _ordinary(directory)
            names = evidence.membership(directory, directories=True)
            if len(names) > 128: raise ValueError('metrics attempt census exceeds128')
            for name in names:
                child = _ordinary(directory / name)
                if not child.is_dir(): raise ValueError('ordinary attempt directory required')
                if (child / 'record.json').exists(): paths.append((child / 'record.json', None))
                else: unavailable.append({'rundir': str(root), 'directory': str(child), 'state': 'unobserved_attempt_record'})
        for path, pin in paths:
            record = evidence.document(path, pin)
            if record.get('stage') != 'science' or record.get('status') not in ('running', 'succeeded', 'failed', 'interrupted'):
                raise ValueError('ordinary scientific attempt record required')
            identity = (str(root.absolute()), record['attempt_id'])
            row = {'rundir': identity[0], 'attempt_id': identity[1], 'status': record['status'],
                'exit_code': record.get('exit_code'), 'elapsed_seconds': _seconds(record),
                'native_calls': None, 'native_seconds': None, 'billed_cost': None,
                'record': evidence.files[str(path.absolute())][0]}
            if identity in attempts and attempts[identity] != row: raise ValueError('attempt identity conflicting')
            attempts[identity] = row
    return list(attempts.values()), approvals, unavailable


def _task(state, completion):
    parent = state.get('parent_task')
    if parent is None:
        if completion is not None: raise ValueError('metrics completion needs exact bound original parent')
        return {'state': 'unbound_original_task', 'original_request': state['contract']['question'],
            'original_obligation_census': None, 'original_obligation_denominator': None,
            'recorded_parent_acceptance': None, 'independent_correctness': 'unknown'}
    census = []
    provided = {} if completion is None else {r['id']: r for r in completion['obligation_census']}
    if completion is not None and (completion['original_request'] != parent['original_request']
            or not any(p == parent['contract'] for p in completion['input_pins'])
            or set(provided) != {r['id'] for r in parent['original_obligations']}):
        raise ValueError('metrics completion must retain exact whole original parent denominator')
    effective = {r['id']: r for r in parent['effective_obligations']}
    for row in parent['original_obligations']:
        census.append({'id': row['id'], 'original': deepcopy(row), 'effective': deepcopy(effective[row['id']]),
            'recorded_coverage': 'open' if row['id'] not in provided else provided[row['id']]['state'],
            'contributions': [] if row['id'] not in provided else deepcopy(provided[row['id']]['contributions']),
            'independent_correctness': 'unknown'})
    addressed = sum(r['recorded_coverage'] == 'addressed' for r in census)
    accepted = None if completion is None else completion['parent_task_accepted']
    return {'state': 'recorded_full_delivery' if accepted else 'partial' if addressed else 'unresolved',
        'contract': deepcopy(parent['contract']), 'original_request': parent['original_request'],
        'original_obligation_census': census, 'original_obligation_denominator': len(census),
        'addressed_obligations': addressed, 'scope_changes': deepcopy(parent['scope_changes']),
        'recorded_parent_acceptance': accepted, 'acceptance_scope': None if completion is None else completion['parent_acceptance_scope'],
        'independent_correctness': 'unknown', 'semantic_entailment_verified': False}


def _utility(pin, state, evidence):
    if pin is None: return None
    document = evidence.document(Path(pin['path']), pin)
    ce.keys(document, ('schema_version', 'kind', 'original_contract', 'declaration_source', 'statement', 'goals'))
    if (type(document['schema_version']) is not int or document['schema_version'] != 1
            or document['kind'] != 'declared-research-utility' or state.get('parent_task') is None
            or document['original_contract'] != state['parent_task']['contract']
            or document['declaration_source'] not in ('user_instruction', 'task_declaration')
            or type(document['statement']) is not str or not document['statement'].strip()):
        raise ValueError('explicit original-task-bound utility declaration required')
    if type(document['goals']) is not list or not 1 <= len(document['goals']) <= 32:
        raise ValueError('bounded complete declared utility goal census required')
    seen = set()
    for goal in document['goals']:
        ce.keys(goal, ('id', 'statement', 'criteria', 'obligation_ids')); ce.identity(goal['id'])
        if goal['id'] in seen or type(goal['statement']) is not str or not goal['statement'].strip(): raise ValueError('distinct literal utility goals required')
        seen.add(goal['id'])
        if type(goal['criteria']) is not dict or not goal['criteria']: raise ValueError('explicit utility criteria required')
        if (type(goal['obligation_ids']) is not list or not goal['obligation_ids']
                or len(set(goal['obligation_ids'])) != len(goal['obligation_ids'])
                or set(goal['obligation_ids']) - {r['id'] for r in state['parent_task']['original_obligations']}):
            raise ValueError('utility must name original task obligations')
    return {'declaration': deepcopy(document), 'source': deepcopy(pin), 'origin_authenticated': False,
            'utility_value': None, 'benefit_measured': False}



def avoided_work(decision, comparison=None):
    """Recorded method-choice comparisons only, never inferred launch savings.

    Separate comparison records carry compared_rung, native_launches, model_calls and
    evidence. They are declared comparisons, not measured campaign benefits.
    """
    unknown = {'avoided_native_launches': None, 'avoided_model_calls': None}
    if not isinstance(decision, dict) or comparison is None:
        return unknown
    if not isinstance(comparison, dict):
        raise ValueError('method-choice comparison object required')
    row = comparison
    selected = decision['selected']['rung']
    compared = row.get('compared_rung')
    if type(compared) is not int or compared <= selected or not row.get('evidence'):
        raise ValueError('avoided work requires an evidenced comparison with a more expensive rung')
    return {'avoided_native_launches': _number(row.get('native_launches'), 'avoided native launches', integer=True),
            'avoided_model_calls': _number(row.get('model_calls'), 'avoided model calls', integer=True)}

def project(root, state, *, completion=None, utility_declaration=None):
    """Internal composition from an already verified cycle and completion view."""
    from . import research_cycle as rc
    evidence = _Evidence()
    root = rc._ordinary(root)
    head = evidence.document(root / 'head.json')
    evidence.document(Path(head['path']), head)
    current = rc._load_history(root)[1]
    for revision in range(current['revision'] + 1):
        evidence.document(root / 'history' / f'{revision:04d}.json')
    if current != state: raise ValueError('metrics state differs from current cycle head')
    graphs, calls, graph_events = _graphs(state, evidence)
    attempts, approvals, unavailable_attempts = _attempts(state, evidence)
    experiments = []
    reviews = []
    for experiment in state['experiments']:
        observation = experiment.get('observation')
        adjudication = experiment.get('adjudication')
        view = None if adjudication is None else adjudication['view']
        if adjudication is not None:
            saved = evidence.document(Path(adjudication['snapshot']['path']), adjudication['snapshot'])
            reviews.extend({'experiment_id': experiment['id'], **deepcopy(event)} for event in saved['events'])
        classification = ('unresolved' if observation is None else
            'failed' if observation.get('execution_status') not in ('succeeded', 'completed') else
            'partial' if observation.get('outcome') is None else 'recorded_component_result')
        experiments.append({'id': experiment['id'], 'parent': experiment.get('parent'), 'change': experiment['change'],
            'state': classification, 'observation': deepcopy(observation),
            'current_applicability': rc._applicability(state, experiment),
            'recorded_review_state': None if view is None else view['state'],
            'recorded_acceptance_scope': None if view is None or view['state'] != 'accepted' else adjudication['scope'],
            'independent_correctness': 'unknown', 'improvement_measured': False})
    missing = [identity for identity in state['contract']['required_experiments'] if identity not in {e['id'] for e in experiments}]
    experiments.extend({'id': identity, 'state': 'not_designed', 'independent_correctness': 'unknown'} for identity in missing)
    model_calls = [r for r in calls if r['kind'] == 'model']
    unknown_graphs = sum(g['state'] != 'observed' for g in graphs)
    unresolved_calls = sum(not row['resolved_outcome'] for row in calls)
    unresolved_model_calls = sum(not row['resolved_outcome'] for row in model_calls)
    resolved_calls = len(calls) - unresolved_calls
    tokens = {key: _aggregate(model_calls, key) for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    for metric in tokens.values():
        metric['unobserved_graphs'] = unknown_graphs
        metric['unresolved_call_records'] = unresolved_model_calls
        if unknown_graphs or unresolved_model_calls: metric['total'] = None
    stage_seconds = _aggregate(attempts, 'elapsed_seconds')
    stage_seconds['unobserved_attempt_records'] = len(unavailable_attempts)
    if unavailable_attempts: stage_seconds['total'] = None
    call_seconds = _aggregate(calls, 'elapsed_seconds')
    call_seconds['unobserved_graphs'] = unknown_graphs
    call_seconds['unresolved_call_records'] = unresolved_calls
    if unknown_graphs or unresolved_calls: call_seconds['total'] = None
    # Repeated snapshots of one review chain are not additional interventions.
    unique_reviews = {}
    for row in reviews:
        origin = next(e.get('rundir') for e in state['experiments'] if e['id'] == row['experiment_id'])
        key = ce.digest({'rundir': origin, 'event': {k: v for k, v in row.items() if k != 'experiment_id'}})
        if key not in unique_reviews: unique_reviews[key] = {**row, 'experiment_ids': []}
        unique_reviews[key]['experiment_ids'].append(row['experiment_id'])
    reviews = list(unique_reviews.values())
    from .cost_records import resource_vector
    # No instrument establishes a complete whole-campaign vector. Keep the
    # separate observed subtotals; inclusive graph and stage times can overlap.
    resources = resource_vector()
    comparisons = []
    seen_decisions = set()
    for experiment in state['experiments']:
        rd = experiment.get('rundir')
        if rd is None:
            continue
        path = Path(rd) / 'inputs/method_decision.json'
        if not path.exists() or str(path.absolute()) in seen_decisions:
            continue
        seen_decisions.add(str(path.absolute()))
        decision = evidence.document(path)
        comparison_path = Path(rd) / 'inputs/method_choice_comparison.json'
        comparison = None
        if comparison_path.exists():
            comparison = evidence.document(comparison_path)
            if comparison.get('schema_version') != 1 or comparison.get('kind') != 'method-choice-comparison':
                raise ValueError('versioned method-choice comparison record required')
            if evidence.document(path, comparison['method_decision']) != decision:
                raise ValueError('method-choice comparison names another decision')
        comparisons.append({'experiment_id': experiment['id'], **avoided_work(decision, comparison),
                            'record': evidence.files[str(path.absolute())][0],
                            'comparison_record': None if comparison is None else evidence.files[str(comparison_path.absolute())][0]})
    savings = {key: _aggregate(comparisons, key)['total'] if comparisons else None
               for key in ('avoided_native_launches', 'avoided_model_calls')}
    result = {'schema_version': 1, 'kind': 'research-outcome-metrics',
        'research_state_sha256': state['sha256'], 'revision': state['revision'],
        'original_task': _task(state, completion),
        'required_experiment_ids': deepcopy(state['contract']['required_experiments']),
        'complete_experiment_census': experiments,
        'component_outcome_counts': {label: sum(e['state'] == label for e in experiments) for label in
            ('not_designed', 'unresolved', 'failed', 'partial', 'recorded_component_result')},
        'resource_use': {'declared_budget': deepcopy(state['contract']['budget']),
            'charged_ceiling': rc._usage(state), 'complete_reservation_ledger': deepcopy(state['resource_ledger']),
            'graphs': graphs, 'call_receipts': calls, 'ordinary_attempts': attempts,
            'call_receipts_scope': 'Every debited Graph call record, including missing/start-only receipts and ambiguous outcomes; no reservation is discarded.',
            'unobserved_attempt_records': unavailable_attempts,
            'prospective_declared_cost_vectors': [{'experiment_id': e['id'], 'cost': deepcopy(e['cost'])} for e in state['experiments']],
            'calls': {'observed_count': resolved_calls,
                'complete_count': resolved_calls if not unknown_graphs and not unresolved_calls else None,
                'count_scope': 'Resolved completed/failed outcome receipts; compatibility names do not denote actual provider calls.',
                'debited_count': len(calls),
                'debited_complete_count': len(calls) if not unknown_graphs else None,
                'receipt_count': sum(row['receipt'] is not None for row in calls),
                'started_count': sum(row['status'] == 'started' for row in calls),
                'ambiguous_count': sum(row['status'] == 'ambiguous' for row in calls),
                'resolved_count': resolved_calls,
                'completed_count': sum(row['status'] == 'completed' for row in calls),
                'failed_count': sum(row['status'] == 'failed' for row in calls),
                'unresolved_count': unresolved_calls,
                'provider_invocation_count': None,
                'unobserved_graphs': unknown_graphs},
            'model_tokens': tokens,
            'call_seconds': call_seconds,
            'ordinary_stage_seconds': stage_seconds,
            'resource_vector': resources, **savings, 'method_choice_comparisons': comparisons,
            'avoidance_scope': 'Recorded counterfactual comparisons with evidence; not actual provider dispatch or measured benefit.',
            'native_calls': None, 'native_seconds': None, 'cost': {'actual': None, 'estimated': None, 'currency': None},
            'campaign_timing': deepcopy(state['timing']),
            'timing_scope': 'Call and stage durations are separate inclusive observations, never added together or called total campaign cost.'},
        'interventions': {'approval_observations': approvals, 'cycle_events': deepcopy(state['events']),
            'recorded_approval_counts': {label: sum(r['classification'] == label for r in approvals)
                for label in ('machine_scripted_assent', 'declared_physicist_mode')},
            'graph_events': graph_events, 'review_events': reviews,
            'send_back_events': sum(r.get('event') == 'review' and r.get('verdict') == 'send_back' for r in reviews),
            'correction_events': sum(r.get('event') == 'correction' for r in reviews),
            'human_interventions': None, 'physicist_interventions': None,
            'origin_scope': 'Actor labels and physicist approval mode do not authenticate a person; scripted_yes is machine assent.'},
        'utility': _utility(utility_declaration, state, evidence),
        'scientific_error_metrics': {'erroneous_acceptances': None, 'erroneous_refusals': None, 'correct_complete_physics_results': None,
            'reason': 'No independent outcome truth/effectiveness instrument supplied; acceptance, refusals and source controls are not truth labels.'},
        'execution_authorized': False, 'physics_validated': False, 'benefit_measured': False}
    evidence.finish()
    if rc._load(root)[1]['sha256'] != state['sha256']: raise ValueError('cycle changed during metrics readout')
    result['input_pins'] = [pin for pin, _ in evidence.files.values()]
    result['input_scope'] = 'Metrics records only; full cycle dependency custody is validated by research_cycle._load. These pins do not replace whole study/source review inventories.'
    if completion is not None:
        result['completion_input_pins'] = deepcopy(completion['input_pins'])
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_DOCUMENT_BYTES:
        raise ValueError('complete metrics readout exceeds16MiB; never truncate')
    return result


def readout(root, *, completion_request=None, utility_declaration=None):
    """Read exact cycle instrumentation without dispatch or another role call."""
    from . import research_cycle as rc, task_completion
    _, state = rc._load(root)
    completion = None
    if completion_request is not None:
        request = rc._read(completion_request, state['base_dir'])
        if state.get('parent_task') is None or request['contract'] != state['parent_task']['contract']:
            raise ValueError('metrics request must name exact original task')
        completion = task_completion.evaluate(completion_request, base_dir=state['base_dir'])
    return project(root, state, completion=completion, utility_declaration=utility_declaration)


def markdown(result):
    """Typed instrumentation companion, not a scientific performance score."""
    task = result['original_task']
    lines = ['## Research outcome instrumentation', '',
        'Recorded task state: ' + task['state'] + '. Independent physics correctness: unknown.',
        'Original obligation denominator: ' + str(task['original_obligation_denominator']) + '.', '',
        '| Experiment | Recorded outcome | Independent correctness |', '|---|---|---|']
    for row in result['complete_experiment_census']:
        lines.append('| ' + row['id'] + ' | ' + row['state'] + ' | unknown |')
    calls = result['resource_use']['calls']
    complete = 'unknown' if calls['complete_count'] is None else str(calls['complete_count'])
    lines.extend(['', 'Debited Graph call records observed: ' + str(calls['debited_count']) + '.',
        'Resolved outcome receipts observed: ' + str(calls['observed_count']) + '; complete resolved-outcome count: ' + complete + '.',
        'Started records: ' + str(calls['started_count']) + '; ambiguous records: ' + str(calls['ambiguous_count']) + '.',
        'Actual provider invocation count: unknown. Reservations and outcome receipts do not establish provider dispatch.',
        'Token/time coverage and ceilings are retained in the typed JSON; missing values remain unknown.',
        'Actual/estimated cost, human/physicist intervention counts and scientific error rates remain unknown.',
        'Utility: ' + ('undeclared' if result['utility'] is None else 'explicit criteria retained; value unmeasured') + '.', ''])
    from .cost_records import render, resource_vector
    # A record written before the vector existed observed no dimension: unknown, never zero.
    vector = result['resource_use'].get('resource_vector')
    lines.extend(['Whole-campaign resources:', render({'cost_class': 'campaign', 'status': 'unknown',
        'resource_vector': resource_vector() if vector is None else vector})])
    for key in ('avoided_native_launches', 'avoided_model_calls'):
        value = result['resource_use'].get(key)
        lines.append(key + ': ' + ('unknown' if value is None else str(value)) + ' (recorded comparison).')
    return '\n'.join(lines)


def write_report(root, output, *, completion_request=None, utility_declaration=None):
    """Materialize the readout from existing records, with source ending custody."""
    from . import research_cycle as rc
    result = readout(root, completion_request=completion_request, utility_declaration=utility_declaration)
    output = rc._ordinary(output)
    if output.exists(): raise ValueError('fresh metrics report output required')
    output.mkdir(parents=True)
    intended = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode()
    if len(intended) > MAX_DOCUMENT_BYTES: raise ValueError('final serialized metrics report exceeds16MiB; never truncate')
    state_io.atomic_json(output / 'research-outcomes.json', json.loads(intended))
    (output / 'research-outcomes.md').write_text(markdown(result))
    for pin in [*result['input_pins'], *result.get('completion_input_pins', [])]: rc._check_pin(pin, Path.cwd())
    if readout(root, completion_request=completion_request, utility_declaration=utility_declaration) != result:
        raise ValueError('metrics readout changed during report delivery')
    if (output / 'research-outcomes.json').read_bytes() != intended or (output / 'research-outcomes.md').read_text() != markdown(result):
        raise ValueError('metrics report changed before delivery; retain partial evidence')
    return {'kind': 'research-outcome-metrics-report', 'files': [str(output / 'research-outcomes.json'), str(output / 'research-outcomes.md')],
            'file_pins': [rc._pin(output / name) for name in ('research-outcomes.json', 'research-outcomes.md')],
            'metrics': result, 'physics_validated': False, 'execution_authorized': False}
