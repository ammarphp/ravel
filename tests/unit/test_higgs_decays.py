"""Synthetic card, format and conservation contracts; no native physics execution."""
from copy import deepcopy
import importlib

import pytest


def api():
    return importlib.import_module('ravel.physics.higgs_decays')


def point(program='HDECAY'):
    return {'schema_version': 1, 'program': program, 'version': 'synthetic-1',
            'order': 'synthetic-order', 'ew_scheme': 'synthetic-scheme',
            'physics_inputs': {'alpha_s_mz': .12, 'mb_mb_GeV': 4., 'mc_GeV': 1.,
                               'mt_pole_GeV': 170., 'gamma_w_GeV': 2., 'gamma_z_GeV': 3.,
                               'gf_GeV_minus2': .00001},
            'parameters': {'mass_GeV': 160., 'mixing': 0.},
            'scalars': [{'pdg': 25, 'mass_GeV': 160., 'coverage': 'complete'}]}


def table():
    p = point()
    return {'schema_version': 1, 'program': p['program'], 'version': p['version'],
            'order': p['order'], 'ew_scheme': p['ew_scheme'], 'units': 'GeV',
            'scalars': [{'pdg': 25, 'mass_GeV': 160., 'coverage': 'complete',
                         'total_width_GeV': 10., 'channels': [
                             {'id': 'bb', 'daughters': [5, -5], 'partial_width_GeV': 6.,
                              'branching_ratio': .6, 'program': 'HDECAY'},
                             {'id': 'WW', 'daughters': [24, -24], 'partial_width_GeV': 4.,
                              'branching_ratio': .4, 'program': 'HDECAY'}]}]}


@pytest.mark.parametrize('mutation', ['channel', 'table'])
def test_mixed_program_branching_set_is_refused(mutation):
    d = table()
    if mutation == 'channel':
        d['scalars'][0]['channels'][1]['program'] = '2HDMC'
    else:
        d['program'] = '2HDMC'
    with pytest.raises(ValueError, match='program'):
        api().validate_table(d)


@pytest.mark.parametrize('field', ['alpha_s_mz', 'mb_mb_GeV', 'mc_GeV',
                                    'mt_pole_GeV', 'gamma_w_GeV', 'gamma_z_GeV', 'ew_scheme'])
def test_missing_physics_input_is_refused_without_defaults(field):
    p = point()
    del (p if field == 'ew_scheme' else p['physics_inputs'])[field]
    with pytest.raises(ValueError, match=field):
        api().validate_point(p)


@pytest.mark.parametrize('delta', [.00002, -.00002])
def test_partial_width_sum_outside_relative_tolerance_is_refused(delta):
    d = table()
    d['scalars'][0]['total_width_GeV'] += delta
    for c in d['scalars'][0]['channels']:
        c['branching_ratio'] = c['partial_width_GeV'] / d['scalars'][0]['total_width_GeV']
    with pytest.raises(ValueError, match='sum'):
        api().validate_table(d)


@pytest.mark.parametrize('mutation', ['nan', 'negative', 'duplicate', 'permutation', 'ratio', 'zero', 'bool'])
def test_invalid_width_table_is_refused(mutation):
    d = table(); scalar = d['scalars'][0]; c = scalar['channels'][0]
    if mutation == 'nan': c['partial_width_GeV'] = float('nan')
    elif mutation == 'negative': c['partial_width_GeV'] = -1.
    elif mutation == 'duplicate': scalar['channels'].append(deepcopy(c))
    elif mutation == 'permutation':
        copied = deepcopy(c); copied['id'] = 'other'; copied['daughters'].reverse()
        scalar['channels'].append(copied)
    elif mutation == 'ratio': c['branching_ratio'] = .2
    elif mutation == 'zero': scalar['total_width_GeV'] = 0.
    else: c['partial_width_GeV'] = True
    with pytest.raises(ValueError): api().validate_table(d)


def test_reference_comparison_refuses_wrong_mass_units_or_program():
    for field, value in [('mass_GeV', 161.), ('unit', 'MeV'), ('program', '2HDMC')]:
        row = {'id': 'ANA-0001', 'channel': 'Gamma_H', 'mass_GeV': 160.,
               'quantity': 'total_width', 'value': 10., 'unit': 'GeV',
               'citation': 'synthetic://source', 'program': 'HDECAY'}
        row[field] = value
        with pytest.raises(ValueError): api().compare_reference(table(), [row], pdg=25)


