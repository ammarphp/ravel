"""Intake coverage, kind-keyed handoff routes, declared-metadata suggestions and in-place resolution.

Prompts here are independent paraphrases written for these behaviours. They are
not taken from any evaluation battery.
"""
import synthetic_identifiers as syn
import hashlib
import json
from pathlib import Path

import pytest

from ravel import cli
from ravel.validation.validate_task_contract import load_contract, validate
from ravel.workflow import capability_routing as cr, intake, route_prompt
from ravel.workflow import scientific_autonomy as autonomy
from shipped_catalogue import shipped_operations


def initiate(tmp_path, prompt, name='run', interpretation=None):
    output = tmp_path / name
    args = ['initiate', '--prompt', prompt, '--out', str(output)]
    if interpretation is not None:
        path = tmp_path / (name + '-intent.json')
        path.write_text(json.dumps(interpretation))
        args += ['--interpretation', str(path)]
    return cli.main(args), output


def interpretation(prompt, kind, **extra):
    return {'schema_version': 1, 'prompt_sha256': intake.prompt_hash(prompt), 'kind': kind,
            'objective': prompt, 'requested_outputs': [prompt],
            'evidence': [{'start': 0, 'end': len(prompt), 'text': prompt}], 'unresolved': [], **extra}


# ------------------------------------------------------------- handoff routes

@pytest.mark.parametrize('prompt,route', [
    (('Reproduce Figure 4 of ' + syn.analysis(380) + ' for wino-like charginos.'), 'checkin'),
    ('Survey which published searches bear on a light leptophobic Z prime.', 'checkin'),
    ('Construct a summary plot of published limits on a heavy scalar decaying to top pairs.', 'checkin'),
    ('Investigate whether a long-lived axion-like particle could explain displaced-vertex anomalies.', 'research'),
    ('Develop a new jet-tagging method for boosted dark showers and benchmark it against standard taggers.', 'research'),
    ('Calculate the partial width of a 2 TeV vector boson decaying to quarks for unit coupling.', 'calculation'),
])
def test_execution_handoff_follows_the_documented_step_for_each_kind(tmp_path, prompt, route):
    code, output = initiate(tmp_path, prompt)
    assert code == 0
    handoff = json.loads((output / 'inputs/intake_handoff.json').read_text())
    assert handoff['route'] == route
    apis = ' '.join(handoff['planning_apis'])
    if route == 'checkin':
        assert 'resource_census' in apis and 'validate_checkin' in apis
        assert 'research_orchestrator' not in apis and 'research' not in handoff['host_next_action']
        assert 'docs/workflow/steps/02-inputs.md' in handoff['instructions']
        assert 'CHECK-IN 1' in handoff['host_next_action']
    elif route == 'research':
        assert 'research_orchestrator' in apis
    else:
        assert 'intake_planner' in apis and 'research_orchestrator' not in apis
    recovery = json.loads((output / 'inputs/capability_recovery.json').read_text())
    parent = [a for a in recovery['next_actions'] if a['stage'] == 'prepare-parent']
    assert len(parent) == 1
    tool = parent[0]['tool']
    assert ('research-orchestrate' in tool) == (route == 'research')
    assert ('resource_census' in tool) == (route == 'checkin')
    assert ('intake-plan' in tool) == (route == 'calculation')


def test_handoff_route_table_covers_every_whole_goal_kind():
    for kind in intake.WHOLE_GOAL_KINDS:
        route = intake.handoff_route({'task_mode': kind})
        assert route == ('research' if kind in ('research', 'method_study', 'anomaly_search') else 'checkin')
    assert intake.handoff_route({'task_mode': 'calculation'}) == 'calculation'
    assert intake.handoff_route({'task_mode': 'generate'}) is None


# ------------------------------------------------------------- parser coverage

@pytest.mark.parametrize('prompt,kind', [
    ('Produce 50k events of p p > t t~ with MadGraph, shower them in Pythia 8 and histogram the top pT.', 'generate'),
    ('Please simulate 5000 Drell-Yan events and pass them through Delphes for a quick look at the dimuon mass.', 'research'),
    ('Compute the inclusive cross section for e+ e- > h z with MG5_aMC at 250 GeV.', 'generate'),
    ('Show me the parton-level rapidity distribution of the heavy quark in gluon fusion.', 'generate'),
    ('Give the normalized missing-momentum spectrum at parton level for monojet production.', 'generate'),
    ('We need a full background estimate and signal-region design for a new same-sign dilepton search.', 'research'),
    ('Design and then carry out a blind search for a narrow diphoton resonance in the open data.', 'research'),
    ('Conduct a new search for long-lived neutral particles in the calorimeter.', 'research'),
])
def test_infer_kind_covers_common_request_shapes(prompt, kind):
    # A detector stage is not served by the scoped generate adapter: the request stays whole
    # as a research parent (rule D5) whose detector stage is an obligation, never dropped.
    detector = 'Delphes' in prompt
    assert intake.infer_kind(prompt) == ('generate' if detector else kind)
    contract = route_prompt.route(prompt)
    assert contract['task_mode'] == kind and validate(contract) == []
    if detector:
        assert any(o['criteria'].get('stage') == 'detector' for o in contract['task_requirements']['obligations'])


