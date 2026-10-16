"""Release availability is separate from scientific prerequisites and admission."""
from dataclasses import dataclass
from importlib.util import find_spec
import json
from pathlib import Path


class CapabilityNotInRelease(ValueError):
    """Planning refusal; this capability cannot create a held study."""
    def __init__(self, reason=''):
        super().__init__(reason or 'This capability is not part of this release of RAVEL.')


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


def availability(mode, *, root=None, find_spec=find_spec, platform_key=None):
    from .release_registry import implementing_module, manifest_operations
    module=implementing_module(mode,root=root)
    if not module_present(module,find_spec=find_spec):
        return Availability(False,module,reason='implementation absent')
    source=Path(root) if root is not None else Path(__file__).resolve().parents[3]
    try:
        from ravel.setup.manifest import view
        document=view(source)
        document=manifest_operations(document,root=root)
    except (OSError,ValueError):
        return Availability(True,module,True,'manifest unreadable; module presence used')
    rows=[r for r in document.get('operations',[]) if r.get('mode')==mode]
    groups=document.get('groups', {})
    if isinstance(groups, list):
        groups={row['id']:row for row in groups}
    supported=[row for row in rows if all(g in groups for g in row.get('groups', []))]
    if not supported:
        return Availability(False,module,reason='operation or tool group absent')
    from ravel.setup import manifest as mf
    reasons=[]
    for row in supported:
        missing=[]
        for gid in row.get('groups', []):
            group=groups[gid] if isinstance(groups, dict) else {}
            if (group.get('qualification') or {}).get('required_per_platform'):
                reason=mf.platform_qualification_reason(group,platform_key or mf.detect_platform())
                if reason:
                    missing.append(reason)
        if not missing:
            return Availability(True,module)
        reasons.extend(missing)
    return Availability(False,module,reason=f"{mode}: " + '; '.join(dict.fromkeys(reasons)))


def require(mode, **kwargs):
    result=availability(mode,**kwargs)
    if not result.available:
        raise CapabilityNotInRelease(result.reason if 'missing successful qualification' in result.reason else '')
    return result
