"""Normalization ledger: recomputation of delivered yields and one named failure per injected error."""
import copy
import math

import pytest

from ravel.physics import normalization_ledger as nl


def basis(order, pdf='NNPDF31_lo', jets=0):
    return {'order': order, 'final_states': ['l+ l-'], 'multiplicities': {'extra_jets': jets},
            'generation_cuts': {'mll_min_GeV': 50}, 'pdf': pdf, 'scales': 'dynamic HT/2'}


def ledger(**over):
    doc = {
        'schema_version': 1, 'sample': 'synthetic signal',
        'luminosity': {'value': 140.0, 'unit': 'fb^-1', 'source': 'stated integrated luminosity'},
        'sigma': {'value': 0.5, 'unit': 'pb', 'order': 'LO', 'tool': 'MG5_aMC', 'pdf': 'NNPDF31_lo',
                  'scales': 'dynamic HT/2', 'process_basis': 'p p > X > l+ l-', 'source': 'generator banner'},
        'br': [{'value': 0.25, 'source': 'slha', 'detail': 'X -> l+ l-'}],
        'filter_eff': {'value': 0.8, 'source': 'generator filter 800/1000'},
        'k': {'value': 1.3, 'applied_once': True, 'numerator_basis': basis('NLO'), 'denominator_basis': basis('LO')},
        'generated': {'requested_N': 1000, 'n_events': 1000, 'sumw': 980.0, 'sumw2': 1010.0, 'negative_fraction': 0.01},
        'selected': {'SR': {'sumw': [100.0, 50.0, 10.0], 'sumw2': [110.0, 55.0, 11.0], 'bin_edges': [0, 100, 200, 400]}},
        'bin_convention': 'per-bin', 'observable_normalized': False,
        'target_normalization': {'order': 'NLO', 'locator': 'Table 2'},
    }
    doc.update(over)
    return doc


def exact_yields(doc):
    s = 0.5 * 1.3 * 0.25 * 0.8 * 140.0 * 1000 / 980.0
    return {'SR': [s * w for w in doc['selected']['SR']['sumw']]}


def test_known_sigma_k_br_and_luminosity_reproduce_the_yields():
    doc = ledger()
    report = nl.check(doc, delivered=exact_yields(doc))
    assert report['passed'], report['failures']
    assert math.isclose(report['scale'], 0.5 * 1.3 * 0.25 * 0.8 * 140e3 / 980.0, rel_tol=1e-15)
    assert report['warnings'][0]['code'] == 'negative_weights'
    assert math.isclose(report['applied_sigma_pb'], 0.5 * 1.3 * 0.25 * 0.8, rel_tol=1e-15)


def codes(report):
    return {f['code'] for f in report['failures']}


def scaled(doc, factor):
    return {'SR': [y * factor for y in exact_yields(doc)['SR']]}


def test_k_applied_twice_is_named():
    doc = ledger()
    assert 'k_applied_twice' in codes(nl.check(doc, delivered=scaled(doc, 1.3)))
    flagged = ledger(k={**ledger()['k'], 'applied_once': False})
    assert 'k_applied_twice' in codes(nl.check(flagged))


def test_pb_fb_swap_is_named():
    doc = ledger()
    assert 'unit_swap' in codes(nl.check(doc, delivered=scaled(doc, 1000.0)))
    assert 'unit_swap' in codes(nl.check(doc, delivered=scaled(doc, 1e-3)))


def test_events_per_gev_template_is_named():
    doc = ledger()
    widths = [100, 100, 200]
    per_gev = {'SR': [y / w for y, w in zip(exact_yields(doc)['SR'], widths)]}
    assert 'bin_convention' in codes(nl.check(doc, delivered=per_gev))
    per_width = ledger(bin_convention='per-unit-width')
    assert nl.check(per_width, delivered=per_gev)['passed']


def test_omitted_br_is_named():
    doc = ledger()
    assert 'br_omitted' in codes(nl.check(doc, delivered=scaled(doc, 4.0)))


