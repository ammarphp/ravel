"""Pure mechanical checks. Native receipts here are explicit stand-ins."""
import copy
import json
import math
from pathlib import Path

import pytest

from ravel.physics import model_physical_checks as physical
from ravel.physics import model_derivation_bridge as bridge


def request():
    f=lambda name,anti=False:{'symbol':name,'antiparticle':anti}
    return {'schema_version':1,'hermiticity':True,'feynman_gauge':True,'partial_widths':{
        'mass_unit':'GeV','width_unit':'GeV','simplify_decays':True,'channels':[{
            'id':'H-muon-pair','parent':f('H'),'daughters':[f('mu'),f('mu',True)],'reference':{
                'kind':'scalar-dirac-yukawa','coupling_numerator':'ymm','coupling_denominator':'vev',
                'color_multiplicity':1,'source_interaction':'L_int = -(ymm/vev) H bar(mu) mu',
                'source_basis':{'path':'SM.fr','sha256':'a'*64},
                'absolute_tolerance':1e-12,'relative_tolerance':1e-7}}]}}


def number(x): return {'real':x,'imag':0}


def native(r=None):
    r=r or request()
    value=physical.scalar_dirac_width(125,0.10566,0.10566/246,1)
    return {'schema_version':1,'request':copy.deepcopy(r),'gauge_before':'True','gauge_after':'True',
        'hermiticity':{'requested':True,'message_free':True,'returned_list':True,'vertex_count':0,'expression':'{}'},
        'widths_message_free':True,'vertices_returned_list':True,'vertex_count':1,'widths_returned_list':True,
        'raw_width_rows':[{'fields':['H','mu','mubar'],'symbolic':'ymm^2 MH (1-4 MMU^2/MH^2)^(3/2)/(8 Pi vev^2)','numeric':number(value)}],
        'channels':[{'request':copy.deepcopy(r['partial_widths']['channels'][0]),'resolved_fields':['H','mu','mubar'],
            'fields_recognized':True,'parent_scalar':True,'daughters_dirac':True,'masses':[number(125),number(.10566),number(.10566)],
            'matched_count':1,'raw_row_index':0}],
        'parameters':{'ymm':number(.10566),'vev':number(246)},
        'partial_width_cache_before':'{}','partial_width_cache_after':'{}',
        'selected_supplied_widths_before':[number(.004)],'selected_supplied_widths_after':[number(.004)],
        'global_partial_width_cache_written':False,'total_width_card_updated':False}


def test_actual_selected_formula_arithmetic_and_scope():
    report=physical.witness(native(),request())
    assert report['passed'] and report['hermiticity_passed']
    assert report['channels'][0]['reference']['absolute_residual']==0
    assert not report['physics_validated'] and not report['complete_total_width_checked']
    assert not report['independent_amplitude_evaluation_performed']
    assert report['selected_supplied_total_widths_unchanged']