def format_spec(program='HDECAY', kind='column_tables'):
    p = point(program)
    fields = {'ew_scheme': {'kind': 'enum', 'tokens': {'synthetic-scheme': '1'}}}
    fields.update({f'physics_inputs.{k}': {'kind': 'number'} for k in p['physics_inputs']})
    fields.update({f'parameters.{k}': {'kind': 'number'} for k in p['parameters']})
    fields['scalars.25.mass_GeV'] = {'kind': 'number'}
    channels = [{'id': 'bb', 'daughters': [5, -5]}, {'id': 'WW', 'daughters': [24, -24]}]
    if kind == 'column_tables':
        layout = {'kind': kind, 'unit': 'GeV', 'files': [
            {'name': 'br.sm1', 'columns': 2, 'skip_rows': 1, 'mass_column': 0,
             'total_width_column': None,
             'channels': [{**channels[0], 'column': 1, 'quantity': 'branching_ratio'}]},
            {'name': 'br.sm2', 'columns': 3, 'skip_rows': 1, 'mass_column': 0,
             'total_width_column': 2,
             'channels': [{**channels[1], 'column': 1, 'quantity': 'branching_ratio'}]}]}
    elif kind == 'slha':
        layout = {'kind': kind, 'unit': 'GeV', 'name': 'synthetic.slha', 'channels': channels}
    else:
        layout = {'kind': kind, 'unit': 'GeV', 'files': [
            {'name': 'synthetic.out', 'pdg': 25, 'separator': '=', 'mass_key': 'mass',
             'total_width_key': 'width', 'channels': [
                 {**channels[0], 'key': 'bb', 'quantity': 'partial_width'},
                 {**channels[1], 'key': 'WW', 'quantity': 'partial_width'}]}]}
    return {'schema_version': 1, 'program': program, 'version': 'synthetic-1',
            'order': 'synthetic-order',
            'complete_input_schema_declared': True,
            'card': {'filename': 'synthetic.in', 'fields': fields,
                     'template': '\n'.join(k + ' = ${' + k + '}' for k in fields) + '\n'},
            'layout': layout}


@pytest.mark.parametrize('mutation', ['missing-template-field', 'unused-input', 'nonfinite',
                                     'scheme', 'version', 'program', 'incomplete-schema', 'escape'])
def test_card_contract_refuses_omission_and_incompatible_source(mutation):
    p = point(); f = format_spec()
    if mutation == 'missing-template-field':
        f['card']['template'] = f['card']['template'].replace('${physics_inputs.mc_GeV}', '1')
    elif mutation == 'unused-input': p['parameters']['unmapped'] = 1.
    elif mutation == 'nonfinite': p['physics_inputs']['alpha_s_mz'] = float('inf')
    elif mutation == 'scheme': p['ew_scheme'] = 'unknown'
    elif mutation == 'version': p['version'] = 'synthetic-2'
    elif mutation == 'program': f['program'] = '2HDMC'
    elif mutation == 'incomplete-schema': f['complete_input_schema_declared'] = False
    else: f['card']['filename'] = '../synthetic.in'
    with pytest.raises(ValueError): api().adapter('HDECAY').render_card(p, f)


@pytest.mark.parametrize('mutation', ['missing-file', 'duplicate-mass', 'width-sum', 'nan',
                                     'extra-column', 'wrong-mass', 'unit'])
def test_parser_refuses_incomplete_or_ambiguous_column_tables(mutation):
    p = point(); f = format_spec()
    outputs = {'br.sm1': '# synthetic\n160 .6\n', 'br.sm2': '# synthetic\n160 .4 10\n'}
    if mutation == 'missing-file': del outputs['br.sm1']
    elif mutation == 'duplicate-mass': outputs['br.sm1'] += '160 .6\n'
    elif mutation == 'width-sum': outputs['br.sm2'] = '# synthetic\n160 .3 10\n'
    elif mutation == 'nan': outputs['br.sm1'] = '# synthetic\n160 nan\n'
    elif mutation == 'extra-column': outputs['br.sm1'] = '# synthetic\n160 .6 1\n'
    elif mutation == 'wrong-mass': outputs['br.sm1'] = '# synthetic\n161 .6\n'
    else: f['layout']['unit'] = 'MeV'
    with pytest.raises(ValueError): api().adapter('HDECAY').parse_outputs(p, f, outputs)


