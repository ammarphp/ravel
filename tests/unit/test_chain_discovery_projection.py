"""Synthetic selected-source discovery and setup projection controls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ravel.setup import manifest
from ravel.workflow import capability_routing


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + '\n', encoding='utf-8')


def signature(name='synthetic-operation', *, groups=None):
    return {
        'implementation': {'kind': 'science-mode', 'mode': name,
                           'module': 'ravel.physics.synthetic_adapter',
                           'dispatch_group': 'event-inference-chain'},
        'registration': {
            'executor': 'analysis-author',
            'setup_groups': ['synthetic-group'] if groups is None else groups,
            'documentation': [{'path': 'docs/workflow/reference/scientific-studies.md',
                               'section': 'Synthetic supplied quantities'}],
            'curation': {'use_when': ['Process supplied synthetic packets.'],
                         'do_not_use_when': ['Required packets are absent.'],
                         'examples': [{'phrase': 'Process supplied synthetic packets.',
                                       'spec': {'mode': name, 'task': {}}}]},
            'descriptor': {'summary': 'Process supplied synthetic packets.',
                           'operations': ['prediction'], 'tools': ['synthetic-tool'],
                           'inputs': ['synthetic packets'], 'observables': [],
                           'outputs': ['synthetic table'], 'context': [],
                           'applicability': {'scope': 'general'}},
        },
    }


def signatures_document(row):
    return {'schema_version': 1, 'operations': {'synthetic-operation': row}}


def selected_source(root, row=None):
    package = root / 'src/ravel'
    files = {
        'workflow/science.py': (
            "MODES = ('base-operation',)\n"
            'from .operation_definitions import populate_modes as _chain_modes\n'
            'MODES = _chain_modes(MODES)\n'
            'def adapter(spec):\n'
            '    from .operation_definitions import adapter_for\n'
            "    discovered = adapter_for(spec['mode'])\n"
            '    if discovered is not None:\n'
            '        return discovered\n'
            "    return {'base-operation': 'base_adapter'}\n"
            "raise AssertionError('selected dispatcher was imported')\n"),
        'workflow/operation_definitions.py': "LEGACY_BINDINGS = {}\nraise AssertionError('selected helper was imported')\n",
        'workflow/operation_registration.py': "raise AssertionError('selected registration was imported')\n",
        'physics/native_capabilities.py': "CAPABILITIES = {}\nraise AssertionError('selected native source was imported')\n",
        'physics/base_adapter.py': 'def validate(): pass\ndef inputs(): pass\ndef run(): pass\n',
        'physics/synthetic_adapter.py': (
            'def validate(): pass\ndef inputs(): pass\ndef run(): pass\n'
            "raise AssertionError('selected adapter was imported')\n"),
    }
    for relative in ('workflow/intake.py', 'workflow/route_prompt.py', 'workflow/cost_preflight.py',
                     'validation/validate_task_contract.py', 'workflow/resource_census.py',
                     'workflow/routine_fetch.py', 'plotting/figure_target.py',
                     'plotting/figure_manifest.py', 'plotting/science_figures.py', 'analysis_catalog.py'):
        files[relative] = ''
    for relative, text in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    write_json(package / 'data/operation_signatures.json', signatures_document(row or signature()))
    write_json(package / 'data/roles/executors.json', {'operations': {'base-operation': 'analysis-author'}})
    write_json(package / 'data/mode_descriptors.json', {
        'schema_version': 1, 'weights': {key: 1 for key in capability_routing.DESCRIPTOR_FIELDS[2:]},
        'threshold': 1, 'modes': {},
    })
    return package


@pytest.fixture(autouse=True)
def no_native_discovery(monkeypatch):
    from ravel.physics import native_capabilities
    monkeypatch.setattr(native_capabilities, 'discover_capabilities', lambda: {})


def test_contract_only_selected_source_discovers_adapter_and_descriptor(tmp_path):
    package = selected_source(tmp_path)
    catalog = capability_routing.catalogue(tmp_path)
    rows = {row['mode']: row for row in catalog['operations']}
    assert list(rows) == ['base-operation', 'synthetic-operation']
    row = rows['synthetic-operation']
    assert row['module'] == 'ravel.physics.synthetic_adapter'
    assert row['entrypoints'] == ['inputs', 'run', 'validate']
    assert row['descriptor']['inputs'] == ['synthetic packets']
    assert row['status'] == 'source_present_not_admitted'
    assert not catalog['compute_authorized'] and not catalog['physics_validated']
    pins = {pin['path']: pin for pin in catalog['source_pins']}
    helper = package / 'workflow/operation_registration.py'
    assert pins[str(helper)]['sha256'] == hashlib.sha256(helper.read_bytes()).hexdigest()
    assert all(Path(pin).is_relative_to(tmp_path) for pin in pins)


def test_two_selected_sources_keep_distinct_contracts_and_pins(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    selected_source(first)
    row = signature()
    row['registration']['descriptor']['inputs'] = ['other packets']
    package = selected_source(second, row)
    (package / 'physics/synthetic_adapter.py').write_text('def run(): pass\n', encoding='utf-8')
    a = capability_routing.catalogue(first)['operations'][-1]
    b = capability_routing.catalogue(second)['operations'][-1]
    assert a['descriptor']['inputs'] == ['synthetic packets']
    assert b['descriptor']['inputs'] == ['other packets']
    assert a['source']['path'] != b['source']['path']
    assert a['source']['sha256'] != b['source']['sha256']
    assert a['entrypoints'] == ['inputs', 'run', 'validate'] and b['entrypoints'] == ['run']


def test_standalone_loader_projects_selected_contract(tmp_path):
    selected_source(tmp_path)
    spec = importlib.util.spec_from_file_location('synthetic_catalogue_loader', capability_routing.__file__)
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    assert loader.catalogue(tmp_path)['operations'][-1]['descriptor']['tools'] == ['synthetic-tool']


def test_packaged_descriptor_hints_project_the_same_contract(tmp_path, monkeypatch):
    package = selected_source(tmp_path)
    monkeypatch.setattr(capability_routing, '__file__', str(package / 'workflow/capability_routing.py'))
    monkeypatch.setattr(capability_routing, '_DECLARED', None)
    rows = capability_routing.declared_descriptors()
    assert list(rows) == ['synthetic-operation']
    assert rows['synthetic-operation']['descriptor']['inputs'] == ['synthetic packets']


def test_partial_selected_source_has_no_installed_registration_fallback(tmp_path):
    package = selected_source(tmp_path)
    (package / 'data/operation_signatures.json').unlink()
    catalog = capability_routing.catalogue(tmp_path)
    assert [row['mode'] for row in catalog['operations']] == ['base-operation']
    assert catalog['operations'][0]['descriptor'] is None
    assert not any(pin['path'].endswith('/operation_registration.py') for pin in catalog['source_pins'])


@pytest.mark.parametrize('surface', ['executor', 'descriptor'])
def test_conflicting_raw_discovery_metadata_is_refused(tmp_path, surface):
    package = selected_source(tmp_path)
    if surface == 'executor':
        path = package / 'data/roles/executors.json'
        document = json.loads(path.read_text())
        document['operations']['synthetic-operation'] = 'calculation'
    else:
        path = package / 'data/mode_descriptors.json'
        document = json.loads(path.read_text())
        document['modes']['synthetic-operation'] = deepcopy(signature()['registration']['descriptor'])
        document['modes']['synthetic-operation']['summary'] = 'Conflicting supplied declaration.'
    write_json(path, document)
    with pytest.raises(ValueError, match='conflict'):
        capability_routing.catalogue(tmp_path)


def setup_tree(root, row=None):
    document = {'groups': [{'id': 'synthetic-group'}],
                'operations': [{'mode': 'base-operation', 'groups': ['synthetic-group']}],
                'retained': {'value': 'unchanged'}}
    write_json(root / 'native/setup/toolchain-manifest.json', document)
    if row is not None:
        write_json(root / 'src/ravel/data/operation_signatures.json', signatures_document(row))
    return document


def test_setup_projects_selected_signature_without_rewriting_old_rows(tmp_path):
    original = setup_tree(tmp_path, signature())
    document = manifest.view(tmp_path)
    assert document['groups'] == original['groups']
    assert document['retained'] == original['retained']
    assert document['operations'] == original['operations'] + [
        {'mode': 'synthetic-operation', 'groups': ['synthetic-group']}]


def test_partial_setup_tree_never_uses_installed_signatures(tmp_path):
    original = setup_tree(tmp_path)
    assert manifest.view(tmp_path) == original


@pytest.mark.parametrize('groups', [[], ['missing-group']])
def test_setup_refuses_missing_or_unknown_required_groups(tmp_path, groups):
    setup_tree(tmp_path, signature(groups=groups))
    with pytest.raises(manifest.ManifestError):
        manifest.view(tmp_path)


def test_setup_refuses_conflicting_raw_operation(tmp_path):
    document = setup_tree(tmp_path, signature())
    document['groups'].append({'id': 'other-group'})
    document['operations'].append({'mode': 'synthetic-operation', 'groups': ['other-group']})
    write_json(tmp_path / 'native/setup/toolchain-manifest.json', document)
    with pytest.raises(manifest.ManifestError, match='conflict'):
        manifest.view(tmp_path)


def test_setup_positions_contract_row_before_its_declared_anchor(tmp_path):
    row = signature()
    row['implementation'].update(dispatch_position=0, dispatch_before='base-operation')
    original = setup_tree(tmp_path, row)
    assert manifest.view(tmp_path)['operations'] == [
        {'mode': 'synthetic-operation', 'groups': ['synthetic-group']}, *original['operations']]