def test_mismatched_k_basis_is_named():
    jets = ledger(k={**ledger()['k'], 'numerator_basis': basis('NLO', jets=1)})
    report = nl.check(jets)
    assert 'k_basis_mismatch' in codes(report) and 'multiplicities' in report['failures'][0]['explanation']
    pdf = ledger(k={**ledger()['k'], 'numerator_basis': basis('NLO', pdf='NNPDF31_nlo')})
    assert 'k_basis_mismatch' in codes(nl.check(pdf))


def test_zero_sum_of_weights_is_named():
    doc = ledger(generated={'requested_N': 1000, 'n_events': 1000, 'sumw': 0.0, 'sumw2': 10.0})
    report = nl.check(doc)
    assert 'sumw_nonpositive' in codes(report) and report['scale'] is None


def test_requested_n_as_denominator_is_named():
    doc = ledger()
    assert 'requested_N_denominator' in codes(nl.check(doc, delivered=scaled(doc, 980.0 / 1000)))
    assert 'requested_N_denominator' in codes(nl.check(ledger(denominator='requested_N')))
    unit = ledger(generated={'requested_N': 1000, 'n_events': 1000, 'sumw': 1000.0, 'sumw2': 1000.0},
                  denominator='n_events')
    assert 'requested_N_denominator' not in codes(nl.check(unit))


def test_uniform_k_on_normalized_observable_is_flagged_as_no_op():
    report = nl.check(ledger(observable_normalized=True))
    assert any(w['code'] == 'k_noop_on_normalized_observable' for w in report['warnings'])
    assert not any(w['code'] == 'k_noop_on_normalized_observable' for w in nl.check(ledger())['warnings'])


def test_certifier_sigma_must_equal_the_ledger_applied_sigma():
    doc = ledger()
    applied_fb = nl.applied_sigma_pb(doc) * 1000
    assert nl.check(doc, certifier_sigma_fb=applied_fb)['passed']
    assert 'certifier_sigma_differs' in codes(nl.check(doc, certifier_sigma_fb=0.5 * 1000))


def test_negative_weight_samples_use_signed_sumw():
    doc = ledger(generated={'requested_N': 1000, 'n_events': 1000, 'sumw': 640.0, 'sumw2': 1000.0,
                            'negative_fraction': 0.18})
    s = 0.5 * 1.3 * 0.25 * 0.8 * 140e3 / 640.0
    assert nl.check(doc, delivered={'SR': [s * 100, s * 50, s * 10]})['passed']


def test_single_bin_and_tolerance_not_bit_equality():
    doc = ledger(selected={'SR': {'sumw': [42.0], 'sumw2': [44.0]}})
    s = nl.scale(doc)
    assert nl.check(doc, delivered={'SR': [s * 42.0 * (1 + 1e-14)]})['passed']
    assert not nl.check(doc, delivered={'SR': [s * 42.0 * (1 + 1e-9)]})['passed']


def test_br_product_and_undeclared_unit_br_assumption():
    doc = ledger(br=[{'value': 1.0, 'source': 'paper_assumption', 'detail': 'X -> l+ l-'}])
    assert 'br_assumption_undeclared' in codes(nl.check(doc))
    doc['br'][0]['statement'] = 'we assume BR(X -> l l) = 100%'
    assert nl.check(doc)['passed']
    assert 'br_above_one' in codes(nl.check(ledger(br=[{'value': 1.2, 'source': 'slha', 'detail': 'x'}])))


def test_order_against_target_gives_checkin2_item():
    report = nl.check(ledger(target_normalization={'order': 'NNLO+NNLL', 'locator': 'Section 5'}))
    assert report['passed']
    assert any(w['code'] == 'order_differs_from_target' for w in report['warnings'])
    assert 'NNLO+NNLL' in report['checkin2_items'][0]
    lines = nl.checkin_lines(report, ledger())
    assert lines[-1].startswith('Before changing any cut')


def test_k_on_already_corrected_sigma_is_refused():
    doc = ledger(sigma={**ledger()['sigma'], 'order': 'NLO'})
    assert 'k_on_corrected_sigma' in codes(nl.check(doc))


