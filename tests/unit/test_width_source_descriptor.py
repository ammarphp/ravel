"""Packaged published-table descriptor for the width-input producer.

Original use: the former producer interpreted one published release (four regional tables and two
limit tables). The synthetic release below has the same file names, axis and series headers,
qualifiers, window and mass populations; ``ORIGINAL_REFERENCE_SHA256`` is the digest of the
reference document the former implementation produced from exactly these bytes (path-normalized),
so equality here is equality with the original interpretation. No published byte is shipped.
Second use: a fictional release with other tables, energy and population through an inline
descriptor of the same closed shape, and the descriptor-free supplied package of
``test_width_inputs``.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ravel.physics import width_inputs as w, mass_width_grid, source_tables
from ravel.workflow import execution
from test_mass_width_grid import put, pin, policy, request_fixture
from test_width_inputs import task as make_task

NAME = 'dijet-photon-published-tables-v1'
SERIES = ['Data', 'Non-resonant background', '$\\gamma+W$', '$\\gamma+Z$', '$t\\bar{t}$',
          "$\\gamma + Z' (m_{Z'} = 20) GeV$", "$\\gamma + Z' (m_{Z'} = 40) GeV$",
          "$\\gamma + Z' (m_{Z'} = 125) GeV \\times 5$", 'Background estimate uncertainty']
REGION_FILES = ('SR.yaml', 'forward_CR.yaml', 'central_inverted_CR.yaml', 'forward_inverted_CR.yaml')
LIMIT_FILES = ('coupling.yaml', 'xsec.yaml')
# Production digest of the reference the former implementation built from release() below.
DOIS = w.load_descriptor(NAME)['expect']['table_doi']
ORIGINAL_REFERENCE_SHA256 = '48796ad6545090cb146d6748d7738005fd4d40e16221236ea9c7254477c1f889'


@pytest.fixture(autouse=True)
def inert_runtime(monkeypatch):
    monkeypatch.setattr(execution, 'runtime_context', lambda: {
        'synthetic_runtime': True, 'environment_sha256': execution.digest(execution.runtime_environment())})


def release():
    """Synthetic bytes with the published release's structure; every number is fabricated."""
    edges = [10 + 6 * i for i in range(43)] + [290]
    files = {}
    for index, name in enumerate(REGION_FILES):
        payload = {'independent_variables': [{'header': {'name': 'm_{J}', 'units': 'GeV'},
                                              'values': [{'low': edges[i], 'high': edges[i + 1]} for i in range(43)]}],
                   'dependent_variables': [{'header': {'name': s},
                                            'values': [{'value': round(0.37 * (i + 1) + k + index, 3)} for i in range(43)]}
                                           for k, s in enumerate(SERIES)]}
        files[name] = yaml.safe_dump(payload, sort_keys=False).encode()
    qualifiers = [{'name': 'SQRT(s)', 'units': 'GeV', 'value': 13000.0},
                  {'name': 'LUMINOSITY', 'units': 'fb$^{-1}$', 'value': 140}]
    for k, name in enumerate(LIMIT_FILES):
        payload = {'independent_variables': [{'header': {'name': "m_{Z'}", 'units': 'GeV'},
                                              'values': [{'value': 20 + 15 * i} for i in range(13)]}],
                   'dependent_variables': [{'header': {'name': n}, 'qualifiers': deepcopy(qualifiers),
                                            'values': [{'value': round(0.011 * (i + 1) * (k + 1) + j / 100, 4)} for i in range(13)]}
                                           for j, n in enumerate(('Observed', 'Expected'))]}
        files[name] = yaml.safe_dump(payload, sort_keys=False).encode()
    docs = [{'comment': 'fabricated release'}] + [
        {'data_file': name, 'table_doi': DOIS[name], 'description': 'fabricated'}
        for name in (*REGION_FILES, *LIMIT_FILES)]
    files['submission.yaml'] = yaml.safe_dump_all(docs, sort_keys=False).encode()
    return files


def write_release(directory):
    directory.mkdir(parents=True, exist_ok=True)
    files = release()
    for name, raw in files.items(): (directory / name).write_bytes(raw)
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}


def synthetic_descriptor(digests):
    d = w.load_descriptor(NAME); d['files'] = digests
    return d


