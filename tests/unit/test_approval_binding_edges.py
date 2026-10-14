"""Input-set changes, dependencies and approval races use synthetic bytes only."""
import json

import pytest

from ravel.workflow import workflow_state as ws, launch_authorization
from ravel.workflow.state_io import atomic_json
from test_approval_binding_inputs import lifecycle, approve, repin_plan


def test_deleted_bound_card_is_refused_and_disclosed(tmp_path):
    rd, files = lifecycle(tmp_path)
    approve(rd)
    (rd / files[3]).unlink()
    errors = ws.verify_approval(str(rd), disclose=True)
    assert any(files[3] in e for e in errors)
    assert files[3] in (rd / 'DEVIATIONS.md').read_text()


def test_directory_membership_addition_requires_reapproval(tmp_path):
    rd, _ = lifecycle(tmp_path)
    directory = rd / 'inputs/model-source'
    directory.mkdir()
    (directory / 'a.model').write_bytes(b'initial model')
    plan_path = rd / 'inputs/executable-plan.json'
    plan = json.loads(plan_path.read_text())
    plan['stages'][0]['inputs'].append('inputs/model-source')
    atomic_json(plan_path, plan)
    approve(rd)
    (directory / 'b.new_type').write_bytes(b'new source module')
    assert any('inputs/model-source/b.new_type' in e for e in ws.verify_approval(str(rd)))


def test_detector_sourced_file_is_bound_transitively(tmp_path):
    rd, files = lifecycle(tmp_path)
    (rd / files[1]).write_text('source response.formula\n')
    source = rd / 'inputs/response.formula'
    source.write_text('set response 1\n')
    approve(rd)
    assert str(source) in ws.approval_input_paths(str(rd))
    source.write_text('set response 2\n')
    assert any('response.formula' in e for e in ws.verify_approval(str(rd)))


def test_plan_input_set_edit_names_the_changed_plan(tmp_path):
    rd, _ = lifecycle(tmp_path)
    approve(rd)
    path = rd / 'inputs/executable-plan.json'
    plan = json.loads(path.read_text())
    plan['stages'][0]['inputs'].append('inputs/new.read')
    atomic_json(path, plan)
    assert any('inputs/executable-plan.json' in e for e in ws.verify_approval(str(rd), disclose=True))
    assert 'inputs/executable-plan.json' in (rd / 'DEVIATIONS.md').read_text()


def test_plan_bound_approval_cannot_drop_input_snapshot(tmp_path):
    rd, _ = lifecycle(tmp_path)
    approve(rd)
    p = rd / 'inputs/checkin1_approval.json'
    record = json.loads(p.read_text())
    record.pop('approved_inputs', None)
    atomic_json(p, record)
    assert ws.verify_approval(str(rd))


def test_input_edit_during_approval_refuses_receipt(tmp_path, monkeypatch):
    from ravel.validation import validate_checkin
    rd, files = lifecycle(tmp_path)
    repin_plan(rd)
    validate = validate_checkin.validate
    def edit(*args, **kwargs):
        result = validate(*args, **kwargs)
        (rd / files[0]).write_text('racing native input bytes')
        return result
    monkeypatch.setattr(validate_checkin, 'validate', edit)
    assert ws.main(['approve', '--rundir', str(rd), '--quote', 'Approve this plan', '--plan', 'smoke']) == 1
    assert not (rd / 'inputs/checkin1_approval.json').exists()


def test_invalid_rendered_card_cannot_be_approved(tmp_path):
    rd, _ = lifecycle(tmp_path)
    path = rd / 'inputs/executable-plan.json'
    plan = json.loads(path.read_text())
    plan['rendered'] = {'run_card.dat': 'expected bytes'}
    atomic_json(path, plan)
    (rd / 'output').mkdir()
    (rd / 'output/run_card.dat').write_text('wrong bytes')
    repin_plan(rd)
    assert ws.main(['approve', '--rundir', str(rd), '--quote', 'Approve this plan', '--plan', 'smoke']) == 1


def test_unreadable_binary_bytes_are_retained_by_digest(tmp_path):
    rd, _ = lifecycle(tmp_path)
    path = rd / 'inputs/executable-plan.json'
    plan = json.loads(path.read_text())
    plan['stages'][0]['inputs'].append('inputs/native-tool.binary')
    (rd / 'inputs/native-tool.binary').write_bytes(b'\xff\x80\x00binary source')
    atomic_json(path, plan)
    approve(rd)
    pins = launch_authorization._capture(rd, 'smoke')['approval_inputs']
    assert any(p['path'].endswith('native-tool.binary') and 'sha256' in p for p in pins)


