"""Legacy delivery writers refuse controller-owned runs; legacy runs stay available and NOT GOVERNED."""
from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from test_p06_support import operator_home  # noqa: F401

from ravel.controller import sink
from ravel.controller.sink import legacy
from ravel.workflow import (architecture_receipt, procedure_export, requester_delivery, result_pack, result_templates,
                            scientific_task_delivery, submission_export, task_completion)
from p07_support import RUN_ID, run  # noqa: F401  (run fixture)

REFUSED = 'refused for the controller-owned run'


def nothing_written(run_, before):
    return sorted(p.relative_to(run_.dir).as_posix() for p in run_.dir.rglob('*')) == before


def listing(run_):
    return sorted(p.relative_to(run_.dir).as_posix() for p in run_.dir.rglob('*'))


def test_result_pack_refuses_a_controller_owned_run(run):
    before = listing(run)
    with pytest.raises(result_pack.PackError, match=REFUSED):
        result_pack.main(['--rundir', str(run.dir), '--stat-mode', 'none-survey', '--detector-mode', 'particle-level'])
    assert nothing_written(run, before)


def test_requester_delivery_refuses_a_controller_owned_run_and_workspace(run, tmp_path):
    before = listing(run)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        requester_delivery.deliver(run.dir, {'report': 'REPORT.md'}, tmp_path / 'workspace')
    assert not (tmp_path / 'workspace').exists() and nothing_written(run, before)
    legacy_run = tmp_path / 'legacy-run'
    legacy_run.mkdir()
    with pytest.raises(sink.SinkRefused, match=REFUSED):  # a workspace inside a controller run is refused too
        requester_delivery.deliver(legacy_run, {'report': 'REPORT.md'}, run.dir / 'workspace')
    assert nothing_written(run, before)


def test_submission_export_refuses_before_any_staging(run, tmp_path):
    request = {'schema_version': 1, 'kind': submission_export.REQUEST_KIND, 'title': 'fictional', 'rundir': str(run.dir),
               'claim_scope': 'fictional-scope', 'results': ['result.json'], 'figures': [], 'note': [], 'recipe': [],
               'code': [], 'environment': [], 'inputs': [], 'audit': {'logs': [], 'transcripts': []},
               'partitions': [], 'site_workflow': None, 'code_repository': None}
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request))
    repository = tmp_path / 'repository'
    repository.mkdir()
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        submission_export.export(path, repository)
    assert list(repository.iterdir()) == []


def test_template_fill_refuses_a_controller_owned_run(run, tmp_path):
    before = listing(run)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        result_templates.fill(tmp_path / 'template.yaml', tmp_path / 'result.json', tmp_path / 'filled.yaml',
                              rundir=run.dir, claim_scope='fictional-scope')
    assert not (tmp_path / 'filled.yaml').exists() and nothing_written(run, before)


def test_task_completion_paths_refuse_a_controller_owned_run(run):
    before = listing(run)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        task_completion.qualified_delivery(run.dir)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        task_completion.require_final({'path': str(run.dir / 'x.json'), 'sha256': '0' * 64, 'size': 1},
                                      base_dir=run.dir)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        task_completion.final_gate(run.dir)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        task_completion.compose(run.dir, write=True)
    assert nothing_written(run, before)


def test_whole_task_artifact_delivery_refuses_a_controller_owned_run(run):
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        scientific_task_delivery.deliver({'schema_version': 1, 'format': 'json', 'artifact_request': {}},
                                         base_dir=run.dir)


def test_procedure_export_refuses_a_controller_owned_run(run, tmp_path):
    before = listing(run)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        procedure_export.export(run.dir, tmp_path / 'procedure')
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        procedure_export.export_for_delivery(run.dir)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        procedure_export.export(tmp_path, run.dir / 'procedure')
    assert not (tmp_path / 'procedure').exists() and nothing_written(run, before)


def test_legacy_delivery_labelling_refuses_and_the_receipt_is_the_controllers(tmp_path, monkeypatch, operator_home):
    from test_p07_receipts import authenticated_run, current_authority, observed_ack
    run = authenticated_run(tmp_path, monkeypatch)
    current_authority(run)
    observed_ack(run)
    with pytest.raises(sink.SinkRefused, match=REFUSED):
        architecture_receipt.label_delivery(run.dir, [], label='diagnostic')
    receipt = architecture_receipt.build_receipt(run.dir, [{'path': 'anything', 'kind': 'number'}])
    assert receipt['schema_version'] == 2 and receipt['run_id'] == RUN_ID
    assert receipt['delivery']['status'] == 'not delivered' and receipt['architecture_complete'] is False
    run.deliver()
    receipt = architecture_receipt.build_receipt(run.dir)
    assert receipt['label'] == 'accepted' and receipt['verification']['delivery_intact'] is True


