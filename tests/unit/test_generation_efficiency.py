"""Pure source/API controls only; synthetic data do not qualify a generator.

Root executes this file against a complete source overlay. Author has not run
imports/collection/tests or native engines. No actual ROOT/MG/MCFM/model calls.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest
from ravel.workflow import generation_efficiency as g, cost_preflight, science
from ravel.physics import model_event_phases as phases
from test_model_events import config, policy


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, allow_nan=False)+'\n').encode() if not isinstance(value, bytes) else value
    path.write_bytes(raw)
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def spec(tmp_path, name='spec'):
    c = config(tmp_path/'inputs')
    cfg = write(tmp_path/'config.json', c)
    value = {'schema_version':2,'mode':'model-events','source':c['source'],
        'assumptions':c['assumptions'],'max_seconds':90,'approval_mode':'physicist',
        'max_attempts':1,'task':{'config':cfg['path']},'review_policy':policy()}
    return value, write(tmp_path/(name+'.json'),value)


@pytest.mark.parametrize('mode,points',[('smoke',1),('full',1),('scan',60)])
def test_fresh_generation_unknown_never_uses_tree_level_anchor(mode,points):
    row=cost_preflight.estimate(mode,points,50000,'native',1)
    assert row['calibration_status']=='uncalibrated'
    assert row['walltime_h'] is None and row['disk_gb_peak'] is None
    assert row['points']==points and row['production_feasibility_established'] is False
    assert cost_preflight.historical_reference_estimate(mode,points,50000,'native',1)['walltime_h'] is not None


def test_no_generation_does_not_invent_wall_or_model_usage():
    value = cost_preflight.estimate('none',1,None,'native',1)
    assert value['walltime_h'] is None and value['status'] == 'unknown'
    assert value['resource_vector']['events'] == 0
    assert value['resource_vector']['model_calls'] is None


def test_real_bounded_pilot_producer_prepares_actual_ci1_without_approval(tmp_path):
    value,pin=spec(tmp_path)
    result=g.prepare_pilot(pin,pin,tmp_path/'run',base_dir=tmp_path)
    assert result['approved'] is False and result['executed'] is False
    checkin=json.loads((tmp_path/'run/inputs/checkin1.json').read_text())
    assert checkin['sections']['iii']['generation_efficiency']['status']=='uncalibrated'
    assert checkin['sections']['iv']['new_generated_events']==3
    assert science.verify_plan(tmp_path/'run',approved=False)['mode']=='model-events'
    assert not (tmp_path/'run/inputs/science-approval.json').exists()


def test_actual_cli_pilot_entry_uses_same_ordinary_plan(tmp_path,capsys):
    from ravel.cli import main
    value,pin=spec(tmp_path)
    request=write(tmp_path/'request.json',{'production':pin,'pilot':pin,'rundir':str(tmp_path/'run')})
    assert main(['generation-efficiency','prepare-pilot','--request',request['path'],
        '--base',str(tmp_path),'--output',str(tmp_path/'prepared.json')])==0
    returned=json.loads(capsys.readouterr().out)
    assert returned['sha256']==hashlib.sha256((tmp_path/'prepared.json').read_bytes()).hexdigest()
    assert science.verify_plan(tmp_path/'run',approved=False)['mode']=='model-events'


@pytest.mark.parametrize('changed',['process','parameter','run','machine'])
def test_process_model_settings_or_machine_changes_do_not_match(tmp_path,monkeypatch,changed):
    value,pin=spec(tmp_path)
    first=g.process_profile(value['task'],tmp_path)
    c=json.loads((tmp_path/'config.json').read_text())
    if changed=='machine':
        observed=g.machine_observation();observed['hostname']='foreign-machine'
        monkeypatch.setattr(g,'machine_observation',lambda:deepcopy(observed))
    else:
        card=Path(c['cards'][changed]['path'])
        raw=card.read_bytes()+b'\n# distinct complete scientific source\n'
        if changed=='run': raw=card.read_bytes().replace(b'6500 = ebeam1',b'7000 = ebeam1')
        card.write_bytes(raw);c['cards'][changed]['sha256']=hashlib.sha256(raw).hexdigest()
        write(tmp_path/'config.json',c)
    second=g.process_profile(value['task'],tmp_path)
    assert first['profile_sha256']!=second['profile_sha256'] or first['machine']!=second['machine']


def test_declared_seed_event_deltas_only_keep_process_identity(tmp_path):
    value,pin=spec(tmp_path);first=g.process_profile(value['task'],tmp_path)
    c=json.loads((tmp_path/'config.json').read_text());c['generation']['events']=2;c['generation']['seed']=20
    card=Path(c['cards']['run']['path']);raw=card.read_bytes().replace(b'3 = nevents',b'2 = nevents').replace(b'19 = iseed',b'20 = iseed')
    card.write_bytes(raw);c['cards']['run']['sha256']=hashlib.sha256(raw).hexdigest();write(tmp_path/'config.json',c)
    second=g.process_profile(value['task'],tmp_path)
    assert first['profile_sha256']==second['profile_sha256'] and first['events']!=second['events']


def test_ending_input_and_alias_are_refused(tmp_path):
    pin=write(tmp_path/'evidence.json',{'x':1});capture=g._Inputs(tmp_path);capture.document(pin)
    write(tmp_path/'evidence.json',{'x':2})
    with pytest.raises(ValueError,match='commitment|changed'):capture.finish()
    alias=tmp_path/'alias.json';alias.symlink_to(tmp_path/'evidence.json')
    with pytest.raises(ValueError,match='aliases'):g._Inputs(tmp_path).read(alias)


@pytest.mark.parametrize('raw',[b'{"x":NaN}',b'{"x":1e9999}',b'{"x":1,"x":2}'])
def test_portable_closed_json_refuses_nonfinite_and_duplicates(tmp_path,raw):
    pin=write(tmp_path/'bad.json',raw)
    with pytest.raises(ValueError):g._Inputs(tmp_path).document(pin)


def test_phase_wrapper_keeps_actual_args_return_and_exception():
    events=[]
    def emit(row):events.append(row)
    emit.next_id=0
    def original(a,*,b):return (a,b)
    row={'phase':'refine'}
    assert phases.wrap(original,row,emit,[])(1,b=2)==(1,2)
    assert [x['state'] for x in events]==['running','completed']
    exc=ValueError('retained source error')
    def failed():raise exc
    with pytest.raises(ValueError) as observed:phases.wrap(failed,row,emit,[])()
    assert observed.value is exc and events[-1]['state']=='failed'


def test_nested_intervals_remain_explicit_and_cannot_double_count():
    events=[];stack=[]
    def emit(row):events.append(row)
    emit.next_id=0
    inner=phases.wrap(lambda:7,{'phase':'reweight'},emit,stack)
    outer=phases.wrap(inner,{'phase':'refine'},emit,stack)
    assert outer()==7
    assert [(x['phase'],x['nested']) for x in events if x['state']=='completed']==[('reweight',True),('refine',False)]


@pytest.mark.parametrize('defect',['missing','failed','nested','nonfinite'])
def test_incomplete_phase_population_never_calibrates(defect):
    rows=[{'phase':x,'state':'completed','wall_seconds':1.,'nested':False} for x in ('build','survey','refine','combine_events','store_events')]
    profile={'protected':{'reweight':{'mode':'OFF'},'shower':{'backend':'OFF'},'cards':{'madspin':None}}}
    if defect=='missing':rows.pop()
    if defect=='failed':rows[-1]['state']='failed'
    if defect=='nested':rows[-1]['nested']=True
    if defect=='nonfinite':rows[-1]['wall_seconds']=float('inf')
    with pytest.raises(ValueError):g.phase_totals(rows,profile)


def test_source_native_api_mapping_binds_complete_method_bodies(tmp_path):
    for module,owner,method,phase in phases.APIS:
        path=tmp_path/(module.replace('.','/')+'.py');path.parent.mkdir(parents=True,exist_ok=True)
        # Multiple methods sharing a class/file are accumulated as one full source.
        rows=[r for r in phases.APIS if r[:2]==(module,owner)]
        raw='class '+owner+':\n'+''.join('    def '+r[2]+'(self,line):\n        return line\n' for r in rows)
        path.write_text(raw)
    first=phases.source_contract(tmp_path)
    assert len(first)==7
    path=tmp_path/'madgraph/interface/common_run_interface.py'
    path.write_text(path.read_text().replace('return line','return 2'))
    assert phases.source_contract(tmp_path)!=first


def test_native_phase_missing_endpoint_is_retained_not_completed(tmp_path):
    api={'phase':'survey'};journal=tmp_path/'journal.jsonl'
    journal.write_text(json.dumps({'id':0,'phase':'survey','api':api,'nested':False,'state':'running'})+'\n')
    assert phases.final_rows(journal,[api])[0]['state']=='running'


def test_complete_explicit_absolute_precision_target_is_required_before_review(tmp_path):
    # Cancellation means may be zero; only an explicit absolute error is checked.
    value,production_pin=spec(tmp_path);profile=g.process_profile(value['task'],tmp_path);pilots=[{'rundir':'/pilotA'},{'rundir':'/pilotB'}]
    source=write(tmp_path/'source.txt',b'Explicit inert estimator/covariance/normalization source, no numerical certification.\n')
    binding={'production':production_pin,'configuration':profile['configuration'],
        'exposure':{'events':profile['events'],'seed':profile['seed']},
        'normalization_target':'Exact full-domain cross section for this declared production exposure'}
    target={'schema_version':2,'kind':'generation_precision_target','profile_sha256':profile['profile_sha256'],**binding,
        'unit':'pb','coordinates':['zero-interference-bin'],'absolute_targets':['0.01']}
    evidence={'schema_version':2,'kind':'generation_precision_evidence','profile_sha256':profile['profile_sha256'],**binding,
        'pilot_roots':['/pilotA','/pilotB'],'estimator':'signed fixed-N block means',
        'sampling_design':'independent frozen-proposal blocks; not grouped Poisson',
        'estimator_source':source,'covariance_source':source,'normalization_source':source,
        'target_source':write(tmp_path/'target.json',target),'unit':'pb',
        'coordinates':target['coordinates'],'absolute_errors':['0.02'],'absolute_targets':['0.01']}
    declaration={'evidence':write(tmp_path/'evidence.json',evidence),'review_rundir':'/missing',
        'check_id':'mc-absolute-precision','claim_scope':'precision'}
    with pytest.raises(ValueError,match='target unmet'):g.precision_evidence(declaration,profile,pilots,g._Inputs(tmp_path),production_pin=production_pin)
    evidence['absolute_errors']=['0.005'];declaration['evidence']=write(tmp_path/'evidence.json',evidence)
    with pytest.raises(ValueError,match='scientifically accepted'):g.precision_evidence(declaration,profile,pilots,g._Inputs(tmp_path),production_pin=production_pin)


def test_generic_pass_record_does_not_replace_estimator_evidence(tmp_path):
    value,production_pin=spec(tmp_path);profile=g.process_profile(value['task'],tmp_path)
    declaration={'evidence':write(tmp_path/'evidence.json',{'status':'pass'}),'review_rundir':'/missing',
        'check_id':'precision','claim_scope':'precision'}
    with pytest.raises(ValueError,match='closed'):g.precision_evidence(declaration,profile,[],g._Inputs(tmp_path),production_pin=production_pin)


def test_real_policy_schema_cannot_admit_unknown_fields_or_v1_study(tmp_path):
    value,pin=spec(tmp_path)
    value['generation_efficiency']={'schema_version':1,'purpose':'production','request':pin,'forecast':None}
    with pytest.raises(ValueError):science.validate(value)
    value['generation_efficiency']['purpose']='pilot';science.validate(value)
    value['generation_efficiency']['approved']=True
    with pytest.raises(ValueError):science.validate(value)


@pytest.mark.parametrize('defect',[None,'budget','foreign_process','foreign_machine','equal_sizes','failed'])
def test_empirical_cost_forecast_keeps_all_phases_residual_and_replan(tmp_path,monkeypatch,defect):
    value,pin=spec(tmp_path);profile=g.process_profile(value['task'],tmp_path)
    def pilot(root,target,capture):
        if defect=='failed':raise ValueError('pilot incomplete/stale; use observe_pilot for RCA')
        observed=deepcopy(profile);observed['events']=1 if root=='/A' else 2
        if defect=='equal_sizes':observed['events']=1
        if defect=='foreign_process':observed['profile_sha256']='f'*64
        if defect=='foreign_machine':observed['machine']={'foreign':True}
        seconds={name:1. for name in (*g.PHASES,'ordinary_stage_residual')}
        if defect=='budget':seconds['refine']=1000.
        return {'rundir':root,'profile':observed,'timing':pin,'phase_seconds':seconds,
            'whole_stage_seconds':sum(seconds.values()),'clock_scope':'inert observation'}
    monkeypatch.setattr(g,'_pilot',pilot)
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{'stages':[]})
    monkeypatch.setattr(g.execution,'validate_completed_execution',lambda *a,**k:[])
    if defect in ('foreign_process','foreign_machine','equal_sizes','failed'):
        with pytest.raises(ValueError):g.forecast(pin,['/A','/B'],base_dir=tmp_path,scaling_assumption='Explicit inert event-linear assumption; not a physics law.',wall_margin=2)
    else:
        result=g.forecast(pin,['/A','/B'],base_dir=tmp_path,scaling_assumption='Explicit inert event-linear assumption; not a physics law.',wall_margin=2)
        assert result['decision']==('budget_replan_required' if defect=='budget' else 'production_cost_forecast_available')
        assert 'ordinary_stage_residual' in result['phase_seconds']
        assert result['physics_validated'] is False and result['execution_authorized'] is False
        assert result['precision_status']=='requires_current_source_bound_precision_review'


def test_observe_failed_attempt_preserves_actual_rows_without_rate(tmp_path,monkeypatch):
    value,pin=spec(tmp_path);rd=tmp_path/'run';(rd/'outputs').mkdir(parents=True);(rd/'inputs').mkdir()
    write(rd/science.SPEC,value);write(rd/science.PLAN,{'inert':'plan'});write(rd/science.APPROVAL,{'inert':'approval'})
    write(rd/g.execution.STATE_NAME,{'stages':{'science':{'status':'failed','error':'loop instability'}}})
    row={'phase':'refine','state':'failed','wall_seconds':12.5}
    (rd/'outputs/model-events-phase-observations.jsonl').write_text(json.dumps(row)+'\n')
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{'base_dir':str(tmp_path),'stages':[{'stage':'science','outputs':['outputs']}]})
    monkeypatch.setattr(g.execution,'validate_completed_execution',lambda *a,**k:['actual inert failure'])
    result=g.observe_pilot(rd,base_dir=tmp_path)
    assert result['forecast_eligible'] is False and result['physics_validated'] is False
    assert result['journals']['model-events-phase-observations.jsonl']['rows']==[row]
    assert result['journals']['command-observations.jsonl'] is None
    assert result['completion_errors']==['actual inert failure']


def test_committed_output_is_exclusive_and_foreign_content_survives(tmp_path):
    p=tmp_path/'observation.json';p.write_bytes(b'foreign')
    with pytest.raises(FileExistsError):g._publish({'x':1},p)
    assert p.read_bytes()==b'foreign'


@pytest.mark.parametrize('defect',[None,'wrong_scope','integrity_only','unlocated','short_target','stale','production','configuration','exposure','normalization'])
def test_explicit_precision_arrays_and_actual_review_scope_are_both_required(tmp_path,monkeypatch,defect):
    from ravel.workflow import physics_review as pr
    value,production_pin=spec(tmp_path);profile=g.process_profile(value['task'],tmp_path);pilots=[{'rundir':'/A'},{'rundir':'/B'}]
    source=write(tmp_path/'estimator.txt',b'Inert signed estimator/source/covariance, not a physical result.\n')
    binding={'production':production_pin,'configuration':profile['configuration'],
        'exposure':{'events':profile['events'],'seed':profile['seed']},
        'normalization_target':'Exact full-domain cross section for this declared production exposure'}
    target={'schema_version':2,'kind':'generation_precision_target','profile_sha256':profile['profile_sha256'],**binding,
        'unit':'pb','coordinates':['bin-zero','bin-tail'],'absolute_targets':['.01','.02']}
    target_pin=write(tmp_path/'target.json',target)
    evidence={'schema_version':2,'kind':'generation_precision_evidence','profile_sha256':profile['profile_sha256'],**binding,
        'pilot_roots':['/A','/B'],'estimator':'centered joint signed block means',
        'sampling_design':'inert independent fixed-N frozen blocks',
        'estimator_source':source,'covariance_source':source,'normalization_source':source,
        'target_source':target_pin,'unit':'pb','coordinates':target['coordinates'],
        'absolute_errors':['.005','.01'],'absolute_targets':target['absolute_targets']}
    if defect=='production':evidence['production']={**production_pin,'sha256':'b'*64}
    if defect=='configuration':evidence['configuration']={**profile['configuration'],'sha256':'b'*64}
    if defect=='exposure':evidence['exposure']={**binding['exposure'],'events':60000}
    if defect=='normalization':evidence['normalization_target']='Another exposure normalization'
    if defect=='short_target':evidence['coordinates']=['bin-zero'];evidence['absolute_errors']=['.005'];evidence['absolute_targets']=['.01']
    evidence_pin=write(tmp_path/'evidence.json',evidence);rd=tmp_path/'review'
    declaration={'evidence':evidence_pin,'review_rundir':str(rd),'check_id':'precision','claim_scope':'precision'}
    reg={'policy':{'required_checks':[{'id':'precision','kind':'scientific'}],
        'claim_scopes':{'precision':{'checks':['precision']}}}}
    if defect=='integrity_only':reg['policy']['required_checks'][0]['kind']='integrity'
    status={'state':'accepted','live_errors':[],'claim_scope':'precision'}
    if defect=='wrong_scope':status['claim_scope']='delivery'
    if defect=='stale':status['live_errors']=['current outputs changed']
    view={'cycle':{'sequence':1,'checks':[{'id':'precision','status':'pass','evidence':[{'path':str(tmp_path/('other' if defect=='unlocated' else 'evidence.json')),'location':'all bins/estimator law'}]}]}}
    for name in (pr.HEAD,pr.POLICY,pr.REGISTRATION,pr.DIRECTORY+'/events/00000001.json'):write(rd/name,{'inert':True})
    # Mock only scientific role/registry machinery. The actual finite source,
    # target/error arrays, scope/population and ending reads execute unchanged.
    monkeypatch.setattr(pr,'status',lambda root:status)
    monkeypatch.setattr(pr,'_read',lambda root:(reg,[]))
    monkeypatch.setattr(pr,'_view',lambda reg,events:view)
    if defect:
        with pytest.raises(ValueError):g.precision_evidence(declaration,profile,pilots,g._Inputs(tmp_path),production_pin=production_pin)
    else:
        capture=g._Inputs(tmp_path);result=g.precision_evidence(declaration,profile,pilots,capture,production_pin=production_pin)
        assert result['status']=='explicit_targets_met_in_current_scoped_review'
        assert result['physics_validated_by_this_helper'] is False
        assert len(capture.finish())>=7


def test_authenticated_full_parent_requires_pilot_without_narrowing_objective(tmp_path):
    parent=write(tmp_path/'parent.json',{'compute_plan':'scan','prompt':'all sixty broad and interfering hypotheses'})
    value={'mode':'model-events','goal_binding':{'contract':parent,'assignment_id':'all'}}
    with pytest.raises(ValueError,match='same-process measured pilot'):g.inputs(value,tmp_path)
    parent_file=Path(parent['path'])
    assert json.loads(parent_file.read_text())['prompt']=='all sixty broad and interfering hypotheses'


def test_fixed_bounded_exploration_does_not_need_invented_forecast(tmp_path):
    assert g.inputs({'mode':'model-events'},tmp_path)==[]


def test_nested_sibling_relative_configs_prepare_real_pilot_not_outer_decoy(tmp_path):
    value,_=spec(tmp_path/'source')
    source_config=json.loads((tmp_path/'source/config.json').read_text())
    write(tmp_path/'config.json', {'outer_decoy':True})
    production=deepcopy(value);production['task']['config']='config.json'
    pilot=deepcopy(production)
    write(tmp_path/'production/config.json',source_config)
    write(tmp_path/'pilot/config.json',source_config)
    p=write(tmp_path/'production/spec.json',production)
    q=write(tmp_path/'pilot/spec.json',pilot)
    prepared=g.prepare_pilot(p,q,tmp_path/'run',base_dir=tmp_path)
    assert prepared['approved'] is False
    plan=science.verify_plan(tmp_path/'run',approved=False)
    assert Path(plan['base_dir'])==tmp_path/'pilot'
    capture=g._Inputs(tmp_path)
    prof=g.process_profile(production['task'],tmp_path/'production',_inputs=capture)
    assert prof['configuration']['path']==str(tmp_path/'production/config.json')
    assert str(tmp_path/'config.json') not in capture.rows
    capture.finish()


def test_actual_pilot_reader_forecast_and_observe_bind_plan_base_and_native_env(tmp_path,monkeypatch):
    # Real readers/profile/phase arithmetic; only prior execution/approval checks
    # are inert. No native process or qualified timing is created by this fixture.
    value,_=spec(tmp_path/'source')
    c=json.loads((tmp_path/'source/config.json').read_text())
    production=deepcopy(value);production['task']['config']='config.json'
    write(tmp_path/'production/config.json',c)
    production_pin=write(tmp_path/'production/spec.json',production)
    write(tmp_path/'config.json',{'outer_decoy':True})
    threads=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
    for key in threads:monkeypatch.delenv(key,raising=False)
    plans={}; roots=[]
    for n in (1,2):
        rd=tmp_path/('pilot'+str(n)); roots.append(str(rd))
        cfg=deepcopy(c);cfg['generation']['events']=n
        write(rd/'source/config.json',cfg)
        sv=deepcopy(value);sv['task']['config']='config.json'
        write(rd/science.SPEC,sv)
        plan={'base_dir':str(rd/'source'),'stages':[{'stage':'science','outputs':['outputs']}]}
        plans[str(rd)]=plan
        write(rd/science.PLAN,plan);write(rd/science.APPROVAL,{'inert':True})
        write(rd/g.execution.STATE_NAME,{'stages':{'science':{
            'started_utc':'2026-10-09T00:00:00+00:00','finished_utc':'2026-10-09T00:00:10+00:00'}}})
        write(rd/'outputs/result.json',{'status':'passed','physics_validated':False})
        rows=[{'phase':name,'state':'completed','wall_seconds':1.,'nested':False}
              for name in ('build','survey','refine','combine_events','store_events')]
        with monkeypatch.context() as native:
            for key in threads:native.setenv(key,'1')
            actual_native=g.machine_observation()
        write(rd/'outputs/model-events-phase-timing.json',{
            'kind':'source_native_phase_observation','complete':True,
            'configuration_sha256':hashlib.sha256((rd/'source/config.json').read_bytes()).hexdigest(),
            'machine':actual_native,'phases':rows})
    monkeypatch.setattr(science,'verify_plan',lambda rd,**kw:plans[str(Path(rd))])
    monkeypatch.setattr(g.execution,'validate_completed_execution',lambda *a,**kw:[])
    result=g.forecast(production_pin,roots,base_dir=tmp_path,
        scaling_assumption='Inert event-linear software control',wall_margin=1)
    assert result['decision']=='production_cost_forecast_available'
    assert result['profile']['caller_machine']['selected_environment']['OMP_NUM_THREADS'] is None
    assert result['profile']['machine']['selected_environment']['OMP_NUM_THREADS']=='1'
    assert result['pilots'][0]['profile']['configuration']['path']==str(tmp_path/'pilot1/source/config.json')
    observation=g.observe_pilot(roots[0],base_dir=tmp_path)
    assert observation['profile']['configuration']['path']==str(tmp_path/'pilot1/source/config.json')
    assert observation['forecast_eligible'] is False


@pytest.mark.parametrize('native_ceiling,expected',[(40,'budget_replan_required'),(80,'production_cost_forecast_available')])
def test_production_input_admission_respects_distinct_native_and_outer_walls(tmp_path,monkeypatch,native_ceiling,expected):
    value,pin=spec(tmp_path)
    c=json.loads((tmp_path/'config.json').read_text());c['max_seconds']=native_ceiling
    write(tmp_path/'config.json',c)
    profile=g.process_profile(value['task'],tmp_path)
    def pilot(root,target,capture):
        count=1 if root=='/A' else 2
        observed=deepcopy(profile);observed['events']=count
        timing={name:0. for name in (*g.PHASES,'ordinary_stage_residual')}
        timing['refine']=20.*count;timing['ordinary_stage_residual']=5.*count/3
        return {'rundir':root,'profile':observed,'phase_seconds':timing}
    monkeypatch.setattr(g,'_pilot',pilot)
    monkeypatch.setattr(science,'verify_plan',lambda *a,**kw:{'stages':[]})
    monkeypatch.setattr(g.execution,'validate_completed_execution',lambda *a,**kw:[])
    result=g.forecast(pin,['/A','/B'],base_dir=tmp_path,scaling_assumption='Inert scaling',wall_margin=1)
    assert result['forecast_seconds'][1]==65.
    assert result['decision']==expected
    assert result['enforced_ceilings']=={'ordinary_stage_seconds':90,'native_configuration_seconds':native_ceiling}
    request=write(tmp_path/'request.json',{'schema_version':1,'kind':'generation_efficiency_request',
        'production':pin,'pilots':['/A','/B'],'scaling_assumption':'Inert scaling','wall_margin':1,'precision':None})
    current=deepcopy(value);current['generation_efficiency']={'schema_version':1,'purpose':'production',
        'request':request,'forecast':write(tmp_path/'forecast.json',result)}
    called=[]
    monkeypatch.setattr(g,'precision_evidence',lambda *a,**kw:called.append(kw['production_pin']))
    if expected=='budget_replan_required':
        with pytest.raises(ValueError,match='budget replan'):g.inputs(current,tmp_path)
        assert called==[]
    else:
        g.inputs(current,tmp_path);assert called==[pin]


def test_same_process_precision_cannot_reuse_different_production_exposure(tmp_path):
    value,pin=spec(tmp_path);profile=g.process_profile(value['task'],tmp_path)
    source=write(tmp_path/'source.txt',b'Inert normalization/estimator law for declared exposure only.\n')
    binding={'production':pin,'configuration':profile['configuration'],
        'exposure':{'events':profile['events'],'seed':profile['seed']},
        'normalization_target':'Exact source-defined production exposure'}
    target={'schema_version':2,'kind':'generation_precision_target','profile_sha256':profile['profile_sha256'],
        **binding,'unit':'pb','coordinates':['all-bin'],'absolute_targets':['.01']}
    evidence={'schema_version':2,'kind':'generation_precision_evidence','profile_sha256':profile['profile_sha256'],
        **binding,'pilot_roots':['/A','/B'],'estimator':'inert projected errors','sampling_design':'inert blocks',
        'estimator_source':source,'covariance_source':source,'normalization_source':source,
        'target_source':write(tmp_path/'target.json',target),'unit':'pb','coordinates':['all-bin'],
        'absolute_errors':['.005'],'absolute_targets':['.01']}
    declaration={'evidence':write(tmp_path/'evidence.json',evidence),'review_rundir':'/not-consumed',
        'check_id':'precision','claim_scope':'precision'}
    changed=deepcopy(value)
    cfg=json.loads((tmp_path/'config.json').read_text());cfg['generation']['events']=2
    write(tmp_path/'other-config.json',cfg);changed['task']['config']=str(tmp_path/'other-config.json')
    other=write(tmp_path/'other-spec.json',changed)
    actual=g.process_profile(changed['task'],tmp_path)
    assert actual['profile_sha256']==profile['profile_sha256']
    with pytest.raises(ValueError,match='exact current production/configuration/exposure'):
        g.precision_evidence(declaration,actual,[{'rundir':'/A'},{'rundir':'/B'}],g._Inputs(tmp_path),production_pin=other)
