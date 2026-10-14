"""Machine consumers for existing signature terms and inherited lineage obligations.

Where an existing validator is available it remains the authority. Other terms
compare explicit raw records, rather than accepting a host's pass/fail annotation.
"""
from __future__ import annotations

from functools import partial
from .rows import number, sequence, pin, result


def _comparisons(doc):
    comparisons = sequence(doc['comparisons'])
    failures = []
    for i, row in enumerate(comparisons):
        prediction, reference = number(row['prediction']), number(row['reference'])
        tolerance = number(row['absolute_tolerance'], nonnegative=True)
        if abs(prediction - reference) > tolerance:
            failures.append(i)
    return result(not failures, 'all raw comparisons must satisfy the declared bounds', failing_comparisons=failures)


def _certificate(kind, doc, *, root=None, contract=None, required_subjects=(), science_envelope=False, **context):
    from ravel.validation.certificates import validate_certificate
    if root is not None and contract is None and not science_envelope:
        from ravel.validation.certificates import read_json, local_path
        contract = read_json(local_path(root, 'inputs/task_contract.json'))
    if root is None or contract is None or not required_subjects:
        raise ValueError('a certificate needs current approval and every served subject')
    checked = validate_certificate(root, doc['path'], kind=kind, contract=contract,
                                   required_subjects=required_subjects, live=True,
                                   science_envelope=science_envelope)
    return result(checked['status'] == 'PASS', '; '.join(checked['errors']) or 'artifact-bound comparison recomputed', certificate=checked['evidence'])


