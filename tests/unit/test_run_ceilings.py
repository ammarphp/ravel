"""Bounded invocation accounting without dispatching a worker."""
import importlib
import pytest
from test_review_points import run, write


def module(): return importlib.import_module('ravel.workflow.run_ceilings')


def test_default_and_exhaustion_are_read_only_until_charge(tmp_path):
    c = module(); run(tmp_path)
    assert c.default('analysis')['max_invocations'] == 72
    assert c.default('research')['max_invocations'] == 120
    value = c.default('analysis'); value['max_invocations'] = 1
    write(tmp_path/'inputs/agent_ceilings.json', value)
    c.charge(tmp_path, 'worker')
    with pytest.raises(c.CeilingExceeded): c.charge(tmp_path, 'rdj')
    assert len((tmp_path/'agent-work/ledger.jsonl').read_text().splitlines()) == 1


def test_api_transport_requires_cap_at_checkin(tmp_path):
    c = module(); run(tmp_path, selected_transports=[{'id': 'api-one', 'billing': 'api'}])
    section = c.checkin_section(tmp_path)
    assert section['missing_evidence_ids'] == ['usd_cap:api-one']


@pytest.mark.parametrize('bad', [True, 0, -1, 1.5])
def test_invalid_invocation_charge_refused(tmp_path, bad):
    c = module(); run(tmp_path)
    with pytest.raises(ValueError): c.charge(tmp_path, 'worker', bad)
    assert not (tmp_path/'agent-work/ledger.jsonl').exists()


def test_concurrent_charges_cannot_overdraw(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    c = module(); run(tmp_path)
    value = c.default('analysis'); value['max_invocations'] = 3
    write(tmp_path/'inputs/agent_ceilings.json', value)
    def spend(_):
        try: c.charge(tmp_path, 'map-item'); return True
        except c.CeilingExceeded: return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(spend, range(8))) == 3
    assert len((tmp_path/'agent-work/ledger.jsonl').read_text().splitlines()) == 3


def test_agent_written_checkin1_response_record_ignored(tmp_path):
    c = module(); run(tmp_path)
    value = c.default('analysis'); value.update(source='checkin1_response', max_invocations=10**9)
    write(tmp_path/c.RECORD, value)
    assert c.resolve(tmp_path)['max_invocations'] == 72
    assert any('ceiling:checkin1_response' in e.pins for e in c.gate_errors(tmp_path, 'launch', {}))


def test_spend_above_ceiling_passes_with_recorded_raise(tmp_path):
    from ravel.workflow import rdj_custody
    c = module(); run(tmp_path)
    write(tmp_path/c.RECORD, c.default('analysis'))
    rdj_custody.record_input_snapshot(tmp_path, 'run_init')
    c.charge(tmp_path, 'worker', 72)
    value = c.default('analysis'); value.update(source='checkin1_response', max_invocations=100)
    write(tmp_path/c.RECORD, value)
    (tmp_path/rdj_custody.CI1_RESPONSE).write_bytes((tmp_path/c.RECORD).read_bytes())
    rdj_custody.record_user_text(tmp_path, 'checkin1_response', rdj_custody.CI1_RESPONSE)
    rdj_custody.record_input_snapshot(tmp_path, 'checkin1')
    assert c.gate_errors(tmp_path, 'spend_above_ceiling', {'invocations': 1}) == []
    from ravel.workflow import decision_gate
    assert any(e.provider == 'rdj' for e in decision_gate.check(tmp_path, 'spend_above_ceiling', {'invocations': 1}))


def test_spend_above_ceiling_without_raise_refused(tmp_path):
    from ravel.workflow import rdj_custody
    c = module(); run(tmp_path)
    value = c.default('analysis'); value['source'] = 'checkin1_response'
    write(tmp_path/c.RECORD, value)
    c.charge(tmp_path, 'worker', 72)
    (tmp_path/rdj_custody.CI1_RESPONSE).write_bytes((tmp_path/c.RECORD).read_bytes())
    rdj_custody.record_user_text(tmp_path, 'checkin1_response', rdj_custody.CI1_RESPONSE)
    rdj_custody.record_input_snapshot(tmp_path, 'checkin1')
    assert c.gate_errors(tmp_path, 'spend_above_ceiling', {})


def test_raise_recorded_before_old_ceiling_reached_refused(tmp_path):
    from ravel.workflow import rdj_custody
    c = module(); run(tmp_path)
    value = c.default('analysis'); value.update(source='checkin1_response', max_invocations=100)
    write(tmp_path/c.RECORD, value)
    (tmp_path/rdj_custody.CI1_RESPONSE).write_bytes((tmp_path/c.RECORD).read_bytes())
    rdj_custody.record_user_text(tmp_path, 'checkin1_response', rdj_custody.CI1_RESPONSE)
    rdj_custody.record_input_snapshot(tmp_path, 'checkin1')
    c.charge(tmp_path, 'worker', 72)
    assert c.gate_errors(tmp_path, 'spend_above_ceiling', {'invocations': 1})


def test_unbound_response_cannot_raise_default_by_changing_run_shape(tmp_path):
    c = module(); run(tmp_path)
    value = c.default('research'); value['source'] = 'checkin1_response'
    write(tmp_path/c.RECORD, value)
    assert c.resolve(tmp_path)['max_invocations'] == 72


def test_agent_written_default_cannot_claim_research_shape(tmp_path):
    c = module(); run(tmp_path)
    write(tmp_path/c.RECORD, c.default('research'))
    assert c.resolve(tmp_path)['max_invocations'] == 72


def test_ceiling_raise_can_bind_through_real_approval_fingerprint(tmp_path):
    from test_approval_chain import _rundir
    from argparse import Namespace
    from ravel.workflow import workflow_state as ws
    c = module(); root = _rundir(tmp_path)
    c.charge(root, 'worker', 72)
    value = c.default('analysis'); value.update(source='checkin1_response', max_invocations=100)
    write(root/c.RECORD, value)
    assert ws.cmd_approve(Namespace(rundir=str(root), plan='smoke', quote='Raise the invocation ceiling to 100.')) == 0
    assert ws.verify_approval(str(root)) == []
    assert c.resolve(root)['max_invocations'] == 100
    assert c.gate_errors(root, 'spend_above_ceiling', {'invocations': 1}) == []
    value['max_invocations'] = 101; write(root/c.RECORD, value)
    assert c.resolve(root)['max_invocations'] == 72