@pytest.mark.parametrize('raw', [
    'DECAY 25 10\n.6 2 5 -5\n.4 2 5 -5\n',
    'DECAY 25 10\n.6 2 5\n.4 2 24 -24\n',
    'DECAY 25 10\n.6 2 5 -5\n.4 2 24 -24\nDECAY 25 10\n',
    'DECAY 25 nan\n.6 2 5 -5\n.4 2 24 -24\n',
])
def test_parser_refuses_malformed_slha(raw):
    with pytest.raises(ValueError):
        api().adapter('2HDMC').parse_outputs(point('2HDMC'), format_spec('2HDMC', 'slha'),
                                           {'synthetic.slha': raw})


def test_subset_cannot_be_serialized_as_complete_decay_or_compared_as_total():
    d = table(); d['scalars'][0]['coverage'] = 'four_fermion'
    d['scalars'][0]['channels'][0]['daughters'] = [11, -11, 12, -12]
    d['scalars'][0]['channels'][1]['daughters'] = [13, -13, 14, -14]
    with pytest.raises(ValueError, match='complete'): api().to_slha(d)
    with pytest.raises(ValueError, match='complete'):
        api().compare_reference(d, [{'id': 'ANA-0001', 'channel': 'Gamma_H', 'quantity': 'total_width',
                                    'mass_GeV': 160., 'value': 10., 'unit': 'GeV',
                                    'citation': 'synthetic://reference'}], pdg=25)


def test_comparison_refuses_duplicate_or_missing_reference_channels():
    row = {'id': 'ANA-0001', 'channel': 'bb', 'quantity': 'branching_ratio',
           'mass_GeV': 160., 'value': .6, 'unit': '1', 'citation': 'synthetic://reference'}
    with pytest.raises(ValueError): api().compare_reference(table(), [row, deepcopy(row)], pdg=25)
    with pytest.raises(ValueError): api().compare_reference(table(), [row], pdg=25, required_channels=['cc'])


PROGRAM_LAYOUTS = [('HDECAY', 'column_tables'), ('eHDECAY', 'column_tables'),
                   ('2HDECAY', 'slha'), ('sHDECAY', 'column_tables'),
                   ('N2HDECAY', 'column_tables'), ('Prophecy4f', 'key_values'),
                   ('2HDMC', 'slha'), ('FeynHiggs', 'slha')]


def supplied_outputs(kind):
    if kind == 'column_tables':
        return {'br.sm1': '# synthetic header\n160 6D-1\n',
                'br.sm2': '# synthetic header\n160 4D-1 1D1\n'}
    if kind == 'slha':
        return {'synthetic.slha': 'BLOCK MASS\n25 160\nDECAY 25 1D1\n6D-1 2 5 -5\n4D-1 2 24 -24\n'}
    return {'synthetic.out': '# synthetic widths\nmass = 160\nwidth = 10\nbb = 6\nWW = 4\n'}


def pin(path):
    from hashlib import sha256
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def request_fixture(tmp_path, action='parse'):
    import json
    files = {'point.json': point(), 'format.json': format_spec()}
    for name, content in files.items():
        (tmp_path / name).write_text(json.dumps(content))
    (tmp_path / 'source.txt').write_text('Synthetic complete card/layout description, not a program manual.\n')
    request = {'schema_version': 1, 'action': action,
               'point': pin(tmp_path / 'point.json'), 'format': pin(tmp_path / 'format.json'),
               'format_source': pin(tmp_path / 'source.txt'),
               'publication': {'json': 'result.json', 'slha': 'widths.slha'}}
    if action == 'parse':
        request['outputs'] = []
        for name, text in supplied_outputs('column_tables').items():
            path = tmp_path / name; path.write_text(text)
            request['outputs'].append({'name': name, **pin(path)})
    else:
        binary = tmp_path / 'synthetic-binary'
        binary.write_text('Inert synthetic binary pin; never executed.\n')
        request['execution'] = {'binary': pin(binary), 'arguments': [],
                                'max_seconds': 4., 'disk_bytes': 8192}
    path = tmp_path / 'request.json'; path.write_text(json.dumps(request))
    return {'request': str(path)}, request