@pytest.mark.parametrize('prompt,operation,kind', [
    ('Enumerate the one-loop Feynman diagrams for h -> gamma gamma in the Standard Model.', 'diagram', 'calculation'),
    ('Can you draw the Feynman diagrams contributing to single-top production at tree level?', 'diagram', 'calculation'),
    ('Fit the kappa_V and kappa_F coupling modifiers to the combined Higgs signal-strength measurements with correlations.',
     'measurement_fit', 'calculation'),
    ('With the published differential top measurements and their covariance, constrain the coefficients ctG and ctW.',
     'measurement_fit', 'calculation'),
    ('Run Rivet with routine SYN_9040_I1228 over the attached ttbar.hepmc.gz and compare with the unfolded data.',
     'supplied_events', 'calculation'),
    ('Apply the SYN_9401_I1415 Rivet analysis to my existing LHE events.', 'supplied_events', 'calculation'),
    ('Draft a four-page letter describing the exclusion obtained in my finished run, with figures, as a PDF.',
     'manuscript', 'research'),
    ('Prepare a LaTeX manuscript summarising the accepted results in results/scan-a.', 'manuscript', 'research'),
])
def test_named_operations_are_expressible_without_analysis_stages(prompt, operation, kind):
    contract = route_prompt.route(prompt)
    assert validate(contract) == []
    assert contract['task_mode'] == kind and contract['intake']['operation'] == operation
    assert contract['compute_plan'] == 'none' and contract['detector_mode'] == 'none'
    assert not any('figure target' in item for item in contract['escalate'])
    assert contract['intake']['unresolved'] == intake.OPERATION_UNRESOLVED[operation]
    assert intake.handoff_route(contract) == 'operation'


def test_operation_handoff_names_declared_candidate_modes(tmp_path):
    code, output = initiate(tmp_path, 'List all tree-level Feynman diagrams for q q~ -> W+ W- in the SM.')
    assert code == 0
    handoff = json.loads((output / 'inputs/intake_handoff.json').read_text())
    assert handoff['route'] == 'operation' and handoff['operation'] == 'diagram'
    assert 'feyn-graph' in handoff['candidate_modes']
    assert 'ravel.workflow.science.plan' in handoff['planning_apis']


@pytest.mark.parametrize('prompt', [
    'Which measurements constrain the top Yukawa coupling?',
    'Reinterpret the ATLAS measurements to constrain my model parameters.',
    'Reproduce the paper and write a note on the comparison.',
])
def test_questions_and_analyses_are_not_relabelled_as_operations(prompt):
    assert intake.operation_kind(prompt) is None


def test_generation_keeps_requested_shower_and_detector_stages_explicit():
    # Herwig and Delphes are stages the scoped generate adapter does not run, so the request is a
    # research parent and both stages, and both tools, are obligations of its census.
    prompt = 'Generate 2000 events of p p > z h with MadGraph, shower with Herwig and run Delphes on them.'
    contract = route_prompt.route(prompt)
    assert contract['task_mode'] == 'research' and contract['compute_plan'] == 'none' and validate(contract) == []
    criteria = [o['criteria'] for o in contract['task_requirements']['obligations']]
    assert {'shower', 'detector', 'generation'} <= {c.get('stage') for c in criteria}
    assert {'Herwig', 'Delphes', 'MadGraph'} <= {c.get('tool') for c in criteria}
    plain = route_prompt.route('Generate parton-level events for p p > z h only.')
    assert 'intake' not in plain or not any('shower' in x for x in plain['intake']['unresolved'])


def test_host_generate_interpretation_cannot_drop_a_requested_shower():
    prompt = 'Make 10k showered events for my UFO model and give the photon pT histogram.'
    value = interpretation(prompt, 'generate', requested_outputs=['photon pT histogram after Pythia shower'])
    contract = route_prompt.route(prompt, interpretation=value)
    assert contract['task_mode'] == 'generate' and validate(contract) == []
    assert any('parton shower' in item for item in contract['intake']['unresolved'])


