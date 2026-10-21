"""Supplied result templates are filled only from accepted results, never by guessing."""
import hashlib
import json
import math
from pathlib import Path

import pytest
import yaml

from ravel import cli
from ravel.physics import quantities
from ravel.workflow import result_templates as rt
from test_task_completion import review_run

HEPDATA = """\
name: Missing transverse momentum
description: Expected signal yield per bin.
independent_variables:
- header: {name: MET, units: GeV}
  values:
  - {low: 250, high: 350}
  - {low: 350, high: 450}
dependent_variables:
- header: {name: Events}
  qualifiers:
  - {name: SQRT(S), units: GeV, value: 13000}
  values:
  - {value: null}
  - {value: null}
"""


def table(bins, **extra):
    return {'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': 'MET', 'unit': 'GeV'}],
            'unit': 'events', 'representation': 'integrated', 'bins': bins, **extra}


def edges(*pairs, values=None, sigma=None):
    out = []
    for i, (lo, hi) in enumerate(pairs):
        row = {'low': [lo], 'high': [hi], 'value': (values or [1.0] * len(pairs))[i]}
        if sigma is not None:
            row['uncertainty'] = sigma[i]
        out.append(row)
    return out


def accepted_run(root, monkeypatch, document, *, capture=True):
    result = root / 'inputs/result.json'
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(document))
    review_run(root, [str(result)] if capture else [], monkeypatch)
    return result


def template(path, text=HEPDATA):
    path.write_text(text)
    return path


def run_fill(tmp_path, monkeypatch, document, text=HEPDATA, suffix='.yaml', **kwargs):
    rd = tmp_path / 'run'
    result = accepted_run(rd, monkeypatch, document)
    tpl = template(tmp_path / ('template' + suffix), text)
    out = tmp_path / ('filled' + suffix)
    record = rt.fill(tpl, result, out, rundir=rd, claim_scope='diagnostic', base_dir=tmp_path, **kwargs)
    return record, tpl, result, out


def test_exact_bins_fill_values_and_keep_every_edge(tmp_path, monkeypatch):
    record, tpl, result, out = run_fill(tmp_path, monkeypatch, table(edges((250, 350), (350, 450), values=[12.0, 4.0])))
    filled = yaml.safe_load(out.read_text())
    original = yaml.safe_load(tpl.read_text())
    assert [v['value'] for v in filled['dependent_variables'][0]['values']] == [12.0, 4.0]
    assert filled['independent_variables'] == original['independent_variables']
    filled['dependent_variables'][0].pop('values'); original['dependent_variables'][0].pop('values')
    assert filled == original
    assert record['bins'][0]['operation'] == 'exact' and record['bins'][1]['result_bins'] == [1]
    assert record['edges_unchanged'] and record['values_from_result_only'] and not record['physics_validated']


def test_provenance_records_hashes_acceptance_and_units(tmp_path, monkeypatch):
    record, tpl, result, out = run_fill(tmp_path, monkeypatch, table(edges((250, 350), (350, 450))))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert record['template']['sha256'] == digest(tpl)
    assert record['result']['sha256'] == digest(result)
    assert record['output']['sha256'] == digest(out)
    assert record['acceptance']['review_accepted'] and record['acceptance']['claim_scope'] == 'diagnostic'
    assert record['acceptance']['delivery_label'] == 'diagnostic' and record['acceptance']['accepted'] is False
    assert record['units']['axes'][0] == {'template_name': 'MET', 'template_unit': 'GeV', 'result_name': 'MET', 'result_unit': 'GeV'}
    assert record['units']['value'] == {'template': None, 'result': 'events'}
    saved = json.loads(out.with_name(out.name + '.provenance.json').read_text())
    assert saved == json.loads(json.dumps(record))


def test_non_diagnostic_fill_without_a_governed_launch_is_refused(tmp_path, monkeypatch):
    # The accepted review covers this result, but no approval-bound supervised launch produced
    # its bytes: only the diagnostic scope may deliver it.
    rd = tmp_path / 'run'
    result = rd / 'inputs/result.json'
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps(table(edges((250, 350), (350, 450)))))
    review_run(rd, [str(result)], monkeypatch, scope='original_task_completion')
    out = tmp_path / 'filled.yaml'
    with pytest.raises(ValueError, match='accepted delivery refused'):
        rt.fill(template(tmp_path / 'template.yaml'), result, out, rundir=rd,
                claim_scope='original_task_completion', base_dir=tmp_path)
    assert not out.exists()


