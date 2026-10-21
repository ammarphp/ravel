"""Capability needs and the best available tool for each.

The packaged tool census (``data/backends/census.json``) is the tool registry. Its ``needs`` table names the
capability needs a plan can have; each tool row's ``serves`` entries say which need the tool serves, with a
preference (1 is best) and the plan forms through which a plan step uses it: the operations it runs or the
roles that run it. A need may add RAVEL's own methods as later candidates. The run's environment profile
(``environment-profile`` record) gives each tool's availability; a method is always available or needs a
supplied input of a kind.

A need arises for a plan from the request's derived task label or a request term (the need's ``triggers``), from
a requested tool that serves it, from a step that declares it, or from a step whose plan form is a candidate
that ``implies`` it. ``check`` judges a plan against the profile: each need that arises is served by a step
using its best available candidate, or the plan records a typed reason; a step never uses a candidate known
to be unavailable while another one is available. The result is the ``tool-selection`` record the
controller keeps and the problems a planner corrects. Nothing here authorizes or executes anything.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

SCHEMA = 'ravel-tool-selection.v1'
RECORD = 'tool-selection'
NEED = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
REASON_CODES = ('not_applicable',)                       # written by a planner, with a statement and evidence
DERIVED_REASONS = ('requested_tool', 'no_available_alternative')   # written by the controller from its records
EVIDENCE = re.compile(r'^(reading|step):([A-Za-z0-9][A-Za-z0-9_.:-]{0,127})$')
METHOD_AVAILABILITY = re.compile(r'^(always|supplied:[a-z][a-z0-9_-]{0,31})$')
EVIDENCE_STEP_KINDS = ('decide', 'ask')


class RegistryError(ValueError):
    """The census declares needs or plan forms the selection cannot use."""


def _strings(value):
    return type(value) is list and all(type(v) is str and v.strip() for v in value)


def registry(census=None):
    """``{need: {'summary', 'triggers', 'candidates': [...]}}`` with candidates in preference order.

    A candidate is ``{'id', 'kind': 'tool'|'method', 'title', 'preference', 'operations', 'roles', 'implies',
    'available', 'request_names'}``; ``available`` is ``'profile'`` for a tool. Refuses unknown needs, repeated
    preferences and candidates without a plan form.
    """
    if census is None:
        from .tool_census import census_bytes
        census = json.loads(census_bytes())
    needs = census.get('needs') or {}
    if type(needs) is not dict:
        raise RegistryError('census needs must be an object')
    out = {}
    for need, row in needs.items():
        if not NEED.match(str(need)) or type(row) is not dict or type(row.get('summary')) is not str:
            raise RegistryError(f'census need {need!r} needs an id and a summary')
        triggers = row.get('triggers') or {}
        if type(triggers) is not dict or set(triggers) - {'task_modes', 'terms'} or any(
                type(triggers.get(key, [])) is not list
                or any(type(v) is not str or not v.strip() for v in triggers.get(key, []))
                for key in ('task_modes', 'terms')):
            raise RegistryError(f'census need {need} has malformed triggers')
        for term in triggers.get('terms', []):
            if term.startswith('re:'):
                try:
                    re.compile(term[3:])
                except re.error as exc:
                    raise RegistryError(f'census need {need} has an invalid term {term!r}: {exc}') from None
        candidates = []
        for method in row.get('methods') or []:
            if (type(method) is not dict or type(method.get('id')) is not str
                    or not METHOD_AVAILABILITY.match(str(method.get('available')))):
                raise RegistryError(f'census need {need} has a malformed method')
            candidates.append({'id': method['id'], 'kind': 'method', 'title': method.get('title') or method['id'],
                               'preference': method.get('preference'), 'operations': list(method.get('operations') or []),
                               'roles': list(method.get('roles') or []), 'implies': False,
                               'available': method['available'], 'request_names': []})
        out[need] = {'summary': row['summary'], 'triggers': {'task_modes': list(triggers.get('task_modes') or []),
                                                             'terms': list(triggers.get('terms') or [])},
                     'candidates': candidates}
    for tool in census.get('tools') or []:
        for entry in tool.get('serves') or []:
            need = entry.get('need') if type(entry) is dict else None
            if need not in out:
                raise RegistryError(f'census tool {tool.get("id")} serves unknown need {need!r}')
            out[need]['candidates'].append({
                'id': tool['id'], 'kind': 'tool', 'title': tool.get('title') or tool['id'],
                'preference': entry.get('preference'), 'operations': list(entry.get('operations') or []),
                'roles': list(entry.get('roles') or []), 'implies': entry.get('implies') is True,
                'available': 'profile', 'request_names': list(tool.get('request_names') or [])})
    for need, row in out.items():
        seen = set()
        for candidate in row['candidates']:
            preference = candidate['preference']
            if type(preference) is not int or preference < 1 or preference in seen:
                raise RegistryError(f'need {need}: candidate {candidate["id"]} needs a distinct positive preference')
            seen.add(preference)
            forms = candidate['operations'] + candidate['roles']
            if not forms or not _strings(candidate['operations']) or not _strings(candidate['roles']):
                raise RegistryError(f'need {need}: candidate {candidate["id"]} names no operation or role')
        row['candidates'].sort(key=lambda c: c['preference'])
    return out


def registry_errors(needs, *, operations=None, roles=None):
    """Plan forms that name no registered operation or role (``operations``/``roles`` are the registered ids)."""
    problems = []
    for need, row in needs.items():
        for candidate in row['candidates']:
            for op in candidate['operations']:
                if operations is not None and op not in operations:
                    problems.append(f'need {need}: candidate {candidate["id"]} names unregistered operation {op}')
            for role in candidate['roles']:
                if roles is not None and role not in roles:
                    problems.append(f'need {need}: candidate {candidate["id"]} names unregistered role {role}')
    return problems


# ---- availability -------------------------------------------------------------------------------------

def _supplied_kinds(supplied):
    kinds = set()
    for row in supplied or ():
        if type(row) is dict and type(row.get('kind')) is str:
            kinds.add(row['kind'])
    return kinds


def candidate_status(candidate, profile, supplied=(), *, status=None):
    """``{'state': 'available'|'unavailable'|'unknown', 'reason': code|None}`` for one candidate.

    A tool's state comes from the profile (``environment_profile.tool_status``, or ``status(census_id)``);
    a tool the profile did not observe is ``unknown``, never ``unavailable``.
    """
    if candidate['kind'] == 'method':
        rule = candidate['available']
        if rule == 'always':
            return {'state': 'available', 'reason': None}
        kind = rule.split(':', 1)[1]
        if kind in _supplied_kinds(supplied):
            return {'state': 'available', 'reason': None}
        return {'state': 'unavailable', 'reason': 'requires_supplied_input:' + kind}
    if status is None:
        from ravel.setup.environment_profile import tool_status

        def status(census_id):
            return tool_status(profile or {}, census_id)
    found = status(candidate['id']) or {}
    if found.get('available') is True:
        return {'state': 'available', 'reason': None}
    reason = found.get('reason') or 'unobserved'
    return {'state': 'unknown' if reason == 'unobserved' else 'unavailable', 'reason': reason}


def _eligible(row):
    return row['state'] in ('available', 'unknown')


# ---- plans --------------------------------------------------------------------------------------------

def _step_view(step):
    """The selection-relevant fields of a judgment-plan step or a controller ``step.v1``."""
    if step.get('_view') is True:
        return step
    parameters = step.get('parameters') if type(step.get('parameters')) is dict else {}
    needs = step.get('needs') if 'needs' in step else parameters.get('needs')
    reasons = step.get('tool_reasons') if 'tool_reasons' in step else parameters.get('tool_reasons')
    return {'_view': True, 'id': step.get('id'), 'kind': step.get('kind'), 'operation': step.get('operation'),
            'role': step.get('role'), 'needs': [n for n in needs if type(n) is str] if type(needs) is list else [],
            'tool_reasons': reasons if type(reasons) is dict else {}}


def _plan_reasons(plan):
    if type(plan.get('tool_reasons')) is dict:
        return plan['tool_reasons']
    parameters = plan.get('parameters') if type(plan.get('parameters')) is dict else {}
    return parameters.get('tool_reasons') if type(parameters.get('tool_reasons')) is dict else {}


def uses(step, candidate):
    """Whether ``step`` uses ``candidate``: its operation or its role is one of the candidate's plan forms."""
    view = _step_view(step)
    return ((view['operation'] is not None and view['operation'] in candidate['operations'])
            or (view['role'] is not None and view['role'] in candidate['roles']))


