"""Common worker delivery of model source and inert native-check outcomes."""
import json

import pytest

from ravel.physics import model_authoring, science_worker
from ravel.plotting import science_figures
from test_model_authoring import fake_feynrules, zprime


def _worker(tmp_path, monkeypatch, *, native=None, lint_passed=True):
    provider = fake_feynrules(tmp_path)
    monkeypatch.setenv('FEYNRULES_ROOT', str(provider))
    model = tmp_path / 'model.json'
    model.write_text(json.dumps(zprime()))
    request = {'schema_version': 1, 'spec': {
        'path': str(model), 'sha256': model_authoring._sha(model)}}
    calls = []
    if native is not None:
        request.update(native={'wolframscript': 'inert-kernel'}, process='a a > b b')

        def observed_native(out, **kwargs):
            calls.append((out, kwargs))
            return dict(native)

        monkeypatch.setattr(model_authoring, 'run_native', observed_native)
    else:
        monkeypatch.setattr(model_authoring, 'run_native',
                            lambda *a, **k: pytest.fail('source authoring invoked a native process'))
    if not lint_passed:
        from ravel.physics import fr_lint
        original = fr_lint.lint

        def failed_lint(*args, **kwargs):
            report = original(*args, **kwargs)
            return {**report, 'passed': False, 'errors': [*report['errors'], 'synthetic lint finding']}

        monkeypatch.setattr(fr_lint, 'lint', failed_lint)
    request_path = tmp_path / 'request.json'
    request_path.write_text(json.dumps(request))
    spec = {'schema_version': 2, 'mode': 'model-authoring',
            'task': {'request': str(request_path)}, 'assumptions': []}
    run = tmp_path / 'run'
    run.mkdir()
    proposal = {'base_dir': str(tmp_path), 'attempt': 1,
                'output_directory': 'outputs/attempt-1', 'stage_binding': {'input_snapshot': {}}}
    # The real adapter and common delivery boundary execute. Authority and plotting
    # are inert; this control establishes the result contract at that boundary.
    monkeypatch.setattr(science_worker, 'verify_worker', lambda _: proposal)
    monkeypatch.setattr(science_worker, 'execution_spec', lambda _: spec)
    monkeypatch.setattr(science_figures, 'render', lambda *_: {'figures': [], 'tables': []})
    code = science_worker.main([str(run), '--attempt', '1'])
    output = run / proposal['output_directory']
    return code, output, calls


def test_source_authoring_reaches_common_worker_delivery_with_its_actual_scope(tmp_path, monkeypatch):
    code, output, calls = _worker(tmp_path, monkeypatch)
    result = json.loads((output / 'result.json').read_text())
    assert code == 0 and calls == []
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert result['authoring']['status'] == 'authored'
    assert result['native_run_performed'] is False and result['native_result'] is None
    assert result['scope'] == 'Generated model source, static lint and exact charge census'
    assert json.loads((output / 'verification.json').read_text())['passed'] is True
    assert json.loads((output / 'model-authoring/authoring.json').read_text()) == result['authoring']
    assert (output / 'model-authoring/model-card.md').is_file()


@pytest.mark.parametrize('status,passed,code', [
    ('checked', True, 0), ('failed', False, 3), ('admission_incomplete', False, 3),
])
def test_native_admission_outcome_survives_common_worker_delivery(tmp_path, monkeypatch, status, passed, code):
    native = {'status': status, 'passed': passed, 'checks': {'scope': 'inert native outcome'}}
    actual, output, calls = _worker(tmp_path, monkeypatch, native=native)
    result = json.loads((output / 'result.json').read_text())
    assert actual == code and len(calls) == 1
    assert result['native_run_performed'] is True
    assert result['native_result'] == native
    assert result['authoring']['native_status'] == status
    assert result['status'] == ('passed' if passed else 'failed')
    assert result['physics_validated'] is False
    assert json.loads((output / 'verification.json').read_text())['passed'] is passed
    assert json.loads((output / 'checkin2.json').read_text())['sections']['waypoint']['status'] == result['status']


def test_failed_source_checks_stay_failed_and_prevent_native_execution(tmp_path, monkeypatch):
    code, output, calls = _worker(tmp_path, monkeypatch, lint_passed=False,
                                  native={'status': 'checked', 'passed': True})
    result = json.loads((output / 'result.json').read_text())
    assert code == 3 and calls == []
    assert result['status'] == 'failed' and result['physics_validated'] is False
    assert result['authoring']['status'] == 'lint_failed'
    assert result['native_run_performed'] is False and result['native_result'] is None
    assert json.loads((output / 'verification.json').read_text())['passed'] is False
