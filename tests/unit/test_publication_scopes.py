"""Scientific reporting must keep denominators and reject contradictory evidence."""
import copy
import importlib.util
import json
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
