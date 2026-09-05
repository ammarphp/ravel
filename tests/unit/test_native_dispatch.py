"""Native plans preserve the declared physical family through fake execution."""
import argparse
import gzip
import json
from pathlib import Path
import pytest
from ravel.physics import native_pipeline as pipeline
from ravel.physics import native_normalization as norm
from ravel.physics.native_capabilities import resolve_capability


def workspace():
    return {'version':'1.0.0','channels':[{'name':'A','samples':[{'name':'bkg','data':[3.],'modifiers':[]}]}],
            'observations':[{'name':'A','data':[3]}],
            'measurements':[{'name':'Measurement','config':{'poi':'mu','parameters':[]}}]}


def configuration(tmp_path, statistics='yields'):
    cards=tmp_path/'cards';cards.mkdir()
    (cards/'process.dat').write_text('import model MSSM_SLHA2\ndefine p = g u d u~ d~\ngenerate p p > x1+ n2\nadd process p p > x1- n2\n')
    (cards/'param.dat').write_text('Block MASS\n 1000023 300\n 1000024 300\n 1000022 100\nDECAY 1000023 1\n 1 2 1000022 23\nDECAY 1000024 1\n 1 2 1000022 24\n')
    (cards/'run.dat').write_text("2 = nevents\n3 = iseed\n6500 = ebeam1\n6500 = ebeam2\n0 = ickkw\n'cteq6l1' = pdlabel\nFalse = use_syst\n")
    (cards/'shower.cfg').write_text('Beams:frameType = 4\nBeams:LHEF = supplied-by-plan\nPrint:quiet = on\n')
    (cards/'detector.tcl').write_text('# explicitly selected detector card\n')
    path=tmp_path/'config.toml'
    path.write_text(f'''[madgraph.run]
nevents = 2
seed = 3
ecms = 13000
[analysis]
script = "Delphes2SA.py"
lumi = 139000
kfactor = 0.8
[simpleanalysis]
name = "EwkThreeLeptonERJR2018"
[ravel.native]
model = "c1n2-wz"
preparation = "explicit-cards"
detector = "simpleanalysis-delphes"
statistics = "{statistics}"
[ravel.native.inputs]
process_card = "cards/process.dat"
param_card = "cards/param.dat"
run_card = "cards/run.dat"
shower_card = "cards/shower.cfg"
delphes_card = "cards/detector.tcl"
''')
    return path


def approve_fixture(plan,*,contract_changes=None,budget_changes=None,mode=None):
    """Record explicit synthetic test approval; production never calls this."""
    from ravel.workflow import workflow_state
    root=Path(plan['rundir']);saved=pipeline.write_plan(plan);cap=plan['capability']
    mode=mode or plan['required_compute_plan']
    contract={'schema_version':1,'prompt':'Synthetic native adapter execution test','task_mode':'reproduce',
              'detector_mode':'simpleanalysis-delphes-native','stat_mode':'stability-only' if cap['statistics_adapter']=='yields' else 'published-likelihood',
              'required_user_inputs':[],'assumptions':['Stub tools are not physics evidence'],
              'compute_plan':mode,'approval_required':True,
              'targets':{'model':cap['model'],'analysis':[cap['routine']],
                         'masses_gev':sorted(set(plan['expected_masses_gev'].values())),
                         'lumi_fb':plan['luminosity_pb_inverse']/1000},
              'execution_plan':{'path':saved.relative_to(root).as_posix(),'sha256':norm.fingerprint(saved)['sha256']}}
    contract.update(contract_changes or {})
    budget={'schema_version':1,'generated_by':'cost_preflight.py','mode':mode,'points':plan['campaign_points'],
            'events_per_point':plan['nevents'],'backend':'native','walltime_h':[.01,1.]}
    budget.update(budget_changes or {})
    if mode in ('full','scan'):contract['cost_estimate']=budget
    checkin={'schema_version':1,'kind':'checkin1','sections':{'i':'Synthetic declared target','i-b':'Stub tools',
             'ii':'No physics gallery claimed','iii':{'plan':'Run fixture tools','waypoint':'Receipt checks'},
             'iv':'Test budget','v':[{'id':'F1','text':'Synthetic artifacts only'}],'vi':['test','review','execute']}}
    for name,value in [('task_contract',contract),('cost_preflight',budget),('checkin1',checkin)]:
        (root/'inputs'/(name+'.json')).write_text(json.dumps(value))
    assert workflow_state.cmd_approve(argparse.Namespace(rundir=str(root),plan=mode,quote='Approved this synthetic unit-test fixture'))==0


