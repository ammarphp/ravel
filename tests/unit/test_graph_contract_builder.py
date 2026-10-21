"""Graph contract regeneration preserves explicit version and source custody."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def builder():
    spec = importlib.util.spec_from_file_location(
        'graph_contract_builder', ROOT / 'scripts/maintenance/build_graph_contracts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_contracts_regenerate_byte_identically():
    from ravel.workflow import graph_registry
    selected = ('review.item', 'review.points', 'consult.case')
    path, raw = builder().build(ROOT, {identity: graph_registry.get(identity)['version'] for identity in selected})
    assert path.read_text() == raw


def test_structural_change_requires_an_explicit_version_advance(tmp_path):
    from ravel.workflow import graph_registry
    registry = tmp_path / 'src/ravel/data/graphs/registry.json'
    registry.parent.mkdir(parents=True)
    document = json.loads((ROOT / 'src/ravel/data/graphs/registry.json').read_text())
    row = next(row for row in document['graphs'] if row['id'] == 'consult.case')
    row['structure_sha256'] = '0' * 64
    registry.write_text(json.dumps(document))
    sanctioned = tmp_path / 'src/ravel/data/agents/sanctioned.json'
    sanctioned.parent.mkdir(parents=True)
    sanctioned.write_bytes((ROOT / 'src/ravel/data/agents/sanctioned.json').read_bytes())
    version = graph_registry.get('consult.case')['version']
    with pytest.raises(ValueError, match='explicit version advance'):
        builder().build(tmp_path, {'consult.case': version})
    _, content = builder().build(tmp_path, {'consult.case': version + 1})
    changed = next(row for row in json.loads(content)['graphs'] if row['id'] == 'consult.case')
    assert changed['version'] == version + 1
    assert changed['structure_sha256'] == graph_registry.get('consult.case')['structure_sha256']
    assert json.loads(registry.read_text()) == document


@pytest.mark.parametrize('versions', [{'unknown.graph': 1}, {'consult.case': 0}])
def test_unknown_graph_and_version_regression_refuse(versions):
    with pytest.raises(ValueError):
        builder().build(ROOT, versions)
