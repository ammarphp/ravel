"""Synthetic requester layouts and custody refusals."""
import json
from pathlib import Path

import pytest

from test_result_templates import HEPDATA, table, edges
from test_task_completion import review_run
from ravel.workflow import result_templates as rt


def delivery():
    from ravel.workflow import requester_delivery
    return requester_delivery


def study(tmp_path, monkeypatch):
    rd = tmp_path / 'ANA-0001'
    (rd / 'results').mkdir(parents=True)
    result = rd / 'results/values.json'
    result.write_text(json.dumps(table(edges((0, 1), (1, 2), values=[2.0, 3.0]))))
    files = {'analysis.py': 'values = [float(i) for i in range(2)]\n',
             'detector.tcl': '# fictional card\n', 'selected.parquet': 'fictional event bytes'}
    for name, value in files.items():
        (rd / name).write_text(value)
    receipt = rd / 'production.json'
    receipt.write_text(json.dumps({'kind': 'ravel-production-receipt',
        'generator': {'version': 'fictional-1'}, 'shower': {'version': 'fictional-2'},
        'detector': {'version': 'fictional-3'}, 'events': {'attempted': 10, 'accepted': 8},
        'sigma': {'value_pb': 1.0, 'order': 'LO', 'pdf': 'fictional-pdf',
                  'source': {'table_id': 'TABLE-0001', 'sha256': 'a' * 64}},
        'luminosity_ifb': 2.0, 'normalization_ledger': {'recomputed_total': 5.0}}))
    review_run(rd, [str(result), str(receipt), *(str(rd / name) for name in files)], monkeypatch)
    tpl = tmp_path / 'template.yaml'
    tpl.write_text(HEPDATA.replace('250, high: 350', '0, high: 1').replace('350, high: 450', '1, high: 2'))
    rt.fill(tpl, result, rd / 'results/filled.yaml', rundir=rd, claim_scope='diagnostic')
    return rd


def layout(**kwargs):
    return {'analysis_code': 'code/', 'cards': 'cards/', 'selected_events': 'events/',
            'templates': ['results/*.yaml'], 'report': 'note.md', **kwargs}