def test_weighted_quantities_fill_plain_json_template_with_covariance_uncertainty(tmp_path, monkeypatch):
    contract = quantities.validate({'schema_version': 1, 'axes': [{'name': 'pT', 'unit': 'GeV'}],
        'bins': [{'id': 'a', 'low': [0.0], 'high': [1.0]}, {'id': 'b', 'low': [1.0], 'high': [3.0]}],
        'weight_names': ['nominal'], 'input_weight_unit': 'pb', 'representation': 'integrated',
        'normalization': {'kind': 'absolute', 'scale': 1.0, 'unit': 'pb'}})
    result = quantities.calculate(contract, [
        {'event_id': 'e1', 'group_id': 'g1', 'shard_id': 's', 'weights': {'nominal': 2.0}, 'fills': [[0.5], [2.0]]},
        {'event_id': 'e2', 'group_id': 'g2', 'shard_id': 's', 'weights': {'nominal': -1.0}, 'fills': [[2.0]]}])
    plain = {'schema_version': 1, 'kind': 'result_template', 'axes': [{'name': 'pT', 'unit': 'GeV'}], 'unit': 'pb',
             'bins': [{'low': [0], 'high': [1], 'value': None}, {'low': [1], 'high': [3], 'value': None}]}
    record, _, _, out = run_fill(tmp_path, monkeypatch, result, json.dumps(plain), '.json')
    filled = json.loads(out.read_text())
    assert [b['value'] for b in filled['bins']] == [2.0, 1.0]
    assert [[b['low'], b['high']] for b in filled['bins']] == [[[0], [1]], [[1], [3]]]
    assert record['bins'][0]['uncertainty'] == pytest.approx(2.0) and record['bins'][1]['uncertainty'] == pytest.approx(math.sqrt(5.0))


def test_declared_overflow_in_last_bin_adds_content_above_its_lower_edge(tmp_path, monkeypatch):
    text = HEPDATA.replace("  - {name: SQRT(S), units: GeV, value: 13000}\n",
                           "  - {name: SQRT(S), units: GeV, value: 13000}\n  - {name: overflow, value: last-bin}\n")
    document = table(edges((250, 350), (350, 450), (450, 600), values=[12.0, 4.0, 2.0]), overflow=0.5)
    record, _, _, out = run_fill(tmp_path, monkeypatch, document, text)
    values = [v['value'] for v in yaml.safe_load(out.read_text())['dependent_variables'][0]['values']]
    assert values == [12.0, 6.5]
    last = record['bins'][1]
    assert last['operation'] == 'includes-overflow' and last['result_bins'] == [1, 2]
    assert last['flow_added'] == [{'flow': 'overflow', 'value': 0.5}] and last['high'] == [450.0]
    assert record['conventions']['overflow'] == 'last-bin'


def test_mentioned_but_undeclared_overflow_is_refused(tmp_path, monkeypatch):
    text = HEPDATA.replace('Expected signal yield per bin.', 'The last bin includes overflow.')
    with pytest.raises(ValueError, match='mentions overflow'):
        run_fill(tmp_path, monkeypatch, table(edges((250, 350), (350, 450))), text)


def test_combined_quantity_flow_cannot_fill_an_overflow_bin(tmp_path, monkeypatch):
    contract = quantities.validate({'schema_version': 1, 'axes': [{'name': 'MET', 'unit': 'GeV'}],
        'bins': [{'id': 'a', 'low': [250.0], 'high': [350.0]}, {'id': 'b', 'low': [350.0], 'high': [450.0]}],
        'weight_names': ['nominal'], 'input_weight_unit': 'events', 'representation': 'integrated',
        'normalization': {'kind': 'absolute', 'scale': 1.0, 'unit': 'events'}})
    result = quantities.calculate(contract, [{'event_id': 'e', 'group_id': 'g', 'shard_id': 's',
                                              'weights': {'nominal': 1.0}, 'fills': [[300.0], [500.0]]}])
    text = HEPDATA.replace("  - {name: SQRT(S), units: GeV, value: 13000}\n",
                           "  - {name: SQRT(S), units: GeV, value: 13000}\n  - {name: overflow, value: last-bin}\n")
    with pytest.raises(ValueError, match='combined sum'):
        run_fill(tmp_path, monkeypatch, result, text)


def test_mismatched_edges_are_refused_and_never_moved(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='exactly these edges'):
        run_fill(tmp_path, monkeypatch, table(edges((250, 340), (340, 450))))
    assert not (tmp_path / 'filled.yaml').exists()


