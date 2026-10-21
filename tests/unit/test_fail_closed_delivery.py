"""Scientific delivery rejects forged, stale, partial and diagnostic promotion."""
import json
from pathlib import Path

import pytest

from ravel.workflow import architecture_receipt as ar
from ravel.workflow import execution, launch_authorization, rdj_anchor


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    for key in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'RAVEL_SESSION_ID', 'CLAUDE_PROJECT_DIR'):
        monkeypatch.delenv(key, raising=False)


def governed(tmp_path, monkeypatch, *, content='{"value": 2}'):
    path = tmp_path / 'value.json'; path.write_text(content)
    command = ['fictional-engine', 'calculate']
    record = {'attempt_id': 'attempt-a', 'authorization_receipt': {'sequence': 2, 'sha256': 'launch-digest'},
              'child_pid': 321, 'command': command,
              'output_snapshot': {str(path): {'files': [{'name': '.', 'sha256': rdj_anchor.sha256_file(path)}]}}}
    auth = {'event': 'authorized', 'sequence': 1, 'sha256': 'auth-digest', 'command': command,
            'context': {'stage': 'calculate'}}
    launch = {'event': 'launched', 'sequence': 2, 'sha256': 'launch-digest', 'authorization_sequence': 1,
              'authorization_sha256': 'auth-digest', 'pid': 321}
    monkeypatch.setattr(execution, 'load_execution', lambda root: {'stages': {'calculate': record}})
    monkeypatch.setattr(rdj_anchor, 'stage_receipt', lambda root, name: record)
    monkeypatch.setattr(launch_authorization, '_events', lambda root: [auth, launch])
    monkeypatch.setattr(launch_authorization, '_historical_errors', lambda value: None)
    return path, record, auth, launch


def test_complete_launch_and_current_bytes_can_be_governed(tmp_path, monkeypatch):
    path, *_ = governed(tmp_path, monkeypatch)
    observed = ar.scientific_admissibility(tmp_path, [{'path': path.name, 'kind': 'number'}])
    assert observed['governed']
    assert observed['artifacts'][0]['receipts'] == ['stage:calculate:attempt-a']


@pytest.mark.parametrize('field', ['authorization', 'pid', 'command', 'stage', 'launch_sha'])
def test_near_matching_launch_does_not_count(tmp_path, monkeypatch, field):
    path, record, auth, launch = governed(tmp_path, monkeypatch)
    if field == 'authorization': launch['authorization_sha256'] = 'wrong'
    if field == 'pid': launch['pid'] = 999
    if field == 'command': auth['command'] = ['different']
    if field == 'stage': auth['context']['stage'] = 'different'
    if field == 'launch_sha': record['authorization_receipt']['sha256'] = 'wrong'
    assert not ar.scientific_admissibility(tmp_path, [{'path': path.name, 'kind': 'number'}])['governed']


def test_authorization_validation_failure_is_not_swallowed_as_pass(tmp_path, monkeypatch):
    path, *_ = governed(tmp_path, monkeypatch)
    def reject(value): raise ValueError('approval changed')
    monkeypatch.setattr(launch_authorization, '_historical_errors', reject)
    decision = ar.scientific_admissibility(tmp_path, [{'path': path.name, 'kind': 'number'}])
    assert not decision['governed'] and 'approval changed' in decision['stages'][0]['reason']


def test_one_direct_figure_blocks_whole_delivery(tmp_path, monkeypatch):
    path, *_ = governed(tmp_path, monkeypatch)
    (tmp_path / 'figure.png').write_bytes(b'fictional image')
    rows = [{'path': path.name, 'kind': 'number'}, {'path': 'figure.png', 'kind': 'figure'}]
    decision = ar.scientific_admissibility(tmp_path, rows)
    assert decision['artifacts'][0]['governed'] and not decision['artifacts'][1]['governed']
    with pytest.raises(ValueError, match='NOT GOVERNED'):
        ar.label_delivery(tmp_path, rows, label='governed')


def test_modified_output_cannot_reuse_launch(tmp_path, monkeypatch):
    path, *_ = governed(tmp_path, monkeypatch)
    path.write_text('{"value": 9}')
    assert not ar.scientific_admissibility(tmp_path, [{'path': path.name, 'kind': 'number'}])['governed']


