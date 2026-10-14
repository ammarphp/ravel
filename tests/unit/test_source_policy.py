"""Synthetic sibling sources and reviewed outputs exercise source restrictions."""
from copy import deepcopy
import pytest
from ravel.workflow import state_io


def policy(**updates):
    return {'id': 'R1', 'kind': 'forbidden-source', 'classes': [], 'identifiers': {},
            'paths': ['refs/**/*.root', 'withheld/*'], 'origin': 'harness',
            'statement': 'Keep supplied blinded values inaccessible', 'evidence': [], **updates}


def test_withheld_glob_read_is_refused_with_named_rule(tmp_path):
    from ravel.workflow import source_policy as sp
    source = tmp_path / 'refs/nested/value.root'
    source.parent.mkdir(parents=True)
    source.write_text('withheld synthetic bytes')
    receipt = sp.read_receipt([policy()], {'path': 'refs/nested/value.root'})
    assert receipt['refusal_code'] == 'forbidden_source'
    assert receipt['rules'][0]['id'] == 'R1'
    assert receipt['source_restriction_sha256'] == sp.digest([policy()])
    assert sp.matches([policy()], {'path': 'refs/value.root'})
    assert not sp.matches([policy()], {'path': 'refs/value.json'})
    with pytest.raises(ValueError, match='forbidden_source.*R1'):
        sp.require_read([policy()], {'path': 'refs/nested/value.root'})


def test_quantity_scope_preserves_definitions_but_never_overrides_path_ban():
    from ravel.workflow import source_policy as sp
    row = policy(kind='no-value-extraction', classes=['tables'], scope={'quantities': ['edge']})
    assert not sp.matches([row], {'classes': ['tables'], 'quantities': ['selection']})
    assert sp.matches([row], {'classes': ['tables'], 'quantities': ['edge']})
    assert sp.matches([row], {'path': 'withheld/values.json', 'quantities': ['selection']})


def test_reading_rows_and_digest_cover_all_policy_keys():
    from ravel.workflow import source_policy as sp
    row = policy()
    reading = {'constraints': [{'type': 'blinding', 'value': row, 'evidence': []}]}
    assert sp.from_reading(reading) == [row]
    changed = deepcopy(row); changed['paths'].append('extra/*')
    assert sp.digest([row]) != sp.digest([changed])


@pytest.mark.parametrize('change', [{'origin': 'code'}, {'paths': ['../outside/*']},
                                    {'origin': 'request', 'evidence': []}])
def test_path_rules_require_request_or_harness_provenance(change):
    from ravel.workflow import source_policy as sp
    with pytest.raises(ValueError): sp.digest([policy(**change)])


def test_path_rule_cannot_omit_its_origin():
    from ravel.workflow import source_policy as sp
    row = policy(origin='request', evidence=[{'start': 0, 'end': 4, 'text': 'Keep'}])
    del row['origin']
    with pytest.raises(ValueError, match='origin'): sp.digest([row])


def test_malformed_reading_is_a_refusal_not_a_crash():
    from ravel.workflow import source_policy as sp
    with pytest.raises(ValueError, match='reading'): sp.from_reading([])


def test_accepted_returns_declared_outputs_and_lists_undeclared(tmp_path, monkeypatch):
    from ravel.workflow import source_policy as sp
    from test_task_completion import review_run, write
    extra = tmp_path / 'run/outputs/additional.json'
    write(extra, {'value': 7})
    root = review_run(tmp_path / 'run', [str(extra)], monkeypatch)
    result = sp.accepted(root, declared_outputs=['outputs/produced.json'], claim_scope='diagnostic')
    assert [p['path'] for p in result['outputs']] == [str(root / 'outputs/produced.json')]
    assert str(extra) in [p['path'] for p in result['undeclared_outputs']]
    with pytest.raises(ValueError, match='declared output'):
        sp.accepted(root, declared_outputs=['outputs/missing.json'], claim_scope='diagnostic')


