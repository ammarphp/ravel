"""Adoption checks complete obligations and actual nonempty bytes, before copying."""
import importlib
import json
from pathlib import Path

import pytest


def module():
    assert importlib.util.find_spec('ravel.workflow.work_order_fidelity'), 'adoption fidelity seam missing'
    return importlib.import_module('ravel.workflow.work_order_fidelity')


def order():
    return {'declared_outputs': [{'path': 'outputs/value.json', 'kind': 'observation', 'required': True}],
            'obligations': [{'id': 'O1', 'output': 'outputs/value.json', 'pointer': '/value'}]}


@pytest.mark.parametrize('fault', ['missing_obligation', 'empty_file', 'empty_value', 'missing_file', 'missing_pointer', 'symlink', 'escape', 'stale_digest'])
def test_adopt_refuses_incomplete_content(fault, tmp_path):
    wf = module()
    workspace = tmp_path / 'worker'
    (workspace / 'outputs').mkdir(parents=True)
    target = workspace / 'outputs/value.json'
    target.write_text('{"value": 0}')
    value = order()
    expected = order()['obligations']
    if fault == 'missing_obligation': value['obligations'] = []
    elif fault == 'empty_file': target.write_text('   ')
    elif fault == 'empty_value': target.write_text('{"value": []}')
    elif fault == 'missing_file': target.unlink()
    elif fault == 'missing_pointer': target.write_text('{"other": 0}')
    elif fault == 'symlink':
        outside = tmp_path / 'outside.json'; outside.write_text('{"value": 0}')
        target.unlink(); target.symlink_to(outside)
    elif fault == 'escape': value['declared_outputs'][0]['path'] = '../outside.json'
    elif fault == 'stale_digest': value['declared_outputs'][0]['sha256'] = '0' * 64
    assert wf.check(value, workspace, expected_obligations=expected)


def test_content_zero_is_not_empty_and_collisions_remain_visible(tmp_path):
    wf = module()
    (tmp_path / 'outputs').mkdir()
    p = tmp_path / 'outputs/value.json'; p.write_text('{"value": 0}')
    assert wf.check(order(), tmp_path, expected_obligations=order()['obligations']) == []
    p.write_text('{"other": 0}')
    assert wf.check(order(), tmp_path, expected_obligations=order()['obligations'])


def test_adopt_cli_refuses_before_copying(tmp_path, capsys):
    wf = module()
    root = tmp_path / 'run'; workspace = root / 'work/N1/attempt-1'
    (workspace / 'outputs').mkdir(parents=True)
    (root / 'inputs/work-orders').mkdir(parents=True)
    data = order(); data['node_id'] = 'N1'
    data['order_sha256'] = wf.digest(data)
    (root / 'inputs/work-orders/N1.json').write_text(json.dumps(data))
    (root / 'inputs/work-obligations.json').write_text(json.dumps({'N1': order()['obligations']}))
    dispatch = importlib.import_module('ravel.workflow.work_dispatch')
    with pytest.raises(ValueError, match='fidelity'):
        dispatch.adopt(root, 'N1', 1)
    assert not (root / 'outputs').exists()
    from ravel import cli
    assert cli.main(['work', 'adopt', '--rundir', str(root), '--node-id', 'N1', '--attempt', '1']) == 1
    assert not (root / 'outputs').exists()


def test_adopt_copies_exact_bytes_after_all_obligations_pass(tmp_path):
    from test_work_dispatch import fixture
    root = tmp_path / 'run'
    data, workspace = fixture(root, node='N1')
    raw = (workspace / 'outputs/result.json').read_bytes()
    dispatch = importlib.import_module('ravel.workflow.work_dispatch')
    result = dispatch.adopt(root, 'N1', 1)
    assert (root / 'outputs/result.json').read_bytes() == raw
    assert result['contract_checks'] == ['check:obligation_coverage', 'check:work_order_content']
    assert dispatch.adopt(root, 'N1', 1) == result


def test_optional_escape_and_duplicate_json_are_refused(tmp_path):
    wf = module()
    (tmp_path / 'outputs').mkdir()
    path = tmp_path / 'outputs/value.json'; path.write_text('{"value": 0, "value": 1}')
    assert wf.check(order(), tmp_path, expected_obligations=order()['obligations'])
    path.write_text('{"value": 0}')
    data = order(); data['declared_outputs'].append({'path': '../escape', 'kind': 'observation', 'required': False})
    assert wf.check(data, tmp_path, expected_obligations=order()['obligations'])
