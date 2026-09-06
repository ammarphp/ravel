"""Scientific reporting must keep denominators and reject contradictory evidence."""
import copy
import importlib.util
import json
import shutil
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from validation_summary import load_baseline, summarize
from gen_validation_pages import render
import claims_check


def test_historical_scopes_and_failures_remain_visible():
    cases, results, _ = load_baseline()
    summary = summarize(cases, results)
    assert summary['registry_cases'] == 9
    assert summary['statistical_layer']['eligible_comparisons'] == 7
    assert summary['statistical_layer']['reference_unavailable'] == 2
    assert summary['acceptance_layer']['verdict_counts'] == {'PASS': 4, 'WARN': 1, 'FAIL': 1}
    pages, _ = render()
    assert set(pages) == {'README.md'} | {'cases/' + c['case_id'].replace('_', '-') + '.md' for c in cases}
    assert 'Certification verdict: FAIL' in pages['cases/ins2182381-gbb-1900-1.md']
    assert 'unscorable' in pages['cases/ins1676551-c1n2-300-100.md']


@pytest.mark.parametrize('mutation', ['remove_worst', 'perfect_ratios', 'nonfinite', 'zero', 'bool'])
def test_missing_or_contradictory_s95_cannot_improve_headline(mutation):
    cases, results, _ = load_baseline()
    results = copy.deepcopy(results)
    lim = results['conf2016054_gluino_onestep_1500_60']['metrics']['limit']
    if mutation == 'remove_worst':
        lim.pop('s95_ratio_obs')
    elif mutation == 'perfect_ratios':
        lim['s95_ratio_obs'] = 1.0
    elif mutation == 'nonfinite':
        lim['s95_obs'] = float('nan')
    elif mutation == 'zero':
        lim['s95_obs'] = 0
    else:
        lim['s95_ratio_obs'] = True
    with pytest.raises(ValueError):
        summarize(cases, results)


def test_missing_registry_case_is_not_silently_omitted(tmp_path):
    target = tmp_path / 'benchmarks'
    target.mkdir(parents=True)
    for name in ('cases.json', 'results.json'):
        doc = json.loads((REPO / 'benchmarks' / name).read_text())
        if name == 'results.json':
            doc['cases'].pop()
        (target / name).write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='registry/baseline mismatch'):
        render(tmp_path)


def test_validation_page_freshness_is_a_real_readonly_gate():
    result = subprocess.run([sys.executable, str(REPO / 'scripts/gen_validation_pages.py'), '--check'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_claims_gate_reads_results_and_rejects_removed_or_doctored_markers(tmp_path):
    assert claims_check.PUBLIC_RESULTS == 'docs/validation/results.md'
    page = tmp_path / 'results.md'
    manifest = tmp_path / 'claims.json'
    manifest.write_text(json.dumps({'claims': [
        {'claim': 'example', 'status': 'VERIFIED', 'value': '42', 'artifacts': []}]}))
    page.write_text('<!-- claim:example -->42<!-- /claim -->')
    assert claims_check.check(page, manifest, tmp_path)[0] == []
    page.write_text('An onboarding README without quantitative claims.')
    assert any('not cited' in m for m in claims_check.check(page, manifest, tmp_path)[0])
    page.write_text('<!-- claim:example -->9000<!-- /claim -->')
    assert any('drift' in m for m in claims_check.check(page, manifest, tmp_path)[0])


def test_private_history_exemption_never_applies_to_a_published_claim(tmp_path):
    page, manifest = tmp_path / 'results.md', tmp_path / 'claims.json'
    page.write_text('')
    entry = {'claim': 'example', 'status': 'HISTORICAL', 'value': '42',
             'artifacts': ['trial-runs/private-archive/RESULT.md']}
    manifest.write_text(json.dumps({'claims': [entry]}))
    fails, warnings = claims_check.check(page, manifest, tmp_path)
    assert not fails and warnings
    entry['status'] = 'VERIFIED'
    manifest.write_text(json.dumps({'claims': [entry]}))
    page.write_text('<!-- claim:example -->42<!-- /claim -->')
    assert any('artifact missing' in m for m in claims_check.check(page, manifest, tmp_path)[0])


def test_readme_subset_claims_are_checked_without_requiring_every_claim(tmp_path):
    page, manifest = tmp_path / 'README.md', tmp_path / 'claims.json'
    manifest.write_text(json.dumps({'claims': [
        {'claim': 'one', 'status': 'VERIFIED', 'value': '1', 'artifacts': []},
        {'claim': 'two', 'status': 'VERIFIED', 'value': '2', 'artifacts': []}]}))
    page.write_text('<!-- claim:one -->1<!-- /claim -->')
    assert claims_check.check(page, manifest, tmp_path, require_all=False)[0] == []
    page.write_text('<!-- claim:one -->100<!-- /claim -->')
    assert any('drift' in m for m in claims_check.check(page, manifest, tmp_path, require_all=False)[0])


@pytest.mark.parametrize('altered', [
    '1.00 fb observed and 54.69 fb median expected at 150/140 GeV',
    '48.83 fb observed and 1.00 fb median expected at 150/140 GeV',
    '48.83 fb observed and 54.69 fb median expected at 200/150 GeV',
])
def test_agreeing_public_text_cannot_override_rrr_point_evidence(tmp_path, altered):
    # A coordinated edit of both public strings still needs the measured point.
    source = tmp_path / 'evidence/audits/2026-09-06-rrr-waypoint/waypoint.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        'reference_point': {'m_parent_GeV': 150., 'm_lsp_GeV': 140.},
        'results': {'anchor20k': {
            'conditional_observed_sigma95_fb': 48.82546569866808,
            'conditional_median_expected_sigma95_fb': 54.68574261326738,
        }},
    }))
    page, manifest = tmp_path / 'README.md', tmp_path / 'claims.json'
    entry = {'claim': 'rrr_anchor_limits', 'status': 'VERIFIED',
             'value': '48.83 fb observed and 54.69 fb median expected at 150/140 GeV',
             'artifacts': [str(source.relative_to(tmp_path))]}
    def write_claim():
        page.write_text(f'<!-- claim:rrr_anchor_limits -->{entry["value"]}<!-- /claim -->')
        manifest.write_text(json.dumps({'claims': [entry]}))
    write_claim()
    assert claims_check.check(page, manifest, tmp_path)[0] == []
    entry['value'] = altered
    write_claim()
    assert any('RRR waypoint scope/value drift' in error
               for error in claims_check.check(page, manifest, tmp_path)[0])


