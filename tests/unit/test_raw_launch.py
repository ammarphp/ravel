"""Synthetic journal projections; no native launch or subprocess."""
from ravel.workflow import raw_launch as raw


def test_exact_output_requires_replayed_approval(tmp_path, monkeypatch):
    output = tmp_path/'outputs/events.lhe'; output.parent.mkdir(); output.write_text('synthetic')
    auth = {'event': 'authorized', 'sequence': 1, 'sha256': 'a', 'authorization': {
        'approval': {'sha256': 'b', 'text': '{"input_fingerprint":"c"}'}},
        'context': {'stage_spec': {'cwd': str(tmp_path), 'outputs': ['outputs/events.lhe']}}}
    launch = {'event': 'launched', 'authorization_sequence': 1, 'authorization_sha256': 'a'}
    monkeypatch.setattr(raw.launch_authorization, '_events', lambda root: [auth, launch])
    checked = []
    monkeypatch.setattr(raw.launch_authorization, '_historical_errors', lambda event: checked.append(event))
    assert raw.gate_errors(tmp_path, 'delivery', {}) == []
    assert checked == [auth]
    extra = output.with_name('other.lhe'); extra.write_text('unbound')
    assert raw.gate_errors(tmp_path, 'delivery', {})[0].pins == ('outputs/other.lhe',)
    auth['context']['stage_spec']['outputs'] = ['outputs']
    assert raw.gate_errors(tmp_path, 'delivery', {}) == []


def test_corrupt_journal_never_credits_outputs(tmp_path, monkeypatch):
    output = tmp_path/'stages/s/events.hepmc'; output.parent.mkdir(parents=True); output.write_text('synthetic')
    def corrupt(*args): raise ValueError('broken hash chain')
    monkeypatch.setattr(raw.launch_authorization, '_events', corrupt)
    error = raw.gate_errors(tmp_path, 'final_task', {})[0]
    assert error.code == 'raw_launch' and error.pins == ('stages/s/events.hepmc',)


import pytest

@pytest.mark.parametrize('rel', ['work/events.lhe', 'inputs/events.lhe', 'work/h.yoda', 'work/e.hepmc3', 'work/e.lhco', 'work/e.stdhep'])
def test_lhe_outside_stages_outputs_and_formats_detected(tmp_path, rel):
    p = tmp_path/rel; p.parent.mkdir(); p.write_text('synthetic')
    assert raw.gate_errors(tmp_path, 'delivery', {})[0].pins == (rel,)


def test_snapshotted_external_lhe_excluded(tmp_path):
    from ravel.workflow import rdj_custody
    p = tmp_path/'inputs/e.lhe'; p.parent.mkdir(); p.write_text('supplied')
    rdj_custody.record_input_snapshot(tmp_path, 'run_init')
    assert raw.gate_errors(tmp_path, 'delivery', {}) == []
    p.write_text('changed')
    assert raw.gate_errors(tmp_path, 'delivery', {})


def test_root_file_without_generator_provenance_not_flagged(tmp_path):
    from rdj_fixtures import Run
    r = Run(tmp_path/'run')
    r.stage('histogram', 'outputs/histogram.root', b'histogram')
    assert raw.gate_errors(r.root, 'delivery', {}) == []


def test_root_histogram_declared_by_authorized_stage_dir_accepted(tmp_path, monkeypatch):
    output = tmp_path/'outputs/histogram.root'; output.parent.mkdir(); output.write_text('synthetic')
    auth = {'event': 'authorized', 'sequence': 1, 'sha256': 'a', 'authorization': {
        'approval': {'sha256': 'b', 'text': '{"input_fingerprint":"c"}'}},
        'context': {'stage_spec': {'cwd': str(tmp_path), 'outputs': ['outputs']}}}
    launch = {'event': 'launched', 'authorization_sequence': 1, 'authorization_sha256': 'a'}
    monkeypatch.setattr(raw.launch_authorization, '_events', lambda root: [auth, launch])
    monkeypatch.setattr(raw.launch_authorization, '_historical_errors', lambda event: None)
    assert raw.gate_errors(tmp_path, 'delivery', {}) == []


def test_unregistered_histogram_stage_cannot_hide_unbound_root(tmp_path):
    from rdj_fixtures import Run
    r = Run(tmp_path/'run')
    r.stage('histogram', 'outputs/histogram.root', b'histogram', register=False)
    assert raw.gate_errors(r.root, 'delivery', {})[0].pins == ('outputs/histogram.root',)
