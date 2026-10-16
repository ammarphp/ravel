"""Science mode event-production: planning refusals, chunked runs, MLM accounting and the chain to columnar analysis."""

from method_decision_fixture import admit_method
import copy
import json
import math
from pathlib import Path

import pytest

import production_fixtures as pf
from columnar_fixtures import RECIPE
from ravel.physics import event_production as ep


@pytest.fixture(autouse=True)
def fast(monkeypatch, tmp_path):
    monkeypatch.setattr(ep, 'POLL_SECONDS', 0.02)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))


def receipt_of(out):
    failures = out / 'event-production' / 'failures.json'
    assert not failures.exists(), failures.read_text()
    return json.loads((out / 'event-production' / ep.RECEIPT).read_text())


# ---------------------------------------------------------------- planning
@pytest.mark.parametrize('change, message', [
    (lambda t: t.pop('model'), 'event-production task needs'),
    (lambda t: t['shower'].update(seed=0), 'shower.seed'),
    (lambda t: t.update(chunks=0), 'chunks'),
    (lambda t: t['normalization'].update(sigma='guess'), 'normalization.sigma'),
    (lambda t: t['detector']['cards'].append(dict(t['detector']['cards'][0])), 'unique'),
    (lambda t: t['shower'].update(variants=[{'name': 'nominal', 'commands': []}]), 'variant name'),
])
def test_task_structure_is_checked(tmp_path, change, message):
    task = pf.production_task(tmp_path)
    change(task)
    with pytest.raises(ValueError, match=message):
        ep.validate(task)


def test_reserved_pythia_settings_are_refused(tmp_path):
    task = pf.production_task(tmp_path)
    task['shower']['commands'].append('Random:seed = 5')
    with pytest.raises(ValueError, match='set by the production stage'):
        ep.compile_task(task, tmp_path)


def test_header_states_generator_process_model_and_run_card(tmp_path):
    header = ep.read_header(pf.write_lhe(tmp_path / 'e.lhe', ickkw=1, xqcut=20))
    assert header['generator'] == {'name': 'MadGraph5_aMC@NLO', 'version': '2.9.27', 'source': 'LHE init <generator> tag'}
    assert header['model'] == 'MSSM_SLHA2' and header['run_card']['ickkw'] == '1' and header['run_card']['xqcut'] == '20'
    assert header['beam_energy_gev'] == [6500.0, 6500.0] and header['idwtup'] == -4


def test_model_differing_from_the_banner_is_refused(tmp_path):
    task = pf.production_task(tmp_path)
    task['model']['name'] = 'SMEFTsim'
    with pytest.raises(ValueError, match='differs from the LHE banner'):
        ep.compile_task(task, tmp_path)


def test_gravitino_with_stock_card_is_refused_and_a_fix_is_explicit(tmp_path):
    task = pf.production_task(tmp_path)
    task['model']['invisible'] = [1000039, 1000022]
    with pytest.raises(ValueError, match='would reconstruct invisible states.*fix_invisibles'):
        ep.compile_task(task, tmp_path)
    task['detector']['cards'][0]['fix_invisibles'] = True
    compiled = ep.compile_task(task, tmp_path)
    assert not compiled['cards'][0]['gate']['consistent']


@pytest.mark.parametrize('edit, message', [
    (lambda m: m.pop('settings'), 'shower.merging needs'),
    (lambda m: m['settings'].pop('JetMatching:qCut'), 'missing JetMatching:qCut'),
    (lambda m: m['settings'].update({'JetMatching:setMad': 'on'}), 'setMad must be off'),
    (lambda m: m['settings'].update({'JetMatching:qCut': 10}), 'below the generation xqcut'),
    (lambda m: m.update(scheme='CKKW-L'), 'must be MLM'),
])
def test_merged_plan_without_complete_matching_settings_is_refused(tmp_path, edit, message):
    task = pf.production_task(tmp_path, merged=True)
    edit(task['shower']['merging'])
    with pytest.raises(ValueError, match=message):
        ep.compile_task(task, tmp_path)


def test_ickkw_sample_without_matching_and_matching_without_ickkw_are_refused(tmp_path):
    task = pf.production_task(tmp_path, merged=True)
    merging = task['shower'].pop('merging')
    with pytest.raises(ValueError, match='double counts jets'):
        ep.compile_task(task, tmp_path)
    pf.write_lhe(tmp_path / 'events.lhe', n=12, ickkw=0)
    task['shower']['merging'] = merging
    with pytest.raises(ValueError, match='needs a sample generated with ickkw = 1'):
        ep.compile_task(task, tmp_path)


