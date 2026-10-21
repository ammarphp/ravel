"""Validator-run rows (node step.validate): the installed validators, attacked directly.

Each case feeds the validator that implements the row's expectation one adversarial change to a
valid, fictional fixture and asserts, from outside the validator, the typed refusal or the
labelled flag it must give. A positive control (the consistent fixture) runs through the same
entry first. The mutation registered for each case disables that validator's own check and the
case then fails on its oracle.

Installed validators used, by row:

- P05 and E17: ``ravel.validation.semantic_composition.plan_report``, the quantity-descriptor part
  of the ordinary request-plan composition check (``validate_request_plan.check`` calls it).
- E07, E10 and E13: ``ravel.physics.scoped.audit_lhe``, the whole-file validator of a retained
  generation product against the approved generation.
- E08: ``ravel.physics.detector_card.invisible_census``, the invisible-state closure check.
- E14: ``ravel.workflow.analysis_admission.assess``, the open admission check.
- E18: ``ravel.physics.normalization_ledger.check`` through the registered run-check adapter
  ``check:physics.normalization_ledger.check`` of ``ravel.workflow.run_validator_checks``.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nc_cases import INSTALLED, case
from nc_mutations import Mutation, register, returns


# ---------------------------------------------------------------- shared fictional fixtures

def _quantity(kind='event_count', unit='events'):
    """A complete invented quantity descriptor."""
    return {'kind': kind, 'unit': unit, 'scale': 1,
            'normalization': {'per_luminosity': kind in ('cross_section', 'differential_cross_section'),
                              'per_bin_width': False, 'per_event': False},
            'included_factors': [{'name': 'factor-a', 'kind': 'branching_fraction',
                                  'value': 0.4, 'source': 'supplied:table-a'}],
            'weight_convention': 'signed', 'selection': 'region-set-a',
            'model_point': {'model': 'model-a', 'mass': 80},
            'event_population': {'id': 'sample-a', 'revision': 'revision-a', 'grouping': 'event',
                                 'events': 10, 'sumw': 10, 'sumw2': 10, 'negative_events': 0},
            'applicability': {'id': 'domain-a', 'parameters': {}, 'assumptions': []},
            'covariance': {'status': 'unknown', 'basis': [], 'matrix': None, 'source': 'declared in the fixture'},
            'luminosity': {'value': 1, 'unit': 'fb^-1', 'scale': 1},
            'bin_ids': ['region-a:0', 'region-b:0'],
            'exposure': {'id': 'sample-a', 'revision': 'revision-a'},
            'regional_exposures': {'region-a': {'id': 'sample-a', 'revision': 'revision-a'},
                                   'region-b': {'id': 'sample-a', 'revision': 'revision-a'}}}


def _registry():
    from ravel.validation import validate_request_plan
    return validate_request_plan.registry()


def _fields(rows):
    return {row['field'] for row in rows}


# ---------------------------------------------------------------- P05 descriptors between operations

def _hand_over_report(quantity):
    """Plan report of one producer -> consumer edge carrying ``quantity`` as its artifact."""
    from ravel.validation import semantic_composition
    plan = {'nodes': [{'id': 'N1', 'operation': 'event-production'},
                      {'id': 'N2', 'operation': 'columnar-analysis'}],
            'inputs': [],
            'edges': [{'id': 'E1', 'from': {'ref': 'N1', 'slot': 'events'}, 'to': {'ref': 'N2', 'slot': 'events'},
                       'require': {}}]}
    artifacts = {'E1': {'quantity': quantity}}
    return semantic_composition.plan_report(plan, _registry(), artifacts)


@case('P05', binding=INSTALLED)
def test_P05_a_flipped_sign_convention_is_refused_and_a_dropped_covariance_is_labelled(nc):
    good = _quantity('sample_exposure')
    # Positive control: the consistent hand-over raises neither an error nor an obligation.
    control = _hand_over_report(good)
    assert control == {'errors': [], 'obligations': []}

    # Attack 1: the signed-weight convention the producer declares is flipped between operations.
    flipped = deepcopy(good)
    flipped['weight_convention'] = 'absolute'
    report = _hand_over_report(flipped)
    mismatch = [row for row in report['errors'] if row['field'] == 'weight_convention']
    assert mismatch, 'a flipped weight sign convention must be a typed descriptor mismatch'
    assert all(row['observed'] == 'absolute' and row['expected'] == 'signed' for row in mismatch)

    # Attack 2: the covariance descriptor is dropped. The consumer states it as required, so the
    # absence is a located obligation (labelled), never a silent pass.
    dropped = deepcopy(good)
    del dropped['covariance']
    report = _hand_over_report(dropped)
    assert {'covariance.status', 'covariance.basis', 'covariance.source'} <= _fields(report['obligations'])
    assert all(row['observed'] is None for row in report['obligations'] if row['field'].startswith('covariance'))
    assert report['errors'] == []


def _compare_nothing(original):
    def compare(observed, expected, location):
        return {'errors': [], 'obligations': []}
    compare.__wrapped__ = original
    return compare


register(Mutation('M11', 'ravel.validation.semantic_composition:compare', _compare_nothing,
                  ('test_P05_a_flipped_sign_convention_is_refused_and_a_dropped_covariance_is_labelled',),
                  why='descriptors are no longer compared across an operation boundary'))


# ---------------------------------------------------------------- inert generation products

GENERATION = {'model': 'model-a', 'definitions': {'p': 'g u d u~ d~'}, 'process': 'p p > e+ e-',
              'events': 2, 'seed': 1729, 'beam_pdg': [2212, 2212],
              'run_settings': {'ebeam1': 6500, 'ebeam2': 6500, 'pdlabel': 'pdfset-a', 'lhaid': 90001}}

EVENT = """
<event>
4 1 1.0 100 0.007 0.118
2 -1 0 0 1 0 0 0 50 50 0 0 9
-2 -1 0 0 0 1 0 0 -50 50 0 0 9
11 1 1 2 0 0 30 0 40 50 0 0 9
-11 1 1 2 0 0 -30 0 -40 50 0 0 9
</event>
"""

PRODUCT = """<LesHouchesEvents version="1.0">
<header>
<MGRunCard>
1=lpp1
1=lpp2
6500=ebeam1
6500=ebeam2
pdfset-a=pdlabel
90001=lhaid
2=nevents
1729=iseed
False=use_syst
none=systematics_program
0=ickkw
</MGRunCard>
<MG5ProcCard>
import model model-a
define p = g u d u~ d~
generate p p &gt; e+ e-
</MG5ProcCard>
<slha>
BLOCK MASS
23 91.0
</slha>
</header>
<init>
2212 2212 6500 6500 0 0 90001 90001 -4 1
760 6.5 1 1
</init>
""" + EVENT * 2 + "\n</LesHouchesEvents>"


def _write_product(nc, name, text):
    path = nc.path('products', name)
    path.write_text(text)
    return path


def _audit(path, generation=GENERATION):
    from ravel.physics import scoped
    return scoped.audit_lhe(path, deepcopy(generation))


def _control_product(nc):
    result = _audit(_write_product(nc, 'control.lhe', PRODUCT))
    assert result['passed'] is True and result['events'] == 2
    assert result['recipe']['pdf_ids'] == [90001, 90001]
    assert result['sampling'] == {'events': 2, 'seed': 1729}


def _tolerating(*fragments):
    """The validator minus the named refusals: it answers a pass for a failure naming a fragment."""
    def build(original):
        def tolerant(path, generation, **kwargs):
            try:
                return original(path, generation, **kwargs)
            except ValueError as exc:
                if any(fragment in str(exc) for fragment in fragments):
                    return {'passed': True, 'events': generation['events'], 'header': {}}
                raise
        tolerant.__wrapped__ = original
        return tolerant
    return build


# ---------------------------------------------------------------- E07 executed PDF differs from approval

@case('E07', binding=INSTALLED)
def test_E07_an_executed_pdf_identifier_that_differs_from_approval_invalidates_the_product(nc):
    _control_product(nc)
    # Attack: the product was made with another PDF member (banner run card and init block agree
    # with each other, and differ from the approved generation).
    other = PRODUCT.replace('90001=lhaid', '90002=lhaid').replace('90001 90001 -4', '90002 90002 -4')
    assert other != PRODUCT and '90002 90002' in other
    path = _write_product(nc, 'other-pdf.lhe', other)
    with pytest.raises(ValueError, match=r'effective run setting differs from plan: lhaid \(90002\.0 != 90001\)'):
        _audit(path)
    # A product whose init block alone names another PDF member is refused too.
    init_only = PRODUCT.replace('90001 90001 -4', '90002 90002 -4')
    with pytest.raises(ValueError, match='LHE PDF identity differs from plan'):
        _audit(_write_product(nc, 'other-init.lhe', init_only))


register(Mutation('M10', 'ravel.physics.scoped:audit_lhe', _tolerating('lhaid', 'PDF identity'),
                  ('test_E07_an_executed_pdf_identifier_that_differs_from_approval_invalidates_the_product',),
                  why='the generation audit stops comparing the executed PDF member with the approved one'))


# ---------------------------------------------------------------- E10 beam energy or seed in the banner

@case('E10', binding=INSTALLED)
def test_E10_a_beam_energy_or_seed_changed_only_in_the_retained_banner_invalidates_the_product(nc):
    _control_product(nc)
    # Attack 1: the beam energy differs in the retained banner only (the init block is untouched).
    energy = PRODUCT.replace('6500=ebeam1', '7000=ebeam1')
    assert energy != PRODUCT
    with pytest.raises(ValueError, match=r'effective run setting differs from plan: ebeam1 \(7000\.0 != 6500\)'):
        _audit(_write_product(nc, 'other-energy.lhe', energy))
    # Attack 2: the actual seed differs in the retained banner only.
    seed = PRODUCT.replace('1729=iseed', '1730=iseed')
    assert seed != PRODUCT
    with pytest.raises(ValueError, match=r'effective run setting differs from plan: iseed \(1730\.0 != 1729\)'):
        _audit(_write_product(nc, 'other-seed.lhe', seed))


register(Mutation('M10', 'ravel.physics.scoped:audit_lhe', _tolerating('ebeam', 'iseed', 'beam energies'),
                  ('test_E10_a_beam_energy_or_seed_changed_only_in_the_retained_banner_invalidates_the_product',),
                  why='the generation audit stops comparing the executed beam energy and seed with the plan'))


# ---------------------------------------------------------------- E13 multiweight product

@case('E13', binding=INSTALLED)
def test_E13_a_multiweight_product_is_rejected_by_the_single_weight_audit(nc):
    _control_product(nc)
    # Attack 1: each event carries named alternative weights.
    named = PRODUCT.replace('</event>', "<rwgt><wgt id='alt-1'>0.9</wgt><wgt id='alt-2'>1.1</wgt></rwgt></event>")
    assert named.count('<rwgt>') == 2
    with pytest.raises(ValueError, match='reweighted LHE is outside the uniform LO contract'):
        _audit(_write_product(nc, 'named-weights.lhe', named))
    # Attack 2: the nominal weights differ between events.
    varied = PRODUCT.replace('4 1 1.0 100', '4 1 2.0 100', 1)
    assert varied != PRODUCT
    with pytest.raises(ValueError, match='variable nominal weights are not supported'):
        _audit(_write_product(nc, 'varied-weights.lhe', varied))


register(Mutation('M10', 'ravel.physics.scoped:audit_lhe', _tolerating('reweighted LHE', 'variable nominal weights'),
                  ('test_E13_a_multiweight_product_is_rejected_by_the_single_weight_audit',),
                  why='the generation audit accepts multiweight and variable-weight products'))


# ---------------------------------------------------------------- E08 invisible-state membership

SPECTRUM = """BLOCK MASS
 1000101 500.0
 1000102 300.0
 1000103 150.0
 1000104 100.0
