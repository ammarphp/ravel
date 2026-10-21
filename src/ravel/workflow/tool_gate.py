"""``ravel_gate``: one tool-call interceptor for every transport.

Every tool call ends in the worker's broker (``broker.Broker.call``): the in-graph loop
calls it in process, CLI workers reach it through the socket (``ravel work call``) or the
MCP face (``ravel work mcp``). The checks therefore live in two pieces, both from this
module, so the three paths produce the same broker receipt:

- ``broker_guard(tools, rundir=…)`` is installed through ``Broker(guards=…)``. After the
  broker's own stop, budget and allowlist checks it refuses any (action, args) pair that
  no toolbelt tool produces, and runs the decision gate for a consequential action (the
  broker action is looked up in the ``broker_actions`` of
  ``data/graphs/consequential_sinks.json``; the author never decides) on the digest of
  the exact arguments, immediately before execution. A refusal is a receipted broker
  reply; any gate error, including ``provider_inactive``, refuses.
- ``production_broker(...)`` is the one factory every real worker broker comes from: the
  CLI worker supervisor (``agent_worker.supervise``) and the host-subagent broker
  (``host_subagent.serve_broker``). It builds the run's source-bound knowledge broker,
  allowlists exactly the toolbelt's actions, narrows knowledge to the toolbelt's ops and
  installs ``broker_guard``. No production broker exists without the guard.
- ``ravel_gate(request, execute)`` is the in-graph ``wrap_tool_call``. Before any counter
  it looks the call's domain path (``…/tool:<tool call id>``) up in the effect ledger: a
  completed receipt is returned only when the saved tool, action and argument digest
  equal the new call's and its broker receipt still verifies; a changed call raises
  ``NondeterministicRequest``. A started or ambiguous one raises ``Ambiguous``.
  Otherwise the call runs once through ``effect_ledger.call`` and the broker. A tool name
  outside the toolbelt is sent as ``tool:<name>``, so the broker refuses it with a receipt.

Tool output is returned as data in a ``ToolMessage``; no router or gate reads it.
Broker refusal codes beyond the broker interface: ``gate_refused`` and ``provider_inactive``.
"""
from __future__ import annotations

from copy import deepcopy
import json

from ravel.paths import package_data_path

from . import effect_ledger, toolbelt

SINKS = ('graphs', 'consequential_sinks.json')


def consequential_gates(action, *, sinks=None):
    """Gates a broker action (or a sink qualname) must pass, from the consequential-sink list
    (§21.2 item 13). A row names the broker actions that reach its sink in ``broker_actions``."""
    rows = sinks if sinks is not None else json.loads(package_data_path(*SINKS).read_text())['sinks']
    gates = []
    for row in rows:
        if row['sink'] == action or action in row.get('broker_actions', ()):
            gates.extend(g for g in row['gates'] if g not in gates)
    return gates


def broker_guard(tools, *, rundir, graph_id=None, sinks=None):
    """The broker-side half of ``ravel_gate``: toolbelt membership, then consequential gates."""
    tools = deepcopy(list(tools))

    def guard(action, args, workspace):
        tool = toolbelt.match(tools, action, args)
        if tool is None:
            return {'code': 'not_allowlisted',
                    'message': f'action {action!r} with these arguments is outside the card toolbelt'}
        gates = consequential_gates(action, sinks=sinks)
        if not gates:
            return None
        from .graph_nodes import check_gate
        subject = {'kind': action, 'digest': effect_ledger.digest({'action': action, 'args': args}),
                   'summary': tool['name'], 'pins': []}
        errors = []
        for gate in gates:
            errors.extend(check_gate(rundir, gate, subject, graph_id=graph_id))
        if errors:
            code = 'provider_inactive' if any(e.get('code') == 'provider_inactive' for e in errors) else 'gate_refused'
            record = {'tool_name': tool['name'], 'atlas_id': tool['atlas_id'], 'gates': gates,
                      'action_digest': subject['digest'], 'errors': errors}
            return {'code': code, 'message': json.dumps(record, sort_keys=True)}
        return None
    guard.__name__ = 'ravel_gate_broker_guard'
    return guard