def test_dry_plan_has_actual_non_slepton_commands_without_writes(tmp_path):
    plan=pipeline.build_execution_plan(tmp_path,configuration(tmp_path),model='c1n2-wz',analysis_id='ATLAS-SUSY-2018-06',m_parent=300,m_lsp=100)
    assert plan['capability']['routine']=='EwkThreeLeptonERJR2018'
    assert plan['compute_authorized'] is False and plan['capability']['physics_certified'] is False
    assert not (tmp_path/'output').exists()
    stage=next(s for s in plan['stages'] if s['stage']=='simpleanalysis')
    assert stage['command'][-2:]==['--routine','EwkThreeLeptonERJR2018']
    assert all('EwkCompressed2018' not in p for p in stage['outputs'])
    assert 'sa2json' not in [s['stage'] for s in plan['stages']]
    assert all(set(s)=={'stage','command','inputs','outputs','depends_on'} for s in plan['stages'])


@pytest.mark.parametrize('change',['wrong_process','wrong_analysis','wrong_detector','wrong_scan_mass','missing_kfactor','merged','wrong_event_count'])
def test_unsupported_inputs_fail_before_preparation(tmp_path,change):
    config=configuration(tmp_path);kwargs={}
    if change=='wrong_process':(tmp_path/'cards/process.dat').write_text('import model MSSM_SLHA2\ngenerate p p > el+ el-\n')
    if change=='wrong_analysis':kwargs['analysis_id']='ATLAS-SUSY-2018-16'
    if change=='wrong_detector':config.write_text(config.read_text().replace('simpleanalysis-delphes','particle-level'))
    if change=='wrong_scan_mass':kwargs['m_parent']=450
    if change=='missing_kfactor':config.write_text(config.read_text().replace('kfactor = 0.8',''))
    if change=='merged':
        card=tmp_path/'cards/run.dat';card.write_text(card.read_text().replace('0 = ickkw','1 = ickkw'))
    if change=='wrong_event_count':
        card=tmp_path/'cards/run.dat';card.write_text(card.read_text().replace('2 = nevents','4 = nevents'))
    with pytest.raises(ValueError):pipeline.build_execution_plan(tmp_path,config,**kwargs)
    assert not (tmp_path/'output').exists()


def test_preparation_preserves_cards_and_source_mutation_invalidates_plan(tmp_path):
    plan=pipeline.build_execution_plan(tmp_path,configuration(tmp_path));saved=pipeline.write_plan(plan)
    pristine=(tmp_path/'cards/param.dat').read_bytes();pipeline.prepare(plan)
    assert (tmp_path/'cards/param.dat').read_bytes()==(tmp_path/'output/param_card.dat').read_bytes()==pristine
    launch=(tmp_path/'output/run.mg5').read_text()
    assert launch.count('\ndone\n')==2 and 'slepton' not in launch.lower()
    assert str(tmp_path/'output/madgraph/unweighted_events.lhe') in (tmp_path/'output/shower.cfg').read_text()
    (tmp_path/'cards/param.dat').write_text('changed')
    with pytest.raises(ValueError,match='changed since planning'):pipeline.load_plan(saved)


def test_non_slepton_likelihood_requires_explicit_complete_channel_map(tmp_path):
    config=configuration(tmp_path,'mapped-likelihood')
    (tmp_path/'background.json').write_text(json.dumps(workspace()))
    (tmp_path/'channels.json').write_text(json.dumps({'A':{'region':'SRlow'}}))
    config.write_text(config.read_text()+'likelihood = "background.json"\nchannel_map = "channels.json"\n')
    plan=pipeline.build_execution_plan(tmp_path,config)
    command=next(s['command'] for s in plan['stages'] if s['stage']=='sa2json')
    assert '--channel-map' in command and '-c' not in command
    (tmp_path/'channels.json').write_text('{}')
    with pytest.raises(ValueError,match='every workspace channel'):pipeline.build_execution_plan(tmp_path,config)


