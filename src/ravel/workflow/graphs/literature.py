"""Literature scout sequencing on the substrate; domain services own custody.

The research loop supplies prepared worker specs and original-campaign acquisition bodies.
No callback is a gate provider. The knowledge broker owns source admission and receipts;
worker nodes use the ordinary governed dispatcher and downstream recovery.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from .. import agent_worker, broker as broker_core, graph_nodes as nodes, graph_substrate as substrate
from .. import literature as service
from ...validation import evidence_card

SCOUT = 'literature.scout'
SOURCE = 'literature.source'
ACTIVE = ContextVar('literature_graph_services', default=None)


@dataclass(frozen=True)
class Services:
    """Trusted integration seam; epoch pins the complete service implementation.

    worker_spec(role, state) -> ordinary agent-worker-spec
    consume_worker(role, receipt, state) -> current domain-consumed phase product
    source_items(state) -> complete explicitly admitted source requests
    acquire(state), extract(state), reextract(state) -> ordinary consumed products
    card_population(state) -> complete cards, including failed/speculative cards
    post(state, report) -> authenticated research-board post reference (never consensus)
    broker -> knowledge-broker SourceBoundBroker bound to the same run
    """
    epoch: str
    worker_spec: Callable
    consume_worker: Callable
    source_items: Callable
    acquire: Callable
    extract: Callable
    reextract: Callable
    card_population: Callable
    post: Callable
    broker: object


@contextmanager
def services(value):
    if not evidence_card.SHA.fullmatch(value.epoch):
        raise ValueError('pinned integration service epoch required')
    token = ACTIVE.set(value)
    try:
        yield value
    finally:
        ACTIVE.reset(token)


def active():
    value = ACTIVE.get()
    if value is None:
        raise ValueError('literature graph requires original-campaign domain services (research-loop seam)')
    return value


class State(nodes.BaseState, total=False):
    work: Annotated[dict, nodes.write_once]
    sources: list
    report: dict
    retried: bool
    request: dict


class SourceView(TypedDict, total=False):
    meta: dict
    source: dict
    request: dict


class SourceState(State, total=False):
    source: dict


def standard(builder, graph_id):
    nodes.add(builder, 'decision_turn', nodes.decision_turn('literature'), graph_id=graph_id)
    nodes.add(builder, 'reconcile', nodes.reconcile_node(), graph_id=graph_id)
    nodes.add(builder, 'hold', nodes.hold('literature_domain_evidence_required'), graph_id=graph_id)
    return builder


def identity(state):
    return {'service_epoch': active().epoch, 'input_sha256': evidence_card.digest({
        k: v for k, v in state.items() if k in ('work', 'source', 'sources', 'request', 'report', 'retried')})}


def effect(name, function, *, kind='external', to_state=None):
    return nodes.effect(name, kind=kind, run=lambda state, ident: function(state),
          segment=lambda state: {'stage': name, 'round': int(state.get('retried', False))}, identity=identity,
          to_state=to_state or (lambda state, result: {'work': {name: result}}),
          implementation=('ravel.workflow.graphs.literature', 'ravel.workflow.literature',
                          'ravel.validation.evidence_card') if kind in ('check', 'compute') else ())


def agent(name, role, ctx, *, get_services=active, project=None):
    def spec(state):
        if role == 'literature-scout':
            service.scout_tier()
        value = get_services().worker_spec(role, state)
        from .. import role_registry
        card = role_registry.load(role)
        expected = {'id': role, 'version': card['version'], 'card_sha256': role_registry.card_sha256(role)}
        if value['role'] != expected:
            raise ValueError('prepared worker must bind the current declared graph role card')
        if role == 'integrity-auditor' and not any(row['pin'] == state.get('record') for row in value['inputs']):
            raise ValueError('integrity auditor must receive the complete current record')
        return value

    def consume(state, receipt):
        current = agent_worker.load_receipt(ctx.scope_root, receipt['node_id'], receipt['attempt'])
        if current != receipt or current['status'] != 'ok':
            raise ValueError('actual current ordinary worker receipt required')
        if role == 'integrity-auditor':
            calls = [broker_core.verify_broker_receipt(ctx.scope_root,
                     {'path': row['record']['path'], 'sha256': row['record']['sha256']}, verify_outputs=False)
                     for row in broker_core.ledger(ctx.scope_root, 'broker')
                     if row['record']['node_id'] == receipt['node_id']
                     and row['record']['attempt'] == receipt['attempt']]
            if not any(call['status'] == 'ok' and call['action'] == 'read'
                       and any(pin['sha256'] == state['record']['sha256'] for pin in call['input_pins'])
                       for call in calls):
                raise ValueError('integrity auditor must actually read the complete record through the broker')
        product = get_services().consume_worker(role, current, state)
        return project(state, product) if project else {'work': {name: product}}

    node = nodes.agent(name, rundir=ctx.scope_root, spec=spec,
                       segment=lambda state: {'stage': name}, to_state=consume)
    node.kind, node.role = 'agent', role
    return node


def source(ctx):
    from langgraph.graph import StateGraph, START, END
    builder = standard(StateGraph(SourceState, input_schema=SourceView), SOURCE)
    nodes.add(builder, 'acquire', effect('acquire', lambda s: active().acquire(s),
        to_state=lambda s, r: {'work': {'acquire': r}, 'results': {'acquire': r}}), graph_id=SOURCE)
    nodes.add(builder, 'extract', effect('extract', lambda s: active().extract(s),
        to_state=lambda s, r: {'work': {'extract': r}, 'results': {'extract': r}}), graph_id=SOURCE)
    builder.add_edge(START, 'acquire'); builder.add_edge('acquire', 'extract'); builder.add_edge('extract', END)
    return builder


def _sources(state):
    items = active().source_items(state)
    if type(items) is not list or len(items) > 32 or len({item['id'] for item in items}) != len(items):
        raise ValueError('complete finite unique source population required')
    return {'sources': deepcopy(items)}


def _broker(state):
    tool = active().broker
    if Path(tool.rundir) != Path(state['meta']['scope_root']):
        raise ValueError('literature broker belongs to a different original run')
    return tool


def _check(state):
    report = service.check_cards(active().card_population(state), broker=_broker(state))
    return report


def _bad(state):
    return any(row['status'] != 'checked' for row in state['report']['census'])


def _retry(state):
    # Refused sources never trigger reacquisition or extraction; retain their receipts.
    bad = [row['id'] for row in state['report']['census'] if row.get('reason') == 'invalid_evidence']
    return active().reextract({**state, 'failed_card_ids': bad}) if bad else {'not_applicable': 'No extraction failures'}


def _post(state):
    # Re-derive once more immediately before a board consumer sees the selected cards.
    current = service.consume_cards(state['report'], active().card_population(state), broker=_broker(state))
    reference = active().post(state, current)
    if type(reference) is not dict or not reference:
        raise ValueError('actual authenticated board post reference required')
    return {'report': current, 'board': reference}


def scout(ctx):
    from langgraph.graph import StateGraph, START, END
    builder = standard(StateGraph(State), SCOUT)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=SCOUT)
    add('scout', agent('scout', 'literature-scout', ctx))
    add('sources', effect('sources', _sources, kind='check', to_state=lambda s, r: r))
    child = substrate.build(SOURCE, substrate.BuildContext(scope_root=ctx.scope_root,
                             graph_id=SOURCE, version=1, instance=ctx.instance))
    edge, mapped = nodes.map_node(lambda s: s['sources'], lambda item: item['id'], child,
        lambda s, item: {'source': item, 'request': s.get('request', {})}, name='source_reads')
    add('source_reads', mapped)
    add('cards', agent('cards', 'literature-scout', ctx))
    add('check_cards', effect('check_cards', _check, kind='check', to_state=lambda s, r: {'report': r}))
    add('reextract', effect('reextract', _retry, to_state=lambda s, r: {'work': {'reextract': r}, 'retried': True}))
    add('revised_cards', agent('revised_cards', 'literature-scout', ctx))
    post = effect('post', _post)
    post.kind = 'board'
    add('post', post)
    builder.add_edge(START, 'scout'); builder.add_edge('scout', 'sources')
    # Empty maps have no Send successor. Explicitly route the empty population.
    nodes.connect(builder, 'sources', nodes.route(lambda s: 'map' if s['sources'] else 'cards',
                   {'map': 'dispatch_sources', 'cards': 'cards'}))
    add('dispatch_sources', nodes.Node('guard', lambda s: {}))
    nodes.connect(builder, 'dispatch_sources', edge)
    builder.add_edge('source_reads', 'cards'); builder.add_edge('cards', 'check_cards')
    nodes.connect(builder, 'check_cards', nodes.route(
        lambda s: 'retry' if _bad(s) and not s.get('retried', False)
                  and any(r.get('reason') == 'invalid_evidence' for r in s['report']['census']) else 'post',
        {'retry': 'reextract', 'post': 'post'}))
    builder.add_edge('reextract', 'revised_cards'); builder.add_edge('revised_cards', 'check_cards')
    builder.add_edge('post', END)
    return builder