@pytest.mark.parametrize('kind,mode', [('manuscript', 'research'), ('diagram', 'calculation'),
                                       ('measurement_fit', 'calculation'), ('supplied_events', 'calculation')])
def test_host_interpretation_kinds_map_to_planning_parents(kind, mode):
    prompt = 'Use my retained material to deliver the requested item, exactly as described here.'
    contract = route_prompt.route(prompt, interpretation=interpretation(prompt, kind))
    assert validate(contract) == []
    assert contract['task_mode'] == mode
    assert contract['intake']['kind'] == mode and contract['intake']['operation'] == kind
    same = route_prompt.route(prompt, interpretation=interpretation(prompt, mode, operation=kind))
    assert same['intake'] == contract['intake']


def test_operation_must_agree_with_interpretation_kind():
    prompt = 'Deliver this request.'
    with pytest.raises(ValueError, match='operation disagrees'):
        route_prompt.route(prompt, interpretation=interpretation(prompt, 'reproduce', operation='diagram'))


def test_method_study_has_its_own_branch_and_keeps_requested_actions():
    prompt = ('Develop a graph-network anomaly detector for multijet events, evaluate it on held-out '
              'samples and compare it with an autoencoder baseline.')
    contract = route_prompt.route(prompt)
    assert validate(contract) == []
    assert contract['intake']['kind'] == 'method_study'
    assert contract['detector_mode'] == 'none' and contract['compute_plan'] == 'none'
    escalations = ' '.join(contract['escalate'] + contract['assumptions'] + [contract['cost_estimate']['note']])
    assert 'survey' not in escalations.lower()
    outputs = ' '.join(contract['intake']['requested_outputs']).lower()
    assert 'develop' in outputs and 'evaluate' in outputs and 'compare' in outputs


# ------------------------------------------------------------- declared metadata

def test_every_current_mode_has_declared_descriptor_metadata():
    from ravel.workflow.science import MODES
    catalog = cr.catalogue()
    assert all(row['descriptor'] for row in catalog['operations'])
    assert {row['mode'] for row in catalog['operations']} == set(MODES)
    pins = {Path(p['path']).name for p in catalog['source_pins']}
    assert 'mode_descriptors.json' in pins


def test_suggestions_come_only_from_declared_metadata():
    source = Path(cr.__file__).read_text()
    assert 'mapyde' not in source and 'slepton' not in source and 'dark pion' not in source
    descriptors = json.loads((Path(cr.__file__).resolve().parents[1] / 'data/mode_descriptors.json').read_text())
    vocabulary = json.dumps(descriptors).lower()
    for identity in ('mapyde', 'challenge'):
        assert identity not in vocabulary
    from ravel.validation import check_generality
    assert not check_generality.load_denylist(None, env={}).hits(vocabulary)


NAMED_TOOL_PROMPTS = [
    ('Run a global flavour fit of the WET coefficients with smelli and report the pull.', 'eft-toolchain'),
    ('Use flavio to predict R(D*) for a given set of Wilson coefficients.', 'eft-toolchain'),
    ('Obtain the lensed CMB TT spectrum from CLASS for my parameter point.', 'cosmology-solver'),
    ('Evaluate P(k) at z=0 with CAMB.', 'cosmology-solver'),
    ('Enumerate one-loop Feynman diagrams for gluon fusion with FeynGraph.', 'feyn-graph'),
    ('Typeset a manuscript from the accepted figures of my previous run.', 'manuscript-build'),
    ('Run the Rivet analysis SYN_9421_I1440 on the supplied file signal.hepmc.', 'analyze'),
    ('Fit Gaussian measurements with their covariance to extract a signal strength.', 'measurement'),
    ('Profile the published pyhf workspace patchset for my model point.', 'published-model'),
    ('Decompose my SLHA spectrum with SModelS.', 'model-portfolio'),
]


# A prompt for an operation this tree does not ship has no mode to find here.
@pytest.mark.parametrize('prompt,mode', [(p, m) for p, m in NAMED_TOOL_PROMPTS if shipped_operations([m])])
def test_named_tools_inputs_and_outputs_find_their_modes(prompt, mode):
    result = cr.plan(prompt)
    rows = {c['mode']: c for c in result['candidates']}
    assert mode in rows
    assert rows[mode]['selection'] == 'declared_metadata_match_requires_host_review'
    assert rows[mode]['matched'] and rows[mode]['reason']


