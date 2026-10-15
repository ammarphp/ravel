"""Apply explicit role registration fragments without rewriting the base registry."""
from copy import deepcopy
import json


def source_pins(package, pin):
    """Pin this module and every fragment inside the given package tree."""
    pin(package / 'workflow/role_registration.py')
    for path in sorted((package / 'data/roles/registration').glob('*.json')):
        pin(path)


def apply(root, document):
    result = deepcopy(document)
    for path in sorted((root / 'registration').glob('*.json')):
        fragment = json.loads(path.read_bytes())
        if fragment.get('schema_version') != 1:
            raise ValueError('unsupported role registration schema: ' + path.name)
        for identity, row in fragment.get('roles', {}).items():
            if identity in result['roles']:
                raise ValueError('duplicate role registration: ' + identity)
            result['roles'][identity] = row
        for alias, row in fragment.get('aliases', {}).items():
            previous = result['aliases'].get(alias)
            if previous != row.get('replaces'):
                raise ValueError('role alias registration has a stale predecessor: ' + alias)
            result['aliases'][alias] = row['role']
    return result
