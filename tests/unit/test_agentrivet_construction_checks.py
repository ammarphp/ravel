"""Construction checks, briefs, compile gate and text repairs with own fixtures and stub tools.

No provider, real compiler, Rivet run or upstream GPL source is used.
"""
import synthetic_identifiers as syn
from copy import deepcopy
import base64
import json
from pathlib import Path
import pytest
from ravel.workflow import agent_graph, agentrivet_checks, agentrivet_construction as operation, research_cycle
from ravel.workflow.state_io import atomic_json, read_json
from agentrivet_checks_fixture import (allow_own_censuses, request, host, draft, review, MODEL, ROUTINE, pin,
                                       rivet_stub, write)


def prepared(tmp_path, **kwargs):
    raw = request(tmp_path, **kwargs)
    result = operation.prepare(raw, base_dir=tmp_path, output_dir=tmp_path / 'prepared')
    return raw, result['request']


def approved(tmp_path, **kwargs):
    raw, rp = prepared(tmp_path, **kwargs)
    agentrivet_checks.approve(rp, base_dir=tmp_path, quote='Run the declared construction checks.', scripted=True)
    return raw, rp


def briefs(seen):
    """(role-instruction head, brief) per dispatched call, from the actual Host request bodies."""
    rows = []
    for body in seen:
        context = json.loads(body['input'][0]['content'])
        brief = next((json.loads(a['content']) for a in context.get('input_artifacts', []) if a['id'] == 'ravel-brief'), None)
        user = next(json.loads(a['content']) for a in context['input_artifacts'] if a['id'] == 'upstream-user-message')
        rows.append({'instructions': body['instructions'], 'brief': brief, 'user': user['user'], 'role': user['role']})
    return rows


def test_prepare_builds_the_hepdata_map_context_and_reference_from_the_record(tmp_path):
    raw, rp = prepared(tmp_path, checks=False)
    value = read_json(rp['path'])
    assert value['routine_name'] == ROUTINE
    table_map = read_json(value['construction']['table_map']['path'])
    assert sorted(table_map['entries']) == ['d01-x01-y01', 'd02-x01-y01']
    assert table_map['entries']['d01-x01-y01']['edges'] == [0.0, 10.0, 20.0, 50.0]
    context = read_json(value['hepdata']['context']['path'])
    assert context['hepdata_info'] == 'own-synthetic-record'
    assert context['hepdata_map']['d02-x01-y01']['bin_edges'] == [1.0, 2.0, 4.0]
    assets = value['hepdata']['assets']
    assert [a['path'] for a in assets] == [ROUTINE + '.yoda'] and assets[0]['role'] == 'reference'
    assert f'/REF/{ROUTINE}/d01-x01-y01' in Path(assets[0]['input']['path']).read_text()


def test_routine_name_is_checked_before_any_capture_or_charge(tmp_path):
    raw = request(tmp_path, checks=False, metadata={'arxiv_id': (syn.arxiv(676)), 'inspire_id': '1',
                                                    'collaboration': 'Bad-Name', 'preprint_year': '2026'})
    with pytest.raises(ValueError, match='not a native identifier'):
        operation.prepare(raw, base_dir=tmp_path, output_dir=tmp_path / 'prepared')
    assert not (tmp_path / 'prepared').exists()


def test_repairs_have_their_own_budget_beyond_three_initial_rounds(tmp_path):
    raw, rp = prepared(tmp_path, checks=False, initial=3, repairs=2)
    assert read_json(rp['path'])['provider']['max_calls'] == 16
    (tmp_path / 'other').mkdir()
    bad = request(tmp_path / 'other', checks=False, initial=3, repairs=2)
    bad['provider']['max_calls'] = 10
    with pytest.raises(ValueError):
        operation.prepare(bad, base_dir=tmp_path / 'other', output_dir=tmp_path / 'other/prepared')


def test_checks_need_their_approval_before_any_role_call(tmp_path, monkeypatch):
    raw, rp = prepared(tmp_path)
    seen = []
    actor = host(monkeypatch, [deepcopy(MODEL)], seen)
    with pytest.raises(ValueError, match='approval'):
        operation.generate(rp, base_dir=tmp_path, host=actor)
    assert not seen
    with pytest.raises(ValueError, match='scripted assent'):
        agentrivet_checks.approve(rp, base_dir=tmp_path, quote='yes', scripted=False)
    receipt = agentrivet_checks.approve(rp, base_dir=tmp_path, quote='Run the declared checks.', scripted=True)
    assert read_json(receipt['path'])['expert_review'] is False
    with pytest.raises(ValueError, match='already recorded'):
        agentrivet_checks.approve(rp, base_dir=tmp_path, quote='again', scripted=True)