def _term_hit(term, text):
    from .capability_routing import _term_pattern
    hit = _term_pattern(term).search(text or '')
    return hit.group(0) if hit else None


def _requested(reading):
    rows = []
    for row in (reading or {}).get('constraints') or ():
        if type(row) is dict and row.get('type') == 'requested_tool' and type(row.get('value')) is dict:
            name = row['value'].get('tool')
            if type(name) is str and name.strip():
                rows.append({'id': row.get('id'), 'tool': name})
    return rows


def _norm(name):
    return re.sub(r'[\s_-]+', '', str(name)).lower()


def _names_match(names, wanted):
    """Whether a requested tool name is one of a census row's request names."""
    for name in names:
        if name.startswith('re:'):
            try:
                if re.search(name[3:], str(wanted), re.I):
                    return True
            except re.error:
                continue
        elif _norm(name) == _norm(wanted):
            return True
    return False


def arising(needs, *, label=None, reading=None, request_text=None, steps=()):
    """``{need: [source, ...]}`` for every need that arises; a source names what raised it.

    ``label`` is the request's derived label (``derived_label.derive``, present for every reading), never a legacy
    contract key, so a request raises the same needs whatever contract schema accompanies it.
    """
    mode = label.get('task_mode') if type(label) is dict else None
    found = {}
    views = [_step_view(s) for s in steps if type(s) is dict]
    requested = _requested(reading)
    for need, row in needs.items():
        sources = []
        if type(mode) is str and mode in row['triggers']['task_modes']:
            sources.append({'from': 'derived_label', 'mode': mode})
        for term in row['triggers']['terms']:
            hit = _term_hit(term, request_text)
            if hit:
                sources.append({'from': 'request_term', 'text': hit[:200]})
                break
        for item in requested:
            for candidate in row['candidates']:
                if candidate['kind'] == 'tool' and _names_match(candidate['request_names'], item['tool']):
                    sources.append({'from': 'requested_tool', 'constraint': item['id'], 'tool': item['tool'],
                                    'candidate': candidate['id']})
        for view in views:
            if need in view['needs']:
                sources.append({'from': 'step_declares', 'step': view['id']})
            for candidate in row['candidates']:
                if candidate['implies'] and uses(view, candidate):
                    sources.append({'from': 'implied', 'step': view['id'], 'candidate': candidate['id']})
        if sources:
            found[need] = sources
    return found


