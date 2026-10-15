"""Discover native selection compatibility from the shipped and supplied analysis packages.

Registration means a package declares an interface the adapter can execute. It never grants
qualification, an acceptance certificate or permission to serve a scientific result.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ALIAS_ENV = "RAVEL_NATIVE_ALIASES"

from .analysis_packages import discover, load_package, PackageInputError
from .sa_routines import RoutineUnavailable

CAPABILITIES = {}


def discover_capabilities(roots=None):
    result = dict(CAPABILITIES)
    for name, package in discover(roots).items():
        compatibility = package['compatibility']
        if name in result:
            raise PackageInputError('ambiguous_analysis_package', name)
        result[name] = {**compatibility, 'analysis_ids': package['analysis_ids'],
                        'detector': compatibility['detectors'][0], 'routine': name,
                        'needs_restframes': package['routine']['kind'] == 'two-pass',
                        'analysis_package': package['manifest_path'], 'package_version': package['package_version'],
                        'qualification': package['qualification'], 'physics_certified': False}
    return result


MODEL_PDGS = {
    "slepton-bino": ((1000011, 2000011, 1000013, 2000013, 1000015, 2000015), 1000022),
    "c1n2-wz": ((1000023, 1000024), 1000022),
    "squark-neutralino": ((1000001, 1000002, 1000003, 1000004, 2000001, 2000002, 2000003, 2000004), 1000022),
    "gluino-neutralino": ((1000021,), 1000022),
}


def load_aliases(path=None):
    """{upstream routine: {"adapter", "analysis_ids"}} from ``path`` or RAVEL_NATIVE_ALIASES (none by default)."""
    path = path or os.environ.get(ALIAS_ENV)
    if not path:
        return {}
    document = json.loads(Path(path).read_text())
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or document.get("kind") != "native-routine-aliases" or not isinstance(document.get("aliases"), dict)):
        raise ValueError(f"{path}: not a version-1 native-routine-aliases file")
    capabilities = discover_capabilities()
    aliases = {}
    for name, row in document["aliases"].items():
        if (not isinstance(row, dict) or set(row) - {"adapter", "analysis_ids"} or row.get("adapter") not in capabilities
                or not isinstance(row.get("analysis_ids", []), list)):
            raise ValueError(f"{path}: alias {name!r} must name a registered adapter")
        if name in capabilities:
            raise ValueError(f"{path}: alias {name!r} shadows a registered adapter")
        aliases[name] = {"adapter": row["adapter"], "analysis_ids": tuple(map(str, row.get("analysis_ids", [])))}
    return aliases


def adapter_for(routine, aliases=None):
    """The registered adapter key for ``routine``: itself, or the adapter its supplied alias names."""
    aliases = load_aliases() if aliases is None else aliases
    if routine in discover_capabilities():
        return routine
    if routine in aliases:
        return aliases[routine]["adapter"]
    raise RoutineUnavailable(routine, "unregistered_native_analysis",
                             f"supply an analysis package and bind its identity with {ALIAS_ENV}")


def resolve_capability(routine, model, preparation, detector, statistics, analysis_id=None, aliases=None, *, analysis_package=None):
    if analysis_package is None:
        rows = discover_capabilities()
        aliases = load_aliases() if aliases is None else aliases
        adapter = aliases.get(routine, {}).get('adapter', routine)
        row = rows.get(adapter)
        if row is None or 'analysis_package' not in row:
            raise PackageInputError('missing_analysis_package', str(routine))
        analysis_package = row['analysis_package']
    package = load_package(analysis_package, require_qualification=True)
    if routine not in (package['package_id'], *package['analysis_ids']):
        aliases = load_aliases() if aliases is None else aliases
        if aliases.get(routine, {}).get('adapter') != package['package_id']:
            raise PackageInputError('package_identity_mismatch', str(routine))
    aliases = load_aliases() if aliases is None else aliases
    extra_ids = aliases.get(routine, {}).get('analysis_ids', ()) if aliases.get(routine, {}).get('adapter') == package['package_id'] else ()
    analysis_ids = [*package['analysis_ids'], *extra_ids]
    compatibility = package['compatibility']
    for value, allowed, field in ((model, compatibility['models'], 'model'),
                                 (preparation, compatibility['preparations'], 'preparation'),
                                 (detector, compatibility['detectors'], 'detector'),
                                 (statistics, compatibility['statistics'], 'statistics')):
        if value not in allowed:
            raise PackageInputError('unsupported_package_binding', f'{field} {value!r}')
    if analysis_id is not None and analysis_id not in analysis_ids:
        raise PackageInputError('package_identity_mismatch', f'requested analysis {analysis_id!r} disagrees')
    return {**compatibility, 'analysis_ids': analysis_ids, 'routine': package['package_id'],
            'model': model, 'preparation': preparation, 'detector': detector,
            'upstream_routine': routine, 'statistics_adapter': statistics,
            'analysis_package': package['manifest_path'], 'package_version': package['package_version'],
            'routine_interface': package['routine'], 'control_regions': package.get('control_regions', []),
            'source_pins': package['source_pins'], 'needs_restframes': package['routine']['kind'] == 'two-pass',
            'physics_certified': False}