@pytest.mark.parametrize('mutation', ['changed-output', 'changed-source', 'source-symlink',
                                     'duplicate-output', 'publication-alias', 'output-alias'])
def test_operation_refuses_changed_pins_aliases_and_duplicate_files(tmp_path, mutation):
    import json
    task, request = request_fixture(tmp_path)
    destination = tmp_path / 'delivery'
    if mutation == 'changed-output': (tmp_path / 'br.sm1').write_text('160 .6\n')
    elif mutation == 'changed-source': (tmp_path / 'source.txt').write_text('changed synthetic source')
    elif mutation == 'source-symlink':
        (tmp_path / 'source.txt').rename(tmp_path / 'other.txt')
        (tmp_path / 'source.txt').symlink_to(tmp_path / 'other.txt')
    elif mutation == 'duplicate-output': request['outputs'].append(deepcopy(request['outputs'][0]))
    elif mutation == 'publication-alias': request['publication']['json'] = 'synthetic.in'
    else: destination = tmp_path
    (tmp_path / 'request.json').write_text(json.dumps(request))
    with pytest.raises(ValueError): api().run(task, tmp_path, destination)
    if mutation != 'output-alias': assert not destination.exists()


@pytest.mark.parametrize('program,kind', PROGRAM_LAYOUTS)
def test_adapter_fake_binary_and_exact_transport(tmp_path, program, kind):
    import json
    import subprocess
    import sys
    p = point(program); f = format_spec(program, kind)
    outputs = supplied_outputs(kind)
    if program == 'Prophecy4f':
        p['scalars'][0]['coverage'] = 'four_fermion'
        f['layout']['files'][0]['channels'][0]['daughters'] = [11, -11, 12, -12]
        f['layout']['files'][0]['channels'][1]['daughters'] = [13, -13, 14, -14]
    engine = api().adapter(program)
    card = engine.render_card(p, f)
    assert '${' not in card
    for field in f['card']['fields']: assert field + ' = ' in card
    (tmp_path / f['card']['filename']).write_text(card)
    fake = tmp_path / 'synthetic_binary.py'
    fake.write_text('from pathlib import Path\nimport json\n'
                    'payload = json.loads(' + repr(json.dumps(outputs)) + ')\n'
                    'for name, content in payload.items(): Path(name).write_text(content)\n')
    subprocess.run([sys.executable, '-B', str(fake)], cwd=tmp_path, check=True, timeout=5)
    result = engine.parse_outputs(p, f, {name: (tmp_path / name).read_text() for name in outputs})
    assert result['units'] == 'GeV' and result['layout_qualified'] is False
    assert {k: result[k] for k in ('program', 'version', 'order', 'ew_scheme')} == {
        k: p[k] for k in ('program', 'version', 'order', 'ew_scheme')}
    scalar = result['scalars'][0]
    assert scalar['total_width_GeV'] == 10.
    assert [c['partial_width_GeV'] for c in scalar['channels']] == [6., 4.]
    assert [c['branching_ratio'] for c in scalar['channels']] == [.6, .4]
    if program != 'Prophecy4f':
        slha = api().to_slha(result)
        decoded = engine.parse_outputs(p, format_spec(program, 'slha'), {'synthetic.slha': slha})
        assert decoded['scalars'] == result['scalars']


