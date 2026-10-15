"""Exact supplied prompts, conservative model identity and complete accounting."""
import hashlib
import json
import math
from pathlib import Path

import pytest
from test_worker_audit import worker, put


def delivery(sha='a' * 64, size=64, mechanism='prompt_first_block', path='/synthetic/project/AGENTS.md', flag=None):
    """A delivery record in the shape the launchers write into their receipts."""
    return {'schema_version': 1, 'path': path, 'sha256': sha, 'bytes': size, 'mechanism': mechanism, 'flag': flag,
            'position': 'before_ravel_instructions', 'ambient': {'ancestor_files': [], 'cli_reported_loaded': None}}


DOCUMENT_TEXT = 'Synthetic project rule 1: cite every number.\n'
DOCUMENT_SHA = hashlib.sha256(DOCUMENT_TEXT.encode()).hexdigest()


def oneshot(root, prompt='  Inspect ANA-0001.\n\n', model='model-test-20260101'):
    from ravel.workflow.cli_agent_host import build_prompt
    parameters = {'model': 'model-alias', 'instructions': prompt, 'output_schema': None}
    context = {'role': 'reviewer'}
    rendered = build_prompt(parameters, context)
    request = {'kind': 'external_agent_request', 'parameters': parameters, 'context': context,
               'request': {'request_id': 'req-1', 'node_id': 'review'}, 'sha256': 'b' * 64}
    put(root / 'requests/a1.json', request)
    receipt = {'kind': 'agent-session-receipt', 'content': {'request_sha256': 'b' * 64,
        'prompt_sha256': hashlib.sha256(rendered.encode()).hexdigest()},
        'cli_reported': {'session_id': 's-review', 'observed_model': model,
                         'usage': {'input_tokens': 8, 'output_tokens': 2, 'total_tokens': 10}},
        'executable': {'cli_version': '1.2'}, 'invocation': {'host_invocation_id': 'h-1'},
        # A flag carried the declared document, so this session's prompt is the template alone.
        'configuration': {'project_instructions': delivery(
            sha=DOCUMENT_SHA, size=len(DOCUMENT_TEXT.encode()), path=str(root / 'declared-document.md'),
            mechanism='system_prompt_append_flag', flag='--instructions-file')},
        'process': {'started_utc': '2026-10-11T00:00:00Z', 'elapsed_seconds': 2}}
    put(root / 'external-responses/review-a1.receipt.json', receipt)
    (root / 'declared-document.md').write_text(DOCUMENT_TEXT)
    return rendered


def test_worker_and_oneshot_census_preserves_both_prompts(tmp_path):
    from ravel.workflow import worker_audit
    worker(tmp_path, 'production')
    prompt = oneshot(tmp_path)
    audit = worker_audit.build(tmp_path)
    assert len(audit['sessions']) == 2
    assert any(r['prompt'] == prompt for r in audit['records'])


def test_log_four_fields_hash_and_supplied_prices(tmp_path):
    from ravel.workflow import prompt_log
    worker(tmp_path, 'production')
    prompt = oneshot(tmp_path)
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 2
    review = next(r for r in log['rows'] if r['session_id'] == 's-review')
    assert review['prompt'] == prompt
    assert hashlib.sha256(prompt.encode()).hexdigest() == review['prompt_sha256']
    assert review['model_requested'] == 'model-alias'
    assert review['instruction_document_sha256'] == DOCUMENT_SHA
    assert review['system_prompt_append'] == DOCUMENT_TEXT
    assert log['totals']['total_tokens'] == 21
    assert 'cost_estimate' not in log['totals']
    prices = {r['model_reported']: {'input_per_million': 2, 'output_per_million': 4} for r in log['rows']}
    priced = prompt_log.build(tmp_path, price_table=prices)
    assert priced['totals']['cost_estimate'] == pytest.approx(math.fsum((16 * 2, 5 * 4)) / 1e6)
    written = prompt_log.write(priced, tmp_path / 'out')
    assert Path(written['jsonl']).exists() and Path(written['markdown']).exists()
    assert prompt in Path(written['markdown']).read_text()


@pytest.mark.parametrize('model,exact', [('model-alias', False), ('model-test-20260101', True)])
def test_reported_alias_is_flagged_without_invented_suffix(tmp_path, model, exact):
    from ravel.workflow import prompt_log
    oneshot(tmp_path, model=model)
    row = prompt_log.build(tmp_path)['rows'][0]
    assert row['model_reported'] == model and row['model_build_exact'] is exact
    assert ('model build inexact' in row['flags']) is (not exact)