@pytest.mark.parametrize('claim,altered', [
    ('rrr_pool_limits', '46.63 fb observed and 56.53 fb median expected from the 60,000-event pool at 150/140 GeV'),
    ('rrr_pool_limits', '47.37 fb observed and 57.27 fb median expected from the 80,000-event pool at 150/140 GeV'),
    ('rrr_cut_rate_ratio', 'a high-region rate ratio of 1.000 (conditional 95% interval 0.990–1.010)'),
    ('rrr_cut_rate_ratio', 'a high-region rate ratio of 1.412 (conditional 95% interval 1.146–1.500)'),
    ('rrr_fresh100_limits', '238.13 fb observed and 203.96 fb median expected at 100/98 GeV'),
    ('rrr_fresh100_limits', '210.00 fb observed and 169.09 fb median expected at 150/140 GeV'),
])
def test_coordinated_control_headlines_still_need_measured_evidence(tmp_path, claim, altered):
    bundle = '2026-09-06-rrr-event-identity' if claim == 'rrr_fresh100_limits' else '2026-09-06-rrr-cut-dependence'
    relative = Path('evidence/audits') / bundle / 'data/evidence.json'
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_bytes((REPO / relative).read_bytes())
    entry = next(item for item in json.loads((REPO / 'evidence/claims.json').read_text())['claims']
                 if item['claim'] == claim)
    entry['artifacts'] = [str(relative)]
    page, manifest = tmp_path / 'README.md', tmp_path / 'claims.json'
    def write_claim():
        page.write_text(f'<!-- claim:{claim} -->{entry["value"]}<!-- /claim -->')
        manifest.write_text(json.dumps({'claims': [entry]}))
    write_claim()
    assert claims_check.check(page, manifest, tmp_path)[0] == []
    entry['value'] = altered
    write_claim()
    expected_error = 'RRR fresh100 scope/value drift' if claim == 'rrr_fresh100_limits' else 'RRR control scope/value drift'
    assert any(expected_error in error
               for error in claims_check.check(page, manifest, tmp_path)[0])


@pytest.mark.parametrize('claim,altered', [
    ('rrr_fresh50_limits', '526.92 fb observed and 707.14 fb median expected at 50/45 GeV'),
    ('rrr_fresh50_limits', '615.63 fb observed and 755.34 fb median expected at 50/48 GeV'),
    ('rrr_fresh_anchor_coverage', '4 of 52 nominal mass points with completed fresh native evidence'),
    ('rrr_fresh_anchor_coverage', '52 of 52 nominal mass points with completed fresh native evidence'),
])
def test_fresh_anchor_headlines_cannot_count_replicas_or_substitute_references(tmp_path, claim, altered):
    relative = Path('evidence/audits/2026-09-06-rrr-fresh-anchors')
    shutil.copytree(REPO / relative, tmp_path / relative)
    entry = next(item for item in json.loads((REPO / 'evidence/claims.json').read_text())['claims']
                 if item['claim'] == claim)
    page, manifest = tmp_path / 'README.md', tmp_path / 'claims.json'
    def write_claim():
        page.write_text(f'<!-- claim:{claim} -->{entry["value"]}<!-- /claim -->')
        manifest.write_text(json.dumps({'claims': [entry]}))
    write_claim()
    assert claims_check.check(page, manifest, tmp_path)[0] == []
    entry['value'] = altered
    write_claim()
    assert any('RRR fresh-anchor scope/value drift' in error
               for error in claims_check.check(page, manifest, tmp_path)[0])


def test_fresh_anchor_headline_gate_checks_underlying_bundle_integrity(tmp_path):
    relative = Path('evidence/audits/2026-09-06-rrr-fresh-anchors')
    shutil.copytree(REPO / relative, tmp_path / relative)
    entry = next(item for item in json.loads((REPO / 'evidence/claims.json').read_text())['claims']
                 if item['claim'] == 'rrr_fresh_anchor_coverage')
    page, manifest = tmp_path / 'README.md', tmp_path / 'claims.json'
    page.write_text(f'<!-- claim:{entry["claim"]} -->{entry["value"]}<!-- /claim -->')
    manifest.write_text(json.dumps({'claims': [entry]}))
    evidence = tmp_path / relative / 'data/evidence.json'
    data = json.loads(evidence.read_text())
    data['scope']['physics_certified'] = True
    evidence.write_text(json.dumps(data))
    assert any('RRR fresh-anchor source invalid' in error
               for error in claims_check.check(page, manifest, tmp_path)[0])