def production_broker(rundir, workspace, *, tools, role, node_id, attempt, max_calls, graph_id=None,
                      forbidden_sources=(), actor_id=None, season=None, atlas_path=None, retrieval=None, review_packet=None):
    """The broker a real worker talks to, with the shared gate installed.

    ``tools`` is the pinned toolbelt. The allowlist is exactly its actions, every one of
    which must have a registered handler; knowledge is narrowed to its ops; and
    ``broker_guard`` refuses any call no tool produces. ``retrieval`` is the trusted
    literature serving configuration from installation settings, or None.
    """
    from .knowledge_broker import create
    tools = deepcopy(list(tools))
    allowed = toolbelt.allowed_actions(tools)
    made = create(rundir, workspace, role=role, atlas_path=atlas_path, node_id=node_id, attempt=attempt,
                  allowed_actions=allowed, max_calls=max_calls, forbidden_sources=list(forbidden_sources),
                  actor_id=actor_id, season=season, may_query=toolbelt.knowledge_ops(tools),
                  guards=[broker_guard(tools, rundir=rundir, graph_id=graph_id)], retrieval=retrieval)
    if toolbelt.CHECK_ACTION in allowed:
        from . import review_projection_checks, role_registry
        review_projection_checks.register(made, role_registry.load(role))
    if toolbelt.REVIEW_ACTION in allowed:
        toolbelt.register_review_reader(made, review_packet)
    unregistered = [a for a in allowed if a not in made.actions]
    if unregistered:
        raise toolbelt.ToolbeltError(f'toolbelt actions without a broker handler: {unregistered}')
    return made


def call_id(path):
    """A broker call id bound to the domain path: a replay after a resume reuses it."""
    return 'g' + effect_ledger.digest(path)[:40]


def verify_receipted_reply(rundir, reply):
    """A saved broker reply must be the reply of a broker receipt that still verifies in custody."""
    from . import broker
    wanted = reply.get('receipt_id') if type(reply) is dict else None
    for row in broker.ledger(rundir, 'broker') if type(wanted) is str else ():
        record = row['record']
        if not wanted.startswith(f"{record['node_id']}/{record['attempt']}/"):
            continue
        receipt = broker.verify_broker_receipt(rundir, {'path': record['path'], 'sha256': record['sha256']},
                                               verify_outputs=False)
        if receipt['receipt_id'] == wanted:
            if receipt['reply'] != reply:
                break
            return receipt
    raise effect_ledger.NondeterministicRequest('saved tool reply has no matching broker receipt in custody')


def _tool_call(request):
    call = request.tool_call if hasattr(request, 'tool_call') else request['tool_call']
    if type(call) is not dict or type(call.get('name')) is not str or type(call.get('id')) is not str:
        raise ValueError('a tool call has a name and an id')
    return call


