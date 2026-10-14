"""Ordinary adapter/resource binding; no model compilation or numerical calls."""
import pytest

from ravel.physics import workspace_combination_study as study
from ravel.validation import initialized_settings_retained as retained
from ravel.workflow import science


@pytest.mark.parametrize("mode,implementation", [
    ("workspace-combination-study", study),
    ("initialized-settings-retained", retained),
])
def test_new_routes_use_public_adapter_and_prospective_review(mode, implementation):
    spec = {"mode": mode, "task": {"input": "supplied.json"}}
    assert mode in science.MODES
    assert science.adapter(spec) is implementation
    assert science._new_capability(spec) is True


def test_workspace_bounds_distinguish_mathematics_and_supervision(monkeypatch):
    observed = []
    monkeypatch.setattr(study, "validate", lambda task: observed.append(task))
    task = {"input": "supplied.json"}
    assert study.execution_seconds(task, "/unused") == 60
    bounds = study.resource_bounds(task, "/unused")
    assert observed == [task, task]
    assert bounds["maximum_mathematical_workers"] == 1
    assert bounds["processes"] == 2
    assert bounds["maximum_native_children"] == bounds["fits"] == bounds["generated_events"] == 0
    assert bounds["model_compilations"] == 8 and bounds["mean_density_calls"] == 20
    assert bounds["mathematical_seconds"] == 60 and bounds["recommended_outer_seconds"] == 180
    assert (bounds["capture_bytes"], bounds["checkpoint_bytes"], bounds["journal_bytes"]) == (
        64 * 1024**2, 16 * 1024**2, 1024**2)


@pytest.mark.parametrize("hook", [study.execution_seconds, study.resource_bounds])
def test_resource_hooks_keep_task_validation(hook):
    with pytest.raises(ValueError):
        hook({"undeclared": "task"}, "/unused")
