"""General supplied MA5 SAF delivery and shared bounded source capture.

The source-booking family retains signed channels, flows and complete supplied
populations. Legacy inputs must be converted with supplied upstream metadata.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from ravel.physics import ma5_saf_reader as reader
from ravel.workflow.state_io import _unique, atomic_json
from ravel.physics import supplied_contracts as contracts

MAX_FILE = 8 * 1024**2


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label+' requires exactly '+', '.join(keys))


def validate(task):
    contracts.fields(task, ('input',))
    _keys(task, ('input', 'output') if 'output' in task else ('input',), 'MA5 SAF task')
    if 'output' in task: contracts.output_contract(task['output'])
    if type(task['input']) is not str or not task['input'].strip():
        raise ValueError('MA5 SAF input path required')
    return deepcopy(task)


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class Capture:
    """One observation's exact bytes; fresh instances at every public boundary."""
    def __init__(self):
        self.files = {}
        self.roots = {}
        self.paths = {}

    def ordinary(self, path, *, directory=False):
        """Observe every lexical ancestor and the leaf without resolving links."""
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('canonical absolute supplied pathname required')
        observed = {}
        try:
            for part in (*reversed(path.parents), path):
                st = part.lstat()
                is_directory = part != path or directory
                if not (stat.S_ISDIR(st.st_mode) if is_directory else stat.S_ISREG(st.st_mode)):
                    raise ValueError('ordinary supplied ancestors and leaf required')
                # Directory timestamps may change when an unrelated delivery
                # file is created; device/inode/mode still binds membership.
                observed[part] = ((st.st_dev, st.st_ino, st.st_mode)
                                  if is_directory else _identity(st))
        except OSError as exc:
            raise ValueError('supplied pathname unavailable') from exc
        old = self.paths.get(path)
        if old is not None and old != observed:
            raise ValueError('supplied ancestor or leaf identity changed')
        self.paths[path] = observed
        return observed[path]

    def bounded(self, path):
        before = self.ordinary(path)
        if not 0 < before[3] <= MAX_FILE:
            raise ValueError('bounded nonempty supplied file required')
        with path.open('rb') as stream:
            if _identity(os.fstat(stream.fileno())) != before:
                raise ValueError('input replaced before capture')
            raw = stream.read(MAX_FILE+1)
            if _identity(os.fstat(stream.fileno())) != before:
                raise ValueError('input changed during capture')
        if self.ordinary(path) != before or len(raw) != before[3]:
            raise ValueError('input pathname changed during capture')
        return before, raw

    def read(self, value, base, expected=None):
        p = Path(value)
        p = p if p.is_absolute() else Path(base).absolute()/p
        before, raw = self.bounded(p)
        sha = hashlib.sha256(raw).hexdigest()
        if expected is not None and sha != expected:
            raise ValueError('supplied source/output bytes changed')
        previous = self.files.get(p)
        if previous is not None and previous != (before, raw):
            raise ValueError('same observation has conflicting input bytes')
        self.files[p] = (before, raw)
        return p, raw

    def pin(self, value, base):
        _keys(value, ('path', 'sha256'), 'MA5 SAF pin')
        if type(value['path']) is not str or not value['path'].strip():
            raise ValueError('nonempty literal pin pathname required')
        if type(value['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
            raise ValueError('SHA256 file identity required')
        return self.read(value['path'], base, value['sha256'])

    def census(self, root):
        root = Path(root)
        self.ordinary(root, directory=True)
        members = list(root.rglob('*'))
        names = set()
        for p in members:
            mode = p.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError('nonordinary member in supplied SAF directory')
            self.ordinary(p, directory=stat.S_ISDIR(mode))
            if stat.S_ISREG(mode) and p.suffix == '.saf':
                names.add(p.relative_to(root).as_posix())
        self.ordinary(root, directory=True)
        return names

    def finish(self):
        for p, (before, raw) in self.files.items():
            now, ending = self.bounded(p)
            if now != before or ending != raw:
                raise ValueError('ending input identity or bytes changed')
        for root, names in self.roots.items():
            if self.census(root) != names:
                raise ValueError('ending SAF membership changed')
        # Recheck all observed ancestors/leaves after the final read/census.
        # This is a finite observation, not a hermetic filesystem sandbox.
        for p, old in list(self.paths.items()):
            self.ordinary(p, directory=len(old[p]) == 3)


def _json(raw):
    def reject(value):
        raise ValueError('nonfinite JSON value: '+value)
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)


def _schema(task, base):
    validate(task)
    capture = Capture(); _, raw = capture.read(task['input'], base)
    doc = _json(raw); capture.finish()
    if doc.get('schema_version') != 2 or type(doc.get('schema_version')) is not int:
        raise contracts.MissingInputError('upstream', 'Convert to the supplied-booking schema2 family')
    contracts.fields(doc, ('analysis', 'source', 'bookings', 'upstream', 'views', 'population_scope'))
    return 2


def inputs(task, base):
    _schema(task, base)
    from ravel.physics import ma5_family
    return [*ma5_family.inputs(task, base), Path(contracts.__file__).resolve()]


def _write_result(out, result, task):
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('ordinary SAF output destination required')
    if 'output' in task:
        contracts.publish(out, result, task['output'])
    else:
        atomic_json(out/'ma5-saf.json', result)


def execution_seconds(task, base):
    validate(task)
    return 30


def _view(texts, expected, population, *, analysis_file='analysis.saf', cutflow_files=None):
    names = reader.regions(texts[analysis_file])
    histograms = reader.histograms(texts['Histograms/histos.saf'])
    if (names != expected['regions']
            or [{k: h[k] for k in ('name', 'nbins', 'xmin', 'xmax', 'regions')} for h in histograms] != expected['histograms']):
        raise ValueError('complete supplied region/histogram population differs from source')
    cutflow_files = ({r: 'Cutflows/'+r+'.saf' for r in names}
                     if cutflow_files is None else cutflow_files)
    cutflows = {r: reader.counters(texts[cutflow_files[r]]) for r in names}
    for region, counters in cutflows.items():
        if [c['name'] for c in counters['cuts']] != expected['cuts'][region]:
            raise ValueError('complete supplied cut population differs from source')
        n = sum(counters['initial'][s]['nentries'] for s in ('positive', 'negative'))
        if n != population:
            raise ValueError('initial event population differs from explicit original view')
    # Both source regions share one event dataset: its complete initial counter is common.
    initial = [c['initial'] for c in cutflows.values()]
    if any(value != initial[0] for value in initial[1:]):
        raise ValueError('same-view initial counter differs between source regions')
    return {'regions': names, 'histograms': histograms, 'cutflows': cutflows,
            'initial_entries': population, 'per_bin_uncertainty_available': False,
            'event_level_covariance_available': False}


def run(task, base, output):
    _schema(task, base)
    from ravel.physics import ma5_family
    return ma5_family.run(task, base, output)
