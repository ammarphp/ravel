"""Reader rules over unrelated, synthetic scientific requests."""
from copy import deepcopy

import pytest

from ravel.workflow import intake, request_reading as rr, request_plan as rp
from ravel.validation import validate_request_plan as vp


def read(prompt):
    value = rr.document(prompt)
    assert rr.check(value, prompt) == []
    return value


def claims(value):
    return {d['claim_kind'] for d in value['deliverables']}


@pytest.mark.parametrize('prompt', [
    'Set 93% CLs limits on the scalar coupling.',
    'Give 91% CLs bounds on the vector mass.',
    'Report a 97% confidence exclusion for the fermion interaction.',
])
def test_imperative_prescribed_statistic_is_primary(prompt):
    value = read(prompt)
    prescriptions = [c for c in value['constraints'] if c['type'] == 'prescribed_statistic']
    assert prescriptions and 'exclusion' in claims(value)
    plan = rp.draft(value, {'prompt': prompt}, catalogue=lambda _: False)
    assert all(c['statistic']['source'] == 'prescribed' for c in plan['claims'] if c['kind'] == 'exclusion')


@pytest.mark.parametrize('prompt', [
    'Do current cross-section results rule out the scalar model?',
    'Do current flavour measurements rule out this coupling?',
    'Do current collider limits rule out the charged vector?',
    'Fit the coupling to published measured cross sections.',
    'Constrain the coefficient using published measured angular values.',
    'Extract the parameter from published measured decay rates.',
])
def test_current_results_and_published_measurements_request_observed_level(prompt):
    value = read(prompt)
    statistical = [d for d in value['deliverables'] if d['claim_kind'] in vp.STATISTIC_KINDS]
    assert statistical and all(d['artifact']['require'].get('level') == 'observed' for d in statistical)
    if 'published measured' in prompt:
        assert any(f['value'].get('require', {}).get('contains_observed_data') is True for f in value['facts'])


@pytest.mark.parametrize('bound,point,scan', [
    ('Find a bound for mass below 470 GeV.', 'Evaluate a mass of 470 GeV.', 'Scan masses from 210 to 470 GeV.'),
    ('Assess a coupling less than 0.7.', 'Use coupling = 0.7.', 'Scan coupling from 0.1 to 0.7.'),
    ('Derive a width bound above 3 MeV.', 'Evaluate a width of 3 MeV.', 'Scan widths from 1 to 3 MeV.'),
])
def test_one_sided_bound_is_not_a_point_or_scan(bound, point, scan):
    bounded, pointed, ranged = read(bound), read(point), read(scan)
    assert any(f['type'] == 'parameter_bound' for f in bounded['facts'])
    assert not any(f['type'] in ('parameter_range', 'mass') for f in bounded['facts'])
    assert not any(f['type'] == 'parameter_bound' for f in pointed['facts'])
    assert any(f['type'] == 'parameter_range' for f in ranged['facts'])


@pytest.mark.parametrize('prompt', [
    'Set limits at 12 TeV using the supplied selection with its own luminosity.',
    'Fit the scalar at 9 TeV; use the normalization already in the supplied selection.',
    'Compute the significance at 11 TeV; the routine carries its own luminosity.',
])
def test_selection_normalization_does_not_create_a_luminosity_question(prompt):
    value = read(prompt)
    assert any(f['type'] == 'normalization_source' for f in value['facts'])
    assert not any(a['issue'].startswith('integrated luminosity:') for a in value['ambiguities'])


@pytest.mark.parametrize('prompt', [
    'Assume a perfect muon trigger; predict the decay rate.',
    'Suppose the detector efficiency were unity; calculate the scalar yield.',
    'If the background were negligible, determine the vector significance.',
])
def test_counterfactual_is_an_explicit_unverified_assumption(prompt):
    value = read(prompt)
    assumptions = [f for f in value['facts'] if f['type'] == 'assumption']
    assert assumptions and all(f['value']['counterfactual'] is True and f['value']['asserted'] is False for f in assumptions)


