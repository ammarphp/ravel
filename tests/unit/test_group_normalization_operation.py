"""Portable ordinary adapter and planning controls; no native/model calls.

Worker cases execute the real normalization adapter; authorization and rendering
are explicitly substituted. Planning cases use the actual public workflow API
without approval, launch, scientific review votes or an optimizer.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from ravel.physics import group_normalization as g
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, read_json
from test_group_normalization import fixture


def task_fixture(tmp_path):
    c, a = fixture(tmp_path)
    path = tmp_path/'normalization.json'
    path.write_text(json.dumps(c))
    task = {'schema_version': 1, 'input': path.name,
            'contract_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return task, c, a, path


def specification(task, version=2):
    spec = {'schema_version': version, 'mode': 'group-normalization',
            'source': 'Fabricated source/group arithmetic control',
            'assumptions': ['No native acquisition or scientific covariance calibration is established'],
            'max_seconds': 30, 'approval_mode': 'scripted_yes', 'task': task}
    if version == 2:
        spec.update(max_attempts=1, review_policy={'schema_version': 1,
            'policy': {'schema_version': 1,
                'actors': {'proposer': 'producer', 'executor': 'executor',
                           'physics_critic': 'critic', 'skeptical_verifier': 'skeptic',
                           'physics_decider': 'decider'},
                'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
                'required_checks': [{'id': 'integrity', 'kind': 'integrity'},
                                    {'id': 'scientific', 'kind': 'scientific'}],
                'claim_scopes': {'supplied_group_delta': {'checks': ['integrity', 'scientific'],
                                                       'actions': ['delivery', 'reuse']}}},
            'correction_contract': {'task_fields': [], 'input_slots': []}})
    return spec


@pytest.mark.parametrize('change', [{'schema_version': True}, {'schema_version': 2},
    {'extra': 'unbound'}, {'input': ''}, {'contract_sha256': 'A'*64},
    {'contract_sha256': 'a'*63}])
def test_task_is_closed_and_externally_pinned(tmp_path, change):
    task, _, _, _ = task_fixture(tmp_path)
    with pytest.raises(g.GroupNormalizationError): g.validate({**task, **change})


def test_complete_source_inventory_without_numerical_evaluation(tmp_path, monkeypatch):
    task, c, _, path = task_fixture(tmp_path)
    monkeypatch.setattr(g, 'normalize', lambda *_args, **_kw: pytest.fail('planning evaluated normalization'))
    actual = g.inputs(task, tmp_path)
    assert actual == [path.resolve(), *(Path(p['path']).resolve() for p in c['sources'])]
    assert len(actual) == len(set(actual)) == 6


@pytest.mark.parametrize('source_id', ['routine', 'trace', 'RAW', 'original-contract', 'acquired'])
def test_every_origin_is_checked_before_planning(tmp_path, source_id):
    task, c, _, _ = task_fixture(tmp_path)
    path = Path(next(p['path'] for p in c['sources'] if p['id'] == source_id))
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(g.GroupNormalizationError, match='source (size|hash) differs'):
        g.inputs(task, tmp_path)


@pytest.mark.parametrize('raw', ['{"schema_version":1,"schema_version":1}', '{"number":NaN}'])
def test_strict_outer_json_refuses_resealed_invalid_documents(tmp_path, raw):
    task, _, _, path = task_fixture(tmp_path)
    path.write_text(raw); task['contract_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(g.GroupNormalizationError): g.inputs(task, tmp_path)


def test_outer_hash_relative_sources_and_no_symlink_ancestry(tmp_path):
    task, c, _, path = task_fixture(tmp_path)
    old = copy.deepcopy(task)
    for pin in c['sources']: pin['path'] = Path(pin['path']).name
    path.write_text(json.dumps(c))
    with pytest.raises(g.GroupNormalizationError, match='contract hash'): g.inputs(old, tmp_path)
    task['contract_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(g.inputs(task, tmp_path)) == 6
    alias = tmp_path/'alias'; alias.symlink_to(tmp_path, target_is_directory=True)
    refusal = f'input path traverses a symlink: {alias/path.name}'
    with pytest.raises(ValueError, match=re.escape(refusal)):
        g.inputs({**task, 'input': str(alias/path.name)}, tmp_path)


def test_complete_origin_pin_ids_required_and_duplicate_path_refuses(tmp_path):
    task, c, _, path = task_fixture(tmp_path)
    c['native_trace_source'] = 'missing'
    path.write_text(json.dumps(c)); task['contract_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(g.GroupNormalizationError, match='origin pins'): g.inputs(task, tmp_path)
    c['native_trace_source'] = 'trace'; c['sources'].append({**c['sources'][0], 'id': 'duplicate'})
    path.write_text(json.dumps(c)); task['contract_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(g.GroupNormalizationError, match='duplicate resolved source'): g.inputs(task, tmp_path)


def test_normal_adapter_delivers_full_result_and_existing_covariance_seam(tmp_path):
    task, c, a, _ = task_fixture(tmp_path)
    out = tmp_path/'fresh-output'
    result = g.run(task, tmp_path, out)
    assert read_json(out/'group-normalization.json') == result
    assert read_json(out/'normalized-joint.json') == g.derived_joint(result)
    assert result['values'] == g.normalize(c, a)['values']
    assert result['status'] == 'passed'
    assert result['native_acquisition_qualified'] is False
    assert result['physics_validated'] is False and result['inference'] is None
    assert result['experimental_independence'] is None
    assert result['sources'] == c['sources']
    before = {p.name:p.read_bytes() for p in out.iterdir()}
    with pytest.raises(g.GroupNormalizationError, match='fresh normalization'):
        g.run(task, tmp_path, out)
    assert {p.name:p.read_bytes() for p in out.iterdir()} == before


def test_public_dispatch_v2_requirement_and_exact_planned_input_graph(tmp_path):
    task, c, _, _ = task_fixture(tmp_path)
    assert science.adapter(specification(task)) is g
    assert science._new_capability(specification(task))
    path = tmp_path/'spec-v1.json'; atomic_json(path, specification(task, 1))
    with pytest.raises(ValueError, match='version 2'):
        science.plan(tmp_path/'refused-v1', path)
    assert not (tmp_path/'refused-v1').exists()
    path = tmp_path/'spec-v2.json'; atomic_json(path, specification(task))
    proposal = science.plan(tmp_path/'prepared-only', path)
    stage = proposal['stages'][0]
    planned = set(stage['inputs'])
    assert str((tmp_path/'normalization.json').resolve()) in planned
    assert all(str(Path(pin['path']).resolve()) in planned for pin in c['sources'])
    assert not (tmp_path/'prepared-only'/science.APPROVAL).exists()
    assert not (tmp_path/'prepared-only'/'outputs/attempt-1').exists()
    # A changed source invalidates the public plan; no command is launched.
    original = Path(c['sources'][0]['path']); original.write_text(original.read_text()+'changed\n')
    with pytest.raises(ValueError): science.verify_plan(tmp_path/'prepared-only')


def test_actual_adapter_worker_filesystem_lifecycle_with_explicit_auth_render_mocks(tmp_path, monkeypatch):
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    task, _, _, _ = task_fixture(tmp_path)
    rd = tmp_path/'run'; rd.mkdir()
    spec = specification(task)
    proposal = {'base_dir': str(tmp_path), 'attempt': 1,
                'output_directory': 'outputs/attempt-1', 'stage_binding': {'input_snapshot': []}}
    monkeypatch.setattr(science_worker, 'verify_worker', lambda _: proposal)
    monkeypatch.setattr(science_worker, 'execution_spec', lambda _: spec)
    monkeypatch.setattr(science_figures, 'render', lambda *_: {'figures': [], 'tables': [], 'status': 'not_applicable'})
    assert science_worker.main([str(rd), '--attempt', '1']) == 0
    outer = rd/'outputs/attempt-1'; nested = outer/'group-normalization'
    assert read_json(outer/'result.json') == read_json(nested/'group-normalization.json')
    assert read_json(nested/'normalized-joint.json')['uncertainty']['kind'] == 'supplied_covariance'
    assert read_json(outer/'verification.json')['physics_validated'] is False
    with pytest.raises(FileExistsError): science_worker.main([str(rd), '--attempt', '1'])