@pytest.mark.parametrize('mutate',[
    lambda n:n.update(gauge_after='False'),
    lambda n:n.update(gauge_before='Global`FeynmanGauge'),
    lambda n:n.update(request={}),
    lambda n:n.update(global_partial_width_cache_written=True),
    lambda n:n.update(total_width_card_updated=True),
    lambda n:n.update(partial_width_cache_after='{new cache}'),
    lambda n:n.update(selected_supplied_widths_after=[number(.008)]),
    lambda n:n.update(widths_message_free=False),
    lambda n:n.update(vertex_count=0),
    lambda n:n.update(vertex_count=True),
    lambda n:n.update(widths_returned_list=False),
    lambda n:n.update(channels=[]),
    lambda n:n.update(raw_width_rows=[]),
    lambda n:n['hermiticity'].update(expression='True'),
    lambda n:n['hermiticity'].update(vertex_count=True),
    lambda n:n['hermiticity'].update(message_free=False),
    lambda n:n['hermiticity'].update(vertex_count=1,expression='{bad vertex}'),
    lambda n:n['channels'][0].update(matched_count=0,raw_row_index=-1),
    lambda n:n['channels'][0].update(matched_count=2),
    lambda n:n['channels'][0].update(raw_row_index=True),
    lambda n:n['channels'][0].update(fields_recognized=False),
    lambda n:n['channels'][0].update(parent_scalar=False),
    lambda n:n['channels'][0].update(daughters_dirac=False),
    lambda n:n['channels'][0].update(resolved_fields=['H','e','ebar']),
    lambda n:n['channels'][0].update(masses=[number(-125),number(.10566),number(.10566)]),
    lambda n:n['channels'][0].update(masses=[number(.21132),number(.10566),number(.10566)]),
    lambda n:n['channels'][0].update(masses=[number(.1),number(.10566),number(.10566)]),
    lambda n:n['channels'][0].update(masses=[number(125),number(.10566),number(.10567)]),
    lambda n:n['channels'][0]['masses'][0].update(imag=1e-15),
    lambda n:n['raw_width_rows'][0].update(numeric=number(-1)),
    lambda n:n['raw_width_rows'][0].update(numeric={'unevaluated':'PartialWidth[unknown]'}),
    lambda n:n['raw_width_rows'][0].update(numeric=number(True)),
    lambda n:n['raw_width_rows'][0].update(numeric=number(float('nan'))),
    lambda n:n['parameters'].update(vev=number(0)),
    lambda n:n['parameters'].update(extra=number(1)),
    lambda n:n['parameters'].update(ymm={'unevaluated':'ymm'}),
    lambda n:n['raw_width_rows'].append(copy.deepcopy(n['raw_width_rows'][0])),
])
def test_actual_returned_population_source_and_numeric_adversaries(mutate):
    n=native();mutate(n)
    assert not physical.witness(n,request())['passed']


def test_incorrect_yukawa_coupling_or_normalization_is_a_measured_mismatch():
    n=native();n['parameters']['ymm']=number(.2)
    report=physical.witness(n,request())
    assert not report['passed'] and report['channels'][0]['reference']['absolute_residual']>0
    n=native();n['raw_width_rows'][0]['numeric']['real']*=2
    assert not physical.witness(n,request())['passed']


def test_unselected_complex_widths_are_retained_not_qualified_or_silently_removed():
    n=native();n['raw_width_rows'].append({'fields':['mu','H','mu'],'symbolic':'sqrt(negative)', 'numeric':{'real':0,'imag':2}})
    report=physical.witness(n,request())
    assert report['passed'] and report['retained_raw_channel_count']==2 and len(report['channels'])==1


@pytest.mark.parametrize('change',[
    lambda r:r.update(schema_version=True),lambda r:r.update(hermiticity='true'),
    lambda r:r.update(feynman_gauge=None),lambda r:r['partial_widths'].update(width_unit='MeV'),
    lambda r:r['partial_widths'].update(simplify_decays=1),
    lambda r:r['partial_widths']['channels'][0]['parent'].update(symbol='Get[evil]'),
    lambda r:r['partial_widths']['channels'][0]['parent'].update(symbol='FeynRules`H'),
    lambda r:r['partial_widths']['channels'][0]['daughters'][0].update(antiparticle=1),
    lambda r:r['partial_widths']['channels'][0]['reference'].update(kind='generic'),
    lambda r:r['partial_widths']['channels'][0]['reference'].update(coupling_numerator='ymm/vev'),
    lambda r:r['partial_widths']['channels'][0]['reference'].update(color_multiplicity=True),
    lambda r:r['partial_widths']['channels'][0]['reference'].update(absolute_tolerance=-1),
    lambda r:r['partial_widths']['channels'][0]['reference'].update(relative_tolerance=float('inf')),
    lambda r:r['partial_widths']['channels'][0]['reference'].update(source_interaction=''),
    lambda r:r['partial_widths']['channels'][0]['reference']['source_basis'].update(sha256='latest'),
    lambda r:r['partial_widths']['channels'][0]['daughters'][1].update(antiparticle=False),
    lambda r:r['partial_widths']['channels'].append(copy.deepcopy(r['partial_widths']['channels'][0])),
])
def test_bounded_declared_channels_not_free_executable_expressions(change):
    r=request();change(r)
    with pytest.raises(ValueError):physical.validate(r)


