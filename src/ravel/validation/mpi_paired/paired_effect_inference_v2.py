"""Authenticated paired intervention inference for supplied finite cohorts."""
from pathlib import Path
import hashlib
import json
from ravel.validation import diagnostic_plan as plans
from ravel.validation.mpi_paired.paired_trace_custody import read_arm, paired_census, require
from ravel.validation.mpi_paired.paired_moments import moments
from ravel.validation.mpi_paired.mpi_paired_estimator import compare, descriptor as estimand
from ravel.validation.mpi_paired.full_signal_moments import summarize, specification


def validate_descriptor(descriptor,signal_spec):
    estimand(descriptor)
    n=plans.positive(plans.required(descriptor,'analyzed_events'),'analyzed_events',integer=True)
    original=plans.positive(plans.required(descriptor,'original_events'),'original_events',integer=True)
    require(1<n<=original,'complete paired exposure required')
    ordinals=plans.required(descriptor,'original_ordinals')
    require(type(ordinals) is list and len(ordinals)==n and len(set(ordinals))==n and all(type(x) is int and 0<=x<original for x in ordinals),'complete unique supplied source ordinals required')
    require(type(plans.required(descriptor,'trace_metadata')) is dict,'explicit trace recipe required')
    require(set(signal_spec)=={'channel_order','channel_map','trace_regions','cross_section_pb','kfactor','luminosity_pb_inverse'},'closed signal specification required')
    specification(signal_spec['channel_order'],signal_spec['channel_map'],signal_spec['trace_regions'])
    require(set(descriptor['regions'])<=set(signal_spec['trace_regions']),'primary region outside trace population')
    for key in ('cross_section_pb','kfactor','luminosity_pb_inverse'):
        plans.positive(signal_spec[key],'signal_spec.'+key)
    return descriptor


def infer(*, expected_pin, arms, selection_sources, signal_spec, descriptor, check_budget):
    validate_descriptor(descriptor,signal_spec)
    n=descriptor['analyzed_events'];original=descriptor['original_events']
    require(set(arms)=={'on','off'},'two paired arms required')
    raw=Path(expected_pin['path']).read_bytes()
    require(len(raw)==expected_pin['bytes'] and hashlib.sha256(raw).hexdigest()==expected_pin['sha256'],'complete identity manifest changed')
    expected=json.loads(raw)
    require(expected.get('subset_exposure')==n and expected.get('original_generation_exposure')==original,'supplied exposure differs')
    require([row['original_ordinal'] for row in expected['rows']]==descriptor['original_ordinals'],'supplied original cohort differs')
    admitted={}
    for arm in ('on','off'):
        check_budget()
        require(set(arms[arm])=={'transport_pin','command_pins'},'closed paired arm contract required')
        admitted[arm]=read_arm(expected_pin=expected_pin,selection_sources=selection_sources,descriptor=descriptor,check_budget=check_budget,**arms[arm])
    census=paired_census(admitted['on'][0],admitted['off'][0]);check_budget()
    estimate=compare(admitted['on'][1],admitted['off'][1],admitted['on'][2],admitted['off'][2],descriptor);check_budget()
    require(estimate['pair_census']==census,'estimator did not use authenticated census')
    covariance=moments(census);target=descriptor['regions'].index(descriptor['target_region'])
    for left,right in ((estimate['fraction_on'],covariance['fractions_on'][target]),(estimate['fraction_off'],covariance['fractions_off'][target]),(estimate['delta_off_minus_on'],covariance['delta_off_minus_on'][target]),(estimate['paired_variance'],covariance['delta_covariance'][target][target]),(estimate['paired_cross_arm_covariance'],covariance['cross_covariance_on_off'][target][target])):
        require(abs(left-right)<=1e-12+1e-10*abs(right),'independent paired moments disagree')
    signal=summarize(admitted['on'][1],admitted['off'][1],analyzed_events=n,original_events=original,**signal_spec);check_budget()
    return {'schema_version':1,'scope':'Conditional paired sensitivity in the supplied cohort','exposure':{'original_generation_events':original,'analyzed_original_events':n,'original_ordinals':descriptor['original_ordinals'],'new_hard_events':0},'region_order':descriptor['regions'],'selected_rate_on':estimate['selected_on']/n,'selected_rate_off':estimate['selected_off']/n,'primary':estimate,'all_bin_moments':covariance,'signal_moments':signal,'same_full_trace_population_reused':True,'exact_trace_pins':{arm:admitted[arm][0]['trace_pin'] for arm in arms},'exact_transport_pins':{arm:admitted[arm][0]['transport_pin'] for arm in arms},'physics_validated':False,'original_failed_diagnostics_unchanged':True,'automatic_retry':False,'automatic_extension':False}
