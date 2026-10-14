"""Portable supplied-source/transport controls. The native producer is mocked."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from types import SimpleNamespace

import pytest
from ravel.physics import retained_shower as adapter, native_event_io, lhe_provenance
from ravel.workflow import science

SCHEMA = json.loads((Path(__file__).resolve().parents[1]/'fixtures/initialized-settings.schema.json').read_text())


def example(schema):
    if 'const' in schema:
        return schema['const']
    if 'allOf' in schema:
        value = {}
        for item in schema['allOf']:
            candidate = example(item)
            if isinstance(candidate, dict):
                value.update(candidate)
        return value
    if 'oneOf' in schema:
        return example(schema['oneOf'][0])
    typ = schema.get('type')
    if isinstance(typ, list):
        typ = typ[0]
    if typ == 'object' or 'properties' in schema:
        return {key: example(value) for key, value in schema.get('properties', {}).items()}
    if typ == 'array':
        return [example(item) for item in schema.get('prefixItems', [])] or [example(schema['items']) for _ in range(schema.get('minItems', 0))]
    if typ in ('integer', 'number'):
        return schema.get('minimum', 0)
    if typ == 'null':
        return None
    if typ == 'boolean':
        return False
    return 'fixture'


def snapshot(command):
    value = example(SCHEMA)
    value['request'] = {'config_path': command[1], 'count_override': command[3], 'argv': command}
    value['producer'].update(pid=123, compiled_source_path='fixture-wrapper.cc')
    for settings in (value['pre_init_settings'], value['post_init_settings']):
        settings['flags'].update({'PartonLevel:MPI': True, 'SLHA:useDecayTable': True, 'Random:setSeed': True})
        settings['modes'].update({'Tune:pp': 14, 'SLHA:readFrom': 1, 'Beams:frameType': 4, 'Random:seed': 83091})
        settings['words'].update({'Beams:LHEF': str(Path(command[1]).parent/'input.lhe'), 'SLHA:file': 'void'})
    return value


def payloads():
    events = [{'header': [3, 1, weight, 91.+i, .007, .12], 'particles': [
        [1,-1,0,0,501,0,0.,0.,100.,100.,0.,0.,9.],
        [-1,-1,0,0,0,501,-0.,0.,-100.,100.,0.,0.,9.],
        [21,1,1,2,501,502,10.+i,0.,0.,10.+i,0.,0.,9.]]} for i,weight in enumerate([1.,-2.])]
    lines = ['<LesHouchesEvents version="1.0">','<init>',
             '2212 2212 6500 6500 0 0 0 0 -4 1', '1 0 1 1', '</init>']
    for event in events:
        lines.extend(['<event>', ' '.join(map(str,event['header'])), *[' '.join(map(str,row)) for row in event['particles']], '</event>'])
    lhe = ('\n'.join(lines)+'\n</LesHouchesEvents>\n').encode()
    rows = [dict(type='begin',schema_version=1,requested_events=2,floating_precision=17,source='existing_Pythia_getLHAupPtr'),
            *[dict(type='event',loop_index=i,successful_index=i,hepmc_event_number=i,**event) for i,event in enumerate(events)],
            dict(type='end',events_written=2,attempted=2,next_failures=0,complete=True)]
    sidecar = ('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
    hepmc = b'HepMC::Version 3.03.01\nHepMC::Asciiv3-START_EVENT_LISTING\nW Weight\nE 0 1 1\nU GEV MM\nP 1 0 21 1 0 0 1 0 1\nE 1 1 1\nU GEV MM\nP 1 0 21 2 0 0 2 0 1\nHepMC::Asciiv3-END_EVENT_LISTING\n'
    return lhe, sidecar, hepmc


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False)+'\n')


def fixture(tmp_path, encoding='gzip'):
    tmp_path = tmp_path.resolve()
    lhe, _, _ = payloads()
    (tmp_path/'input.lhe').write_bytes(lhe)
    (tmp_path/'wrapper.cc').write_text('synthetic wrapper source; no native compilation\n')
    (tmp_path/'binary').write_text('synthetic binary bytes; native launch is mocked\n')
    (tmp_path/'binary').chmod(0o755)
    (tmp_path/'run.dat').write_text('2 = nevents\n0 = ickkw\nFalse = use_syst\n')
    (tmp_path/'card.cfg').write_text(f'Beams:frameType = 4\nBeams:LHEF = {tmp_path/"input.lhe"}\nMain:numberOfEvents = 2\nJetMatching:merge = off\nRandom:setSeed = on\nRandom:seed = 83091\n')
    (tmp_path/'schema.json').write_bytes((Path(__file__).resolve().parents[1]/'fixtures/initialized-settings.schema.json').read_bytes())
    (tmp_path/'producer-evidence.json').write_text('{"kind":"explicit synthetic producer evidence, not a qualification"}\n')
    runtime_pin = lhe_provenance.pin(tmp_path/'binary')
    write_json(tmp_path/'runtime.json', {'schema_version':1,'files':[{'path':runtime_pin['path'],'sha256':runtime_pin['sha256']}]})
    paths = {'binary':'binary','wrapper_source':'wrapper.cc','lhe':'input.lhe','run_card':'run.dat','shower_card':'card.cfg',
             'settings_schema':'schema.json','producer_evidence':'producer-evidence.json','runtime_inventory':'runtime.json'}
    pins = [dict(id=key,path=str(tmp_path/name),sha256=hashlib.sha256((tmp_path/name).read_bytes()).hexdigest(),size=(tmp_path/name).stat().st_size) for key,name in paths.items()]
    value = {'schema_version':1,'kind':'retained-shower-contract','scope':adapter.SCOPE,'sources':pins,
        'roles':{key:key for key in paths if key!='runtime_inventory'},'runtime_inventory':'runtime_inventory',
        'producer':{'binary_sha256':pins[0]['sha256'],'wrapper_source_sha256':pins[1]['sha256'],
            'compiled_source_path':'fixture-wrapper.cc','compiled_header_version_integer':8312,
            'qualification_status':'supplied_evidence_requires_scope_review'},
        'environment':{key:'1' for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']},
        'resources':{'events':2,'workers':1,'attempts':1,'builds':0,'generation':0,'analyses':0,'max_seconds':60,
                     'retained_bytes':1000000,'free_floor_bytes':0,'storage_guard':'pre_and_post_checks_not_quota'},
        'encoding':encoding,'post_init_expectations':{'flags':{'PartonLevel:MPI':True,'SLHA:useDecayTable':True,'Random:setSeed':True},
            'modes':{'Tune:pp':14,'SLHA:readFrom':1,'Beams:frameType':4,'Random:seed':83091},'parms':{},
            'words':{'Beams:LHEF':str(tmp_path/'input.lhe'),'SLHA:file':'void'}},'platform':platform.platform(),
        'assumptions':['synthetic supplied producer','complete signed source cohort','transport does not qualify physics']}
    path=tmp_path/'contract.json';write_json(path,value)
    return {'input':str(path),'contract_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},value


def mocked_producer(monkeypatch, mutation=None):
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        _, sidecar, hepmc=payloads()
        Path(command[2]).write_bytes(hepmc)
        Path(command[5]).write_bytes(sidecar)
        if '--initialized-settings' in command:
            destination=Path(command[command.index('--initialized-settings')+1])
            value=snapshot(command)
            if mutation:
                mutation(value, destination)
            else:
                write_json(destination,value)
        return subprocess.CompletedProcess(command,0)
    # Mock only this module's native invocation; do not replace shared subprocess.run.
    # The real renderer may separately inspect fonts through the standard library.
    monkeypatch.setattr(native_event_io,'subprocess',SimpleNamespace(run=run))
    return calls


@pytest.mark.parametrize('encoding',['plain','gzip'])
def test_real_adapter_complete_signed_transport_and_initialization(tmp_path,monkeypatch,encoding):
    task,_=fixture(tmp_path,encoding)
    for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:monkeypatch.setenv(key,'1')
    calls=mocked_producer(monkeypatch)
    result=adapter.run(task,tmp_path,tmp_path/'result')
    assert len(calls)==1 and result['status']=='passed' and result['physics_validated'] is False
    assert result['events']==2 and result['initialized_settings']['event_generation_complete'] is False
    report=json.loads((tmp_path/'result/transport-verification.json').read_text())
    assert report['joined_events']==2 and report['negative_original_weights']==1
    assert report['initialized_settings']==lhe_provenance.pin(tmp_path/'result/initialized-settings.json')
    if encoding=='gzip':assert gzip.decompress((tmp_path/'result/events.hepmc.gz').read_bytes())==payloads()[2]
    with pytest.raises(ValueError,match='fresh'):adapter.run(task,tmp_path,tmp_path/'result')


@pytest.mark.parametrize('bad',['unknown','count_bool','many_workers','extra_roles','wrong_hash','environment','unobserved_expectation','settings_type','lhe_expectation'])
def test_prospective_adverse_contract_or_environment_refuses_before_native(tmp_path,monkeypatch,bad):
    task,value=fixture(tmp_path)
    calls=mocked_producer(monkeypatch)
    if bad=='unknown':value['unexpected']=1
    elif bad=='count_bool':value['resources']['events']=True
    elif bad=='many_workers':value['resources']['workers']=2
    elif bad=='extra_roles':value['roles']['extra']='binary'
    elif bad=='wrong_hash':value['sources'][0]['sha256']='0'*64
    elif bad=='unobserved_expectation':value['post_init_expectations']['flags']['Unknown:setting']=True
    elif bad=='settings_type':value['post_init_expectations']['modes']['Tune:pp']=True
    elif bad=='lhe_expectation':value['post_init_expectations']['words']['Beams:LHEF']='wrong.lhe'
    else:monkeypatch.setenv('OMP_NUM_THREADS','2')
    write_json(Path(task['input']),value);task['contract_sha256']=hashlib.sha256(Path(task['input']).read_bytes()).hexdigest()
    with pytest.raises(Exception):adapter.run(task,tmp_path,tmp_path/'result')
    assert not calls


@pytest.mark.parametrize('bad',['missing','partial','duplicate','nonfinite','incomplete','completion','request','oversize'])
def test_optional_snapshot_publication_refusals_keep_partial_source_evidence(tmp_path,monkeypatch,bad):
    task,value=fixture(tmp_path)
    for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:monkeypatch.setenv(key,'1')
    def mutation(snapshot,destination):
        if bad=='missing':return
        if bad=='partial':destination.write_text('{');return
        if bad=='duplicate':destination.write_text('{"schema_version":1,"schema_version":1}');return
        if bad=='nonfinite':destination.write_text('{"x":NaN}');return
        if bad=='oversize':destination.write_text(' '*1024**2+'x');return
        if bad=='incomplete':snapshot['snapshot_complete']=False
        elif bad=='completion':snapshot['event_generation_complete']=True
        elif bad=='request':snapshot['request']['count_override']='1'
        write_json(destination,snapshot)
    mocked_producer(monkeypatch,mutation)
    with pytest.raises(Exception):adapter.run(task,tmp_path,tmp_path/'result')
    assert not (tmp_path/'result/transport-verification.json').exists()
    assert list((tmp_path/'result').glob('.original-lha-*'))


@pytest.mark.parametrize('bad',['channel_count','channel_order','ids','finite','source','rng','post_init'])
def test_complete_snapshot_downstream_refuses_semantics_after_schema(tmp_path,monkeypatch,bad):
    task,contract=fixture(tmp_path)
    command=['binary',str(tmp_path.resolve()/'card.cfg'),'events','2','--lhe-sidecar','sidecar','--initialized-settings','snapshot']
    value=snapshot(command)
    if bad=='channel_count':value['post_init_particles'][0]['channel_count']=1
    elif bad=='channel_order':value['post_init_particles'][0].update(channel_count=1,channels=[dict(index=1,on_mode=1,branching_ratio=1.,me_mode=0,products=[1000022,11])])
    elif bad=='ids':value['post_init_particles'][0]['pdg_id']=1000013
    elif bad=='finite':value['post_init_particles'][0]['m0_GeV']=float('inf')
    elif bad=='source':value['producer']['compiled_source_path']='unbound.cc'
    elif bad=='rng':value['internal_rng']['unchanged_by_snapshot']=False
    else:value['post_init_settings']['flags']['PartonLevel:MPI']=False
    with pytest.raises(Exception):adapter.verify_initialized(value,SCHEMA,contract,card=tmp_path.resolve()/'card.cfg',events=2,expected_argv=command)


def test_public_route_v2_obligation_and_real_adapter_resolution(tmp_path):
    task,_=fixture(tmp_path)
    spec={'schema_version':1,'mode':'retained-shower','task':task,'source':'synthetic','assumptions':['supplied'],'max_seconds':60,'approval_mode':'scripted_yes'}
    assert science.adapter(spec) is adapter and science._new_capability(spec) is True
    with pytest.raises(ValueError,match='prospective|version|schema'):
        path=tmp_path/'v1-spec.json';write_json(path,spec)
        science.plan(tmp_path/'forbidden-run',path)


def test_legacy_optional_absence_keeps_original_command(tmp_path,monkeypatch):
    task,c=fixture(tmp_path)
    roles={name:Path(next(r['path'] for r in c['sources'] if r['id']==ident)) for name,ident in c['roles'].items()}
    calls=mocked_producer(monkeypatch)
    native_event_io.shower_original(roles['binary'],roles['shower_card'],tmp_path/'legacy.hepmc',2,lhe=roles['lhe'],
        sidecar=tmp_path/'legacy-sidecar.jsonl',verification=tmp_path/'legacy-verification.json',
        wrapper_source=roles['wrapper_source'],run_card=roles['run_card'])
    assert len(calls[0])==6 and '--initialized-settings' not in calls[0]
    assert 'initialized_settings' not in json.loads((tmp_path/'legacy-verification.json').read_text())


def spec2(task):
    return {'schema_version':2,'mode':'retained-shower','task':task,'source':'Portable complete signed cohort control',
        'assumptions':['Native producer is explicitly mocked; no physics or binary qualification'],
        'max_seconds':60,'max_attempts':1,'approval_mode':'scripted_yes','review_policy':{
            'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'producer','executor':'executor',
                'physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},
                'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
                'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'transport','kind':'scientific'}],
                'claim_scopes':{'supplied_transport':{'checks':['integrity','transport'],'actions':['delivery','reuse']}}},
            'correction_contract':{'task_fields':[],'input_slots':[]}}}


def test_real_worker_adapter_renderer_and_fresh_attempt_lifecycle(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    from ravel.workflow.state_io import read_json
    task,_=fixture(tmp_path)
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):monkeypatch.setenv(name,'1')
    calls=mocked_producer(monkeypatch)
    spec=spec2(task);rd=tmp_path/'worker';rd.mkdir()
    proposal={'base_dir':str(tmp_path.resolve()),'attempt':1,'output_directory':'outputs/attempt-1',
              'stage_binding':{'input_snapshot':{}}}
    # Only authority/spec transport and native subprocess are mocked. Adapter,
    # worker, real renderer, publication, recipe/checkin and repeat guard are real.
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal)
    monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1'
    assert len(calls)==1 and read_json(out/'result.json')==read_json(out/'retained-shower/retained-shower.json')
    assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
    assert read_json(out/'verification.json')['physics_validated'] is False
    assert read_json(out/'figures.json')['status']=='not_applicable'
    before={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
    assert before=={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}


def test_public_prospective_plan_closes_entire_supplied_graph_without_native(tmp_path,monkeypatch):
    task,c=fixture(tmp_path);calls=mocked_producer(monkeypatch)
    spec=spec2(task);p=tmp_path/'spec.json';write_json(p,spec)
    # Packet presentation only is bypassed; actual planning, source inventory,
    # stage/fingerprint/policy/checkin snapshots are constructed normally.
    monkeypatch.setattr(science,'packet',lambda *a,**k:{})
    proposal=science.plan(tmp_path/'planned',p)
    paths=set(proposal['stage_binding']['input_snapshot'])
    assert str(Path(task['input']).resolve()) in paths
    assert all(row['path'] in paths for row in c['sources'])
    checkin=json.loads((tmp_path/'planned/inputs/checkin1.json').read_text())
    assert proposal['mode']=='retained-shower' and checkin['kind']=='checkin1' and not calls


@pytest.mark.parametrize('bad',['schema_substitution','source_alias','role_alias','symlink_source','zero_schema'])
def test_closed_source_graph_and_reviewed_schema_refuse_before_dispatch(tmp_path,monkeypatch,bad):
    task,c=fixture(tmp_path);calls=mocked_producer(monkeypatch)
    if bad=='schema_substitution':
        schema=copy.deepcopy(SCHEMA);schema['properties']['snapshot_complete']={'type':'boolean'}
        write_json(tmp_path/'schema.json',schema)
        row=next(r for r in c['sources'] if r['id']=='settings_schema')
        row.update(sha256=hashlib.sha256((tmp_path/'schema.json').read_bytes()).hexdigest(),size=(tmp_path/'schema.json').stat().st_size)
    elif bad=='source_alias':
        row=next(r for r in c['sources'] if r['id']=='producer_evidence');other=c['sources'][1]
        row.update(path=other['path'],sha256=other['sha256'],size=other['size'])
    elif bad=='role_alias':c['roles']['settings_schema']='producer_evidence'
    elif bad=='symlink_source':
        p=tmp_path/'producer-evidence.json';p.rename(tmp_path/'real-evidence');p.symlink_to(tmp_path/'real-evidence')
    else:
        (tmp_path/'schema.json').write_bytes(b'')
        row=next(r for r in c['sources'] if r['id']=='settings_schema');row.update(sha256=hashlib.sha256(b'').hexdigest(),size=0)
    write_json(Path(task['input']),c);task['contract_sha256']=hashlib.sha256(Path(task['input']).read_bytes()).hexdigest()
    with pytest.raises(Exception):adapter.inputs(task,tmp_path)
    assert not calls


def test_optional_cli_argument_uses_existing_original_transport(monkeypatch):
    calls=[];monkeypatch.setattr(native_event_io,'shower_original',lambda *a,**k:calls.append((a,k)))
    argv=['shower-original','--binary','binary','--card','card','--output','events','--events','2',
          '--lhe','input','--sidecar','sidecar','--verification','report','--wrapper-source','source',
          '--run-card','run','--encoding','gzip','--initialized-settings','initialized.json']
    assert native_event_io.main(argv)==0 and len(calls)==1
    assert calls[0][1]['initialized_settings']=='initialized.json'


@pytest.mark.parametrize('existing',['input_alias','output_alias','existing','broken_symlink'])
def test_initialized_destination_alias_or_existing_refuses_before_native(tmp_path,monkeypatch,existing):
    task,c=fixture(tmp_path);calls=mocked_producer(monkeypatch)
    dest=tmp_path/'new-initialized.json'
    if existing=='input_alias':dest=tmp_path/'input.lhe'
    elif existing=='output_alias':dest=tmp_path/'events.hepmc'
    elif existing=='existing':dest.write_text('{}')
    else:dest.symlink_to(tmp_path/'absent')
    with pytest.raises(ValueError):native_event_io.shower_original(tmp_path/'binary',tmp_path/'card.cfg',tmp_path/'events.hepmc',2,
        lhe=tmp_path/'input.lhe',sidecar=tmp_path/'sidecar.jsonl',verification=tmp_path/'report.json',
        wrapper_source=tmp_path/'wrapper.cc',run_card=tmp_path/'run.dat',initialized_settings=dest)
    assert not calls


@pytest.mark.parametrize('fault',['growth','replace','same_size_write','symlink_replace'])
def test_descriptor_bounded_initialized_reader_refuses_midread_mutation(tmp_path,monkeypatch,fault):
    p=tmp_path/'initialized.json';p.write_text('{"original":1}')
    original_read=native_event_io.os.read;read_sizes=[];trigger=[False]
    def altered_read(fd,size):
        read_sizes.append(size)
        if not trigger[0]:
            trigger[0]=True
            if fault=='growth':
                with p.open('ab') as stream:stream.write(b'x'*(1024**2+100))
            elif fault=='same_size_write':p.write_text('{"original":2}')
            else:
                replacement=tmp_path/'replacement.json';replacement.write_text('{"original":1}')
                if fault=='replace':os.replace(replacement,p)
                else:p.unlink();p.symlink_to(replacement)
        return original_read(fd,size)
    monkeypatch.setattr(native_event_io.os,'read',altered_read)
    with pytest.raises(ValueError):native_event_io.read_initialized_settings(p)
    assert read_sizes and max(read_sizes)<=1024**2+1


def test_same_size_rewrite_is_refused_when_file_times_do_not_resolve_it(tmp_path,monkeypatch):
    # A filesystem whose timestamps are coarser than the rewrite reports equal
    # times before and after it; the reader must compare the bytes themselves.
    p=tmp_path/'initialized.json';p.write_text('{"original":1}')
    original_read=native_event_io.os.read;trigger=[False]
    def coarse(function):
        def observed(target,*args,**kwargs):
            value=function(target,*args,**kwargs);fields=list(value)
            return os.stat_result(fields[:7]+[0,0,0],{'st_atime_ns':0,'st_mtime_ns':0,'st_ctime_ns':0})
        return observed
    def altered_read(fd,size):
        if not trigger[0]:
            trigger[0]=True;p.write_text('{"original":2}')
        return original_read(fd,size)
    monkeypatch.setattr(native_event_io.os,'lstat',coarse(os.lstat))
    monkeypatch.setattr(native_event_io.os,'fstat',coarse(os.fstat))
    monkeypatch.setattr(native_event_io.os,'read',altered_read)
    with pytest.raises(ValueError,match='content changed'):native_event_io.read_initialized_settings(p)
    assert trigger[0]


def test_initialized_descriptor_reader_returns_exact_bytes_pin_and_strict_json(tmp_path):
    p=tmp_path/'snapshot.json';p.write_text('{"x":1}\n')
    value,pin=native_event_io.read_initialized_settings(p)
    assert value=={'x':1} and pin==lhe_provenance.pin(p)
    p.write_text('{"x":1,"x":1}')
    with pytest.raises(ValueError):native_event_io.read_initialized_settings(p)


def test_initialized_reader_open_is_nonblocking_and_leaf_nofollow(tmp_path,monkeypatch):
    p=tmp_path/'snapshot.json';p.write_text('{"x":1}')
    original_open=native_event_io.os.open;flags=[]
    def observed_open(path,value):
        flags.append(value)
        return original_open(path,value)
    monkeypatch.setattr(native_event_io.os,'open',observed_open)
    assert native_event_io.read_initialized_settings(p)[0]=={'x':1}
    assert flags and flags[0]&os.O_NONBLOCK and flags[0]&os.O_NOFOLLOW


@pytest.mark.parametrize('cap_kind',['payload_only','complete'])
def test_storage_postcondition_includes_completion_record_and_retains_failure(tmp_path,monkeypatch,cap_kind):
    task,c=fixture(tmp_path)
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):monkeypatch.setenv(name,'1')
    calls=mocked_producer(monkeypatch)
    baseline=tmp_path/'samplea';adapter.run(task,tmp_path,baseline)
    payload_bytes=sum(p.stat().st_size for p in baseline.iterdir() if p.is_file() and p.name!='retained-shower.json')
    cap=payload_bytes if cap_kind=='payload_only' else payload_bytes+(baseline/'retained-shower.json').stat().st_size+500
    c['resources']['retained_bytes']=cap
    write_json(Path(task['input']),c);task['contract_sha256']=hashlib.sha256(Path(task['input']).read_bytes()).hexdigest()
    out=tmp_path/'sampleb'
    if cap_kind=='payload_only':
        with pytest.raises(ValueError,match='post-publication storage'):adapter.run(task,tmp_path,out)
        saved=json.loads((out/'retained-shower.json').read_text())
        assert saved['status']=='failed' and saved['storage_postcondition']['completion_record_included'] is True
        assert saved['storage_postcondition']['retained_bytes_observed']>cap
        assert (out/'events.hepmc.gz').is_file() and (out/'transport-verification.json').is_file()
    else:
        result=adapter.run(task,tmp_path,out)
        assert result['status']=='passed' and sum(p.stat().st_size for p in out.iterdir() if p.is_file())<=cap
    assert len(calls)==2