class Gate:
    """The in-graph interceptor for one worker turn sequence.

    ``broker_call(request) -> reply`` is the in-process broker client (``Broker.call``).
    ``prefix`` is the agent node's domain path; each call keys ``<prefix>/tool:<id>``.
    ``rundir`` (the worker's run) lets a replay re-verify its broker receipt in custody.
    """

    def __init__(self, tools, *, scope_root, graph, prefix, broker_call, provisioning=None, rundir=None,
                 literature_output=None):
        self.tools = list(tools)
        self.names = toolbelt.by_name(self.tools)
        self.scope_root, self.graph, self.prefix = scope_root, dict(graph), prefix
        self.broker_call = broker_call
        self.literature_output = literature_output
        bound_workspace = getattr(getattr(broker_call, '__self__', None), 'workspace', None)
        if (self.literature_output is None and bound_workspace is not None
                and any(t['executes_through']['action'] == 'literature query' for t in self.tools)):
            from . import broker, literature_mcp
            bound_run = getattr(getattr(broker_call, '__self__', None), 'rundir', None)
            logical_workspace = broker.logical(bound_run, bound_workspace) if bound_run is not None else None
            self.literature_output = literature_mcp.projector(bound_workspace,
                                                             logical_workspace=logical_workspace)
        self.provisioning = dict(provisioning or {})
        self.provisioning.setdefault('toolbelt_manifest_sha256', effect_ledger.digest(self.tools))
        self.verify_reply = (lambda reply: verify_receipted_reply(rundir, reply)) if rundir is not None else None

    def path(self, call):
        return f"{self.prefix}/tool:{call['id']}"

    def call(self, request):
        """Run one tool call through the ledger and the broker; return the broker reply."""
        call = _tool_call(request)
        where = self.path(call)
        broker_request = toolbelt.to_request(self.tools, call['name'], call.get('args', {}), call_id(where))
        identity = {'kind': 'tool', 'tool': call['name'], 'action': broker_request['action'],
                    'args_sha256': effect_ledger.digest(broker_request['args'])}
        saved = effect_ledger.latest(self.scope_root, where)
        if saved is not None and saved['status'] == 'completed':
            # Step 0: a replay never reaches a counter, a budget or the repeat detector,
            # and only the same call, with its receipt intact, is a replay.
            if saved['identity_sha256'] != effect_ledger.digest({**identity, 'kind': 'external'}):
                raise effect_ledger.NondeterministicRequest(
                    'tool call id reused with a different tool or arguments', saved['call_id'])
            if effect_ledger.digest(saved['result']) != saved.get('result_sha256'):
                raise effect_ledger.NondeterministicRequest('saved tool result changed', saved['call_id'])
            if self.verify_reply is not None:
                self.verify_reply(deepcopy(saved['result']))
            return deepcopy(saved['result'])
        if saved is not None and saved['status'] in effect_ledger.OPEN:
            raise effect_ledger.Ambiguous('tool call started without a receipted outcome; reconcile it',
                                          saved['call_id'])
        return effect_ledger.call(self.scope_root, graph=self.graph, path=where, kind='external',
                                  identity=identity, provisioning=self.provisioning,
                                  function=lambda: self.broker_call(broker_request))

    def message(self, request, reply):
        call = _tool_call(request)
        tool = self.names.get(call['name'])
        artifact = {'receipt_id': reply.get('receipt_id'), 'status': reply.get('status'), 'tool_name': call['name'],
                    'atlas_id': tool['atlas_id'] if tool else None}
        content = json.dumps(reply, sort_keys=True)
        failed = reply.get('status') != 'ok'
        route = tool['executes_through'] if tool is not None else {}
        if self.literature_output is not None and route.get('action') == 'literature query':
            projection = self.literature_output(reply, route['fixed_args']['op'])
            content = [{'type': 'text', 'text': content}, *projection['content']]
            failed = failed or projection['isError']
        try:
            from langchain_core.messages import ToolMessage
        except ImportError:  # the gate itself has no LangChain dependency
            return {'type': 'tool', 'tool_call_id': call['id'], 'name': call['name'], 'content': content,
                    'status': 'error' if failed else 'success', 'artifact': artifact}
        return ToolMessage(content=content, tool_call_id=call['id'], name=call['name'], artifact=artifact,
                           status='error' if failed else 'success')

    def __call__(self, request, execute=None):
        """``ToolNode(..., wrap_tool_call=gate)``. Tools execute only through the broker, so
        ``execute`` (ToolNode's own tool runner) is never called."""
        return self.message(request, self.call(request))


def ravel_gate(tools, **options):
    """Build the ``wrap_tool_call`` interceptor (see ``Gate``)."""
    return Gate(tools, **options)


def langchain_tools(tools):
    """StructuredTool stubs that carry each tool's name, description and schema for
    ``bind_tools``; calling one directly is refused because only ``ravel_gate`` executes."""
    from langchain_core.tools import StructuredTool
    result = []
    for tool in tools:
        def refuse(**_):
            raise RuntimeError('toolbelt tools execute only through ravel_gate and the broker')
        result.append(StructuredTool.from_function(func=refuse, name=tool['name'], description=tool['description'],
                                                   args_schema=tool['args_schema'], infer_schema=False))
    return result
