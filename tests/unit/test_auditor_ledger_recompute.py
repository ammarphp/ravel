"""The normalization auditor's recomputation on synthetic ledgers; no worker, model or native calls.

The auditor recomputes the normalization from the pinned cross-section table, luminosity,
branching fractions and signed generator-weight sums, and compares the label and every
delivered bin with that recomputation. ``audit_ledger`` stands in for the worker's use of
the card's ``must_check`` (the normalization-ledger check); the review-path integration
test reuses it as the mocked auditor.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math

import pytest

from ravel.physics import cross_sections as xs, normalization_ledger as nl

CHECK_PRODUCER = 'ravel.physics.normalization_ledger'


def pinned_table():
    """A registry table with a unique id; chosen by structure, not by name."""
    rows = xs.registry()['tables']
    counts = Counter(r['id'] for r in rows)
    return next(r for r in rows if counts[r['id']] == 1 and r['convention'].get('order') in nl.ORDERS)


def ledger(*, order=None):
    """A synthetic signal ledger bound to ``pinned_table``; ``order`` overrides its order label."""
    table = pinned_table()
    c = table['convention']
    return {
        'schema_version': 1, 'sample': 'synthetic 700 GeV chargino, 150 GeV LSP',
        'luminosity': {'value': 120.0, 'unit': 'fb^-1', 'source': 'stated integrated luminosity'},
        'sigma': {'value': 0.04, 'unit': 'pb', 'order': order or c['order'], 'tool': 'synthetic calculator',
                  'pdf': c['pdf'] or xs.AS_PUBLISHED, 'scales': 'as-published', 'process_basis': table['basis'],
                  'source': table['id'], 'pin': {'sha256': table['sha256']}},
        'br': [{'value': 0.5, 'source': 'slha', 'detail': 'synthetic decay'}],
        'filter_eff': {'value': 1.0, 'source': 'no generator filter'},
        'k': None,
        'generated': {'requested_N': 2000, 'n_events': 2000, 'sumw': 1990.0, 'sumw2': 2010.0, 'negative_fraction': 0.0},
        'selected': {'SR': {'sumw': [40.0, 25.0, -2.0], 'sumw2': [41.0, 26.0, 2.0], 'bin_edges': [250, 350, 450, 600]}},
        'bin_convention': 'per-bin', 'observable_normalized': False,
        'target_normalization': {'order': order or c['order'], 'locator': 'pinned table'},
    }


def wrong_order():
    return next(o for o in nl.ORDERS if o != pinned_table()['convention']['order'])


def recompute(doc):
    """An independent recomputation from the ledger's own factors, in the documented order."""
    br = math.prod(row['value'] for row in doc['br'])
    k = (doc.get('k') or {}).get('value', 1.0)
    per_weight = (doc['sigma']['value'] * k * br * doc['filter_eff']['value']
                  * doc['luminosity']['value'] * 1000.0 / doc['generated']['sumw'])
    return {name: [per_weight * w for w in region['sumw']] for name, region in doc['selected'].items()}


def audit_ledger(doc, *, delivered=None, check_id='normalization-ledger'):
    """Run the card's must_check; return (check result, findings) as the auditor reports them.

    A failure becomes one evidence-bearing ``code_check`` finding located by the check-result
    id; a pass gives no finding. Opinions are never produced here.
    """
    report = nl.check(doc, delivered=delivered)
    raw = json.dumps(doc, sort_keys=True).encode()
    result = {'schema_version': 1, 'kind': 'ravel-check-result', 'check_id': check_id, 'producer': CHECK_PRODUCER,
              'status': 'passed' if report['passed'] else 'failed', 'failures': report['failures'],
              'ledger_sha256': hashlib.sha256(raw).hexdigest()}
    if report['passed']:
        return result, []
    codes = sorted({f['code'] for f in report['failures']})
    return result, [{'id': 'NA-' + check_id, 'summary': 'normalization ledger recomputation failed: ' + ', '.join(codes),
                     'materiality': 'A', 'evidence_class': 'code_check', 'evidence_locators': ['check:' + check_id],
                     'location': '$.sigma', 'status': 'open'}]


