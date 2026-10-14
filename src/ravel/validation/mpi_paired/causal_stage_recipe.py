"""Validate a supplied paired stage graph without launching work."""
from ravel.validation import mpi_observer as observer
from ravel.validation import diagnostic_plan as plans


def stages(*, plan, resources):
    observer.validate_stages(plans.required(plan,'stages'),resources['max_seconds'])
    census=plans.required(plan,'census')
    plans.require(type(census) is dict and census,'census','supplied effect census required')
    for key,value in census.items():
        plans.positive(value,'census.'+key,integer=True,zero=True)
    plans.require(census.get('new_hard_events')==0 and census.get('new_compiles')==0,'census','reuse qualified binary and supplied hard events')
    return {'schema_version':1,'stages':plan['stages'],'census':census,
            'sum_native_command_ceilings_seconds':sum(row['max_seconds'] for row in plan['stages'])}