def test_inclusive_discovery_regions_are_not_an_independent_likelihood():
    with pytest.raises(ValueError,match='unsupported statistics'):
        resolve_capability('ZeroLeptonDiscovery2018','squark-neutralino','explicit-cards','simpleanalysis-delphes','mapped-likelihood')
    assert resolve_capability('ZeroLeptonDiscovery2018','squark-neutralino','explicit-cards','simpleanalysis-delphes','yields')['routine']=='ZeroLeptonDiscovery2018'


def test_fake_tool_chain_runs_non_slepton_plan_and_real_bookkeeping(tmp_path,monkeypatch):
    stub_backend(tmp_path,monkeypatch)
    plan=pipeline.build_execution_plan(tmp_path,configuration(tmp_path));(tmp_path/'logs').mkdir();called=[]
    approve_fixture(plan)
    def supervise(stage,rundir,events,log,command,**declarations):
        called.append(stage)
        assert declarations['cwd']==str(tmp_path) and declarations['outputs'] and declarations['resume'] is True
        if stage=='prepare':pipeline.prepare(plan)
        elif stage=='madgraph':
            target=Path(declarations['outputs'][0]);target.parent.mkdir(parents=True,exist_ok=True)
            event='<event>\n1 1 1 1 1 1\n1000022 1 0 0 0 0 0 0 0 100 100 0 9\n</event>\n'
            with gzip.open(target,'wt') as stream:stream.write('<LesHouchesEvents>\n<init>\n2212 2212 6500 6500 0 0 0 0 3 1\n2 0.1 1 1\n</init>\n'+event*2+'</LesHouchesEvents>\n')
            Path(log).write_text('Cross-section : 2 +- 0.1 pb\n')
        elif stage=='unpack_lhe':pipeline.main(['unpack','--input',declarations['inputs'][0],'--output',declarations['outputs'][0]])
        elif stage=='pythia':
            Path(declarations['outputs'][0]).write_text('fake HepMC\n');Path(log).write_text('pythia_shower: wrote 2 events; sigma = 2e-9 mb\n')
        elif stage=='normalization':
            result=norm.resolve_normalization(tmp_path/'output/madgraph/unweighted_events.lhe',tmp_path/'logs/madgraph.log',tmp_path/'logs/pythia.log',.8,2)
            Path(declarations['outputs'][0]).write_text(json.dumps(result))
        elif stage=='native_report':pipeline.main(['report','--plan',plan['plan_path']])
        else:
            for output in declarations['outputs']:
                Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text('{}' if output.endswith('.json') else 'fake native output\n')
        assert all(Path(p).is_file() for p in declarations['outputs'])
        return 0
    assert pipeline.execute_plan(plan,supervisor=supervise)==0
    assert called==[s['stage'] for s in plan['stages']]
    result=json.loads((tmp_path/'output/native_execution_result.json').read_text())
    assert result['analysis']=='EwkThreeLeptonERJR2018' and result['model']=='c1n2-wz'
    assert result['physics_certified'] is False
    assert norm.load_normalization(tmp_path/'output/normalization.json')['applied_cross_section_pb']==1.6


def test_failed_supervisor_has_no_unsupervised_fallback(tmp_path,monkeypatch):
    stub_backend(tmp_path,monkeypatch)
    plan=pipeline.build_execution_plan(tmp_path,configuration(tmp_path));calls=[]
    approve_fixture(plan)
    def failed(*args,**kwargs):calls.append(args[0]);return 43
    assert pipeline.execute_plan(plan,supervisor=failed)==43 and calls==['prepare']


def test_scan_validates_selected_batch_before_any_launch(tmp_path,monkeypatch):
    from ravel.workflow import scan_orchestrator as scan
    first=tmp_path/'one';second=tmp_path/'two';first.mkdir();second.mkdir();configuration(first);configuration(second)
    broken=second/'config.toml';broken.write_text(broken.read_text().replace('kfactor = 0.8',''))
    points=[{'tag':p.name,'run_dir':str(p),'config':'config.toml','m_parent':300,'m_lsp':100} for p in (first,second)]
    monkeypatch.setattr(scan,'load_manifest',lambda _:('',{'model':'c1n2-wz','analysis_id':'ATLAS-SUSY-2018-06','points':points}))
    monkeypatch.setattr(scan,'point_status',lambda _:('pending',''))
    monkeypatch.setattr(scan.subprocess,'Popen',lambda *a,**k:pytest.fail('launched before every plan was validated'))
    with pytest.raises(SystemExit,match='before launch'):scan.cmd_launch(argparse.Namespace(scandir='unused',backend='native',max=2,go=True,pdf=None))
    assert not (first/'output').exists()


