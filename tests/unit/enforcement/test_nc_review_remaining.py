"""Fifteen real review/research guards with independently observed inert effects.

Each report uses a real protected RunStore, ledger and qualified sink publication.
The observations are unqualified fixtures, never credited scientific review.
"""
from copy import deepcopy

from nc_cases import CONTROLLER, case
from nc_review_entry import ReviewEntry
from nc_mutations import Mutation, register
import nc_review_peer as peer


def _observe(outcome, *, errors=(), notices=(), disclosures=()):
    assert outcome.source_gap is None, outcome.source_gap
    assert outcome.errors == tuple(errors), outcome.report
    assert outcome.notices == tuple(notices), outcome.report
    assert outcome.disclosures == tuple(disclosures), outcome.report
    assert outcome.allowed is (not errors)
    assert outcome.effects == (0 if errors else 1)
    assert outcome.ending['reason'] == (errors or notices or disclosures or
        ('production component guard permitted inert effect',))[0]
    assert outcome.receipt['qualified'] and not outcome.receipt['accepted']
    assert outcome.ending['scientific_claims_adopted'] == []
    assert outcome.report['fixture_models']['qualification'] == 'unqualified'
    assert all(peer.CANARY.encode() not in raw for raw in outcome.published.values())


def _run(nc, row, check, mutate, *, errors=(), notices=(), clean_disclosures=(), disclosures=(), prepare=None):
    entry = ReviewEntry(nc, row)
    clean = peer.fixture()
    if prepare:
        prepare(clean)
    control = entry.run(getattr(peer, 'real_' + check), clean)
    _observe(control, disclosures=clean_disclosures)
    attacked = deepcopy(clean)
    mutate(attacked)
    negative = entry.run(getattr(peer, 'real_' + check), attacked)
    _observe(negative, errors=errors, notices=notices, disclosures=disclosures)
    return control, negative


@case('V04', binding=CONTROLLER)
def test_V04_conclusion_filename_is_screened_before_review_credit(nc):
    control, negative = _run(nc, 'V04', 'packet', lambda p: p['packet']['inputs'].append('summary.md'),
         errors=('packet_input_forbidden',))
    assert control.reads == 1 and negative.reads == 0


@case('V05', binding=CONTROLLER)
def test_V05_downgraded_rdj_class_is_recomputed_before_authorization(nc):
    _run(nc, 'V05', 'rdj', lambda p: p['action'].update(declared_class='R1'),
         errors=('consequence_class_downgraded',))


@case('V06', binding=CONTROLLER)
def test_V06_critic_and_verifier_cannot_share_a_session(nc):
    _run(nc, 'V06', 'cycle', lambda p: p['seats'][1].update(session_id='critic'), errors=('session_reused',))


@case('V07', binding=CONTROLLER)
def test_V07_unchanged_repair_bytes_receive_no_progress_credit(nc):
    control, negative = _run(nc, 'V07', 'repair', lambda p: p['repair'].update(after=p['repair']['before']),
         errors=('repair_no_progress',))
    assert control.diagnostics['redos_consumed'] == negative.diagnostics['redos_consumed'] == 1


@case('V09', binding=CONTROLLER)
def test_V09_verbal_crosscheck_without_broker_receipt_is_qualified(nc):
    _run(nc, 'V09', 'crosscheck', lambda p: p['crosscheck'].update(receipt=None),
         notices=('crosscheck_execution_missing', 'method_independence_unverified'))


@case('V10', binding=CONTROLLER)
def test_V10_missing_operation_validator_yields_not_certified(nc):
    _run(nc, 'V10', 'certify', lambda p: p['certification'].update(validator=None),
         notices=('operation_validator_missing', 'NOT CERTIFIED'))


@case('P01', binding=CONTROLLER)
def test_P01_unreviewed_baseline_na_cannot_cross_stage_edge(nc):
    _run(nc, 'P01', 'baseline', lambda p: p['stages'][2].update(status='not_applicable'),
         errors=('baseline_review_required',))


@case('P02', binding=CONTROLLER)
def test_P02_stream_b_cannot_read_stream_a_before_barrier(nc):
    control, negative = _run(nc, 'P02', 'idea_barrier', lambda p: p['ideas']['reads'].append('stream-a-proposal'),
         errors=('idea_stream_barrier_closed',))
    assert control.diagnostics['guard_reads'] == 1 and negative.diagnostics['guard_reads'] == 0


@case('P03', binding=CONTROLLER)
def test_P03_experiment_without_own_ci1_cannot_launch(nc):
    _run(nc, 'P03', 'child_authority', lambda p: p['child'].update(ci1=None), errors=('child_ci1_required',))


@case('C34', binding=CONTROLLER)
def test_C34_worker_authored_preregistration_has_no_launch_credit(nc):
    _run(nc, 'C34', 'preregistration', lambda p: p['preregistration'].update(producer='worker'),
         errors=('producer_preregistration_required',))