@pytest.mark.parametrize('document', [{'delivery_label': 'diagnostic'}, {'scientific_acceptance': False}])
def test_diagnostic_output_never_promotes(tmp_path, monkeypatch, document):
    path, *_ = governed(tmp_path, monkeypatch, content=json.dumps(document))
    assert not ar.scientific_admissibility(tmp_path, [{'path': path.name, 'kind': 'number'}])['governed']


def test_empty_population_and_symlink_cannot_pass(tmp_path, monkeypatch):
    path, *_ = governed(tmp_path, monkeypatch)
    (tmp_path / 'alias.json').symlink_to(path)
    for rows in ([], [{'path': 'alias.json', 'kind': 'number'}], [{'path': '../outside', 'kind': 'figure'}]):
        assert not ar.scientific_admissibility(tmp_path, rows)['governed']


def test_authored_receipt_and_accepted_flag_have_no_authority(tmp_path):
    (tmp_path / 'value.json').write_text('{"value": 3, "accepted": true}')
    (tmp_path / 'architecture_receipt.json').write_text('{"accepted": true, "governed": true}')
    rows = [{'path': 'value.json', 'kind': 'number'}]
    result = ar.label_delivery(tmp_path, rows)
    assert result['delivery_label'] == 'diagnostic' and 'NOT GOVERNED' in result['notices']
    with pytest.raises(ValueError, match='accepted delivery refused'):
        ar.label_delivery(tmp_path, rows, label='accepted')


def test_pack_population_includes_pdf_and_every_number():
    result = {'pointers': {'sr_yields': 'y.json', 'exclusion': 'x.json', 'cert': 'c.json'}}
    figures = {'figures': [{'filename': 'f.png', 'pdf': 'f.pdf'}, {'filename': 'g.png'}]}
    rows = ar.pack_artifacts(result, figures)
    assert [r['path'] for r in rows] == ['y.json', 'x.json', 'c.json', 'f.png', 'f.pdf', 'g.png']


def test_verify_pack_recomputes_forged_accepted_label(tmp_path, capsys):
    from ravel.validation import verify_pack
    (tmp_path / 'result.json').write_text(json.dumps({'delivery_label': 'accepted',
        'architecture_receipt': {'accepted': True, 'admissibility': {'governed': True}}}))
    assert verify_pack.main(['verify-pack', str(tmp_path)]) == 1
    assert 'NOT GOVERNED' in capsys.readouterr().out


def test_verify_pack_recomputes_nested_pack_label(tmp_path, capsys):
    from ravel.validation import verify_pack
    pack = tmp_path / 'outputs/pack'
    pack.mkdir(parents=True)
    (pack / 'result.json').write_text(json.dumps({'delivery_label': 'accepted'}))
    assert verify_pack.main(['verify-pack', str(tmp_path)]) == 1
    assert 'outputs/pack/result.json' in capsys.readouterr().out


@pytest.mark.parametrize('name', ['result.json', 'figures.json'])
def test_verify_pack_malformed_pack_is_reported_not_crashed(tmp_path, capsys, name):
    from ravel.validation import verify_pack
    (tmp_path / name).write_text('[1]')
    assert verify_pack.main(['verify-pack', str(tmp_path)]) in (0, 1)
    assert 'NOT GOVERNED' in capsys.readouterr().out


def test_result_pack_diagnostic_default_and_loud_notice(tmp_path, monkeypatch, capsys):
    from test_host_governance import _packable
    from ravel.workflow import result_pack
    _packable(tmp_path)
    argv = ['--rundir', str(tmp_path), '--stat-mode', 'best-sr-counting', '--detector-mode', 'particle-level',
            '--normalization-ledger', 'outputs/normalization-ledger.json']
    assert result_pack.main(argv) == 0
    for name in ('result.json', 'figures.json'):
        value = json.loads((tmp_path / name).read_text())
        assert value['delivery_label'] == 'diagnostic' and value['architecture_receipt']['accepted'] is False
    assert 'NOT GOVERNED' in capsys.readouterr().out
    with pytest.raises(result_pack.PackError, match='NOT GOVERNED'):
        result_pack.main([*argv, '--delivery-label', 'governed'])