def codes(report):
    return {f['code'] for f in report['failures']}


def test_recomputation_from_the_pinned_source_matches_every_delivered_bin():
    doc = ledger()
    expected = recompute(doc)
    report = nl.check(doc, delivered=expected)
    assert report['passed'], report['failures']
    assert not any(w['code'] == 'source_unpinned' for w in report['warnings'])
    assert report['expected']['SR']['values'] == pytest.approx(expected['SR'], rel=1e-12)
    # The signed weight stays signed; nothing is clipped to make the total look physical.
    assert report['expected']['SR']['values'][2] < 0


def test_planted_order_label_is_a_blocking_code_check_finding():
    doc = ledger(order=wrong_order())
    result, findings = audit_ledger(doc, delivered=recompute(doc))
    assert result['status'] == 'failed'
    mismatch = next(f for f in result['failures'] if f['code'] == 'sigma_table_mismatch')
    assert mismatch['field'] == 'order' and wrong_order() in mismatch['explanation']
    assert pinned_table()['convention']['order'] in mismatch['explanation']
    [finding] = findings
    assert finding['evidence_class'] == 'code_check' and finding['materiality'] == 'A'
    assert finding['evidence_locators'] == ['check:normalization-ledger']


def test_corrected_ledger_returns_no_finding():
    planted = ledger(order=wrong_order())
    corrected = deepcopy(planted)
    corrected['sigma']['order'] = corrected['target_normalization']['order'] = pinned_table()['convention']['order']
    result, findings = audit_ledger(corrected, delivered=recompute(corrected))
    assert result['status'] == 'passed' and findings == []
    # The correction changes the ledger bytes the earlier failure was computed for.
    assert result['ledger_sha256'] != audit_ledger(planted)[0]['ledger_sha256']


def test_central_value_agreement_does_not_hide_a_label_error():
    """The planted label leaves every number unchanged: only the pinned-table comparison finds it."""
    planted = ledger(order=wrong_order())
    assert recompute(planted) == recompute(ledger())
    assert 'sigma_table_mismatch' in codes(nl.check(planted, delivered=recompute(planted)))


@pytest.mark.parametrize('factor,code', [(1000.0, 'unit_swap'), (1e-3, 'unit_swap')])
def test_applied_factor_errors_in_delivered_bins_are_named(factor, code):
    doc = ledger()
    delivered = {'SR': [y * factor for y in recompute(doc)['SR']]}
    result, findings = audit_ledger(doc, delivered=delivered)
    assert code in {f['code'] for f in result['failures']} and findings


def test_unpinned_source_is_flagged_not_certified():
    doc = ledger()
    doc['sigma'].pop('pin')
    doc['sigma']['source'] = 'synthetic free-text source'
    report = nl.check(doc)
    assert any(w['code'] == 'source_unpinned' for w in report['warnings'])


def test_stale_check_result_stops_blocking_after_the_ledger_changes(tmp_path, monkeypatch):
    """The failure is bound to the ledger bytes; a corrected file cannot be blocked by the old result."""
    from ravel.workflow import rdj_custody, rdj_loop
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'
    path = run / 'inputs/normalization_ledger.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(ledger(order=wrong_order())))
    result, _ = audit_ledger(json.loads(path.read_text()))
    result['pins'] = [{'path': 'inputs/normalization_ledger.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    (run / 'checks').mkdir()
    (run / 'checks/normalization-ledger.json').write_text(json.dumps(result))
    rdj_custody.register_check_result(run, 'checks/normalization-ledger.json')
    assert rdj_loop._check_pins_current(run, rdj_custody.check_result(run, 'normalization-ledger'))
    path.write_text(json.dumps(ledger()))
    assert not rdj_loop._check_pins_current(run, rdj_custody.check_result(run, 'normalization-ledger'))
