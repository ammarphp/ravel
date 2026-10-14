"""Missing supplied scientific inputs must refuse before inspecting payloads."""
import pytest
from ravel.physics import truth_reco_response as truth
from ravel.physics import hhh_native_trace as trace
from ravel.physics import native_group_fills as groups
from ravel.physics import native_cumulant as cumulant

@pytest.mark.parametrize('operation', ['response', 'instrumentation', 'groups', 'cumulant'])
def test_missing_supplied_input_is_typed(operation):
    with pytest.raises(ValueError) as caught:
        if operation == 'response':
            truth.analyze_event({})
        elif operation == 'instrumentation':
            trace.instrument(b'')
        elif operation == 'groups':
            groups._acquire('absent', 'absent', {}, expected_trace_sha256='', expected_raw_sha256='')
        else:
            cumulant.validate_request({})
    assert caught.value.reason == 'missing_input'

@pytest.mark.xfail(reason="awaits GEN-3B",strict=True)
def test_selected_analysis_package_loader_interface():
    from ravel.physics import analysis_packages
    assert callable(analysis_packages.load_instrumentation)

@pytest.mark.parametrize('module,bindings',[(truth,('PT_EDGES','ABS_ETA_EDGES','FOUR_STATES','SLEPTONS','FLAVOURS','ORIGINS')),(trace,('ORIGINAL','ROUTINE','SOURCE_SHA256','FEATURES','SUPPORT')),(groups,('SITES','_SOURCE_SHA','_MODEL_SHA','_RMISS')),(cumulant,('ROUTINE','PROTOCOL','SOURCE_DIGESTS','SOURCE_FILES','POPULATION','ECORR_TABLE'))])
def test_fixed_product_populations_and_source_bindings_are_gone(module,bindings):
    assert all(not hasattr(module,name) for name in bindings)

def test_cumulant_package_ships_no_source_snapshot():
    from pathlib import Path
    root=Path(cumulant.__file__).resolve().parents[1]/'data/native_cumulants'
    assert {p.name for p in root.iterdir()}=={'README.md'}
