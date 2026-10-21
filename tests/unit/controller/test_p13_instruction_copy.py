"""P13: authenticate the sole controller instruction beside an actual review projection.

Small filesystem fixtures only. Ownership is the sole mocked authority; descriptors,
projection pins and workspace instruction bytes are real files. No launch or model call.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.workflow import review_context, review_dispatch as rd, review_independence as ri, review_projection


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def instruction(tmp_path, monkeypatch):
    run, workspace, custody = (tmp_path / name for name in ('run', 'workspace', 'custody'))
    for path in (run, workspace, custody):
        path.mkdir()
    (workspace / 'inputs').mkdir()
    projected = review_projection.project(
        run, 'plan-critic', key='instruction-copy-control',
        item={'point_id': 'point-control', 'role': 'plan-critic', 'subject_sha256': 'a' * 64},
        out_root=workspace / 'inputs/packet')
    review_context.verify_packet(projected['path'], expected_manifest_sha256=projected['manifest_sha256'])
    path = workspace / 'inputs/packet.md'
    path.write_text('Review the projected item and return its declared structured record.\n')
    copy = {'path': 'inputs/packet.md', 'sha256': sha(path)}
    key = 'worker-control-1'
    descriptor_path = custody / (key + '.launch.json')
    descriptor = {'transport': {'controller': {'packet_sha256': copy['sha256']}}}
    descriptor_path.write_text(json.dumps(descriptor, sort_keys=True))
    pin = {'path': 'inputs/controller/packet.md', 'sha256': copy['sha256']}
    record = {'spec': {'final_record_schema': 'controller.v1',
                       'inputs': [{'as': copy['path'], 'pin': pin}]},
              'packet': projected, 'launch': {'descriptor_sha256': sha(descriptor_path)},
              'input_copies': [deepcopy(copy)]}
    monkeypatch.setattr(ri, 'controller_run', lambda value: 'controller-run-control')
    return SimpleNamespace(query={'run': str(run)}, record=record, copy=copy, workspace=workspace,
                           custody=custody, key=key, path=path, descriptor=descriptor,
                           descriptor_path=descriptor_path, projection=projected)


def accepts(value):
    return rd._controller_instruction_copy(value.query, value.record, value.copy,
                                           value.workspace, value.custody, value.key)


def save_descriptor(value):
    value.descriptor_path.write_text(json.dumps(value.descriptor, sort_keys=True))
    value.record['launch']['descriptor_sha256'] = sha(value.descriptor_path)


def test_CF10_exact_owned_controller_instruction_beside_real_projection_is_authenticated(instruction):
    value = instruction
    assert len(value.record['spec']['inputs']) == 1
    assert value.record['spec']['inputs'][0]['pin']['sha256'] == value.copy['sha256']
    assert value.record['launch']['descriptor_sha256'] == sha(value.descriptor_path)
    assert value.descriptor['transport']['controller']['packet_sha256'] == sha(value.path)
    assert review_context.verify_packet(
        value.projection['path'], expected_manifest_sha256=value.projection['manifest_sha256']) is not False
    assert accepts(value) is True


def test_CF10_instruction_exception_is_unavailable_to_unowned_legacy_run(instruction, monkeypatch):
    monkeypatch.setattr(ri, 'controller_run', lambda value: None)
    assert accepts(instruction) is False


@pytest.mark.parametrize('inputs', [None, {}, [], [{}, {}], [{}], [{'as': 'inputs/packet.md'}],
                                    [{'as': 'inputs/other.md', 'pin': {'sha256': 'b' * 64}}]])
def test_CF10_instruction_requires_exact_sole_pinned_raw_input(instruction, inputs):
    instruction.record['spec']['inputs'] = inputs
    assert accepts(instruction) is False


def test_CF10_additional_raw_input_cannot_accompany_controller_instruction(instruction):
    instruction.record['spec']['inputs'].append(
        {'as': 'inputs/author.txt', 'pin': {'path': 'inputs/author.txt', 'sha256': 'b' * 64}})
    assert accepts(instruction) is False


@pytest.mark.parametrize('schema', [None, '', 'producer.v1', 'reviewer.v1', 'controller.v2'])
def test_CF10_instruction_requires_exact_controller_schema(instruction, schema):
    instruction.record['spec']['final_record_schema'] = schema
    assert accepts(instruction) is False


@pytest.mark.parametrize('which', ['copy', 'pin', 'descriptor'])
def test_CF10_instruction_copy_pin_and_descriptor_packet_digests_must_agree(instruction, which):
    if which == 'copy':
        instruction.copy['sha256'] = 'b' * 64
    elif which == 'pin':
        instruction.record['spec']['inputs'][0]['pin']['sha256'] = 'b' * 64
    else:
        instruction.descriptor['transport']['controller']['packet_sha256'] = 'b' * 64
        save_descriptor(instruction)
    assert accepts(instruction) is False


@pytest.mark.parametrize('path', [None, '', 'inputs/raw.txt', 'inputs/packet/packet.md', '../packet.md'])
def test_CF10_only_exact_instruction_copy_destination_qualifies(instruction, path):
    instruction.copy['path'] = path
    assert accepts(instruction) is False


@pytest.mark.parametrize('case', ['tampered', 'symlink', 'missing'])
def test_CF10_protected_launch_descriptor_must_be_original_regular_file(instruction, case):
    path = instruction.descriptor_path
    original = path.read_bytes()
    path.unlink()
    if case == 'tampered':
        path.write_bytes(original + b' ')
    elif case == 'symlink':
        target = path.with_name('descriptor-target.json')
        target.write_bytes(original)
        path.symlink_to(target)
    assert accepts(instruction) is False


@pytest.mark.parametrize('case', ['tampered', 'symlink', 'missing'])
def test_CF10_workspace_instruction_must_be_original_regular_file(instruction, case):
    path = instruction.path
    original = path.read_bytes()
    path.unlink()
    if case == 'tampered':
        path.write_bytes(original + b'Unbound framing.\n')
    elif case == 'symlink':
        target = path.with_name('instruction-target.md')
        target.write_bytes(original)
        path.symlink_to(target)
    assert accepts(instruction) is False


@pytest.mark.parametrize('controller', [None, {}, [], 'declared', {'packet_sha256': 'b' * 64}])
def test_CF10_descriptor_requires_its_own_exact_typed_controller_packet_pin(instruction, controller):
    instruction.descriptor['transport']['controller'] = controller
    save_descriptor(instruction)
    assert accepts(instruction) is False


def test_CF10_public_receipt_controller_metadata_cannot_bless_unbound_instruction(instruction):
    instruction.descriptor['transport'].pop('controller')
    save_descriptor(instruction)
    instruction.record['receipt'] = {'controller': {'packet_sha256': instruction.copy['sha256']}}
    instruction.record['controller'] = {'packet_sha256': instruction.copy['sha256']}
    instruction.query['controller'] = {'packet_sha256': instruction.copy['sha256']}
    assert accepts(instruction) is False


@pytest.mark.parametrize('value', [None, 'raw', 3, []])
def test_CF10_malformed_sole_input_element_is_refused(instruction, value):
    instruction.record['spec']['inputs'] = [value]
    assert accepts(instruction) is False


@pytest.mark.parametrize('value', ['raw-pin', ['raw-pin'], 7])
def test_CF10_malformed_truthy_pin_is_refused(instruction, value):
    instruction.record['spec']['inputs'][0]['pin'] = value
    assert accepts(instruction) is False


@pytest.mark.parametrize('value', [None, 'raw-copy', 7, [], ['copy']])
def test_CF10_malformed_copy_is_refused(instruction, value):
    instruction.copy = value
    assert accepts(instruction) is False


@pytest.mark.parametrize('field', ['spec', 'launch'])
@pytest.mark.parametrize('value', [None, 'raw-value', 7, [], ['value']])
def test_CF10_malformed_protected_spec_or_launch_is_refused(instruction, field, value):
    instruction.record[field] = value
    assert accepts(instruction) is False


@pytest.mark.parametrize('value', [None, 'raw-descriptor', 7, [], ['descriptor']])
def test_CF10_malformed_descriptor_is_refused_even_when_exact_bytes_are_pinned(instruction, value):
    instruction.descriptor = value
    save_descriptor(instruction)
    assert accepts(instruction) is False


@pytest.mark.parametrize('value', [None, 'raw-transport', 7, [], ['transport']])
def test_CF10_malformed_descriptor_transport_is_refused_even_when_pinned(instruction, value):
    instruction.descriptor['transport'] = value
    save_descriptor(instruction)
    assert accepts(instruction) is False


def test_CF10_invalid_pinned_descriptor_json_raises_for_the_callers_fail_closed_boundary(instruction):
    instruction.descriptor_path.write_text('{not-json')
    instruction.record['launch']['descriptor_sha256'] = sha(instruction.descriptor_path)
    with pytest.raises(ValueError):
        accepts(instruction)
