"""Find ambiguities in a typed analysis specification before any code is written.

The categories are general to collider analyses (version ``CATEGORIES_VERSION``):

- ``collection_scope``: a cut or observable uses a collection that is not stated
  explicitly while several object definitions share its family (for example "the two
  leading jets" with baseline and signal jets defined);
- ``veto_scope``: a veto whose collection is not explicit (a veto on baseline or on
  signal objects moves the yield);
- ``object_reuse``: two definitions of one family with no overlap step between them, so
  one object may be counted twice;
- ``cut_ordering``: cuts of a region without a complete, unique order (the cutflow
  depends on it);
- ``fill_timing``: a histogram that does not say after which cut it is filled;
- ``variable_consistency``: one observable defined twice with different values, or a
  field that is ambiguous in the source;
- ``normalization_basis``: a histogram whose normalisation basis is not explicit.

An ambiguity blocks only when it can move a yield or a shape: its category is one that
does by nature (collection and veto scope, undefined variables, normalisation basis), or
the specification estimates its impact above 10 per cent. Every other ambiguity is
recorded as a defaulted assumption for CHECK-IN 1. Each section and object family
reports at most ``CAP`` ambiguities; the remainder is summarised in one entry.
"""
from collections import defaultdict

CATEGORIES_VERSION = 1
CATEGORIES = ('collection_scope', 'veto_scope', 'object_reuse', 'cut_ordering', 'fill_timing',
              'variable_consistency', 'normalization_basis')
HIGH_IMPACT = {'collection_scope', 'veto_scope', 'normalization_basis'}
THRESHOLD = 0.10
CAP = 5


def _explicit(field):
    return isinstance(field, dict) and field.get('status') == 'explicit'


def _entry(category, item, field, reason, *, impact=None, default=None):
    return {'category': category, 'item': item['id'], 'field': field, 'reason': reason,
            'impact_estimate': item.get('impact_estimate', impact), 'default': default}


def find(spec):
    """Ambiguities, the blocking subset and the defaulted assumptions for CHECK-IN 1."""
    items = spec['doc']['items']
    objects = {i['id']: i for i in items if i['role'] == 'object'}
    families = defaultdict(list)
    for item in items:
        if item['role'] == 'object':
            families[item['family']].append(item)
    overlaps = {frozenset((i.get('fields', {}).get('remove', {}).get('value'), i.get('fields', {}).get('near', {}).get('value')))
                for i in items if i['role'] == 'overlap'}
    found = []
    for item in items:
        fields = item.get('fields', {})
        for name, field in fields.items():
            if field.get('status') == 'ambiguous':
                found.append(_entry('variable_consistency', item, name,
                                    f'the source admits readings {field["readings"]}', default=field['readings'][0]))
        if item['role'] in ('cut', 'observable') and item.get('collection') is not None:
            collection = item['collection']
            if not _explicit(collection):
                value = collection.get('value')
                family = objects[value]['family'] if value in objects else (value or item.get('family'))
                candidates = [o['id'] for o in objects.values() if o['family'] == family]
                veto = fields.get('kind', {}).get('value') == 'veto'
                if veto or len(candidates) > 1:
                    found.append(_entry('veto_scope' if veto else 'collection_scope', item, 'collection',
                                        f'the collection is {collection["status"]}; candidates {candidates or [family]}',
                                        default=value))
        if item['role'] == 'histogram':
            basis = fields.get('normalization_basis')
            if not _explicit(basis):
                found.append(_entry('normalization_basis', item, 'normalization_basis',
                                    'the normalisation basis is not stated in the source',
                                    default=(basis or {}).get('value')))
            if not _explicit(fields.get('fill_after')):
                found.append(_entry('fill_timing', item, 'fill_after',
                                    'the histogram does not say after which cut it is filled', default='last cut'))
    for family, members in families.items():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                x, y = members[a]['id'], members[b]['id']
                if frozenset((x, y)) not in overlaps and not _explicit(members[b].get('fields', {}).get('derived_from')):
                    found.append(_entry('object_reuse', members[b], 'derived_from',
                                        f'{x!r} and {y!r} are both {family} definitions with no overlap step '
                                        'or stated derivation', default=f'{y} is a subset of {x}'))
    regions = defaultdict(list)
    for item in items:
        if item['role'] == 'cut':
            regions[item['region']].append(item)
    for region, cuts in regions.items():
        orders = [c.get('order') for c in cuts]
        if None in orders or len(set(orders)) != len(orders):
            found.append(_entry('cut_ordering', cuts[0], 'order',
                                f'region {region!r} has cuts without a unique order', default='listed order'))
    observables = defaultdict(list)
    for item in items:
        if item['role'] == 'observable':
            observables[item.get('fields', {}).get('name', {}).get('value', item['id'])].append(item)
    for name, defs in observables.items():
        if len(defs) > 1:
            definitions = {repr({k: v.get('value') for k, v in d.get('fields', {}).items() if k != 'name'}) for d in defs}
            if len(definitions) > 1:
                found.append(_entry('variable_consistency', defs[1], 'definition',
                                    f'observable {name!r} is defined {len(defs)} times differently', impact=1.0))
    # Classify and cap.
    for entry in found:
        estimate = entry['impact_estimate']
        entry['blocking'] = bool(entry['category'] in HIGH_IMPACT or (estimate is not None and estimate > THRESHOLD))
    capped, counts = [], defaultdict(int)
    by_id = {i['id']: i for i in items}
    for entry in sorted(found, key=lambda e: (not e['blocking'], e['category'], e['item'])):
        item = by_id[entry['item']]
        group = (item['role'], item.get('family') or item.get('region') or '')
        counts[group] += 1
        if counts[group] <= CAP or entry['blocking']:
            capped.append(entry)
    summaries = [{'category': 'cap', 'group': list(g), 'omitted': n - CAP, 'blocking': False}
                 for g, n in counts.items() if n > CAP]
    blocking = [e for e in capped if e['blocking']]
    assumptions = [{'id': f'A{k + 1}', 'category': e['category'], 'item': e['item'], 'field': e['field'],
                    'statement': f'{e["reason"]}; default: {e["default"]}', 'status': 'defaulted'}
                   for k, e in enumerate(e for e in capped if not e['blocking'])]
    return {'schema_version': 1, 'kind': 'specification-ambiguities', 'categories_version': CATEGORIES_VERSION,
            'ambiguities': capped + summaries, 'blocking': blocking, 'assumptions': assumptions}
