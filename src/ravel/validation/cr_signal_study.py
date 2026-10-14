"""Ordinary no-fit qualification of a fixed control-region signal intervention.

The original source witness supplies all arithmetic. This adapter binds its
complete inputs, current runtime and returned components to ordinary custody.
Import/intake never compiles or evaluates a model. Run needs ordinary approval.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

from ravel.validation import cr_switch_qualification as witness
from ravel.validation import likelihood_parity as parity
from ravel.workflow.state_io import _unique, atomic_json

MAX_FILE_BYTES = 16 * 1024**2
MAX_CAPTURE_BYTES = 64 * 1024**2
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_JOURNAL_BYTES = 1024**2
PROTOCOL = {"limits": witness.LIMITS, "tolerances": witness.TOLERANCES,
            "backend": "numpy", "precision": "64b", "pyhf_version": "0.7.6",
            "scientific_seconds": 300, "attempts": 1}
SCOPE = "five_vector_CR_signal_response_qualification"


def raw_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def parse(raw):
    def reject(value):
        raise ValueError("nonfinite JSON: " + value)
    result = json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)
    raw_json(result)  # also rejects finite-looking overflow such as 1e999
    return result


def validate(task):
    parity._keys(task, ("input",), "CR response task")
    witness.require(type(task['input']) is str and task['input'].strip(), "input path required")
    return deepcopy(task)


def read_bytes(path):
    """Descriptor-bound limited read; growth/replacement fails before parsing."""
    from ravel.workflow.science import regular
    path = regular(str(path), ".")
    def identity(s):
        return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        before = os.fstat(f.fileno())
        witness.require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE_BYTES,
                        "bounded regular input required")
        raw = f.read(MAX_FILE_BYTES + 1)
        after = os.fstat(f.fileno())
    witness.require(len(raw) <= MAX_FILE_BYTES and len(raw) == before.st_size and
                    identity(before) == identity(after) == identity(path.stat()),
                    "input changed or exceeded bounded read")
    regular(str(path), ".")
    return raw


def capture(task, base):
    from ravel.workflow.science import regular
    captured = {}
    def read(path, sha=None, decode=True):
        path = regular(str(path), base)
        raw = read_bytes(path)
        if sha is not None:
            witness.require(type(sha) is str and len(sha) == 64 and
                            hashlib.sha256(raw).hexdigest() == sha, "input pin differs")
        key = str(path)
        witness.require(key not in captured or captured[key] == raw, "capture changed")
        captured[key] = raw
        witness.require(sum(map(len, captured.values())) <= MAX_CAPTURE_BYTES, "capture exceeds 64 MiB")
        return path, parse(raw) if decode else raw
    path, doc = read(validate(task)['input'])
    parity._keys(doc, ('schema_version', 'workspace', 'compiled_reference', 'runtime_inventory',
                      'measurement', 'signal', 'all_controls', 'expected_membership',
                      'protocol', 'grounding'), 'CR response input')
    witness.require(type(doc['schema_version']) is int and doc['schema_version'] == 1,
                    'integer schema1 required')
    witness.require(raw_json(doc['protocol']) == raw_json(PROTOCOL), 'fixed scientific protocol differs')
    for key in ('measurement', 'signal'):
        witness.require(type(doc[key]) is str and doc[key].strip(), 'explicit ' + key + ' required')
    controls = doc['all_controls']
    witness.require(type(controls) is list and 1 <= len(controls) <= 128 and
                    all(type(x) is str and x for x in controls), 'explicit control channel roster required')
    def bound(pin, decode=True):
        parity._keys(pin, ('path', 'sha256'), 'input binding')
        return read(regular(pin['path'], path.parent), pin['sha256'], decode=decode)[1]
    bound_inputs = {key: bound(doc[key]) for key in ('workspace', 'compiled_reference', 'runtime_inventory')}
    membership = witness.intervention(bound_inputs['workspace'], doc['signal'], controls)
    witness.require(membership == doc['expected_membership'], 'complete CR presence/nominal roster differs')
    reference = bound_inputs['compiled_reference']
    witness.require(reference['pyhf_version'] == PROTOCOL['pyhf_version'], 'reference compiler version differs')
    witness.require(type(doc['grounding']) is list and 1 <= len(doc['grounding']) <= 128,
                    'pinned source/interpretation grounding required')
    for pin in doc['grounding']:
        bound(pin, decode=False)
    return doc, bound_inputs, captured


def inputs(task, base, *, _session=None):
    doc, bound, captured = capture(task, base)
    runtime = parity.runtime_files(bound['runtime_inventory'], _session=_session)
    return list(dict.fromkeys([*(Path(p) for p in captured), *runtime]))


def _validation_inputs(task, base, session):
    return inputs(task, base, _session=session)


def observed_imports(inventory):
    """Bind actually loaded scientific package files to the supplied census.

    This is Python module-origin evidence, not an OS dynamic-loader inventory.
    The supervisor separately binds interpreter/framework/environment inputs.
    """
    pins = {str(Path(row['path']).resolve()): row['sha256'] for row in inventory['files']}
    prefixes = ('pyhf', 'numpy', 'scipy', 'jsonschema', 'jsonpatch', 'jsonpointer', 'iminuit')
    witness.require(all(name in sys.modules for name in ('pyhf', 'numpy')), 'scientific imports absent')
    rows = []
    for name, module in sorted(sys.modules.copy().items()):
        if not any(name == p or name.startswith(p + '.') for p in prefixes):
            continue
        path = getattr(module, '__file__', None)
        if path is None:  # namespace modules have no independently executed file
            continue
        path = str(Path(path).resolve())
        witness.require(path in pins, 'loaded scientific module is outside runtime binding: ' + name)
        rows.append({'module': name, 'path': path, 'sha256': pins[path]})
    return rows


class Recorder:
    """Each completed component is durable before the next numerical call."""
    def __init__(self, out):
        self.out, self.previous, self.sequence, self.journal_bytes = out, None, 0, 0
        self.journal = out / 'progress.jsonl'
        self.journal.touch(exist_ok=False)
        self.expected = {'progress.jsonl': b''}
    def manifest(self):
        return [{'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                for name, raw in sorted(self.expected.items())]
    def verify(self):
        witness.require(not any(p.is_symlink() for p in (self.out, *self.out.parents)),
                        'diagnostic output path changed')
        names = set()
        for path in self.out.iterdir():
            witness.require(path.name in self.expected, 'unexpected diagnostic output: ' + path.name)
            names.add(path.name)
        witness.require(names == set(self.expected), 'diagnostic output membership changed')
        for name, raw in self.expected.items():
            witness.require(read_bytes(self.out / name) == raw, 'diagnostic output changed: ' + name)
    def write_fresh(self, name, state):
        """Fresh terminal records never replace prior or corrupted evidence."""
        raw = (json.dumps(state, indent=2, allow_nan=False) + '\n').encode()
        witness.require(len(raw) <= MAX_CHECKPOINT_BYTES, 'terminal record exceeds bound')
        witness.require(name not in self.expected and
                        not any(p.is_symlink() for p in (self.out, *self.out.parents)),
                        'unowned terminal record or output path')
        self.expected[name] = raw
        with (self.out / name).open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    def __call__(self, state):
        raw = raw_json(state)
        persisted = (json.dumps(state, indent=2, allow_nan=False) + '\n').encode()
        witness.require(len(persisted) <= MAX_CHECKPOINT_BYTES, 'checkpoint exceeds bound')
        target = self.out / 'checkpoint.json'
        self.verify()
        # Check journal allowance before replacing the checkpoint.
        row = {'sequence': self.sequence, 'previous': self.previous,
               'state_sha256': hashlib.sha256(persisted).hexdigest(),
               'canonical_state_sha256': hashlib.sha256(raw).hexdigest(), 'status': state.get('status')}
        line = raw_json(row) + b'\n'
        witness.require(self.journal_bytes + len(line) <= MAX_JOURNAL_BYTES, 'journal exceeds bound')
        # Atomic pretty JSON changes byte spelling; retain its actual digest.
        self.expected['checkpoint.json'] = persisted
        atomic_json(target, state)
        self.previous = hashlib.sha256(persisted).hexdigest()
        self.expected['progress.jsonl'] += line
        with self.journal.open('ab') as f:
            f.write(line); f.flush(); os.fsync(f.fileno())
        self.journal_bytes += len(line); self.sequence += 1
        self.verify()


def run(task, base, output):
    from ravel.physics.finite_mc_model import _admit_output
    out = _admit_output(output)
    started = time.monotonic()
    recorder = Recorder(out)
    captured, result, bound, imported = {}, None, None, []
    error, ending_errors, runtime_before, runtime_after = None, [], False, False
    try:
        doc, bound, captured = capture(task, base)
        parity.runtime_files(bound['runtime_inventory'])
        runtime_before = True
        # No pyhf import until approved execution and fresh input custody pass.
        import importlib.metadata
        witness.require(importlib.metadata.version('pyhf') == PROTOCOL['pyhf_version'],
                        'actual compiler version differs')
        result = witness.qualify(bound['workspace'], measurement=doc['measurement'],
            signal=doc['signal'], all_controls=doc['all_controls'],
            original_reference=bound['compiled_reference'], engine=witness.PyhfEngine(), persist=recorder)
        imported = observed_imports(bound['runtime_inventory'])
        witness.require(result['passed'] is True and result['status'] == 'completed' and
                        len(result['calls']) == 45 and len(result['compilations']) == 3 and
                        len(result['rows']) == 5, 'complete fixed-vector qualification did not pass')
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    # Fresh end observations run on failure too; no rewrite of numerical state.
    for path, raw in captured.items():
        try:
            if read_bytes(path) != raw:
                ending_errors.append(path)
        except Exception as exc:
            ending_errors.append({'path': path, 'error': str(exc)})
    if bound is not None:
        try:
            parity.runtime_files(bound['runtime_inventory'])
            runtime_after = True
        except Exception as exc:
            ending_errors.append({'runtime': str(exc)})
    try:
        recorder.verify()
    except Exception as exc:
        ending_errors.append({'diagnostic_outputs': str(exc)})
    elapsed = time.monotonic() - started
    if elapsed > PROTOCOL['scientific_seconds']:
        ending_errors.append('adapter cooperative 300-second deadline exceeded')
    passed = error is None and not ending_errors and runtime_before and runtime_after
    summary = {'schema_version': 1, 'status': 'passed' if passed else 'failed', 'scope': SCOPE,
        'physics_validated': False, 'optimizer_calls': 0, 'generated_events': 0, 'root_searches': 0,
        'protocol': deepcopy(PROTOCOL), 'error': error, 'ending_errors': ending_errors,
        'runtime_before_passed': runtime_before, 'runtime_after_passed': runtime_after,
        'observed_scientific_imports': imported,
        'checkpoint': 'checkpoint.json' if recorder.previous else None,
        'checkpoint_sha256': recorder.previous, 'elapsed_seconds': elapsed,
        'expected_diagnostic_outputs': recorder.manifest(),
        'source_inputs': [{'path': p, 'sha256': hashlib.sha256(raw).hexdigest()} for p, raw in captured.items()],
        'limitations': ['Shared compiled main means; independent scalar auxiliary/full density assembly only.',
            'Only five fixed vectors, no interpolation proof, optimizer qualification, profile limit or coverage.',
            'CR-only intervention preserves existing constraints; it is not nuisance removal or MPI attribution.',
            'Structural flat-direction candidates are reported, never pruned.',
            'The ordinary supervisor and its ending custody, not this cooperative final save, establish timed delivery.']}
    try:
        recorder.write_fresh('cr-signal-result.json', summary)
        recorder.verify()
        witness.require(time.monotonic() - started <= PROTOCOL['scientific_seconds'],
                        'adapter cooperative 300-second deadline exceeded during final persistence')
    except Exception as exc:
        # Preserve every changed/partial file. A separate exclusive failure
        # record prevents late corruption from becoming successful delivery.
        summary = deepcopy(summary)
        summary['status'] = 'failed'
        summary['ending_errors'].append({'terminal_outputs': str(exc)})
        summary['expected_terminal_outputs'] = recorder.manifest()
        summary['delivery_failure_record'] = 'delivery-failure.json'
        recorder.write_fresh('delivery-failure.json', summary)
        # Verify the failure record itself without rewriting the known-bad files.
        witness.require(read_bytes(out / 'delivery-failure.json') == recorder.expected['delivery-failure.json'],
                        'terminal failure record changed')
    return summary


def execution_seconds(task, base):
    validate(task)
    return PROTOCOL['scientific_seconds']


def resource_bounds(task, base):
    validate(task)
    return {'processes': 2, 'maximum_mathematical_workers': 1, 'threads': 1,
            'maximum_native_children': 0, 'model_compilations': 3, 'evaluator_calls': 45,
            'mathematical_seconds': 120, 'scientific_seconds': 300,
            'fits': 0, 'generated_events': 0, 'capture_bytes': MAX_CAPTURE_BYTES,
            'checkpoint_bytes': MAX_CHECKPOINT_BYTES, 'journal_bytes': MAX_JOURNAL_BYTES,
            'maximum_terminal_records': 2, 'terminal_record_bytes_each': MAX_CHECKPOINT_BYTES,
            'maximum_expected_output_bytes': 3 * MAX_CHECKPOINT_BYTES + MAX_JOURNAL_BYTES}
