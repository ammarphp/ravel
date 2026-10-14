"""Explicit package inputs for synthetic migration controls."""
import synthetic_identifiers as syn
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def selected_manifest(label):
    return ROOT / 'analysis-packages' / label / 'manifest.json'


def manifest_pin(label):
    path = selected_manifest(label)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def native_package(path, name, regions, *, models, statistics=('yields', 'mapped-likelihood'), preparations=('explicit-cards',),
                   helper_outputs=()):
    """An inert supplied implementation with synthetic interface qualification."""
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'selection.py'
    source.write_text('NAME = ' + repr(name) + '\nFLAVOUR_FLAGS = ("isee", "ismm")\n'
                      + 'def sr_order(): return ' + repr(list(regions)) + '\n'
                      + 'def select(arrays, i): return None\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    compatibility = {'models': list(models), 'preparations': list(preparations),
                     'detectors': ['simpleanalysis-delphes'], 'statistics': list(statistics)}
    evidence = root / 'qualification.json'
    evidence.write_text(json.dumps({'schema_version': 1, 'kind': 'routine-qualification', 'status': 'passed',
        'interface_version': 1, 'selection_sha256': digest, 'compatibility': compatibility,
        'checks': [{'name': 'synthetic-only', 'passed': True, 'reference': 1., 'computed': 1., 'rtol': 0., 'atol': 0.}]}))
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'kind': 'analysis-package', 'package_id': name,
        'package_version': '1.0', 'analysis_ids': [name, (syn.analysis(907, 97))], 'compatibility': compatibility,
        'routine': {'path': 'selection.py', 'sha256': digest, 'kind': 'counting', 'regions': list(regions),
                    'flavour_flags': ['isee', 'ismm'], 'helper_outputs': list(helper_outputs), 'arguments': []},
        'qualification': {'status': 'qualified', 'evidence': [{'path': evidence.name,
            'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]}}))
    return manifest


def qualify_fixture(tmp_path, source_manifest):
    """Copy a selection input and bind a synthetic interface report; no native qualification."""
    import shutil
    root = Path(tmp_path) / 'selected-package'
    root.mkdir(exist_ok=True)
    document = json.loads(Path(source_manifest).read_text())
    shutil.copyfile(Path(source_manifest).parent / document['routine']['path'], root / document['routine']['path'])
    evidence = root / 'qualification.json'
    evidence.write_text(json.dumps({'schema_version': 1, 'kind': 'routine-qualification', 'status': 'passed',
        'interface_version': 1, 'selection_sha256': document['routine']['sha256'],
        'compatibility': document['compatibility'], 'checks': [{'name': 'synthetic-interface-only', 'passed': True, 'reference': 1., 'computed': 1., 'rtol': 0., 'atol': 0.}]}))
    document['qualification'] = {'status': 'qualified', 'evidence': [{'path': evidence.name,
        'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
    selected = root / 'manifest.json'
    selected.write_text(json.dumps(document))
    return selected