def test_tag_loop_gets_compile_text_in_loop_briefs_journal_and_reservation(tmp_path, monkeypatch):
    raw, rp = approved(tmp_path, initial=2, repairs=0)
    seen = []
    code_review, physics = review(approved=False)
    queue = [deepcopy(MODEL), {'text': draft(broken=True)}, code_review, physics,
             {'text': draft()}, *review()]
    actor = host(monkeypatch, queue, seen)
    gp = operation.generate(rp, base_dir=tmp_path, host=actor)
    assert not queue
    calls = briefs(seen)
    assert [c['role'] for c in calls] == ['analyst', 'coder', 'code_reviewer', 'physics_reviewer',
                                          'coder', 'code_reviewer', 'physics_reviewer']
    assert all(c['brief']['routine_name'] == ROUTINE for c in calls)
    assert calls[1]['instructions'].startswith('Return only public JSON')       # Host prefix
    assert 'Own coder instruction' in calls[1]['instructions']
    assert {t['id'] for t in calls[1]['brief']['hepdata_tables']} == {'d01-x01-y01', 'd02-x01-y01'}
    assert any(item['id'] == 'double_filling' for item in calls[1]['brief']['checklist'])
    # The reviewer of the broken draft and the next coder see the compiler text.
    observed = calls[2]['brief']['observations']
    assert observed['compile']['status'] == 'failed'
    assert observed['compile']['diagnostics'][0]['message'] == "unknown type name 'BROKEN'"
    assert "unknown type name 'BROKEN'" in calls[4]['brief']['observations']['compile']['output']
    assert calls[5]['brief']['observations']['compile']['status'] == 'passed'
    result = read_json(gp['path'])
    assert result['selection'] == {'draft_index': 1, 'basis': 'upstream_accepted'} and not result['compile_gate']
    evidence = read_json(result['construction_evidence']['path'])
    assert evidence['selected_check']['compile']['status'] == 'passed'
    assert evidence['selected_bookings']['findings'] == [] and evidence['physics_validated'] is False
    journal = sorted((tmp_path / 'prepared/logs/authorization').glob('*.json'))
    assert [read_json(p)['event'] for p in journal] == ['authorized', 'launched'] * 2
    assert read_json(journal[0])['authorization']['machine_approval_is_not_human_review'] is True
    campaign = research_cycle._load(raw['campaign'])[1]
    rows = [r for r in campaign['resource_ledger'] if r['id'].startswith('operation:agentrivet-construction-checks')]
    assert len(rows) == 1 and rows[0]['ceiling']['native_attempts'] == 4
    _, request_doc = operation._load(rp, tmp_path)
    operation._generation(request_doc, gp, tmp_path)


def test_compile_gated_loop_uses_ravel_compile_skips_reviews_and_selects_observed_draft(tmp_path, monkeypatch):
    raw, rp = approved(tmp_path, gated=True, initial=3, repairs=0)
    seen = []
    code_review, physics = review(approved=False)
    queue = [deepcopy(MODEL), {'text': draft(broken=True)}, {'text': draft()}, code_review, physics,
             {'text': draft(broken=True, extra='// regression')}]
    actor = host(monkeypatch, queue, seen)
    gp = operation.generate(rp, base_dir=tmp_path, host=actor)
    assert not queue
    calls = briefs(seen)
    assert [c['role'] for c in calls] == ['analyst', 'coder', 'coder', 'code_reviewer', 'physics_reviewer', 'coder']
    assert "unknown type name 'BROKEN'" in calls[2]['user']                    # upstream compile-fix prompt text
    result = read_json(gp['path'])
    assert result['compile_gate'] is True
    assert result['selection'] == {'draft_index': 1, 'basis': 'last_observed_compile'}
    memory = read_json(result['raw_request']['memory']['path'])
    assert memory['code_review'][0] is None and memory['code_review'][2] is None
    assert [b['data']['returncode'] for b in memory['build_result']] == [1, 0, 1]
    assert Path(result['raw_request']['translation_unit']['path']).read_text() == draft().strip()
    assert read_json(result['source_study']['request']['path'])['selection']['draft_index'] == 1
    _, request_doc = operation._load(rp, tmp_path)
    operation._generation(request_doc, gp, tmp_path)
    # A stale check record cannot vouch for a skipped review.
    record = tmp_path / 'prepared/checks/probe-01/record.json'
    value = read_json(record)
    value['compile']['output'] = 'changed'
    atomic_json(record, value)
    with pytest.raises(ValueError, match='RAVEL-observed compile'):
        operation._generation(request_doc, gp, tmp_path)


