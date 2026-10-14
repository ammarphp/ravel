"""Pure integrated algebra and inert ordinary API controls; no native calls."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import struct
from pathlib import Path

import pytest
from ravel.physics import background_construction as b, background_discrete_profile as d
from ravel.physics import native_likelihood as native, statistical_construction as regional
from ravel.workflow import science
from test_statistical_construction import fixture as regional_fixture, native_config


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    monkeypatch.setattr(native,'_process',lambda *a,**k: (_ for _ in ()).throw(AssertionError('native forbidden in pure controls')))


def specification(tmp_path, correlated=False):
    base=regional_fixture(tmp_path,correlated)
    # Complete original signal/control contributions stay. Existing common
    # ABCD component also stays: the supplied family is ADDITIONAL, not an
    # implicit replacement of an undeclared background.
    k=len(base['auxiliary']['names'])
    par=lambda name: {'name':name,'role':'rate','initial':'4','bounds':['0','100'],'fixed':False,'meaning':'expected full-domain component yield','source':'s'}
    return {'schema_version':1,'baseline':base,'domain':['1','3'],
        'bin_windows':[['1','2'],['2','3'],['1','3'],None],
        'transfer':{'coefficients':['1','2','1/3','0'],'powers':{},'log_response':[['0']*k for _ in range(4)],'source':'s'},
        'candidates':[{'id':'constant','family':{'kind':'bernstein','degree':0},'parameters':[par('b0')],'source':'s'},
                      {'id':'linear','family':{'kind':'bernstein','degree':1},'parameters':[par('b1'),par('b2')],'source':'s'}],
        'penalty':{'kind':'fixed_nll_per_floating_background_coefficient','factor':'1/2','source':'s','justification':'Artificial declared penalty, not calibrated.'},
        'census':{'source':'s','statement':'Both artificial candidate families, supplied before fitting.'}}


def prepare(tmp_path, spec=None):
    spec=spec or specification(tmp_path)
    original,cfg=native_config(tmp_path,spec['baseline'])
    fit=cfg['fit'];fit.pop('saved_fit');fit.update(points=3,absolute_nll=True)
    handoff=b.write_native_population(spec,tmp_path/'population',runtime=cfg['runtime'],fit=fit,candidate_seconds=[30,40],overhead_seconds=10)
    return spec,fit,handoff


def rows(fit, offset=0):
    # Equal nominal delta curves with DIFFERENT absolute native baseline.
    lo,hi=map(lambda s:float(F(s)),fit['domain']);spacing=(hi-lo)/fit['points']
    return [{fit['poi']:0.,'deltaNLL':0.,'nll':10.+offset,'nll0':90.,'quantileExpected':-1.}]+[
        {fit['poi']:lo+(i+.5)*spacing,'deltaNLL':float(i+1),'nll':10.+offset,'nll0':90.,'quantileExpected':.5}
        for i in range(fit['points'])]


def result(fit, offset=0):
    raw=rows(fit,offset)
    for row in raw:
        row[fit['poi']]=struct.unpack('f',struct.pack('f',row[fit['poi']]))[0]
        row.update(beta=5.,u=2.,v=3.,b0=4.,b1=4.,b2=4.)
        row.update({'ravel_mean_'+str(i):10. for i in range(4)})
    return {'status':'passed','physics_validated':False,'fit':fit,'inference':native.extract_rows(raw,fit)}


def test_bernstein_nonuniform_exact_fraction_partition():
    value=b.basis_integrals({'kind':'bernstein','degree':2},['2','8'],[['2','3'],['3','5'],['5','8']])
    # Independent Beta-CDF antiderivatives on t=(x-2)/6.
    primitive=[lambda t:1-(1-t)**3,lambda t:3*t*t-2*t**3,lambda t:t**3]
    edges=[F(0),F(1,6),F(1,2),F(1)]
    expected=[[f(y)-f(x) for x,y in zip(edges,edges[1:])] for f in primitive]
    assert [[F(x) for x in r] for r in value]==expected
    assert all(sum(map(F,row))==1 for row in value)


@pytest.mark.parametrize('degree',range(13))
def test_all_bernstein_degrees_conserve_each_component(degree):
    answer=b.basis_integrals({'kind':'bernstein','degree':degree},['0','1'],[['0','1/7'],['1/7','2/3'],['2/3','1'],None])
    assert len(answer)==degree+1
    assert all(sum(map(F,r))==1 and F(r[-1])==0 for r in answer)


def test_histogram_partial_bin_exact_counts_to_density_distinction():
    value=b.basis_integrals({'kind':'histogram_templates','knots':['0','1','3'],'components':[['2','4'],['0','3']]},['0','3'],[['1/2','2'],['0','3']])
    assert value==[['1/2','1'],['1/2','1']]
    # Irregular widths matter: unnormalized first-component total is 2+8=10.


def test_linear_triangle_exact_intersections():
    value=b.basis_integrals({'kind':'linear_templates','knots':['0','1','3'],'components':[['0','2','0']]},['0','3'],[['0','1/2'],['1/2','2'],['2','3']])
    assert list(map(F,value[0]))==[F(1,12),F(3,4),F(1,6)]


def test_laurent_positive_source_interval():
    value=b.basis_integrals({'kind':'fixed_integer_powers','powers':[-2,0,2]},['1','2'],[['1','3/2'],['3/2','2']])
    assert list(map(F,value[0]))==[F(2,3),F(1,3)]
    assert all(sum(map(F,row))==1 for row in value)


@pytest.mark.parametrize('family,domain,windows',[
    ({'kind':'bernstein','degree':True},['0','1'],[['0','1']]),
    ({'kind':'fixed_integer_powers','powers':[-1]},['1','2'],[['1','2']]),
    ({'kind':'fixed_integer_powers','powers':[-2]},['0','2'],[['0','2']]),
    ({'kind':'histogram_templates','knots':['0','1'],'components':[['0']]},['0','1'],[['0','1']]),
    ({'kind':'linear_templates','knots':['0','1'],'components':[['1','-1']]},['0','1'],[['0','1']]),
    ({'kind':'bernstein','degree':1},['0','1'],[['-1','1']]),
    ({'kind':'histogram_templates','knots':['0','1'],'components':[['1']]},['0','2'],[['0','1']]),
])
def test_family_domain_refusals(family,domain,windows):
    with pytest.raises(ValueError):b.basis_integrals(family,domain,windows)


def test_full_regional_lowering_preserves_aux_signal_and_exact_transfer(tmp_path):
    spec=specification(tmp_path,True);spec['transfer']['powers']={'kappa':1}
    spec['transfer']['log_response'][0]=['2','-1']
    compiled=b.construct(spec)
    for candidate in compiled:
        doc=candidate['document'];original=spec['baseline']
        assert doc['terms'][:len(original['terms'])]==original['terms']
        assert all(doc[key]==original[key] for key in ('auxiliary','bins','partition','prediction','template_statistics','assumptions'))
    doc=compiled[0]['document'];j=regional.mean_jet(doc,regional.initial_point(doc))
    old=regional.mean_jet(spec['baseline'],regional.initial_point(spec['baseline']))
    assert j['means']==pytest.approx([old['means'][0]+2,old['means'][1]+4,old['means'][2]+4/3,old['means'][3]])
    assert compiled[0]['penalty_nll']=='1/2' and compiled[1]['penalty_nll']=='1'
    # Physical shape=eta0, transfer=.6eta0+.8eta1; new first-bin
    # derivative from exp(2shape-transfer) is 2*(1.4,-.8).
    assert j['jacobian'][0][-2:]==pytest.approx([old['jacobian'][0][-2]+2.8,old['jacobian'][0][-1]-1.6])


def test_parameter_used_only_in_shared_transfer_is_real_not_dummy(tmp_path):
    s=specification(tmp_path)
    p=deepcopy(s['baseline']['parameters'][-1]);p['name']='acceptance';p['fixed']=False
    s['baseline']['parameters'].append(p);s['transfer']['powers']={'acceptance':1}
    assert all('acceptance' in c['document']['terms'][-1]['powers'] for c in b.construct(s))


@pytest.mark.parametrize('mutation',[
    lambda s:s['candidates'][1].update(id='constant'),
    lambda s:s['candidates'][0]['parameters'][0].update(name='model_s'),
    lambda s:s['candidates'][0]['parameters'][0].update(bounds=['-1','10']),
    lambda s:s['transfer'].update(coefficients=['-1','1','1','0']),
    lambda s:s['transfer'].update(powers={'c':1}),
    lambda s:s['penalty'].update(factor='-1'),
    lambda s:s['candidates'][0]['parameters'].append(deepcopy(s['candidates'][0]['parameters'][0])),
])
def test_population_semantics_refuse(tmp_path,mutation):
    s=specification(tmp_path);mutation(s)
    with pytest.raises(ValueError):b.construct(s)


def test_complete_native_bundles_task_inputs_budget_and_commands(tmp_path):
    spec,fit,h=prepare(tmp_path)
    public={'schema_version':2,'mode':h['mode'],'task':h['task'],'max_seconds':80}
    assert science.adapter(public) is d and science._new_capability(public)
    paths=science.task_inputs(public,tmp_path)
    cfg,_,entries,_=d._configuration(h['task'],tmp_path)
    assert len(entries)==2 and len(paths)==len(set(paths))
    assert d.resource_bounds(h['task'],tmp_path)['candidate_seconds']==[30,40]
    for e in entries:
        _,argv=native.commands(e['config'],{'combine':'combine','text2workspace':'text2workspace'},tmp_path,has_response=True)
        assert argv.count('--saveNLL')==1 and argv[-2:]==['--X-rtd','REMOVE_CONSTANT_ZERO_POINT=1']
        assert '--algo' in argv and argv[argv.index('--algo')+1]=='grid'
    with pytest.raises(ValueError): science.task_inputs({**public,'max_seconds':79},tmp_path)


def test_absolute_opt_in_preserves_legacy_and_refuses_saved_asimov_version(tmp_path):
    _,fit,h=prepare(tmp_path);cfg=d._configuration(h['task'],tmp_path)[2][0]['config']
    legacy=deepcopy(cfg);legacy['fit'].pop('absolute_nll')
    _,argv=native.commands(legacy,{'combine':'x','text2workspace':'y'},tmp_path)
    assert '--X-rtd' not in argv and 'absolute_nll_rows' not in native.extract_rows(rows(fit),legacy['fit'])
    for path,value in [(('schema_version',),2),(('fit','absolute_nll'),False),(('fit','data'),'asimov_background'),(('runtime','expected','combine_version'),'10.0.0')]:
        bad=deepcopy(cfg);target=bad
        for key in path[:-1]: target=target[key]
        target[path[-1]]=value
        with pytest.raises(ValueError):native._validate_absolute_scan(bad)


def test_envelope_uses_raw_absolute_baseline_and_keeps_ties(tmp_path):
    spec,fit,_=prepare(tmp_path)
    results=[{'id':'constant','result':result(fit,10)},{'id':'linear','result':result(fit,0)}]
    e=d.envelope(spec,results,fit)
    assert all(p['selected_candidates']==['linear'] for p in e['points'])
    assert F(e['retained_minimum_nll_rational'])==101
    # Difference in raw baseline exactly cancels declared half-unit penalty.
    results[0]['result']=result(fit,F(1,2))
    e=d.envelope(spec,results,fit)
    assert all(p['selected_candidates']==['constant','linear'] for p in e['points'])
    assert e['coverage_qualified'] is False and e['global_minimum_qualified'] is False


def test_complete_raw_and_grid_population_required(tmp_path):
    spec,fit,_=prepare(tmp_path);good=[{'id':'constant','result':result(fit)},{'id':'linear','result':result(fit)}]
    for mutation in [lambda r:r.pop(),lambda r:r[0]['result'].update(status='failed'),
                     lambda r:r[0]['result']['inference']['rows'][1].pop('nll0'),
                     lambda r:r[0]['result']['inference']['absolute_nll_rows'][0].update(returned_sum_rational='0')]:
        r=deepcopy(good);mutation(r)
        with pytest.raises(ValueError):d.envelope(spec,r,fit)
    other=deepcopy(good);raw=other[1]['result']['inference']['rows'];raw[1]['c']+=1e-8
    other[1]['result']['inference']=native.extract_rows(raw,fit)
    with pytest.raises(ValueError):d.envelope(spec,other,fit)


def test_returned_values_retained_before_failure_no_next_call(tmp_path,monkeypatch):
    _,fit,h=prepare(tmp_path);seen=[]
    def fake(*args):seen.append(args);return {'status':'failed','physics_validated':False,'literal_failure':{'raw':17}}
    monkeypatch.setattr(native,'run',fake)
    out=tmp_path/'run';r=d.run(h['task'],tmp_path,out)
    assert len(seen)==1 and r['status']=='failed' and r['envelope'] is None
    assert r['returns'][0]['result']['literal_failure']=={'raw':17}
    assert r['population'][1]['status']=='not_executed'
    assert json.loads((out/'background-discrete-profile.json').read_text())==r


def test_serial_success_report_and_ending_source_failure(tmp_path,monkeypatch):
    _,fit,h=prepare(tmp_path);calls=[]
    def fake(*args):calls.append(args);return result(fit)
    monkeypatch.setattr(native,'run',fake)
    out=tmp_path/'run';r=d.run(h['task'],tmp_path,out)
    assert len(calls)==2 and r['status']=='passed' and r['ending_inputs']==r['original_inputs']
    from ravel.plotting.science_figures import render
    report=render({'mode':'background-discrete-profile','task':h['task']},r,tmp_path,out)
    assert report['figures']==[] and len(report['tables'])==1
    assert len(json.loads((out/'background-model-comparison.json').read_text())['returns'])==2


def test_wrong_native_document_refuses_before_execution(tmp_path):
    _,_,h=prepare(tmp_path);cfg,_,entries,_=d._configuration(h['task'],tmp_path)
    p=Path(entries[0]['config']['model']['construction']['path']);doc=json.loads(p.read_text());doc['bins'][0]['observed']+=1
    p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):d._configuration(h['task'],tmp_path)


def test_full_nuisance_branches_required(tmp_path):
    spec,fit,_=prepare(tmp_path)
    good=[{'id':'constant','result':result(fit)},{'id':'linear','result':result(fit)}]
    raw=good[0]['result']['inference']['rows'];raw[1].pop('b0')
    good[0]['result']['inference']=native.extract_rows(raw,fit)
    with pytest.raises(ValueError,match='nuisance branches'):d.envelope(spec,good,fit)


def test_returned_float_precision_not_recovered_by_reduction():
    raw=[{'deltaNLL':1.,'nll':1e16,'nll0':-1e16}]
    absolute=native._absolute_profile_rows(raw)
    assert absolute[0]['returned_sum_rational']=='1'
    assert (raw[0]['deltaNLL']+raw[0]['nll'])+raw[0]['nll0']==0. # Explicit sequential floating sum loses it.
    assert absolute[0]['native_accuracy_qualified'] is False


def test_whole_budget_refuses_before_native_call(tmp_path,monkeypatch):
    _,_,h=prepare(tmp_path);clock=iter([0.,11.,12.]);calls=[]
    monkeypatch.setattr(d.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(native,'run',lambda *args:calls.append(args))
    r=d.run(h['task'],tmp_path,tmp_path/'run')
    assert not calls and r['status']=='failed' and len(r['population'])==2
    assert all(p['status']=='not_executed' for p in r['population'])


def test_ending_input_change_retains_both_complete_returns(tmp_path,monkeypatch):
    spec,fit,h=prepare(tmp_path);calls=[];source=Path(spec['baseline']['sources'][0]['path'])
    def fake(*args):
        calls.append(args)
        if len(calls)==2:source.write_text('changed')
        return result(fit)
    monkeypatch.setattr(native,'run',fake)
    r=d.run(h['task'],tmp_path,tmp_path/'run')
    assert len(r['returns'])==2 and r['status']=='failed' and r['ending_inputs']!=r['original_inputs']
    assert 'input bytes changed' in r['error']['message']


def test_journal_save_failure_forbids_next_candidate(tmp_path,monkeypatch):
    _,fit,h=prepare(tmp_path);calls=[];original=d.atomic_json
    def save(path,obj):
        if obj.get('returns'):raise OSError('synthetic storage exhaustion')
        original(path,obj)
    monkeypatch.setattr(d,'atomic_json',save)
    monkeypatch.setattr(native,'run',lambda *args:(calls.append(args) or result(fit)))
    with pytest.raises(OSError):d.run(h['task'],tmp_path,tmp_path/'run')
    assert len(calls)==1


def test_no_observed_component_support_refuses_before_native(tmp_path):
    spec=specification(tmp_path);spec['bin_windows']=[None]*4
    with pytest.raises(ValueError,match='no support'):b.construct(spec)


@pytest.mark.parametrize('scale',['1/10000000000000000000000000000000000000000','10000000000000000000000000000000000000000'])
def test_rational_power_integral_coordinate_scale_invariance(scale):
    t=F(scale)
    original=b.basis_integrals({'kind':'fixed_integer_powers','powers':[-12,-2,0,12]},['1','2'],[['1','3/2'],['3/2','2']])
    scaled=b.basis_integrals({'kind':'fixed_integer_powers','powers':[-12,-2,0,12]},[str(t),str(2*t)],[[str(t),str(3*t/2)],[str(3*t/2),str(2*t)]])
    assert original==scaled


def test_common_grid_budget_or_runtime_change_refuses(tmp_path):
    _,_,h=prepare(tmp_path);cfg=json.loads(Path(h['task']['input']).read_text());p=Path(cfg['candidates'][1]['input']['path'])
    child=json.loads(p.read_text());child['fit']['seed']+=1;p.write_text(json.dumps(child))
    cfg['candidates'][1]['input']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest();Path(h['task']['input']).write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='differs across candidates'):d._configuration(h['task'],tmp_path)
