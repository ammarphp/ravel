"""Fictional supplied table packages; no downloaded inputs or native calls."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ravel.physics import width_inputs as w, mass_width_grid, source_tables
from ravel.physics.supplied_contracts import MissingInputError
from ravel.workflow import science, execution
from test_mass_width_grid import put, pin, policy, request_fixture, response_fixture, law_fixture


@pytest.fixture(autouse=True)
def inert_runtime(monkeypatch):
    monkeypatch.setattr(execution, 'runtime_context', lambda: {
        'synthetic_runtime': True, 'environment_sha256': execution.digest(execution.runtime_environment())})


def fixture(base, variant=False):
    p, request, law = request_fixture(base/'study', missing=True)
    n = 3 if variant else 2
    identity = 'ANA-0002' if variant else 'ANA-0001'
    region_ids = ['zone'+str(i) for i in range(6 if variant else 4)]
    files = {}; tables = []; submission = [{'comment': 'Entirely fictional source package'}]
    for index, rid in enumerate(region_ids):
        filename = 'distribution-'+str(index)+'.yaml'
        payload = {'independent_variables': [{'header': {'name': 'fictional_mass', 'units': 'GeV'},
                    'values': [{'low': 1+i, 'high': 2+i} for i in range(n)]}],
                   'dependent_variables': [{'header': {'name': name}, 'values': [{'value': i+.125} for i in range(n)]}
                                          for name in ('samples', 'background') ]}
        files[filename] = put(base/filename, yaml.safe_dump(payload, sort_keys=False))
        tables.append({'id': rid, 'file': filename, 'role': 'region', 'axis_header': payload['independent_variables'][0]['header'],
                       'columns': [{'header': c['header'], 'qualifiers': []} for c in payload['dependent_variables']],
                       'quantity': None, 'unit': None, 'applicability': None})
        submission.append({'data_file': filename, 'description': 'Fictional noninteger postfit samples; reference only'})
    filename = 'bounds.yaml'
    payload = {'independent_variables': [{'header': {'name': 'hypothesis_mass', 'units': 'GeV'},
                'values': [{'value': m} for m in ([17, 47, 311] if variant else [23, 71])]}],
               'dependent_variables': [{'header': {'name': name}, 'values': [{'value': i+.25} for i in range(n)]}
                                      for name in ('observed_bound', 'expected_bound')]}
    files[filename] = put(base/filename, yaml.safe_dump(payload, sort_keys=False))
    tables.append({'id': 'limit', 'file': filename, 'role': 'limit', 'axis_header': payload['independent_variables'][0]['header'],
                   'columns': [{'header': c['header'], 'qualifiers': []} for c in payload['dependent_variables']],
                   'quantity': 'rate_times_branching_acceptance', 'unit': 'unreported_in_table_headers',
                   'applicability': 'Supplied fictional decay/acceptance definition; no projection'})
    submission.append({'data_file': filename, 'description': 'Fictional reference pair'})
    files['index.yaml'] = put(base/'index.yaml', yaml.safe_dump_all(submission, sort_keys=False))
    analysis = deepcopy(request['analysis']); analysis.update(id=identity, region_ids=region_ids)
    if variant:
        analysis.update(energy_tev=9, lumi_fb=31, observable='other_mass_GeV')
        analysis['generation']['energy_gev'] = [4500, 4500]
    metadata = {'schema_version': 1, 'kind': identity+'_supplied_references', 'energy_tev': analysis['energy_tev'], 'lumi_fb': analysis['lumi_fb'],
                'uncertainty_law': 'unknown; marginal samples do not supply a joint auxiliary law',
                'source_discrepancies': ['Displayed sample scale remains supplied source metadata'], 'observations_reconstructed': False,
                'coupling_to_width_or_rate_map': None, 'source_origin_scope': 'Complete supplied fictional source bytes'}
    package = {'schema_version': 1, 'sources': files, 'submission': 'index.yaml', 'tables': tables,
               'reference_metadata': metadata, 'analysis': analysis}
    axes = [{'name': 'mass_GeV', 'values': [17, 47, 311] if variant else [23, 71]},
            {'name': 'width_over_mass', 'values': [.017, .12, .47] if variant else [.03, .21]}]
    fmt = 'json-compact' if variant else 'json'
    output = {key: {'filename': identity+'-'+key+'.json', 'format': fmt} for key in ('references','recipe','specification','receipt')}
    output['study'] = {'result': {'filename': identity+'-study.json', 'format': fmt},
                       'report': {'filename': identity+('.csv' if variant else '.md'), 'format': 'csv' if variant else 'markdown'}}
    document = {'schema_version': 2, 'goal_binding': request['goal_binding'], 'source_package': put(base/'package.json', package),
                'axes': axes, 'point_inputs': [], 'regional_input': None, 'native_runtime': None, 'native_fit': None,
                'review_policy': put(base/'policy.json', policy()), 'child_seconds': 60,
                'assumptions': ['All values are fictional; references are never observations'], 'output': output}
    return document, package


def task(base, document):
    p = put(base/'producer.json', document)
    return {k: p[v] for k, v in (('input','path'), ('input_sha256','sha256'))}


def parsed(package):
    pins = package['sources']
    return w.parse_package(package, {k: Path(v['path']).read_bytes() for k,v in pins.items()}, pins)


def test_two_packages_change_identity_grid_population_and_output_without_code_edit(tmp_path):
    for variant in (False, True):
        base = tmp_path/str(variant); document, package = fixture(base, variant)
        result = w.run(task(base, document), base, base/'out')
        reference = json.loads(Path(result['references']['path']).read_bytes())
        recipe = json.loads(Path(result['recipe']['path']).read_bytes())
        assert recipe['analysis']['id'] == package['analysis']['id'] and recipe['axes'] == document['axes']
        assert result['cell_denominator'] == (9 if variant else 4)
        assert reference['region_bin_denominator'] == (18 if variant else 8)
        assert reference['limit_value_denominator'] == (6 if variant else 4)
        assert reference['limits']['rate_times_branching_acceptance']['unit'] == 'unreported_in_table_headers'
        assert all(r['statistical_role'] == 'published_postfit_plot_reference_only' for r in reference['regions'])
        spec = json.loads(Path(result['specification']['path']).read_bytes())
        assert science.adapter(spec) is mass_width_grid
        built = mass_width_grid.run(spec['task'], base/'out', base/'built')
        assert len(built['cells']) == result['cell_denominator'] and all(c['state']=='blocked' for c in built['cells'])
        tables = mass_width_grid.write_report(built, base/'built')
        assert tables[0]['files'] == [document['output']['study']['report']['filename']]
        raw = Path(result['references']['path']).read_bytes()
        assert (b'\n  "' not in raw) if variant else (b'\n  "' in raw)


def test_missing_source_package_has_typed_reason(tmp_path):
    document, _ = fixture(tmp_path); document.pop('source_package')
    with pytest.raises(MissingInputError) as error: w.inputs(task(tmp_path, document), tmp_path)
    assert error.value.reason == 'missing-input' and error.value.field == 'source_package'


def test_source_numeric_tokens_and_no_rounding_or_auxiliary_inference(tmp_path):
    _, package = fixture(tmp_path); reference = parsed(package)
    sample = reference['regions'][0]['payload']['dependent_variables'][0]['values'][0]['value']
    assert sample['literal'] == '0.125' and Fraction(reference['regions'][0]['series_exact']['samples'][0]) == Fraction(1,8)
    assert not reference['observations_reconstructed'] and reference['coupling_to_width_or_rate_map'] is None
    assert 'unknown' in reference['uncertainty_law'] and reference['source_discrepancies'] == package['reference_metadata']['source_discrepancies']


@pytest.mark.parametrize('fault', ['source', 'mapping', 'qualifier', 'window', 'extra', 'counts', 'projection'])
def test_supplied_package_custody_mapping_and_reference_safeguards(tmp_path, fault):
    document, package = fixture(tmp_path)
    if fault=='source': Path(package['sources']['bounds.yaml']['path']).write_text('changed')
    elif fault=='mapping': package['tables'].pop()
    elif fault=='qualifier': package['tables'][0]['columns'][0]['qualifiers']=[{'name':'unknown'}]
    elif fault=='window': package['tables'][0]['axis_header']['units']='unknown'
    elif fault=='extra': package['sources']['extra.yaml']=put(tmp_path/'extra.yaml','a: 1')
    elif fault=='counts': package['reference_metadata']['observations_reconstructed']=True
    else: package['reference_metadata']['coupling_to_width_or_rate_map']={'invented':True}
    document['source_package']=put(tmp_path/'package.json',package)
    with pytest.raises(ValueError): w.run(task(tmp_path,document),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('fault', ['foreign', 'duplicate', 'review', 'runtime', 'grid', 'output'])
def test_incomplete_foreign_duplicate_domain_refusals_before_output(tmp_path, fault):
    document, _ = fixture(tmp_path)
    cell={'coordinate':{'mass_GeV':23,'width_over_mass':.03},'response':None,'generation_request':None,'missing':[]}
    if fault=='foreign': cell['coordinate']['mass_GeV']=99; document['point_inputs']=[cell]
    elif fault=='duplicate': document['point_inputs']=[cell,cell]
    elif fault=='review': document['review_policy']=None
    elif fault=='runtime': document['native_runtime']=document['review_policy']
    elif fault=='grid': document['axes'][1]['values']=[True]
    else: document['output']['receipt']['filename']='../escape'
    with pytest.raises(ValueError): w.run(task(tmp_path,document),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_source_mutation_after_materialization_never_becomes_success(tmp_path, monkeypatch):
    document, package=fixture(tmp_path); original=mass_width_grid._emit_result
    def mutate(out,value,contract,capture):
        result=original(out,value,contract,capture)
        if contract==document['output']['specification']: Path(package['sources']['bounds.yaml']['path']).write_text('changed')
        return result
    monkeypatch.setattr(mass_width_grid,'_emit_result',mutate)
    with pytest.raises(ValueError): w.run(task(tmp_path,document),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out'/document['output']['receipt']['filename']).exists()


def test_parent_scope_and_ordinary_admission_remain_required(tmp_path):
    document, _=fixture(tmp_path); t=task(tmp_path,document)
    with pytest.raises(ValueError,match='original width question'): w.goal_inputs({'schema_version':2,'task':t,'goal_binding':None},tmp_path)
    spec={'schema_version':2,'mode':'width-inputs','source':'Supplied fictional source package','assumptions':document['assumptions'],
          'max_seconds':60,'approval_mode':'physicist','max_attempts':1,'goal_binding':document['goal_binding'],'review_policy':policy(),'task':t}
    rd=tmp_path/'ordinary'
    plan=science.plan(rd,put(tmp_path/'spec.json',spec)['path'])
    assert plan['mode']=='width-inputs' and science.verify_plan(rd,approved=False)['mode']=='width-inputs'
    with pytest.raises((ValueError,FileNotFoundError)): science.verify_plan(rd,approved=True)
    assert not (rd/'execution_state.json').exists()
