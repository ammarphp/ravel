"""Private paired-effect intake. No simulator, ROOT runtime or optimizer is loaded.

This checks retained content/producer witnesses and exact trace-file custody.
It does not substitute for the original provenance verifier, accepted observer
qualification, ordinary stage admission, or the effect run's final custody.
"""
from pathlib import Path
import gzip
import hashlib
import json
import math

from ravel.validation import diagnostic_plan as plans


def require(value, message):
    if not value:
        raise ValueError(message)


def same_pin(left, right):
    return all(left.get(key) == right.get(key) for key in ('path', 'sha256', 'bytes'))


def validate_arm(expected, transport, trace_header, trace_rows, current_files,
                 transport_pin, command_receipts, selection_sources, descriptor):
    """Pure admission on already read evidence; no arithmetic inference or RNG."""
    from ravel.validation.mpi_paired.mpi_identity_transport import original_map
    n = expected['subset_exposure']
    require(type(n) is int and n > 1, 'Complete positive paired cohort required')
    require(transport.get('status') == 'transport_verified' and transport.get('events') == n,
            'Actual complete original-content transport required')
    require(set(transport.get('source_files', {})) ==
            {'expected_manifest', 'lhe', 'sidecar', 'hepmc', 'delphes', 'ntuple', 'trace'},
            'Complete original-content/downstream file census required')
    for key, value in transport['source_files'].items():
        require(key in current_files and same_pin(value, current_files[key]),
                'Current identity source bytes differ: ' + key)
    require(same_pin(current_files['lhe'], expected['subset_pin']), 'Different hard-event cohort')
    mapping = original_map(expected, transport['original_content_witness'])
    require(mapping == transport['mapping'], 'Reported map differs from full-content witness')
    require(len({row['original_content_sha256'] for row in mapping}) == n,
            'Full original content is not unique within cohort')
    # Every native product, including the identity report, must be tied to a
    # completed producer. Supplied success fields alone cannot supply custody.
    products = [current_files[key] for key in ('sidecar', 'hepmc', 'delphes', 'ntuple', 'trace')]
    products.append(transport_pin)
    artifacts = []
    require(type(command_receipts) is list and command_receipts, 'Native command receipts required')
    for receipt in command_receipts:
        require(receipt.get('status') == 'completed' and receipt.get('actual_returncode') == 0
                and receipt.get('expected_returncode') == 0 and not receipt.get('timed_out', False),
                'Every declared producer must have completed cleanly')
        require(isinstance(receipt.get('argv'), list) and receipt['argv'], 'Actual producer argv required')
        require(type(receipt.get('pid')) is int and receipt['pid'] > 0, 'Actual producer identity required')
        artifacts.extend(receipt.get('artifacts', []))
    for product in products:
        require(sum(same_pin(product, artifact) for artifact in artifacts) == 1,
                'Generated file needs exactly one bound completed producer: ' + product['path'])
    require(trace_header.get('kind') == 'header' and trace_header.get('schema_version') == 1
            and trace_header.get('level') == 'reco' and trace_header.get('weight_unit') == 'pb',
            'Declared reconstruction trace/unit required')
    metadata = trace_header.get('metadata', {})
    require(metadata.get('input_events') == n and
            metadata.get('input_sha256') == current_files['ntuple']['sha256'],
            'Trace is not bound to this complete converted ntuple')
    require(all(metadata.get(k)==v for k,v in plans.required(descriptor,'trace_metadata').items()),'supplied trace recipe differs')
    for key in ('selection_source_sha256', 'diagnostic_source_sha256', 'rjr_binary_sha256'):
        require(metadata.get(key) == selection_sources[key], 'Trace source recipe differs: ' + key)
    require(type(trace_rows) is list and len(trace_rows) == n, 'Every hard event must remain in trace')
    categories = []
    weights = []
    for index, row in enumerate(trace_rows):
        require(type(row.get('event_id')) is int and row['event_id'] == index,
                'Trace population is skipped, duplicated, reordered or replaced')
        accepted = row.get('accepted_regions')
        require(type(accepted) is list and all(type(value) is str for value in accepted)
                and len(set(accepted)) == len(accepted), 'Unique literal accepted regions required')
        selected = [i + 1 for i, region in enumerate(descriptor['regions']) if region in accepted]
        require(len(selected) <= 1, 'supplied exclusive region overlap')
        categories.append(selected[0] if selected else 0)
        weight = row.get('weight_pb')
        require(type(weight) in (int, float) and math.isfinite(weight) and weight > 0,
                'This contrast requires finite positive constant trace weights')
        weights.append(float(weight).hex())
    require(len(set(weights)) == 1, 'Trace weights are not constant')
    return {'mapping': mapping, 'categories': categories, 'constant_weight_hex': weights[0],
            'category_count':len(descriptor['regions'])+1, 'events': n, 'trace_pin': current_files['trace'], 'transport_pin': transport_pin}


