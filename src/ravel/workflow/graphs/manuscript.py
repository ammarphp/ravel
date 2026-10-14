"""Manuscript sequencing with ordinary workers, computed disclosure and CI3.

Existing manuscript_workflow/manuscript_production bodies remain the phase
producers and consumers. The research loop binds prepared specs through Services; the
integrity auditor and meta-reviewer never acquire gate authority from prose.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from .. import completion_disclosure, graph_nodes as nodes, graph_substrate as substrate
from .. import procedure_export
from ...validation import evidence_card
from . import literature as shared

GRAPH = 'manuscript.build'
SECTION = 'manuscript.section'
ACTIVE = ContextVar('manuscript_graph_services', default=None)


@dataclass(frozen=True)
class Services:
    """Original phase/campaign seam, supplied by the manuscript owner or the research loop.

    consume_worker must delegate to the current phase/author/integrity consumers.
    integrity_action/final_action return ordinary exact action bytes and pins.
    record_pin is the current complete scientific record presented to the auditor.
    The code builds disclosure and exports the procedure; callbacks cannot supply
    either computed result. No callback replaces a registered gate provider.
    """
    epoch: str
    worker_spec: Callable
    consume_worker: Callable
    sections: Callable
    integrity_action: Callable
    final_action: Callable
    record_pin: Callable


@contextmanager
def services(value):
    if not evidence_card.SHA.fullmatch(value.epoch):
        raise ValueError('pinned manuscript integration service epoch required')
    token = ACTIVE.set(value)
    try:
        yield value
    finally:
        ACTIVE.reset(token)


def active():
    value = ACTIVE.get()
    if value is None:
        raise ValueError('manuscript graph requires original phase/campaign services (research-loop seam)')
    return value


class State(nodes.BaseState, total=False):
    work: Annotated[dict, nodes.write_once]
    request: dict
    sections: list
    section: dict
    record: dict
    disclosure: dict
    procedure: dict


class SectionView(TypedDict, total=False):
    meta: dict
    request: dict
    section: dict
    record: dict


def standard(builder, graph_id):
    nodes.add(builder, 'decision_turn', nodes.decision_turn('manuscript'), graph_id=graph_id)
    nodes.add(builder, 'reconcile', nodes.reconcile_node(), graph_id=graph_id)
    nodes.add(builder, 'hold', nodes.hold('manuscript_integrity_or_delivery_evidence_required'), graph_id=graph_id)
    return builder


def effect(name, run, *, to_state, kind='compute', gate=None):
    def identity(state):
        value = {'service_epoch': active().epoch, 'input_sha256': evidence_card.digest({
            k: v for k, v in state.items() if k in ('work', 'request', 'record', 'disclosure', 'procedure')})}
        if gate:
            action = active().integrity_action(state)
            value['action_bytes_sha256'] = action['digest']
        return value
    return nodes.effect(name, kind=kind, run=lambda state, ident: run(state),
               segment=lambda state: {'stage': name}, identity=identity, to_state=to_state,
               implementation=('ravel.workflow.graphs.manuscript', 'ravel.workflow.completion_disclosure',
                               'ravel.workflow.procedure_export') if kind in ('compute', 'check') else (), gate=gate)


def section(ctx):
    from langgraph.graph import StateGraph, START, END
    builder = standard(StateGraph(State, input_schema=SectionView), SECTION)
    nodes.add(builder, 'section', shared.agent('section', 'manuscript-writer', ctx,
                                              get_services=active,
                   project=lambda s, r: {'results': {'section': r}}), graph_id=SECTION)
    builder.add_edge(START, 'section'); builder.add_edge('section', END)
    return builder


def _sections(state):
    rows = active().sections(state)
    if type(rows) is not list or not rows or len(rows) > 32 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('complete finite unique manuscript section population required')
    return {'sections': deepcopy(rows)}


def _record(state):
    pin = active().record_pin(state)
    evidence_card._keys(pin, {'path', 'sha256', 'size'}, 'scientific record pin')
    from .. import report_integrity
    report_integrity._raw(pin, Path(state['meta']['scope_root']), {})
    return {'record': deepcopy(pin)}


def _disclosure(state):
    root = state['meta']['scope_root']
    return completion_disclosure.build(root) if completion_disclosure.required(root) else {
        'schema_version': 1, 'kind': 'research-disclosure-not-applicable',
        'reason': 'No bound research protocol; no research validation claim is supplied'}


def _procedure(state):
    return procedure_export.export_for_delivery(state['meta']['scope_root'])


def manuscript(ctx):
    from langgraph.graph import StateGraph, START, END
    builder = standard(StateGraph(State), GRAPH)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=GRAPH)
    add('story', shared.agent('story', 'manuscript-writer', ctx, get_services=active))
    add('sections', effect('sections', _sections, to_state=lambda s, r: r, kind='check'))
    child = substrate.build(SECTION, substrate.BuildContext(scope_root=ctx.scope_root,
                             graph_id=SECTION, version=1, instance=ctx.instance))
    edge, mapped = nodes.map_node(lambda s: s['sections'], lambda row: row['id'], child,
        lambda s, row: {'section': row, 'request': s.get('request', {})}, name='section_writes')
    add('section_writes', mapped)
    add('writer', shared.agent('writer', 'manuscript-writer', ctx, get_services=active))
    add('record', effect('record', _record, to_state=lambda s, r: r, kind='check'))
    add('integrity_auditor', shared.agent('integrity_auditor', 'integrity-auditor', ctx, get_services=active))
    add('meta_reviewer', shared.agent('meta_reviewer', 'research-meta-reviewer', ctx, get_services=active))
    add('report_integrity', nodes.gate('report_integrity', lambda s: active().integrity_action(s)))
    add('disclosure', effect('disclosure', _disclosure, to_state=lambda s, r: {'disclosure': r}, gate='report_integrity'))
    add('procedure_note', effect('procedure_note', _procedure, kind='external',
                                 to_state=lambda s, r: {'procedure': r}, gate='report_integrity'))
    add('checkin3', nodes.interrupt('checkin3_response', lambda s: {'record': s['record'],
                                   'disclosure': s['disclosure'], 'procedure': s['procedure']}))
    add('final_task', nodes.gate('final_task', lambda s: active().final_action(s)))
    builder.add_edge(START, 'story'); builder.add_edge('story', 'sections')
    nodes.connect(builder, 'sections', edge)
    builder.add_edge('section_writes', 'writer'); builder.add_edge('writer', 'record')
    builder.add_edge('record', 'integrity_auditor'); builder.add_edge('integrity_auditor', 'meta_reviewer')
    builder.add_edge('meta_reviewer', 'report_integrity')
    nodes.connect(builder, 'report_integrity', nodes.gate_route('report_integrity', passed='disclosure', refused='hold'))
    builder.add_edge('disclosure', 'procedure_note'); builder.add_edge('procedure_note', 'checkin3')
    builder.add_edge('checkin3', 'final_task')
    nodes.connect(builder, 'final_task', nodes.gate_route('final_task', passed=END, refused='hold'))
    return builder
