"""Controller-only capture of compiler and reading evidence, independent of a request view.

P01 captures a new snapshot after committing a plan/reading transition and before asking
for authority. Workers cannot sign snapshots. request() never captures its own input.
"""
from copy import deepcopy
from collections.abc import Mapping
from . import common

KIND = 'authority-context'
SCHEMA = 'authority-context.v1'


def view_items(plan, reading):
    """Canonical check-in items, preserving compiler objects and the reading's extra items."""
    if not isinstance(plan, Mapping) or not isinstance(reading, Mapping):
        raise common.AuthorityRefused('retained check-in needs compiler and reading records')
    items = reading.get('items', {})
    if not isinstance(items, Mapping):
        raise common.AuthorityRefused('reading items must be a mapping')
    result = deepcopy(dict(items))
    for key in ('ambiguities', 'questions', 'assumptions'):
        if key not in result and key in reading:
            result[key] = deepcopy(reading[key])
    for key in ('steps', 'deliverables', 'boundaries'):
        fallback = reading.get('boundaries', result.get(key, [])) if key == 'boundaries' else []
        result[key] = deepcopy(plan.get(key, fallback))
    return result


def capture(store, kind, *, plan, reading, view):
    kind = common.kind_of(kind)
    if type(plan) is not dict or type(reading) is not dict:
        raise common.AuthorityRefused('retained check-in needs compiler and reading records')
    if not {'request_pins', 'inferred_critical_facts', 'flags'} <= reading.keys():
        raise common.AuthorityRefused('reading must explicitly disclose request comparisons and inferred facts')
    if kind == 'approve_plan' and (not plan.get('steps') or not plan.get('deliverables')):
        raise common.AuthorityRefused('a retained plan requires steps and deliverables')
    from .mode import frozen
    requested = frozen(store).get('request_pins', {})
    if type(requested) is not dict:
        raise common.AuthorityRefused('the frozen request pins are malformed')
    planned = plan.get('request_pins', {})
    if not set(requested) <= set(planned):
        raise common.AuthorityRefused('the retained plan omits frozen request pins')
    reading = deepcopy(reading)
    reading['request_pins'].update({k: {'requested': v, 'planned': planned[k]}
                                    for k, v in requested.items()})
    expected = deepcopy(view)
    if 'plan_sha256' in expected['pins'] and expected['pins']['plan_sha256'] != plan.get('sha256'):
        raise common.AuthorityRefused('view does not bind the retained plan')
    expected['items'] = view_items(plan, reading)
    expected['flags'] = deepcopy(reading['flags'])
    value = {'kind': kind, 'view': expected, 'plan': deepcopy(plan), 'reading': deepcopy(reading)}
    rows = common.scan(store, KIND, SCHEMA)
    previous = next((r for r in reversed(rows) if r['kind'] == kind), None)
    if previous is not None and all(previous[k] == v for k, v in value.items()):
        return previous
    return common.append(store, KIND, {'schema': SCHEMA, 'uid': common.uid(), 'run_id': common.run_id(store),
                                       **value})


def current(store, kind):
    row = next((r for r in reversed(common.scan(store, KIND, SCHEMA)) if r['kind'] == kind), None)
    if row is None:
        raise common.AuthorityRefused('no authenticated retained plan and reading for this check-in')
    return row
