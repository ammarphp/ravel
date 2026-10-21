"""Materialisation (CONTROLLER-SPEC 7.2): instantiate the catalogue rows that apply at a stage.

Contexts (JSON values; unknown keys are pinned by the context digest but not interpreted):

- ``intake``: ``run_id`` (required), ``task_mode``, ``route``, ``deliverables`` (the reading's original obligations).
- ``plan``: ``plan`` (``plan.v1``: ``steps``, ``deliverables``, ``waypoints``, ``obligations``, ``sha256``), ``route``
  (route id or ``judgment``), ``task_mode``. Each replan materialises a new revision.
- ``dispatch`` and ``review``: ``step``, ``seat`` (the seat id; the role unless ``role`` is given), ``attempt`` (1, 2,
  ...: a retry is a new attempt), ``seat_kind`` (``worker``, ``launch``, ``review``, ...), ``review_kind``
  (``critic``, ``rdj``, ``final``, ``repair``, ...), ``point`` (scan point), ``step_kind`` (for a controller step that
  is not a plan step).
- ``deliver``: ``artifacts`` (delivered artifact ids), ``claims``.
- ``event``: ``kind`` (a check-in or decision-gate name such as ``deviation``), ``id`` (unique per occurrence),
  ``step``, ``role`` (the role of the seat an ``escalation`` occurred at: a row that selects a role is instantiated
  only for that role).

A selector whose fact is absent from the context keeps its row: unknown applicability stays on result paths.
Obligations a plan or step declares are added whatever their selector says; nothing a plan declares removes one.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
import re

from . import chain
from .catalogue import Catalogue
from .chain import LedgerError
from .state import State, instance_key

LAUNCH_KINDS = ('operate', 'acquire')
RESEARCH_GRAPH = 'research.loop'
SITE_ROUTE = 'study.site'
STEP_DOCUMENT = 'docs/workflow/steps/%s.md'
IDENT = re.compile(r'^[^\x00-\x1f\x7f]{1,200}$')
SEAT_STAGES = ('dispatch', 'review')


def _ident(value, what: str) -> str:
    if not isinstance(value, str) or not IDENT.match(value) or value != value.strip():
        raise LedgerError('context_invalid', f'{what} must be a non-empty single-line string, not {value!r}')
    return value


def _optional(value, what: str):
    return None if value is None else _ident(value, what)


def _idents(values, what: str) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise LedgerError('context_invalid', f'{what} must be a list')
    result = []
    for value in values:
        _ident(value, what)
        if value in result:
            raise LedgerError('context_invalid', f'{what} {value!r} is repeated')
        result.append(value)
    return result


def _source(path: str) -> str:
    path = path.split('#', 1)[0].strip()
    return path[2:] if path.startswith('./') else path


# ---- contexts ------------------------------------------------------------------------------------------------

def intake_context(context: dict) -> dict:
    deliverables = context.get('deliverables')
    return {
        'run_id': _ident(context.get('run_id'), 'run_id'),
        'task_mode': _optional(context.get('task_mode'), 'task_mode'),
        'route': _optional(context.get('route'), 'route'),
        'deliverables': None if deliverables is None else _idents(deliverables, 'deliverable'),
    }


def _step(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise LedgerError('context_invalid', f'plan step {index} is not an object')
    sources = raw.get('instruction_sources')
    seats = raw.get('seats')
    step = {
        'id': _ident(raw.get('id'), f'plan step {index} id'),
        'kind': _optional(raw.get('kind'), 'step kind'),
        'role': _optional(raw.get('role'), 'step role'),
        'operation': _optional(raw.get('operation'), 'step operation'),
        'mode': _optional(raw.get('mode'), 'step mode'),
        'route': _optional(raw.get('route'), 'step route'),
        'graph': _optional(_graph_id(raw.get('graph') or raw.get('subgraph')), 'step graph'),
        'stage': _optional(raw.get('stage'), 'step research stage'),
        'stages': _idents(raw.get('stages') or [], 'step research stage'),
        'workflow_step': _optional(raw.get('workflow_step'), 'step workflow step'),
        'rung': _optional(raw.get('rung'), 'step rung'),
        'depends_on': _idents(raw.get('depends_on') or [], 'step dependency'),
        'waypoint': raw.get('waypoint') is True,
        'points': _idents(raw.get('points') or [], 'scan point'),
        'sources': None if sources is None else sorted({_source(_ident(s, 'instruction source')) for s in sources}),
        'launch': raw.get('launch') if type(raw.get('launch')) is bool else None,
        'wms': raw.get('wms') if type(raw.get('wms')) is bool else None,
        'gates': _idents(raw.get('gates') or [], 'step gate'),
        'obligations': _idents(raw.get('obligations') or [], 'step obligation'),
        'deliverables': _idents(raw.get('deliverables') or [], 'step deliverable'),
    }
    if seats is not None:
        normal = []
        for item in seats if isinstance(seats, list) else [None]:
            if isinstance(item, str):
                item = {'seat': item}
            if not isinstance(item, dict):
                raise LedgerError('context_invalid', f'step {step["id"]} has an invalid seat')
            seat = _ident(item.get('seat'), 'seat')
            normal.append({'seat': seat, 'role': _optional(item.get('role'), 'seat role') or role_of(seat),
                           'kind': _optional(item.get('kind'), 'seat kind')})
        step['seats'] = normal
    else:
        derived = []
        if step['role']:
            derived.append({'seat': step['role'], 'role': step['role'], 'kind': 'producer'})
        for role in raw.get('review') or []:
            _ident(role, 'review seat')
            count = sum(1 for s in derived if s['role'] == role)
            derived.append({'seat': role if count == 0 else f'{role}#{count + 1}', 'role': role, 'kind': 'review'})
        step['seats'] = derived
    if len({s['seat'] for s in step['seats']}) != len(step['seats']):
        raise LedgerError('context_invalid', f'step {step["id"]} repeats a seat')
    return step


def role_of(seat: str) -> str:
    return seat.split('#', 1)[0]


def _graph_id(value):
    return value.get('id') if isinstance(value, dict) else value


def _route_id(value):
    return value.get('id') if isinstance(value, dict) else value


def _deliverables(raw, step_ids: set) -> list[dict]:
    if raw is None:
        return []
    items = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            items.append({'id': name, 'steps': value} if not isinstance(value, dict) else {'id': name, **value})
    elif isinstance(raw, list):
        items = [{'id': item} if isinstance(item, str) else item for item in raw]
    else:
        raise LedgerError('context_invalid', 'plan deliverables must be a list or an object')
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise LedgerError('context_invalid', 'a plan deliverable is not an object')
        name = _ident(item.get('id'), 'deliverable')
        if name in seen:
            raise LedgerError('context_invalid', f'deliverable {name} is mapped twice')
        seen.add(name)
        steps = item.get('steps')
        if steps is None and item.get('step') is not None:
            steps = [item['step']]
        if steps is None and isinstance(item.get('outputs'), list):
            steps = sorted({o.get('step') for o in item['outputs'] if isinstance(o, dict) and o.get('step')})
        steps = _idents(steps or [], 'deliverable step')
        unknown = [s for s in steps if s not in step_ids]
        if unknown:
            raise LedgerError('context_invalid', f'deliverable {name} maps to unknown steps {unknown}')
        kept_open = item.get('open') is True or item.get('status') == 'open'
        result.append({'id': name, 'steps': [] if kept_open else steps, 'open': kept_open or not steps})
    return result


def plan_context(context: dict, state: State) -> dict:
    """The plan (``context['plan']``, or the context itself when it carries the plan's fields)."""
    plan = context.get('plan') if isinstance(context.get('plan'), dict) else context
    if not isinstance(plan.get('steps'), list):
        raise LedgerError('context_invalid', 'the plan stage needs a plan with a steps list')
    steps = [_step(raw, i) for i, raw in enumerate(plan['steps'])]
    ids = [s['id'] for s in steps]
    if len(set(ids)) != len(ids):
        raise LedgerError('context_invalid', 'plan step ids are not unique')
    waypoints = set(_idents(plan.get('waypoints') or [], 'waypoint'))
    if waypoints - set(ids):
        raise LedgerError('context_invalid', f'waypoints {sorted(waypoints - set(ids))} are not plan steps')
    for step in steps:
        step['waypoint'] = step['waypoint'] or step['id'] in waypoints
        missing = [d for d in step['depends_on'] if d not in ids]
        if missing:
            raise LedgerError('context_invalid', f'step {step["id"]} depends on unknown steps {missing}')
    intake = state.intake or {}
    deliverables = _deliverables(plan.get('deliverables'), set(ids))
    declared = {d['id'] for d in deliverables}
    extra = {}
    for step in steps:  # a deliverable only a step names is mapped to that step; the plan's own list prevails
        for name in step['deliverables']:
            if name not in declared:
                extra.setdefault(name, []).append(step['id'])
    deliverables.extend({'id': name, 'steps': mapped, 'open': False} for name, mapped in extra.items())
    sources = plan.get('instruction_sources')
    sha = plan.get('sha256') if isinstance(plan.get('sha256'), str) else context.get('plan_sha256')
    return {
        'route': _optional(_route_id(context.get('route') or plan.get('route')) or intake.get('route'), 'route'),
        'task_mode': _optional(context.get('task_mode') or plan.get('task_mode') or intake.get('task_mode'),
                               'task_mode'),
        'plan_sha256': sha if isinstance(sha, str) else chain.digest(plan),
        'steps': steps,
        'deliverables': deliverables,
        'obligations': _idents(plan.get('obligations') or [], 'plan obligation'),
        'sources': None if sources is None else sorted({_source(_ident(s, 'instruction source')) for s in sources}),
        'open_obligations': _open_obligations(plan.get('open_obligations')),
    }


def _open_obligations(raw) -> list[dict]:
    """Obligations the plan keeps open (an unmapped deliverable, an unstated required parameter)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise LedgerError('context_invalid', 'open obligations must be a list')
    result = []
    for item in raw:
        if not isinstance(item, dict):
            raise LedgerError('context_invalid', 'an open obligation is an object')
        result.append({'kind': _ident(item.get('kind') or 'obligation', 'open obligation kind'),
                       'id': _ident(item.get('id'), 'open obligation id'),
                       'reason': item.get('reason') if isinstance(item.get('reason'), str) else None})
    return result


def seat_context(context: dict, stage: str) -> dict:
    attempt = context.get('attempt')
    if type(attempt) is not int or attempt < 1:
        raise LedgerError('context_invalid', 'a seat attempt must be an integer of at least 1')
    seat = _ident(context.get('seat'), 'seat')
    seat_kind = _optional(context.get('seat_kind'), 'seat kind')
    if stage == 'review' and seat_kind is None:
        seat_kind = 'review'
    return {
        'step': _ident(context.get('step'), 'step'),
        'seat': seat,
        'role': _optional(context.get('role'), 'seat role') or role_of(seat),
        'attempt': attempt,
        'seat_kind': seat_kind,
        'review_kind': _optional(context.get('review_kind'), 'review kind') if stage == 'review' else None,
        'point': _optional(context.get('point'), 'scan point'),
        'step_kind': _optional(context.get('step_kind'), 'step kind'),
    }


def deliver_context(context: dict) -> dict:
    return {'artifacts': _idents(context.get('artifacts') or [], 'artifact'),
            'claims': _idents(context.get('claims') or [], 'claim')}


def event_context(context: dict) -> dict:
    result = {'kind': _ident(context.get('kind'), 'event kind'), 'id': _ident(context.get('id'), 'event id'),
              'step': _optional(context.get('step'), 'event step')}
    if context.get('role') is not None:
        result['role'] = _ident(context['role'], 'event role')
    return result


def normalise(stage: str, context, state: State) -> dict:
    if not isinstance(context, dict):
        raise LedgerError('context_invalid', 'a materialisation context must be an object')
    if stage == 'intake':
        return intake_context(context)
    if stage == 'plan':
        return plan_context(context, state)
    if stage in SEAT_STAGES:
        return seat_context(context, stage)
    if stage == 'deliver':
        return deliver_context(context)
    if stage == 'event':
        return event_context(context)
    raise LedgerError('stage_unknown', f'unknown materialisation stage {stage!r}')


# ---- selectors -----------------------------------------------------------------------------------------------

def _all(values):
    """AND over True/False/None: any False is False, otherwise any None is None."""
    values = list(values)
    if any(v is False for v in values):
        return False
    return None if any(v is None for v in values) else True


def _any(values):
    values = list(values)
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def _document(step: dict, document: str):
    if step['workflow_step'] and STEP_DOCUMENT % step['workflow_step'] == document:
        return True
    if step['sources'] is None:
        return None
    return document in step['sources']


def _facts_value(key: str, value, facts: dict):
    step = facts.get('step')
    steps = facts.get('steps')
    if key in ('checkin', 'gate'):
        return True
    if key == 'route':
        route = facts.get('route')
        return None if route is None else route in value
    if key == 'task_mode':
        mode = facts.get('task_mode')
        return None if mode is None else mode == value
    if key == 'has_step_kind':
        if steps is None:
            return None
        if any(s['kind'] == value for s in steps):
            return True
        return None if any(s['kind'] is None for s in steps) else False
    if key == 'seat_kind':
        kind = facts.get('seat_kind')
        return None if kind is None else kind in value
    if key == 'review_kind':
        if facts.get('stage') != 'review':
            return False
        kind = facts.get('review_kind')
        return None if kind is None else kind in value
    if key == 'role':
        role = facts.get('role') if facts.get('stage') in SEAT_STAGES else (step or {}).get('role')
        return role == value
    if key == 'document':
        if step is not None:
            return _document(step, value)
        plan_sources = facts.get('sources')
        if plan_sources is not None and value in plan_sources:
            return True
        if steps is None:
            return None
        found = _any(_document(s, value) for s in steps)
        return None if found is False and plan_sources is None and not steps else found
    if key == 'wms':
        if step is not None and step.get('wms') is not None:
            return step['wms'] == value
        if facts.get('route') == SITE_ROUTE:
            return value is True
        return None if facts.get('route') is None else value is False
    if step is None:
        kind = facts.get('step_kind')
        if key == 'step_kind' and kind is not None:
            return kind in value
        return None
    if key == 'operation':
        return step['operation'] == value
    if key == 'mode':
        return value in (step['mode'], step['operation'])
    if key == 'workflow_step':
        return _document(step, STEP_DOCUMENT % value)
    if key == 'research_stage':
        return step['stage'] == value or value in step['stages'] or step['graph'] == RESEARCH_GRAPH
    if key == 'step_kind':
        return None if step['kind'] is None else step['kind'] in value
    if key == 'points':
        return bool(step['points']) is value
    if key == 'launches':
        if step['launch'] is not None:
            return step['launch'] is value
        if step['kind'] is None:
            return None
        return (step['kind'] in LAUNCH_KINDS) is value
    if key == 'rung':
        return None if step['rung'] is None else step['rung'] in value
    raise LedgerError('catalogue_invalid', f'selector {key} has no evaluator')


def applies(select, facts: dict):
    return _all(_facts_value(key, value, facts) for key, value in (select or {}).items())


def _declared(catalogue: Catalogue, names) -> list[str]:
    """Catalogue ids named by exact id or glob pattern; a name that matches nothing is refused."""
    result = []
    for name in names:
        if name in catalogue.rows:
            matched = [name]
        else:
            matched = [rid for rid in catalogue.order if fnmatchcase(rid, name)] if any(c in name for c in '*?[') else []
        if not matched:
            raise LedgerError('obligation_unknown', f'declared obligation {name!r} is not in the catalogue')
        result.extend(r for r in matched if r not in result)
    return result


def _route_step_scopes(select, plan: dict) -> list[dict]:
    routes = (select or {}).get('route')
    if not routes:
        return []
    return [{'step': s['id']} for s in plan['steps'] if s['kind'] == 'route' and s['route'] in routes]


def select(catalogue: Catalogue, stage: str, context: dict, state: State) -> list[tuple[str, dict]]:
    """(row id, scope) pairs in catalogue order."""
    chosen: list[tuple[str, dict]] = []

    def add(rid, scope):
        pair = (rid, scope)
        if pair not in chosen:
            chosen.append(pair)

    if stage == 'intake':
        facts = {'stage': stage, 'task_mode': context['task_mode'], 'route': context['route']}
        for rid in catalogue.by_stage['intake']:
            row = catalogue.rows[rid]
            app = row['applicability']
            if app['scope'] == 'run':
                if applies(app.get('select'), facts) is not False:
                    add(rid, {})
            else:
                for deliverable in context['deliverables'] or []:
                    add(rid, {'deliverable': deliverable})
        return chosen

    if stage == 'plan':
        steps = context['steps']
        base = {'stage': stage, 'task_mode': context['task_mode'], 'route': context['route'], 'steps': steps,
                'sources': context['sources']}
        plan_declared = set(_declared(catalogue, context['obligations']))
        step_declared = {s['id']: set(_declared(catalogue, s['obligations'])) for s in steps}
        for rid in catalogue.by_stage['plan']:
            row = catalogue.rows[rid]
            app = row['applicability']
            scope, sel = app['scope'], app.get('select')
            if scope == 'run':
                if rid in plan_declared or applies(sel, base) is not False:
                    add(rid, {})
                for extra in _route_step_scopes(sel, context):
                    add(rid, extra)
                for step in steps:
                    if rid in step_declared[step['id']]:
                        add(rid, {})
                continue
            for step in steps:
                if scope == 'waypoint' and not step['waypoint']:
                    continue
                declared = rid in plan_declared or rid in step_declared[step['id']]
                if not declared and applies(sel, {**base, 'step': step}) is False:
                    continue
                if scope == 'point':
                    for point in step['points']:
                        add(rid, {'step': step['id'], 'point': point})
                else:
                    add(rid, {'step': step['id']})
        for step in steps:  # decisions a step declares: event gates bound to the step
            for gate in step['gates']:
                rid = f'GATE-{gate}'
                if rid not in catalogue.rows:
                    raise LedgerError('obligation_unknown', f'step {step["id"]} declares unknown gate {gate!r}')
                if catalogue.rows[rid]['applicability']['stage'] == 'event':
                    add(rid, {'step': step['id'], 'event': gate})
        # intake rows a plan declares (a route spec that names a task route the reading did not)
        for rid in sorted(plan_declared | set().union(*step_declared.values()) if steps else plan_declared):
            app = catalogue.rows[rid]['applicability']
            if app['stage'] == 'intake' and app['scope'] == 'run':
                add(rid, {})
        for rid in catalogue.by_stage['intake']:  # every deliverable the plan names is conserved
            if catalogue.rows[rid]['applicability']['scope'] != 'deliverable':
                continue
            for deliverable in context['deliverables']:
                add(rid, {'deliverable': deliverable['id']})
        return chosen

    plan = state.plan or {'steps': None, 'route': None, 'task_mode': None, 'obligations': []}
    if stage in SEAT_STAGES:
        step = state.step(context['step'])
        facts = {'stage': stage, 'route': plan.get('route'), 'task_mode': plan.get('task_mode'),
                 'steps': plan.get('steps'), 'sources': plan.get('sources'), 'step': step, 'role': context['role'],
                 'seat_kind': context['seat_kind'], 'review_kind': context['review_kind'],
                 'step_kind': context['step_kind'] or ('review' if stage == 'review' and step is None else None)}
        declared = set(_declared(catalogue, list(plan.get('obligations') or []) + list((step or {}).get('obligations') or [])))
        scope = {'step': context['step'], 'point': context['point'], 'seat': context['seat'],
                 'attempt': context['attempt']}
        scope = {k: v for k, v in scope.items() if v is not None}
        stages = ('seat', 'review') if stage == 'review' else ('seat',)
        for name in stages:
            for rid in catalogue.by_stage[name]:
                sel = catalogue.rows[rid]['applicability'].get('select')
                if rid in declared or applies(sel, facts) is not False:
                    add(rid, dict(scope))
        return chosen

    if stage == 'deliver':
        facts = {'stage': stage, 'route': plan.get('route'), 'task_mode': plan.get('task_mode'),
                 'steps': plan.get('steps'), 'sources': plan.get('sources')}
        declared = set(_declared(catalogue, plan.get('obligations') or []))
        for rid in catalogue.by_stage['deliver']:
            app = catalogue.rows[rid]['applicability']
            if rid not in declared and applies(app.get('select'), facts) is False:
                continue
            if app['scope'] == 'run':
                add(rid, {})
            else:
                for artifact in context['artifacts']:
                    add(rid, {'artifact': artifact})
        return chosen

    # event
    for rid in catalogue.by_stage['event']:
        sel = catalogue.rows[rid]['applicability'].get('select') or {}
        if context['kind'] in (sel.get('checkin'), sel.get('gate')) and sel.get('role') in (None, context.get('role')):
            add(rid, {'event': context['id']})
    if not chosen:
        raise LedgerError('event_unknown', f'no obligation is instantiated by an event of kind {context["kind"]!r}')
    return chosen


def instances(catalogue: Catalogue, run_id: str, pairs) -> list[dict]:
    return [{'key': instance_key(rid, run_id, scope), 'id': rid, 'scope': scope} for rid, scope in pairs]