def stub_backend(tmp_path,monkeypatch):
    """Replace external engines only; exercise real subprocesses and receipts."""
    import sys
    build=tmp_path/'backend';tools=build/'tools'
    conda=tools/'miniforge3/bin/conda';conda.parent.mkdir(parents=True)
    conda.write_text('#!'+sys.executable+'\n'+r'''
import gzip,json,pathlib,sys
cmd=sys.argv[5:]
def arg(flag):return cmd[cmd.index(flag)+1]
def put(path,text='stub physics artifact\n'):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
name=pathlib.Path(cmd[0]).name
if name=='mg5_aMC':
    # Real MG refuses an existing output directory. The wrapper must give every
    # changed-input attempt a fresh cwd rather than delete downstream artifacts.
    proc=pathlib.Path('PROC_madgraph')
    if proc.exists():sys.exit(41)
    proc.mkdir();target=proc/'Events/run_01/unweighted_events.lhe.gz';target.parent.mkdir(parents=True)
    event='<event>\n1 1 1 1 1 1\n1000022 1 0 0 0 0 0 0 0 100 100 0 9\n</event>\n'
    with gzip.open(target,'wt') as f:f.write('<LesHouchesEvents>\n<init>\n2212 2212 6500 6500 0 0 0 0 3 1\n2.0 0.1 1 1\n</init>\n'+event*2+'</LesHouchesEvents>\n')
    print('Cross-section : 2.0 +- 0.1 pb')
elif name=='pythia_shower':
    put(cmd[2]);print('pythia_shower: wrote 2 events; sigma = 2e-9 mb')
elif name=='DelphesHepMC3':put(cmd[2])
elif name=='python':
    module=cmd[2]
    if module=='ravel.validation.lhe_check':put(arg('--json-out'),'{}')
    elif module=='ravel.physics.delphes2sa_native':
        put(arg('--output'));put(arg('--output')+'.normalization.json','{}')
    elif module=='ravel.physics.native_simpleanalysis':
        for ext in ('.root','.txt'):put(str(pathlib.Path(arg('--output'))/(arg('--routine')+ext)))
        if arg('--routine')=='EwkCompressed2018':
            for name in ('native_objects.txt','native_rjr.csv'):put(str(pathlib.Path(arg('--output'))/name))
    elif module=='ravel.physics.sa2json_native':put(arg('-o'),'[]')
    elif module=='ravel.physics.pyhf_exclude':put(str(pathlib.Path(arg('--out'))/'exclusion.json'),'{}')
    else:raise RuntimeError('unexpected module '+repr(cmd))
else:raise RuntimeError('unexpected command '+repr(cmd))
''');conda.chmod(0o755)
    for relative in ('mg5amcnlo/bin/mg5_aMC','miniforge3/envs/recast/bin/DelphesHepMC3',
                     'miniforge3/envs/mg5/bin/python','miniforge3/envs/rivet/bin/python','miniforge3/envs/recast/bin/python'):
        path=tools/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('#!/bin/sh\nexit 88\n');path.chmod(0o755)
    converter=tools/'miniforge3/envs/pipeline/share/mapyde/scripts/Delphes2SA.py'
    converter.parent.mkdir(parents=True);converter.write_text('# explicitly pinned stub converter\n')
    for name in ('pythia_shower','rjr_resolve'):
        path=build/name;path.write_text('#!/bin/sh\nexit 89\n');path.chmod(0o755)
    monkeypatch.setattr(pipeline,'native_build_root',lambda:build)
    monkeypatch.setattr(pipeline,'native_binary',lambda name:build/name)
    return build


def quick_supervisor(*args,**kwargs):
    from ravel.workflow.stage_supervisor import supervise
    return supervise(*args,**kwargs,poll=.005,grace=.1,kill_secs=30)


