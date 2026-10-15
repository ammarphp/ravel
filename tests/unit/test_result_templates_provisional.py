"""A deadline-labelled provisional fill: refused outside its contract, superseded by review."""
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from ravel import cli
from ravel.workflow import completion_claims, execution, physics_review as pr, study_deadline, workflow_state
from ravel.workflow import result_templates as rt
from ravel.workflow.state_io import atomic_json
from test_physics_review import policy, check_packet, accept
from test_result_templates import HEPDATA, edges, table, template

DEADLINE = {'utc': '2030-01-01T12:00:00Z', 'margin_s': 3600}
BEFORE, INSIDE = '2030-01-01T10:00:00Z', '2030-01-01T11:30:00Z'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def produced_run(root, monkeypatch, document, *, deadline=DEADLINE):
    """A run whose stage receipt pins outputs/result.json, under an open, unresolved review."""
    (root / 'inputs').mkdir(parents=True)
    p = policy(); p['claim_scopes']['original_task_completion'] = {'checks': ['integrity', 'agreement'], 'actions': ['delivery', 'reuse']}
    atomic_json(root / pr.POLICY, p)
    atomic_json(root / 'inputs/checkin1_approval.json', {'fixture': 'mocked compute approval only'})
    contract = {'schema_version': 1, 'prompt': 'Synthetic binned prediction.'}
    if deadline is not None:
        contract['deadline'] = deadline
    atomic_json(root / 'inputs/task_contract.json', contract)
    monkeypatch.setattr(pr, '_science_run', lambda root: False)
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'synthetic no-child hardware description')
    monkeypatch.setattr(workflow_state, 'approval_input_paths', lambda rd: [str(Path(rd) / pr.POLICY)])
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    (root / 'inputs/settings.cfg').write_text('synthetic=1\n')
    (root / 'inputs/held-fixed.txt').write_text('fixed\n')
    atomic_json(root / 'inputs/reference.json', {'reference': 1})
    inputs = ['inputs/settings.cfg', 'inputs/held-fixed.txt']
    spec = {'command': [sys.executable, '-c', 'pass'], 'cwd': str(root.resolve()), 'inputs': inputs,
            'outputs': ['outputs/produced.json', 'outputs/result.json'],
            'input_snapshot': execution.snapshot(root, inputs), 'parents': {}, 'runtime': execution.runtime_context()}
    spec['fingerprint'] = execution.digest(spec)
    record = execution.begin_attempt(root, 'detector', spec, 'logs/detector.log')
    atomic_json(root / 'outputs/produced.json', {'value': 1})
    (root / 'outputs/result.json').write_text(json.dumps(document))
    (root / 'logs/detector.log').write_text('generated value 1\n')
    assert execution.finish_attempt(root, record, 0) == 0
    check_packet(root, record)
    checks = json.loads((root / 'inputs/checks.json').read_text())
    for check in checks['checks']:  # the review examines the result it will accept
        check['evidence'].append({'path': 'outputs/result.json', 'location': '$.bins'})
    atomic_json(root / 'inputs/checks.json', checks)
    pr.open_cycle(root, effective_settings=['inputs/settings.cfg'], stage_receipts=[record['attempt_record']],
                  check_results='inputs/checks.json')
    return root / 'outputs/result.json'


@pytest.fixture
def study(tmp_path, monkeypatch):
    rd = tmp_path / 'run'
    result = produced_run(rd, monkeypatch, table(edges((250, 350), (350, 450), values=[12.0, 4.0])))
    tpl = template(tmp_path / 'template.yaml')
    (tmp_path / 'requester').mkdir()
    requester = template(tmp_path / 'requester/answer.yaml')
    return {'rd': rd, 'result': result, 'tpl': tpl, 'requester': requester, 'base': tmp_path, 'monkeypatch': monkeypatch}