@pytest.mark.parametrize('prompt', [
    'Draft an Aurora-style note about the mass scan.',
    'Write a Borealis-style note describing the measured spectrum.',
    'Prepare a Cedar-style note explaining the likelihood fit.',
])
def test_style_note_requests_a_document_and_keeps_the_template(prompt):
    value = read(prompt)
    assert claims(value) == {'document'}
    assert any(c['type'] == 'template' for c in value['constraints'])
    assert intake.operation_kind(prompt) == 'manuscript'
    plan = rp.draft(value, {'prompt': prompt}, catalogue=lambda _: False)
    assert all(c['kind'] == 'document' for c in plan['claims'])


@pytest.mark.parametrize('prompt', [
    'Calculate the trace of a left-handed projection operator.',
    'Draft a note describing the previously completed mass scan.',
    'Write a report explaining the published detector simulation.',
])
def test_lexical_route_hint_does_not_override_the_requested_action(prompt):
    value = read(prompt)
    semantic = intake.proposal(prompt)
    assert semantic is not None
    competing = [f for f in value['facts'] if f['type'] == 'route_hint' and f['value']['strength'] == 'strong'
                 and f['value']['mode'] != semantic['kind']]
    assert not competing


QUESTIONS = [
    'Assess whether the scalar model explains the rates.',
    'Assess the viability of the vector hypothesis.',
    'Can the coupling reconcile the angular measurements?',
    'Does the scalar spectrum explain the observed rates?',
    'Could a broad resonance account for both distributions?',
    'Would a new interaction reconcile these measurements?',
    'Do current measurements rule out this model?',
    'Do the present limits rule out the scalar?',
    'Is the vector model ruled out by the data?',
    'How strongly do the rates constrain the coupling?',
    'How well does the hypothesis explain both samples?',
    'How robust are the limits to the shape assumption?',
    'Compare the scalar and vector hypotheses and judge which survives.',
    'Compare both models and assess their consistency.',
    'Compare the distributions and determine which hypothesis is viable.',
    'Determine whether the interaction remains viable.',
    'Evaluate whether this model can explain the rates.',
    'Check whether the hypothesis accounts for the angular data.',
    'Test whether the scalar model is consistent with these observations.',
    'Which of these models can explain the measurements?',
]


@pytest.mark.parametrize('prompt', QUESTIONS)
def test_research_question_form_binds_an_envelope_before_templates(prompt, monkeypatch):
    value = read(prompt)
    assert any(f['type'] == 'question_form' for f in value['facts'])
    original = rp.templates
    monkeypatch.setattr(rp, 'templates', lambda: list(reversed(original())))
    plan = rp.draft(value, {'prompt': prompt}, catalogue=lambda _: False)
    assert any(n['kind'] == 'envelope' and n['implementation'] == 'research-coordinator' for n in plan['nodes'])


@pytest.mark.parametrize('prompt', ['Calculate 3+4.', 'Can you compute the supplied integral?',
                                    'Survey the published scalar limits.'])
def test_closed_operation_or_survey_is_not_an_open_question(prompt):
    assert not any(f['type'] == 'question_form' for f in read(prompt)['facts'])