def test_compile_gated_upstream_without_checks_never_compiles(tmp_path, monkeypatch):
    raw, rp = prepared(tmp_path, gated=True, checks=False)
    seen = []
    queue = [deepcopy(MODEL), {'text': draft()}, *review()]
    actor = host(monkeypatch, queue, seen)
    gp = operation.generate(rp, base_dir=tmp_path, host=actor)
    result = read_json(gp['path'])
    assert not result['compile_gate'] and 'build_result' not in read_json(result['raw_request']['memory']['path'])
    assert not (tmp_path / 'prepared/logs').exists()


YODA = f'''BEGIN YODA_COUNTER_V3 /RAW/_EVTCOUNT
Path: /RAW/_EVTCOUNT
Type: Counter
---
# sumW       \tsumW2        \tnumEntries
1.000000e+01 \t1.000000e+01 \t1.000000e+01
END YODA_COUNTER_V3

BEGIN YODA_ESTIMATE0D_V3 /RAW/_XSEC
Path: /RAW/_XSEC
Type: Estimate0D
---
# value      \terrDn(1)     \terrUp(1)
2.000000e+00 \t-0.000000e+00\t0.000000e+00
END YODA_ESTIMATE0D_V3

BEGIN YODA_HISTO1D_V3 /RAW/{ROUTINE}/d01-x01-y01
Path: /RAW/{ROUTINE}/d01-x01-y01
Type: Histo1D
---
Edges(A1): [0.000000e+00, 1.000000e+01, 2.000000e+01, 5.000000e+01]
# sumW       \tsumW2        \tsumW(A1)     \tsumW2(A1)    \tnumEntries
0 0 0 0 0
4 4 20 100 4
4 4 60 900 4
2 2 60 1800 2
0 0 0 0 0
END YODA_HISTO1D_V3

BEGIN YODA_ESTIMATE1D_V3 /{ROUTINE}/d01-x01-y01
Path: /{ROUTINE}/d01-x01-y01
Type: Estimate1D
---
Edges(A1): [0.000000e+00, 1.000000e+01, 2.000000e+01, 5.000000e+01]
# value
nan
8.000000e+01
8.000000e+01
1.333333333e+01
nan
END YODA_ESTIMATE1D_V3

BEGIN YODA_HISTO1D_V3 /RAW/{ROUTINE}/d02-x01-y01
Path: /RAW/{ROUTINE}/d02-x01-y01
Type: Histo1D
---
Edges(A1): [1.000000e+00, 2.000000e+00, 3.000000e+00, 4.000000e+00]
# sumW       \tsumW2        \tsumW(A1)     \tsumW2(A1)    \tnumEntries
0 0 0 0 0
10 10 15 30 10
10 10 25 60 10
0 0 0 0 0
0 0 0 0 0
END YODA_HISTO1D_V3
'''


def test_small_sample_findings_reach_reviewers_and_the_next_coder(tmp_path, monkeypatch):
    events = tmp_path / 'events.hepmc'
    events.write_text('own synthetic event file placeholder\n')
    (tmp_path / 'stub').mkdir()
    sample = {'rivet': rivet_stub(tmp_path / 'stub', YODA), 'events': pin(events)}
    raw, rp = approved(tmp_path, initial=2, repairs=0, sample=sample,
                       normalization=[{'object': 'd01-x01-y01', 'basis': 'xsec', 'unit': 'pb'}])
    seen = []
    code_review, physics = review(approved=False)
    queue = [deepcopy(MODEL), {'text': draft(extra='book(_h["m"], 2, 1, 1); book(_h["x"], 9, 1, 1);')},
             code_review, physics, {'text': draft()}, *review()]
    actor = host(monkeypatch, queue, seen)
    gp = operation.generate(rp, base_dir=tmp_path, host=actor)
    calls = briefs(seen)
    observed = calls[2]['brief']['observations']
    checks = {(f['check'], f['object']) for f in observed['sample']['findings'] if f['severity'] != 'pass'}
    assert ('normalization', f'/{ROUTINE}/d01-x01-y01') in checks
    assert ('multiple_fills_per_event', f'/{ROUTINE}/d02-x01-y01') in checks
    assert ('binning_mismatch', f'/RAW/{ROUTINE}/d02-x01-y01') in checks
    message = next(f['message'] for f in observed['sample']['findings'] if f['check'] == 'normalization')
    assert 'unit' in message and '1000' in message
    assert any(f['check'] == 'booking_unknown_table' for f in observed['booking_findings'])
    assert calls[4]['brief']['observations']['sample']['status'] == 'completed'
    sample_dir = tmp_path / 'prepared/checks/probe-01'
    assert (sample_dir / 'sample.yoda').is_file() and (sample_dir / f'{ROUTINE}.yoda').is_file()
    journal = [read_json(p) for p in sorted((tmp_path / 'prepared/logs/authorization').glob('*.json'))]
    assert [e['context']['label'] for e in journal if e['event'] == 'authorized'] == ['compile', 'sample'] * 2
    assert read_json(gp['path'])['physics_validated'] is False