def test_new_unrecorded_model_site_fails_census(tmp_path):
    from ravel.workflow import prompt_log
    source = tmp_path / 'ravel/new_call.py'
    source.parent.mkdir()
    source.write_text('import subprocess\ndef spend():\n    subprocess.run(["codex", "exec", "prompt"])\n')
    census = prompt_log.call_site_census(tmp_path / 'ravel')
    assert census['gaps'] and not census['complete']
    assert census['rows'][0]['record'] is None


def test_mutated_prompt_is_visible_as_gap(tmp_path):
    from ravel.workflow import prompt_log
    oneshot(tmp_path)
    path = tmp_path / 'requests/a1.json'
    request = json.loads(path.read_text())
    request['parameters']['instructions'] = 'changed'
    put(path, request)
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 1
    assert log['rows'][0]['prompt'] is None
    assert any('prompt' in g['reason'] for g in log['gaps'])


def test_provider_call_writes_full_wire_prompt_and_failure(tmp_path):
    from ravel.workflow import provider_transport, prompt_log
    class Control:
        root = tmp_path
        attempt_id = 'a1'
        node_id = 'answer'
        def call(self, label, kind, request, function, **kwargs):
            return function()
    control = provider_transport.audit_control(Control(), {'role': 'answerer'})
    body = {'model': 'model-test-20260101', 'instructions': ' exact\n', 'input': []}
    result = {'usage': {'input_tokens': 3, 'output_tokens': 4, 'total_tokens': 7},
              'transport': {'observed_model': 'model-test-20260101', 'response_id': 'response-1'}}
    assert control.call('responses', 'model', body, lambda: result) == result
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 1 and json.loads(log['rows'][0]['prompt']) == body
    with pytest.raises(ValueError):
        control.call('anthropic', 'model', body, lambda: (_ for _ in ()).throw(ValueError('failure')))
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 2 and any(r['total_tokens'] is None for r in log['rows'])


def custody_of(run, monkeypatch):
    """The run's custody folder under a temporary state directory, where a worker's prompt file lives."""
    from ravel.workflow import broker
    state = run.parent / 'state'
    monkeypatch.setenv('RAVEL_STATE_DIR', str(state))
    folder = state.resolve() / 'workers' / broker.digest(str(run.resolve()))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def worker_with_prompt(run, stdin, text, **transport):
    receipt_pin, _ = worker(run, 'production')
    receipt_path = Path(receipt_pin['path'])
    receipt = json.loads(receipt_path.read_text())
    stdin.parent.mkdir(parents=True, exist_ok=True)
    stdin.write_bytes(text.encode())
    receipt['transport'] = {'stdin': {'path': str(stdin), 'sha256': hashlib.sha256(text.encode()).hexdigest()},
                            **transport}
    put(receipt_path, receipt)
    return receipt_path


def test_worker_exact_stdin_and_duplicate_receipt_are_collected_once(tmp_path, monkeypatch):
    from ravel.workflow import prompt_log
    root = tmp_path / 'run'
    root.mkdir()
    text = '  ANA-0002 π\r\n```text\nexact\n'
    worker_with_prompt(root, custody_of(root, monkeypatch) / 'production.1.prompt.txt', text)
    tmp_path = root
    rendered = oneshot(tmp_path)
    original = tmp_path / 'external-responses/review-a1.receipt.json'
    put(tmp_path / 'transport-receipts/nested.json', {'launcher_receipt': json.loads(original.read_text())})
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 2
    assert next(r['prompt'] for r in log['rows'] if r['role'] == 'production') == text
    assert next(r['prompt'] for r in log['rows'] if r['role'] == 'reviewer') == rendered
    assert sum(t['total_tokens'] for t in log['totals']['by_role'].values()) == log['totals']['total_tokens']


def test_supplied_transcript_and_hook_only_prompt(tmp_path):
    from ravel.workflow import prompt_log
    from test_agent_audit import jsonl, codex_rows
    transcript = jsonl(tmp_path / 'rollout.jsonl', codex_rows())
    hook = tmp_path / '.ravel/agent-audit/prompts.jsonl'
    put(hook, {'event': 'prompt_submitted', 'session_id': 'interactive-1',
               'timestamp': '2026-01-01T00:00:00+02:00', 'prompt': '  ANA-0003\n'})
    log = prompt_log.build(tmp_path, [transcript, transcript])
    assert len(log['rows']) == 3
    assert next(r for r in log['rows'] if r['session_id'] == 'interactive-1')['total_tokens'] is None
    assert log['totals']['total_tokens'] == 2630