def paired_census(on, off):
    """Authenticate the complete pair association before any ratio or bootstrap."""
    require(on['mapping'] == off['mapping'] and on['events'] == off['events'],
            'Arms do not contain the same original hard-event population')
    require(on['constant_weight_hex'] == off['constant_weight_hex'], 'Arm normalization weights differ')
    n = on['events']
    require(len(on['categories']) == len(off['categories']) == n, 'Incomplete categorical exposure')
    require(on['category_count']==off['category_count'],'category populations differ')
    dimension=on['category_count']
    census = [[0] * dimension for _ in range(dimension)]
    for left, right in zip(on['categories'], off['categories']):
        require(type(left) is int and type(right) is int and 0 <= left < dimension and 0 <= right < dimension,
                'Invalid exclusive category')
        census[left][right] += 1
    return census


def read_arm(*, expected_pin, transport_pin, command_pins, selection_sources, descriptor, check_budget):
    """Fresh regular-file reads and before/after pins within an admitted effect job.

    Caller supplies its prospective deadline/resource callback. This function
    does not authorize any job, create an output, or invoke an estimator.
    """
    cache = {}
    def pin(path):
        check_budget()
        path = Path(path).absolute()
        require(path.is_file() and not path.is_symlink(), 'Regular owned/input file required')
        before = path.stat()
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                check_budget()
                h.update(chunk)
        after = path.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                'File changed while hashing')
        return {'path': str(path), 'bytes': after.st_size, 'sha256': h.hexdigest()}
    def checked(expected):
        actual = pin(expected['path'])
        require(same_pin(actual, expected), 'Declared evidence bytes changed')
        cache[actual['path']] = actual
        return Path(actual['path'])
    expected = json.loads(checked(expected_pin).read_text())
    transport = json.loads(checked(transport_pin).read_text())
    commands = [json.loads(checked(p).read_text()) for p in command_pins]
    files = transport['source_files']
    require(same_pin(files['expected_manifest'], expected_pin), 'Transport used another identity manifest')
    current = {name: pin(value['path']) for name, value in files.items()}
    for name, value in files.items():
        require(same_pin(value, current[name]), 'Identity source changed before interpretation: ' + name)
    cache.update({value['path']: value for value in current.values()})
    trace = Path(current['trace']['path'])
    opener = gzip.open if trace.suffix == '.gz' else open
    rows = []
    with opener(trace, 'rt') as stream:
        header = json.loads(next(stream))
        for line in stream:
            check_budget()
            require(len(rows) < expected['subset_exposure'], 'Trace exceeds declared exposure')
            rows.append(json.loads(line))
    admitted = validate_arm(expected, transport, header, rows, current, transport_pin,
                            commands, selection_sources, descriptor)
    for old in cache.values():
        require(same_pin(old, pin(old['path'])), 'Evidence changed during paired intake')
    return admitted, rows, transport