def test_planning_inputs_pin_every_file(tmp_path):
    task = pf.production_task(tmp_path)
    names = {p.name for p in ep.inputs(task, tmp_path)}
    assert {'events.lhe', 'card.tcl', 'pythia_shower', 'DelphesHepMC3'} <= names
    assert ep.execution_seconds(task, tmp_path) == 3 * 120 + 600


def test_missing_program_is_refused(tmp_path):
    task = pf.production_task(tmp_path)
    task['tools']['delphes'] = str(tmp_path / 'nowhere/DelphesHepMC3')
    with pytest.raises(ValueError, match='not installed'):
        ep.compile_task(task, tmp_path)


def test_chunk_runs_only_inside_a_dispatched_backend_job(tmp_path, monkeypatch):
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'dispatch_record': str(tmp_path / 'none.json')}))
    monkeypatch.delenv('RAVEL_OUTPUT_DIR', raising=False)
    with pytest.raises(ValueError, match='execution-backend job'):
        ep.run_chunk(plan)
    monkeypatch.setenv('RAVEL_OUTPUT_DIR', str(tmp_path))
    with pytest.raises(ValueError, match='not dispatched by an approved production run'):
        ep.run_chunk(plan)


# ---------------------------------------------------------------- runs
def test_chunked_run_keeps_counts_weights_and_writes_the_receipt(tmp_path):
    task = pf.production_task(tmp_path, n=12, chunks=3)
    task['retain_hepmc'] = True
    task['detector']['cards'].append({'name': 'skimmed', 'card': 'card.tcl', 'keep_branches': ['Jet', 'MissingET'],
                                      'required_branches': ['Event.Weight']})
    result = ep.run(task, tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False, result.get('failures')
    receipt = receipt_of(tmp_path / 'out')
    assert receipt['quantity'] == {'weight_convention': 'signed'}
    assert receipt['events']['attempted'] == receipt['events']['accepted'] == 12
    assert receipt['events']['detector_entries'] == {'synthetic': 12, 'skimmed': 12}
    seeds = [c['seed'] for c in receipt['events']['chunks']]
    assert len(set(seeds)) == 3
    merged = receipt['outputs']['synthetic']
    assert merged['entries'] == sum(f['entries'] for f in merged['files']) == 12
    assert math.isclose(merged['sum_weights'], math.fsum(f['sum_weights'] for f in merged['files']))
    assert math.isclose(merged['sum_weights'], 12 * 0.25, rel_tol=1e-6)        # LHE weights carried to Event.Weight
    assert receipt['sigma'] == {**receipt['sigma'], 'value_pb': 0.25, 'source': 'LHE init block (sum of XSECUP over subprocesses)'}
    assert receipt['sigma']['convention']['tool'] == 'MadGraph5_aMC@NLO 2.9.27'
    assert receipt['generator']['version'] == '2.9.27' and receipt['shower']['version'] == '8.312'
    assert receipt['detector']['version'] == '3.5.1'
    assert receipt['cards']['delphes']['skimmed']['derived']['edits'][0]['module'] == 'TreeWriter'
    assert receipt['cards']['delphes']['synthetic']['derived'] is None
    assert receipt['merging'] == {'scheme': 'none'} and receipt['weights']['branch'] == 'Event.Weight'
    assert receipt['process']['banner'][-1] == 'generate p p > n2 x1+' and receipt['model']['name'] == 'MSSM_SLHA2'
    out = tmp_path / 'out' / 'event-production'
    metadata = json.loads((out / receipt['event_metadata']['nominal-0000']['metadata']).read_text())
    assert set(metadata) == {'schema_version', 'event_level', 'beam_pdg', 'beam_energy_gev', 'weight_names', 'events',
                             'groups', 'cross_section_pb', 'source'}
    journal = [json.loads(l) for l in (out / 'journal.jsonl').read_text().splitlines()]
    assert [r['event'] for r in journal].count('submitted') == 3 and all(r.get('plan_sha256') for r in journal if r['event'] == 'submitted')
    assert all((out / 'backend' / t / 'backend-handle.json').is_file() for t in ('nominal-0000', 'nominal-0001', 'nominal-0002'))
    assert json.loads((out / 'gate' / 'fetched-nominal-0001.json').read_text())['verdict'] == 'accepted'


def test_gravitino_run_writes_a_derived_card_and_records_the_deviation(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_TEST_STUB_BSM', '1000039')
    task = pf.production_task(tmp_path, n=4, chunks=1)
    task['model']['invisible'] = [1000039]
    task['detector']['cards'][0]['fix_invisibles'] = True
    ep.run(task, tmp_path, tmp_path / 'out')
    receipt = receipt_of(tmp_path / 'out')
    card = receipt['cards']['delphes']['synthetic']
    assert card['derived'] and card['sha256'] != card['source']['sha256']
    assert {e['text'].strip() for e in card['derived']['edits']} == {
        'add EnergyFraction {1000039} {0.0}', 'add PdgCode {1000039}', 'add PdgCode {-1000039}'}
    assert receipt['deviations'] and 'derived card' in receipt['deviations'][0]


def test_undeclared_stable_bsm_state_stops_before_delphes(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_TEST_STUB_BSM', '1000039')
    task = pf.production_task(tmp_path, n=4, chunks=1)
    result = ep.run(task, tmp_path, tmp_path / 'out')
    assert result['status'] == 'failed' and not (tmp_path / 'out/event-production' / ep.RECEIPT).exists()
    assert '1000039' in json.dumps(result['failures'])


def test_empty_detector_output_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_TEST_STUB_EMPTY', '1')
    result = ep.run(pf.production_task(tmp_path, n=4, chunks=2), tmp_path, tmp_path / 'out')
    assert result['status'] == 'failed' and set(result['failures']) == {'nominal-0000', 'nominal-0001'}


def test_an_error_while_chunks_run_cancels_them(tmp_path, monkeypatch):
    from ravel.workflow import execution_backend as eb
    monkeypatch.setenv('RAVEL_TEST_STUB_SLEEP', '60')
    # The error arrives in the run's own wait on its chunks. time.sleep is one function for the whole
    # process, so the lease and the backend wait as usual and only the run's poll interval is counted.
    monkeypatch.setattr(ep, 'POLL_SECONDS', 0.0173)
    sleep = ep.time.sleep
    calls = []

    def interrupted(seconds):
        if seconds != ep.POLL_SECONDS:
            return sleep(seconds)
        calls.append(seconds)
        if len(calls) == 3:
            raise RuntimeError('supervisor stop')
    monkeypatch.setattr(ep.time, 'sleep', interrupted)
    with pytest.raises(RuntimeError, match='supervisor stop'):
        ep.run(pf.production_task(tmp_path, n=4, chunks=2), tmp_path, tmp_path / 'out')
    out = tmp_path / 'out/event-production'
    journal = [json.loads(l) for l in (out / 'journal.jsonl').read_text().splitlines()]
    assert [r['event'] for r in journal] == ['submitted', 'cancelled']
    handle = eb.read_handle(out / 'backend/nominal-0000')
    plan = json.loads((out / 'backend/nominal-0000/plan.json').read_text())
    assert eb.observe(plan, handle)['state'] in ('cancelled', 'failed')
    assert not (out / 'backend/nominal-0001').exists()


def test_a_chunk_past_its_declared_limit_is_a_recorded_failure(tmp_path, monkeypatch):
    """The wait on a chunk ends at its declared wall-clock limit, and the record states why."""
    import time
    from ravel.workflow import execution_backend as eb
    monkeypatch.setenv('RAVEL_TEST_STUB_SLEEP', '60')
    task = pf.production_task(tmp_path, n=4, chunks=1)
    task['resources']['wall_seconds_per_chunk'] = 1
    started = time.monotonic()
    result = ep.run(task, tmp_path, tmp_path / 'out')
    assert time.monotonic() - started < 45, 'the wait outlived the declared limit and the bounded cancellation'
    assert result['status'] == 'failed' and set(result['failures']) == {'nominal-0000'}
    failure = result['failures']['nominal-0000']
    assert failure['state'] == 'failed' and 'wall-clock ceiling reached' in failure['detail']
    out = tmp_path / 'out/event-production'
    assert json.loads((out / 'failures.json').read_text())['nominal-0000']['detail'] == failure['detail']
    journal = [json.loads(l) for l in (out / 'journal.jsonl').read_text().splitlines()]
    assert [r['event'] for r in journal] == ['submitted', 'finished']
    assert journal[-1]['state'] == 'failed' and 'wall-clock ceiling reached' in journal[-1]['detail']
    assert not (out / ep.RECEIPT).exists()
    handle = eb.read_handle(out / 'backend/nominal-0000')
    assert handle['cancel_requested'] is True
    plan = json.loads((out / 'backend/nominal-0000/plan.json').read_text())
    assert eb.observe(plan, handle)['state'] in ('cancelled', 'failed')


def test_a_job_that_stays_unfinished_after_its_payload_exited_keeps_the_observed_reason(tmp_path, monkeypatch):
    """A job that never becomes terminal is failed at its limit with what was last observed, never awaited further."""
    from ravel.workflow import execution_backend as eb
    task = pf.production_task(tmp_path, n=4, chunks=1)
    task['resources']['wall_seconds_per_chunk'] = 1
    held = {'state': 'running', 'exit_code': 0, 'payload_exited': True,
            'detail': 'payload exited 0; a descendant outside its process group still runs'}
    monkeypatch.setattr(eb, 'observe', lambda plan, handle: dict(held))
    monkeypatch.setattr(eb, 'cancel', lambda plan, handle, **kwargs: dict(held))
    result = ep.run(task, tmp_path, tmp_path / 'out')
    failure = result['failures']['nominal-0000']
    assert result['status'] == 'failed' and failure['state'] == 'failed'
    assert 'wall-clock ceiling reached' in failure['detail'] and 'a descendant outside its process group' in failure['detail']


def test_the_merge_job_is_bounded_by_the_declared_limit(tmp_path, monkeypatch):
    """The merge job waits no longer than the limit the task declares (the one execution_seconds counts)."""
    task = pf.production_task(tmp_path, n=6, chunks=2)
    task['merge'] = 'hadd'
    assert ep.execution_seconds(task, tmp_path) == 2 * 120 + 120 + 600
    compiled = ep.compile_task(task, tmp_path)
    out = tmp_path / 'out'
    (out / 'chunks/nominal-0000').mkdir(parents=True)
    (out / 'chunks/nominal-0000/synthetic.root').write_bytes(b'synthetic chunk file')
    receipts = {'nominal-0000': {'outputs': {'synthetic': {'file': 'synthetic.root', 'entries': 3, 'sum_weights': 0.75,
                                                           'sum_weights2': 0.1875}}}}
    submitted = []

    def refused(jobs, *args):
        submitted.extend(jobs)
        return {jobs[0]['tag']: {'state': 'failed', 'detail': 'not run by this test'}}
    monkeypatch.setattr(ep, '_run_jobs', refused)
    card = {'name': 'synthetic'}
    with pytest.raises(ValueError, match='merging synthetic .nominal. failed: not run by this test'):
        ep._merge_card(task, compiled, out, 'nominal', card, ['nominal-0000'], receipts)
    assert [job['spec']['resources']['wall_seconds'] for job in submitted] == [120]
    del task['resources']['wall_seconds_per_chunk']
    with pytest.raises(ValueError, match='merging synthetic'):
        ep._merge_card(task, compiled, out, 'nominal', card, ['nominal-0000'], receipts)
    assert submitted[-1]['spec']['resources']['wall_seconds'] == ep.DEFAULT_RESOURCES['wall_seconds_per_chunk']


def test_hadd_merge_is_verified(tmp_path):
    task = pf.production_task(tmp_path, n=9, chunks=3)
    task['merge'] = 'hadd'
    ep.run(task, tmp_path, tmp_path / 'out')
    merged = receipt_of(tmp_path / 'out')['outputs']['synthetic']
    assert merged['scheme'] == 'hadd' and merged['verified']['entries'] == 9
    assert math.isclose(merged['verified']['sum_weights'], merged['sum_weights'], rel_tol=1e-6)


def test_mlm_accounting_normalizes_to_the_matched_fraction(tmp_path):
    task = pf.production_task(tmp_path, n=12, chunks=2, merged=True)
    task['shower']['variants'] = [{'name': 'qcut-high', 'commands': ['JetMatching:qCut = 40']}]
    result = ep.run(task, tmp_path, tmp_path / 'out')
    receipt = receipt_of(tmp_path / 'out')
    accounting = receipt['merging']['accounting']
    assert accounting['attempted'] == 12 and accounting['accepted'] == 8 and accounting['vetoed'] == 4
    pre = receipt['sigma']['pre_matching_pb']
    assert math.isclose(receipt['sigma']['value_pb'] / pre, accounting['accepted'] / accounting['attempted'])
    assert math.isclose(receipt['merging']['matched_sigma_pb'], result['sigma_pb'])
    by_mult = receipt['merging']['pre_veto_sigma_pb']['by_extra_partons']
    assert set(by_mult) == {'0', '1', '2'} and math.isclose(math.fsum(by_mult.values()), pre)
    assert receipt['merging']['djr']['counts'] and receipt['events']['detector_entries'] == {'synthetic': 8}
    assert receipt['outputs']['synthetic']['entries'] == 8
    variant = receipt['variants']['qcut-high']
    assert 'JetMatching:qCut = 40' in variant['shower_commands'] and 'JetMatching:qCut = 30' not in variant['shower_commands']
    assert len({c['seed'] for c in receipt['events']['chunks'] + variant['events']['chunks']}) == 4


def test_mlm_requires_njetmax_to_match_the_sample(tmp_path):
    task = pf.production_task(tmp_path, n=6, chunks=1, merged=True)
    task['shower']['merging']['settings']['JetMatching:nJetMax'] = 1
    with pytest.raises(ValueError, match='nJetMax is 1 but the LHE holds up to 2'):
        ep.run(task, tmp_path, tmp_path / 'out')


def test_ledger_cross_section_is_carried_with_its_convention(tmp_path):
    task = pf.production_task(tmp_path, n=4, chunks=1)
    ledger = {'schema_version': 1, 'sample': 'synthetic', 'luminosity': {'value': 139, 'unit': 'fb^-1', 'source': 's'},
              'sigma': {'value': 30.0, 'unit': 'fb', 'order': 'NLO+NLL', 'tool': 'declared table', 'pdf': 'PDF4LHC15',
                        'scales': 'central', 'process_basis': 'n2 x1+', 'source': 'synthetic reference table'},
              'br': [{'value': 0.5, 'source': 'paper_assumption', 'detail': 'declared'}], 'filter_eff': None, 'k': None,
              'generated': {'sumw': 1.0, 'sumw2': 1.0}, 'selected': {'r': {'sumw': [1.0], 'sumw2': [1.0]}},
              'bin_convention': 'per-bin'}
    (tmp_path / 'ledger.json').write_text(json.dumps(ledger))
    task['normalization'] = {'sigma': 'ledger', 'ledger': 'ledger.json'}
    ep.run(task, tmp_path, tmp_path / 'out')
    sigma = receipt_of(tmp_path / 'out')['sigma']
    assert math.isclose(sigma['value_pb'], 0.015) and sigma['convention']['order'] == 'NLO+NLL'
    assert sigma['source'] == 'synthetic reference table' and sigma['normalization_ledger']['applied_sigma_pb'] == sigma['value_pb']


def test_generation_receipt_pointer_needs_a_declared_convention(tmp_path):
    task = pf.production_task(tmp_path, n=4, chunks=1)
    (tmp_path / 'gen.json').write_text(json.dumps({'cross_section': {'value_pb': 0.31}}))
    task['events']['generation_receipt'] = 'gen.json'
    task['normalization'] = {'sigma': 'generation-receipt', 'pointer': '/cross_section/value_pb', 'source': 'generator receipt',
                             'convention': {'order': 'LO', 'tool': 'MG5', 'pdf': 'NNPDF', 'scales': 'default', 'process_basis': 'n2 x1+'}}
    assert ep.compile_task(task, tmp_path)['sigma']['value_pb'] == 0.31
    task['normalization']['pointer'] = '/missing'
    with pytest.raises(ValueError, match='no value at /missing'):
        ep.compile_task(task, tmp_path)


# ---------------------------------------------------------------- chain to the analysis engine
def test_end_to_end_lhe_to_binned_values(tmp_path):
    """LHE fixture -> stub shower and Delphes -> Delphes-shaped ROOT -> columnar analysis -> binned_values."""
    from ravel.physics import columnar_analysis
    task = pf.production_task(tmp_path, n=30, chunks=3)
    production = ep.run(task, tmp_path, tmp_path / 'out')
    assert production['status'] == 'passed', production.get('failures')
    receipt_path = tmp_path / 'out' / production['receipt']['path']
    receipt = json.loads(receipt_path.read_text())
    (tmp_path / 'recipe.json').write_text(json.dumps(RECIPE))
    normalization = {**receipt['analysis_normalization'], 'luminosity_ifb': 139.0, 'luminosity_source': 'synthetic'}
    normalization['cross_section_pb'] = {'production_receipt': str(receipt_path), 'pointer': '/sigma/value_pb'}
    analysis = {'recipe': 'recipe.json', 'format': 'delphes', 'inputs': production['outputs']['synthetic'],
                'normalization': normalization, 'chunk_size': 7}
    files = columnar_analysis.inputs(analysis, tmp_path)
    assert receipt_path in [Path(f) for f in files]
    result = columnar_analysis.run(analysis, tmp_path, tmp_path / 'analysis')
    assert result['status'] == 'passed'
    norm = result['normalization']
    assert math.isclose(norm['scale'], 0.25 * 1000 * 139.0 / receipt['weights']['sum'])
    assert norm['cross_section_from']['sha256'] == ep.sha256(receipt_path)
    histogram = json.loads((tmp_path / 'analysis' / result['histograms']['met in three-lepton region']['file']).read_text())
    assert histogram['kind'] == 'binned_values'


# ---------------------------------------------------------------- registration and the ordinary lifecycle
def test_registration_descriptor_and_cli(tmp_path, capsys):
    from ravel import cli
    from ravel.paths import package_data_path
    from ravel.workflow import science
    from test_science_capability_integration import specification
    task = pf.production_task(tmp_path, n=4, chunks=1)
    spec = {**specification('event-production', task), 'max_seconds': 3600}
    assert 'event-production' in science.MODES and science.adapter(spec) is ep and science._new_capability(spec)
    science.validate(spec)
    assert {p.name for p in science.task_inputs(spec, tmp_path)} >= {'events.lhe', 'card.tcl'}
    descriptors = json.loads(package_data_path('mode_descriptors.json').read_text())['modes']
    assert 'Delphes' in descriptors['event-production']['tools']
    for name in ('event-production', 'detector-card', 'output-gate'):
        assert name in cli.FOCUSED_COMMANDS
    path = pf.write_task(tmp_path, task)
    assert ep.main(['check', str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['cards'][0]['gate']['consistent']


@pytest.mark.parametrize('prompt', [
    'Shower my LHE events with Pythia 8 and run the Delphes CMS card to get detector-level events.',
    'Produce Delphes ROOT files from these MLM-merged Les Houches events with the gravitino invisible.'])
def test_capability_routing_suggests_the_mode(prompt):
    from ravel.workflow import capability_routing as cr
    assert 'event-production' in {c['mode'] for c in cr.plan(prompt)['candidates']}


def test_receipt_command_checks_the_delphes_files(tmp_path, capsys):
    result = ep.run(pf.production_task(tmp_path, n=4, chunks=2), tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed', result.get('failures')
    receipt = tmp_path / 'out/event-production' / ep.RECEIPT
    assert ep.main(['receipt', str(receipt)]) == 0
    assert all(r['passed'] for r in json.loads(capsys.readouterr().out))
    assert ep.main(['header', str(tmp_path / 'events.lhe')]) == 0


def test_ordinary_plan_approve_run(tmp_path):
    from ravel.workflow import science
    from test_science_capability_integration import specification
    work = tmp_path / 'request'
    work.mkdir()
    task = pf.production_task(work, n=6, chunks=2)
    spec = specification('event-production', task)
    spec['max_seconds'] = 7200
    (work / 'science.json').write_text(json.dumps(spec))
    rd = tmp_path / 'study'
    science.plan(rd, work / 'science.json'); admit_method(rd)
    with pytest.raises(Exception):
        science.run(rd)
    assert not list(rd.rglob(ep.RECEIPT))
    science.approve(rd, 'Scripted engineering check.', scripted=True)
    assert science.run(rd) == 0, '\n'.join(p.read_text(errors='replace')[-3000:]
                                           for p in sorted(rd.rglob('*.log')) + sorted(rd.rglob('failures.json')))
    receipt = json.loads(next(rd.rglob(ep.RECEIPT)).read_text())
    assert receipt['events']['accepted'] == 6
    events = [json.loads(p.read_text()) for p in sorted((rd / 'logs/authorization').glob('*.json'))]
    assert [e['event'] for e in events][:2] == ['authorized', 'launched']