def test_actual_host_seam_records_fake_http_without_network(tmp_path, monkeypatch):
    from ravel.workflow import agent_host, prompt_log
    from test_provider_transport import node, request, install_http, document, capabilities, Control
    install_http(monkeypatch, document('chat_completions'))
    control = Control()
    control.root = tmp_path
    control.node_id = 'role'
    control.attempt_id = 'a1'
    host = agent_host.AgentHost(adapter='chat_completions', endpoint='http://127.0.0.1/v1/chat/completions',
        privacy='local_only', local_models=['fixture-model'], capabilities=capabilities())
    n = node()
    host.execute(n, request(n), control)
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 1 and log['rows'][0]['total_tokens'] == 17
    assert len(control.calls) == 1


def test_provider_journal_and_graph_census_do_not_double_count(tmp_path):
    from ravel.workflow import prompt_log, provider_transport, agent_graph, worker_audit
    class Control:
        root = tmp_path
        node_id = 'answer'
        attempt_id = 'a1'
        def call(self, label, kind, request, function, **kwargs):
            result = function()
            call_id = agent_graph.digest({'attempt_id': self.attempt_id, 'label': label})
            put(tmp_path / 'calls' / (call_id + '.json'), {'kind': 'model', 'node_id': self.node_id,
                'attempt_id': self.attempt_id, 'call_id': call_id, 'result': result, 'status': 'completed'})
            put(tmp_path / 'graph_state.json', {'calls': {call_id: {'kind': 'model', 'node_id': self.node_id}}})
            put(tmp_path / 'graph_spec.json', {'nodes': [{'id': 'answer', 'role': 'answerer'}]})
            return result
    control = provider_transport.audit_control(Control(), {'role': 'answerer'})
    result = {'usage': {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3},
              'transport': {'observed_model': 'model-test-20260101', 'response_id': 'response-1'}}
    control.call('responses', 'model', {'model': 'requested'}, lambda: result)
    assert len(worker_audit.build(tmp_path)['sessions']) == 1
    assert prompt_log.build(tmp_path)['totals']['total_tokens'] == 3


def test_cli_dispatch_and_existing_audit_delegate(tmp_path, monkeypatch):
    from ravel import cli
    from ravel.workflow import prompt_log
    oneshot(tmp_path)
    assert cli.main(['audit', 'prompt-log', '--rundir', str(tmp_path), '--out', str(tmp_path / 'out')]) == 0
    monkeypatch.setattr(cli, '_audit', lambda args: 17)
    assert cli.main(['audit', '--root', str(tmp_path)]) == 17


def test_renderer_change_cannot_claim_exact_text_and_export_refuses_overwrite(tmp_path, monkeypatch):
    from ravel.workflow import prompt_log, cli_agent_host
    oneshot(tmp_path)
    monkeypatch.setattr(cli_agent_host, 'build_prompt', lambda *args: 'changed renderer')
    log = prompt_log.build(tmp_path)
    assert log['rows'][0]['prompt'] is None
    prompt_log.write(log, tmp_path / 'out')
    with pytest.raises(FileExistsError):
        prompt_log.write(log, tmp_path / 'out')


@pytest.mark.parametrize('rate', [-1, float('nan'), True])
def test_supplied_price_validation(tmp_path, rate):
    from ravel.workflow import prompt_log
    oneshot(tmp_path)
    with pytest.raises(ValueError, match='price table'):
        prompt_log.build(tmp_path, price_table={'model-test-20260101': {'input_per_million': rate, 'output_per_million': 1}})


def test_unavailable_worker_prompt_retains_a_row(tmp_path):
    from ravel.workflow import prompt_log
    _, transcript = worker(tmp_path, 'production', reported=False)
    Path(transcript['path']).unlink()
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 1
    assert log['rows'][0]['prompt'] is None and log['rows'][0]['total_tokens'] is None
    assert not log['complete']


@pytest.mark.parametrize('location', ['calls/x.json', 'requests/x.json', 'transport-receipts/x.json'])
def test_non_object_evidence_file_is_a_gap_not_a_crash(tmp_path, location):
    from ravel.workflow import prompt_log
    oneshot(tmp_path)
    put(tmp_path / location, [1, 2])
    put(tmp_path / 'prompt-receipts/y.json', {'launcher_receipt': 'not an object'})
    log = prompt_log.build(tmp_path)
    assert len(log['rows']) == 1
    assert any(g.get('path') == str(tmp_path / location) for g in log['gaps'])
    assert any(g.get('path') == str(tmp_path / 'prompt-receipts/y.json') for g in log['gaps'])


def test_each_row_flag_is_one_gap(tmp_path):
    from ravel.workflow import prompt_log
    oneshot(tmp_path, model='model-alias')
    log = prompt_log.build(tmp_path)
    assert [g['reason'] for g in log['gaps'] if 'source' in g] == ['model build inexact']