def test_independent_cross_checks_only_warn():
    doc = ledger(cross_checks=[{'tool': 'second calculator', 'order': 'LO', 'pdf': 'CT18', 'sigma_pb': 0.7,
                                'rel_tol': 0.1}])
    report = nl.check(doc)
    assert report['passed'] and any(w['code'] == 'cross_check_differs' for w in report['warnings'])


def native_record():
    return {'schema_version': 1, 'status': 'resolved', 'basis': 'unmerged_lo_lhe', 'cross_section_pb': 0.5,
            'kfactor': 1.3, 'applied_cross_section_pb': 0.65, 'correction_applications': 1,
            'luminosity_applied': False,
            'generation': {'cross_section_pb': 0.5, 'n_events': 1000, 'sumw': 980.0, 'sumw2': 1010.0,
                           'negative_weights': 10},
            'shower': {'n_events': 1000, 'cross_section_pb': 0.5},
            'sources': [{'path': 'events.lhe', 'sha256': 'a' * 64}],
            'decay_factors': {'per_particle': [{'particle': 9000006, 'source': 'pythia', 'factor': 0.25}],
                              'filters': [{'name': 'lepton filter', 'efficiency': 0.8, 'source': 'filter log'}],
                              'filter_factor': 0.8}}


def test_existing_native_normalization_record_round_trips_unchanged():
    record = native_record()
    before = copy.deepcopy(record)
    doc = nl.from_native_normalization(
        record, luminosity=ledger()['luminosity'], selected=ledger()['selected'], sample='synthetic signal',
        sigma_convention={'order': 'LO', 'tool': 'MG5_aMC', 'pdf': 'NNPDF31_lo', 'scales': 'dynamic HT/2',
                          'process_basis': 'p p > X > l+ l-', 'source': 'generator banner'},
        k_bases={'numerator_basis': basis('NLO'), 'denominator_basis': basis('LO')})
    assert record == before and doc['sources']['native_normalization'] == before
    assert math.isclose(nl.scale(doc), nl.scale(ledger()), rel_tol=1e-15)
    assert nl.check(doc, delivered=exact_yields(doc))['passed']


def test_engine_block_reproduces_the_ledger_scale():
    doc = ledger()
    spec = nl.engine_normalization(doc)
    f = spec['factor']['value']
    engine_scale = spec['cross_section_pb'] * 1000.0 * spec['luminosity_ifb'] * f / spec['sum_of_weights']
    assert nl.check_engine_scale(doc, {'scale': engine_scale})['passed']
    assert not nl.check_engine_scale(doc, {'scale': engine_scale * 1.3})['passed']
    pointer = nl.engine_normalization(doc, receipt='production-receipt.json')['cross_section_pb']
    assert pointer == {'production_receipt': 'production-receipt.json', 'pointer': '/normalization_ledger/applied_sigma_pb'}


def test_receipt_block_carries_applied_sigma_and_convention():
    block = nl.receipt_block(ledger())
    assert block['sigma_pb'] == block['normalization_ledger']['applied_sigma_pb']
    assert block['sigma_convention']['order'] == 'LO' and block['sigma_source'] == 'generator banner'


def test_root_stream_scale_delegates_to_the_ledger_formula():
    from ravel.physics import root_stream_core
    sample = {'kind': 'mc', 'normalization': {'luminosity_fb_inverse': 140.0, 'cross_section_pb': 0.5,
                                              'filter_efficiency': 0.8, 'k_factor': 1.3, 'sum_weights': 980.0}}
    assert root_stream_core.scale(sample) == 140.0 * 1000 * 0.5 * 0.8 * 1.3 / 980.0


def test_validation_refuses_missing_sources_and_units():
    with pytest.raises(ValueError, match='luminosity unit'):
        nl.validate(ledger(luminosity={'value': 1, 'unit': 'fb', 'source': 's'}))
    bad = ledger()
    del bad['sigma']['pdf']
    with pytest.raises(ValueError, match='cross-section pdf'):
        nl.validate(bad)
    with pytest.raises(ValueError, match='needs a source'):
        nl.validate(ledger(br=[{'value': 0.5, 'source': 'guess', 'detail': 'x'}]))


