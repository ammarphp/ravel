"""Real subprocess transport controls using an explicit Podman protocol stand-in.

These exercise host lifecycle and refusal semantics, not an ATLAS installation,
VM, emulator, source compile or scientific witness.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from ravel.analysis_sources import digest
from ravel.physics.routine_build import executable_identity
from ravel.physics import simpleanalysis_container as bridge


FAKE = '''import json,os,sys,time
from pathlib import Path
args=sys.argv[1:];assert args[:2]==['--connection','test'];args=args[2:]
root=Path(os.environ['HOME']);p=root/'state.json';s=json.loads(p.read_text()) if p.exists() else {}
cid='a'*64;op=args[0]
with (root/'calls.jsonl').open('a') as f:f.write(json.dumps(args)+'\\n')
def save():p.write_text(json.dumps(s))
if op=='create':
    labels={}
    for i,x in enumerate(args):
        if x=='--label':
            k,v=args[i+1].split('=',1);labels[k]=v
    s={'Id':cid,'Name':args[args.index('--name')+1],'Image':'sha256:'+'b'*64,
       'Config':{'Labels':labels},'State':{'Running':False,'Pid':0,'ExitCode':0}}
    save();Path(args[args.index('--cidfile')+1]).write_text(cid);print(cid)
elif args[:2]==['container','exists']:
    sys.exit(0 if s else 1)
elif args[:2]==['container','inspect']:
    print(json.dumps([s]));sys.exit(0)
elif args[:2]==['container','stop']:
    s['State']['Running']=False;s['State']['Pid']=0;s['State']['ExitCode']=143;save()
elif op=='cp':
    if args[1].startswith(cid+':'):
        out=Path(args[2]);out.mkdir(exist_ok=True);(out/'native.log').write_text('actual stand-in retained output\\n')
elif op=='start':
    s['State']['Running']=True;s['State']['Pid']=4321;save()
    mode=(root/'mode').read_text() if (root/'mode').exists() else 'pass'
    if mode=='hang':time.sleep(60)
    code=2 if mode=='fail' else 0
    s['State']['Running']=False;s['State']['Pid']=0;s['State']['ExitCode']=code;save();print('native stand-in console');sys.exit(code)
elif op=='wait':print(s['State']['ExitCode'])
else:raise RuntimeError(args)
'''


def fixture(tmp_path):
    host = tmp_path/'host'; host.mkdir()
    client = tmp_path/'podman'; client.write_text('#!' + sys.executable + '\n' + FAKE); client.chmod(0o755)
    image = {'reference': 'example/analysisbase@sha256:' + 'c'*64,
             'manifest_sha256': 'c'*64, 'config_sha256': 'b'*64,
             'platform': 'linux/amd64', 'user': 'atlas'}
    qualification = tmp_path/'qualification.json'
    qualification.write_text(json.dumps({'status':'passed', 'image':image,
        'native_process_observation': {'scope':'explicit protocol stand-in'},
        'emulation_observation': {'scope':'explicit protocol stand-in','procfs_semantics_observed':True,'emulator_binary_identity_complete':True},
        'cleanup':{'requires_recovery':False}}))
    env = {'PATH':'/usr/bin:/bin','HOME':str(host),'TMPDIR':str(host),
           'LC_ALL':'C','LC_CTYPE':'C','PYTHONCOERCECLOCALE':'0','PYTHONUTF8':'1',
           'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
           'XDG_CONFIG_HOME':str(host),'XDG_DATA_HOME':str(host),
           'CONTAINERS_MACHINE_PROVIDER':'test'}
    if sys.platform == 'darwin': env['__CF_USER_TEXT_ENCODING'] = f'0x{os.getuid():X}:0x0:0x0'
    config = {'schema_version':1,'client':executable_identity(client),'client_artifacts':[],
              'connection':'test','environment':env,'image':image,
              'qualification':{'path':str(qualification),'sha256':digest(qualification),'size':qualification.stat().st_size}}
    source=tmp_path/'inputs'; source.mkdir();(source/'run.sh').write_text('exit 0\n');(source/'zero-byte-header').touch()
    plan=bridge.make_plan(config,source,max_seconds=30)
    return host,config,source,plan


def test_read_only_plan_and_observed_successful_transport(tmp_path):
    host,config,source,plan=fixture(tmp_path)
    assert not (host/'calls.jsonl').exists()
    out=tmp_path/'output'; receipt=bridge.execute(plan,out)
    assert receipt['status']=='passed' and receipt['native_exit_code']==0
    assert receipt['input_files_after']==plan['input_files']
    assert receipt['cleanup']['state']=='stopped' and receipt['cleanup']['requires_recovery'] is False
    assert (out/'container-output/native.log').read_text()=='actual stand-in retained output\n'
    log=[json.loads(x) for x in (out/'container-client.jsonl').read_text().splitlines()]
    create=next(x for x in log if x['argv'][3]=='create')
    assert create['environment']==config['environment']
    assert '--network' in create['argv'] and '--pull' in create['argv']
    assert not any(x in create['argv'] for x in ('--volume','--mount','--privileged','--rm'))
    assert receipt['physics_validated'] is False
    assert bridge.verify_receipt(receipt,plan,out)['observed_exit_code']==0
    with pytest.raises(ValueError,match='earlier owned'):
        bridge.execute(plan,out)


@pytest.mark.parametrize('defect',['command','environment','inspect','output','input','missing_call'])
def test_retained_transport_cannot_rehash_wrong_process_or_source_facts(tmp_path,defect):
    _,_,source,plan=fixture(tmp_path);out=tmp_path/'output';receipt=bridge.execute(plan,out)
    journal=out/'container-client.jsonl';rows=[json.loads(line) for line in journal.read_text().splitlines()]
    if defect=='command':rows[3]['argv'].append('--volume=/unapproved')
    elif defect=='environment':rows[3]['environment']['UNAPPROVED']='yes'
    elif defect=='inspect':rows[5]['stdout_base64']='W10='
    elif defect=='missing_call':rows.pop()
    elif defect=='output':(out/'container-output/native.log').write_text('altered output')
    elif defect=='input':(source/'run.sh').write_text('altered input')
    journal.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    with pytest.raises(ValueError):bridge.verify_receipt(receipt,plan,out)


def test_native_failure_retains_output_and_observed_cleanup(tmp_path):
    host,_,_,plan=fixture(tmp_path);(host/'mode').write_text('fail')
    out=tmp_path/'output'
    with pytest.raises(RuntimeError,match='native job'):
        bridge.execute(plan,out)
    receipt=json.loads((out/'container-receipt.json').read_text())
    assert receipt['status']=='failed' and receipt['native_exit_code']==2
    assert receipt['cleanup']['requires_recovery'] is False
    assert receipt['output_files']['native.log']['size']>0


def test_independent_outer_observation_preserves_worker_receipt_and_recovers_despite_changed_science_inputs(tmp_path):
    _,config,_,plan=fixture(tmp_path);out=tmp_path/'output';receipt=bridge.execute(plan,out)
    original=(out/'container-client.jsonl').read_bytes()
    report=tmp_path/'outer-observation';observed=bridge.recover(plan,out,journal_directory=report)
    assert observed['requires_recovery'] is False and observed['after']['State']['Pid']==0
    assert (out/'container-client.jsonl').read_bytes()==original
    assert bridge.verify_receipt(receipt,plan,out)['status']=='passed'
    Path(config['qualification']['path']).write_text('changed mutable science input')
    observed=bridge.recover(plan,out,journal_directory=tmp_path/'outer-recovery')
    assert observed['requires_recovery'] is False
    with pytest.raises(ValueError,match='support file'):
        bridge.execute(plan,tmp_path/'new-output')


def test_changed_source_and_unqualified_image_refused_before_any_process(tmp_path):
    host,config,source,plan=fixture(tmp_path)
    (source/'run.sh').write_text('changed\n')
    with pytest.raises(ValueError,match='inputs changed'): bridge.execute(plan,tmp_path/'output')
    assert not (host/'calls.jsonl').exists()
    config['image']['reference']='example/analysisbase:latest'
    with pytest.raises(ValueError,match='immutable'): bridge.make_plan(config,source,max_seconds=30)
    assert not (host/'calls.jsonl').exists()


def test_symlink_transfer_rejected(tmp_path):
    host,_,source,_=fixture(tmp_path)
    (source/'outside').symlink_to(tmp_path/'podman')
    with pytest.raises(ValueError,match='symlink'): bridge.tree_facts(source)
    assert not (host/'calls.jsonl').exists()


def test_outer_recovery_after_worker_group_kill_ignores_mutable_journal(tmp_path):
    host,_,_,plan=fixture(tmp_path);(host/'mode').write_text('hang')
    out=tmp_path/'output';planfile=tmp_path/'plan.json';planfile.write_text(json.dumps(plan))
    code='import json,sys;from ravel.physics.simpleanalysis_container import execute;execute(json.load(open(sys.argv[1])),sys.argv[2])'
    env=dict(os.environ);env['PYTHONPATH']=str(Path(bridge.__file__).resolve().parents[2]);env['PYTHONDONTWRITEBYTECODE']='1'
    proc=subprocess.Popen([sys.executable,'-c',code,str(planfile),str(out)],env=env,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if (host/'state.json').exists() and json.loads((host/'state.json').read_text())['State']['Running']:break
            if proc.poll() is not None:pytest.fail(proc.communicate()[1].decode())
            time.sleep(.02)
        else:pytest.fail('stand-in container did not start')
        os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
        assert json.loads((host/'state.json').read_text())['State']['Running'] is True
        # A forged worker CID/command cannot redirect outer cleanup.
        (out/'container-resource.json').write_text(json.dumps({'job_name':'unrelated','container_id':'d'*64,'command':['destroy','everything']}))
        result=bridge.recover(plan,out)
        assert result['state']=='stopped' and result['requires_recovery'] is False
        assert result['after']['State']['Pid']==0
    finally:
        if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)


def test_cleanup_does_not_stop_container_with_wrong_ownership_labels(tmp_path):
    host,_,_,plan=fixture(tmp_path);out=tmp_path/'output';bridge.execute(plan,out)
    state=json.loads((host/'state.json').read_text());state['State'].update(Running=True,Pid=4321)
    state['Config']['Labels']['org.ravel.plan']='f'*64;(host/'state.json').write_text(json.dumps(state))
    result=bridge.recover(plan,out)
    assert result['requires_recovery'] is True
    assert json.loads((host/'state.json').read_text())['State']['Running'] is True


def test_native_listing_binds_exact_positive_compile_source_denominator(tmp_path):
    from ravel import analysis_sources
    source=tmp_path/'source';source.mkdir()
    (source/'a.cxx').write_text('DefineAnalysis(RealAnalysis)\n// DefineAnalysis(CommentOnly)\nconst char* s="DefineAnalysis(StringOnly)";\n')
    (source/'b.h').write_text('#define DefineAnalysis(HEADER_MACRO) ignored\n')
    capsule={'schema_version':1,'kind':'analysis-source-capsule','framework':'simpleanalysis','routine':'RealAnalysis',
        'source':{'repository':'supplied','revision':None,'description':'explicit source registration control'},'root':str(source),
        'files':[{'path':p.name,'sha256':digest(p),'role':'compile' if p.suffix=='.cxx' else 'header'} for p in source.iterdir()],
        'layout':{'include_dirs':[],'asset_dirs':[]},'submodules':[], 'dependencies':[],
        'dependency_review':{'complete':True,'description':'explicit miniature control, no ATLAS runtime claim'}}
    analysis_sources.validate_capsule(capsule)
    bindings=bridge.routine_bindings(capsule,tmp_path,['a.cxx'])
    assert set(bindings)=={'RealAnalysis'}
    assert bridge.verify_listing(b'Select analyses among:\n RealAnalysis\n',bindings)==['RealAnalysis']
    for data in ('Select analyses among:\n RealAnalysis\n Extra\n',
                 'Select analyses among:\n RealAnalysis\n RealAnalysis\n',
                 'RealAnalysis\n'):
        with pytest.raises(ValueError):bridge.verify_listing(data,bindings)