def provisional(study, out='provisional.yaml', **kwargs):
    kwargs.setdefault('deliver_into', study['requester'])
    return rt.fill(study['tpl'], study['result'], study['base'] / out, rundir=study['rd'], claim_scope='diagnostic',
                   base_dir=study['base'], provisional=True, **kwargs)


def at(study, when):
    study['monkeypatch'].setenv('WORKFLOW_STATE_UTC', when)


# ---------------------------------------------------------------- negative first
def test_provisional_without_a_declared_deadline_is_refused(tmp_path, monkeypatch):
    rd = tmp_path / 'run'
    result = produced_run(rd, monkeypatch, table(edges((250, 350), (350, 450))), deadline=None)
    monkeypatch.setenv('WORKFLOW_STATE_UTC', INSIDE)
    with pytest.raises(ValueError, match='deadline declared'):
        rt.fill(template(tmp_path / 't.yaml'), result, tmp_path / 'p.yaml', rundir=rd, claim_scope='diagnostic',
                base_dir=tmp_path, provisional=True)
    assert not (tmp_path / 'p.yaml').exists()


def test_provisional_before_the_margin_is_refused(study):
    at(study, BEFORE)
    before = study['requester'].read_bytes()
    with pytest.raises(ValueError, match='margin has not been reached'):
        provisional(study)
    assert not (study['base'] / 'provisional.yaml').exists() and study['requester'].read_bytes() == before


def test_provisional_from_an_output_no_receipt_pins_is_refused(study):
    at(study, INSIDE)
    hand = study['rd'] / 'inputs/hand-made.json'
    hand.write_text(json.dumps(table(edges((250, 350), (350, 450), values=[99.0, 99.0]))))
    with pytest.raises(ValueError, match='no valid stage receipt pins this output'):
        rt.fill(study['tpl'], hand, study['base'] / 'p.yaml', rundir=study['rd'], claim_scope='diagnostic',
                base_dir=study['base'], provisional=True)
    # Changed receipt-pinned bytes are no longer the captured output either.
    study['result'].write_text(json.dumps(table(edges((250, 350), (350, 450), values=[50.0, 4.0]))))
    with pytest.raises(ValueError, match='no valid stage receipt'):
        provisional(study, 'q.yaml', deliver_into=None)


def test_provisional_after_acceptance_is_refused_in_favour_of_the_reviewed_fill(study):
    accept(study['rd'], scope='diagnostic')
    at(study, INSIDE)
    with pytest.raises(ValueError, match='without --provisional'):
        provisional(study)


def test_provisional_never_supersedes_and_supersession_needs_the_requester_file(study):
    with pytest.raises(ValueError, match='never supersedes'):
        provisional(study, supersedes=study['base'] / 'x.json')
    with pytest.raises(ValueError, match='give deliver-into'):
        rt.fill(study['tpl'], study['result'], study['base'] / 'r.yaml', rundir=study['rd'], claim_scope='diagnostic',
                base_dir=study['base'], supersedes=study['base'] / 'x.json')


# ---------------------------------------------------------------- the margin path
def test_in_margin_provisional_fill_is_labelled_names_the_review_and_delivers(study):
    at(study, INSIDE)
    record = provisional(study)
    out = study['base'] / 'provisional.yaml'
    text = out.read_text()
    assert text.startswith(rt.PROVISIONAL_MARK) and '# provisional: true' in text
    assert f"cycle {record['open_review']['cycle_id']}" in text and 'awaiting_review' in text
    assert [v['value'] for v in yaml.safe_load(text)['dependent_variables'][0]['values']] == [12.0, 4.0]
    assert study['requester'].read_bytes() == out.read_bytes()
    assert record['provisional'] is True and record['acceptance']['accepted'] is False
    assert record['open_review']['state'] == 'awaiting_review' and record['acceptance']['receipt']['stage'] == 'detector'
    assert record['deadline']['seconds_left'] == 1800 and record['delivered_into']['sha256_after'] == sha(out)
    saved = json.loads(Path(str(out) + '.provenance.json').read_text())
    assert saved['provisional'] is True and saved['notice']['open_review']['cycle_id'] == record['open_review']['cycle_id']
    view = study_deadline.state(study['rd'])
    assert view['in_margin'] is True and view['action']['kind'] == 'provisional-fill'
    assert 'margin reached' in view['warning'] and view['action']['open_review']['state'] == 'awaiting_review'


