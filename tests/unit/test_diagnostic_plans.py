"""Supplied-plan refusal and synthetic parameterization controls."""
import json
from pathlib import Path
import pytest
from ravel.validation import likelihood_profile_probe as profile
from ravel.validation import mpi_observer as observer
from ravel.validation import mpi_paired_effect as paired
from ravel.validation import initialized_settings_retained as retained

@pytest.mark.parametrize('adapter', [profile, observer, paired, retained])
def test_missing_selected_plan_has_typed_refusal(tmp_path, adapter):
    import hashlib
    path = tmp_path/'input.json'
    path.write_text('{}')
    task = {'input': str(path)}
    if adapter in (paired, retained):
        task['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError) as caught:
        adapter.document(task, tmp_path)
    assert getattr(caught.value, 'code', None) == 'missing_input'
    assert getattr(caught.value, 'field', None) == 'plan'

@pytest.mark.parametrize('adapter, constants', [
    (profile, ('ENGINE_SHA256', 'LIMITS', 'TOLERANCES')),
    (observer, ('STAGES',)),
    (paired, ()),
    (retained, ('ARM_IDS', 'STAGE_IDS')),
])
def test_no_installed_study_portfolio(adapter, constants):
    assert all(not hasattr(adapter, name) for name in constants)


def test_no_installed_numerical_or_paired_portfolio():
    from ravel.validation import likelihood_candidate_check, likelihood_step_refinement
    from ravel.validation.mpi_paired import mpi_paired_estimator, paired_effect_inference_v2
    for module,names in ((likelihood_candidate_check,('LIMITS','SELECTORS')),(likelihood_step_refinement,('LIMITS','SELECTED','COORDINATES','CRITERIA')),(mpi_paired_estimator,('REGIONS','SEED','REPLICATES','GAP')),(paired_effect_inference_v2,('N','SOURCE_EXPOSURE','ORDINAL_START'))):
        assert all(not hasattr(module,name) for name in names)


def test_requested_output_cannot_escape_owned_tree(tmp_path):
    from ravel.validation import diagnostic_plan as plans
    from diagnostic_plan_fixture import metadata
    contract={'plan':metadata(file='../outside.json')}
    with pytest.raises(plans.PlanError):plans.selected(contract)
    plan=metadata();alias=tmp_path/'result.json';alias.symlink_to(tmp_path/'outside')
    with pytest.raises(plans.PlanError):plans.publish(tmp_path,plan,{})