def test_hand_edited_template_reports_both_hashes(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'workspace'
    mod.deliver(rd, layout(), ws)
    path = ws / 'results/filled.yaml'; before = mod.file_sha256(path)
    path.write_text(path.read_text() + '\n# hand edit\n'); after = mod.file_sha256(path)
    with pytest.raises(ValueError) as caught:
        mod.verify(ws)
    assert all(s in str(caught.value) for s in ('hand-edited', str(path.relative_to(ws)), before, after))


def test_literal_fallback_array_is_reported(tmp_path):
    mod = delivery(); bad = tmp_path / 'literal.py'; good = tmp_path / 'computed.py'
    bad.write_text('values = [-1.0, 2.0]\n'); good.write_text('values = [float(i) for i in range(2)]\n')
    found = mod.literal_scan([bad, good], table_lengths=[2])
    assert len(found) == 1 and found[0]['path'] == str(bad) and found[0]['length'] == 2


def test_unaccepted_study_refused(tmp_path):
    rd = tmp_path / 'ANA-0002'; rd.mkdir()
    with pytest.raises(ValueError, match='accepted'):
        delivery().deliver(rd, layout(), tmp_path / 'ws')
    assert not (tmp_path / 'ws').exists()


def test_unknown_layout_key_refused(tmp_path):
    with pytest.raises(ValueError, match='unknown'):
        delivery().validate_layout({'unknown': 'x'})


@pytest.mark.parametrize('value', ['../escape', '/absolute', 'nested/../../escape'])
def test_layout_escape_refused(tmp_path, value):
    with pytest.raises(ValueError, match='relative|escape'):
        delivery().deliver(tmp_path, layout(report=value), tmp_path / 'ws')


def test_layout_symlink_refused(tmp_path, monkeypatch):
    rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'; ws.mkdir()
    (ws / 'code').symlink_to(rd, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        delivery().deliver(rd, layout(), ws)


@pytest.mark.parametrize('supplied', [layout(), {'analysis_code': 'src/custom/', 'cards': 'inputs/sim/',
    'selected_events': 'samples/skim/', 'templates': ['results/filled.yaml'], 'report': 'docs/report.txt',
    'copy_limit_mb': 0}])
def test_two_requester_layouts_copy_reference_and_provenance(tmp_path, monkeypatch, supplied):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    report = ws / supplied['report']; report.parent.mkdir(parents=True)
    report.write_text('Requester text.\n')
    index = mod.deliver(rd, supplied, ws)
    assert (ws / supplied['analysis_code'] / 'analysis.py').is_file()
    assert (ws / supplied['cards'] / 'detector.tcl').is_file()
    event = next(row for row in index['files'] if row['category'] == 'selected_events')
    assert ('reference' in event) == (supplied.get('copy_limit_mb') == 0)
    assert (ws / event['path']).exists() == ('reference' not in event)
    content = report.read_text(); block = content.split(mod.BEGIN)[1]
    assert content.startswith('Requester text.\n') and len(block.encode()) < 6 * 1024
    for word in ('ANA-0001', 'code_version', 'generator', 'shower', 'detector', 'cards', 'sha256',
                 'attempted', 'accepted', 'cross_section', 'LO', 'pdf', 'source_table',
                 'luminosity', 'ledger_recomputed_total', 'reviews', 'sequence', 'verdict', 'actor_kind', 'fill'):
        assert word in block
    assert 'human review' not in block
    assert mod.verify(ws)['run'] == 'ANA-0001'


def test_missing_delivered_file_refused(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    mod.deliver(rd, layout(), ws); (ws / 'code/analysis.py').unlink()
    with pytest.raises(ValueError, match='missing.*analysis.py'):
        mod.verify(ws)


def test_machine_actor_kind_retained(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    original = mod._review
    def recorded(root):
        scope, cycle, reviews = original(root)
        for review in reviews:
            review['actor_kind'] = 'machine'
        return scope, cycle, reviews
    monkeypatch.setattr(mod, '_review', recorded)
    mod.deliver(rd, layout(), ws)
    text = (ws / 'note.md').read_text()
    assert '"actor_kind":"machine"' in text and 'human review' not in text


def test_all_keys_omitted_is_supported(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    mod.deliver(rd, {}, ws)
    assert mod.verify(ws)['report'] is None


def test_report_cannot_collide_with_index(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    with pytest.raises(ValueError, match='collid'):
        mod.deliver(rd, layout(report=mod.INDEX), ws)
    assert not ws.exists()


def test_recipe_is_delivered_as_analysis_code(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch)
    recipe = rd / 'recipe.json'; recipe.write_text(json.dumps({'kind': 'columnar-analysis-recipe', 'schema_version': 1}))
    # A fresh synthetic accepted cycle includes the recipe in its captured inputs.
    other = tmp_path / 'ANA-0003'
    import shutil
    (other / 'results').mkdir(parents=True)
    for name in ('analysis.py', 'detector.tcl', 'selected.parquet', 'production.json', 'recipe.json'):
        shutil.copyfile(rd / name, other / name)
    shutil.copyfile(rd / 'results/values.json', other / 'results/values.json')
    review_run(other, [str(p) for p in other.rglob('*') if p.is_file()], monkeypatch)
    mod.deliver(other, {'analysis_code': 'logic/'}, tmp_path / 'ws')
    assert (tmp_path / 'ws/logic/recipe.json').is_file()


def test_nested_ledger_total_is_recomputed_not_taken_on_trust(tmp_path):
    from test_normalization_ledger import ledger
    from ravel.physics import normalization_ledger as nl
    mod = delivery(); doc = ledger()
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps({'kind': 'ravel-production-receipt',
        'sigma': {'normalization_ledger': doc, 'value_pb': 1.0}}))
    rows = mod._physics([path])
    assert rows[0]['ledger_recomputed_total'] == pytest.approx(
        nl._integrated_total(doc, nl.expected_yields(doc)))
    assert rows[0]['pdf'] == doc['sigma']['pdf']


def test_generation_receipt_point_fields_are_indexed(tmp_path):
    mod = delivery(); path = tmp_path / 'receipt.json'
    path.write_text(json.dumps({'kind': 'generation-receipt', 'generator': {'version': 'fictional'},
        'pdf': {'name': 'fictional-pdf'}, 'points': [{'id': 'POINT-0001',
        'events': {'generated': 4, 'accepted': 3}, 'cards': [{'sha256': 'a' * 64}],
        'cross_section': {'value_pb': 2.0, 'order': 'LO'}}]}))
    rows = mod._physics([path])
    assert rows[0]['events'] == {'generated': 4, 'accepted': 3}
    assert rows[0]['cross_section']['value_pb'] == 2.0
    assert rows[0]['cards'][0]['sha256'] == 'a' * 64


def test_parent_file_collision_refused_before_copy(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'; ws.mkdir()
    (ws / 'code').write_text('owned requester file')
    with pytest.raises(ValueError, match='directory'):
        mod.deliver(rd, layout(), ws)
    assert not (ws / 'cards').exists()


def test_verify_fill_record_must_agree_with_index(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    mod.deliver(rd, layout(), ws)
    index_path = ws / mod.INDEX; index = json.loads(index_path.read_text())
    next(row for row in index['files'] if 'fill' in row)['fill']['result_sha256'] = 'b' * 64
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match='fill provenance'):
        mod.verify(ws)


def test_oversized_index_refused_without_writes(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    monkeypatch.setattr(mod, 'code_version', lambda: {'version': 'x' * 7000})
    with pytest.raises(ValueError, match='6 kB'):
        mod.deliver(rd, layout(), ws)
    assert not ws.exists()


def test_workspace_overlapping_run_refused(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='overlap'):
        mod.deliver(rd, layout(), rd / 'nested')
    assert not (rd / 'nested').exists()


def test_cli_deliver_and_verify(tmp_path, monkeypatch):
    from ravel import cli
    rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'; config = tmp_path / 'layout.json'
    config.write_text(json.dumps(layout()))
    assert cli.main(['deliver-workspace', '--rundir', str(rd), '--layout', str(config), '--into', str(ws)]) == 0
    assert cli.main(['deliver-workspace', 'verify', '--into', str(ws)]) == 0


def test_schema_and_runtime_refuse_same_unknown_keys_and_escapes():
    import jsonschema
    mod = delivery()
    schema = json.loads((Path(__file__).resolve().parents[2] / 'src/ravel/data/schemas/requester-layout.schema.json').read_text())
    for supplied in ({'unknown': 1}, {'cards': '../x'}, {'report': '/x'}, {'templates': ['../*.yaml']}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(supplied, schema)
        with pytest.raises(ValueError):
            mod.validate_layout(supplied)
    for supplied in ({}, layout(), {'templates': ['tables/*/*.json']}):
        jsonschema.validate(supplied, schema)
        mod.validate_layout(supplied)


def test_symlinked_source_inside_run_refused(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch)
    (tmp_path / 'outside.yaml').write_text('outside\n')
    (rd / 'results/linked.yaml').symlink_to(tmp_path / 'outside.yaml')
    with pytest.raises(ValueError, match='symlink'):
        mod.deliver(rd, layout(), tmp_path / 'ws')
    assert not (tmp_path / 'ws').exists()


def test_unpatched_review_actor_kind_is_never_inferred(tmp_path, monkeypatch):
    mod = delivery(); rd = study(tmp_path, monkeypatch); ws = tmp_path / 'ws'
    index = mod.deliver(rd, layout(), ws)
    assert index['reviews'] and {r['actor_kind'] for r in index['reviews']} == {'unrecorded'}
    assert 'human' not in (ws / 'note.md').read_text()