def test_json_template_carries_the_provisional_key(study):
    at(study, INSIDE)
    plain = {'schema_version': 1, 'kind': 'result_template', 'axes': [{'name': 'MET', 'unit': 'GeV'}], 'unit': 'events',
             'bins': [{'low': [250], 'high': [350], 'value': None}, {'low': [350], 'high': [450], 'value': None}]}
    tpl = study['base'] / 't.json'; tpl.write_text(json.dumps(plain))
    rt.fill(tpl, study['result'], study['base'] / 'p.json', rundir=study['rd'], claim_scope='diagnostic',
            base_dir=study['base'], provisional=True)
    filled = json.loads((study['base'] / 'p.json').read_text())
    assert filled['provisional']['provisional'] is True and [b['value'] for b in filled['bins']] == [12.0, 4.0]


def test_reviewed_fill_supersedes_the_provisional_one_in_place(study):
    at(study, INSIDE)
    first = provisional(study)
    first_path = study['base'] / 'provisional.yaml.provenance.json'
    first_bytes = first_path.read_bytes()
    accept(study['rd'], scope='diagnostic')
    # Without naming the provisional record the delivered requester file is refused.
    with pytest.raises(ValueError, match='already holds values'):
        rt.fill(study['tpl'], study['result'], study['base'] / 'a.yaml', rundir=study['rd'], claim_scope='diagnostic',
                base_dir=study['base'], deliver_into=study['requester'])
    reviewed = rt.fill(study['tpl'], study['result'], study['base'] / 'reviewed.yaml', rundir=study['rd'],
                       claim_scope='diagnostic', base_dir=study['base'], deliver_into=study['requester'],
                       supersedes=first_path)
    assert study['requester'].read_bytes() == (study['base'] / 'reviewed.yaml').read_bytes()
    assert not study['requester'].read_text().startswith(rt.PROVISIONAL_MARK)
    assert reviewed['provisional'] is False and reviewed['acceptance']['accepted'] is True
    assert reviewed['delivered_into']['sha256_before'] == first['delivered_into']['sha256_after']
    assert reviewed['supersedes']['provisional_record']['sha256'] == hashlib.sha256(first_bytes).hexdigest()
    assert first_path.read_bytes() == first_bytes  # the provisional record is never rewritten
    link = json.loads(Path(str(first_path) + rt.SUPERSEDED_SUFFIX).read_text())
    assert link['superseded_by']['sha256'] == sha(study['base'] / 'reviewed.yaml.provenance.json')
    assert link['provisional_record']['path'] == str(first_path.resolve())
    with pytest.raises(ValueError, match='already been superseded'):
        rt.fill(study['tpl'], study['result'], study['base'] / 'again.yaml', rundir=study['rd'], claim_scope='diagnostic',
                base_dir=study['base'], deliver_into=study['requester'], supersedes=first_path)
    view = study_deadline.state(study['rd'])
    assert view['action']['kind'] == 'reviewed-fill'


def test_supersession_refuses_a_changed_requester_file(study):
    at(study, INSIDE)
    provisional(study)
    accept(study['rd'], scope='diagnostic')
    study['requester'].write_text(study['requester'].read_text() + '# edited\n')
    with pytest.raises(ValueError, match='requester file changed'):
        rt.fill(study['tpl'], study['result'], study['base'] / 'reviewed.yaml', rundir=study['rd'], claim_scope='diagnostic',
                base_dir=study['base'], deliver_into=study['requester'],
                supersedes=study['base'] / 'provisional.yaml.provenance.json')