def test_declared_rebinning_merges_adjacent_bins_and_preserves_totals(tmp_path, monkeypatch):
    document = table(edges((250, 300), (300, 350), (350, 450), values=[5.0, 7.0, 4.0]))
    rebinning = {'schema_version': 1, 'reason': 'Result was produced on finer bins.',
                 'merges': [{'template_bin': 0, 'result_bins': [0, 1]}]}
    record, _, _, out = run_fill(tmp_path, monkeypatch, document, rebinning=rebinning)
    values = [v['value'] for v in yaml.safe_load(out.read_text())['dependent_variables'][0]['values']]
    assert values == [12.0, 4.0]
    assert record['bins'][0]['operation'] == 'declared-merge' and record['rebinning'] == rebinning
    assert record['totals'] == {'filled': 16.0, 'from_result': 16.0}


def test_rebinning_that_does_not_tile_the_template_bin_is_refused(tmp_path, monkeypatch):
    document = table(edges((250, 300), (310, 350), (350, 450)))
    rebinning = {'schema_version': 1, 'reason': 'gap', 'merges': [{'template_bin': 0, 'result_bins': [0, 1]}]}
    with pytest.raises(ValueError, match='does not tile'):
        run_fill(tmp_path, monkeypatch, document, rebinning=rebinning)


def test_unit_mismatch_is_refused(tmp_path, monkeypatch):
    document = table(edges((250, 350), (350, 450)))
    document['axes'][0]['unit'] = 'TeV'
    with pytest.raises(ValueError, match='never converted'):
        run_fill(tmp_path, monkeypatch, document)


def test_result_outside_the_accepted_review_is_refused(tmp_path, monkeypatch):
    rd = tmp_path / 'run'
    result = accepted_run(rd, monkeypatch, table(edges((250, 350), (350, 450))), capture=False)
    with pytest.raises(ValueError, match='did not capture'):
        rt.fill(template(tmp_path / 't.yaml'), result, tmp_path / 'filled.yaml', rundir=rd,
                claim_scope='diagnostic', base_dir=tmp_path)
    assert not (tmp_path / 'filled.yaml').exists()


def test_unreviewed_result_and_wrong_scope_are_refused(tmp_path, monkeypatch):
    rd = tmp_path / 'plain'
    (rd / 'inputs').mkdir(parents=True)
    result = rd / 'inputs/result.json'
    result.write_text(json.dumps(table(edges((250, 350), (350, 450)))))
    with pytest.raises((ValueError, OSError)):
        rt.fill(template(tmp_path / 't.yaml'), result, tmp_path / 'a.yaml', rundir=rd, claim_scope='diagnostic', base_dir=tmp_path)
    reviewed = tmp_path / 'run'
    captured = accepted_run(reviewed, monkeypatch, table(edges((250, 350), (350, 450))))
    with pytest.raises(ValueError, match='accepted actual review'):
        rt.fill(tmp_path / 't.yaml', captured, tmp_path / 'b.yaml', rundir=reviewed, claim_scope='reproduction', base_dir=tmp_path)


def test_filled_column_and_existing_output_are_never_overwritten(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='empty dependent columns'):
        run_fill(tmp_path, monkeypatch, table(edges((250, 350), (350, 450))), HEPDATA.replace('{value: null}', '{value: 3}'))
    out = tmp_path / 'exists.yaml'
    out.write_text('keep\n')
    with pytest.raises(ValueError, match='never overwritten'):
        rt.fill(template(tmp_path / 't.yaml'), tmp_path / 'run/inputs/result.json', out, rundir=tmp_path / 'run',
                claim_scope='diagnostic', base_dir=tmp_path)
    assert out.read_text() == 'keep\n'


def test_cli_fill_template_writes_output_and_provenance(tmp_path, monkeypatch, capsys):
    rd = tmp_path / 'run'
    result = accepted_run(rd, monkeypatch, table(edges((250, 350), (350, 450), values=[2.0, 3.0], sigma=[0.5, 1.0])))
    tpl = template(tmp_path / 't.yaml')
    out = tmp_path / 'out/filled.yaml'
    assert cli.main(['fill-template', '--template', str(tpl), '--result', str(result), '--out', str(out),
                     '--rundir', str(rd), '--claim-scope', 'diagnostic', '--base', str(tmp_path),
                     '--uncertainty-label', 'stat']) == 0
    rows = yaml.safe_load(out.read_text())['dependent_variables'][0]['values']
    assert rows == [{'value': 2.0, 'errors': [{'symerror': 0.5, 'label': 'stat'}]},
                    {'value': 3.0, 'errors': [{'symerror': 1.0, 'label': 'stat'}]}]
    assert json.loads(capsys.readouterr().out)['bins'] == 2
    assert Path(str(out) + '.provenance.json').is_file()