def test_receipt_without_request_digest_takes_no_identity_from_an_unbound_request(tmp_path):
    from ravel.workflow import prompt_log
    oneshot(tmp_path)
    path = tmp_path / 'external-responses/review-a1.receipt.json'
    receipt = json.loads(path.read_text())
    del receipt['content']['request_sha256']
    put(path, receipt)
    path = tmp_path / 'requests/a1.json'
    request = json.loads(path.read_text())
    del request['sha256']
    request['parameters']['instructions'] = 'another request'
    put(path, request)
    row = prompt_log.build(tmp_path)['rows'][0]
    assert row['prompt'] is None and row['role'] is None and row['model_requested'] is None
    assert row['request_source'] is None


def test_provider_record_keeps_requested_model_when_the_body_omits_it(tmp_path):
    from ravel.workflow import provider_transport, prompt_log
    class Control:
        root = tmp_path
        attempt_id = 'a1'
        node_id = 'answer'
        def call(self, label, kind, request, function, **kwargs):
            return function()
    node = {'role': 'answerer', 'parameters': {'model': 'model-requested'}}
    control = provider_transport.audit_control(Control(), node)
    with pytest.raises(ValueError):
        control.call('gemini', 'model', {'contents': []}, lambda: (_ for _ in ()).throw(ValueError('failure')))
    row = prompt_log.build(tmp_path)['rows'][0]
    assert row['model_requested'] == 'model-requested' and row['model_reported'] is None
    assert row['status'] == 'failed' and row['total_tokens'] is None


def test_recording_leaves_the_provider_result_unchanged(tmp_path):
    from ravel.workflow import provider_transport
    class Unbound:
        def call(self, label, kind, request, function, **kwargs):
            return function()
    class Bound(Unbound):
        root = tmp_path
        attempt_id = 'a1'
        node_id = 'answer'
    expected = {'usage': {'input_tokens': 3, 'output_tokens': 4, 'total_tokens': 7},
                'transport': {'observed_model': 'model-test-20260101', 'response_id': 'response-1'}}
    for control in (Unbound(), Bound()):
        recording = provider_transport.audit_control(control, {'role': 'answerer'})
        result = recording.call('responses', 'model', {'model': 'model-alias'}, lambda: json.loads(json.dumps(expected)))
        assert result == expected
    assert len(list((tmp_path / 'prompt-receipts').glob('*.json'))) == 1


def test_worker_prompt_is_read_only_from_this_run_custody_folder(tmp_path, monkeypatch):
    """A worker receipt names its prompt in custody, outside the run; no other outside path is read."""
    from ravel.workflow import prompt_log
    root = tmp_path / 'run'
    root.mkdir()
    custody = custody_of(root, monkeypatch)
    text = '===== PROJECT INSTRUCTIONS =====\nRule 1.\n===== END OF PROJECT INSTRUCTIONS =====\n\nYou are the role.\n'
    record = delivery(sha='c' * 64)
    receipt_path = worker_with_prompt(root, custody / 'production.1.prompt.txt', text, project_instructions=record)
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] == text and 'full prompt unknown' not in row['flags']
    # The log's document hash is the one the receipt's delivery record holds.
    assert row['instruction_document_sha256'] == record['sha256'] == 'c' * 64
    assert row['instruction_delivery'] == 'prompt_first_block'
    receipt = json.loads(receipt_path.read_text())
    for name, outside in (('elsewhere', tmp_path / 'elsewhere/prompt.txt'),
                          ('another run', custody.parent / ('0' * 64) / 'production.1.prompt.txt'),
                          ('inside the run', root / 'agent-work/production/1/input.txt')):
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(text.encode())
        receipt['transport']['stdin']['path'] = str(outside)
        put(receipt_path, receipt)
        log = prompt_log.build(root)
        assert log['rows'][0]['prompt'] is None, name
        assert any('custody' in str(g.get('reason')) for g in log['gaps']), name
    link = custody / 'linked.prompt.txt'
    link.symlink_to(tmp_path / 'elsewhere/prompt.txt')
    receipt['transport']['stdin']['path'] = str(link)
    put(receipt_path, receipt)
    assert prompt_log.build(root)['rows'][0]['prompt'] is None
    receipt['transport']['stdin']['path'] = str(custody / 'production.1.prompt.txt')
    put(receipt_path, receipt)
    (custody / 'production.1.prompt.txt').write_bytes(text.encode() + b'changed')
    assert prompt_log.build(root)['rows'][0]['prompt'] is None