@pytest.mark.parametrize('prompt,absent', [
    ('Write a short paper summarising the results stored in runs/higgsino-fit as a PDF.', {'continuous-fit', 'joint-fit', 'measurement'}),
    ('Fill the results template with the numbers from my run.', {'signal-template'}),
    ('Make the ratio of the two histograms look nicer.', {'ratio-measurement'}),
    ('Compare SR/CR yields for the dark pion/dark rho benchmarks in `data/fit-results.json`.', {'joint-fit', 'continuous-fit'}),
])
def test_paths_quotes_and_generic_words_do_not_trigger_modes(prompt, absent):
    modes = {c['mode'] for c in cr.plan(prompt)['candidates']}
    assert not modes & absent


def test_slash_joined_physics_terms_survive_path_removal():
    text = cr.matching_text('Study the dark pion/dark rho plane with SR/CR yields in runs/abc-1 and x.hepmc.')
    assert 'dark pion' in text and 'dark rho' in text and 'SR/CR' in text
    assert 'runs/abc-1' not in text and 'HepMC' in text


# ------------------------------------------------------------- held intake resolution

# A genuine hold: a context label carrying a scientific qualifier (an ungrounded identifier).
# A request with a scientific object and no matching rule is an open parent, not a hold.
HELD = 'Context label: particle-level\nTell me whether a 650 GeV leptoquark decaying to b tau is still allowed by current data.'


def test_resolve_replaces_held_intake_in_place_and_keeps_history(tmp_path, capsys):
    code, output = initiate(tmp_path, HELD)
    assert code == 1 and output.is_dir()
    held = load_contract(output / 'inputs/task_contract.json')
    assert held['task_mode'] == 'unsupported'
    capsys.readouterr()
    path = tmp_path / 'intent.json'
    path.write_text(json.dumps(interpretation(HELD, 'reinterpret')))
    assert cli.main(['initiate', '--resolve', str(output), '--interpretation', str(path)]) == 0
    contract = load_contract(output / 'inputs/task_contract.json')
    assert contract['task_mode'] == 'reinterpret' and contract['prompt'] == HELD and validate(contract) == []
    history = output / 'inputs/history/revision-1'
    assert load_contract(history / 'inputs/task_contract.json') == held
    resolution = json.loads((history / 'resolution.json').read_text())
    assert resolution['previous_task_mode'] == 'unsupported' and resolution['task_mode'] == 'reinterpret'
    assert resolution['request_sha256'] == hashlib.sha256(HELD.encode()).hexdigest()
    assert (output / 'inputs/interpretation.json').read_bytes() == path.read_bytes()
    assert json.loads((output / 'inputs/intake_handoff.json').read_text())['route'] == 'checkin'
    assert json.loads((output / 'current_state.json').read_text())['request']['task_mode'] == 'reinterpret'
    assert json.loads((output / 'run_state.json').read_text())['task_mode'] == 'reinterpret'
    out = capsys.readouterr().out
    assert 'resolved in place' in out and str(history) in out


def test_resolve_refuses_a_different_request_hash(tmp_path):
    _, output = initiate(tmp_path, HELD)
    before = (output / 'inputs/task_contract.json').read_bytes()
    path = tmp_path / 'intent.json'
    path.write_text(json.dumps(interpretation(HELD + ' ', 'reinterpret')))
    assert cli.main(['initiate', '--resolve', str(output), '--interpretation', str(path)]) == 2
    assert (output / 'inputs/task_contract.json').read_bytes() == before
    assert not (output / 'inputs/history').exists()


def test_resolve_refuses_after_checkin1(tmp_path):
    _, output = initiate(tmp_path, HELD)
    (output / 'inputs/checkin1.json').write_text('{}')
    path = tmp_path / 'intent.json'
    path.write_text(json.dumps(interpretation(HELD, 'reinterpret')))
    assert cli.main(['initiate', '--resolve', str(output), '--interpretation', str(path)]) == 2
    assert load_contract(output / 'inputs/task_contract.json')['task_mode'] == 'unsupported'


def test_resolve_also_corrects_a_pre_checkin1_draft_twice(tmp_path):
    prompt = 'Using LHC data, constrain the two EFT coefficients from published cross-section data points.'
    code, output = initiate(tmp_path, prompt)
    assert code == 0
    for index, kind in enumerate(('research', 'measurement_fit'), 1):
        path = tmp_path / f'intent-{index}.json'
        path.write_text(json.dumps(interpretation(prompt, kind)))
        assert cli.main(['initiate', '--resolve', str(output), '--interpretation', str(path)]) == 0
        assert (output / f'inputs/history/revision-{index}/inputs/task_contract.json').is_file()
    final = load_contract(output / 'inputs/task_contract.json')
    assert final['task_mode'] == 'calculation' and final['intake']['operation'] == 'measurement_fit'