def test_rendered_edit_during_approval_is_refused(tmp_path, monkeypatch):
    from ravel.validation import validate_checkin
    rd, _ = lifecycle(tmp_path)
    path = rd / 'inputs/executable-plan.json'
    plan = json.loads(path.read_text())
    plan['rendered'] = {'run_card.dat': 'expected bytes'}
    atomic_json(path, plan)
    repin_plan(rd)
    (rd / 'output').mkdir()
    validate = validate_checkin.validate
    def edit(*args, **kwargs):
        result = validate(*args, **kwargs)
        (rd / 'output/run_card.dat').write_text('racing rendered bytes')
        return result
    monkeypatch.setattr(validate_checkin, 'validate', edit)
    assert ws.main(['approve', '--rundir', str(rd), '--quote', 'Approve this plan', '--plan', 'smoke']) == 1
    assert not (rd / 'inputs/checkin1_approval.json').exists()


def test_materialized_rendered_card_deletion_is_refused(tmp_path):
    rd, _ = lifecycle(tmp_path)
    path = rd / 'inputs/executable-plan.json'
    plan = json.loads(path.read_text())
    plan['rendered'] = {'run_card.dat': 'expected bytes'}
    atomic_json(path, plan)
    (rd / 'output').mkdir()
    card = rd / 'output/run_card.dat'
    card.write_text('expected bytes')
    approve(rd)
    card.unlink()
    assert any('output/run_card.dat' in e for e in ws.verify_approval(str(rd)))


def test_relative_run_directory_binds_the_same_inputs(tmp_path, monkeypatch):
    rd, files = lifecycle(tmp_path)
    monkeypatch.chdir(rd.parent)
    assert ws.main(['approve', '--rundir', rd.name, '--quote', 'Approve relative run', '--plan', 'smoke']) == 0
    (rd / files[0]).write_text('changed relative run bytes')
    assert any(files[0] in e for e in ws.verify_approval(rd.name))


def prepared_rendering(tmp_path):
    """Exercise real execution receipts without launching any process."""
    rd, files = lifecycle(tmp_path)
    path = rd / 'inputs/executable-plan.json'
    plan = json.loads(path.read_text())
    plan['rendered'] = {'run_card.dat': 'rendered setting = 1\n'}
    plan['stages'].insert(0, {'stage': 'prepare', 'command': ['/bin/sleep', '0'],
                              'inputs': [*files, 'inputs/checkin1_approval.json'],
                              'outputs': ['output/run_card.dat'], 'depends_on': []})
    atomic_json(path, plan)
    approve(rd)
    prepare_rendering(rd)
    return rd, path, plan


def prepare_rendering(rd, *, after_begin=None):
    from ravel.workflow import execution
    plan = json.loads((rd / 'inputs/executable-plan.json').read_text())
    stage = plan['stages'][0]
    spec = execution.plan_stage(rd, stage['stage'], stage['command'], stage['inputs'],
                                stage['outputs'], [], str(rd))
    record = execution.begin_attempt(rd, stage['stage'], spec, 'logs/prepare.log')
    if after_begin:
        after_begin()
    (rd / 'output').mkdir(exist_ok=True)
    (rd / 'output/run_card.dat').write_text(plan['rendered']['run_card.dat'])
    assert execution.finish_attempt(rd, record, 0) == 0


def amend_rendering(rd, path, plan):
    plan['rendered']['run_card.dat'] = 'rendered setting = 2\n'
    atomic_json(path, plan)
    approve(rd)


def test_reapproval_accepts_receipted_old_rendering_until_prepare_reruns(tmp_path):
    rd, path, plan = prepared_rendering(tmp_path)
    amend_rendering(rd, path, plan)
    assert not ws.verify_approval(str(rd))
    assert launch_authorization._capture(rd, 'smoke')['approval']
    assert 'output/run_card.dat' in (rd / 'DEVIATIONS.md').read_text()
    # begin_attempt archives the old output before launch authorization is read.
    def archived():
        assert not (rd / 'output/run_card.dat').exists()
        assert not ws.verify_approval(str(rd))
        assert launch_authorization._capture(rd, 'smoke')['approval']
    prepare_rendering(rd, after_begin=archived)
    assert not ws.verify_approval(str(rd))