def _reason_problems(where, need, reason, *, reading, steps):
    """Problems of a planner-written typed reason (``not_applicable`` with a statement and evidence)."""
    if type(reason) is not dict or reason.get('code') not in REASON_CODES:
        return [f'{where} tool_reasons[{need}] needs code not_applicable, a statement and evidence']
    problems = []
    if type(reason.get('statement')) is not str or len(reason['statement'].strip()) < 8:
        problems.append(f'{where} tool_reasons[{need}] states no reason')
    evidence = reason.get('evidence')
    if not _strings(evidence) or not evidence:
        problems.append(f'{where} tool_reasons[{need}] names no evidence (reading:<id> or step:<decide or ask id>)')
        return problems
    known = {row.get('id') for key in ('facts', 'constraints', 'deliverables', 'ambiguities')
             for row in (reading or {}).get(key) or () if type(row) is dict}
    kinds = {s['id']: s['kind'] for s in steps}
    for pointer in evidence:
        match = EVIDENCE.match(pointer)
        if match is None:
            problems.append(f'{where} tool_reasons[{need}] evidence {pointer!r} is not reading:<id> or step:<id>')
        elif match.group(1) == 'reading' and match.group(2) not in known:
            problems.append(f'{where} tool_reasons[{need}] evidence {pointer} names no item of the reading')
        elif match.group(1) == 'step' and kinds.get(match.group(2)) not in EVIDENCE_STEP_KINDS:
            problems.append(f'{where} tool_reasons[{need}] evidence {pointer} names no decide or ask step of the plan')
    return problems


def _forms(candidate):
    parts = []
    if candidate['operations']:
        parts.append('operation ' + '|'.join(candidate['operations']))
    if candidate['roles']:
        parts.append('role ' + '|'.join(candidate['roles']))
    return ' or '.join(parts)


