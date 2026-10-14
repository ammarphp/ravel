"""Release availability is separate from scientific prerequisites and admission."""
from dataclasses import dataclass
from importlib.util import find_spec
import json
from pathlib import Path


class CapabilityNotInRelease(ValueError):
    """Planning refusal; this capability cannot create a held study."""
    def __init__(self):
        super().__init__('This capability is not part of this release of RAVEL.')


@dataclass(frozen=True)
class Availability:
    available: bool
    module: str | None
    manifest_fallback: bool = False
    reason: str = ''


def module_present(module, *, find_spec=find_spec):
    if not module:
        return False
    try:
        return find_spec(module) is not None
    except (ImportError,ValueError,AttributeError):
        return False


def availability(mode, *, root=None, find_spec=find_spec):
    from .release_registry import implementing_module, manifest_operations
    module=implementing_module(mode,root=root)
    if not module_present(module,find_spec=find_spec):
        return Availability(False,module,reason='implementation absent')
    source=Path(root) if root is not None else Path(__file__).resolve().parents[3]
    try:
        document=json.loads((source/'native/setup/toolchain-manifest.json').read_text())
        document=manifest_operations(document,root=root)
    except (OSError,ValueError):
        return Availability(True,module,True,'manifest unreadable; module presence used')
    rows=[r for r in document.get('operations',[]) if r.get('mode')==mode]
    groups=document.get('groups',{})
    if isinstance(groups,list):
        groups={row['id'] for row in groups}
    supported=any(all(g in groups for g in row.get('groups',[])) for row in rows)
    return Availability(supported,module,reason='' if supported else 'operation or tool group absent')


def require(mode, **kwargs):
    result=availability(mode,**kwargs)
    if not result.available:
        raise CapabilityNotInRelease()
    return result
