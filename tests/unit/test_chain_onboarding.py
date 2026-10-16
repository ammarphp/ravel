"""A new fictional operation joins real readers with only adapter and contract edits."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ravel.workflow import knowledge_atlas

ROOT = Path(__file__).resolve().parents[2]
NAME = 'synthetic-chain-selection'
CONTRACT = 'src/ravel/data/operation_signatures.json'
UNCHANGED = ('src/ravel/data/roles/executors.json', 'src/ravel/data/roles/registry.json',
             'src/ravel/data/mode_descriptors.json', 'native/setup/toolchain-manifest.json',
             'docs/workflow/reference/scientific-studies.md')


@pytest.fixture(scope='module')
def candidate(tmp_path_factory):
    root = tmp_path_factory.mktemp('synthetic-onboarding')
    atlas = knowledge_atlas.generate(ROOT)
    for pin in atlas['generator']['sources']:
        target = root / pin['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / pin['path'], target)
    shutil.copytree(ROOT / 'src/ravel', root / 'src/ravel', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Complete setup data supports its unchanged ordinary validator.
    shutil.copytree(ROOT / 'native/setup', root / 'native/setup', dirs_exist_ok=True)
    document = json.loads((root / CONTRACT).read_text())
    row = deepcopy(document['operations']['columnar-analysis'])
    row['summary'] = 'Synthetic supplied-event selection.'
    row['implementation'] = {'kind': 'science-mode', 'mode': NAME,
                             'module': 'ravel.physics.synthetic_chain_selection',
                             'dispatch_group': 'event-inference-chain', 'presentation': 'present'}
    descriptor = json.loads((root / 'src/ravel/data/mode_descriptors.json').read_text())['modes']['columnar-analysis']
    curation = json.loads((root / 'src/ravel/data/knowledge/curation/columnar-analysis.json').read_text())['op']
    for example in curation['examples']:
        example['spec']['mode'] = NAME
    row['registration'] = {
        'executor': 'analysis-author', 'descriptor': descriptor, 'setup_groups': ['python-host'],
        'documentation': [{'path': 'docs/workflow/reference/scientific-studies.md',
                           'section': 'Generated-event quantity handoffs'}],
        'curation': curation,
    }
    document['operations'][NAME] = row
    (root / CONTRACT).write_text(json.dumps(document))
    (root / 'src/ravel/physics/synthetic_chain_selection.py').write_text(
        '"""Synthetic compatibility adapter for supplied selections."""\n'
        'from ravel.physics.columnar_analysis import validate, inputs, run\n'
        'def present(result):\n    return result, "Synthetic selection delivery."\n')
    return root, document


def execute(root, body):
    env = dict(os.environ, PYTHONPATH=str(root / 'src'), RAVEL_ROOT=str(root),
               PYTHONDONTWRITEBYTECODE='1')
    script = f'from pathlib import Path\nroot = Path({str(root)!r})\nname = {NAME!r}\n' + body
    result = subprocess.run([sys.executable, '-c', script], cwd=root, env=env,
                            text=True, capture_output=True, timeout=150)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    return result.stdout


def test_adapter_contract_and_tests_only_through_real_fresh_process(candidate, record_property):
    root, _ = candidate
    for relative in UNCHANGED:
        assert (root / relative).read_bytes() == (ROOT / relative).read_bytes()
    output = execute(root, '''
import json
from ravel.workflow import science, capability_routing, production_executor, role_registry, knowledge_atlas
from ravel.physics.science_worker import diagnostic_presentation
from ravel.setup import manifest, doctor
from ravel.validation import signature_conformance, check_knowledge
from ravel.validation.validate_request_plan import signatures
assert science.MODES[-1] == name and science.MODES.count(name) == 1
adapter = science.adapter({'mode': name, 'task': {}})
assert adapter.__name__ == 'ravel.physics.synthetic_chain_selection'
assert diagnostic_presentation(name, {'value': 7}) == ({'value': 7}, 'Synthetic selection delivery.')
catalogue = capability_routing.catalogue(root)
offered = next(row for row in catalogue['operations'] if row['mode'] == name)
assert offered['status'] == 'source_present_not_admitted' and offered['descriptor']
table = production_executor.executors()
assert table['operations'][name] == 'analysis-author'
assert name in role_registry.load('analysis-author')['operations']
assert production_executor.completeness_errors() == []
assert signature_conformance.entry_errors(name, signatures()[name]) == []
installed, _ = manifest.load(root)
assert [row['mode'] for row in installed['operations']][:len(science.MODES)] == list(science.MODES)
assert doctor.select_groups(installed, mode=name) == ['compiler-bootstrap', 'python-host']
atlas = knowledge_atlas.generate(root)
row = next(row for row in atlas['entries'] if row['id'] == 'op:' + name)
assert row['op']['validation_tier'] == 'registered'
assert row['op']['examples'] and row['links']['docs']
errors = check_knowledge.validate(root, atlas)
assert not errors, errors
surface = role_registry.render('governed-node')
for relative, text in surface.items():
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
assert not role_registry.check_rendered(root, surfaces=('governed-node',))
victim = root / role_registry.profile_paths('governed-node')['analysis-author']
victim.write_text('{}')
assert role_registry.check_rendered(root, surfaces=('governed-node',))
stale = json.loads(json.dumps(atlas))
stale['entries'] = [row for row in stale['entries'] if row['id'] != 'op:' + name]
assert any('drift or omission' in error for error in check_knowledge.validate(root, stale))
print(json.dumps({'central_metadata_edits': 1, 'extra_authored_tables': 0, 'mode': name,
                  'qualification': row['op']['validation_tier']}))
''')
    record_property('onboarding', output.strip())
    record_property('unchanged_source_sha256', json.dumps({p: hashlib.sha256((root / p).read_bytes()).hexdigest()
                                                         for p in UNCHANGED}, sort_keys=True))


@pytest.mark.parametrize('fault', ['missing-section', 'missing-doc', 'unknown-role', 'bad-example'])
def test_incomplete_onboarding_still_refuses_in_real_consumers(candidate, fault):
    root, document = candidate
    broken = deepcopy(document)
    declaration = broken['operations'][NAME]['registration']
    if fault == 'missing-section':
        declaration['documentation'][0]['section'] = 'Absent synthetic section'
    elif fault == 'missing-doc':
        declaration['documentation'][0]['path'] = 'docs/absent-synthetic-file.md'
    elif fault == 'unknown-role':
        declaration['executor'] = 'synthetic-missing-role'
    else:
        declaration['curation']['examples'][0]['spec']['task'] = {'unknown': True}
    (root / CONTRACT).write_text(json.dumps(broken))
    try:
        if fault == 'unknown-role':
            execute(root, '''
from ravel.workflow.production_executor import completeness_errors
assert any('not a registered production role' in error for error in completeness_errors())
''')
        elif fault == 'bad-example':
            execute(root, '''
from ravel.workflow.knowledge_atlas import generate
from ravel.validation.check_knowledge import validate
assert any('offline example refused' in error for error in validate(root, generate(root)))
''')
        else:
            execute(root, '''
from ravel.workflow.knowledge_atlas import generate
try:
    generate(root)
except ValueError as error:
    assert 'registration.documentation' in str(error), str(error)
else:
    raise AssertionError('invalid documentation accepted')
''')
    finally:
        (root / CONTRACT).write_text(json.dumps(document))