def instruction_block(monkeypatch):
    """The first-block renderer of the session-instructions module (a stand-in where that module is absent)."""
    import importlib.util
    import sys
    import types
    if importlib.util.find_spec('ravel.workflow.project_instructions') is not None:
        from ravel.workflow import project_instructions
        return project_instructions.block

    def block(text, pinned):
        return (f'===== DECLARED DOCUMENT {pinned["sha256"]} {pinned["bytes"]} =====\n' + text
                + ('' if text.endswith('\n') else '\n') + '===== END =====\n\n')
    stand_in = types.ModuleType('ravel.workflow.project_instructions')
    stand_in.block = block
    monkeypatch.setitem(sys.modules, 'ravel.workflow.project_instructions', stand_in)
    import ravel.workflow
    monkeypatch.setattr(ravel.workflow, 'project_instructions', stand_in, raising=False)
    return block


@pytest.mark.parametrize('text', ['Rule 1: cite every number.\n', 'Règle 1 π\r\nRule 2 without a final newline'])
def test_oneshot_prompt_with_the_declared_document_is_rebuilt_to_its_hash(tmp_path, monkeypatch, text):
    from ravel.workflow import prompt_log
    block = instruction_block(monkeypatch)
    root = tmp_path / 'run'
    template = oneshot(root)
    document = tmp_path / 'project/AGENTS.md'
    document.parent.mkdir()
    document.write_bytes(text.encode('utf-8'))
    record = delivery(sha=hashlib.sha256(text.encode('utf-8')).hexdigest(), size=len(text.encode('utf-8')),
                      path=str(document))
    sent = block(text, record) + template
    path = root / 'external-responses/review-a1.receipt.json'
    receipt = json.loads(path.read_text())
    receipt['configuration']['project_instructions'] = record
    receipt['content']['prompt_sha256'] = hashlib.sha256(sent.encode('utf-8')).hexdigest()
    put(path, receipt)
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] == sent and 'full prompt unknown' not in row['flags']
    assert row['prompt_sha256'] == receipt['content']['prompt_sha256']
    assert row['instruction_document_sha256'] == record['sha256']
    assert row['instruction_delivery'] == 'prompt_first_block' and row['system_prompt_append'] is None
    # The pinned bytes are gone: the prompt stays unknown and the row says why.
    document.write_bytes(text.encode('utf-8') + b'Rule 9.\n')
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] is None and row['instruction_document_sha256'] == record['sha256']
    assert 'full prompt unknown' in row['flags'] and 'declared document bytes unavailable' in row['flags']


def test_oneshot_flag_delivery_keeps_the_document_text_with_the_row(tmp_path):
    """Behind a flag the document is outside the prompt hash; the row carries it, checked against the record."""
    from ravel.workflow import prompt_log
    root = tmp_path / 'run'
    template = oneshot(root)
    text = 'Rule 1: cite every number.\n'
    document = tmp_path / 'project/AGENTS.md'
    document.parent.mkdir()
    document.write_text(text)
    path = root / 'external-responses/review-a1.receipt.json'
    receipt = json.loads(path.read_text())
    receipt['configuration']['project_instructions'] = delivery(
        sha=hashlib.sha256(text.encode()).hexdigest(), size=len(text.encode()), path=str(document),
        mechanism='system_prompt_append_flag', flag='--instructions-file')
    put(path, receipt)
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] == template and row['system_prompt_append'] == text
    assert row['instruction_delivery'] == 'system_prompt_append_flag'
    document.write_text(text + 'changed')
    row = prompt_log.build(root)['rows'][0]
    assert row['system_prompt_append'] is None and 'declared document bytes unavailable' in row['flags']


def test_log_document_hash_equals_the_receipt_record_or_is_flagged(tmp_path):
    from ravel.workflow import prompt_log
    oneshot(tmp_path)
    path = tmp_path / 'external-responses/review-a1.receipt.json'
    receipt = json.loads(path.read_text())
    row = prompt_log.build(tmp_path)['rows'][0]
    assert row['instruction_document_sha256'] == receipt['configuration']['project_instructions']['sha256']
    # Fields no launcher writes are not read.
    receipt['configuration'].pop('project_instructions')
    receipt['instruction_document_sha256'] = 'd' * 64
    put(path, receipt)
    request = json.loads((tmp_path / 'requests/a1.json').read_text())
    request['context']['instruction_document_sha256'] = 'e' * 64
    put(tmp_path / 'requests/a1.json', request)
    row = prompt_log.build(tmp_path)['rows'][0]
    assert row['instruction_document_sha256'] is None and row['instruction_delivery'] is None
    receipt['configuration']['project_instructions'] = {'sha256': 'not a digest'}
    put(path, receipt)
    row = prompt_log.build(tmp_path)['rows'][0]
    assert row['instruction_document_sha256'] is None and 'instruction delivery record malformed' in row['flags']


