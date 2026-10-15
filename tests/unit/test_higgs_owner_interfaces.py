"""The scalar review checks' owner interfaces: typed status records over the existing comparisons."""
import copy
import json
from pathlib import Path

from ravel.physics import higgs_likelihood, higgs_parameterization
from ravel.validation import higgs_checks

ROOT = Path(__file__).parents[2]
SHA = 'a' * 64


def bundle():
    return json.loads((ROOT / 'tests/fixtures/higgs/parameterization.json').read_text())


def test_closure_interface_passes_the_supplied_held_out_points():
    report = higgs_parameterization.check_parameterization_closure(bundle())
    assert report['status'] == 'passed' and report['findings'] == [] and report['points']
    assert higgs_checks.run_check(bundle(), check_id='check:higgs.parameterization_closure')['status'] == 'passed'


def test_failed_closure_is_a_material_finding_through_the_delegation():
    doc = bundle()
    doc['closure']['points'][0]['values'] = [50.0, 50.0]
    report = higgs_parameterization.check_parameterization_closure(doc)
    assert report['status'] == 'failed' and report['findings'][0]['materiality'] == 'A'
    assert higgs_checks.run_check(doc, check_id='check:higgs.parameterization_closure')['status'] == 'failed'


def test_closure_without_points_or_with_an_invalid_bundle_is_inconclusive():
    doc = bundle()
    del doc['closure']
    assert higgs_parameterization.check_parameterization_closure(doc)['status'] == 'inconclusive'
    broken = bundle()
    del broken['parameters']
    assert higgs_parameterization.check_parameterization_closure(broken)['status'] == 'inconclusive'


def engines(primary=2.0, independent=2.5):
    signals = {'operation': 'higgs-signals', 'comparison_input_sha256': SHA, 'status': 'passed',
               'delta_chi2': primary, 'measurements': [{'id': 'm1'}, {'id': 'm2'}], 'datasets': ['synthetic']}
    likelihood = {'operation': 'higgs-lilith', 'comparison_input_sha256': SHA, 'status': 'passed',
                  'delta_chi2': independent, 'database': {'measurement_ids': ['m2', 'm3']}}
    return {'signals': signals, 'likelihood': likelihood}


def test_cross_engine_agreement_within_the_declared_tolerance_passes():
    report = higgs_likelihood.check_cross_engine(engines())
    assert report['status'] == 'passed' and report['findings'] == []
    assert report['comparison']['only_higgs_signals'] == ['m1'] and report['comparison']['only_lilith'] == ['m3']
    assert higgs_checks.run_check(engines(), check_id='check:higgs.cross_engine')['status'] == 'passed'


def test_cross_engine_disagreement_is_a_material_finding():
    doc = engines(primary=2.0, independent=9.0)
    report = higgs_likelihood.check_cross_engine(doc)
    assert report['status'] == 'failed' and report['findings'][0]['materiality'] == 'B'
    assert higgs_checks.run_check(doc, check_id='check:higgs.cross_engine')['status'] == 'failed'


def test_cross_engine_needs_one_comparison_input_and_passed_engines():
    other = engines()
    other['likelihood']['comparison_input_sha256'] = 'b' * 64
    failed = engines()
    failed['signals']['status'] = 'failed'
    swapped = copy.deepcopy(engines())
    swapped['signals']['operation'] = 'higgs-lilith'
    for doc in (other, failed, swapped, {'signals': {}}, []):
        assert higgs_likelihood.check_cross_engine(doc)['status'] == 'inconclusive'