def test_comparison_applies_per_channel_tolerances_and_retains_failures():
    d = table(); scalar = d['scalars'][0]
    names = ['bb', 'tautau', 'mumu', 'cc', 'gammagamma', 'Zgamma', 'gg', 'WW', 'ZZ']
    scalar['channels'] = [{'id': name, 'daughters': [n, -n], 'partial_width_GeV': 1.,
                           'branching_ratio': .1, 'program': 'HDECAY'}
                          for n, name in enumerate(names, 1)]
    scalar['total_width_GeV'] = 9.
    for c in scalar['channels']: c['branching_ratio'] = 1. / 9.
    rows = [{'id': f'ANA-000{n}', 'channel': name, 'mass_GeV': 160.,
             'quantity': 'branching_ratio', 'unit': '1', 'value': 1. / 9.,
             'citation': 'synthetic://reference'} for n, name in enumerate(names)]
    rows.append({'id': 'ANA-0010', 'channel': 'Gamma_H', 'mass_GeV': 160., 'quantity': 'total_width',
                 'unit': 'GeV', 'value': 9., 'citation': 'synthetic://reference'})
    record = api().compare_reference(d, rows, pdg=25, required_channels=names + ['Gamma_H'])
    assert record['passed'] and len(record['channels']) == 10
    assert {r['channel']: r['relative_tolerance'] for r in record['channels']} == {
        **dict.fromkeys(names[:7], .015), **dict.fromkeys(['WW', 'ZZ', 'Gamma_H'], .03)}
    rows[0]['value'] /= 1.016
    rows[-1]['value'] /= 1.031
    record = api().compare_reference(d, rows, pdg=25)
    assert not record['passed']
    assert [r['channel'] for r in record['channels'] if not r['passed']] == ['bb', 'Gamma_H']


def test_comparison_consumes_version_one_reference_row_interface():
    rows = [{'id': 'ANA-0001', 'process': 'bb', 'mass_gev': 160., 'quantity': 'branching_ratio',
             'value': .6, 'unit': '1', 'citation_key': 'synthetic-source'}]
    result = api().compare_reference(table(), rows, pdg=25, required_channels=['bb'])
    assert result['passed'] and result['channels'][0]['citation'] == 'synthetic-source'


@pytest.mark.xfail(reason='awaits scope-tools FeynHiggs', strict=True)
def test_feynhiggs_scope_tools_interface():
    api().adapter('FeynHiggs').scope_tools_job()


@pytest.mark.parametrize('program,kind', PROGRAM_LAYOUTS[:-1])
@pytest.mark.xfail(reason='awaits pinned program manual and real output layout', strict=True)
def test_pinned_manual_layout_qualification(program, kind):
    import json
    import os
    from pathlib import Path
    # The supplied fixture directory is outside the exported source tree.
    directory = Path(os.environ['RAVEL_DECAY_LAYOUT_FIXTURES']) / program
    p = json.loads((directory / 'point.json').read_text())
    f = json.loads((directory / 'format.json').read_text())
    engine = api().adapter(program)
    result = engine.parse_outputs(p, f, {n: (directory / n).read_text() for n in engine.output_names(f)})
    assert result['scalars'] == json.loads((directory / 'expected.json').read_text())['scalars']


def test_source_bound_operation_writes_card_json_and_slha(tmp_path):
    import json
    task, request = request_fixture(tmp_path)
    files = api().inputs(task, tmp_path)
    assert tmp_path / 'source.txt' in files and tmp_path / 'br.sm1' in files
    result = api().run(task, tmp_path, tmp_path / 'delivery')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert result['decay_table']['format_provenance']['format'] == request['format']
    assert json.loads((tmp_path / 'delivery/result.json').read_text()) == result
    assert (tmp_path / 'delivery/synthetic.in').is_file()
    assert 'DECAY 25 10' in (tmp_path / 'delivery/widths.slha').read_text()


def test_preparation_emits_guarded_job_only_and_never_launches(tmp_path, monkeypatch):
    import subprocess
    task, _ = request_fixture(tmp_path, 'prepare')
    def forbidden(*args, **kwargs): raise AssertionError('native launch is forbidden during card preparation')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    result = api().run(task, tmp_path, tmp_path / 'delivery')
    job = result['native_job']
    assert job['launch_performed'] is False and job['max_seconds'] == 4.
    assert job['launch_interface'] == 'ravel.workflow.launch_authorization.authorized_popen'
    assert 'method-decision record' in job['requires'] and 'scientific admission' in job['requires']
    assert not (tmp_path / 'delivery/widths.slha').exists()