def pinned_ledger():
    from ravel.physics import cross_sections as xs
    entry = xs.table_entry('pp13600-gluino-nnlo-nnll')
    return ledger(k=None, sigma={**ledger()['sigma'], 'order': entry['convention']['order'],
                                'pdf': entry['convention']['pdf'], 'process_basis': entry['basis'],
                                'source': entry['id']})


@pytest.mark.parametrize('field,value', [('order', 'NLO+NLL'), ('pdf', 'synthetic other PDF'),
                                       ('process_basis', 'synthetic other production')])
def test_pinned_sigma_refuses_mismatched_convention_and_basis(field, value):
    doc = pinned_ledger()
    assert nl.check(doc)['passed']
    table_value = doc['sigma'][field]
    doc['sigma'][field] = value
    report = nl.check(doc)
    assert 'sigma_table_mismatch' in codes(report)
    explanation = next(r['explanation'] for r in report['failures'] if r['code'] == 'sigma_table_mismatch')
    assert value in explanation and table_value in explanation


def test_hash_source_is_bound_and_free_text_source_is_flagged():
    from ravel.physics import cross_sections as xs
    doc = pinned_ledger()
    doc['sigma']['source'] = xs.table_entry(doc['sigma']['source'])['sha256']
    doc['sigma']['order'] = 'NLO+NLL'
    assert 'sigma_table_mismatch' in codes(nl.check(doc))
    report = nl.check(ledger())
    assert report['passed'] and any(w['code'] == 'source_unpinned' for w in report['warnings'])


def test_unknown_table_pdf_cannot_be_invented():
    doc = ledger(k=None, sigma={**ledger()['sigma'], 'order': 'aNNLO+NNLL',
                               'source': 'pp13-gluino-nnlo-nnll', 'process_basis': 'gluino_pair'})
    assert 'sigma_table_mismatch' in codes(nl.check(doc))
    doc['sigma']['pdf'] = 'as-published'
    assert nl.check(doc)['passed']


def test_lookup_builder_preserves_a_registry_pin_and_own_convention(monkeypatch):
    from ravel.physics import cross_sections as xs
    monkeypatch.setattr(xs, 'load_table', lambda entry: {'data': {'700': {'xsec_pb': 0.6}}})
    lookup = xs.lookup({'schema_version': 1, 'basis': 'gluino_pair', 'sqrt_s_GeV': 13600,
                        'masses': {'mass': 700}, 'convention': {
                            'order': 'aNNLO+NNLL', 'pdf': 'as-published', 'scale': 'as-published'}})
    doc = ledger(k=None, sigma=nl.from_cross_section(lookup))
    report = nl.check(doc)
    assert report['passed']
    assert not any(w['code'] == 'source_unpinned' for w in report['warnings'])
    doc['sigma']['order'] = 'NLO+NLL'
    assert 'sigma_table_mismatch' in codes(nl.check(doc))


def test_alternate_reports_recomputed_total_and_ratio_without_mutation():
    doc = ledger(sigma_alternates=[{'order': 'NLO', 'pdf': 'synthetic PDF',
                                   'value_pb': 0.75, 'source': 'synthetic alternate calculator'}])
    before = copy.deepcopy(doc)
    primary = nl.check(ledger(), delivered=exact_yields(doc))
    report = nl.check(doc, delivered=exact_yields(doc))
    assert report['passed'] and doc == before
    assert report['expected'] == primary['expected'] and report['scale'] == primary['scale']
    alternate = report['sigma_alternates'][0]
    assert alternate['ratio'] == pytest.approx(1.5)
    assert alternate['delivered_total'] == pytest.approx(sum(exact_yields(doc)['SR']) * 1.5)
    assert any('Alternate' in line and '1.5' in line for line in nl.checkin_lines(report, doc))
    assert nl.receipt_block(doc)['normalization_ledger']['sigma_alternates'] == doc['sigma_alternates']


