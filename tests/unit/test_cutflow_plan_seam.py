"""Supplied cutflow input closure joins the ordinary native planner; no native launch."""
import pytest
from ravel.physics import compressed_validation as validation
from source_record_fixtures import TRACE_PRODUCER


def test_native_trace_plan_requires_explicit_cutflow_definition(tmp_path):
    with pytest.raises(ValueError) as error:validation.native_plan_inputs(None,tmp_path,TRACE_PRODUCER)
    assert error.value.reason=='missing_cutflow_definition'


def test_public_definition_views_cannot_mutate_admitted_population(tmp_path):
    from source_record_fixtures import cutflow
    binding,value=cutflow(tmp_path)
    bound=validation.bind(binding)
    changed=bound.value;changed['predicates'].clear()
    changed_pin=bound.pin;changed_pin['sha256']='0'*64
    assert bound.value['predicates']==value['predicates'] and bound.pin==binding
    with pytest.raises(TypeError):bound.sources['selection']=b'invented source'