@pytest.mark.parametrize('model,routine',[
    ('c1n2-wz','EwkThreeLeptonERJR2018'),('slepton-bino','EwkCompressed2018'),
    ('gluino-neutralino','ZeroLeptonDiscovery2018'),('squark-neutralino','ZeroLeptonDiscovery2018')])
def test_every_registered_family_subprocess_receipts_and_changed_card_resume(tmp_path,monkeypatch,model,routine):
    from ravel.workflow.execution import load_execution,validate_execution
    stub_backend(tmp_path,monkeypatch)
    config=configuration(tmp_path)
    config.write_text(config.read_text().replace('c1n2-wz',model).replace('EwkThreeLeptonERJR2018',routine))
    if model!='c1n2-wz':
        particle,pdg,daughters={'slepton-bino':('el+ el-',1000011,'2 1000022 11'),
                                'gluino-neutralino':('go go',1000021,'3 1000022 1 -1'),
                                'squark-neutralino':('ul ul~',1000002,'2 1000022 2')}[model]
        (tmp_path/'cards/process.dat').write_text('import model MSSM_SLHA2\ngenerate p p > '+particle+'\n')
        (tmp_path/'cards/param.dat').write_text(f'Block MASS\n {pdg} 300\n 1000022 100\nDECAY {pdg} 1\n 1 {daughters}\n')
    plan=pipeline.build_execution_plan(tmp_path,config)
    approve_fixture(plan)
    assert pipeline.execute_plan(plan,supervisor=quick_supervisor)==0
    assert validate_execution(tmp_path)==[]
    first=load_execution(tmp_path)
    first_ids={name:r['attempt_id'] for name,r in first['stages'].items()}
    assert pipeline.execute_plan(plan,supervisor=quick_supervisor)==0
    assert first_ids=={name:r['attempt_id'] for name,r in load_execution(tmp_path)['stages'].items()}
    old_lhe=(tmp_path/'output/madgraph/unweighted_events.lhe').read_bytes()
    card=tmp_path/'cards/run.dat';card.write_text(card.read_text()+'# requested revision\n')
    revised=pipeline.build_execution_plan(tmp_path,config)
    approve_fixture(revised)
    assert pipeline.execute_plan(revised,supervisor=quick_supervisor)==0
    assert validate_execution(tmp_path)==[]
    current=load_execution(tmp_path)
    assert all(current['stages'][name]['attempt_id']!=old for name,old in first_ids.items())
    assert len(list((tmp_path/'work/madgraph').glob('attempt-*/PROC_madgraph')))==2
    archived=list((tmp_path/'logs/execution/unpack_lhe').glob('*/prior_outputs/0/unweighted_events.lhe'))
    assert len(archived)==1 and archived[0].read_bytes()==old_lhe
    assert all((tmp_path/record['attempt_record']).is_file() for record in first['stages'].values())
    result=json.loads((tmp_path/'output/native_execution_result.json').read_text())
    assert result['analysis']==routine and result['model']==model and result['physics_certified'] is False