def request(base, directory, descriptor, *, extra=None):
    p, req, law = request_fixture(base / 'study', missing=True)
    analysis = {'pdg': 32, 'generation': deepcopy(req['analysis']['generation'])}
    analysis['generation']['energy_gev'] = [6500, 6500]
    selection = {'descriptor': descriptor, 'directory': str(directory), 'analysis': analysis}
    output = {key: {'filename': 'EX-' + key + '.json', 'format': 'json'} for key in ('references', 'recipe', 'specification', 'receipt')}
    output['study'] = {'result': {'filename': 'EX-study.json', 'format': 'json'},
                       'report': {'filename': 'EX.md', 'format': 'markdown'}}
    document = {'schema_version': 2, 'goal_binding': req['goal_binding'], 'source_package': selection,
                'axes': [{'name': 'mass_GeV', 'values': [20 + 15 * i for i in range(13)]},
                         {'name': 'width_over_mass', 'values': [0.03, 0.3]}],
                'point_inputs': [], 'regional_input': None, 'native_runtime': None, 'native_fit': None,
                'review_policy': put(base / 'policy.json', policy()), 'child_seconds': 60,
                'assumptions': ['All values fabricated; references are never observations'], 'output': output}
    document.update(extra or {})
    return document


def normalized(reference):
    text = json.dumps(reference, sort_keys=True)
    for row in [r['source'] for r in reference['regions']] + [v['source'] for v in reference['limits'].values()]:
        text = text.replace(row['path'], Path(row['path']).name)
    return hashlib.sha256(text.encode()).hexdigest()


def test_packaged_descriptor_is_listed_closed_and_pins_published_bytes():
    assert NAME in w.descriptor_names()
    d = w.load_descriptor(NAME)
    assert len(d['files']) == 7 and set(d['files']) == {*REGION_FILES, *LIMIT_FILES, 'submission.yaml'}
    assert d['analysis']['region_ids'] == ['central_tagged', 'forward_tagged', 'central_antitagged', 'forward_antitagged']
    assert [t['file'] for t in d['tables']] == [*REGION_FILES, *LIMIT_FILES]
    assert [t['id'] for t in d['tables']][4:] == ['g_q', 'sigma_times_BR_qq_times_acceptance']
    assert all(len(t['columns']) == 9 for t in d['tables'][:4]) and all(len(t['columns']) == 2 for t in d['tables'][4:])
    for bad in ('nope', '../' + NAME, 'A'):
        with pytest.raises(ValueError):
            w.load_descriptor(bad)


def test_original_interpretation_of_the_published_tables_is_reproduced(tmp_path):
    digests = write_release(tmp_path / 'release')
    descriptor = synthetic_descriptor(digests)
    package, expect = w.descriptor_package({'descriptor': descriptor, 'directory': str(tmp_path / 'release'),
                                            'analysis': {'pdg': 32, 'generation': {}}}, tmp_path)
    pins = {n: {'path': v['path'], 'sha256': v['sha256'], 'size': len((tmp_path / 'release' / n).read_bytes())}
            for n, v in package['sources'].items()}
    payloads = {n: (tmp_path / 'release' / n).read_bytes() for n in pins}
    reference = w.parse_package(package, payloads, pins)
    w.check_expectations(expect, reference)
    assert [r['id'] for r in reference['regions']] == ['central_tagged', 'forward_tagged', 'central_antitagged', 'forward_antitagged']
    assert list(reference['limits']) == ['g_q', 'sigma_times_BR_qq_times_acceptance']
    assert reference['region_bin_denominator'] == 172 and reference['region_series_value_denominator'] == 1548
    assert reference['limit_value_denominator'] == 52 and reference['windows_GeV'][0] == ['10', '16'] and reference['windows_GeV'][-1] == ['262', '290']
    assert reference['limits']['g_q']['mass_GeV'] == [20 + 15 * i for i in range(13)]
    assert reference['limits']['g_q']['unit'] == 'dimensionless'
    assert reference['observations_reconstructed'] is False and reference['coupling_to_width_or_rate_map'] is None
    assert normalized(reference) == ORIGINAL_REFERENCE_SHA256