def test_worker_row_takes_reported_model_and_version_from_the_receipt(tmp_path):
    """The worker transcript row names no model; the receipt's observed model reaches the log unchanged."""
    from ravel.workflow import prompt_log
    receipt_pin, transcript = worker(tmp_path, 'production')
    row = json.loads(Path(transcript['path']).read_text())
    row.update(models=[], model=None, cli_version=None)
    put(Path(transcript['path']), row)
    receipt_path = Path(receipt_pin['path'])
    receipt = json.loads(receipt_path.read_text())
    receipt['model'] = {'requested': 'model-alias', 'observed': 'model-test-20260101'}
    receipt['cli_version'] = '3.4.5'
    receipt['transcript'] = {**receipt['transcript'], 'sha256': hashlib.sha256(Path(transcript['path']).read_bytes()).hexdigest(),
                             'size': Path(transcript['path']).stat().st_size}
    put(receipt_path, receipt)
    logged = prompt_log.build(tmp_path)['rows'][0]
    assert logged['model_requested'] == 'model-alias' and logged['model_reported'] == 'model-test-20260101'
    assert logged['model_build_exact'] is True and logged['cli_version'] == '3.4.5'
    receipt['model']['observed'] = 'model-alias'
    put(receipt_path, receipt)
    logged = prompt_log.build(tmp_path)['rows'][0]
    assert logged['model_reported'] == 'model-alias' and logged['model_build_exact'] is False


def test_loop_turns_are_collected_once_from_effect_ledger(tmp_path, monkeypatch):
    from test_ravel_loop import setup, wire
    from ravel.workflow import prompt_log
    script = [wire('chat_completions', name, args) for name, args in
              [('echo', {'x': 1}), ('submit_final', {'answer': 2})]]
    for raw in script:
        raw['model'] = 'model-test-20260101'
    loop, sender, _, _ = setup(tmp_path, monkeypatch, script)
    loop.run('  Synthetic request π\n')
    loop.run('  Synthetic request π\n')
    log = prompt_log.build(loop.scope_root)
    assert len(log['rows']) == len(sender.calls) == 2
    assert len({r['call_id'] for r in log['rows']}) == 2
    assert [json.loads(r['prompt']) for r in log['rows']] == sender.calls
    assert all(r['stream'] == 'loop' and r['model_requested'] == 'synthetic-model'
               and r['model_reported'] == 'model-test-20260101' for r in log['rows'])
    assert log['totals']['total_tokens'] == sum(r['total_tokens'] for r in log['rows']) > 0
    # An unfinished model effect is still a turn; unknown billing is not zero.
    path = Path(log['rows'][0]['source']['path'])
    record = json.loads(path.read_text())
    record.pop('result')
    record.pop('result_sha256')
    record['status'] = 'ambiguous'
    put(path, record)
    rows, _ = prompt_log.receipt_records(loop.scope_root)
    assert len(rows) == 2
    unfinished = next(r for r in rows if r['status'] == 'ambiguous')
    # The request was kept with the effect before it was sent, so the turn still has its exact prompt.
    assert json.loads(unfinished['prompt']) in sender.calls and unfinished['total_tokens'] is None


def test_sender_site_requires_an_active_collection_route(tmp_path, monkeypatch):
    from ravel.workflow import prompt_log
    source = tmp_path / 'ravel/workflow/ravel_chat_model.py'
    source.parent.mkdir(parents=True)
    source.write_text('class RavelTransportChatModel:\n    def turn(self):\n        def dispatch():\n            self.sender({})\n')
    census = prompt_log.call_site_census(tmp_path / 'ravel')
    assert len(census['rows']) == 1 and census['complete']
    monkeypatch.setitem(prompt_log.EFFECT_COLLECTORS, 'ravel-loop', None)
    census = prompt_log.call_site_census(tmp_path / 'ravel')
    assert not census['complete'] and census['rows'][0]['record'] is None
    with pytest.raises(AssertionError):
        test_source_census_has_no_unmapped_spending_site()


def test_new_sender_is_an_unmapped_spending_site(tmp_path):
    from ravel.workflow import prompt_log
    source = tmp_path / 'ravel/new_sender.py'
    source.parent.mkdir()
    source.write_text('def spend(self):\n    return self.sender({})\n')
    census = prompt_log.call_site_census(tmp_path / 'ravel')
    assert census['rows'] and census['gaps'] and not census['complete']


def test_rootless_provider_records_before_dispatch_without_overwriting(tmp_path, monkeypatch):
    from ravel.workflow import prompt_log, provider_transport
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('RAVEL_SESSION_ID', 'synthetic-session')
    class Control:
        def call(self, label, kind, request, function, **kwargs):
            return function()
    result = {'usage': {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3},
              'transport': {'observed_model': 'model-test-20260101', 'response_id': 'response-1'}}
    def dispatched():
        records = [json.loads(p.read_text()) for p in tmp_path.glob('prompt-log/*/prompt-receipts/*.json')]
        assert sum(r['status'] == 'started' for r in records) == 1
        return result
    control = provider_transport.audit_control(Control(), {'role': 'answerer'})
    for _ in range(2):
        assert control.call('responses', 'model', {'model': 'requested'}, dispatched) is result
    log = prompt_log.build(tmp_path / 'prompt-log')
    assert len(log['rows']) == 2
    assert all(r['rootless'] and r['recording_session_id'] == 'synthetic-session' for r in log['rows'])
    assert log['totals']['total_tokens'] == 6