def test_changed_population_parameters_and_layout_need_no_product_edits():
    p = point(); f = format_spec()
    p['parameters']['mixing'] = .25
    p['scalars'].append({'pdg': 35, 'mass_GeV': 240., 'coverage': 'complete'})
    f['card']['fields']['scalars.35.mass_GeV'] = {'kind': 'number'}
    f['card']['template'] += 'other_mass = ${scalars.35.mass_GeV}\n'
    f['layout']['files'][0]['mass_column'] = 1
    f['layout']['files'][0]['channels'][0]['column'] = 0
    outputs = {'br.sm1': '# synthetic\n.6 160\n.2 240\n',
               'br.sm2': '# synthetic\n160 .4 10\n240 .8 20\n'}
    engine = api().adapter('HDECAY')
    assert '0.25' in engine.render_card(p, f)
    result = engine.parse_outputs(p, f, outputs)
    assert [s['total_width_GeV'] for s in result['scalars']] == [10., 20.]
    assert [c['partial_width_GeV'] for c in result['scalars'][1]['channels']] == [4., 16.]


def test_four_fermion_sector_rejects_two_body_channel_mapping():
    p = point('Prophecy4f'); p['scalars'][0]['coverage'] = 'four_fermion'
    with pytest.raises(ValueError, match='four'):
        api().adapter('Prophecy4f').parse_outputs(p, format_spec('Prophecy4f', 'key_values'),
                                               supplied_outputs('key_values'))


def test_order_metadata_must_match_the_supplied_format_convention():
    p = point(); p['order'] = 'different-synthetic-order'
    with pytest.raises(ValueError, match='order'):
        api().adapter('HDECAY').render_card(p, format_spec())


def test_native_expected_outputs_may_not_overwrite_the_rendered_card(tmp_path):
    import json
    task, request = request_fixture(tmp_path, 'prepare')
    spec = format_spec(); spec['card']['filename'] = 'br.sm1'
    (tmp_path / 'format.json').write_text(json.dumps(spec))
    request['format'] = pin(tmp_path / 'format.json')
    (tmp_path / 'request.json').write_text(json.dumps(request))
    with pytest.raises(ValueError): api().run(task, tmp_path, tmp_path / 'delivery')
    assert not (tmp_path / 'delivery').exists()


def test_width_sum_overflow_is_a_typed_refusal():
    d = table(); scalar = d['scalars'][0]; scalar['total_width_GeV'] = 1e308
    for c in scalar['channels']:
        c['partial_width_GeV'] = 9e307; c['branching_ratio'] = .9
    with pytest.raises(ValueError): api().validate_table(d)


def test_cli_transport_and_comparison_use_supplied_publication_names(tmp_path):
    import json
    task, request = request_fixture(tmp_path)
    request['publication'] = {'json': 'supplied-result.json', 'slha': 'supplied-widths.slha'}
    (tmp_path / 'request.json').write_text(json.dumps(request))
    assert api().main(['transport', '--request', task['request'], '--base', str(tmp_path),
                       '--output', str(tmp_path / 'delivery')]) == 0
    references = tmp_path / 'cited-rows.json'
    references.write_text(json.dumps([{'id': 'ANA-0001', 'channel': 'bb', 'mass_GeV': 160.,
                                      'quantity': 'branching_ratio', 'unit': '1', 'value': .6,
                                      'citation': 'synthetic://source'}]))
    output = tmp_path / 'agreement.json'
    args = ['compare', '--table', str(tmp_path / 'delivery/supplied-result.json'),
            '--reference-rows', str(references), '--pdg', '25', '--channels', 'bb', '--output', str(output)]
    assert api().main(args) == 0
    assert json.loads(output.read_text())['passed'] is True
    row = json.loads(references.read_text()); row[0]['value'] = .5
    references.write_text(json.dumps(row)); args[-1] = str(tmp_path / 'disagreement.json')
    assert api().main(args) == 1
    assert json.loads((tmp_path / 'disagreement.json').read_text())['passed'] is False


def test_program_metadata_matches_adapter_identities():
    import json
    from pathlib import Path
    registry = json.loads((Path(api().__file__).parents[1] / 'data/higgs/decay-programs.json').read_text())
    assert {row['program'] for row in registry['programs']} == {p for p, _ in PROGRAM_LAYOUTS}
    for row in registry['programs']:
        assert api().adapter(row['program']).model_families == tuple(row['model_families'])
        assert row['format_status'].startswith('awaits')