def test_packaged_descriptor_refuses_bytes_other_than_the_published_release(tmp_path):
    write_release(tmp_path / 'release')
    document = request(tmp_path, tmp_path / 'release', NAME)
    with pytest.raises(ValueError):
        w.run(make_task(tmp_path, document), tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_descriptor_selection_runs_end_to_end_and_matches_the_package_route(tmp_path):
    digests = write_release(tmp_path / 'release')
    document = request(tmp_path, tmp_path / 'release', synthetic_descriptor(digests))
    result = w.run(make_task(tmp_path, document), tmp_path, tmp_path / 'out')
    reference = json.loads(Path(result['references']['path']).read_bytes())
    assert result['cell_denominator'] == 26 and result['mass_denominator'] == 13
    assert result['region_bin_denominator'] == 172 and result['limit_value_denominator'] == 52
    assert normalized(reference) == ORIGINAL_REFERENCE_SHA256
    recipe = json.loads(Path(result['recipe']['path']).read_bytes())
    assert recipe['analysis']['id'] == w.load_descriptor(NAME)['analysis']['id'] and recipe['analysis']['pdg'] == 32
    assert recipe['analysis']['observable'] == 'TAR_mJ_GeV' and recipe['analysis']['energy_tev'] == 13
    # the same tables through an explicit supplied package give the same reference
    package, _ = w.descriptor_package(document['source_package'], tmp_path)
    explicit = deepcopy(document)
    explicit['source_package'] = put(tmp_path / 'package.json', {
        **package, 'sources': {n: {'path': Path(v['path']).name, 'sha256': v['sha256']} for n, v in package['sources'].items()}})
    (tmp_path / 'package-dir').mkdir()
    for name in package['sources']: (tmp_path / 'package-dir' / name).write_bytes((tmp_path / 'release' / name).read_bytes())
    explicit['source_package'] = put(tmp_path / 'package-dir' / 'package.json', {
        **package, 'sources': {n: {'path': n, 'sha256': v['sha256']} for n, v in package['sources'].items()}})
    again = w.run(make_task(tmp_path, explicit), tmp_path, tmp_path / 'out-explicit')
    assert normalized(json.loads(Path(again['references']['path']).read_bytes())) == ORIGINAL_REFERENCE_SHA256


@pytest.mark.parametrize('fault', ['doi', 'window_count', 'mass_count', 'qualifier', 'request_field'])
def test_published_record_facts_beyond_the_digests_are_enforced(tmp_path, fault):
    files = release()
    if fault == 'doi':
        docs = list(yaml.safe_load_all(files['submission.yaml']))
        docs[1]['table_doi'] = DOIS['SR.yaml'] + '9'
        files['submission.yaml'] = yaml.safe_dump_all(docs, sort_keys=False).encode()
    elif fault == 'window_count':
        t = yaml.safe_load(files['SR.yaml']); t['independent_variables'][0]['values'].pop()
        for c in t['dependent_variables']: c['values'].pop()
        files['SR.yaml'] = yaml.safe_dump(t, sort_keys=False).encode()
    elif fault == 'mass_count':
        t = yaml.safe_load(files['coupling.yaml']); t['independent_variables'][0]['values'].pop()
        for c in t['dependent_variables']: c['values'].pop()
        files['coupling.yaml'] = yaml.safe_dump(t, sort_keys=False).encode()
    elif fault == 'qualifier':
        t = yaml.safe_load(files['xsec.yaml']); t['dependent_variables'][0]['qualifiers'][1]['value'] = 139
        files['xsec.yaml'] = yaml.safe_dump(t, sort_keys=False).encode()
    release_dir = tmp_path / 'release'; release_dir.mkdir()
    for name, raw in files.items(): (release_dir / name).write_bytes(raw)
    digests = {n: hashlib.sha256(r).hexdigest() for n, r in files.items()}
    analysis = {'pdg': 32, 'generation': {}} if fault != 'request_field' else {'pdg': 32}
    with pytest.raises(ValueError):
        package, expect = w.descriptor_package({'descriptor': synthetic_descriptor(digests), 'directory': str(release_dir),
                                                'analysis': analysis}, tmp_path)
        pins = {n: {'path': v['path'], 'sha256': v['sha256'], 'size': len(files[n])} for n, v in package['sources'].items()}
        w.check_expectations(expect, w.parse_package(package, files, pins))


# ---- second, unrelated use ------------------------------------------------------------------------

def other_release():
    """Another publication: one region, two limit samples, another energy; no shared populations."""
    files = {}
    t = {'independent_variables': [{'header': {'name': 'm_{jj}', 'units': 'TeV'}, 'values': [{'low': 1 + i / 2, 'high': 1.5 + i / 2} for i in range(5)]}],
         'dependent_variables': [{'header': {'name': n}, 'values': [{'value': 0.5 + i + k / 10} for i in range(5)]}
                                 for k, n in enumerate(('observed', 'background'))]}
    files['dijet.yaml'] = yaml.safe_dump(t, sort_keys=False).encode()
    t = {'independent_variables': [{'header': {'name': 'M_{res}', 'units': 'TeV'}, 'values': [{'value': 1.5}, {'value': 2.0}, {'value': 2.5}]}],
         'dependent_variables': [{'header': {'name': n}, 'qualifiers': [{'name': 'SQRT(s)', 'units': 'TeV', 'value': 8}],
                                  'values': [{'value': 0.1 * (i + 1) + k} for i in range(3)]} for k, n in enumerate(('obs', 'exp'))]}
    files['limit.yaml'] = yaml.safe_dump(t, sort_keys=False).encode()
    files['index.yaml'] = yaml.safe_dump_all([{'comment': 'other'}, {'data_file': 'dijet.yaml', 'table_doi': 'x/t1'},
                                              {'data_file': 'limit.yaml', 'table_doi': 'x/t2'}], sort_keys=False).encode()
    return files


def test_second_use_inline_descriptor_with_other_tables_energy_and_units(tmp_path):
    files = other_release(); release_dir = tmp_path / 'other'; release_dir.mkdir()
    for name, raw in files.items(): (release_dir / name).write_bytes(raw)
    descriptor = {'schema_version': 1, 'kind': 'width-source-descriptor', 'name': 'fictional-dijet',
        'source': 'Fictional published tables for the second-use control', 'files': {n: hashlib.sha256(r).hexdigest() for n, r in files.items()},
        'submission': 'index.yaml',
        'tables': [{'id': 'bin', 'file': 'dijet.yaml', 'role': 'region', 'axis_header': {'name': 'm_{jj}', 'units': 'TeV'},
                    'columns': [{'header': {'name': 'observed'}, 'qualifiers': []}, {'header': {'name': 'background'}, 'qualifiers': []}],
                    'quantity': None, 'unit': None, 'applicability': None},
                   {'id': 'limit', 'file': 'limit.yaml', 'role': 'limit', 'axis_header': {'name': 'M_{res}', 'units': 'TeV'},
                    'columns': [{'header': {'name': 'obs'}, 'qualifiers': [{'name': 'SQRT(s)', 'units': 'TeV', 'value': 8}]},
                                {'header': {'name': 'exp'}, 'qualifiers': [{'name': 'SQRT(s)', 'units': 'TeV', 'value': 8}]}],
                    'quantity': 'rate_limit', 'unit': 'unreported_in_table_headers', 'applicability': 'fictional decay definition; no projection'}],
        'reference_metadata': {'schema_version': 1, 'kind': 'fictional_references', 'energy_tev': 8, 'lumi_fb': 20,
            'uncertainty_law': 'unknown', 'source_discrepancies': [], 'observations_reconstructed': False,
            'coupling_to_width_or_rate_map': None, 'source_origin_scope': 'fabricated bytes'},
        'analysis': {'id': 'FICTIONAL-DIJET', 'energy_tev': 8, 'lumi_fb': 20, 'observable': 'dijet_mass_TeV',
                     'region_ids': ['bin'], 'missing': ['law absent']},
        'analysis_inputs': ['pdg', 'generation'],
        'expect': {'table_doi': {'dijet.yaml': 'x/t1', 'limit.yaml': 'x/t2'},
                   'region_windows': {'count': 5, 'first_low': '1', 'last_high': '7/2'},
                   'limit_masses': {'count': 3, 'first': 1.5, 'last': 2.5}}}
    d = w.load_descriptor(descriptor)
    package, expect = w.descriptor_package({'descriptor': d, 'directory': str(release_dir),
                                            'analysis': {'pdg': 5000001, 'generation': {}}}, tmp_path)
    pins = {n: {'path': v['path'], 'sha256': v['sha256'], 'size': len(files[n])} for n, v in package['sources'].items()}
    reference = w.parse_package(package, files, pins)
    w.check_expectations(expect, reference)
    assert reference['windows_GeV'][0] == ['1', '3/2'] and list(reference['limits']) == ['rate_limit']
    assert reference['region_bin_denominator'] == 5 and reference['limit_value_denominator'] == 6
    assert reference['energy_tev'] == 8 and reference['limits']['rate_limit']['mass_GeV'] == [1.5, 2.0, 2.5]
    # a descriptor that omits a listed table or file refuses rather than dropping it
    short = deepcopy(descriptor); short['tables'].pop()
    package, expect = w.descriptor_package({'descriptor': short, 'directory': str(release_dir),
                                            'analysis': {'pdg': 5000001, 'generation': {}}}, tmp_path)
    with pytest.raises(ValueError, match='no unused'):
        w.parse_package(package, files, pins)