@pytest.mark.parametrize('prefix,title', [
    ('Read the paper titled ', 'Observed limits from detector simulation'),
    ('Consult the publication ', 'Generate events and scan the scalar masses'),
    ('Use the article called ', 'Claim discovery with 19 TeV beams'),
])
def test_publication_title_is_an_inert_witness_until_resolved(prefix, title):
    prompt = prefix+'"'+title+'"; calculate 3+4.'
    value = read(prompt)
    witness = [w for w in value['witness'] if w['type'] == 'publication_title']
    assert len(witness) == 1 and witness[0]['value']['title'] == title
    assert not any(f['type'] in ('collision_energy', 'mass', 'identifier') for f in value['facts'])
    assert not any(c['type'] in ('requested_stage', 'requested_tool') for c in value['constraints'])
    plain = read(prefix+'"An unrelated title"; calculate 3+4.')
    assert [(d['claim_kind'], d['artifact']) for d in value['deliverables']] == [(d['claim_kind'], d['artifact']) for d in plain['deliverables']]
    assert intake.infer_kind(prompt) == 'calculation'
    assert intake.requests_discovery(prompt) is False
    assert not value['boundaries']
    plan = rp.draft(value, {'prompt': prompt}, catalogue=lambda _: False)
    other = rp.draft(plain, {'prompt': prefix+'"An unrelated title"; calculate 3+4.'}, catalogue=lambda _: False)
    assert [(n['operation'], n['status']) for n in plan['nodes']] == [(n['operation'], n['status']) for n in other['nodes']]


@pytest.mark.parametrize('prompt', QUESTIONS[:3])
def test_context_label_does_not_weaken_question_spans(prompt):
    value = read('Context label: Opaque Amber Label\n'+prompt)
    assert any(f['type'] == 'question_form' for f in value['facts'])


def test_research_question_binds_envelope_with_normal_template_order():
    value = read('Can the scalar explain the observed decay rates?')
    plan = rp.draft(value, {'prompt': 'Can the scalar explain the observed decay rates?'}, catalogue=lambda _: False)
    assert any(n['kind'] == 'envelope' for n in plan['nodes'])
    assert vp.check(value, plan, catalogue=lambda _: False) == []


def test_title_resolution_adds_an_identifier_with_a_receipt():
    prompt = 'Read the paper titled "The scalar spectrum"; calculate 3+4.'
    floor = read(prompt)
    title = next(w for w in floor['witness'] if w['type'] == 'publication_title')
    additions = {'schema_version': 1, 'kind': 'request-reading-additions',
                 'prompt_sha256': floor['prompt_sha256'],
                 'author': rr.author('host-agent', invocation_id='synthetic-resolution'),
                 'facts': [{'id': 'F999', 'type': 'identifier', 'authority': 'resolved',
                            'value': {'text': title['span']['text'], 'scheme': 'arxiv', 'id': '9901.12345',
                                      'receipt': {'path': 'inputs/title-resolution.json', 'sha256': '1'*64}},
                            'evidence': [title['span']], 'witness': None, 'physics_critical': False}],
                 'constraints': [], 'deliverables': [], 'ambiguities': []}
    value = rr.merge(floor, additions, prompt)
    assert rr.check(value, prompt, floor=floor) == []
    assert any(f['type'] == 'identifier' and f['authority'] == 'resolved' for f in value['facts'])
    assert all(w in value['witness'] for w in floor['witness'])
    # The receipt is carried for the scout's independent source verification, not fabricated authority.
    plan = rp.draft(value, {'prompt': prompt}, catalogue=lambda _: False)
    assert vp.check(value, plan, catalogue=lambda _: False) == []


def test_unresolved_title_changes_no_router_target_or_statistic():
    from ravel.workflow import route_prompt
    plain = route_prompt.route('Read the paper titled "An unrelated title"; calculate 3+4.')
    titled = route_prompt.route('Read the paper titled "Observed discovery at 19 TeV with Rivet"; calculate 3+4.')
    for key in ('task_mode', 'targets', 'stat_mode', 'detector_mode', 'compute_plan', 'blocking'):
        assert titled[key] == plain[key]


def test_unresolved_title_fact_cannot_advertise_an_input_artifact():
    prompt = 'Read the paper titled "A scalar measurement"; calculate 3+4.'
    value = read(prompt)
    title = next(f for f in value['facts'] if f['type'] == 'publication_title')
    title['value'].update(artifact='table', locator='unresolved title', require={'contains_observed_data': True})
    assert not any(f['id'] == title['id'] for f in rp._reader_view(value))