def _label(candidate):
    return f'{candidate["title"]} ({candidate["kind"]} {candidate["id"]}, preference {candidate["preference"]})'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def ranked(row, profile, supplied=(), requested=(), *, status=None):
    """The need's candidates with their state; requested tools first among the eligible ones."""
    out = []
    asked = {s.get('candidate') for s in requested if s.get('from') == 'requested_tool'}
    for candidate in row['candidates']:
        state = candidate_status(candidate, profile, supplied, status=status)
        out.append({**{k: deepcopy(candidate[k]) for k in ('id', 'kind', 'title', 'preference', 'operations',
                                                            'roles', 'implies')},
                    'requested': candidate['id'] in asked, **state})
    eligible = [c for c in out if _eligible(c)]
    best = next((c for c in eligible if c['requested']), None) or (eligible[0] if eligible else None)
    return out, best


def check(plan, *, profile, supplied=(), label=None, reading=None, request_text=None, needs=None,
          status=None, profile_record=None):
    """``(record, problems)`` for ``plan`` (a judgment plan or a controller plan) under ``profile``."""
    needs = registry() if needs is None else needs
    steps = [_step_view(s) for s in (plan or {}).get('steps') or () if type(s) is dict]
    arisen = arising(needs, label=label, reading=reading, request_text=request_text, steps=steps)
    plan_reasons = _plan_reasons(plan or {})
    problems, rows = [], []
    for view in steps:
        for need in list(view['needs']) + list(view['tool_reasons']):
            if need not in needs:
                problems.append(f'step {view["id"]} names unknown capability need {need!r} '
                                f'(known: {", ".join(sorted(needs))})')
    for need in plan_reasons:
        if need not in needs:
            problems.append(f'the plan records a tool reason for unknown capability need {need!r}')
    for need, sources in arisen.items():
        row = needs[need]
        before = len(problems)
        candidates, best = ranked(row, profile, supplied, sources, status=status)
        by_id = {c['id']: c for c in candidates}
        serving = []
        for view in steps:
            used = [c for c in row['candidates'] if uses(view, c)]
            if not used:
                if need in view['needs']:
                    problems.append(f'step {view["id"]} declares need {need} but uses none of its candidates '
                                    f'({"; ".join(_forms(c) for c in row["candidates"])})')
                continue
            candidate = by_id[min(used, key=lambda c: c['preference'])['id']]
            entry = {'step': view['id'], 'candidate': candidate['id'], 'state': candidate['state'],
                     'best': best is not None and candidate['id'] == best['id'], 'reason': None}
            if candidate['state'] == 'unavailable':
                if best is None:
                    entry['reason'] = {'code': 'no_available_alternative',
                                       'statement': 'no candidate of this need is available on this host',
                                       'evidence': [f'profile:{profile_record}'] if profile_record else []}
                else:
                    problems.append(f'step {view["id"]} uses {_label(candidate)} for need {need}, unavailable here '
                                    f'({candidate["reason"]}), while {_label(best)} is available: plan it '
                                    f'({_forms(best)})')
            elif not entry['best']:
                if candidate['requested']:
                    entry['reason'] = {'code': 'requested_tool', 'statement': 'the request names this tool',
                                       'evidence': ['reading:' + str(s['constraint']) for s in sources
                                                    if s.get('candidate') == candidate['id']]}
                elif need in view['tool_reasons']:
                    found = _reason_problems(f'step {view["id"]}', need, view['tool_reasons'][need],
                                             reading=reading, steps=steps)
                    problems.extend(found)
                    if not found:
                        entry['reason'] = deepcopy(view['tool_reasons'][need])
            serving.append(entry)
        plan_reason = plan_reasons.get(need)
        eligible_lacking = [e['step'] for e in serving if e['state'] != 'unavailable' and not e['best']
                            and e['reason'] is None]
        if any(e['best'] for e in serving):
            status_value = 'served'
        elif best is None:
            status_value = 'no_available_candidate'
            if not serving:
                if plan_reason is None:
                    problems.append(f'need {need} ({row["summary"]}) arises ({_sources(sources)}) and no candidate '
                                    f'is available here ({_states(candidates)}): hold what it serves and record the '
                                    f"plan's tool_reasons[{need}] (code not_applicable, a statement and evidence)")
                else:
                    problems.extend(_reason_problems('the plan', need, plan_reason, reading=reading, steps=steps))
        elif serving and all(e['reason'] is not None for e in serving):
            status_value = 'served_with_reason'
        elif not serving and plan_reason is not None:
            found = _reason_problems('the plan', need, plan_reason, reading=reading, steps=steps)
            problems.extend(found)
            status_value = 'unserved' if found else 'reasoned'
        else:
            status_value = 'unserved'
            if eligible_lacking:
                problems.append(f'need {need} ({row["summary"]}) arises ({_sources(sources)}); step(s) '
                                f'{", ".join(eligible_lacking)} serve it with a lower-preference candidate while '
                                f'{_label(best)} is available: plan it ({_forms(best)}) or record '
                                f'tool_reasons[{need}] on the step (code not_applicable, a statement and evidence '
                                'reading:<id> or step:<decide or ask step id>)')
            elif not serving:
                problems.append(f'need {need} ({row["summary"]}) arises ({_sources(sources)}) and no step serves '
                                f'it: plan a step that uses {_label(best)} ({_forms(best)}) or record the plan\'s '
                                f'tool_reasons[{need}] (code not_applicable, a statement and evidence)')
        rows.append({'need': need, 'summary': row['summary'], 'arises': deepcopy(sources),
                     'candidates': candidates, 'best': best['id'] if best else None, 'served_by': serving,
                     'plan_reason': deepcopy(plan_reason) if plan_reason is not None else None,
                     'status': status_value, 'problems': problems[before:]})
    record = {'schema': SCHEMA, 'plan_sha256': (plan or {}).get('sha256'), 'profile_record': profile_record,
              'profile_sha256': _digest(profile) if profile is not None else None,
              'needs_sha256': _digest(needs), 'needs': rows, 'problems': list(problems), 'passed': not problems}
    return record, problems