def _check(name, doc, *, plan=None, claim=None, documents=(), reading=None, **context):
    if name in ('closure', 'decay_closure', 'formula_check_value', 'numerical_reference', 'routine_validation'):
        return _comparisons(doc)
    if name in ('acceptance_certificate', 'r5'):
        return _certificate('acceptance' if name == 'acceptance_certificate' else 'r5', doc, **context)
    if name == 'fit_alarms':
        from ravel.validation.regression_triggers import evaluate, consume_flags
        records = [d for _, d in documents if d.get('kind') == 'inference'] or sequence(doc.get('records'))
        checks = [c for d in records for c in (evaluate(d) if d.get('kind') == 'inference' else consume_flags(d))]
        failures = [c for c in checks if c['status'] == 'fail']
        return result(not failures, 'fit and scan alarms recomputed from inference artifacts', alarms=checks)
    if name == 'limit_status':
        from ravel.limits import claim_errors
        records = [d for _, d in documents if 'limits' in d] or sequence(doc.get('records'))
        errors = [e for d in records for e in claim_errors(d)]
        return result(not errors, '; '.join(errors) or 'typed limit status preserved')
    if name == 'statistic_matches_claim':
        approved = (claim or {}).get('statistic', {}).get('definition') or doc['approved_statistic']
        delivered = doc.get('delivered_statistic')
        if delivered is None:
            actual = [d.get('statistic', {}).get('definition') for _, d in documents if d.get('kind') == 'inference']
            if not actual or any(v is None for v in actual):
                raise ValueError('delivered inference must state its statistic')
        else:
            actual = [delivered]
        return result(all(v == approved for v in actual), 'delivered statistic must equal the approved definition')
    if name == 'normalization_ledger':
        from ravel.physics.normalization_ledger import check
        report = check(doc['ledger'], delivered=doc.get('delivered'))
        return result(not report['failures'], 'normalization ledger recomputed', report=report)
    if name == 'summary_complete':
        from ravel.validation.summary_audit import audit
        report = audit(doc['survey'], doc['manifest'])
        return result(report['verdict'] == 'PASS', 'summary population and basis audited', audit=report)
    if name == 'figure_comparison':
        from ravel.plotting.reference_comparison import verify_target_comparison
        errors = verify_target_comparison(doc['target'])
        return result(not errors, '; '.join(errors) or 'published-figure comparison recomputed')
    if name == 'validation.plot_lint':
        from ravel.validation.plot_lint import figure_spec_errors
        errors = figure_spec_errors(doc['figure_spec'])
        return result(not errors, '; '.join(errors) or 'declared figure axes and units are valid')
    if name == 'io_contract':
        from ravel.validation.signature_conformance import witness
        artifacts = sequence(doc.get('artifacts'))
        errors = [e for artifact in artifacts for e in witness(artifact['kind'], artifact['document'])]
        return result(not errors, '; '.join(errors) or 'all delivered kinds pass their witnesses')
    if name == 'census':
        requested, retained = sequence(doc['required_ids']), sequence(doc['retained_ids'])
        return result(len(retained) == len(set(retained)) and set(requested) <= set(retained), 'the required source population must be retained without duplicate ids')
    if name == 'known_answer_tests':
        tests = sequence(doc['tests'])
        return result(all(t['actual'] == t['expected'] and type(t['actual']) is type(t['expected']) for t in tests), 'authored code must reproduce every declared known answer')
    if name == 'invisible_card':
        invisible, treated = sequence(doc['invisible_states']), sequence(doc['detector_invisible_states'])
        return result(set(invisible) <= set(treated), 'all declared invisible states must be invisible in the effective detector card')
    if name == 'likelihood_pairing':
        published, applied = doc['published_selection_sha256'], doc['applied_selection_sha256']
        pin({'path': 'selection', 'sha256': published}); pin({'path': 'selection', 'sha256': applied})
        return result(published == applied, 'the likelihood and applied selection must have the same pinned basis')
    if name == 'lhe_check':
        rows = sequence(doc['events'])
        errors = [i for i, event in enumerate(rows) if type(event['declared_particles']) is not int or event['declared_particles'] != len(sequence(event['particles'])) or not all(number(p['energy'], nonnegative=True) >= abs(number(p['pz'])) for p in event['particles'])]
        return result(not errors, 'LHE particle census and basic four-vector domain recomputed', failing_events=errors)
    if name == 'deviations':
        rows = sequence(doc['settings'])
        failures = []
        for i, row in enumerate(rows):
            if type(row['requested']) is not type(row['effective']) or row['requested'] != row['effective']:
                if not row.get('deviation_pin'):
                    failures.append(i)
                else:
                    pin(row['deviation_pin'])
        return result(not failures, 'changed effective settings require a located deviation', missing_deviations=failures)
    if name == 'prose':
        from ravel.limits import prose_errors
        errors = prose_errors(doc['text'], doc['inference'])
        return result(not errors, '; '.join(errors) or 'prose is consistent with typed inference')
    if name == 'basis_manifest':
        curves = sequence(doc['curves'])
        pin(doc['target_basis'])
        for curve in curves:
            pin(curve['source_basis'])
            if curve['source_basis'] != doc['target_basis']:
                pin(curve['conversion'])
                if curve['identity_actual'] != curve['identity_expected']:
                    return result(False, 'a basis conversion failed its declared identity check')
        return result(True, 'all source bases and conversions are pinned')
    if name == 'independent_reference':
        prediction, reference = sequence(doc['prediction_pins']), sequence(doc['reference_pins'])
        a, b = {pin(p)['sha256'] for p in prediction}, {pin(p)['sha256'] for p in reference}
        return result(not a & b, 'comparison reference must have independent evidence lineage')
    if name == 'field_authority':
        if plan is not None and claim is not None:
            from ravel.validation import validate_request_plan as rp
            refs = rp.ancestors(plan, claim['id'])
            nodes = {n['id']: n for n in plan['nodes'] if n['id'] in refs}
            ambiguities = {a['id']: a for a in (reading or {}).get('ambiguities', [])}
            errors = rp._critical_fields(plan, rp.registry(), nodes, ambiguities)
            return result(not errors, '; '.join(e['reason'] for e in errors) or 'critical declared fields satisfy the current anchored-authority rule')
        fields = sequence(doc['fields'])
        for field in fields:
            if field['authority'] == 'adapter_default' or not field.get('anchor'):
                return result(False, 'critical fields need an anchored authority')
            pin(field['anchor'])
        return result(True, 'every critical field has anchored authority')
    if name == 'observed_admissible':
        provided = [i.get('provides', {}).get('require', {}) for i in (plan or {}).get('inputs', []) if i['id'] in __import__('ravel.validation.validate_request_plan', fromlist=['ancestors']).ancestors(plan, claim['id'])] if plan else sequence(doc['inputs'])
        return result(any(p.get('observed') is True or p.get('contains_observed_data') is True for p in provided), 'an observed claim needs measured data in its lineage')
    if name == 'reference_withheld':
        forbidden = {pin(p)['sha256'] for p in sequence(doc['forbidden_pins'])}
        consumed = {pin(p)['sha256'] for p in sequence(doc['consumed_pins'])}
        pin(doc['alternative_waypoint'])
        return result(not forbidden & consumed and doc['fidelity'] == 'blinded-prediction', 'withheld references must stay outside post-run prediction lineage')
    if name == 'designed_selection_bundle':
        closure = _comparisons(doc['mc_closure'])
        pin(doc['cutflow_review'])
        number(doc['relative_mc_target'], positive=True)
        return result(closure['status'] == 'pass' and doc['fidelity'] == 'uncertified-proxy' and doc['in_record'] is False, 'a designed or unanchored selection needs MC closure, cutflow review and proxy fidelity')
    if name == 'split_integrity':
        training, test = sequence(doc['training_ids']), sequence(doc['test_ids'])
        return result(not set(training) & set(test), 'training and test populations must be disjoint')
    if name == 'baseline_first':
        return result(number(doc['baseline_sequence'], nonnegative=True) < number(doc['candidate_sequence'], nonnegative=True), 'the frozen baseline must precede candidate evaluation')
    raise ValueError('unresolved legacy check ' + name)


NAMES = ('acceptance_certificate', 'basis_manifest', 'census', 'closure', 'decay_closure', 'deviations',
         'figure_comparison', 'fit_alarms', 'formula_check_value', 'independent_reference', 'invisible_card',
         'io_contract', 'known_answer_tests', 'lhe_check', 'likelihood_pairing', 'limit_status',
         'normalization_ledger', 'numerical_reference', 'prose', 'r5', 'routine_validation',
         'statistic_matches_claim', 'summary_complete', 'validation.plot_lint', 'field_authority',
         'observed_admissible', 'reference_withheld', 'designed_selection_bundle', 'split_integrity', 'baseline_first')
EVALUATORS = {name: partial(_check, name) for name in NAMES}
