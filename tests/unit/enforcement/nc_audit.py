"""Compare the declared coverage population with pytest's actual collected items.

Declarations establish case availability, not successful execution or scientific validity.
The collector checks identities before any case starts; runtime reporting keeps blocked cases
separate from completed cases. Explicit selections may run a subset without claiming full coverage.
"""
from __future__ import annotations

from collections import Counter


def expected_pairs(document):
    """Every declared (coverage row, test function) pair, including parameterized rows."""
    pairs = {(row['id'], row['test']) for row in document['bespoke'] if row['status'] == 'implemented'}
    for row, gid in document['parameterized'].items():
        group = document['groups'][gid]
        if group['status'] == 'implemented':
            pairs.update((row, test) for test in group['tests'])
    return pairs


def collection_errors(items, document, *, installed_rows=None, complete_files=True):
    """Refuse unknown, repeated, misbound or omitted collected cases.

    ``installed_rows`` comes from the effective registries, independently of the bindings file.
    ``complete_files`` is false for explicit node, keyword or marker selections; individual item
    validation and installed-population equality still hold in those selections.
    """
    errors = []
    if installed_rows is not None:
        installed_rows = set(installed_rows)
        bound = set(document['parameterized'])
        missing, stale = installed_rows - bound, bound - installed_rows
        if missing or stale:
            errors.append(f'installed population differs from bindings: missing={sorted(missing)}, stale={sorted(stale)}')
    expected = expected_pairs(document)
    bespoke = {row['id']: row for row in document['bespoke']}
    seen = Counter()
    files = {item.nodeid.split('::', 1)[0] for item in items}
    for item in items:
        mark = item.get_closest_marker('nc_case')
        if mark is None:
            continue
        test = item.nodeid.split('[', 1)[0]
        dimension = mark.kwargs.get('dimension')
        if dimension:
            row = getattr(getattr(item, 'callspec', None), 'params', {}).get('row')
            if not isinstance(row, str) or row not in document['parameterized']:
                errors.append(f'{item.nodeid}: unknown or absent parameterized row {row!r}')
                continue
            group = document['groups'][document['parameterized'][row]]
            if group['dimension'] != dimension or (dimension == 'ROLE' and group['field'] not in mark.kwargs.get('fields', ())):
                errors.append(f'{item.nodeid}: row does not match its declared dimension or card field')
            if mark.kwargs.get('binding') not in group['bindings']:
                errors.append(f'{item.nodeid}: runtime binding differs from its declaration')
            rows = (row,)
        else:
            rows = mark.kwargs.get('rows', ())
            if not rows:
                errors.append(f'{item.nodeid}: bespoke case declares no rows')
            for row in rows:
                if row not in bespoke or bespoke[row]['binding'] != mark.kwargs.get('binding'):
                    errors.append(f'{item.nodeid}: unknown row or runtime binding differs for {row!r}')
        for row in rows:
            pair = (row, test)
            seen[pair] += 1
            if pair not in expected:
                errors.append(f'{item.nodeid}: no declaration binds {row!r} to this test')
    duplicates = sorted(pair for pair, count in seen.items() if count != 1)
    if duplicates:
        errors.append(f'coverage cases collected more than once: {duplicates}')
    if complete_files:
        selected = {pair for pair in expected if pair[1].split('::', 1)[0] in files}
        missing = selected - set(seen)
        if missing:
            errors.append(f'declared cases missing from collection: {sorted(missing)}')
    return errors


def pending_rows(document):
    """Bindings without a declared case; these cannot count toward closed coverage."""
    return sorted([row['id'] for row in document['bespoke'] if row['status'] != 'implemented']
                  + [row for row, gid in document['parameterized'].items()
                     if document['groups'][gid]['status'] != 'implemented'])