@pytest.mark.parametrize('field,value', [('value_pb', -1), ('value_pb', float('nan')),
                                       ('order', 'made-up'), ('pdf', ''), ('source', '')])
def test_invalid_alternates_are_refused(field, value):
    alternate = {'order': 'NLO', 'pdf': 'synthetic PDF', 'value_pb': 0.75, 'source': 'synthetic calculator'}
    alternate[field] = value
    with pytest.raises(ValueError):
        nl.check(ledger(sigma_alternates=[alternate]))


def test_duplicate_registry_id_requires_a_disambiguating_hash():
    from ravel.physics import cross_sections as xs
    entries = [e for e in xs.registry()['tables'] if e['id'] == 'pp13600-wino-1000023-1000024-nnll']
    entry = entries[0]
    doc = ledger(k=None, sigma={**ledger()['sigma'], 'source': entry['id'],
                               'order': entry['convention']['order'], 'pdf': entry['convention']['pdf'],
                               'process_basis': entry['basis']})
    assert 'sigma_table_ambiguous' in codes(nl.check(doc))
    doc['sigma']['pin'] = {'sha256': entry['sha256']}
    assert nl.check(doc)['passed']
    doc['sigma']['pin']['sha256'] = 'a' * 64
    assert 'sigma_table_pin_mismatch' in codes(nl.check(doc))


def test_charge_sum_builder_checks_every_constituent_table(monkeypatch):
    from ravel.physics import cross_sections as xs
    monkeypatch.setattr(xs, 'load_table', lambda entry: {'data': {'700': {'xsec_pb': 0.6}}})
    lookup = xs.lookup({'schema_version': 1, 'basis': 'wino_C1N2', 'sqrt_s_GeV': 13600,
                        'masses': {'mass': 700}, 'charge': 'sum', 'convention': {
                            'order': 'aNNLO+NNLL', 'pdf': 'as-published', 'scale': 'as-published'}})
    doc = ledger(k=None, sigma=nl.from_cross_section(lookup))
    assert nl.check(doc)['passed']
    assert len(doc['sigma']['tables']) == 2
    assert not any(w['code'] == 'source_unpinned' for w in nl.check(doc)['warnings'])
    doc['sigma']['tables'][1]['sha256'] = 'a' * 64
    assert 'sigma_table_pin_mismatch' in codes(nl.check(doc))


def test_alternate_total_integrates_density_bins_and_keeps_signed_weights():
    doc = ledger(bin_convention='per-unit-width',
                 selected={'SR': {'sumw': [2., -1.], 'sumw2': [4., 1.], 'bin_edges': [0., 2., 6.]}},
                 sigma_alternates=[{'order': 'NLO', 'pdf': 'synthetic PDF',
                                    'value_pb': 0.75, 'source': 'synthetic alternate'}])
    report = nl.check(doc)
    row = report['sigma_alternates'][0]
    assert row['delivered_total'] == pytest.approx(nl.scale(doc) * 1.5)


def test_pinned_alternate_mismatch_is_refused():
    doc = ledger(sigma_alternates=[{'order': 'NLO+NLL', 'pdf': 'as-published',
                                   'value_pb': 0.75, 'source': 'pp13-gluino-nnlo-nnll'}])
    report = nl.check(doc)
    assert not report['passed']
    assert any(f['code'] == 'sigma_table_mismatch' and f['sigma_alternate'] == 0 for f in report['failures'])


def test_constituent_records_do_not_override_the_declared_source():
    from ravel.physics import cross_sections as xs
    doc = pinned_ledger()
    other = xs.table_entry('pp13-sgmodel-ggxsec-nlo-nll')
    doc['sigma']['tables'] = [{'id': other['id'], 'sha256': other['sha256']}]
    doc['sigma']['order'] = other['convention']['order']
    assert 'sigma_table_mismatch' in codes(nl.check(doc))