DECAY 1000101 1.0
   1.0 2 1000102 11
DECAY 1000102 1.0
   1.0 2 1000103 1000104
"""


@case('E08', binding=INSTALLED)
def test_E08_a_removed_invisible_daughter_fails_the_census_closure(nc):
    from ravel.physics import detector_card
    slha = nc.path('model', 'spectrum.slha')
    slha.write_text(SPECTRUM)
    model = {'invisible': [1000103, 1000104], 'slha': str(slha), 'produced': [1000101]}
    # Positive control: both stable daughters of the chain are declared invisible.
    census = detector_card.invisible_census(deepcopy(model), nc.root)
    assert census['invisible'] == [1000103, 1000104]
    assert census['evidence']['slha']['stable_bsm'] == [1000103, 1000104]
    # Attack: one declared invisible daughter is removed from this variant; the headline
    # (produced) states and the spectrum are unchanged.
    variant = dict(deepcopy(model), invisible=[1000103])
    with pytest.raises(ValueError) as refusal:
        detector_card.invisible_census(variant, nc.root)
    text = str(refusal.value)
    assert text.startswith('invisible-state census refused')
    assert 'neither declared invisible nor declared visible: 1000104' in text


def _census_without_refusal(original):
    def census(model, base=None):
        try:
            return original(model, base)
        except ValueError:
            return {'invisible': sorted(abs(p) for p in model['invisible']), 'visible_stable': [], 'evidence': {}}
    census.__wrapped__ = original
    return census


register(Mutation('M10', 'ravel.physics.detector_card:invisible_census', _census_without_refusal,
                  ('test_E08_a_removed_invisible_daughter_fails_the_census_closure',),
                  why='the invisible-state census no longer refuses an undeclared stable state'))


# ---------------------------------------------------------------- E14 routine presence is not qualification

def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value):
    from ravel.workflow import analysis_admission
    return analysis_admission._digest(value)


def _admission_specification(nc):
    """An invented routine-reproduction admission: every bound check receipt, plus the reference comparison."""
    from ravel.workflow import analysis_admission as admission
    root = nc.path('admission', 'keep').parent
    artifacts = []
    for name, role in (('routine', 'source'), ('events', 'events'), ('document', 'paper')):
        path = root / (name + '.txt')
        path.write_text('invented admission control ' + name + '\n')
        artifacts.append({'id': name, 'path': path.name, 'sha256': _sha(path), 'role': role})
    spec = {'schema_version': 1, 'kind': 'analysis_specification', 'analysis_id': 'uncatalogued:routine-a',
            'implementation': {'framework': 'framework-a', 'routine': 'Routine', 'artifact': 'routine'},
            'request': {'purpose': 'reference-reproduction', 'input_level': 'particle', 'target_level': 'particle',
                        'scope': {'model': 'model-a', 'era': 'era-a'}},
            'artifacts': artifacts, 'subjects': ['routine', 'events', 'document'],
            'definitions': [{'id': 'cut', 'role': 'selection', 'definition': 'pT strictly greater than 30 GeV',
                             'artifact': 'document', 'locator': 'line 1'}],
            'outputs': [{'name': 'SR', 'quantity': 'yield', 'unit': 'events', 'normalization': 'absolute',
                         'representation': 'integrated', 'weight': 'nominal', 'definition': 'cut', 'bin': None}],
            'checks': []}

    def bind(identity, value):
        path = root / (identity + '.json')
        path.write_text(json.dumps(value, indent=2))
        spec['artifacts'].append({'id': identity, 'path': path.name, 'sha256': _sha(path), 'role': 'check'})

    for kind in admission.requirements(spec):
        if kind == 'reference':
            continue
        bind('check-' + kind, {
            'schema_version': 1, 'kind': 'analysis_check_receipt', 'check': kind,
            'analysis_id': spec['analysis_id'], 'scope_sha256': _digest(spec['request']['scope']),
            'request_sha256': _digest(spec['request']),
            'implementation_sha256': _digest(spec['implementation']),
            'subjects': admission._binding(spec), 'definitions_sha256': _digest(spec['definitions']),
            'outputs_sha256': _digest(spec['outputs']), 'status': 'passed',
            'producer': {'identity': 'checker-' + kind, 'context_id': 'context-' + kind, 'role': 'checker'},
            'method': 'invented structural control', 'limitations': ['invented control only']})
        spec['checks'].append({'kind': kind, 'method': 'receipt', 'artifact': 'check-' + kind})

    def values(number, prediction):
        return {'schema_version': 1, 'kind': 'analysis_reference_values', 'analysis_id': spec['analysis_id'],
                'scope_sha256': _digest(spec['request']['scope']), 'request_sha256': _digest(spec['request']),
                'implementation_sha256': _digest(spec['implementation']),
                'definitions_sha256': _digest(spec['definitions']),
                'subjects': admission._binding(spec) if prediction else {'document': spec['artifacts'][2]['sha256']},
                'source': 'invented prediction' if prediction else 'invented independent arithmetic',
                'outputs': [{'basis': deepcopy(spec['outputs'][0]), 'value': number}]}

    bind('prediction', values(4, True))
    bind('reference', values(4, False))
    spec['checks'].append({'kind': 'reference', 'method': 'comparison', 'prediction': 'prediction',
                           'reference': 'reference', 'criteria': {'rtol': 0, 'atol': 0}})
    return root, spec


def _assess(root, spec):
    from ravel.workflow import analysis_admission
    (root / 'analysis.json').write_text(json.dumps(spec, indent=2))
    return analysis_admission.assess({'specification': 'analysis.json'}, root)


@case('E14', binding=INSTALLED)
def test_E14_removing_the_bound_qualification_report_keeps_the_routine_unadmitted(nc):
    root, spec = _admission_specification(nc)
    # Positive control: with the bound reference comparison present, the evidence census is complete.
    admitted = _assess(root, spec)
    assert 'reference' in admitted['required_checks']
    assert admitted['obligations'] == [] and admitted['status'] == 'evidence-complete'
    assert admitted['evidence_complete'] is True
    # Attack: the bound qualification report (prediction, reference and their comparison) is
    # removed; the routine stays among the bound subjects, installed and unchanged.
    attacked = deepcopy(spec)
    attacked['checks'] = [c for c in attacked['checks'] if c['kind'] != 'reference']
    attacked['artifacts'] = [a for a in attacked['artifacts'] if a['id'] not in ('prediction', 'reference')]
    assert attacked['implementation'] == spec['implementation'] and 'routine' in attacked['subjects']
    report = _assess(root, attacked)
    assert report['obligations'] == [{'kind': 'reference', 'status': 'unknown'}]
    assert report['status'] == 'blocked' and report['evidence_complete'] is False
    assert report['admitted_claim'] == 'unresolved scoped evidence'
    assert report['physics_validated'] is False


def _without_reference(original):
    def requirements(specification):
        return [kind for kind in original(specification) if kind != 'reference']
    requirements.__wrapped__ = original
    return requirements


register(Mutation('M10', 'ravel.workflow.analysis_admission:requirements', _without_reference,
                  ('test_E14_removing_the_bound_qualification_report_keeps_the_routine_unadmitted',),
                  why='admission stops requiring a qualification comparison for a reproduction claim'))


# ---------------------------------------------------------------- E17 likelihood bins unpaired with yields

def _pairing_report(workspace_bins):
    from ravel.validation import semantic_composition
    yields = _quantity('event_count')
    workspace = dict(_quantity('statistical_model'), bin_ids=list(workspace_bins),
                     auxiliary_information=['observation-a', 'observation-b'])
    plan = {'nodes': [{'id': 'N1', 'operation': 'signal-template'}],
            'inputs': [{'id': 'I1', 'provides': {'kind': 'event_count', 'require': {}}},
                       {'id': 'I2', 'provides': {'kind': 'statistical_model', 'require': {}}}],
            'edges': [{'id': 'E1', 'from': {'ref': 'I1', 'slot': 'provided'}, 'to': {'ref': 'N1', 'slot': 'yields'},
                       'require': {}},
                      {'id': 'E2', 'from': {'ref': 'I2', 'slot': 'provided'}, 'to': {'ref': 'N1', 'slot': 'workspace'},
                       'require': {}}]}
    artifacts = {'E1': {'quantity': yields}, 'E2': {'quantity': workspace}}
    return semantic_composition.plan_report(plan, _registry(), artifacts)


@case('E17', binding=INSTALLED)
def test_E17_permuted_region_labels_with_equal_lengths_are_refused_before_a_likelihood_result(nc):
    # Positive control: workspace bins in the yields' order pair without error or obligation.
    assert _pairing_report(['region-a:0', 'region-b:0']) == {'errors': [], 'obligations': []}
    # Attack: the same labels, the same length, in the other order.
    report = _pairing_report(['region-b:0', 'region-a:0'])
    unpaired = [row for row in report['errors'] if row['field'] == 'bin_ids']
    assert unpaired, 'permuted bin labels must be a typed pairing error'
    assert all(row['observed'] == ['region-b:0', 'region-a:0'] for row in unpaired)
    assert all(len(row['observed']) == 2 for row in unpaired)


def _relations_nothing(original):
    def relations(rows, rules, location):
        return {'errors': [], 'obligations': []}
    relations.__wrapped__ = original
    return relations


register(Mutation('M10', 'ravel.validation.semantic_composition:relations', _relations_nothing,
                  ('test_E17_permuted_region_labels_with_equal_lengths_are_refused_before_a_likelihood_result',),
                  why='quantity relations between a signal template and its workspace are no longer compared'))


# ---------------------------------------------------------------- E18 normalization order

CHECK_ID = 'check:physics.normalization_ledger.check'


def _ledger(k=None, target=None):
    ledger = {'schema_version': 1, 'sample': 'sample-a',
              'luminosity': {'value': 10.0, 'unit': 'fb^-1', 'source': 'declared in the fixture'},
              'sigma': {'value': 1.0, 'unit': 'pb', 'order': 'LO', 'tool': 'tool-a', 'pdf': 'pdfset-a',
                        'scales': 'scale-a', 'process_basis': 'basis-a', 'source': 'fixture-table-a'},
              'generated': {'sumw': 100.0, 'sumw2': 100.0},
              'selected': {'region-a': {'sumw': [10.0, 5.0], 'sumw2': [10.0, 5.0]}},
              'bin_convention': 'per-bin'}
    if k is not None:
        ledger['k'] = {'value': 1.4, 'applied_once': True, **k}
    if target is not None:
        ledger['target_normalization'] = target
    return ledger


def _run_ledger_check(nc, name, ledger):
    from ravel.workflow import run_validator_checks
    run = nc.root / name
    nc.write_json(f'{name}/inputs/normalization_ledger.json', ledger)
    workspace = nc.path(name, 'workspace', 'keep').parent
    value = run_validator_checks.RunCheckInput(run, {'check_inputs': {}}, workspace)
    result = run_validator_checks.run(CHECK_ID, value)
    assert result['validator_executed'] is True
    return result


def _basis(order):
    return {'order': order, 'final_states': ['pair-a'], 'multiplicities': [2], 'generation_cuts': 'none',
            'pdf': 'pdfset-a'}


@case('E18', binding=INSTALLED)
def test_E18_an_invented_flat_factor_in_place_of_a_higher_order_rate_is_flagged(nc):
    # Positive control: a leading-order rate with a correction whose bases state their own orders.
    control = _run_ledger_check(nc, 'control', _ledger(k={'numerator_basis': _basis('NLO'),
                                                          'denominator_basis': _basis('LO')}))
    assert control['status'] == 'passed' and control['diagnostics']['failures'] == []
    # Attack 1: the missing higher-order rate is replaced by a flat factor whose denominator
    # basis claims an order the applied cross section does not have.
    invented = _run_ledger_check(nc, 'invented', _ledger(k={'numerator_basis': _basis('NLO+NLL'),
                                                            'denominator_basis': _basis('NLO')}))
    assert invented['status'] == 'failed'
    assert [row['code'] for row in invented['diagnostics']['failures']] == ['k_basis_mismatch']
    assert 'denominator order NLO is not the order of the applied cross section (LO)' in \
        invented['diagnostics']['failures'][0]['explanation']
    # Attack 2: the target states a higher order and no correction is supplied; the lower-order
    # normalization is not passed off as the target, it is raised for the check-in.
    unresolved = _run_ledger_check(nc, 'unresolved', _ledger(target={'order': 'NLO+NLL', 'locator': 'table-a'}))
    assert [row['code'] for row in unresolved['diagnostics']['warnings']
            if row['code'] == 'order_differs_from_target'] == ['order_differs_from_target']
    assert unresolved['diagnostics']['checkin2_items'] == [
        'Normalization order LO differs from the target publication (NLO+NLL, table-a).']


register(Mutation('M10', 'ravel.physics.normalization_ledger:_basis_mismatch', returns(list),
                  ('test_E18_an_invented_flat_factor_in_place_of_a_higher_order_rate_is_flagged',),
                  why='the normalization ledger stops comparing correction-factor bases with the applied rate'))