def test_requested_channels_can_be_measured_without_an_applicable_analytic_reference():
    r=request();r['partial_widths']['channels'][0]['reference']=None;n=native(r);n['parameters']={}
    n['channels'][0].update(parent_scalar=False,daughters_dirac=False)
    result=physical.witness(n,r)
    assert result['passed'] and result['channels'][0]['reference'] is None


def test_hermiticity_only_is_useful_and_never_requests_decays():
    r=request();r['partial_widths']['channels']=[];n=native();n['request']=copy.deepcopy(r)
    n.update(raw_width_rows=[],channels=[],parameters={},vertex_count=0,selected_supplied_widths_before=[],selected_supplied_widths_after=[])
    assert physical.witness(n,r)['passed']
    with pytest.raises(ValueError):physical.validate({**r,'hermiticity':False})


def test_hermiticity_not_requested_is_explicit_not_inferred_from_width_success():
    r=request();r['hermiticity']=False;n=native(r)
    n['hermiticity']={'requested':False,'message_free':False,'returned_list':False,'vertex_count':-1,'expression':'$Failed'}
    assert physical.witness(n,r)['passed']


def test_reference_closed_threshold_color_coupling_controls():
    with pytest.raises(ValueError):physical.scalar_dirac_width(2,1,.2,1)
    with pytest.raises(ValueError):physical.scalar_dirac_width(1,1,.2,1)
    base=physical.scalar_dirac_width(125,.1,.2,1)
    assert physical.scalar_dirac_width(125,.1,.4,1)==4*base
    assert physical.scalar_dirac_width(125,.1,-.2,3)==3*base
    assert physical.scalar_dirac_width(125,0,0,1)==0


def test_reference_source_pin_is_a_consumed_input_and_changed_source_refuses(tmp_path):
    basis=tmp_path/'SM.fr';basis.write_text('Source interaction fixture, not an actual model')
    r=request();r['partial_widths']['channels'][0]['reference']['source_basis']={'path':'SM.fr','sha256':bridge.custody._hash(basis)}
    assert physical.inputs(r,tmp_path)==[basis]
    basis.write_text('altered')
    with pytest.raises(ValueError):physical.inputs(r,tmp_path)


def test_actual_released_api_option_and_channel_semantics_in_generated_script():
    text=physical.script(request())
    assert 'FeynRules`CheckHermiticity[lag, FeynRules`FlavorExpand->True]' in text
    assert 'FeynRules`ComputeWidths[selectedVertices,System`Save->False,FeynRules`SimplifyDecays->True]' in text
    assert 'FeynRules`MaxParticles->3' in text and 'FeynRules`SelectParticles->Map' in text
    assert 'FeynRules`anti[Global`mu]' in text
    assert 'rawWidthRows' in text and 'Length[positions]' in text
    assert 'OwnValues[FeynRules`FR$PartialWidths]' in text
    assert 'PartialWidth[' not in text and 'TotWidth[' not in text and 'DecayFeynmanRules[' not in text
    assert 'UpdateWidths[' not in text and 'Global`FeynmanGauge=' not in text and 'Abs[' not in text
    assert 'Global`ymm' in text and 'Global`vev' in text


def legacy_config():
    pin = {'path': '/bound/file', 'sha256': 'a' * 64}
    return {'schema_version': 1, 'operation': 'feynrules-source-ufo', 'source': 'Literal bound model source', 'kernel': pin, 'application_metadata': pin, 'provider_tree': {'root': '/bound/provider', 'manifest': pin}, 'model_tree': {'root': '/bound/model', 'manifest': pin}, 'model_files': ['SM.fr'], 'restrictions': [], 'lagrangian_symbol': 'LSM', 'trusted_provider_source': True, 'trusted_model_source': True, 'provider_readiness_receipt': pin, 'expected_kernel_version': 14.3, 'expected_provider_version': '2.3.49', 'provider_readiness_run': {'path': '/qualified/run', 'attempt_id': 'fixture', 'attempt_record': pin}, 'max_seconds': 900, 'max_ram_mib': 8192}