def _sources(sources):
    out = []
    for s in sources:
        detail = s.get('mode') or s.get('text') or s.get('tool') or s.get('step') or ''
        out.append(f'{s["from"]} {detail}'.strip())
    return '; '.join(dict.fromkeys(out))


def _states(candidates):
    return '; '.join(f'{c["id"]}: {c["reason"] or c["state"]}' for c in candidates)


def planning_view(*, profile, supplied=(), label=None, reading=None, request_text=None, needs=None,
                  status=None):
    """What a planner sees: every need, whether it arises for this request, its ranked candidates with their
    state on this host and the best available one."""
    needs = registry() if needs is None else needs
    arisen = arising(needs, label=label, reading=reading, request_text=request_text)
    view = []
    for need, row in sorted(needs.items()):
        candidates, best = ranked(row, profile, supplied, arisen.get(need, ()), status=status)
        view.append({'need': need, 'summary': row['summary'], 'arises': deepcopy(arisen.get(need, [])),
                     'best': best['id'] if best else None,
                     'candidates': [{k: c[k] for k in ('id', 'kind', 'title', 'preference', 'operations', 'roles',
                                                       'state', 'reason', 'requested')} for c in candidates]})
    return {'schema': 'ravel-tool-planning-view.v1', 'needs': view,
            'rule': ('Each need that arises is served by a step using its best available candidate (the operation '
                     'or role shown), or a step or the plan records tool_reasons[need] = {code: not_applicable, '
                     'statement, evidence: [reading:<id> | step:<decide or ask step id>]}. Declare a step\'s needs '
                     'with needs: [...]. Never plan a candidate whose state is unavailable while another is '
                     'available.')}


def alternatives(record, need, *, exclude=()):
    """The other eligible candidates of ``need`` in a selection record, best first (for runtime recovery)."""
    for row in (record or {}).get('needs') or ():
        if row.get('need') == need:
            return [deepcopy(c) for c in row.get('candidates') or () if c.get('state') in ('available', 'unknown')
                    and c.get('id') not in set(exclude)]
    return []


def bound(record, step_id):
    """``[(need, candidate)]`` the selection bound to ``step_id``: the candidate each serving step uses."""
    out = []
    for row in (record or {}).get('needs') or ():
        by_id = {c['id']: c for c in row.get('candidates') or ()}
        for entry in row.get('served_by') or ():
            if entry.get('step') == step_id and entry.get('candidate') in by_id:
                out.append((row['need'], deepcopy(by_id[entry['candidate']])))
    return out