# ---------------------------------------------------------------- never reviewed evidence
def test_claims_checkin3_and_accepted_results_refuse_a_provisional_pin(study):
    at(study, INSIDE)
    provisional(study)
    out = study['base'] / 'provisional.yaml'
    for path in (out, Path(str(out) + '.provenance.json'), study['requester']):
        assert rt.provisional_errors([path])
        claim = {'id': 'c1', 'quantity': {'path': str(path), 'sha256': sha(path), 'size': path.stat().st_size},
                 'execution_receipts': [], 'validator_receipts': []}
        with pytest.raises(ValueError, match='provisional_not_reviewed'):
            completion_claims.claim_record(study['rd'], claim, require_trials=False)
        errors = completion_claims.checkin_errors({'claims': [claim]}, study['rd'], kind='deck')
        assert any('provisional_not_reviewed' in e for e in errors)
    accept(study['rd'], scope='diagnostic')
    with pytest.raises(ValueError, match='provisional fill'):
        rt.accepted(out, rundir=study['rd'], claim_scope='diagnostic', base_dir=study['base'])
    assert rt.provisional_errors([study['result'], study['tpl']]) == []


def test_submission_export_refuses_a_provisional_result(tmp_path, monkeypatch):
    from test_submission_export import accepted_analysis
    from ravel.workflow import submission_export as se
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    rd = tmp_path / 'prov'
    result = produced_run(rd, monkeypatch, table(edges((250, 350), (350, 450))))
    monkeypatch.setenv('WORKFLOW_STATE_UTC', INSIDE)
    out = tmp_path / 'work/provisional.yaml'
    rt.fill(template(tmp_path / 't.yaml'), result, out, rundir=rd, claim_scope='diagnostic', base_dir=tmp_path,
            provisional=True)
    document = json.loads(request.read_text()); document['results'].append(str(out))
    request.write_text(json.dumps(document))
    (tmp_path / 'repo').mkdir()
    with pytest.raises(ValueError, match='provisional fill'):
        se.export(request, tmp_path / 'repo')


def test_status_view_never_labels_provisional_as_reviewed_or_machine_as_human(study):
    at(study, INSIDE)
    provisional(study)
    view = study_deadline.state(study['rd'])
    text = json.dumps(view).lower()
    assert view['action']['kind'] == 'provisional-fill'
    assert 'reviewed' not in view['action']['kind'] and 'accepted' not in json.dumps(view['action']['open_review'])
    assert 'human' not in text and 'physicist' not in text
    record = json.loads((study['base'] / 'provisional.yaml.provenance.json').read_text())
    assert record['acceptance']['accepted'] is False and record['physics_validated'] is False
    assert record['open_review']['attestation'] == pr.ATTESTATION


def test_cli_provisional_and_supersedes(study, capsys):
    at(study, INSIDE)
    out = study['base'] / 'cli/provisional.yaml'
    assert cli.main(['fill-template', '--template', str(study['tpl']), '--result', str(study['result']), '--out', str(out),
                     '--rundir', str(study['rd']), '--claim-scope', 'diagnostic', '--base', str(study['base']),
                     '--deliver-into', str(study['requester']), '--provisional']) == 0
    assert json.loads(capsys.readouterr().out)['provisional'] is True
    accept(study['rd'], scope='diagnostic')
    assert cli.main(['fill-template', '--template', str(study['tpl']), '--result', str(study['result']),
                     '--out', str(study['base'] / 'cli/reviewed.yaml'), '--rundir', str(study['rd']),
                     '--claim-scope', 'diagnostic', '--base', str(study['base']), '--deliver-into', str(study['requester']),
                     '--supersedes', str(out) + '.provenance.json']) == 0
    assert json.loads(capsys.readouterr().out)['provisional'] is False
