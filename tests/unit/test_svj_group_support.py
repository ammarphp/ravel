"""Portable regression witnesses retained from Stau independent-review-v1.

The +5/-1 independent-group case is distinct from rejected negative events
and cancellation within one declared Poisson group. No physics calibration.
"""
from copy import deepcopy
from fractions import Fraction as F
import json
import math
from pathlib import Path
import pytest
import test_svj_recipe as owner
from ravel.physics import svj_recipe as op


@pytest.fixture(autouse=True)
def controls_only(monkeypatch):
    import platform, subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError("native/provider/external dispatch forbidden")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(platform._Processor, 'get', staticmethod(lambda: 'inert-review-platform'))
    monkeypatch.setattr(platform, 'architecture', lambda *a, **k: ('64bit', 'inert-review-platform'))


def split_first_group(base, same_group=False, negative_selected=True):
    d = owner.fixture(base)
    rp = Path(d['points'][0]['response']['path'])
    rd = json.loads(rp.read_text())
    for anchor in rd['anchors']:
        path = Path(anchor['events']['path'])
        rows = json.loads(path.read_text())
        negative = deepcopy(rows[0])
        negative['event_id'] = 'negative'
        negative['group_id'] = rows[0]['group_id'] if same_group else 'negative-group'
        negative['weights'] = {'nominal': -1.0, 'twice': -2.0}
        if negative_selected:
            rows[0]['weights'] = {'nominal': 5.0, 'twice': 10.0}
        else:
            negative['met']['pt'] = 0.0
        rows.append(negative)
        anchor['events'] = owner.ref(path, rows)
    d['points'][0]['response'] = owner.emit(rp, rd)
    if negative_selected and not same_group:
        for cell in d['templates']:
            if cell['response_id'] != 'no_tag':
                continue
            path = Path(cell['template']['path'])
            template = json.loads(path.read_text())
            sample = next(c for c in template['channels'] if c['name'] == 'SR')['samples'][0]
            sample['mc_stat']['sumw2'][0] = 26.0
            next(m for m in sample['modifiers'] if m['type'] == 'staterror')['data'][0] = math.sqrt(26)
            cell['template'] = owner.emit(path, template)
    return d


def test_independent_full_joint_gram_fraction_oracle(tmp_path):
    d = owner.fixture(tmp_path)
    result = op.run(owner.task(tmp_path, d), tmp_path, tmp_path/'out')
    bundle = json.loads((tmp_path/'out/response-p0/complete-response.json').read_text())
    vectors = []
    for group in bundle['group_ids']:
        v = []
        for weight in ('nominal', 'twice'):
            for anchor in bundle['anchor_records']:
                for column in range(len(bundle['destination_ids'])):
                    v.append(sum((F(row['weights'][weight])*F(row['allocation'][column]) for row in anchor if row['group_id']==group),F(0)))
        vectors.append(v)
    expected = [[sum((v[i]*v[j] for v in vectors), F(0)) for j in range(len(vectors[0]))] for i in range(len(vectors[0]))]
    assert bundle['joint_weight_anchor_covariance'] == [[float(x) for x in row] for row in expected]
    assert len(expected) == 20 and result['prepared_cells'] == 4
    assert not result['original_task_complete'] and not result['physics_validated']


def test_signed_negative_group_cannot_be_nonnegative_mc(tmp_path):
    d = split_first_group(tmp_path)
    result = op.run(owner.task(tmp_path, d), tmp_path, tmp_path/'out')
    bundle = json.loads((tmp_path/'out/response-p0/complete-response.json').read_text())
    assert bundle['events'] == 6
    first = bundle['destination_ids'].index('s0')
    assert bundle['weights']['nominal']['normalized_values'][first] == float(F(5)-F(1))
    assert bundle['weights']['nominal']['conditional_group_covariance'][first][first] == float(F(5)**2+F(-1)**2)
    assert bundle['group_marks']['nominal']['negative-group'][first] == -1.0
    cells = [row for row in result['cells'] if row['response_id']=='no_tag']
    assert all(row['state']=='blocked' for row in cells), 'negative selected generator-group mark was admitted as nonnegative finite-MC law'


def test_negative_rejected_event_does_not_invalidate_selected_nonnegative_law(tmp_path):
    d = split_first_group(tmp_path, negative_selected=False)
    result = op.run(owner.task(tmp_path, d), tmp_path, tmp_path/'out')
    assert result['prepared_cells'] == 4
    bundle = json.loads((tmp_path/'out/response-p0/complete-response.json').read_text())
    assert bundle['events'] == 6
    assert any(row['weights']['nominal'] < 0 for row in bundle['anchor_records'][0])


def test_same_group_cancellation_retains_group_poisson_unit(tmp_path):
    d = split_first_group(tmp_path, same_group=True)
    result = op.run(owner.task(tmp_path, d), tmp_path, tmp_path/'out')
    bundle = json.loads((tmp_path/'out/response-p0/complete-response.json').read_text())
    first = bundle['destination_ids'].index('s0')
    assert bundle['group_marks']['nominal']['g0'][first] == 4
    assert bundle['weights']['nominal']['conditional_group_covariance'][first][first] == 16
    assert result['prepared_cells'] == 4


def test_known_control_missing_blocks_all_cells(tmp_path):
    d = owner.fixture(tmp_path)
    d['analysis']['unresolved_bins'] = [{'id': '1L_0', 'role': 'CR', 'reason': 'Known basis; signal and nuisance response unavailable'}]
    result = op.run(owner.task(tmp_path, d), tmp_path, tmp_path/'out')
    assert result['blocked_cells'] == len(result['cells']) == 4
    assert not list((tmp_path/'out').rglob('expected-science.json'))
