"""Declared dependency/layout custody controls; no routine execution."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ravel import analysis_sources as source


def capsule(tmp_path):
    root = tmp_path / 'upstream'
    (root / 'left').mkdir(parents=True)
    (root / 'right').mkdir()
    (root / 'main.cc').write_text('int main() { return 0; }\n')
    (root / 'left/model.json').write_text('{"value":1}\n')
    (root / 'right/model.json').write_text('{"value":2}\n')
    facts = [{'path': p, 'sha256': source.digest(root / p), 'role': role} for p, role in
             [('main.cc', 'compile'), ('left/model.json', 'preprocessing'), ('right/model.json', 'preprocessing')]]
    return {'schema_version': 1, 'kind': 'analysis-source-capsule', 'framework': 'cpp',
            'routine': 'PreviouslyUnknown', 'source': {'repository': 'supplied', 'revision': None,
                'description': 'Synthetic source-layout control, no physics'}, 'root': 'upstream',
            'files': facts, 'layout': {'include_dirs': [], 'asset_dirs': ['left', 'right']},
            'dependencies': [{'name': 'two distinct model configurations', 'kind': 'asset',
                'status': 'resolved', 'files': ['left/model.json', 'right/model.json'], 'reason': 'Both distinct bytes are bound'}],
            'dependency_review': {'complete': True, 'description': 'Finite structural fixture, no hidden inputs'},
            'submodules': []}


def test_unknown_routine_and_same_basename_assets_preserve_distinct_layout(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('planning executed a subprocess'))
    c = capsule(tmp_path)
    r = source.inventory(c, tmp_path)
    assert r['declared_files_verified'] == 3
    assert r['files'][1]['sha256'] != r['files'][2]['sha256']
    assert r['physics_validated'] is False


@pytest.mark.parametrize('path', ['/outside.cc', '../outside.cc', 'left/../right.cc', 'left//file.cc', 'left\\file.cc'])
def test_capsule_rejects_nonrelative_or_unnormalized_paths(tmp_path, path):
    c = capsule(tmp_path); c['files'][0]['path'] = path
    with pytest.raises(ValueError, match='normalized relative'):
        source.validate_capsule(c)


def test_tampered_asset_and_nested_symlink_fail_before_execution(tmp_path):
    c = capsule(tmp_path)
    p = tmp_path / 'upstream/left/model.json'
    p.write_text('changed')
    with pytest.raises(ValueError, match='bytes differ'):
        source.source_files(c, tmp_path)
    c['files'][1]['sha256'] = source.digest(p)
    outside = tmp_path / 'external'; outside.mkdir(); (outside / 'model.json').write_text('changed')
    p.unlink(); p.parent.rmdir(); p.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        source.source_files(c, tmp_path)


def test_lfs_pointer_is_not_model_content_even_with_matching_digest(tmp_path):
    c = capsule(tmp_path); p = tmp_path / 'upstream/left/model.json'
    p.write_text('version https://git-lfs.github.com/spec/v1\noid sha256:' + '0' * 64 + '\nsize 9000\n')
    c['files'][1]['sha256'] = source.digest(p)
    with pytest.raises(ValueError, match='LFS pointer'):
        source.source_files(c, tmp_path)


def test_unresolved_requirements_can_be_listed_but_cannot_assert_complete(tmp_path):
    c = capsule(tmp_path); c['dependencies'][0]['status'] = 'unresolved'
    with pytest.raises(ValueError, match='cannot be complete'):
        source.validate_capsule(c)
    c['dependency_review']['complete'] = False
    assert source.inventory(c, tmp_path)['dependencies'][0]['status'] == 'unresolved'


@pytest.mark.parametrize('mutation', [
    lambda c: c['files'].append(copy.deepcopy(c['files'][0])),
    lambda c: c['dependencies'][0].update(files=['not-declared.onnx']),
    lambda c: c.update(schema_version=True),
    lambda c: c['source'].update(repository='https://example.invalid/upstream', revision='main'),
    lambda c: c['submodules'].append({'path': 'sub', 'repository': 'https://example.invalid/sub', 'revision': 'a' * 40}),
])
def test_malformed_or_unbound_source_assertions_fail(tmp_path, mutation):
    c = capsule(tmp_path); mutation(c)
    with pytest.raises(ValueError):
        source.validate_capsule(c)


def test_duplicate_json_key_rejected(tmp_path):
    p = tmp_path / 'capsule.json'; p.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match='duplicate'):
        source.load_capsule(p)


@pytest.mark.parametrize('code', ['auto model = getONNX(name(), "res.odd");',
                               '#include "Rivet/Tools/RivetONNXrt.hh"\n',
                               'addONNX("nn", "prefix_"+suffix);',
                               'auto p=analysisDataPath("onnx");'])
def test_helper_constructed_model_dependencies_are_positive_cues(tmp_path, code):
    c = capsule(tmp_path); p = tmp_path / 'upstream/main.cc'; p.write_text(code)
    c['files'][0]['sha256'] = source.digest(p)
    assert source.dependency_cues(c, tmp_path)['onnx_model'] is True


def test_comment_is_not_model_dependency(tmp_path):
    c = capsule(tmp_path); p = tmp_path / 'upstream/main.cc'
    p.write_text('// getONNX("fake");\n/* addONNX("fake"); */ int main() { return 0; }')
    c['files'][0]['sha256'] = source.digest(p)
    assert source.dependency_cues(c, tmp_path)['onnx_model'] is False


def test_secondary_routine_binding_uses_actual_literal_source_and_named_assets(tmp_path):
    c = capsule(tmp_path);root=tmp_path/'upstream'
    (root/'main.cc').write_text('RIVET_DECLARE_PLUGIN(PreviouslyUnknown);\n// RIVET_DECLARE_PLUGIN(Fake);\nconst char* s="RIVET_DECLARE_PLUGIN(StringFake)";')
    (root/'secondary.cc').write_text('RIVET_DECLARE_PLUGIN(Secondary);')
    (root/'Secondary.info').write_text('Name: Secondary')
    (root/'Secondary.yoda.gz').write_bytes(b'exact reference fixture')
    c['files'][0]['sha256']=source.digest(root/'main.cc')
    c['files'] += [{'path':p,'sha256':source.digest(root/p),'role':role} for p,role in
                  [('secondary.cc','compile'),('Secondary.info','configuration'),('Secondary.yoda.gz','reference')]]
    bindings=source.routine_bindings(c,tmp_path,['main.cc','secondary.cc'])
    assert set(bindings)=={'PreviouslyUnknown','Secondary'}
    assert bindings['Secondary']['source_files']==[c['files'][3]]
    assert [f['path'] for f in bindings['Secondary']['supporting_files']]==['Secondary.info','Secondary.yoda.gz']
    assert 'Fake' not in bindings and 'StringFake' not in bindings


def test_catalogue_seed_binds_reference_bytes_without_claiming_dependency_closure(tmp_path):
    root = tmp_path / 'upstream'; root.mkdir()
    files = {}
    for name, raw in [('Routine.cc', b'int x = 1;\n'), ('Routine.info', b'Name: Routine\n'), ('Routine.yoda', b'reference bytes\n')]:
        (root / name).write_bytes(raw)
        files[name] = {'path': name, 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
    row = {'name': 'Routine', 'framework': 'rivet', 'source_id': 'rivet',
           'source_files': [files['Routine.cc']], 'metadata_file': files['Routine.info'],
           'reference_files': [files['Routine.yoda']]}
    catalogue = {'sources': {'rivet': {'repository': 'https://example.invalid/upstream', 'revision': 'a' * 40}}}
    seed = source.from_catalogue(catalogue, row, root)
    assert seed['dependency_review']['complete'] is False
    assert {f['role'] for f in seed['files']} == {'compile', 'configuration', 'reference'}
    (root / 'Routine.yoda').write_bytes(b'changed reference')
    with pytest.raises(ValueError, match='blob differs'):
        source.from_catalogue(catalogue, row, root)

def test_aliased_plugin_binds_positive_canonical_and_alias_without_source_rewriting(tmp_path):
    c=capsule(tmp_path);root=tmp_path/'upstream';p=root/'main.cc'
    p.write_text('RIVET_DECLARE_ALIASED_PLUGIN(PreviouslyUnknown, OldName);\n// RIVET_DECLARE_ALIASED_PLUGIN(Fake, OldFake);\nconst char* s="RIVET_DECLARE_ALIASED_PLUGIN(StringFake, OldStringFake)";\n')
    c['files'][0]['sha256']=source.digest(p)
    (root/'macro.h').write_text('#define RIVET_DECLARE_PLUGIN(clsname) fake\n#define RIVET_DECLARE_ALIASED_PLUGIN(clsname, alias) fake\n')
    c['files'].append({'path':'macro.h','role':'header','sha256':source.digest(root/'macro.h')})
    bindings=source.routine_bindings(c,tmp_path,['main.cc'])
    assert set(bindings)=={'PreviouslyUnknown'}
    assert bindings['PreviouslyUnknown']['registration']=='literal-RIVET_DECLARE_ALIASED_PLUGIN'
    assert bindings['PreviouslyUnknown']['aliases']==['OldName']
    assert bindings['PreviouslyUnknown']['source_files']==[c['files'][0]]
