"""Retain the complete native SimpleAnalysis ROOT output, without rebinning.

The pinned OutputHandler books TH1D, TH2D and one TTree with integer/float
scalars or vectors. Unknown objects, repeated cycles and absent squared-weight
storage are refused rather than silently omitted. Histogram flows, labels,
signed contents and native squared weights remain separate from event-level
covariance; neither implies a detector calibration or an exclusion result.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

from ravel import analysis_sources as sources


def _finite(value):
    if isinstance(value, list):
        return [_finite(item) for item in value]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('native ntuple contains unsupported or nonfinite values')
    return value


def read_outputs(path, routine, *, expected_events):
    """Read every booked object and branch from the retained native ROOT file.

    This is a decoder, not a source-booking oracle. The complete observed object
    census is retained; independent acceptance must compare it with the routine's
    complete source-defined booking/output obligations.
    """
    import awkward as ak
    import numpy as np
    import uproot

    path = Path(path)
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError('ordinary nonempty native ROOT output required')
    if not isinstance(routine, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', routine):
        raise ValueError('literal native routine required')
    if type(expected_events) is not int or expected_events < 1:
        raise ValueError('complete nonempty input-event denominator required')
    before = {'sha256': sources.digest(path), 'size': path.stat().st_size}
    objects = {}
    trees = []
    with uproot.open(path) as root:
        keys = root.keys(recursive=False, cycle=True)
        if len({key.rsplit(';', 1)[0] for key in keys}) != len(keys):
            raise ValueError('repeated ROOT output cycles require an explicit contract')
        for key in keys:
            name = key.rsplit(';', 1)[0]
            if not name.startswith(routine+'__'):
                raise ValueError('native ROOT object belongs to an unselected routine')
            obj = root[key]
            if obj.classname in ('TH1D', 'TH2D'):
                dimensions = 1 if obj.classname == 'TH1D' else 2
                values = np.asarray(obj.values(flow=True), dtype=np.float64)
                axes = []
                for axis in obj.axes:
                    edges = np.asarray(axis.edges(flow=False), dtype=np.float64)
                    native_labels = axis.member('fLabels', none_if_missing=True)
                    labels = None if native_labels is None else [''] * (len(edges) - 1)
                    label_slots = []
                    seen_slots = set()
                    for label in native_labels if native_labels is not None else ():
                        slot = label.member('@fUniqueID')
                        if label.classname != 'TObjString' or type(slot) is not int or not 1 <= slot < len(edges) or slot in seen_slots:
                            raise ValueError('invalid or duplicate native histogram label slot')
                        seen_slots.add(slot)
                        labels[slot - 1] = str(label)
                        label_slots.append({'bin': slot, 'label': str(label)})
                    if (edges.ndim != 1 or len(edges) < 2 or not np.isfinite(edges).all()
                            or not np.all(np.diff(edges) > 0)
                            or labels is not None and (len(labels) != len(edges) - 1
                                or any(not isinstance(label, str) for label in labels))):
                        raise ValueError('invalid native histogram axis/labels')
                    axes.append({'edges': edges.tolist(), 'labels': labels, 'native_label_slots': label_slots,
                                 'title': str(axis.member('fTitle'))})
                shape = tuple(len(axis['edges']) + 1 for axis in axes)
                native_sumw2 = np.asarray(obj.member('fSumw2'), dtype=np.float64)
                if (len(axes) != dimensions or values.shape != shape
                        or native_sumw2.ndim != 1 or native_sumw2.size != values.size
                        or not np.isfinite(values).all() or not np.isfinite(native_sumw2).all()
                        or np.any(native_sumw2 < 0)):
                    raise ValueError('native histogram requires complete finite signed contents and explicit Sumw2')
                # ROOT's global bin index advances X first. This retains every
                # under/overflow corner of a 2D histogram in [x][y] coordinates.
                squared = native_sumw2.reshape(shape, order='F')
                entries = float(obj.member('fEntries'))
                moments = {field: float(obj.member(field)) for field in
                           (('fTsumw', 'fTsumw2', 'fTsumwx', 'fTsumwx2') if dimensions == 1 else
                            ('fTsumw', 'fTsumw2', 'fTsumwx', 'fTsumwx2',
                             'fTsumwy', 'fTsumwy2', 'fTsumwxy'))}
                if not math.isfinite(entries) or entries < 0 or not all(math.isfinite(v) for v in moments.values()):
                    raise ValueError('nonfinite native histogram entries/global moments')
                objects[name] = {'class': obj.classname, 'title': str(obj.title),
                    'dimensions': dimensions, 'axes': axes, 'entries': entries,
                    'sumw_with_flows': values.tolist(), 'sumw2_with_flows': squared.tolist(),
                    'native_global_moments': moments,
                    'flow_indexing': 'each axis: underflow, finite bins, overflow',
                    'bin_covariance': None,
                    'covariance_scope': 'native per-bin Sumw2 only; event/group joint moments are not inferred'}
            elif obj.classname == 'TTree' and name == routine+'__ntuple':
                trees.append(name)
                if int(obj.num_entries) != expected_events:
                    raise ValueError('complete rejected/accepted native event-tree census required')
                branches = {}
                for branch_name in obj.keys():
                    branch = obj[branch_name]
                    typename = branch.typename
                    if typename not in ('int32_t', 'int', 'float', 'std::int32_t',
                                        'std::vector<int>', 'std::vector<int32_t>', 'std::vector<float>',
                                        'vector<int>', 'vector<float>'):
                        raise ValueError('unsupported native OutputHandler branch type: ' + typename)
                    values = ak.to_list(branch.array(library='ak'))
                    if len(values) != expected_events:
                        raise ValueError('incomplete native output branch census')
                    branches[branch_name] = {'typename': typename, 'values': _finite(values)}
                objects[name] = {'class': obj.classname, 'title': str(obj.title),
                                 'entries': expected_events, 'branches': branches}
            else:
                raise ValueError('unsupported native ROOT output object: ' + obj.classname)
    if len(trees) != 1:
        raise ValueError('exactly one complete native OutputHandler ntuple required')
    if {'sha256': sources.digest(path), 'size': path.stat().st_size} != before:
        raise ValueError('native ROOT output changed during decoding')
    return {'schema_version': 1, 'kind': 'simpleanalysis-native-outputs',
            'routine': routine, 'source_file': before, 'object_census': sorted(objects),
            'objects': objects, 'physics_validated': False,
            'scope': 'Complete observed native ROOT objects; no inferred booking, normalization or joint covariance'}
