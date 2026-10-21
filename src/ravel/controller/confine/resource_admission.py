"""Conservative retained-copy admission, distinct from filesystem reservations.

A generic authored launch cannot honour a run-wide retained-disk ceiling. The
trusted source reader has a finite output ceiling and a fixed copy population;
its admission accounts for source blobs, adoption and downstream input copies.
Live free space is an observation, never a receipt-headroom reservation or quota.
"""
from pathlib import Path
import shutil
import stat


RECEIPT_MARGIN_BYTES = 1 << 20
COPY_POPULATION = ('acquisition', 'adoption', 'downstream_input')


def launch_limits(launch, wall_seconds, *, retained_disk_bytes=None):
    """Forward every declared resource request without silently dropping a limit."""
    from .launcher import LIMIT_KEYS, LaunchHeld, _limits, _require_supported_limits
    nested = launch.get('limits', {})
    if not isinstance(nested, dict) or set(nested) - LIMIT_KEYS:
        raise ValueError('launch limits contain an unsupported resource name')
    limits = dict(nested)
    for name in LIMIT_KEYS:
        if name in launch:
            if name in limits and limits[name] != launch[name]:
                raise ValueError('conflicting launch resource declarations: ' + name)
            limits[name] = launch[name]
    limits = {key: value for key, value in _limits(limits).items() if key != 'cpu_set'}
    if 'wall_seconds' in limits and limits['wall_seconds'] > wall_seconds:
        raise ValueError('launch wall_seconds exceeds its reserved wall time')
    limits['wall_seconds'] = min(limits.get('wall_seconds', wall_seconds), wall_seconds)
    limits.setdefault('cpus', 1)
    _require_supported_limits(limits)
    if retained_disk_bytes is not None:
        raise LaunchHeld('resource_limit_unsupported',
                         'generic local launch cannot enforce the operator retained_disk_bytes ceiling; '
                         'select a separately qualified adapter covering retained copies and receipt headroom')
    return limits


def retained_bytes(root):
    """Logical retained bytes including every attempt, without following links.

    Runtime sockets and link metadata can coexist with immutable artifacts. Their
    own inode sizes count; their targets are never read or granted by accounting.
    """
    root = Path(root)
    if root.is_symlink():
        raise ValueError('retained storage root is a symbolic link')
    total = 0
    if not root.exists():
        return total
    for path in root.rglob('*'):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            total += info.st_size
    return total


def acquisition_admission(run_dir, max_bytes, *, retained_disk_bytes=None, free_floor_bytes=None,
                          store_root=None, input_bytes=0):
    """Account every retained representation before the bounded source reader starts."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('acquisition needs a positive output byte ceiling')
    for name, value in (('retained_disk_bytes', retained_disk_bytes), ('free_floor_bytes', free_floor_bytes),
                        ('input_bytes', input_bytes)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(name + ' must be a nonnegative integer or null')
    root = Path(run_dir).resolve(strict=True)
    roots = [root]
    if store_root is not None:
        store = Path(store_root).resolve(strict=True)
        if not store.is_relative_to(root):
            roots.append(store)
    existing = sum(retained_bytes(path) for path in roots)
    copy_bytes = max_bytes * len(COPY_POPULATION) + input_bytes
    projected = existing + copy_bytes + RECEIPT_MARGIN_BYTES
    if retained_disk_bytes is not None and projected > retained_disk_bytes:
        raise ValueError('retained_disk_budget_exhausted: existing bytes plus all retained copies and receipt '
                         'margin exceed the operator retained_disk_bytes ceiling')
    filesystems = {}
    for path in roots:
        device = path.stat().st_dev
        if device not in filesystems:
            free = shutil.disk_usage(path).free
            # Conservatively charge the complete copy population on each filesystem.
            needed = copy_bytes + RECEIPT_MARGIN_BYTES + (free_floor_bytes or 0)
            if free < needed:
                raise ValueError('acquisition_storage_exhausted: filesystem cannot cover all retained copies, '
                                 'receipt margin and configured free-space floor')
            filesystems[device] = {'path': str(path), 'free_bytes': free, 'required_free_bytes': needed}
    return {'schema_version': 1, 'kind': 'acquisition-storage-admission', 'existing_bytes': existing,
            'output_ceiling_bytes': max_bytes, 'copy_population': list(COPY_POPULATION),
            'copy_ceiling_bytes': copy_bytes, 'input_bytes': input_bytes,
            'receipt_margin_bytes': RECEIPT_MARGIN_BYTES, 'projected_retained_bytes': projected,
            'retained_disk_bytes': retained_disk_bytes, 'filesystems': list(filesystems.values()),
            'scope': 'conservative admission accounting; no quota or receipt-headroom reservation',
            'headroom_reserved': False}


def admit_acquisition(store, step, run_dir, *, input_paths=(), plan_sha256=None, attempt=1, phase='start'):
    """Re-evaluate storage at the source-reader action, as well as during preflight."""
    from ravel.controller.step.services import module
    authority = module('authority')
    provider = getattr(authority, 'effective_bounds', None)
    bounds = provider(store) if callable(provider) else {}
    provider = getattr(authority, 'frozen', None)
    frozen = provider(store, required=False) if callable(provider) else None
    evidence = acquisition_admission(
        run_dir, ((step.get('parameters') or {}).get('task') or {}).get('max_bytes'),
        retained_disk_bytes=(bounds.get('budgets') or {}).get('retained_disk_bytes'),
        free_floor_bytes=(frozen or {}).get('disk_free_floor_bytes'),
        store_root=getattr(store, 'root', None),
        input_bytes=sum(Path(path).stat().st_size for path in input_paths))
    record = {**evidence, 'step_id': step['id'], 'attempt': attempt,
              'plan_sha256': plan_sha256, 'phase': phase}
    return {**record, 'record_id': store.append('acquisition-storage-admission', record)}