def test_failed_build_repair_gives_the_coder_compiler_text_not_pins(tmp_path, monkeypatch):
    from ravel.workflow import failed_stage_review
    raw, rp = prepared(tmp_path, checks=False, initial=1, repairs=1)
    seen = []
    actor = host(monkeypatch, [deepcopy(MODEL), {'text': draft()}, *review()], seen)
    gp = operation.generate(rp, base_dir=tmp_path, host=actor)
    g = read_json(gp['path'])
    log = tmp_path / 'build-01.log'
    atomic_json(log, {'schema_version': 2, 'command': ['rivet-build'], 'returncode': 1,
                      'stdout_base64': base64.b64encode(b'compiling\n').decode(),
                      'stderr_base64': base64.b64encode(f"{ROUTINE}.cc:7:12: error: no member named 'fill2' in 'Rivet::Histo1D'\n".encode()).decode()})
    failure = {'kind': 'failed_stage_diagnostic_intake', 'run_dir': str(tmp_path / 'failed'), 'exit_code': 1,
               'execution_error': 'routine build/probe failed; inspect build-01.log',
               'evidence': [{**pin(log), 'size': log.stat().st_size, 'location': 'build log'}],
               'source_inputs': {g['raw_request']['translation_unit']['path']: {'files': [
                   {'name': '.', 'sha256': g['raw_request']['translation_unit']['sha256'], 'size': 1}]}}}
    feedback = tmp_path / 'feedback.json'
    atomic_json(feedback, failure)
    monkeypatch.setattr(failed_stage_review, 'verify', lambda value, **kwargs: value)
    queue = [{'text': draft(extra='// repaired')}, *review()]
    seen.clear()

    def response(data, parameters, request_, control, **kwargs):
        seen.append(json.loads(data))
        return actor._result(queue.pop(0), parameters, request_, observed_model='fixture-model', response_id='own-inert-repair')
    monkeypatch.setattr(actor, '_responses', response)
    new = operation.repair(rp, gp, pin(feedback), base_dir=tmp_path, host=actor)
    coder = briefs(seen)[0]
    assert coder['role'] == 'coder'
    assert "no member named 'fill2'" in coder['user'] and 'Only change lines' in coder['user']
    assert f'Analysis ID: {ROUTINE}' in coder['user'] and draft() in coder['user']
    assert '"sha256"' not in coder['user']
    result = read_json(new['path'])
    assert result['native_repair_count'] == 1
    memory = read_json(result['raw_request']['memory']['path'])
    assert memory['iteration'] == 2 and len(memory['code_draft']) == 2


def test_send_back_repair_carries_the_review_findings_text(tmp_path):
    from ravel.workflow import agentrivet_brief
    kind, text = agentrivet_brief.send_back_feedback('Leptons must be dressed.', {'unresolved_findings': [
        {'id': 'f1', 'finding': 'Jets cluster bare leptons; the paper removes dressed leptons.', 'sha256': 'x'}]})
    assert kind == 'review' and 'dressed leptons' in text and 'sha256' not in text
    prompt = agentrivet_brief.repair_prompt({'analysis_model': 'own summary'}, ROUTINE, 'int x;', kind, text)
    assert 'independent review findings' in prompt and 'Jets cluster bare leptons' in prompt


def test_coordinator_waits_for_the_checks_approval_then_generates_by_step(tmp_path, monkeypatch):
    from ravel.workflow import research_tools
    raw = request(tmp_path)
    campaign = Path(raw['campaign'])
    rp = tmp_path / 'raw-preparation.json'
    atomic_json(rp, raw)
    cp = tmp_path / 'choice.json'
    atomic_json(cp, {'kind': 'paper-first', 'request': pin(rp)})
    seen = []
    actor = host(monkeypatch, [deepcopy(MODEL), {'text': draft()}, *review()], seen)
    handoff = research_tools.routine_workflow(campaign, {**pin(cp), 'size': cp.stat().st_size}, campaign / 'routine-work',
                                              actor, max_wall_seconds=60)
    assert handoff['kind'] == 'paper-first-routine-awaiting-checks-approval' and not seen
    agentrivet_checks.approve(handoff['request'], base_dir=tmp_path, quote='Run the declared checks.', scripted=True)
    sp = tmp_path / 'step.json'
    atomic_json(sp, {'action': 'generate', 'arguments': {'request': handoff['request']}})
    result = research_tools.routine_step(campaign, {**pin(sp), 'size': sp.stat().st_size}, base_dir=tmp_path,
                                         host=actor, output_dir=campaign / 'routine-generation')
    assert result['kind'] == 'paper-first-routine-research-handoff' and len(seen) == 4
    assert not result['execution_authorized'] and not result['physics_validated']