@pytest.mark.parametrize('failure',['empty_config','unknown_routine','unknown_adapter','missing_backend','wrong_beam_alias','late_alias','single_parent','width_only','wrong_daughters','bad_workspace'])
def test_adversarial_preflight_does_not_start_tools(tmp_path,monkeypatch,failure):
    backend=stub_backend(tmp_path,monkeypatch);config=configuration(tmp_path)
    if failure=='empty_config':config.write_text('')
    if failure=='unknown_routine':config.write_text(config.read_text().replace('EwkThreeLeptonERJR2018','invented'))
    if failure=='unknown_adapter':config.write_text(config.read_text().replace('explicit-cards','infer-cards'))
    if failure=='missing_backend':(backend/'pythia_shower').unlink()
    if failure=='wrong_beam_alias':(tmp_path/'cards/process.dat').write_text('import model MSSM_SLHA2\ndefine p = e+ e-\ngenerate p p > x1+ n2\n')
    if failure=='late_alias':
        card=tmp_path/'cards/process.dat';card.write_text(card.read_text()+'define n2 = go\n')
    if failure=='single_parent':(tmp_path/'cards/process.dat').write_text('import model MSSM_SLHA2\ngenerate p p > n2 j\n')
    if failure=='width_only':(tmp_path/'cards/param.dat').write_text('Block MASS\n 1000023 300\n 1000024 300\n 1000022 100\nDECAY 1000023 1\nDECAY 1000024 1\n')
    if failure=='wrong_daughters':
        card=tmp_path/'cards/param.dat';card.write_text(card.read_text().replace('1000022 23','1000022 22').replace('1000022 24','1000022 22'))
    if failure=='bad_workspace':
        config.write_text(config.read_text().replace('statistics = "yields"','statistics = "mapped-likelihood"')+'likelihood = "background.json"\nchannel_map = "channels.json"\n')
        (tmp_path/'background.json').write_text('{"channels":[]}');(tmp_path/'channels.json').write_text('{}')
    with pytest.raises(ValueError):
        plan=pipeline.build_execution_plan(tmp_path,config)
        if failure=='missing_backend':approve_fixture(plan)
        pipeline.execute_plan(plan,supervisor=lambda *a,**k:pytest.fail('preflight started an external tool'))
    assert not (tmp_path/'output').exists() and not (tmp_path/'execution_state.json').exists()


@pytest.mark.parametrize('state',['running','failed','done'])
def test_babysitter_never_prunes_or_mtime_heals_receipted_runs(tmp_path,monkeypatch,state):
    from ravel.workflow import scan_babysitter as baby,execution
    root=tmp_path/'point';artifact=root/'output/madgraph/events.hepmc';artifact.parent.mkdir(parents=True);artifact.write_text('retained evidence')
    status=root/'logs/STATUS.txt';status.parent.mkdir();status.write_text('PASS old stage\n')
    (root/'execution_state.json').write_text('{}')
    ledger={'stages':{'madgraph':{'status':'running','child_pid':123,'child_identity':'owned'}}} if state=='running' else {'stages':{'native_report':{'status':'succeeded'}}}
    monkeypatch.setattr(execution,'load_execution',lambda _:ledger)
    monkeypatch.setattr(execution,'process_identity',lambda _:'owned')
    monkeypatch.setattr(baby,'supervised_stage_active',lambda *a:state=='running')
    monkeypatch.setattr(execution,'validate_execution',lambda _:['failure'] if state=='failed' else [])
    monkeypatch.setattr(baby,'live_points',lambda:set())
    counts,freed=baby.cycle('unused',{'points':[{'run_dir':str(root),'tag':'m300_dm200'}]},argparse.Namespace(stale_min=0))
    assert counts[state]==1 and counts['healed']==0 and counts['stale']==0 and freed==0
    assert artifact.read_text()=='retained evidence' and status.exists()
    assert baby.clean_heavy(root)==0
    with pytest.raises(ValueError,match='supervised|native_pipeline'):baby.reset_point(root)


def test_scan_yields_completion_and_explicit_failed_resume(tmp_path,monkeypatch):
    from ravel.workflow import scan_orchestrator as scan,scan_babysitter as baby
    config=configuration(tmp_path)
    (tmp_path/'execution_state.json').write_text('{}')
    (tmp_path/'output').mkdir();(tmp_path/'output/native_execution_result.json').write_text('{"statistics":"yields"}')
    mp={'run_dir':str(tmp_path),'tag':'m300_dm200','config':str(config),'m_parent':300,'m_lsp':100}
    monkeypatch.setattr(baby,'point_state',lambda _:'done')
    monkeypatch.setattr(scan,'harvest_point',lambda _:pytest.fail('yields completion tried to invent a limit'))
    assert scan.point_status(mp)==('done',None)
    monkeypatch.setattr(baby,'point_state',lambda _:'failed')
    assert scan.point_status(mp)==('failed',None)
    monkeypatch.setattr(scan,'load_manifest',lambda _:('',{'model':'c1n2-wz','analysis_id':'ATLAS-SUSY-2018-06','points':[mp]}))
    launched=[];monkeypatch.setattr(scan,'launch_point',lambda *a,**k:launched.append(k['plan']))
    args=argparse.Namespace(scandir='unused',backend='native',max=1,go=False,pdf=None,resume=False)
    scan.cmd_launch(args);assert launched==[]
    args.resume=True;scan.cmd_launch(args);assert len(launched)==1


