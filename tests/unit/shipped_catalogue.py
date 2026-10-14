"""What this tree ships, read from its own catalogues.

The source tree declares every operation and toolchain group, including those a release withholds. The
export removes a withheld one from every catalogue together: the toolchain manifest, the descriptor
catalogue, the operation signatures and the science registry. A test about a named operation or group asks
these catalogues instead of assuming that it ships; a name that no catalogue declares is not shipped here.
"""
import json
from importlib.resources import files

from ravel.setup import manifest as mf
from ravel.workflow import science


def _data(name):
    return json.loads(files('ravel').joinpath('data', name).read_text())


def operations():
    """Every operation name a catalogue of this tree declares."""
    signatures = _data('operation_signatures.json')['operations']
    return (set(science.MODES) | set(_data('mode_descriptors.json')['modes']) | set(signatures)
            | {row['implementation'].get('mode') for row in signatures.values()}
            | {row['mode'] for row in mf.load()[0]['operations']}) - {None}


def shipped_operations(names):
    """The members of ``names`` this tree ships, in their given order."""
    declared = operations()
    return tuple(name for name in names if name in declared)


def shipped_groups(names):
    """The members of ``names`` that this tree's toolchain manifest declares, in their given order."""
    declared = mf.by_id(mf.load()[0])
    return tuple(name for name in names if name in declared)
