"""Portable centrality preload controls; native processes/authority are mocked."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import pytest
from ravel.physics import rivet_preload as preload, existing_events as adapter, routine_build
from ravel.workflow import science
from ravel.workflow.execution import file_hash
from ravel.workflow.state_io import read_json, atomic_json
from test_rivet_built_adapter import task, evidence
from test_rivet_weight_cap import initial


def source(p, text):
    p.write_text(text + '\n')
    return {'path': str(p), 'sha256': file_hash(p), 'first_line': 1, 'last_line': 1, 'text': text}


def yoda(name='/Calibration/V0M', values=('0','1','3','0')):
    return ('BEGIN YODA_ESTIMATE1D_V3 '+name+'\nPath: '+name+'\n---\nEdges(A1): [0,1,3]\nErrorLabels: [""]\n# value totalDn totalUp\n' + '\n'.join(v+' -0.1 0.1' for v in values)+'\nEND YODA_ESTIMATE1D_V3\n')


def fixture(tmp_path, original=None, mode='GEN'):
    value = task(); value['options'] = {'cent': mode}
    original = original or tmp_path/'source.cc'
    cc = source(original, 'declareCentrality(Observable(), "Calibration", "V0M", "CENT");')
    api = source(tmp_path/'API.hh', 'Source fixture: getPreload<Estimate1D>; percentile sums finite values without widths.')
    p = tmp_path/'calibration.yoda'; p.write_text(yoda('/Calibration/V0M' + {'GEN':'','IMP':'_IMP','USR':'_USR'}[mode]))
    value['centrality_preload'] = {'schema_version': 1, 'path': p.name, 'sha256': file_hash(p), 'mode': mode,
        'calibration_analysis': 'Calibration', 'histogram': 'V0M', 'routine_source': cc,
        'source_dependencies': [api], 'provenance': 'fabricated nonuniform-bin source/parser control, no generator qualification',
        'weight_policy': 'source_calibration_unverified', 'origin': {'path': p.name, 'sha256': file_hash(p)}}
    return value, original, p


def test_complete_native_values_flows_error_tokens_no_rescale(tmp_path):
    value, cc, p = fixture(tmp_path)
    record = preload.inspect(value, tmp_path, admitted_source_files=[cc])
    assert record['object_path'] == '/Calibration/V0M'
    assert record['finite_area_check'] == 7 and record['percentile_finite_value_sum_check'] == 4
    assert [b['value_token'] for b in record['native_object']['bins']] == ['0','1','3','0']
    assert len(record['native_object']['bins']) == 4
    assert record['native_object']['bins'][1]['native_errors'][0]['down_token'] == '-0.1'
    assert not record['native_consumption_observed'] and not record['calibration_weight_applicability_verified']
    assert record['native_object']['bins'][1]['variance'] is None
    assert {p, cc, tmp_path/'API.hh', Path(preload.__file__)} <= set(preload.inputs(value,tmp_path,admitted_source_files=[cc]))


@pytest.mark.parametrize('mode', ['GEN','IMP','USR'])
def test_exact_mode_specific_path_argv(tmp_path, mode):
    value, cc, p = fixture(tmp_path, mode=mode)
    argv, record = preload.arguments(value,tmp_path,admitted_source_files=[cc],exposure={'format':'HepMC3'})
    assert argv == ['--preload-file',str(p)] and record['mode'] == mode


def test_usr_refuses_hepmc2_and_no_exposure(tmp_path):
    v, cc, _ = fixture(tmp_path,mode='USR')
    for exposure in (None,{'format':'HepMC2'}):
        with pytest.raises(ValueError,match='HepMC3'):
            preload.arguments(v,tmp_path,admitted_source_files=[cc],exposure=exposure)


@pytest.mark.parametrize('change', [
    lambda c:c.update(schema_version=True), lambda c:c.update(mode='REF'),
    lambda c:c.update(path='a,b.yoda'),lambda c:c.update(weight_policy='nominal_verified'),
    lambda c:c.update(extra=1),lambda c:c.update(calibration_analysis='UnlistedSourceBooked'),
    lambda c:c.update(histogram='Wrong'),lambda c:c.update(source_dependencies=[]),
    lambda c:c.update(provenance='')])
def test_closed_contract_and_source_identity(tmp_path,change):
    value,_,_=fixture(tmp_path);change(value['centrality_preload'])
    with pytest.raises(ValueError): preload.validate(value)


def test_option_runtime_and_source_graph_bindings(tmp_path):
    value, cc, p = fixture(tmp_path)
    with pytest.raises(ValueError,match='not admitted'): preload.inspect(value,tmp_path,admitted_source_files=[])
    value['options']['cent']='RAW'
    with pytest.raises(ValueError,match='matching cent'): preload.validate(value)
    value['options']['cent']='GEN';value['runtime']['version']='4.2.0'
    with pytest.raises(ValueError,match='4.1.3/4.1.4'):preload.validate(value)


@pytest.mark.parametrize('mutation',[
    lambda t:t+yoda('/RAW/_EVTCOUNT'),lambda t:t+yoda('/UnlistedSourceBooked/count'),
    lambda t:t+yoda(),lambda t:t.replace('Path: /Calibration/V0M','Path: /Wrong'),
    lambda t:t.replace('1 -0.1','nan -0.1',1),lambda t:t.replace('1 -0.1','-1 -0.1',1),
    lambda t:t.replace('1 -0.1','0 -0.1',1).replace('3 -0.1','0 -0.1',1),
    lambda t:t.replace('ErrorLabels:', 'MaskedBins: [1]\nErrorLabels:'),
    lambda t:t.replace('ESTIMATE1D','HISTO1D'),lambda t:t.replace('0 -0.1 0.1\nEND','END')])
def test_exact_calibration_only_object_and_rows(tmp_path,mutation):
    value,cc,p=fixture(tmp_path);p.write_text(mutation(p.read_text()));value['centrality_preload']['sha256']=file_hash(p);value['centrality_preload']['origin']['sha256']=file_hash(p)
    with pytest.raises(ValueError):preload.inspect(value,tmp_path,admitted_source_files=[cc])


def test_fresh_digest_source_and_symlink_refusals(tmp_path):
    value,cc,p=fixture(tmp_path)
    p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='calibration bytes'):preload.inspect(value,tmp_path,admitted_source_files=[cc])
    value['centrality_preload']['sha256']=file_hash(p);value['centrality_preload']['origin']['sha256']=file_hash(p);cc.write_text(cc.read_text()+'// changed\n')
    with pytest.raises(ValueError,match='source bytes'):preload.inspect(value,tmp_path,admitted_source_files=[cc])
    value['centrality_preload']['routine_source']['sha256']=file_hash(cc)
    link=tmp_path/'link.yoda';link.symlink_to(p);value['centrality_preload']['path']=link.name
    with pytest.raises(ValueError,match='regular source'):preload.inspect(value,tmp_path,admitted_source_files=[cc])


def test_legacy_untouched_and_new_initial_v2_gate():
    value=initial(task());assert not science._new_capability({'mode':'analyze','task':value})
    assert preload.arguments(value,admitted_source_files=[]) == ([],None)
    value['centrality_preload']={}
    assert science._new_capability({'mode':'analyze','task':value})


@pytest.mark.parametrize('built',[True,False])
@pytest.mark.parametrize('mutate',[False,True])
def test_real_adapter_dispatch_and_post_execution_rebind(tmp_path,monkeypatch,built,mutate):
    _, plugin, _, original, _, _=evidence(tmp_path,monkeypatch)
    value,cc,p=fixture(tmp_path,original)
    if not built:
        value=initial(value);row={'id':value['routine'],'name':value['routine'],'source_files':[{'path':cc.name}]}
        monkeypatch.setattr(adapter,'_source_files',lambda _t:({'sources':{'rivet':{'revision':'synthetic-source'}}},row,[cc]))
        (tmp_path/'rivet-build').write_text('mocked');(tmp_path/'out').mkdir()
    monkeypatch.setattr(adapter,'subprocess',SimpleNamespace(run=lambda *_a,**_k:SimpleNamespace(returncode=0,stdout='rivet v4.1.3\n')))
    calls=[]
    def call(command,cwd,env,log):
        calls.append(command);Path(log).write_text('unit routing observation')
        if '--weight-nominal' in command:
            assert command[command.index('--preload-file')+1]==str(p)
            assert command[command.index('-a')+1]=='UnlistedSourceBooked:cent=GEN'
            if built:atomic_json(tmp_path/'out/loader-event-observation.json',{'kind':'unit-dispatch-observation','plugin':str(plugin),'environment':env,'runtime_version':'4.1.3','python':{'path':str(Path(value['runtime']['python']).resolve()),'sha256':file_hash(value['runtime']['python'])}})
            (tmp_path/'out/histograms.yoda').write_text('mocked native output')
            if mutate:p.write_text(p.read_text()+'\n')
        elif '-j' in command:Path(command[command.index('1')+1]).write_bytes(b'mocked plugin')
        else:atomic_json(tmp_path/'out/observables.json',{'observables':{value['observables'][0]['path']:{}},'event_counters':{'/RAW/_EVTCOUNT':{'entries':1,'sumw':1,'sumw2':1}}})
    monkeypatch.setattr(adapter,'_call',call)
    files=adapter.inputs(value,tmp_path)
    assert p in files and cc in files
    if mutate:
        with pytest.raises(ValueError,match='calibration bytes'):adapter.run(value,tmp_path,tmp_path/'out')
    else:
        result=adapter.run(value,tmp_path,tmp_path/'out');receipt=read_json(tmp_path/'out/centrality-preload.json')
        assert receipt['native_consumption_observed'] is False and receipt['object_path']=='/Calibration/V0M'
        assert result['centrality_preload']['sha256']==file_hash(tmp_path/'out/centrality-preload.json')
        assert result['census']['sumw']==[1.] and result['census']['group_weight_second_moments']==[[1.]]
        if built:assert read_json(tmp_path/'out/build-reuse.json')['centrality_preload']==result['centrality_preload']


def test_literal_projection_retains_full_origin_and_rejects_rewrite(tmp_path):
    value,cc,p=fixture(tmp_path)
    original=tmp_path/'full.yoda';original.write_text(p.read_text()+yoda('/RAW/_EVTCOUNT'))
    subset=tmp_path/'selected.yoda'
    result=preload.prepare(original,expected_sha256=file_hash(original),object_path='/Calibration/V0M',output_path=subset)
    assert subset.read_bytes()==p.read_bytes() and original.read_text().endswith(yoda('/RAW/_EVTCOUNT'))
    value['centrality_preload'].update(path=subset.name,sha256=result['sha256'],origin=result['origin'])
    preload.inspect(value,tmp_path,admitted_source_files=[cc])
    assert original in preload.inputs(value,tmp_path,admitted_source_files=[cc])
    with pytest.raises(ValueError,match='fresh ordinary'):preload.prepare(original,expected_sha256=file_hash(original),object_path='/Calibration/V0M',output_path=subset)
    subset.write_text(subset.read_text().replace('3 -0.1','4 -0.1'))
    value['centrality_preload']['sha256']=file_hash(subset)
    with pytest.raises(ValueError,match='block differs'):preload.inspect(value,tmp_path,admitted_source_files=[cc])


def test_unrelated_grounding_cannot_replace_build_source(tmp_path,monkeypatch):
    evidence(tmp_path,monkeypatch)
    value,cc,_=fixture(tmp_path,original=tmp_path/'uncompiled.cc')
    value['grounding']=[{'path':str(cc),'sha256':file_hash(cc)}]
    with pytest.raises(ValueError,match='not admitted'):
        adapter.inputs(value,tmp_path)


@pytest.mark.parametrize('built',[True,False])
def test_public_v2_planning_binds_whole_calibration_graph_no_launch(tmp_path,monkeypatch,built):
    _,_,_,original,_,_=evidence(tmp_path,monkeypatch)
    value,cc,p=fixture(tmp_path,original)
    if not built:
        value=initial(value);row={'id':value['routine'],'name':value['routine'],'source_files':[{'path':cc.name}]}
        monkeypatch.setattr(adapter,'_source_files',lambda _t:({'sources':{'rivet':{'revision':'fabricated-source'}}},row,[cc]))
        (tmp_path/'rivet-build').write_text('stub')
    monkeypatch.setattr(adapter,'subprocess',SimpleNamespace(run=lambda *_a,**_k:pytest.fail('planning native process')))
    monkeypatch.setattr(adapter,'_call',lambda *_a,**_k:pytest.fail('planning native route'))
    spec={'schema_version':2,'mode':'analyze','source':'fabricated source/parser plan control',
        'assumptions':['No native calibration or generator/beam applicability established'],
        'max_seconds':30,'max_attempts':1,'approval_mode':'scripted_yes','task':value,
        'review_policy':{'schema_version':1,'policy':{'schema_version':1,
            'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},
            'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
            'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],
            'claim_scopes':{'preload_delivery':{'checks':['integrity','scientific'],'actions':['delivery','reuse']}}},
            'correction_contract':{'task_fields':[],'input_slots':[]}}}
    src=tmp_path/'spec.json';atomic_json(src,spec)
    # New initial-route field requires v2 before any intake/worker creation.
    legacy=deepcopy(spec);legacy['schema_version']=1;legacy.pop('review_policy');legacy.pop('max_attempts');atomic_json(src,legacy)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'legacy-refused',src)
    assert not (tmp_path/'legacy-refused').exists()
    atomic_json(src,spec);rd=tmp_path/'prospective';science.plan(rd,src)
    assert science.verify_plan(rd)['schema_version']==2
    assert not (rd/science.APPROVAL).exists() and not (rd/'outputs/attempt-1').exists()
    p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError):science.verify_plan(rd)
    assert not (rd/science.APPROVAL).exists()
