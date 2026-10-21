"""Bind prepared descriptor contracts to exact declared analysis artifacts before CI1."""
from __future__ import annotations

from copy import deepcopy

from .. import compiler
from ..study import evidence
from ..study.contracts import relative
from . import common


def _artifact(value, by_id):
    if type(value) is not str:
        raise ValueError('scientific evidence names an exact declared artifact')
    producer, separator, path = value.partition(':')
    if not separator or producer not in by_id:
        raise ValueError('scientific evidence names a known producing step')
    relative(path)
    if path not in {row['path'] for row in by_id[producer].get('outputs') or ()}:
        raise ValueError('scientific evidence names a declared producer output')
    return producer


def _ancestors(step, by_id):
    pending, found = list(step.get('depends_on') or ()), set()
    while pending:
        identifier = pending.pop()
        if identifier in found:
            continue
        found.add(identifier)
        if identifier in by_id:
            pending.extend(by_id[identifier].get('depends_on') or ())
    return found


def bind(plan, source):
    """Admit source descriptor bindings without granting review or ledger authority.

    Preparation may add its own declared expected artifacts to a later step's
    inputs. Other expected artifacts must already be declared ancestor inputs.
    Observations remain that step's future declared outputs; runtime custody and
    the existing scientific validators still decide what their bytes establish.
    """
    supplied = source.get('scientific_bindings', {})
    if type(supplied) is not dict:
        raise ValueError('scientific_bindings is an object keyed by exact step id')
    changed = deepcopy(plan)
    by_id = {step['id']: step for step in changed['steps']}
    for identifier, bindings in supplied.items():
        step = by_id.get(identifier)
        if step is None or common.phase_of(step) == 'prepare':
            raise ValueError('scientific bindings name an exact nonpreparation step')
        if type(bindings) is not list:
            raise ValueError('scientific bindings for a step are a list')
        if any(type(row) is not dict or {'entry_ids', 'review'} & row.keys() for row in bindings):
            raise ValueError('source scientific bindings cannot supply ledger entry ids or review credit')
        parameters = step.setdefault('parameters', {})
        incoming = evidence.requirements({'parameters': {'evidence_requirements': deepcopy(bindings)}})
        combined = evidence.requirements(step)
        known = {row['row']: row for row in combined}
        for binding in incoming:
            previous = known.get(binding['row'])
            if previous is not None:
                if previous != binding:
                    raise ValueError('a scientific row cannot replace its existing approved binding')
                continue
            combined.append(binding)
            known[binding['row']] = binding
        parameters['evidence_requirements'] = combined
        for binding in evidence.requirements(step):
            if 'observed' in binding:
                if _artifact(binding['observed'], by_id) != identifier:
                    raise ValueError('scientific observed evidence must be the step own declared output')
            producer = _artifact(binding['expected'], by_id)
            if producer == identifier:
                raise ValueError('scientific expected evidence cannot be its own future output')
            inputs = step.setdefault('inputs', [])
            dependencies = step.setdefault('depends_on', [])
            if common.phase_of(by_id[producer]) == 'prepare':
                if not any(row.get('artifact') == binding['expected'] for row in inputs):
                    inputs.append({'artifact': binding['expected']})
                if producer not in dependencies:
                    dependencies.append(producer)
            elif (producer not in _ancestors(step, by_id)
                  or not any(row.get('artifact') == binding['expected'] for row in inputs)):
                raise ValueError('nonpreparation scientific evidence must already be a declared ancestor input')
    problems = compiler.check_dag(changed['steps'])
    if problems:
        raise ValueError('; '.join(problems))
    changed['sha256'] = common.digest({key: value for key, value in changed.items() if key != 'sha256'})
    return changed
