"""Independent expected metadata for newly registered source group fragments."""
from copy import deepcopy
from decimal import Decimal


def extend_group_expectation(main, root):
    """Extend the split-only identity expectation with new fragment contracts.

    This reads source declarations, never the loader's generated result. The
    calling identity test still compares the entire document and CLI digest.
    Synthetic loader tests separately exercise malformed registration records.
    """
    import json
    expected = deepcopy(main)
    positioned = set(expected['group_order'])
    wrappers = [json.loads(p.read_text()) for p in sorted((root / 'native/setup/groups').glob('*.json'))
                if p.name != 'group.schema.json']
    new = {w['group']['id']: w['group'] for w in wrappers if w['group']['id'] not in positioned}
    # As the loader does: a release list exists only when the main file or a fragment declares one.
    if any('unreleased' in wrapper for wrapper in wrappers):
        expected.setdefault('unreleased', {'groups': [], 'operations': []})
    holds = expected.get('unreleased', {})
    for wrapper in wrappers:
        for key in ('groups', 'operations'):
            if key in wrapper.get('unreleased', {}):
                holds.setdefault(key, []).extend(deepcopy(wrapper['unreleased'][key]))
    pending = list(new)
    while pending:
        ready = next((gid for gid in pending if set(new[gid]['depends_on']) <= positioned), None)
        assert ready is not None, 'new fragment dependencies cannot follow positioned source groups'
        expected['group_order'].append(ready)
        positioned.add(ready)
        pending.remove(ready)
    held = {row['id'] for row in holds.get('groups', [])}
    additions = [gid for gid in expected['group_order'] if gid in new
                 and gid not in expected['default']['groups'] and gid not in held]
    expected['default']['groups'].extend(additions)
    if additions:
        expected['default']['disk_gb'] = float(Decimal(str(expected['default']['disk_gb']))
            + sum(Decimal(str(new[gid]['size_gb'])) for gid in additions))
    return expected