def test_governed_successor_cannot_launder_direct_predecessor(tmp_path, monkeypatch):
    path, record, *_ = governed(tmp_path, monkeypatch)
    record['parents'] = {'direct': 'parent-digest'}
    assert not ar.scientific_admissibility(tmp_path, [{'path': path.name, 'kind': 'number'}])['governed']


def test_accepted_label_needs_exact_reviewed_population(tmp_path, monkeypatch):
    path, *_ = governed(tmp_path, monkeypatch)
    monkeypatch.setattr(ar, '_role_observations', lambda root: {
        'status': 'observed', 'roles': [], 'missing': [], 'dispatches': [], 'blocking_points': [], 'errors': []})
    review = {'state': 'accepted', 'accepted': True, 'claim_scope': 'computed', 'errors': [], 'artifacts': []}
    monkeypatch.setattr(ar, '_review_observation', lambda root: review)
    rows = [{'path': path.name, 'kind': 'number'}]
    with pytest.raises(ValueError, match='accepted delivery refused'):
        ar.label_delivery(tmp_path, rows, label='accepted')
    review['artifacts'] = [{'path': str(path), 'sha256': rdj_anchor.sha256_file(path)}]
    assert ar.label_delivery(tmp_path, rows, label='accepted')['delivery_label'] == 'accepted'
    review['claim_scope'] = 'diagnostic'
    with pytest.raises(ValueError, match='accepted delivery refused'):
        ar.label_delivery(tmp_path, rows, label='accepted')


def test_requester_diagnostic_and_receipt_integrity(tmp_path, monkeypatch):
    from test_requester_delivery import study, layout
    from ravel.workflow import requester_delivery
    rd = study(tmp_path, monkeypatch)
    ws = tmp_path / 'delivered'
    index = requester_delivery.deliver(rd, layout(), ws)
    assert index['delivery_label'] == 'diagnostic'
    assert not any(r['category'] == 'accepted_result' for r in index['files'])
    assert 'NOT GOVERNED' in (ws / 'note.md').read_text()
    saved = ws / requester_delivery.INDEX
    index['architecture_receipt']['accepted'] = True
    saved.write_text(json.dumps(index))
    with pytest.raises(ValueError, match='architecture receipt changed'):
        requester_delivery.verify(ws)


def test_requester_diagnostic_index_cannot_carry_accepted_category(tmp_path, monkeypatch):
    from test_requester_delivery import study, layout
    from ravel.workflow import requester_delivery
    rd = study(tmp_path, monkeypatch)
    ws = tmp_path / 'delivered'
    index = requester_delivery.deliver(rd, layout(), ws)
    rows = [row for row in index['files'] if row['category'] == 'diagnostic_result']
    assert rows
    for row in rows:
        row['category'] = 'accepted_result'
    (ws / requester_delivery.INDEX).write_text(json.dumps(index))
    with pytest.raises(ValueError, match='diagnostic delivery'):
        requester_delivery.verify(ws)


def test_explicit_legacy_scientific_acceptance_cannot_hide_as_diagnostic(tmp_path, capsys):
    from ravel.validation import verify_pack
    (tmp_path / 'result.json').write_text('{"scientific_acceptance": true, "delivery_label": "diagnostic"}')
    assert verify_pack.main(['verify-pack', str(tmp_path)]) == 1
    assert 'NOT GOVERNED' in capsys.readouterr().out


def test_requester_rejects_receipt_for_different_delivered_bytes(tmp_path, monkeypatch):
    from test_requester_delivery import study, layout
    from ravel.workflow import requester_delivery
    rd = study(tmp_path, monkeypatch)
    ws = tmp_path / 'delivered'
    index = requester_delivery.deliver(rd, layout(), ws)
    index['delivery_label'] = 'accepted'
    for row in index['files']:
        if row['category'] == 'diagnostic_result':
            row['category'] = 'accepted_result'
    receipt = index['architecture_receipt']
    receipt['admissibility']['artifacts'] = []
    receipt['sha256'] = ar._digest({k: v for k, v in receipt.items() if k != 'sha256'})
    (ws / requester_delivery.INDEX).write_text(json.dumps(index))
    with pytest.raises(ValueError, match='artifact population'):
        requester_delivery.verify(ws)
