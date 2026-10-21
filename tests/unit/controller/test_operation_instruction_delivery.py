"""Operation-owned source instructions reach the installed executor's packet."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ravel import evidence_layout
from ravel.controller import instructions as ins
from ravel.controller.instructions import catalogue, compiler, delivery
from ravel.controller.routes import study
from ravel.paths import package_data_path
from ravel.workflow import role_registry


def population():
    signatures = json.loads(package_data_path('operation_signatures.json').read_text())['operations']
    executors = json.loads(package_data_path('roles', 'executors.json').read_text())
    owners = executors['operations']
    if evidence_layout.is_public_tree(Path(__file__).resolve().parents[3]):
        # A release withholds the operations of the groups it withholds, signature and instructions
        # together; the operations it ships all have both.
        owners = {name: role for name, role in owners.items() if name in signatures}
    return signatures, owners


def test_every_executable_signature_injects_operation_owned_sources():
    signatures, owners = population()
    cat = catalogue.installed()
    executors = json.loads(package_data_path('roles', 'executors.json').read_text())
    assert set(signatures) <= set(owners) | set(executors['host_operations'])
    assert set(signatures) == set(cat.manifests.get('operations', {}))
    for name, signature in signatures.items():
        selectors = study._operation_instructions({'operation': name, 'signature': signature})
        assert 'operation:' + name in selectors, name
        rows = cat.resolve_all(selectors)
        assert rows, name
        signature_id = cat.manifests['operations'][name]['signature']
        assert signature_id in rows
        assert json.loads(cat.units[signature_id]['text']) == signature


def test_every_executor_receives_its_signature_and_linked_knowledge_with_a_neutral_preamble():
    signatures, owners = population()
    cat = catalogue.installed()
    for name in owners:
        card = role_registry.load(owners[name])
        step = {'id': 'execute', 'kind': 'operate', 'operation': name, 'role': card['id']}
        manifest = ins.manifest(step, card)
        delivered = {row['id'] for row in manifest['units']}
        expected = cat.resolve('operation:' + name)
        assert expected and set(expected) <= delivered, name
        packet = ins.packet(manifest, card, step, [])
        assert all(cat.units[uid]['text'] in packet['text'] for uid in expected
                   if cat.units[uid]['kind'] == 'duty'), name
        preamble = '\n'.join(cat.units[row['id']]['text'] for row in manifest['units'] if row['via'] == 'preamble')
        assert 'pyhf' not in preamble.lower() and 'mass-plane' not in preamble.lower()
        assert delivery.seat_scope(step, card)['operation'] == name
        for identity in cat.manifests['operations'][name]['knowledge']:
            assert set(cat.resolve('knowledge:' + identity)) <= delivered, (name, identity)


def test_a_real_operation_packet_carries_the_source_body_and_refuses_its_removal():
    signatures, owners = population()
    cat = catalogue.installed()
    name = next(name for name in sorted(owners) if cat.manifests['operations'][name]['knowledge'])
    card = role_registry.load(owners[name])
    step = {'id': 'execute', 'kind': 'operate', 'operation': name, 'role': card['id'],
            'instruction_sources': study._operation_instructions({'operation': name, 'signature': signatures[name]})}
    manifest = ins.manifest(step, card)
    packet = ins.packet(manifest, card, step, [])
    units = cat.resolve('operation:' + name)
    assert all(cat.units[uid]['text'] in packet['text'] for uid in units if cat.units[uid]['kind'] == 'duty')
    assert ins.check_packet(packet, manifest, card, step, []) == []
    text = packet['text'].replace(cat.units[units[0]]['text'], 'changed source')
    changed = {**packet, 'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
    assert ins.check_packet(changed, manifest, card, step, [])


def test_operation_source_projection_is_current_and_every_unit_has_a_delivery_route():
    cat = catalogue.installed()
    assert catalogue.coverage_problems(cat) == []
    signatures, _ = population()
    for name, signature in signatures.items():
        assert cat.manifests['operations'][name]['signature_sha256'] == compiler.digest_value(signature)


def test_study_injection_refuses_a_signature_from_a_different_source_epoch():
    signatures, _ = population()
    name = next(iter(signatures))
    changed = deepcopy(signatures[name])
    changed['summary'] = 'Changed operation declaration'
    with pytest.raises(ValueError, match='instruction signature'):
        study._operation_instructions({'operation': name, 'signature': changed})


def source_tree(tmp_path):
    from test_p03_catalogue import synthetic
    sources = synthetic(tmp_path)
    name = 'fictional-operation'
    paths = {'doc': 'docs/reference/fictional-operation.md',
             'hb': 'src/ravel/data/skills/fictional/SKILL.md',
             'check': 'src/ravel/validation/fictional_check.py',
             'curation': 'src/ravel/data/knowledge/curation/fictional-operation.json'}

    def write(path, value):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if isinstance(value, str) else json.dumps(value))
        return {'path': path, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}

    doc = write(paths['doc'], '# Fictional operation\n\nPreserve the ordered input operands.\n')
    handbook = write(paths['hb'], '# Fictional handbook\n\nCheck the complete source population.\n')
    check = write(paths['check'], 'def validate(value):\n    return value == 7\n')
    curation = write(paths['curation'], {'id': 'op:' + name, 'op': {'use_when': ['Exact supplied operands']}})
    write('src/ravel/data/operation_signatures.json', {'operations': {name: {
        'summary': 'Use complete ordered operands', 'consumes': [], 'produces': [], 'review': {'checks': []}}}})
    write('src/ravel/data/knowledge/atlas.json', {'entries': [
        {'id': 'op:' + name, 'kind': 'op', 'curation_source': curation,
         'links': {'docs': ['doc:' + paths['doc']], 'handbooks': ['hb:fictional'],
                   'checks': ['check:fictional_check.validate']}},
        {'id': 'doc:' + paths['doc'], 'kind': 'doc', 'source': doc},
        {'id': 'hb:fictional', 'kind': 'hb', 'source': handbook},
        {'id': 'check:fictional_check.validate', 'kind': 'check', 'source': check},
    ]})
    return sources, name, paths


def test_a_new_signature_projects_complete_source_bodies_without_handwritten_routing(tmp_path):
    sources, name, paths = source_tree(tmp_path)
    built, manifests = catalogue.build(tmp_path, sources=sources, citations={'rows': []}, cards=[])
    cat = catalogue.Catalogue(built, manifests)
    text = '\n'.join(cat.units[uid]['text'] for uid in cat.resolve('operation:' + name))
    assert 'Preserve the ordered input operands.' in text
    assert 'Check the complete source population.' in text
    assert 'return value == 7' in text
    assert 'Exact supplied operands' in text
    assert catalogue.coverage_problems(cat) == []


@pytest.mark.parametrize('damage', ['changed', 'missing', 'withheld'])
def test_operation_source_custody_refuses_changed_missing_and_withheld_inputs(tmp_path, damage):
    sources, _, paths = source_tree(tmp_path)
    target = tmp_path / paths['doc']
    view = None
    if damage == 'changed':
        target.write_text('# Changed\n\nUse a different source.\n')
    elif damage == 'missing':
        target.unlink()
    else:
        shipped = {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*') if path.is_file()}
        view = compiler.View(tmp_path, shipped=shipped - {paths['doc']})
    with pytest.raises((ValueError, OSError)):
        catalogue.build(tmp_path, sources=sources, citations={'rows': []}, cards=[], view=view)


def test_operation_publication_preserves_the_source_preimage_and_delivered_postimage(tmp_path):
    sources, name, paths = source_tree(tmp_path)
    original = (tmp_path / paths['doc']).read_bytes()
    published = b'# Published operation\n\nPreserve the full published operands.\n'
    view = compiler.View(tmp_path, transforms={paths['doc']: True}, publish=lambda *args: published)
    built, manifests = catalogue.build(tmp_path, sources=sources, citations={'rows': []}, cards=[], view=view)
    cat = catalogue.Catalogue(built, manifests)
    text = '\n'.join(cat.units[uid]['text'] for uid in cat.resolve('operation:' + name))
    assert 'Preserve the full published operands.' in text
    assert (tmp_path / paths['doc']).read_bytes() == original
    row = next(row for row in built['files'] if row['path'] == paths['doc'])
    assert row['sha256'] == hashlib.sha256(published).hexdigest()
    (tmp_path / paths['doc']).write_text('# Unbound preimage\n')
    with pytest.raises(ValueError, match='digest mismatch'):
        catalogue.build(tmp_path, sources=sources, citations={'rows': []}, cards=[], view=view)


def test_contract_owned_curation_retains_the_complete_registered_source_record(tmp_path):
    from test_chain_discovery_projection import signature
    sources, name, paths = source_tree(tmp_path)
    relative = 'src/ravel/data/operation_signatures.json'
    row = signature(name)
    row['registration']['documentation'] = [{'path': paths['doc'], 'section': 'Fictional operation'}]
    (tmp_path / relative).write_text(json.dumps({'operations': {name: row}}))
    atlas_path = tmp_path / 'src/ravel/data/knowledge/atlas.json'
    atlas = json.loads(atlas_path.read_text())
    atlas['entries'][0]['curation_source'] = {
        'path': relative, 'sha256': hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()}
    atlas_path.write_text(json.dumps(atlas))
    built, manifests = catalogue.build(tmp_path, sources=sources, citations={'rows': []}, cards=[])
    cat = catalogue.Catalogue(built, manifests)
    units = cat.resolve('knowledge:op:' + name)
    assert json.loads(cat.units[units[0]]['text']) == row
    assert set(units) <= set(cat.resolve('operation:' + name))