def test_output_dotdot_alias_refuses_before_overwriting_original_source(tmp_path):
    import json
    task, request = request_fixture(tmp_path)
    request['publication']['json'] = 'source.txt'
    (tmp_path / 'request.json').write_text(json.dumps(request))
    original = (tmp_path / 'source.txt').read_bytes()
    with pytest.raises(ValueError):
        api().run(task, tmp_path, tmp_path / 'uncreated' / '..')
    assert (tmp_path / 'source.txt').read_bytes() == original


def test_feynhiggs_preparation_cannot_bypass_scope_tools(tmp_path):
    import json
    task, request = request_fixture(tmp_path, 'prepare')
    (tmp_path / 'point.json').write_text(json.dumps(point('FeynHiggs')))
    (tmp_path / 'format.json').write_text(json.dumps(format_spec('FeynHiggs', 'slha')))
    request['point'] = pin(tmp_path / 'point.json'); request['format'] = pin(tmp_path / 'format.json')
    (tmp_path / 'request.json').write_text(json.dumps(request))
    with pytest.raises(ValueError, match='scope-tools'):
        api().run(task, tmp_path, tmp_path / 'delivery')
    assert not (tmp_path / 'delivery').exists()


def test_slha_reported_mass_mismatch_is_refused():
    outputs = supplied_outputs('slha')
    outputs['synthetic.slha'] = outputs['synthetic.slha'].replace('25 160', '25 170')
    with pytest.raises(ValueError, match='mass'):
        api().adapter('2HDMC').parse_outputs(point('2HDMC'), format_spec('2HDMC', 'slha'), outputs)


def test_native_quantity_is_transported_unchanged_and_the_other_is_derived():
    # .1 * 3 / 3 differs from .1 in binary arithmetic; the printed ratio must survive.
    outputs = {'br.sm1': '# synthetic\n160 .1\n', 'br.sm2': '# synthetic\n160 .9 3\n'}
    channels = api().adapter('HDECAY').parse_outputs(point(), format_spec(), outputs)['scalars'][0]['channels']
    assert [c['branching_ratio'] for c in channels] == [.1, .9]
    assert [c['partial_width_GeV'] for c in channels] == [.1 * 3., .9 * 3.]
    keyed = {'synthetic.out': 'mass = 160\nwidth = 3\nbb = .3\nWW = 2.7\n'}
    channels = api().adapter('HDECAY').parse_outputs(point(), format_spec(kind='key_values'),
                                                   keyed)['scalars'][0]['channels']
    assert [c['partial_width_GeV'] for c in channels] == [.3, 2.7]
    assert [c['branching_ratio'] for c in channels] == [.3 / 3., 2.7 / 3.]


@pytest.mark.parametrize('delta', [.000005, -.000005])
def test_partial_width_sum_inside_relative_tolerance_is_accepted(delta):
    d = table(); scalar = d['scalars'][0]
    scalar['total_width_GeV'] += delta
    for c in scalar['channels']:
        c['branching_ratio'] = c['partial_width_GeV'] / scalar['total_width_GeV']
    assert api().validate_table(d) == d


@pytest.mark.parametrize('document', ['point', 'row', 'channel'])
def test_malformed_documents_are_typed_refusals(tmp_path, document):
    import json
    if document == 'point':
        task, request = request_fixture(tmp_path)
        (tmp_path / 'point.json').write_text(json.dumps([point()]))
        request['point'] = pin(tmp_path / 'point.json')
        (tmp_path / 'request.json').write_text(json.dumps(request))
        with pytest.raises(ValueError): api().run(task, tmp_path, tmp_path / 'delivery')
        assert not (tmp_path / 'delivery').exists()
        return
    row = {'id': 'ANA-0001', 'channel': 'bb', 'quantity': 'branching_ratio',
           'mass_GeV': 160., 'value': .6, 'unit': '1', 'citation': 'synthetic://reference'}
    rows = ['bb'] if document == 'row' else [{**row, 'channel': ['bb']}]
    with pytest.raises(ValueError): api().compare_reference(table(), rows, pdg=25)
