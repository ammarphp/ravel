"""One loader for registries and optional installed extensions.

Absence of the extension fragment is the ordinary release configuration.
Entries never shadow entries already declared by the main registry.
"""
from functools import lru_cache
from importlib import import_module
import json
from pathlib import Path


def package_root(root=None):
    if root is None:
        return Path(__file__).resolve().parents[1]
    source=Path(root)/'src/ravel'
    return source if source.is_dir() else Path(root)/'ravel'


@lru_cache(maxsize=64)
def _cached_json(path, modified, size):
    return json.loads(Path(path).read_text())


def _json_file(path):
    stat=path.stat()
    return _cached_json(str(path),stat.st_mtime_ns,stat.st_size)


def fragment(root=None):
    path=package_root(root)/'data/release/in-development.json'
    if not path.is_file():
        return {}
    value=_json_file(path)
    if not isinstance(value,dict):
        raise ValueError('registry fragment must be an object')
    return value


def merge_entries(name, base, *, root=None):
    extra=fragment(root).get(name, {} if isinstance(base,dict) else [])
    if isinstance(base,dict):
        duplicate=set(base)&set(extra)
        if duplicate:
            raise ValueError('duplicate registry entry: '+', '.join(sorted(duplicate)))
        return {**base,**extra}
    if set(base)&set(extra):
        raise ValueError('duplicate registry entry in '+name)
    return list(base)+list(extra)


def load_document(filename, table, fragment_key, *, root=None, available=False):
    document=dict(_json_file(package_root(root)/'data'/filename))
    document[table]=merge_entries(fragment_key,document[table],root=root)
    if available:
        from .capability_availability import availability
        document[table]={name:row for name,row in document[table].items()
                         if availability(name,root=root).available}
    return document


def mode_descriptors(*,root=None,available=True):
    return load_document('mode_descriptors.json','modes','mode_descriptors',root=root,available=available)


def operation_signatures(*,root=None,available=True):
    document=load_document('operation_signatures.json','operations','operation_signatures',root=root)
    if available:
        from .capability_availability import availability
        document['operations']={name:row for name,row in document['operations'].items()
            if row.get('implementation',{}).get('kind')!='science-mode' or availability(name,root=root).available}
    return document


def science_modes(base, *, root=None, available=True):
    from .capability_availability import availability
    values=merge_entries('science_modes',base,root=root)
    order={name:i for i,name in enumerate(fragment(root).get('science_mode_order', values))}
    return tuple(name for name in sorted(values,key=lambda n:order.get(n,len(order)))
                 if not available or availability(name,root=root).available)


def implementing_module(mode, *, root=None):
    extra=fragment(root).get('adapters',{})
    if mode in extra:
        return extra[mode]
    rows=operation_signatures(root=root,available=False)['operations']
    return rows.get(mode,{}).get('implementation',{}).get('module')


def extension(slot, *, root=None):
    """Resolve a declared extension only when the caller requests its operation."""
    from .capability_availability import CapabilityNotInRelease, module_present
    target=fragment(root).get('extensions',{}).get(slot)
    if not target:
        raise CapabilityNotInRelease()
    module, _, name=target.partition(':')
    if not module_present(module):
        raise CapabilityNotInRelease()
    loaded=import_module(module)
    return getattr(loaded,name) if name else loaded


def manifest_operations(document, *, root=None):
    document=dict(document)
    document['operations']=_operation_rows(document.get('operations',[]),fragment(root).get('toolchain_operations',[]))
    order={mode:i for i,mode in enumerate(fragment(root).get('toolchain_operation_order',[]))}
    document['operations'].sort(key=lambda row:order.get(row['mode'],len(order)))
    for field, rows in fragment(root).get('manifest_tables',{}).items():
        document[field]=list(document.get(field,[]))+list(rows)
    return document


def _operation_rows(base,extra):
    if {row['mode'] for row in base}&{row['mode'] for row in extra}:
        raise ValueError('duplicate manifest operation')
    return list(base)+list(extra)


class _LazyModule:
    """Defer an import; attribute reads and writes (including test patches) reach the module."""
    def __init__(self, name):
        object.__setattr__(self,'_name',name)

    def _module(self):
        from .capability_availability import CapabilityNotInRelease, module_present
        if not module_present(self._name):
            raise CapabilityNotInRelease()
        return import_module(self._name)

    def __getattr__(self, name):
        return getattr(self._module(),name)

    def __setattr__(self, name, value):
        setattr(self._module(),name,value)

    def __delattr__(self, name):
        delattr(self._module(),name)


def lazy_module(name):
    return _LazyModule(name)

