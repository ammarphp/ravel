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


def test_historical_scopes_and_failures_remain_visible():
    cases, results, _ = load_baseline()
    summary = summarize(cases, results)
    assert summary['registry_cases'] == 9
    assert summary['statistical_layer']['eligible_comparisons'] == 7
    assert summary['statistical_layer']['reference_unavailable'] == 2
    assert summary['acceptance_layer']['verdict_counts'] == {'PASS': 4, 'WARN': 1, 'FAIL': 1}
    pages, _ = render()
    assert set(pages) == {'README.md'} | {c['case_id'] + '.md' for c in cases}
    assert 'Certification verdict: FAIL' in pages['ins2182381_gbb_1900_1.md']
    assert 'unscorable' in pages['ins1676551_c1n2_300_100.md']


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
    target = tmp_path / 'framework/benchmark'
    target.mkdir(parents=True)
    for name in ('cases.json', 'results.json'):
        doc = json.loads((REPO / 'framework/benchmark' / name).read_text())
        if name == 'results.json':
            doc['cases'].pop()
        (target / name).write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='registry/baseline mismatch'):
        render(tmp_path)


def test_validation_page_freshness_is_a_real_readonly_gate():
    result = subprocess.run([sys.executable, str(REPO / 'scripts/gen_validation_pages.py'), '--check'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