def test_legacy_runs_keep_working_and_carry_not_governed(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    receipt = architecture_receipt.build_receipt(tmp_path)
    assert 'NOT GOVERNED' in receipt['notices'] and receipt['governance']['label'] == 'NOT GOVERNED'
    assert receipt['architecture_predicates']['controller_mode'] is False
    assert receipt['architecture_complete'] is False
    architecture_receipt.verify_saved_receipt(receipt)
    labelled = architecture_receipt.label_delivery(tmp_path, [], label='diagnostic')
    assert labelled['delivery_label'] == 'diagnostic' and 'NOT GOVERNED' in labelled['notices']


def test_a_legacy_receipt_is_never_architecture_complete_even_with_complete_custody(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    from ravel.workflow import research_architecture
    monkeypatch.setattr(research_architecture, 'observe', lambda root, artifacts, admissibility: {'complete': True})
    monkeypatch.setattr(architecture_receipt, '_role_observations', lambda root: {
        'status': 'observed', 'roles': [], 'dispatches': [], 'missing': [], 'blocking_points': [], 'errors': []})
    receipt = architecture_receipt.build_receipt(tmp_path)
    assert receipt['architecture_predicates'] == {'controller_mode': False, 'research_join_complete': True,
                                                  'required_roles_credited': True}
    assert receipt['architecture_complete'] is False


def test_host_governance_reasons_reach_the_notices(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    from ravel.workflow import host_governance
    real = host_governance.enforcement_record
    monkeypatch.setattr(host_governance, 'enforcement_record', lambda root: {
        **real(root), 'governance': {'label': 'NOT GOVERNED', 'reasons': ['hooks disabled by a fictional setting']}})
    receipt = architecture_receipt.build_receipt(tmp_path)
    assert any('hooks disabled by a fictional setting' in n for n in receipt['notices'])


def test_SW24_procedure_byte_ceiling_of_a_controller_run_ignores_the_environment(run, tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '5')
    assert procedure_export._byte_ceiling(run.dir) == 2048  # the operator's value (fake authority)
    assert procedure_export._byte_ceiling(tmp_path) == 5  # a legacy run keeps its documented setting
    monkeypatch.setitem(sys.modules, 'ravel.controller.authority', types.ModuleType('ravel.controller.authority'))
    assert procedure_export._byte_ceiling(run.dir) == procedure_export.DEFAULT_BYTE_CEILING


SCANNER = b'''
ENV = "RAVEL_RESTRICTED_SOURCES"
def load_deny_list(path):
    return [line.strip() for line in open(path) if line.strip()]
def scan(paths, deny, root=None):
    found = []
    for base in paths:
        import pathlib
        for p in pathlib.Path(base).rglob("*"):
            if p.is_file() and deny and any(term in p.read_text() for term in deny):
                found.append({"path": str(p)})
    return found
'''


def test_SW22_restricted_source_policy_of_a_controller_run_is_the_pinned_list(run, tmp_path, monkeypatch):
    monkeypatch.setattr(submission_export, '_git', lambda *a, **k: subprocess.CompletedProcess(a, 0, SCANNER, b''))
    vendor = tmp_path / 'vendor'
    vendor.mkdir()
    (vendor / 'module.py').write_text('fictional-withheld-term\n')
    deny = tmp_path / 'deny.txt'
    deny.write_text('fictional-withheld-term\n')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(tmp_path / 'absent.txt'))
    # No pinned policy: absence is not permission, whatever the environment says.
    monkeypatch.setattr(submission_export, '_pinned_deny_list', lambda run_id: None)
    with pytest.raises(ValueError, match='no pinned restricted-source policy'):
        submission_export._restricted_source_scan(tmp_path, 'v0', vendor, controller_run=RUN_ID)
    from ravel.workflow.submission_export import file_sha256
    pinned = {'path': str(deny), 'sha256': file_sha256(deny)}
    monkeypatch.setattr(submission_export, '_pinned_deny_list', lambda run_id: pinned)
    with pytest.raises(ValueError, match='restricted-source finding'):
        submission_export._restricted_source_scan(tmp_path, 'v0', vendor, controller_run=RUN_ID)
    (vendor / 'module.py').write_text('clean\n')
    assert submission_export._restricted_source_scan(tmp_path, 'v0', vendor, controller_run=RUN_ID) == \
        {'deny_list': 'pinned', 'findings': 0}
    deny.write_text('changed after intake\n')
    with pytest.raises(ValueError, match='changed after intake'):
        submission_export._restricted_source_scan(tmp_path, 'v0', vendor, controller_run=RUN_ID)


def test_sink_stage_and_ownership_rules(run, tmp_path, monkeypatch):
    assert legacy.refuse_controller_owned(tmp_path / 'elsewhere', 'a writer') is None
    with legacy.stage('fictional stage'):
        assert legacy.refuse_controller_owned(run.dir, 'a writer') == RUN_ID
        assert legacy.current_stage() == 'fictional stage'
    assert legacy.current_stage() is None
    with pytest.raises(sink.SinkRefused):
        legacy.refuse_controller_owned(run.dir / 'steps' / 'deep', 'a writer')

    def unknown(path):
        raise ValueError('the controller-run marker cannot be read')
    monkeypatch.setattr(sys.modules['ravel.controller.store'], 'controller_owned', unknown)
    with pytest.raises(ValueError, match='cannot be read'):  # ownership that cannot be read refuses (fail closed)
        legacy.refuse_controller_owned(tmp_path, 'a writer')


def test_without_the_controller_core_no_run_is_controller_owned(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', None)
    assert legacy.owner(tmp_path) is None and legacy.refuse_controller_owned(tmp_path, 'a writer') is None
