"""The declared project instruction document: pin, custody, delivery choice, ancestor files and credit.

Synthetic text and invented paths only; no CLI is started here.
"""
import hashlib
import json

import pytest

from ravel.workflow import broker, project_instructions as pi, review_points

TEXT = 'Rule 1: cite every number.\nRule 2: écrire en clair.\n'


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project folder with an instruction document and a run directory outside it."""
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'project').mkdir()
    (tmp_path / 'run/inputs').mkdir(parents=True)
    document = tmp_path / 'project/AGENTS.md'
    document.write_text(TEXT, encoding='utf-8')
    return tmp_path


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_pin_names_the_real_path_digest_and_byte_count(project):
    pinned = pi.pin(project / 'project/AGENTS.md')
    assert pinned == {'path': str((project / 'project/AGENTS.md').resolve()), 'sha256': sha(TEXT),
                      'bytes': len(TEXT.encode('utf-8'))}


@pytest.mark.parametrize('case', ['absent', 'empty', 'link', 'binary', 'too-large'])
def test_pin_refuses_what_is_not_one_text_document(project, case):
    target = project / 'project/OTHER.md'
    if case == 'empty':
        target.write_text('  \n')
    elif case == 'link':
        target.symlink_to(project / 'project/AGENTS.md')
    elif case == 'binary':
        target.write_bytes(b'\xff\xfe\x00rule')
    elif case == 'too-large':
        target.write_text('x' * (pi.MAX_BYTES + 1))
    with pytest.raises(pi.ProjectInstructionsError) as refused:
        pi.pin(target)
    assert refused.value.missing == ['project_instructions:document']


def test_a_run_without_a_pin_declares_nothing_and_creates_no_custody(project):
    assert pi.declared(project / 'run') is None and pi.for_run(project / 'run') is None
    assert not (project / 'state').exists()
    assert pi.deliver(None, 'claude', None) == ({pi.CARRIER: None}, '', None)
    assert pi.receipt_problem({'kind': 'agent-worker-receipt', 'transport': {}}, None) is None


def test_declare_writes_the_pin_and_binds_it_in_custody(project):
    record = pi.declare(project / 'run', project / 'project/AGENTS.md')
    assert record['sequence'] == 1 and record['approval'] is None and record['sha256'] == sha(TEXT)
    assert json.loads((project / 'run' / pi.PIN_FILE).read_text()) == record == pi.declared(project / 'run')
    rows = broker.ledger(project / 'run', pi.LEDGER)
    assert [r['record']['record_sha256'] for r in rows] == [broker.digest(record)]
    assert pi.for_run(project / 'run') == {'path': record['path'], 'sha256': record['sha256'],
                                           'bytes': record['bytes'], 'rundir': str((project / 'run').resolve())}
    with pytest.raises(pi.ProjectInstructionsError) as again:
        pi.declare(project / 'run', project / 'project/AGENTS.md')
    assert again.value.missing == ['project_instructions:already-pinned'] and 'repin' in str(again.value)


@pytest.mark.parametrize('case,missing', [
    ('hand-written', 'project_instructions:pin-not-in-custody'),
    ('hand-edited', 'project_instructions:pin-changed'),
    ('removed', 'project_instructions:pin-removed'),
])
def test_a_pin_file_changed_by_hand_pins_nothing(project, case, missing):
    run = project / 'run'
    if case == 'hand-written':
        (run / pi.PIN_FILE).write_text(json.dumps({'path': str(project / 'project/AGENTS.md'), 'sha256': sha(TEXT)}))
    else:
        record = pi.declare(run, project / 'project/AGENTS.md')
        if case == 'hand-edited':
            (project / 'project/AGENTS.md').write_text(TEXT + 'Rule 3: none.\n')
            edited = {**record, 'sha256': sha(TEXT + 'Rule 3: none.\n'), 'bytes': record['bytes'] + 14}
            (run / pi.PIN_FILE).write_text(json.dumps(edited))
        else:
            (run / pi.PIN_FILE).unlink()
    with pytest.raises(pi.ProjectInstructionsError) as refused:
        pi.declared(run)
    assert refused.value.missing == [missing]


def test_a_changed_document_is_refused_with_the_repin_command(project):
    run = project / 'run'
    pi.declare(run, project / 'project/AGENTS.md')
    pinned = pi.for_run(run)
    assert pi.text_of(pinned) == TEXT
    (project / 'project/AGENTS.md').write_text(TEXT + 'Rule 3: added mid-run.\n')
    with pytest.raises(pi.ProjectInstructionsError) as refused:
        pi.deliver(pinned, 'claude', None)
    message = str(refused.value)
    assert refused.value.missing == ['project_instructions:changed']
    assert f'ravel project-instructions repin --rundir {run.resolve()}' in message
    assert '--approved-by' in message and '--statement' in message and 'may not change during a run' in message


def test_repin_needs_an_explicit_approval_and_keeps_it_in_custody(project):
    run = project / 'run'
    first = pi.declare(run, project / 'project/AGENTS.md')
    changed = TEXT + 'Rule 3: added mid-run.\n'
    (project / 'project/AGENTS.md').write_text(changed)
    for approved_by, statement in (('', 'new rule'), ('operator-0001', '  '), (None, 'new rule')):
        with pytest.raises(pi.ProjectInstructionsError) as refused:
            pi.repin(run, approved_by=approved_by, statement=statement)
        assert refused.value.missing == ['project_instructions:approval']
    assert pi.declared(run) == first  # a refused re-pin changed nothing
    second = pi.repin(run, approved_by='operator-0001', statement='the project added rule 3')
    assert second['sequence'] == 2 and second['sha256'] == sha(changed)
    assert second['approval']['approved_by'] == 'operator-0001' and second['approval']['replaces_sha256'] == sha(TEXT)
    rows = broker.ledger(run, pi.LEDGER)
    assert [r['record']['sequence'] for r in rows] == [1, 2] and rows[1]['record']['approval'] == second['approval']
    assert pi.text_of(pi.for_run(run)) == changed
    with pytest.raises(pi.ProjectInstructionsError) as same:
        pi.repin(run, approved_by='operator-0001', statement='nothing changed')
    assert same.value.missing == ['project_instructions:unchanged']


def test_repin_without_a_first_pin_is_refused(project):
    with pytest.raises(pi.ProjectInstructionsError) as refused:
        pi.repin(project / 'run', approved_by='operator-0001', statement='first')
    assert refused.value.missing == ['project_instructions:not-pinned']


def test_delivery_without_a_confirmed_flag_is_the_first_block_of_the_prompt(project):
    pinned = pi.pin(project / 'project/AGENTS.md')
    declaration = {'argv_template': ['fake', '-p', '--model', '{model}']}
    probe = {'flags': {'-p': 'confirmed', '--model': 'confirmed'}}
    values, prefix, record = pi.deliver(pinned, 'claude', probe, declaration=declaration,
                                        carrier=project / 'carrier.md')
    assert values == {pi.CARRIER: None} and not (project / 'carrier.md').exists()
    assert prefix.startswith(pi.BLOCK_OPEN) and prefix.endswith(pi.BLOCK_CLOSE + '\n\n')
    assert TEXT in prefix and pinned['sha256'] in prefix
    assert record == {'schema_version': 1, 'path': pinned['path'], 'sha256': pinned['sha256'],
                      'bytes': pinned['bytes'], 'mechanism': 'prompt_first_block', 'flag': None,
                      'position': 'before_ravel_instructions',
                      'ambient': {'ancestor_files': [], 'cli_reported_loaded': None}}
    assert pi.record_problem(record, pinned) is None


@pytest.mark.parametrize('state,carried', [('confirmed', True), ('missing', False)])
def test_a_probe_confirmed_template_flag_carries_the_document(project, state, carried):
    pinned = pi.pin(project / 'project/AGENTS.md')
    declaration = {'argv_template': ['fake', '-p', '--instructions-file', '{' + pi.CARRIER + '}']}
    probe = {'flags': {'-p': 'confirmed', '--instructions-file': state}}
    carrier = project / 'home/project-instructions.md'
    values, prefix, record = pi.deliver(pinned, 'fake', probe, declaration=declaration, carrier=carrier)
    if carried:
        assert values == {pi.CARRIER: str(carrier)} and prefix == ''
        assert carrier.read_text(encoding='utf-8') == TEXT and (carrier.stat().st_mode & 0o777) == 0o400
        assert record['mechanism'] == 'system_prompt_append_flag' and record['flag'] == '--instructions-file'
        # A second delivery of the same text reuses the file; different bytes there are refused.
        assert pi.deliver(pinned, 'fake', probe, declaration=declaration, carrier=carrier)[0] == values
        carrier.chmod(0o600)
        carrier.write_text('other')
        with pytest.raises(pi.ProjectInstructionsError) as refused:
            pi.deliver(pinned, 'fake', probe, declaration=declaration, carrier=carrier)
        assert refused.value.missing == ['project_instructions:carrier-changed']
    else:
        assert values == {pi.CARRIER: None} and TEXT in prefix and record['mechanism'] == 'prompt_first_block'
    assert pi.record_problem(record, pinned) is None


def test_classify_accepts_only_the_pinned_document_and_whole_file_imports(project):
    folder = project / 'project'
    pinned = pi.pin(folder / 'AGENTS.md')
    assert pi.classify(folder / 'AGENTS.md', pinned) == 'declared'
    (folder / 'CLAUDE.md').write_text('@AGENTS.md\n')
    (folder / 'GEMINI.md').write_text(f'  @{folder / "AGENTS.md"}  \n')
    assert pi.classify(folder / 'CLAUDE.md', pinned) == pi.classify(folder / 'GEMINI.md', pinned) == 'import'
    assert pi.ancestor_row(folder / 'CLAUDE.md', pinned) == {
        'path': str(folder / 'CLAUDE.md'), 'relation': 'import', 'sha256': sha('@AGENTS.md\n')}
    refused = {'more.md': '@AGENTS.md\nAlso do this.\n', 'two.md': '@AGENTS.md @other.md\n',
               'other.md': '@OTHER.md\n', 'plain.md': 'Do this.\n', 'bare.md': '@\n'}
    for name, content in refused.items():
        (folder / name).write_text(content)
        assert pi.classify(folder / name, pinned) is None, name
    (folder / 'link.md').symlink_to(folder / 'AGENTS.md')
    assert pi.classify(folder / 'link.md', pinned) is None
    assert pi.classify(folder / 'CLAUDE.md', None) is None
    (folder / 'AGENTS.md').write_text(TEXT + 'changed\n')
    assert pi.classify(folder / 'AGENTS.md', pinned) is None and pi.classify(folder / 'CLAUDE.md', pinned) is None


def test_receipt_problem_reads_both_receipt_kinds(project):
    pinned = pi.pin(project / 'project/AGENTS.md')
    _, _, record = pi.deliver(pinned, 'claude', None)
    worker = {'kind': 'agent-worker-receipt', 'transport': {'id': 'fake', 'project_instructions': record}}
    oneshot = {'kind': 'transport-session-receipt', 'configuration': {'project_instructions': record}}
    assert pi.receipt_problem(worker, pinned) is None and pi.receipt_problem(oneshot, pinned) is None
    assert pi.receipt_problem({'kind': 'agent-worker-receipt', 'transport': {'id': 'fake'}}, pinned) \
        == 'project_instructions:not-recorded'
    assert pi.receipt_problem({'kind': 'transport-session-receipt', 'configuration': {}}, pinned) \
        == 'project_instructions:not-recorded'
    other = {**record, 'sha256': '0' * 64}
    assert pi.record_problem(other, pinned) == 'project_instructions:other-document'
    assert pi.record_problem({**record, 'mechanism': 'somewhere'}, pinned) == 'project_instructions:record-shape'
    assert pi.record_problem({k: v for k, v in record.items() if k != 'ambient'}, pinned) \
        == 'project_instructions:record-shape'
    assert pi.with_cli_report(record, True)['ambient']['cli_reported_loaded'] is True
    assert record['ambient']['cli_reported_loaded'] is None  # the input record is not edited


def test_review_credit_check_refuses_a_receipt_without_the_record(project):
    pinned = pi.pin(project / 'project/AGENTS.md')
    _, _, record = pi.deliver(pinned, 'claude', None)
    plan = {'claims': [{'id': 'claim-0001', 'text': 'synthetic'}], 'nodes': []}
    point = {'id': 'point-0001', 'claim_id': 'claim-0001'}

    def receipt(transport):
        facts = {'plan': plan}
        return {'kind': 'agent-worker-receipt', 'schema_version': 2, 'transport': transport,
                'review_subject': review_points.review_subject(facts, point)}
    with_record = receipt({'id': 'fake', 'project_instructions': record})
    without = receipt({'id': 'fake'})
    # No pin in the run's facts: the check asks for nothing.
    assert review_points.credit_refusal(without, {'plan': plan}, point) is None
    facts = {'plan': plan, 'project_instructions': pinned}
    assert review_points.credit_refusal(with_record, facts, point) is None
    assert review_points.credit_refusal(without, facts, point) == 'project_instructions'
    stale = receipt({'id': 'fake', 'project_instructions': {**record, 'sha256': 'f' * 64}})
    assert review_points.credit_refusal(stale, facts, point) == 'project_instructions'


def test_owning_run_walks_up_to_the_pin(project):
    run = project / 'run'
    (run / 'graphs/review/requests').mkdir(parents=True)
    assert pi.owning_run(run / 'graphs/review/requests') == run.resolve()
    assert pi.for_run(pi.owning_run(run / 'graphs/review/requests')) is None
    pi.declare(run, project / 'project/AGENTS.md')
    assert pi.owning_run(run / 'graphs/review/requests') == run.resolve()
    assert pi.owning_run(project / 'elsewhere/graph') is None  # no run above it


def test_owning_run_stops_at_the_run_that_holds_the_request(project):
    """A run nested under a declaring run is its own run: the search never reaches the pin above it."""
    outer = project / 'run'
    pi.declare(outer, project / 'project/AGENTS.md')
    inner = outer / 'nested/child-run'
    (inner / 'inputs').mkdir(parents=True)
    (inner / 'graph/requests').mkdir(parents=True)
    with pytest.raises(pi.ProjectInstructionsError) as refused:
        pi.owning_run(inner / 'graph/requests')
    assert refused.value.missing == ['project_instructions:run-ambiguous'] and '--rundir' in str(refused.value)
    assert not hasattr(pi, 'find_run')  # the unbounded search is gone
    assert pi.for_run(inner) is None  # naming the run itself answers the question


def test_command_pins_shows_and_repins(project, capsys):
    run, document = str(project / 'run'), str(project / 'project/AGENTS.md')
    assert pi.main(['pin', '--rundir', run, '--path', document]) == 0
    assert json.loads(capsys.readouterr().out)['sha256'] == sha(TEXT)
    assert pi.main(['show', '--rundir', run]) == 0
    assert json.loads(capsys.readouterr().out)['document_matches'] is True
    (project / 'project/AGENTS.md').write_text(TEXT + 'Rule 3.\n')
    assert pi.main(['show', '--rundir', run]) == 3
    shown = json.loads(capsys.readouterr().out)
    assert shown['document_matches'] is False and 'repin' in shown['refusal']
    assert pi.main(['pin', '--rundir', run, '--path', document]) == 3
    assert json.loads(capsys.readouterr().out)['missing'] == ['project_instructions:already-pinned']
    with pytest.raises(SystemExit):  # the approval arguments are required
        pi.main(['repin', '--rundir', run])
    capsys.readouterr()
    assert pi.main(['repin', '--rundir', run, '--approved-by', 'operator-0001', '--statement', 'rule 3 added']) == 0
    assert json.loads(capsys.readouterr().out)['sequence'] == 2
    assert pi.main(['show', '--rundir', run]) == 0


def test_a_work_packet_record_needs_the_host_acknowledgement(project):
    pinned = pi.for_run(project / 'run') or pi.declare(project / 'run', project / 'project/AGENTS.md')
    pinned = pi.for_run(project / 'run')
    record = pi.for_packet(pinned)['record']
    assert record['mechanism'] == 'work_packet' and record['host_acknowledged_sha256'] is None
    assert pi.record_problem(record, pinned) == 'project_instructions:unobserved'
    assert pi.record_problem(pi.acknowledged(record, 'e' * 64), pinned) == 'project_instructions:unobserved'
    assert pi.record_problem(pi.acknowledged(record, pinned['sha256']), pinned) is None
    assert pi.record_problem(pi.acknowledged(record, 'not a digest'), pinned) == 'project_instructions:unobserved'
    # A prompt record never carries the acknowledgement field, and a packet record never lacks it.
    _, _, prompt_record = pi.deliver(pinned, 'fake-agent', None)
    assert pi.record_problem({**prompt_record, 'host_acknowledged_sha256': pinned['sha256']}, pinned) \
        == 'project_instructions:record-shape'
    bare = {k: v for k, v in record.items() if k != 'host_acknowledged_sha256'}
    assert pi.record_problem(bare, pinned) == 'project_instructions:record-shape'


def test_every_pinned_text_is_kept_in_custody_after_the_file_changes(tmp_path, monkeypatch):
    """A re-pin replaces the declaration; the bytes of each earlier pin stay readable by their sha256."""
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run, document = tmp_path / 'run', tmp_path / 'project/AGENTS.md'
    (run / 'inputs').mkdir(parents=True)
    document.parent.mkdir()
    document.write_text('Project rule 1: cite every number.\n')
    first = pi.declare(run, document)
    assert pi.retained_text(run, first['sha256']) == 'Project rule 1: cite every number.\n'
    document.write_text('Project rule 1: cite every number.\nProject rule 2: write plainly.\n')
    second = pi.repin(run, approved_by='operator-0001', statement='rule 2 was agreed')
    assert pi.retained_text(run, first['sha256']) == 'Project rule 1: cite every number.\n'
    assert pi.retained_text(run, second['sha256']).endswith('Project rule 2: write plainly.\n')
    assert pi.retained_text(run, 'f' * 64) is None
    kept = pi.retained_path(run, first['sha256'])
    assert kept.parent == pi._ledger_file(pi._run(run)).parent and not kept.is_relative_to(run)
    kept.chmod(0o600)
    kept.write_text('edited by hand\n')
    assert pi.retained_text(run, first['sha256']) is None  # a copy that no longer holds the pinned bytes is not used