@case('E02', binding=CONTROLLER)
def test_E02_forbidden_inventory_provider_is_refused_before_probe(nc):
    control, negative = _run(nc, 'E02', 'inventory', lambda p: p['inventory'].update(requested='excluded-provider'),
         errors=('inventory_provider_restricted',))
    assert control.diagnostics['probe_calls'] == 1 and negative.diagnostics['probe_calls'] == 0


@case('CF09', binding=CONTROLLER)
def test_CF09_held_out_workspace_artifact_never_enters_packet(nc):
    control, negative = _run(nc, 'CF09', 'packet', lambda p: p['packet']['inputs'].append('held_out/source.txt'),
         errors=('packet_input_forbidden',), prepare=lambda p: p['packet'].update(role='ml-trainer'))
    assert control.reads == 1 and negative.reads == 0


@case('XF04', binding=CONTROLLER)
def test_XF04_same_family_distinct_stage_sessions_proceed(nc):
    # One model change removes cross-family diversity but preserves actor/session separation.
    clean = peer.fixture(); clean['seats'][1]['model'] = 'gpt-5'
    entry = ReviewEntry(nc, 'XF04')
    _observe(entry.run(peer.real_stage_seats, clean))
    attacked = deepcopy(clean); attacked['seats'][1]['model'] = 'claude-x'
    _observe(entry.run(peer.real_stage_seats, attacked), disclosures=('separate session, same model family',))


@case('XF06', binding=CONTROLLER)
def test_XF06_single_author_family_is_disclosed_without_launch_hold(nc):
    _run(nc, 'XF06', 'author_diversity', lambda p: p.update(author_families=['claude', 'claude']),
         disclosures=('single model family',))


@case('R06', binding=CONTROLLER)
def test_R06_prose_claim_cannot_replace_nine_stage_research_join(nc):
    _run(nc, 'R06', 'research_join', lambda p: p['stages'].pop(),
         errors=('research_stage_population_incomplete',))


# Production mutations disable the exact consumer each real probe invokes. They
# remain mandatory against the current production consumers.
from nc_mutations import CONTROLLER as REAL_MUTATION, passes_through


def _declared_class(original):
    def disabled(root, gate, action, facts=None, declared=None):
        return ((declared or {}).get('class', 'R1'), {})
    return disabled


def _progress_always(original):
    def disabled(*args, **kwargs):
        report = deepcopy(original(*args, **kwargs))
        for item in report['finding_progress']:
            for history in item['history']:
                history['progress'] = True
        return report
    return disabled


def _validator_attestation_ignored(original):
    def register_action(self, name, handler, **options):
        if options.get('derivation') == 'registered_validator':
            prior = handler
            def handler(args):
                return {**prior(args), 'validator_executed': True}
        return original(self, name, handler, **options)
    return register_action


def _unseal(original):
    def call(self, request):
        season = self.season
        try:
            self.season = None
            return original(self, request)
        finally:
            self.season = season
    return call


def _inventory_unrestricted(original):
    def call(self, request):
        action = request['action']
        if action not in self.allowed_actions:
            self.allowed_actions.add(action)
            self.actions[action] = next(iter(self.actions.values()))
        return original(self, request)
    return call


for mechanism, target, replacement, rows in (
    ('M08', 'ravel.workflow.review_projection:screen_inputs',
     lambda original: lambda root, role, paths: (list(paths), []), ('V04', 'CF09')),
    ('M21', 'ravel.workflow.rdj_loop:compute_class', _declared_class, ('V05',)),
    ('M06', 'ravel.workflow.review_independence:seat_refusal',
     lambda original: lambda *a, **k: None, ('V06',)),
    ('M17', 'ravel.workflow.physics_review:correction_progress', _progress_always, ('V07',)),
    ('M10', 'ravel.workflow.broker:Broker.register', _validator_attestation_ignored, ('V09',)),
    ('M15', 'ravel.controller.step.validate:run_validators',
     passes_through(lambda report, *a, **k: {**report, 'passed': True}), ('V10',)),
    ('M01', 'ravel.workflow.research_protocol:methodology_status',
     lambda original: lambda root: {'pending': []}, ('R06',)),
    ('M01', 'ravel.workflow.research_protocol:gate_errors',
     lambda original: lambda *a, **k: [], ('P01',)),
    ('M08', 'ravel.workflow.broker:Broker.call', _unseal, ('P02',)),
    ('M04', 'ravel.workflow.workflow_state:verify_approval',
     lambda original: lambda *a, **k: [], ('P03',)),
    ('M09', 'ravel.workflow.research_launch:verify',
     lambda original: lambda *a, **k: [], ('C34',)),
    ('M07', 'ravel.workflow.broker:Broker.call', _inventory_unrestricted, ('E02',)),
    ('M20', 'ravel.workflow.review_independence:family_relation',
     lambda original: lambda models: 'different', ('XF04',)),
    ('M20', 'ravel.workflow.spawn_rows:family_label',
     lambda original: lambda families: None, ('XF06',)),
):
    register(Mutation(mechanism, target, replacement, rows, binding=REAL_MUTATION,
                      why='disable the production content guard reached by the mandatory real probe'))