@pytest.mark.parametrize('args', [
    ['--resolve', 'held'],
    ['--resolve', 'held', '--interpretation', 'i.json', '--out', 'x'],
    ['--resolve', 'held', '--prompt', 'x', '--interpretation', 'i.json'],
])
def test_resolve_argument_shape_is_checked(args):
    with pytest.raises(SystemExit) as exc:
        cli.main(['initiate', *args])
    assert exc.value.code == 2


def test_unsupported_initiate_prints_a_short_summary_not_the_packet(tmp_path, capsys):
    code, output = initiate(tmp_path, HELD)
    assert code == 1
    captured = capsys.readouterr()
    assert len(captured.out) < 3000
    assert 'needs_intent_resolution' in captured.out and '--resolve' in captured.out
    assert str(output / 'inputs/capability_recovery.json') in captured.out
    assert json.loads((output / 'inputs/capability_recovery.json').read_text())['original_request'] == HELD


# ------------------------------------------------------------- autonomy heading

@pytest.mark.parametrize('message,command', [
    ('Run autonomously: is a 700 GeV top partner excluded by the latest searches?', 'Run autonomously:'),
    ('Run autonomously - reinterpret the dijet search for my Z prime benchmark.', 'Run autonomously -'),
    ('Context first.\nRun autonomously: compute the expected limit for the heavy scalar.', 'Run autonomously:'),
    ('please run autonomously: compare the two fits and tell me which is preferred?', 'please run autonomously:'),
    ('Run Autonomously — survey the existing constraints on a light dark photon.', 'Run Autonomously —'),
])
def test_heading_form_delegates_with_the_rest_of_the_message_as_scope(message, command):
    span = autonomy.delegation_intent(message)
    assert span is not None and span['text'] == command
    assert message[span['start']:span['end']] == span['text']


@pytest.mark.parametrize('message', [
    'Run autonomously: only if I confirm the budget first.',
    'Run autonomously:',
    'Example:\nRun autonomously: estimate the limit.',
    '> Run autonomously: estimate the limit.',
    '```\nRun autonomously: estimate the limit.\n```',
    'Run autonomously: estimate the limit.\nDo not run autonomously after all.',
    'The manual says "Run autonomously: estimate the limit."',
    'If the fit converges:\nRun autonomously: estimate the limit.',
    'Run autonomously? Estimate the limit.',
])
def test_heading_form_keeps_quotation_conditional_and_negation_guards(message):
    assert autonomy.delegation_intent(message) is None


@pytest.mark.parametrize('prompt', [
    'Reinterpret the monojet search for my model using the published background estimate in each signal region.',
    'Reproduce the background estimate of the published search and its signal regions.',
])
def test_published_background_estimates_inside_recasts_stay_recasts(prompt):
    assert not intake.research_request(prompt)


def test_words_inside_paths_do_not_choose_the_kind():
    assert intake.infer_kind('Prepare a manuscript from the accepted results in out/scan-reproduce-2.') == 'research'
    assert intake.operation_kind('Prepare a manuscript from the accepted results in out/scan-reproduce-2.') == 'manuscript'


@pytest.mark.parametrize('quote', ['whole', 'command'])
def test_heading_form_prepares_an_ordinary_delegation_declaration(tmp_path, quote):
    from ravel.workflow.task_completion import initial_requirements
    message = 'Run autonomously: is a 900 GeV gluino with a light neutralino still allowed?'
    path = tmp_path / 'initial-user-message.txt'
    path.write_text(message)
    result = autonomy.prepare_declaration(
        {'prompt': message, 'task_mode': 'research', 'task_requirements': initial_requirements(message)},
        tmp_path / 'delegation.json',
        user_text={'path': str(path), 'sha256': hashlib.sha256(message.encode()).hexdigest()},
        quote=message if quote == 'whole' else 'Run autonomously:', origin='initial_prompt',
        delegate_actor='actual-machine', actions=['approve_plan'],
        bounds={'compute_plans': ['smoke'], 'allowed_changed_paths': [], 'allowed_stages': [], 'max_redos': 0},
        task_class='research_analysis', base_dir=tmp_path)
    span = autonomy.declaration(result['document'], tmp_path)['value']['command_span']
    assert span['text'] == 'Run autonomously:' and result['execution_authorized'] is False


@pytest.mark.parametrize('prompt', [
    'Produce a summary plot of limits from published searches for heavy resonances with few signal events.',
    'Reproduce the published cutflow after we generate 10k signal events for the benchmark.',
])
def test_generation_words_inside_broader_requests_do_not_select_generate(prompt):
    assert intake.infer_kind(prompt) != 'generate'
