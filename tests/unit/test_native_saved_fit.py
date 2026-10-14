"""Synthetic saved-fit admission/extraction only; no ROOT/Combine execution."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.physics import native_likelihood as native

def fit():
    return {"method":"MultiDimFit","data":"observed","poi":"fm0","domain":["-15","15"],
      "mass":120,"seed":123456,"points":None,"minimizer":None,"fixed_witness_points":["-15","-7.5","0","7.5","15"],
      "reference_quantiles":None,"saved_fit":{"algorithm":"none","required_object":"multidimfit.ravel.root:fit_mdf","maximum_edm":.001}}

def diagnostic():
    return {"name":"multidimfit.ravel.root:fit_mdf","status":0,"covariance_quality":3,"edm":.0001,"minimum_nll":-8.,
      "invalid_nll_evaluations":0,"status_history":[{"label":"MIGRAD","status":0},{"label":"HESSE","status":0}],
      "floating_parameters":[{"name":"fm0","value":-.02,"error":1.},{"name":"nuisance","value":.1,"error":1.}],
      "constant_parameters":[{"name":"global","value":0.}]}

def extract(fits,rows=None):
    rows = [{"fm0":-.02,"deltaNLL":0.,"quantileExpected":-1.}] if rows is None else rows
    return native.extract_native_result('RAVEL_NATIVE_RESULT='+json.dumps({"rows":rows,"fit_results":fits}),fit())

def test_closed_none_command_and_no_profile_or_limit_claim():
    cfg={"schema_version":2,"fit":fit(),"model":{"card":"source/card.txt"}}
    _,command=native.commands(cfg,{"combine":Path('combine'),"text2workspace":Path('text2workspace')},Path('/synthetic'),has_response=True)
    assert command[command.index('--algo')+1]=='none'
    assert '--points' not in command and '--skipInitialFit' not in command and '--freezeParameters' not in command
    assert '--saveFitResult' in command and '--saveNLL' in command and '--saveWorkspace' in command
    result=extract([diagnostic()]);assert result['passed'] and result['kind']=='native_saved_best_fit_diagnostics'
    assert result['fit_diagnostics']['saved_result_available']

@pytest.mark.parametrize('mutation',[
 lambda f:f.update(method='AsymptoticLimits'),lambda f:f.update(data='asimov_background'),lambda f:f.update(points=31),
 lambda f:f.update(reference_quantiles={}),lambda f:f['saved_fit'].update(algorithm='grid'),
 lambda f:f['saved_fit'].update(required_object='another_result'),lambda f:f['saved_fit'].update(maximum_edm=.002),
 lambda f:f['saved_fit'].update(maximum_edm=0),lambda f:f['saved_fit'].update(extra=True),])
def test_closed_saved_fit_contract_refuses_other_algorithms_or_looser_gates(mutation):
    value=fit();mutation(value)
    with pytest.raises(ValueError):native._validate_saved_fit(value)

@pytest.mark.parametrize('mutation',[
 lambda d:d.update(status=1),lambda d:d.update(covariance_quality=2),lambda d:d.update(edm=.00101),
 lambda d:d.update(edm=-1.),lambda d:d.update(invalid_nll_evaluations=1),lambda d:d.update(status_history=[]),
 lambda d:d['status_history'][0].update(status=1),lambda d:d.update(name='fit_mdf'),
 lambda d:d['floating_parameters'][0].update(value=.5),])
def test_literal_saved_failure_stays_failed_and_evidence_retained(mutation):
    value=diagnostic();mutation(value);result=extract([value])
    assert not result['passed'] and result['fit_diagnostics']['saved_fit_results']==[value]

def test_absence_and_multiple_saved_results_never_pass():
    assert not extract([])['passed']
    assert not extract([diagnostic(),diagnostic()])['passed']

@pytest.mark.parametrize('mutation',[
 lambda d:d.update(status=True),lambda d:d.update(edm=float('nan')),
 lambda d:d.update(name=[]),lambda d:d.update(name=True),
 lambda d:d.update(floating_parameters=[]),lambda d:d['floating_parameters'].append(deepcopy(d['floating_parameters'][0])),
 lambda d:d['floating_parameters'][1].update(error=-1),lambda d:d['constant_parameters'][0].update(value=float('inf')),
 lambda d:d['status_history'][0].update(status=True),lambda d:d['floating_parameters'][0].update(extra=0),])
def test_malformed_saved_evidence_refuses(mutation):
    value=diagnostic();mutation(value)
    with pytest.raises(ValueError):extract([value])

@pytest.mark.parametrize('rows',[
 [],[{"fm0":0.,"deltaNLL":0.,"quantileExpected":0.}],
 [{"fm0":16.,"deltaNLL":0.,"quantileExpected":-1.}],
 [{"fm0":0.,"deltaNLL":0.,"quantileExpected":-1.}]*2,])
def test_exact_one_best_fit_identity_and_domain(rows):
    with pytest.raises(ValueError):extract([diagnostic()],rows)

def test_actual_parameter_population_requires_every_bound_nuisance_once():
    result=extract([diagnostic()]);native._check_saved_population(result,{"workspace":{"pois":["fm0"],"nuisances":["nuisance","missing"]}})
    assert not result['passed'] and result['fit_diagnostics']['missing_actual_model_parameters']==['missing']
    result=extract([diagnostic()]);native._check_saved_population(result,{"workspace":{"pois":["fm0"],"nuisances":["nuisance"]}})
    assert result['passed'] and result['fit_diagnostics']['actual_model_parameter_coverage']

def test_v1_grid_command_preserved():
    value=fit();value.pop('saved_fit');value['points']=31
    cfg={"schema_version":1,"fit":value,"model":{"card":"source/card.txt"}}
    _,command=native.commands(cfg,{"combine":Path('combine'),"text2workspace":Path('text2workspace')},Path('/synthetic'),has_response=True)
    assert command[-9:]==['--algo','grid','--points','31','-P','fm0','--saveNLL','--saveFitResult','--saveWorkspace']
