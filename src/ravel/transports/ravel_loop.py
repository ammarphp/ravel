"""Durable broker-backed agent loop, built only from the graph-substrate node factories.

Model and broker calls have independent domain effects. A checkpoint gap reuses
their committed outcomes; an unreceipted started call is held for reconciliation.
A run that pins a project instruction document gets no loop turn: the loop sends its
own provider request and cannot put the document ahead of it or record its delivery.
``build`` can be embedded as a subgraph; ``run`` supplies the standalone substrate
lifecycle for transport qualification. Neither confers scientific authority.
"""
from copy import deepcopy
import json
import re
from pathlib import Path
import time

from jsonschema import Draft202012Validator

from ravel.workflow import effect_ledger as ledger, graph_nodes as nodes, graph_substrate as substrate
from ravel.workflow.execution import file_hash
from ravel.workflow.langchain_guard import GuardError, local_context
from ravel.workflow.state_io import atomic_json, read_json


class LoopState(nodes.BaseState, total=False):
    messages: list[dict]
    turn: int
    steps: int
    broker_calls: int
    final: dict | None
    delivery: dict
    action_receipts: list[dict]
    turn_receipts: list[dict]
    loop_status: str
    stop_receipt: dict
    started_epoch: float


class RavelLoop:
    def __init__(self, scope_root, *, model, broker, budgets, final_schema, tools, instance,
                 parent_path=None, version=1, tool_actions=None):
        self.scope_root = Path(scope_root).absolute()
        self.model, self.broker = model, broker
        self.budgets, self.final_schema = deepcopy(budgets), deepcopy(final_schema)
        self.instance, self.parent_path, self.version = deepcopy(instance), parent_path, version
        required = {'max_turns', 'max_wall_seconds', 'max_broker_calls', 'max_cost_usd'}
        if set(budgets) - (required | {'max_steps'}) or not required <= budgets.keys():
            raise ValueError('complete finite worker budgets required')
        for key in ('max_turns', 'max_wall_seconds', 'max_broker_calls'):
            if type(budgets[key]) is not int or not 1 <= budgets[key] <= 100000:
                raise ValueError('positive finite budget required: ' + key)
        self.budgets.setdefault('max_steps', budgets['max_broker_calls'])
        if type(self.budgets['max_steps']) is not int or self.budgets['max_steps'] < 0:
            raise ValueError('finite step budget required')
        if budgets['max_cost_usd'] is not None:
            import math
            cap = budgets['max_cost_usd']
            if type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0:
                raise ValueError('positive cost cap required')
        Draft202012Validator.check_schema(final_schema)
        if tools is None:
            tools, tool_actions = broker_tools(broker)
        self.tools = deepcopy(tools)
        self.tool_actions = deepcopy(tool_actions or {t['name']: t['name'] for t in tools})
        if set(self.tool_actions) != {t['name'] for t in tools}:
            raise ValueError('each tool requires exactly one trusted broker action mapping')
        names = [t['name'] for t in self.tools]
        from ravel.workflow.provider_tools import NAME
        if len(set(names)) != len(names) or 'submit_final' in names or any(not NAME.fullmatch(n) for n in names):
            raise ValueError('distinct provider tool identifiers required')
        for t in self.tools:
            if set(t) != {'name', 'description', 'args_schema'}: raise ValueError('explicit tool schema required')
            Draft202012Validator.check_schema(t['args_schema'])
        self.tools.append({'name': 'submit_final', 'description': 'Submit the complete final public record',
                           'args_schema': deepcopy(final_schema)})
        self.prefix = ledger.path('ravel-loop', instance, parent_path, {'agent': 'loop'})
        self._identity = ledger.digest(self.identity)

    @property
    def identity(self):
        return {'model': self.model.identity, 'budgets': self.budgets, 'final_schema': self.final_schema,
                'implementation_sha256': file_hash(__file__),
                'tools': self.tools, 'tool_actions': self.tool_actions, 'instance': self.instance,
                'broker': {'node_id': self.broker.node_id, 'attempt': self.broker.attempt,
                    'allowed_actions': sorted(self.broker.allowed_actions)}}

    def _current(self):
        self.model.current()
        if ledger.digest(self.identity) != self._identity:
            raise GuardError('loop binding changed')

    def _undeclared(self):
        """Refuse a model turn in a run that pins a project instruction document; nothing is sent.

        Every session of such a run receives the document ahead of its instructions and records the
        delivery. The loop has neither step, so the declaration is read before each dispatch and a
        pinned run is refused. Workers of that run go through a CLI worker transport.
        """
        from ravel.workflow import project_instructions
        try:
            pinned = project_instructions.for_path(self.scope_root)
        except project_instructions.ProjectInstructionsError as exc:
            if not project_instructions.unsettled(exc):
                raise GuardError(str(exc)) from None
            pinned = True  # a directory above this scope pins a document
        if pinned is not None:
            raise GuardError('this run pins a project instruction document and the agent loop cannot deliver it; '
                             'no model request was sent. Run the worker through a CLI worker transport')

    def _path(self, turn, kind):
        return ledger.extend(self.prefix, {'turn': turn}) + '/' + kind

    def _call(self, turn, kind, identity, function, *, effect_kind, provisioning=None):
        self._current()
        request = {'loop_binding': self._identity, **identity}
        if effect_kind == 'check': request['implementation_sha256'] = file_hash(__file__)
        return ledger.call(self.scope_root, graph={'id': 'ravel-loop', 'version': self.version},
            path=self._path(turn, kind), kind=effect_kind, identity=request, provisioning=provisioning or {},
            function=function, revalidate=lambda receipt: self._current())

    def _pin(self, turn, kind):
        receipt = ledger.latest(self.scope_root, self._path(turn, kind))
        # The ledger appends reuse observations. Pin an immutable outcome artifact,
        # never the mutable receipt container; its call id links back to the ledger.
        rel = 'calls/evidence/loop-' + receipt['call_id'] + '.json'
        path = self.scope_root / rel
        value = {'call_id': receipt['call_id'], 'path': receipt['path'], 'status': receipt['status'],
                 'identity_sha256': receipt['identity_sha256'], 'result': receipt.get('result'),
                 'result_sha256': receipt.get('result_sha256')}
        if path.exists():
            if read_json(path) != value: raise GuardError('immutable loop receipt changed')
        else: atomic_json(path, value)
        return {'path': rel, 'sha256': file_hash(path)}

    def _revalidate_state(self, state):
        for saved in ledger.receipts(self.scope_root):
            if not saved['path'].startswith(self.prefix + '/'): continue
            if saved['status'] == 'completed':
                ledger._revalidate(self.scope_root, saved, lambda _: self._current())
        for i, delivery in enumerate(state.get('turn_receipts', [])):
            saved = ledger.latest(self.scope_root, self._path(i, 'model'))
            if saved is None or saved.get('result') != delivery:
                raise GuardError('checkpoint model receipt differs from ledger')
        for i, action in enumerate(state.get('action_receipts', [])):
            saved = ledger.latest(self.scope_root, self._path(i, 'action'))
            if saved is None or saved.get('result') != {k: v for k, v in action.items() if k != 'receipt'}:
                raise GuardError('checkpoint action receipt differs from ledger')
            pin = action['receipt']
            if self._pin(i, 'action') != pin: raise GuardError('checkpoint outcome pin changed')
        if state.get('final') is not None:
            if not state.get('action_receipts') or state['action_receipts'][-1]['final'] != state['final']:
                raise GuardError('checkpoint final has no action receipt')

    def _envelope(self, state):
        return {'messages': state['messages'], 'tools': self.tools,
                'tool_choice': 'submit_final' if state['steps'] >= self.budgets['max_steps'] else 'auto',
                'stream': self.model.stream_enabled}

    def _guard(self, state):
        self._current()
        reasons = []
        if state['turn'] >= self.budgets['max_turns']: reasons.append('max_turns')
        if time.time() - state['started_epoch'] >= self.budgets['max_wall_seconds']: reasons.append('max_wall_seconds')
        cap = self.budgets['max_cost_usd']
        if cap is not None:
            bound = self.model.max_cost_per_turn_usd
            costs = [r['usage'].get('cost_usd') for r in state['turn_receipts']]
            if bound is None: reasons.append('unpriced_transport')
            elif any(c is None for c in costs): reasons.append('unknown_cost')
            elif sum(costs) + bound > cap: reasons.append('max_cost_usd')
        if reasons:
            self._call(state['turn'], 'stop', {'reasons': reasons},
                       lambda: {'status': 'budget_exhausted', 'reasons': reasons}, effect_kind='check')
            return 'exhausted'
        return 'go'

    def _model(self, state):
        self._undeclared()
        envelope = self._envelope(state)
        from ravel.workflow.provider_tools import render
        wire_body = render(self.model.adapter, envelope, model=self.model.model,
            max_output_tokens=self.model.max_output_tokens, text_protocol=self.model.text_protocol,
            token_limit_field=self.model.token_limit_field)
        remaining = self.budgets['max_wall_seconds'] - (time.time() - state['started_epoch'])
        # Deadline is provisioning: checkpoint replay must not change turn equality.
        cap = self.budgets['max_cost_usd']
        spent = sum(r['usage'].get('cost_usd') or 0 for r in state['turn_receipts'])
        # The exact serialized request is kept with the effect before anything is sent, so a turn whose
        # sender fails after dispatch still has its prompt. It is recorded, never compared.
        kept = {'wire_request': json.dumps(wire_body, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                           allow_nan=False)}
        delivery = self._call(state['turn'], 'model', {'envelope': envelope, 'wire_request_sha256': ledger.digest(wire_body)},
            lambda: self.model.turn(envelope, timeout=max(.001, remaining),
                max_cost_usd=None if cap is None else min(cap - spent, self.model.max_cost_per_turn_usd)), effect_kind='model',
            provisioning=kept)
        return {'delivery': delivery, 'turn_receipts': state['turn_receipts'] + [deepcopy(delivery)]}

    def _action(self, state):
        turn, delivery = state['turn'], state['delivery']
        message = delivery['message']
        calls = message.get('tool_calls', []) if message else []
        code = (delivery['error'] or {}).get('code')
        final, reply = None, None
        call = calls[0] if len(calls) == 1 else None
        if code is None and len(calls) != 1: code = 'multiple_actions' if len(calls) > 1 else 'missing_action'
        schema = next((t['args_schema'] for t in self.tools if call and t['name'] == call['name']), None)
        if code is None and schema is None: code = 'unknown_tool'
        if code is None and list(Draft202012Validator(schema).iter_errors(call['args'])): code = 'schema_invalid'
        if code is None and time.time() - state['started_epoch'] >= self.budgets['max_wall_seconds']:
            code = 'budget_exhausted'
        cap = self.budgets['max_cost_usd']
        cost = delivery['usage'].get('cost_usd')
        if code is None and cap is not None and (cost is None or cost > self.model.max_cost_per_turn_usd):
            code = 'budget_exhausted'
        if code is None and call['name'] != 'submit_final':
            if state['steps'] >= self.budgets['max_steps']: code = 'budget_exhausted'
            elif state['broker_calls'] >= self.budgets['max_broker_calls']: code = 'budget_exhausted'
        if code is None and call['name'] == 'submit_final':
            final, code = deepcopy(call['args']), 'ok'
        elif code is None:
            request = {'call_id': ledger.digest({'path': self._path(turn, 'tool')}),
                       'action': self.tool_actions[call['name']], 'args': call['args']}
            reply = self._call(turn, 'tool', {'broker_request': request},
                               lambda: self.broker.call(request), effect_kind='external')
            code = 'ok' if reply['status'] == 'ok' else reply['error']['code']
        record = {'code': code, 'action': call['name'] if call else None, 'reply': reply,
                  'status': 'ok' if code == 'ok' else 'refused', 'final': final}
        self._call(turn, 'action', {'delivery_sha256': ledger.digest(delivery)}, lambda: record, effect_kind='check')
        pin = self._pin(turn, 'action')
        public = {**record, 'receipt': pin}
        messages = deepcopy(state['messages'])
        if message and calls:
            messages.append(message)
            messages.extend({'role': 'tool', 'name': c['name'], 'tool_call_id': c['id'],
                             'content': json.dumps(public)} for c in calls)
        else:
            messages.append({'role': 'user', 'content': 'Protocol refusal: ' + json.dumps(public)})
        return {'turn': turn + 1, 'steps': state['steps'] + 1, 'messages': messages,
                'broker_calls': state['broker_calls'] + (1 if reply is not None else 0),
                'final': final, 'loop_status': 'completed' if final is not None else 'running',
                'action_receipts': state['action_receipts'] + [public]}

    def builder(self):
        """Graph-substrate registry factory surface, with its own error routes."""
        from langgraph.graph import StateGraph, START, END
        builder = StateGraph(LoopState)
        nodes.add(builder, 'guard', nodes.guard(self._guard, routes={'go': 'model', 'exhausted': 'stop'}), graph_id='ravel-loop')
        nodes.add(builder, 'model', nodes.Node('effect', self._model, then='action'), graph_id='ravel-loop')
        route = nodes.route(lambda s: 'end' if s.get('final') is not None else 'again', {'end': END, 'again': 'guard'})
        nodes.add(builder, 'action', nodes.Node('effect', self._action, then=route), graph_id='ravel-loop')
        def stopped(state):
            return {'loop_status': 'budget_exhausted', 'stop_receipt': self._pin(state['turn'], 'stop')}
        nodes.add(builder, 'stop', nodes.Node('guard', stopped, then=END), graph_id='ravel-loop')
        nodes.add(builder, 'decision_turn', nodes.decision_turn('ravel-loop'), graph_id='ravel-loop')
        nodes.add(builder, 'reconcile', nodes.reconcile_node(), graph_id='ravel-loop')
        nodes.add(builder, 'hold', nodes.hold('effect_reconciliation_required'), graph_id='ravel-loop')
        builder.add_edge(START, 'guard')
        return builder

    def build(self, *, checkpointer=None):
        """An embeddable compiled substrate subgraph."""
        return substrate.finish(self.builder(), 'ravel-loop', checkpointer=checkpointer)

    def run(self, prompt):
        """Standalone invocation; repeated calls consume the same ledger/checkpoint."""
        local_context()  # refuse ambient tracing before substrate.environment resets it
        self._current()
        self._undeclared()
        binding = ledger.digest({'loop': self._identity, 'prompt': prompt})
        with substrate.scope_runner(self.scope_root, 'ravel-loop', binding), substrate.saver(self.scope_root) as saver:
            ledger.recover(self.scope_root)
            begun = self._call(-1, 'start', {'prompt': prompt}, lambda: {'epoch': time.time()}, effect_kind='check')
            app = self.build(checkpointer=saver)
            config = {'configurable': {'thread_id': binding}, 'recursion_limit': 4 * self.budgets['max_turns'] + 12}
            old = app.get_state(config)
            if old.created_at: self._revalidate_state(old.values)
            initial = {'meta': {'graph_id': 'ravel-loop', 'version': self.version, 'instance': self.instance,
                'scope_root': str(self.scope_root), 'path': self.parent_path}, 'messages': [{'role': 'user', 'content': prompt}],
                'turn': 0, 'steps': 0, 'broker_calls': 0, 'started_epoch': begun['epoch'], 'final': None,
                'action_receipts': [], 'turn_receipts': [], 'loop_status': 'running'}
            app.invoke(None if old.created_at else initial, config, durability='sync')
            state = app.get_state(config).values
            self._current()
            self._revalidate_state(state)
            status = state.get('loop_status', 'running')
            if state.get('failures'):
                latest = next(reversed(state['failures'].values()))
                status = 'ambiguous' if latest['failure_kind'] == 'ambiguous_effect' else 'refused'
                # The terminal error channel never grants a new turn or replay.
                if any(r['status'] in ledger.OPEN for r in ledger.receipts(self.scope_root)): status = 'ambiguous'
            turns = deepcopy(state.get('turn_receipts', []))
            for saved in ledger.receipts(self.scope_root):
                if saved['path'].startswith(self.prefix + '/') and saved['path'].endswith('/model') and saved['status'] in ledger.OPEN:
                    turns.append({'model_effect': saved['call_id'], 'effect_status': saved['status'],
                        'request_sha256': saved['identity']['wire_request_sha256'], 'response_sha256': None,
                        'provider_usage': None, 'http_status': None, 'message': None,
                        'error': {'code': 'ambiguous', 'message': 'sent effect lacks a complete outcome'}})
            return {'final': deepcopy(state.get('final')), 'status': status, 'steps': state.get('steps', 0),
                    'action_receipts': deepcopy(state.get('action_receipts', [])),
                    'turn_receipts': turns,
                    'stop_receipt': deepcopy(state.get('stop_receipt')), 'framework_values_are_scientific_authority': False}


def build(ctx):
    """Consumer seam: the tool gate and the broker supply ``ctx.extras['ravel_loop']``."""
    loop = ctx.extras['ravel_loop']
    if (Path(ctx.scope_root).absolute() != loop.scope_root or ctx.graph_id != 'ravel-loop'
            or ctx.version != loop.version or ctx.instance != loop.instance):
        raise GuardError('substrate context differs from the exact loop binding')
    return loop.builder()


def broker_tools(broker):
    """Temporary tool-gate seam: trusted registered action list, with safe wire names.

    The generic args object makes no statement about an action's scientific
    inputs. The registered broker handler retains its own full validation.
    Callers with typed tool-gate schemas should supply those schemas explicitly.
    """
    tools, mapping = [], {}
    for action in sorted(set(broker.actions) & set(broker.allowed_actions)):
        name = re.sub(r'[^A-Za-z0-9_]', '_', action)
        if not name or name[0].isdigit(): name = 'tool_' + name
        if len(name) > 64 or name in mapping or name == 'submit_final':
            raise ValueError('broker actions need distinct provider-safe tool names')
        mapping[name] = action
        tools.append({'name': name, 'description': 'Broker action: ' + action, 'args_schema': {'type': 'object'}})
    return tools, mapping
