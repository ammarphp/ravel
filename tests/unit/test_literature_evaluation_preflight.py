"""Preflight of a declared evaluation membership against a pinned index. Fictional corpus only.

Failure class: an evaluation runs against an index it was not prepared for (a changed corpus or
manifest, a missing document version, answers located in another coordinate system) or with
unfrozen gold answers, and its scores are read as evidence. The preflight reads only the
membership document and the snapshot it is given.
"""
import builtins
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ravel.workflow import literature_build as store, literature_evaluation_preflight as pre
from test_literature_serving import Embedder, Reranker, make_corpus


@pytest.fixture
def index(tmp_path):
    root = Path(os.path.realpath(tmp_path))
    snapshot = store.build_index(root / 'index', make_corpus(root / 'corpus'), embedder=Embedder(),
                                 reranker_identity=Reranker().identity)
    return root, snapshot


def membership(snapshot, **changes):
    manifest = snapshot['manifest']
    value = {'schema_version': 1, 'kind': pre.KIND, 'coordinates': 'member-lines',
             'corpus_sha256': manifest['corpus_sha256'], 'index_manifest_sha256': manifest['manifest_sha256'],
             'gold': {'frozen': True, 'sha256': 'a' * 64},
             'documents': [{'document_id': 'paper:alder', 'version': 'v1'},
                           {'document_id': 'paper:birch', 'version': 'v1'}]}
    value.update(deepcopy(changes))
    return value


def codes(report):
    return [r['code'] for r in report['reasons']]


def test_a_complete_fictional_preflight_passes(index):
    _, snapshot = index
    report = pre.preflight(membership(snapshot), snapshot)
    assert report['status'] == 'passed' and report['reasons'] == []
    assert report['index']['manifest_sha256'] == snapshot['manifest']['manifest_sha256']
    assert report['quality_measured'] is False and report['provider_qualified'] is False


CASES = {
    'missing version': ({'documents': [{'document_id': 'paper:alder', 'version': 'v2'}]}, ['version_missing']),
    'missing document': ({'documents': [{'document_id': 'paper:elm', 'version': 'v1'}]}, ['document_missing']),
    'coordinate system': ({'coordinates': 'pdf-pages'}, ['coordinate_system_mismatch'] * 2),
    'changed corpus': ({'corpus_sha256': '1' * 64}, ['corpus_digest_changed']),
    'changed index': ({'index_manifest_sha256': '2' * 64}, ['index_digest_changed']),
    'unfrozen gold': ({'gold': {'frozen': False, 'sha256': 'a' * 64}}, ['gold_not_frozen']),
    'gold without digest': ({'gold': {'frozen': True, 'sha256': None}}, ['gold_not_frozen']),
    'open document': ({'extra': 'x'}, ['invalid_membership']),
    'unknown coordinates': ({'coordinates': 'pixels'}, ['invalid_membership']),
}


@pytest.mark.parametrize('case', CASES)
def test_each_unprepared_condition_is_refused_with_its_reason(index, case):
    _, snapshot = index
    changes, expected = CASES[case]
    report = pre.preflight(membership(snapshot, **changes), snapshot)
    assert report['status'] == 'refused' and codes(report) == expected


def test_the_function_reads_nothing(index, monkeypatch):
    _, snapshot = index
    def refuse(*args, **kwargs):
        raise AssertionError('the preflight opened a file')
    monkeypatch.setattr(builtins, 'open', refuse)
    monkeypatch.setattr(os, 'open', refuse)
    assert pre.preflight(membership(snapshot), snapshot)['status'] == 'passed'


def test_the_command_reads_only_the_membership_and_the_index(index, monkeypatch, capsys):
    root, snapshot = index
    path = root / 'declared' / 'membership.json'
    path.parent.mkdir()
    path.write_text(json.dumps(membership(snapshot)))
    opened, real = [], builtins.open

    def recording(file, *args, **kwargs):
        opened.append(os.path.realpath(os.fspath(file)))
        return real(file, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', recording)
    real_read = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda self: opened.append(os.path.realpath(self)) or real_read(self))
    assert pre.main(['--membership', str(path), '--index-root', str(root / 'index')]) == 0
    monkeypatch.setattr(builtins, 'open', real)
    assert json.loads(capsys.readouterr().out)['status'] == 'passed'
    allowed = (str(path), str(root / 'index') + os.sep)
    assert opened and all(p == allowed[0] or p.startswith(allowed[1]) for p in opened), opened
    path.write_text(json.dumps(membership(snapshot, coordinates='pdf-pages')))
    assert pre.main(['--membership', str(path), '--index-root', str(root / 'index')]) == 1


def test_product_code_names_no_location_of_its_own():
    # Every path comes from the caller; the module carries no absolute or home-relative location.
    import ast
    constants = [n.value for n in ast.walk(ast.parse(Path(pre.__file__).read_text()))
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [c for c in constants if c.startswith(('/', '~')) or os.sep + '.' in c]