def test_contract_restrictions_must_equal_pinned_reading(tmp_path):
    from ravel.validation import validate_task_contract as vtc
    import intake_sidecar_fixtures as fx
    root = tmp_path / 'run'
    contract, reading, _ = fx.pinned_run(root)
    contract['forbidden_sources'] = [policy()]
    assert any('forbidden_sources' in e for e in vtc.validate_pins(root, contract))


def test_checkin_refusal_retains_source_receipt(tmp_path):
    from ravel.validation import validate_checkin as vc
    from test_checkin_sections import document
    state_io.atomic_json(tmp_path / 'inputs/task_contract.json', {'forbidden_sources': [policy()]})
    checkin = document()
    checkin['sections']['sources'] = [{'path': 'withheld/values.json'}]
    errors = vc.validate(checkin, tmp_path)
    assert any('forbidden_source' in e and 'R1' in e for e in errors)


def test_inventory_omits_withheld_sources_and_keeps_receipts():
    from ravel.workflow import source_policy as sp
    sources = [{'path': 'withheld/value.json'}, {'path': 'allowed/selection.json'}]
    result = sp.inventory([policy()], sources)
    assert result['sources'] == sources[1:]
    assert result['refused'][0]['rules'][0]['id'] == 'R1'


def test_unreviewed_output_is_visible_but_not_accepted(tmp_path, monkeypatch):
    from ravel.workflow import source_policy as sp
    from test_task_completion import review_run, write
    root = review_run(tmp_path / 'run', [], monkeypatch)
    extra = root / 'outputs/additional.json'
    write(extra, {'value': 9})
    result = sp.accepted(root, declared_outputs=['outputs/produced.json'], claim_scope='diagnostic')
    assert [p['path'] for p in result['outputs']] == [str(root / 'outputs/produced.json')]
    assert any(p['path'] == str(extra) and p['reviewed'] is False for p in result['undeclared_outputs'])


def test_broker_dependency_integration():
    try:
        from ravel.workflow import knowledge_broker
    except ImportError:
        pytest.xfail('awaits the knowledge broker')
    assert hasattr(knowledge_broker, 'source_policy')


def test_routed_contract_carries_its_reading_restrictions():
    from ravel.workflow import route_prompt, source_policy as sp
    contract, reading, _ = route_prompt.route_records(
        'Predict binned signal yields of a synthetic toy model. Do not use HEPData.')
    rows = sp.from_reading(reading)
    assert rows and contract['forbidden_sources'] == rows


def test_checkin_without_a_sources_census_is_refused_under_restrictions(tmp_path):
    from ravel.validation import validate_checkin as vc
    from test_checkin_sections import document
    state_io.atomic_json(tmp_path / 'inputs/task_contract.json', {'forbidden_sources': [policy()]})
    for census in (None, []):
        checkin = document()
        if census is not None:
            checkin['sections']['sources'] = census
        assert any('sources' in e and 'census' in e for e in vc.validate(checkin, tmp_path))
    checkin = document()
    checkin['sections']['sources'] = [{'path': 'allowed/selection.json'}]
    assert not any('source' in e for e in vc.validate(checkin, tmp_path))


def test_restricted_run_reading_no_sources_declares_an_explicit_empty_census(tmp_path):
    from ravel.validation import validate_checkin as vc
    from test_checkin_sections import document
    state_io.atomic_json(tmp_path / 'inputs/task_contract.json', {'forbidden_sources': [policy()]})
    checkin = document()
    checkin['sections']['sources'] = [{'none': 'the closed-form calculation reads no external source'}]
    assert not any('source' in e for e in vc.validate(checkin, tmp_path))
    for census in ([{'none': ''}], [{'none': 'no source'}, {'path': 'allowed/selection.json'}]):
        checkin['sections']['sources'] = census
        assert any('sources' in e and 'none' in e for e in vc.validate(checkin, tmp_path)), census