def test_coverage_discloses_unrecorded_oneshot_failures(tmp_path, monkeypatch):
    from ravel.workflow import prompt_log
    monkeypatch.setattr(prompt_log, 'call_site_census', lambda: {'rows': [], 'gaps': [], 'complete': True})
    log = prompt_log.build(tmp_path)
    assert not log['complete']
    assert 'one-shot failures are not yet recorded' in ' '.join(g['reason'] for g in log['gaps'])
    exported = prompt_log.write(log, tmp_path / 'out')
    assert 'one-shot failures are not yet recorded' in Path(exported['markdown']).read_text()


def first_block_receipt(root, monkeypatch, text='Rule 1: cite every number.\n'):
    """A one-shot receipt whose declared document travelled in the prompt's first block; returns what was sent."""
    block = instruction_block(monkeypatch)
    template = oneshot(root)
    document = root.parent / 'project/AGENTS.md'
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(text)
    record = delivery(sha=hashlib.sha256(text.encode()).hexdigest(), size=len(text.encode()), path=str(document))
    sent = block(text, record) + template
    path = root / 'external-responses/review-a1.receipt.json'
    receipt = json.loads(path.read_text())
    receipt['configuration']['project_instructions'] = record
    receipt['content']['prompt_sha256'] = hashlib.sha256(sent.encode()).hexdigest()
    put(path, receipt)
    return sent, path, receipt, document, record


def test_oneshot_prompt_kept_beside_the_receipt_survives_a_changed_document(tmp_path, monkeypatch):
    """The launcher keeps the exact prompt beside its receipt; nothing has to be rebuilt from files that can change."""
    from ravel.workflow import prompt_log
    root = tmp_path / 'run'
    sent, path, receipt, document, record = first_block_receipt(root, monkeypatch)
    kept = path.with_suffix('.prompt.txt')
    kept.write_text(sent)
    (root / 'requests/a1.json').unlink()                # no request file to rebuild the prompt from
    document.write_text('Rule 1 was replaced by an approved re-pin.\n')
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] == sent and row['prompt_sha256'] == receipt['content']['prompt_sha256']
    assert 'full prompt unknown' not in row['flags'] and 'declared document bytes unavailable' not in row['flags']
    assert row['instruction_document_sha256'] == record['sha256'] and row['prompt_source']['path'] == str(kept)
    # A kept file that does not hash to the receipt's prompt digest is not the prompt.
    kept.write_text(sent + 'edited')
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] is None and 'kept prompt differs from the receipt prompt digest' in row['flags']
    kept.unlink()
    kept.symlink_to(document)
    assert prompt_log.build(root)['rows'][0]['prompt'] is None


def test_relayed_session_prompt_is_read_from_beside_the_session_record(tmp_path, monkeypatch):
    """A host relay writes no request file; the prompt kept beside its session record is the row's prompt."""
    from ravel.workflow import prompt_log
    root = tmp_path / 'run'
    sent, path, receipt, document, record = first_block_receipt(root, monkeypatch)
    path.unlink()
    (root / 'requests/a1.json').unlink()
    put(root / 'graph/transport-receipts/req-1-a1.json', {'schema_version': 1, 'kind': 'transport-session-record',
        'request_id': 'req-1', 'attempt_id': 'a1', 'launcher_receipt': receipt})
    (root / 'graph/transport-receipts/req-1-a1.prompt.txt').write_text(sent)
    rows = prompt_log.build(root)['rows']
    assert len(rows) == 1 and rows[0]['prompt'] == sent and 'full prompt unknown' not in rows[0]['flags']


def test_oneshot_prompt_is_rebuilt_from_the_text_custody_kept_for_an_earlier_pin(tmp_path, monkeypatch):
    """After an approved re-pin the file holds other bytes; the run's custody still holds the pinned text."""
    from ravel.workflow import prompt_log
    root = tmp_path / 'run'
    sent, path, receipt, document, record = first_block_receipt(root, monkeypatch)
    custody = custody_of(root, monkeypatch)
    text = document.read_text()
    document.write_text('Rule 1 was replaced by an approved re-pin.\n')
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] is None and 'declared document bytes unavailable' in row['flags']
    (custody / ('project-instructions.' + record['sha256'] + '.md')).write_text(text)
    row = prompt_log.build(root)['rows'][0]
    assert row['prompt'] == sent and 'declared document bytes unavailable' not in row['flags']
    (custody / ('project-instructions.' + record['sha256'] + '.md')).write_text(text + 'edited')
    assert prompt_log.build(root)['rows'][0]['prompt'] is None


