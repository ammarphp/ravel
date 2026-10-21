"""Controller-owned direct worker dispatch identities and conservative settlement."""
from copy import deepcopy
import math
from pathlib import Path

from . import spec
from .services import StepHold, digest, records

SESSION = 'subgraph-usage-session'
DISPATCH = 'subgraph-item-dispatch'
OBSERVATION = 'subgraph-item-observation'
SUMMARY = 'subgraph-usage-summary'


def binding(store, step, attempt):
    return {'run_id': store.run_id, 'step_id': step['id'], 'attempt': attempt,
            'step_sha256': spec.step_sha256(step)}


def measurement(store, step, attempt):
    """Read only protected summaries for this exact parent attempt and approved step."""
    expected = binding(store, step, attempt)
    rows = [r for r in records(store, SUMMARY) if r.get('binding') == expected]
    return (deepcopy(rows[-1]['measured']), rows[-1]['_record_id']) if rows else (None, None)


def _number(value, *, integer=False):
    return (type(value) is int if integer else type(value) in (int, float)) and math.isfinite(value) and value >= 0


class Tracker:
    """The graph records exact item specs before dispatch; workers cannot write these rows."""

    def __init__(self, store, step, attempt, root):
        self.store = store
        self.binding = binding(store, step, attempt)
        self.root = Path(root)
        self.graph = deepcopy(step['graph'])
        row = {'binding': self.binding, 'root': str(self.root), 'graph': deepcopy(step['graph'])}
        previous = [r for r in records(store, SESSION) if r.get('binding') == self.binding]
        if previous:
            if any(previous[-1].get(k) != v for k, v in row.items()):
                raise StepHold('subgraph_usage_identity_changed', 'the direct workers keep their parent binding')
            self.session = previous[-1]['_record_id']
        else:
            self.session = store.append(SESSION, row)

    def record(self, descriptors):
        from ravel.workflow import agent_worker, broker, graph_registry
        allowed = graph_registry.get(self.graph['id'])
        graphs = [{'id': allowed['id'], 'version': allowed['version']}, *allowed['subgraphs']]
        for descriptor in descriptors:
            worker = agent_worker._validate(descriptor['spec'])
            if descriptor['graph'] not in graphs or not worker['parent'].get('review_subject'):
                raise StepHold('subgraph_usage_identity_changed', 'only declared subject-bound item graphs dispatch')
            row = {'session': self.session, 'binding': self.binding, 'worker': worker,
                   'graph': deepcopy(descriptor['graph']),
                   'identity_sha256': broker.digest({'worker_spec_sha256': broker.digest(worker), 'kind': 'worker'}),
                   'request_sha256': broker.digest({k: worker[k] for k in ('role', 'work_order', 'inputs', 'budgets')})}
            previous = [r for r in records(self.store, DISPATCH) if r.get('session') == self.session
                        and r['worker']['node_id'] == worker['node_id'] and r['worker']['attempt'] == worker['attempt']]
            if previous:
                if any(previous[-1].get(k) != v for k, v in row.items()):
                    raise StepHold('subgraph_usage_identity_changed', 'a dispatched item cannot change its identity')
            else:
                if any(r.get('session') == self.session for r in records(self.store, SUMMARY)):
                    raise StepHold('subgraph_usage_closed', 'settled item populations cannot grow')
                self.store.append(DISPATCH, row)

    def finish(self, *, completed):
        from ravel.workflow import agent_worker, broker
        previous = [r for r in records(self.store, SUMMARY) if r.get('session') == self.session]
        if previous:
            return previous[-1]['_record_id']
        dispatched = [r for r in records(self.store, DISPATCH) if r.get('session') == self.session]
        # Without a completed census or any recorded dispatch, retain the whole parent reservation.
        if not completed and not dispatched:
            return None
        totals = {'wall_seconds': 0, 'model_calls': 0, 'tokens': 0, 'cost_usd': 0,
                  'core_hours': 0, 'events': 0, 'children': len(dispatched)}
        observations = []
        for row in dispatched:
            worker = row['worker']
            ceilings = worker['budgets']
            amounts = {'wall_seconds': ceilings['max_wall_seconds'], 'model_calls': ceilings['max_turns'],
                       'tokens': None, 'cost_usd': ceilings['max_cost_usd']}
            receipt_sha, fallback = None, list(amounts)
            try:
                receipt = agent_worker.load_receipt(self.root, worker['node_id'], worker['attempt'])
                expected = {'node_id': worker['node_id'], 'attempt': worker['attempt'], 'role': worker['role'],
                            'graph': row['graph'], 'review_point_id': worker['parent']['review_point_id'],
                            'review_subject': worker['parent']['review_subject'],
                            'identity_sha256': row['identity_sha256'], 'request_sha256': row['request_sha256']}
                if any(receipt.get(k) != v for k, v in expected.items()):
                    raise ValueError('receipt belongs to another dispatch or review subject')
                receipt_sha = broker.digest(receipt)
                if receipt['status'] not in ('ok', 'failed', 'refused', 'voided'):
                    raise ValueError('an unresolved worker keeps its full declared ceiling')
                if _number(receipt.get('wall_seconds')):
                    amounts['wall_seconds'] = receipt['wall_seconds']
                    fallback.remove('wall_seconds')
                usage = receipt.get('usage')
                if type(usage) is not dict:
                    usage = {}
                if usage.get('reported') is True:
                    if _number(usage.get('turns'), integer=True):
                        amounts['model_calls'] = usage['turns']
                        fallback.remove('model_calls')
                    if all(_number(usage.get(k), integer=True) for k in ('input_tokens', 'output_tokens')):
                        amounts['tokens'] = usage['input_tokens'] + usage['output_tokens']
                        fallback.remove('tokens')
                    if _number(usage.get('cost_usd')):
                        amounts['cost_usd'] = usage['cost_usd']
                        fallback.remove('cost_usd')
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Missing, foreign or tampered receipts cannot refund a declared item ceiling.
            observation = self.store.append(OBSERVATION, {
                'session': self.session, 'binding': self.binding, 'dispatch': row['_record_id'],
                'receipt_sha256': receipt_sha, 'charged': amounts, 'fallback': fallback})
            observations.append(observation)
            for dimension, value in amounts.items():
                totals[dimension] = None if value is None or totals[dimension] is None else totals[dimension] + value
        return self.store.append(SUMMARY, {'session': self.session, 'binding': self.binding,
            'completed': completed, 'dispatches': [r['_record_id'] for r in dispatched],
            'observations': observations, 'measured': totals})