def test_reverted_rendered_card_after_repreparation_refuses_launch(tmp_path):
    rd, path, plan = prepared_rendering(tmp_path)
    card = rd / 'output/run_card.dat'
    old = card.read_bytes()
    amend_rendering(rd, path, plan)
    prepare_rendering(rd)
    assert not ws.verify_approval(str(rd))
    card.write_bytes(old)
    with pytest.raises(ValueError, match='output/run_card.dat'):
        launch_authorization._capture(rd, 'smoke')


def test_hand_edit_to_superseded_rendering_refuses_launch(tmp_path):
    rd, path, plan = prepared_rendering(tmp_path)
    amend_rendering(rd, path, plan)
    (rd / 'output/run_card.dat').write_text('hand edited card\n')
    with pytest.raises(ValueError, match='output/run_card.dat'):
        launch_authorization._capture(rd, 'smoke')


def test_unreceipted_prior_rendering_cannot_be_amended(tmp_path):
    rd, path, plan = prepared_rendering(tmp_path)
    (rd / 'execution_state.json').unlink()
    plan['rendered']['run_card.dat'] = 'rendered setting = 2\n'
    atomic_json(path, plan)
    repin_plan(rd)
    assert ws.main(['approve', '--rundir', str(rd), '--quote', 'Approve amended inputs',
                    '--plan', 'smoke']) == 1


# ---- CJ-F: delegated (machine) re-approval classifies changes within its bounds ---------------

def _delegated_run(tmp_path, monkeypatch, allowed, epoch=None):
    import hashlib as _hashlib
    import intake_sidecar_fixtures as fx
    from ravel.workflow import scientific_autonomy as autonomy
    prompt = "Run autonomously: " + fx.PROMPT
    rd = tmp_path / "run"
    contract, reading, plan = fx.pinned_run(rd, prompt=prompt)
    if epoch is not None:
        contract = {**contract, "agent_layer_epoch": epoch}
    user = rd / "inputs/initial-user-message.txt"
    user.write_text(prompt)
    declared = autonomy.prepare_declaration(
        contract, rd / "inputs/delegation.json",
        user_text={"path": str(user), "sha256": _hashlib.sha256(prompt.encode()).hexdigest()},
        quote="Run autonomously:", origin="initial_prompt", delegate_actor="ravel-coordinator",
        actions=["approve_plan"],
        bounds={"compute_plans": ["none"], "allowed_changed_paths": allowed, "allowed_stages": [], "max_redos": 0},
        task_class="research_analysis", base_dir=rd)
    fx.write_json(rd / "inputs/task_contract.json", declared["document"])
    fx.write_json(rd / "inputs/checkin1.json", fx.checkin1(plan, reading))
    fx.write_json(rd / "inputs/cost_preflight.json", {"schema_version": 1, "generated_by": "cost_preflight.py",
                                                      "mode": "none", "walltime_h": [0, 0]})
    for name in ("settings.cfg", "card.dat"):
        (rd / "inputs" / name).write_text("synthetic setting = 1\n")
    original = ws.approval_input_paths

    def with_declared_reads(rundir):
        return original(rundir) + [str(rd / "inputs/settings.cfg"), str(rd / "inputs/card.dat")]
    monkeypatch.setattr(ws, "approval_input_paths", with_declared_reads)
    from ravel.workflow import gate_wiring
    # These tests isolate approval binding; the R2 approve_plan gate has its own tests (test_gate_wiring_r2r3).
    monkeypatch.setattr(gate_wiring, "require_delegated", lambda rundir, gate, action: None)
    return rd


def test_delegated_reapproval_refuses_changes_outside_allowed_paths(tmp_path, monkeypatch):
    rd = _delegated_run(tmp_path, monkeypatch, ["inputs/settings.cfg"])
    ws.record_delegated_approval(rd, "none")
    before = (rd / "inputs/checkin1_approval.json").read_bytes()
    (rd / "inputs/card.dat").write_text("synthetic setting = 2\n")
    with pytest.raises(ValueError, match="allowed_changed_paths.*inputs/card.dat"):
        ws.record_delegated_approval(rd, "none")
    assert (rd / "inputs/checkin1_approval.json").read_bytes() == before


def test_delegated_reapproval_classifies_an_allowed_change(tmp_path, monkeypatch):
    rd = _delegated_run(tmp_path, monkeypatch, ["inputs/settings.cfg"])
    ws.record_delegated_approval(rd, "none")
    (rd / "inputs/settings.cfg").write_text("synthetic setting = 2\n")
    assert ws.verify_approval(str(rd))
    record = ws.record_delegated_approval(rd, "none")
    rows = record["input_changes"]
    assert [r["path"] for r in rows] == ["inputs/settings.cfg"] and rows[0]["prior_approval_sha256"]
    assert "inputs/settings.cfg" in (rd / "DEVIATIONS.md").read_text()
    assert ws.verify_approval(str(rd)) == []


