"""Unexecuted whole-context AR1 controls; root owns actual software dispatch."""
import pytest
from test_autonomy_v2_authority_joins import request
from ravel.workflow import scientific_autonomy as autonomy


@pytest.mark.parametrize('opening,closing',[(chr(34),chr(34)),("'","'"),('“','”'),('‘','’'),('«','»'),('‹','›'),('`','`')])
@pytest.mark.parametrize('command_inside',[True,False])
def test_paired_whole_context_quotation_controls(tmp_path,opening,closing,command_inside):
    if command_inside:
        message='The supplied manual says '+opening+'Inspect the inputs. Run autonomously.'+closing
        with pytest.raises(ValueError):request(tmp_path,message)
        assert not (tmp_path/'delegation.json').exists()
    else:
        message='The supplied manual says '+opening+'Inspect the inputs.'+closing+' Run autonomously.'
        result=request(tmp_path,message)
        assert autonomy.delegation_intent(message) is not None
        assert result['execution_authorized'] is False
        assert result['document']['autonomy']


@pytest.mark.parametrize('message,allowed',[
    ('Only after I approve:\nSteps:\nRun autonomously.',False),
    ('Only after I approve:\nSteps:\n  Phase one:\n    Run autonomously.',False),
    ('Only after I approve:\n\nSteps:\nRun autonomously.',False),
    ('If I confirm:\nSteps:\nInspect the inputs.\nRun autonomously.',False),
    ('Source excerpt:\nProcedure:\nRun autonomously.',False),
    ('Steps:\nRun autonomously.',True),
    ('Run autonomously. If the resonance mass is below 500 GeV, include the low-mass searches.',True),
    ("Construct the Z' to WW limit plot. Run autonomously.",True),
])
def test_inherited_governing_header_controls(tmp_path,message,allowed):
    if allowed:
        result=request(tmp_path,message)
        assert autonomy.delegation_intent(message) is not None
        assert result['execution_authorized'] is False
    else:
        with pytest.raises(ValueError):request(tmp_path,message)
        assert not (tmp_path/'delegation.json').exists()