def legacy_mass_row(name='h', calculated=125.0, model_file=125.0):
    return {'particle': name, 'analytic': 'Sqrt[2 lam] vev', 'calculated': {'real': calculated, 'imag': 0}, 'model_file': {'real': model_file, 'imag': 0}}

def legacy_native():
    return {'process_id': 123, 'kernel_version': 14.3, 'provider_version': '2.3.49', 'provider_root': '/owned/provider', 'model_root': '/owned/model', 'export_root': '/owned/ufo', 'model_files': ['/owned/model/SM.fr'], 'restrictions': [], 'lagrangian_symbol': 'LSM', 'namespace_compatibility': {'mode': 'package_context_symbols_v1', 'message_free_load': True, 'load_messages': [], 'system_definitions_unchanged': True, 'package_commutator_downvalues': 2, 'package_matrix_symbol_downvalues': 8}, 'source_loads': {'provider_load_without_messages': True, 'model_load_without_messages': True, 'requested_model_files': ['/owned/model/SM.fr']}, 'restriction_loads': [], 'electric_charge_symbol_defined': True, 'lagrangian_defined': True, 'lagrangian_nonzero': True, 'lagrangian_leaf_count': 100, 'class_count': 5, 'parameter_count': 10, 'kinetic_result': True, 'kinetic_result_expression': 'True', 'kinetic_nonzero': True, 'kinetic_leaf_count': 15, 'kinetic_api_downvalues': 1, 'mass_api_downvalues': 1, 'kinetic_printed': 'All kinetic terms are correctly normalized.', 'mass_printed': 'All mass terms are diagonal.', 'fermion_kinetic_witness': [], 'mass_coefficients': [], 'mass_rows': [legacy_mass_row()], 'parallel_disabled': True, 'parallel_kernels_list': True, 'parallel_kernel_count': 0, 'decay_calculation_requested': False, 'generated_events': 0}


def test_bridge_legacy_script_and_new_connected_script_are_distinct_not_relabelled():
    # Explicit original C3 mechanical receipt fixtures; no actual execution.
    c=legacy_config(); paths=[Path('/owned/provider'),Path('/owned/model'),Path('/owned/ufo'),Path('/owned/receipt')]
    legacy=bridge.script(c,*paths)
    assert 'ComputeWidths[' not in legacy and '"decay_calculation_requested"->False' in legacy
    c['physical_checks']=request(); text=bridge.script(c,*paths)
    assert '"physical_checks"->physicalChecks' in text and '"decay_calculation_requested"->True' in text
    assert text.index('num[x_]')<text.index('ComputeWidths[')<text.index('WriteUFO[')
    assert 'FeynRules`AddDecays -> False' in text
    n=legacy_native();n.update(physical_checks=native(),decay_calculation_requested=True)
    outcome=bridge.adjudicate(n,c,*paths[:3],123)
    assert outcome['passed'] and outcome['physical_checks']['passed']
    n['kinetic_result']=False;n['kinetic_result_expression']='Null'
    assert not bridge.adjudicate(n,c,*paths[:3],123)['passed']
    assert not bridge.adjudicate(n,legacy_config(),*paths[:3],123)['passed']


@pytest.mark.parametrize('target',['request','channel','after_width'])
def test_bool_number_alias_cannot_replace_exact_intent_or_selected_width(target):
    r=request();n=native(r)
    if target=='request':n['request']['feynman_gauge']=1
    elif target=='channel':n['channels'][0]['request']['parent']['antiparticle']=0
    else:
        n['selected_supplied_widths_before']=[number(1)]
        n['selected_supplied_widths_after']=[number(True)]
    assert not physical.witness(n,r)['passed']