def test_deleted_approval_cannot_restart_delegated_binding(tmp_path, monkeypatch):
    rd = _delegated_run(tmp_path, monkeypatch, [])
    ws.record_delegated_approval(rd, "none")
    (rd / "inputs/card.dat").write_text("synthetic setting = 2\n")
    (rd / "inputs/checkin1_approval.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        ws.record_delegated_approval(rd, "none")


def test_verification_does_not_write_the_deviation_ledger(tmp_path):
    rd, files = lifecycle(tmp_path)
    approve(rd)
    before = (rd / 'DEVIATIONS.md').read_bytes() if (rd / 'DEVIATIONS.md').exists() else None
    (rd / files[0]).write_text('synthetic setting = 2\n')
    assert ws.verify_approval(str(rd))
    after = (rd / 'DEVIATIONS.md').read_bytes() if (rd / 'DEVIATIONS.md').exists() else None
    assert after == before
    with pytest.raises(ValueError):
        launch_authorization._capture(rd, 'smoke', command=['/bin/sleep', '0'])
    assert files[0] in (rd / 'DEVIATIONS.md').read_text()


def test_deleting_every_approval_run_file_cannot_restart_delegated_binding(tmp_path, monkeypatch):
    rd = _delegated_run(tmp_path, monkeypatch, [])
    ws.record_delegated_approval(rd, "none")
    (rd / "inputs/card.dat").write_text("synthetic setting = 2\n")
    for rel in ("inputs/checkin1_approval.json", ws.DELEGATED_APPROVAL_LOG, "run_state.json"):
        if (rd / rel).exists():
            (rd / rel).unlink()
    with pytest.raises(ValueError, match="custody"):
        ws.record_delegated_approval(rd, "none")
    assert not (rd / "inputs/checkin1_approval.json").exists()


def test_rewritten_prior_approval_is_not_a_delegated_baseline(tmp_path, monkeypatch):
    rd = _delegated_run(tmp_path, monkeypatch, [])
    ws.record_delegated_approval(rd, "none")
    (rd / "inputs/card.dat").write_text("synthetic setting = 2\n")
    path = rd / "inputs/checkin1_approval.json"
    record = json.loads(path.read_text())
    current = ws._approval_inputs_snapshot(str(rd), ws.approval_input_paths(str(rd)))
    record["approved_inputs"] = current
    atomic_json(path, record)
    with pytest.raises(ValueError, match="custody"):
        ws.record_delegated_approval(rd, "none")


def test_human_approval_is_a_custody_baseline_for_delegated_reapproval(tmp_path, monkeypatch):
    rd = _delegated_run(tmp_path, monkeypatch, [])
    from types import SimpleNamespace
    assert ws.cmd_approve(SimpleNamespace(rundir=str(rd), plan="none", quote="approve")) == 0
    (rd / "inputs/card.dat").write_text("synthetic setting = 2\n")
    (rd / "inputs/checkin1_approval.json").unlink()
    with pytest.raises(ValueError, match="custody"):
        ws.record_delegated_approval(rd, "none")


def test_refused_delegated_reapproval_leaves_approval_inputs_untouched(tmp_path, monkeypatch):
    from ravel.workflow import review_points
    rd = _delegated_run(tmp_path, monkeypatch, [], epoch=2)
    assert review_points.approve(rd) is not None
    (rd / "inputs/review_points_approval.json").unlink()
    real = review_points.approve
    monkeypatch.setattr(review_points, "approve", lambda rundir: None)  # an approval recorded before review points
    ws.record_delegated_approval(rd, "none")
    monkeypatch.setattr(review_points, "approve", real)
    (rd / "inputs/card.dat").write_text("synthetic setting = 2\n")
    with pytest.raises(ValueError, match="allowed_changed_paths"):
        ws.record_delegated_approval(rd, "none")
    assert not (rd / "inputs/review_points_approval.json").exists()
    (rd / "inputs/card.dat").write_text("synthetic setting = 1\n")
    assert ws.verify_approval(str(rd)) == []
    record = ws.record_delegated_approval(rd, "none")
    assert any(r["path"] == "inputs/review_points_approval.json" for r in record["approved_inputs"])
    assert ws.verify_approval(str(rd)) == []