def test_quiet_live_stage_uses_supervisor_lock_and_orphan_is_held(tmp_path):
    import fcntl
    from ravel.workflow.scan_babysitter import point_state
    lock=tmp_path/'logs/execution/madgraph.lock';lock.parent.mkdir(parents=True)
    (tmp_path/'execution_state.json').write_text(json.dumps({'schema_version':1,'revision':0,'stages':{'madgraph':{'status':'running'}}}))
    with lock.open('w') as stream:
        fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
        assert point_state(tmp_path)=='running'
        fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
    assert point_state(tmp_path)=='failed'


@pytest.mark.parametrize('failure',['missing','stale','unbound_plan','changed_plan','wrong_model','wrong_analysis','wrong_mass','wrong_lumi','wrong_stats','exceeded_events','exceeded_points','wrong_backend','dry'])
def test_executor_library_rejects_unapproved_scope_before_any_stage(tmp_path,monkeypatch,failure):
    stub_backend(tmp_path,monkeypatch);plan=pipeline.build_execution_plan(tmp_path,configuration(tmp_path))
    if failure!='missing':
        targets={'model':plan['capability']['model'],'analysis':[plan['capability']['routine']],
                 'masses_gev':[100,300],'lumi_fb':139}
        changes={};budget={};mode=None
        if failure=='wrong_model':targets['model']='slepton-bino'
        if failure=='wrong_analysis':targets['analysis']=['EwkCompressed2018']
        if failure=='wrong_mass':targets['masses_gev']=[100,400]
        if failure=='wrong_lumi':targets['lumi_fb']=140
        if failure.startswith('wrong_') and failure not in ('wrong_stats','wrong_backend'):changes['targets']=targets
        if failure=='wrong_stats':changes['stat_mode']='published-likelihood'
        if failure=='exceeded_events':budget['events_per_point']=1
        if failure=='wrong_backend':budget['backend']='container'
        if failure=='exceeded_points':
            plan=pipeline.build_execution_plan(tmp_path,tmp_path/'config.toml',campaign_points=2);budget['points']=1
        if failure=='dry':mode='dry'
        approve_fixture(plan,contract_changes=changes,budget_changes=budget,mode=mode)
        if failure=='stale':
            path=tmp_path/'inputs/checkin1.json';path.write_text(path.read_text()+'\n')
        if failure=='unbound_plan':
            path=tmp_path/'inputs/task_contract.json';value=json.loads(path.read_text());del value['execution_plan'];path.write_text(json.dumps(value))
            from ravel.workflow.workflow_state import cmd_approve
            assert cmd_approve(argparse.Namespace(rundir=str(tmp_path),plan='smoke',quote='Synthetic legacy fixture'))==0
        if failure=='changed_plan':
            path=Path(plan['plan_path']);path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError):pipeline.execute_plan(plan,supervisor=lambda *a,**k:pytest.fail('unauthorized stage started'))
    assert not (tmp_path/'output').exists() and not (tmp_path/'execution_state.json').exists()


def test_valid_approval_does_not_allow_replacement_plan(tmp_path,monkeypatch):
    stub_backend(tmp_path,monkeypatch);config=configuration(tmp_path);plan=pipeline.build_execution_plan(tmp_path,config)
    approve_fixture(plan);assert pipeline.verify_execution_approval(plan) is True
    card=tmp_path/'cards/run.dat';card.write_text(card.read_text()+'# changed generation proposal\n')
    replacement=pipeline.build_execution_plan(tmp_path,config);pipeline.write_plan(replacement)
    with pytest.raises(ValueError,match='approved bytes'):pipeline.execute_plan(replacement,supervisor=lambda *a,**k:pytest.fail('replacement ran'))


def test_internal_generation_entry_also_requires_approval(tmp_path,monkeypatch):
    stub_backend(tmp_path,monkeypatch);plan=pipeline.build_execution_plan(tmp_path,configuration(tmp_path));saved=pipeline.write_plan(plan)
    monkeypatch.setattr(pipeline.subprocess,'run',lambda *a,**k:pytest.fail('unauthorized internal generation'))
    with pytest.raises(ValueError,match='approval'):pipeline.generate(plan)
    with pytest.raises(SystemExit) as error:pipeline.main(['generate','--plan',str(saved)])
    assert error.value.code==2 and not (tmp_path/'work').exists()