def test_loop_turn_whose_sender_failed_after_dispatch_keeps_its_exact_request(tmp_path, monkeypatch):
    from test_ravel_loop import setup
    from ravel.workflow import prompt_log
    loop, sender, _, _ = setup(tmp_path, monkeypatch, [TimeoutError('lost after send')], streaming=True)
    assert loop.run('  Synthetic request π\n')['status'] == 'ambiguous' and len(sender.calls) == 1
    rows, _ = prompt_log.receipt_records(loop.scope_root)
    assert len(rows) == 1 and rows[0]['stream'] == 'loop' and rows[0]['status'] != 'completed'
    assert json.loads(rows[0]['prompt']) == sender.calls[0] and 'full prompt unknown' not in rows[0]['flags']
    assert rows[0]['total_tokens'] is None  # unknown billing is not zero
    # The kept request is bound by the effect's request digest.
    path = Path(rows[0]['source']['path'])
    record = json.loads(path.read_text())
    record['provisioning']['wire_request'] = record['provisioning']['wire_request'].replace('Synthetic', 'Edited')
    put(path, record)
    rows, _ = prompt_log.receipt_records(loop.scope_root)
    assert rows[0]['prompt'] is None and 'loop wire request hash differs' in rows[0]['flags']


def test_worker_census_names_unrecorded_oneshot_failures(tmp_path):
    """A failed one-shot leaves no receipt, so the census cannot be complete and says what it does not cover."""
    from ravel.workflow import prompt_log, worker_audit
    empty = worker_audit.build(tmp_path / 'empty')
    assert not empty['complete']
    assert ['one-shot failures are not yet recorded' in g['reason'] for g in empty['gaps']] == [True]
    worker(tmp_path / 'run', 'production')
    audit = worker_audit.build(tmp_path / 'run')
    assert len(audit['sessions']) == 1 and not audit['complete']
    assert [g.get('scope') for g in audit['gaps']] == ['coverage']
    log = prompt_log.build(tmp_path / 'run')
    assert sum('one-shot failures are not yet recorded' in str(g.get('reason')) for g in log['gaps']) == 1


def test_source_census_has_no_unmapped_spending_site():
    """A supported spending site without a collected record fails here; a named gap does not pass."""
    from ravel.workflow import prompt_log
    census = prompt_log.call_site_census()
    unmapped = [r for r in census['rows'] if r['record'] is None]
    assert census['rows'] and not unmapped, unmapped
    assert census['gaps'] == [] and census['complete'] is True
    assert any(r['target'] == 'self.dispatcher' for r in census['rows'])


def test_caller_supplied_dispatch_is_recorded_before_it_runs_and_collected(tmp_path):
    """The request handed to a caller-supplied dispatcher is kept before the call, with its outcome after it."""
    import test_agentrivet_provider as fixture
    from ravel.workflow import prompt_log
    llm = fixture.provider(tmp_path)
    seen = []
    original = fixture.dispatcher

    def watching(prepared):
        records = [json.loads(p.read_text()) for p in (llm.root / 'prompt-receipts').glob('*.json')]
        seen.append([r['status'] for r in records])
        return original(prepared)
    llm.dispatcher = watching
    fixture.QUEUE.extend([{'text': 'first raw code'}, RuntimeError('supplied ambiguous dispatch')])
    assert llm.generate([{'role': 'user', 'content': 'Synthetic request'}]) == 'first raw code'
    with pytest.raises(RuntimeError):
        llm.generate([{'role': 'user', 'content': 'Second synthetic request'}])
    assert seen == [['started'], ['completed', 'started']] or seen == [['started'], ['started', 'completed']]
    rows, gaps = prompt_log.receipt_records(llm.root)
    assert len(rows) == 2 and not gaps and {r['stream'] for r in rows} == {'dispatcher'}
    done = next(r for r in rows if r['status'] == 'completed')
    failed = next(r for r in rows if r['status'] == 'failed')
    requests = {json.dumps(r, sort_keys=True) for r in fixture.OBSERVED}
    assert {json.dumps(json.loads(r['prompt']), sort_keys=True) for r in rows} == requests
    assert done['model_requested'] == 'fixture-control' and done['model_reported'] == 'fixture-control'
    assert done['role'] == 'proposer' and failed['model_reported'] is None and failed['total_tokens'] is None
    assert all('full prompt unknown' not in r['flags'] for r in rows)