@pytest.mark.parametrize('statistics',['mapped-likelihood','compressed-likelihood'])
def test_statistical_adapters_execute_their_declared_subprocess_plan(tmp_path,monkeypatch,statistics):
    from ravel.workflow.execution import validate_execution
    stub_backend(tmp_path,monkeypatch);config=configuration(tmp_path,statistics)
    background=workspace()
    if statistics=='compressed-likelihood':
        config.write_text(config.read_text().replace('c1n2-wz','slepton-bino').replace('EwkThreeLeptonERJR2018','EwkCompressed2018'))
        (tmp_path/'cards/process.dat').write_text('import model MSSM_SLHA2\ngenerate p p > el+ el-\n')
        (tmp_path/'cards/param.dat').write_text('Block MASS\n 1000011 300\n 1000022 100\nDECAY 1000011 1\n 1 2 1000022 11\n')
        for group in ('channels','observations'):background[group][0]['name']='SR_eMLLa_hghmet_ee'
        background['measurements'][0]['config']['poi']='mu_SIG'
    (tmp_path/'background.json').write_text(json.dumps(background))
    config.write_text(config.read_text()+'likelihood = "background.json"\n')
    if statistics=='mapped-likelihood':
        (tmp_path/'channels.json').write_text('{"A":{"region":"SRlow"}}')
        config.write_text(config.read_text()+'channel_map = "channels.json"\n')
    plan=pipeline.build_execution_plan(tmp_path,config);approve_fixture(plan)
    assert pipeline.execute_plan(plan,supervisor=quick_supervisor)==0
    assert validate_execution(tmp_path)==[] and (tmp_path/'output/exclusion.json').is_file()
    report=json.loads((tmp_path/'output/native_execution_result.json').read_text())
    assert report['statistics']==statistics and report['physics_certified'] is False


@pytest.mark.parametrize('process',[
    'generate p p > x1+ n2\nadd process p p > x1+ n2 j\n',
    'define weak = x1+ x1- n2\ngenerate p p > weak weak\n'])
def test_unmerged_adapter_rejects_overlapping_samples_and_wrong_associated_modes(tmp_path,process):
    card=tmp_path/'process.dat';card.write_text('import model MSSM_SLHA2\n'+process)
    with pytest.raises(ValueError,match='overlap|associated'):pipeline.validate_process_card(card,'c1n2-wz')


def test_mapped_signal_uses_declared_workspace_poi_and_rejects_background_owned_poi():
    from ravel.physics.sa2json_native import signal_poi
    import pyhf
    spec=workspace();poi=signal_poi(spec)
    assert poi=='mu'
    spec['channels'][0]['samples'].append({'name':'signal','data':[15.],
        'modifiers':[{'name':poi,'type':'normfactor','data':None}]})
    assert pyhf.Workspace(spec).model().config.poi_name=='mu'
    with pytest.raises(ValueError,match='background'):signal_poi(spec)


def test_container_launch_is_diagnostic_only_until_bound_adapter_exists(tmp_path,monkeypatch,capsys):
    from ravel.workflow import scan_orchestrator as scan
    point={'run_dir':str(tmp_path),'tag':'m300_dm200','config':'config.toml'}
    manifest={'points':[point]}
    monkeypatch.setattr(scan,'load_manifest',lambda _:('',manifest))
    monkeypatch.setattr(scan,'point_status',lambda _:('pending',None))
    monkeypatch.setattr(scan.subprocess,'Popen',lambda *a,**k:pytest.fail('unbound container was launched'))
    args=argparse.Namespace(scandir='unused',backend='container',max=1,go=False,force=False)
    scan.cmd_launch(args)
    assert 'DRY DIAGNOSTIC ONLY; live dispatch unsupported' in capsys.readouterr().out
    args.go=True
    with pytest.raises(SystemExit,match='unsupported'):scan.cmd_launch(args)
    with pytest.raises(SystemExit,match='unsupported'):scan.launch_point(point,manifest,args)
    assert not (tmp_path/'logs').exists()
