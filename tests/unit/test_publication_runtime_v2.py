"""Prospective synthetic software controls; no TeX, native loader or model calls.

V3 retains all original predicates. The original publication late-member hook
forwards the selected-policy keyword, and the intake control now supplies an
authentic task contract binding rather than its obsolete placeholder. The ordinary
qualification receipt boundary is not mocked into an actual qualification claim.
Root executes these definitions only after separate source/resource admission.
"""
from copy import deepcopy
import hashlib
import json
import os
import sys
from pathlib import Path
import pytest
from ravel.workflow import publication_runtime as pr, report_integrity as ri, state_io
from ravel.physics import manuscript_build as mb, reinterpret_db as db


LIMITS={'max_files':20000,'max_bytes':16*1024**3,'max_metadata_bytes':16*1024**2}
UUID='12345678-1234-1234-1234-123456789ABC'


def pin(path):
    raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(value if type(value) is bytes else (json.dumps(value,allow_nan=False)+'\n').encode())
    return pin(path)


def request(root):
    source=root/'source';(source/'bin').mkdir(parents=True);(source/'assets').mkdir()
    for name in ('pdftex','pdfinfo'):
        put(source/'bin'/name,b'INERT executable bytes; never run\n');(source/'bin'/name).chmod(0o755)
    (source/'bin/pdflatex').symlink_to('pdftex')
    for name in ('pdflatex.fmt','article.cls','zref-user.sty','zref-abspage.sty','geometry.sty','graphicx.sty','synthetic.tfm'):
        put(source/'assets'/name,('SYNTHETIC runtime data '+name).encode())
    put(source/'assets/libactual.dylib',b'SYNTHETIC library bytes, no ABI qualification\n')
    (source/'assets/libalias.dylib').symlink_to('libactual.dylib')
    inv=pr.source_inventory(source,root/'source-inventory.json',limits=LIMITS)
    out=root/'snapshot';snapshot=out/'runtime';assets=str(snapshot/'selected/assets');binary=str(snapshot/'selected/bin')
    basic={'PATH':binary,'TMPDIR':'{work}/tmp','LANG':'C','LC_ALL':'C',
        'DYLD_LIBRARY_PATH':assets,'DYLD_PRINT_LIBRARIES':'1','DYLD_PRINT_LIBRARIES_POST_LAUNCH':'1'}
    compiler={**basic,**{k:assets+'//' for k in ('TEXMFCNF','TEXMFROOT','TEXINPUTS','TEXFORMATS')},
        **{k:'{work}/'+k.lower() for k in ('TEXMFHOME','TEXMFVAR','TEXMFCONFIG','TEXMFOUTPUT')},
        'openin_any':'p','openout_any':'p','shell_escape':'f','MKTEXPK':'0','MKTEXTFM':'0','MKTEXFMT':'0'}
    req={'schema_version':1,'trees':[{'source_root':str(source),'destination':'selected','inventory':inv}],
         'allowed_target_roots':[],'tools':{'compiler':'selected/bin/pdflatex','pdfinfo':'selected/bin/pdfinfo','svg_converter':None},
         'environment':{'compiler':compiler,'pdfinfo':basic,'svg_converter':None},'platform':'Darwin',
         'platform_dependencies':[],'custody_limits':LIMITS}
    return put(root/'request.json',req),out,source,req


def test_alias_bytes_names_permissions_and_complete_provenance(tmp_path):
    req,out,source,_=request(tmp_path);r=pr.materialize(req,out)
    assert Path(r['compiler']['path']).name=='pdflatex'
    assert Path(r['compiler']['path']).read_bytes()==(source/'bin/pdftex').read_bytes()
    assert Path(r['compiler']['path']).stat().st_mode&0o111
    assert not any(p.is_symlink() for p in out.rglob('*'))
    doc=json.loads(Path(r['closure_manifest']['path']).read_bytes())
    leaf=doc['source_provenance'][0]['complete_source_inventory']['files']['bin/pdflatex']
    assert leaf['links'][-1]['target']=='pdftex' and leaf['source']['sha256']==r['compiler']['sha256']
    assert not doc['runtime_qualified'] and doc['qualification'] is None
    assert pr.closure_inputs(r,out,LIMITS)[0]==doc
    with pytest.raises(ValueError,match='qualification'):pr.closure_inputs(r,out,LIMITS,require_qualified=True)


@pytest.mark.parametrize('change',['cycle','dangling','escape','directory-cycle','fifo','retarget','changed-byte','new-member'])
def test_source_alias_and_complete_population_failures(tmp_path,change):
    req,out,source,original=request(tmp_path)
    if change=='cycle':(source/'bin/pdflatex').unlink();(source/'bin/pdflatex').symlink_to('pdflatex')
    if change=='dangling':(source/'bin/pdftex').unlink()
    if change=='escape':(source/'bin/pdflatex').unlink();(source/'bin/pdflatex').symlink_to('/bin/sh')
    if change=='directory-cycle':(source/'assets/loop').symlink_to(source)
    if change=='fifo':os.mkfifo(source/'fifo')
    if change=='retarget':(source/'bin/pdflatex').unlink();(source/'bin/pdflatex').symlink_to('pdfinfo')
    if change=='changed-byte':(source/'assets/synthetic.tfm').write_bytes(b'changed')
    if change=='new-member':put(source/'assets/unlisted.sty',b'new')
    with pytest.raises((ValueError,OSError)):pr.materialize(req,out)
    assert not (out/'closure-manifest.json').exists()


@pytest.mark.parametrize('change',['member','byte','mode','alias'])
def test_snapshot_complete_ending_identity_is_required(tmp_path,change):
    req,out,_,_=request(tmp_path);r=pr.materialize(req,out);q=out/'runtime/selected/assets/synthetic.tfm'
    if change=='member':put(q.parent/'extra.sty',b'extra')
    if change=='byte':q.write_bytes(b'changed')
    if change=='mode':
        # Flip one permission bit of the recorded mode. A fixed mode would equal the
        # snapshot's own mode under a restrictive process umask and change nothing.
        import stat
        before=stat.S_IMODE(q.stat().st_mode);q.chmod(before^0o100)
        assert stat.S_IMODE(q.stat().st_mode)!=before
    if change=='alias':q.unlink();q.symlink_to(q.parent/'article.cls')
    with pytest.raises(ValueError):pr.closure_inputs(r,out,LIMITS)


@pytest.mark.parametrize('count',[4097,5976])
def test_full_large_inventory_explicit_policy_and_legacy_refusal(tmp_path,count):
    source=tmp_path/'assets';source.mkdir()
    for i in range(count):(source/f'{i:05d}.sty').write_bytes(b'x')
    with pytest.raises(ValueError):pr.inventory(source,tmp_path/'legacy.json')
    r=pr.inventory(source,tmp_path/'explicit.json',limits=LIMITS)
    assert r['file_count']==count and len(json.loads((tmp_path/'explicit.json').read_bytes())['files'])==count


@pytest.mark.parametrize('field,value',[('max_files',True),('max_files',20001),('max_files',0),('max_bytes',-1),('max_bytes',16*1024**3+1),('max_metadata_bytes',16*1024**2+1)])
def test_admitted_capacity_is_finite_not_automatic_authority(field,value):
    with pytest.raises(ValueError):ri.custody_limits({**LIMITS,field:value})


def test_shared_union_cannot_reset_or_double_charge_same_member(tmp_path):
    a=put(tmp_path/'a',b'a');b=put(tmp_path/'b',b'b');limits={**LIMITS,'max_files':1}
    consumed=ri.CustodyInputs();budget=ri.CustodyAccumulator(limits)
    ri._dependency(a,tmp_path,consumed,limits=limits,accumulator=budget)
    ri._dependency(a,tmp_path,consumed,limits=limits,accumulator=budget)
    assert len(budget.members)==1
    with pytest.raises(ValueError):ri._dependency(b,tmp_path,consumed,limits=limits,accumulator=budget)


def test_operational_metadata_large_complete_but_prose_limit_unchanged(tmp_path):
    value={'inventory':'x'*(ri.MAX_BYTES+1)};p=put(tmp_path/'large.json',value)
    assert ri._operational_json(p,tmp_path,ri.CustodyInputs(),limits=LIMITS)==value
    with pytest.raises(ValueError):ri._operational_json(p,tmp_path,{})
    with pytest.raises(ValueError):ri._raw(p,tmp_path,{})


@pytest.mark.parametrize('change',['HOME','preload','trailing','empty','host','shell','package-fetch','suppressed'])
def test_closed_tool_environment_has_no_inherited_search_or_injection(tmp_path,change):
    req,out,_,_=request(tmp_path);r=pr.materialize(req,out);bad=deepcopy(r['environment']);row=bad['compiler']
    if change=='HOME':row['HOME']='/tmp'
    if change=='preload':row['DYLD_INSERT_LIBRARIES']='/tmp/evil'
    if change=='trailing':row['TEXINPUTS']+=':'
    if change=='empty':row['TEXINPUTS']=''
    if change=='host':row['TEXINPUTS']='/usr/share'
    if change=='shell':row['shell_escape']='t'
    if change=='package-fetch':row['MKTEXFMT']='1'
    if change=='suppressed':row.pop('DYLD_PRINT_LIBRARIES')
    with pytest.raises(ValueError):pr.environment_contract(bad,out/'runtime',{k:r[k] for k in ('compiler','pdfinfo','svg_converter')},'Darwin')


def test_explicit_tool_env_work_paths_and_verifier_do_not_create_missing_state(tmp_path):
    req,out,_,_=request(tmp_path);r=pr.materialize(req,out);work=tmp_path/'work';work.mkdir()
    env=pr.tool_environment(r,'compiler',work)
    assert 'HOME' not in env and 'CODEX_HOME' not in env and env['OMP_NUM_THREADS']=='1'
    assert Path(env['TMPDIR']).is_relative_to(work)
    Path(env['TMPDIR']).rmdir()
    with pytest.raises(ValueError):pr.tool_environment(r,'compiler',work,create=False)
    assert not Path(env['TMPDIR']).exists()


@pytest.mark.parametrize('change',['missing','old-format','outside','system-uuid','changed-snapshot'])
def test_real_loader_text_admission_refuses_missing_or_unbound_images(tmp_path,change):
    req,out,_,_=request(tmp_path);r=pr.materialize(req,out);snapshot=json.loads(Path(r['closure_manifest']['path']).read_bytes())
    text=f"dyld[17]: <{UUID}> {r['compiler']['path']}\n";system=[]
    if change=='missing':text='ordinary stderr with no loader output\n'
    if change=='old-format':text=f"dyld[17]: loaded {r['compiler']['path']}\n"
    if change=='outside':text+=f'dyld[17]: <{UUID}> /private/unlisted.dylib\n'
    if change=='system-uuid':text+=f'dyld[17]: <{UUID}> /usr/lib/libSystem.B.dylib\n';system=[{'kind':'system-image','path':'/usr/lib/libSystem.B.dylib','uuid':'00000000-0000-0000-0000-000000000000'}]
    if change=='changed-snapshot':Path(r['compiler']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):pr.observed_images(text,pid=17,snapshot=snapshot,platform_dependencies=system)


def test_system_image_uuid_is_not_a_fabricated_regular_file_pin(tmp_path):
    req,out,_,_=request(tmp_path);r=pr.materialize(req,out);snapshot=json.loads(Path(r['closure_manifest']['path']).read_bytes())
    system=[{'kind':'system-image','path':'/usr/lib/libSystem.B.dylib','uuid':UUID}]
    images=pr.observed_images(f'dyld[7]: <{UUID}> /usr/lib/libSystem.B.dylib\n',pid=7,snapshot=snapshot,platform_dependencies=system)
    assert images==[{'path':'/usr/lib/libSystem.B.dylib','uuid':UUID,'kind':'declared-system-image'}]


def test_success_boolean_without_ordinary_receipt_is_not_qualification(tmp_path):
    req,out,_,_=request(tmp_path);r=pr.materialize(req,out)
    with pytest.raises(ValueError):pr.qualify(r['closure_manifest'],{'compiler':{'success':True},'pdfinfo':{'success':True}},tmp_path/'qualified.json')
    assert not (tmp_path/'qualified.json').exists()


def test_source_changed_during_captured_copy_cannot_be_rebased(tmp_path,monkeypatch):
    req,out,source,_=request(tmp_path);original=os.open;affected=source/'bin/pdftex';fired=False
    def changed(p,*args,**kwargs):
        nonlocal fired
        if Path(p)==affected and out.exists() and not fired:
            fired=True;affected.write_bytes(b'altered')
        return original(p,*args,**kwargs)
    monkeypatch.setattr(os,'open',changed)
    with pytest.raises(ValueError):pr.materialize(req,out)
    assert fired and not (out/'closure-manifest.json').exists()


def test_ending_source_link_retarget_refuses_even_when_same_bytes(tmp_path,monkeypatch):
    req,out,source,_=request(tmp_path);original=pr._emit;fired=False
    def retarget(path,document,maximum,*,compact=False):
        nonlocal fired
        result=original(path,document,maximum,compact=compact)
        if path.name=='closure-manifest.json':
            fired=True;(source/'bin/pdflatex').unlink();(source/'bin/pdflatex').symlink_to('pdfinfo')
        return result
    monkeypatch.setattr(pr,'_emit',retarget)
    with pytest.raises(ValueError):pr.materialize(req,out)
    assert fired and (out/'closure-manifest.json').exists() # Failed intent remains, never returned qualified.


def test_unqualified_v2_ordinary_build_refuses_before_any_native_effect(tmp_path,monkeypatch):
    from test_manuscript_build import fixture
    task,c,p=fixture(tmp_path,monkeypatch)
    req,out,source,_=request(tmp_path/'selected')
    rt=pr.materialize(req,out)
    c.update({'schema_version':2,'custody_limits':LIMITS})
    c['runtime']={k:rt[k] for k in ('compiler','pdfinfo','svg_converter','asset_trees','environment','closure_manifest','snapshot_root','platform')}
    c['runtime'].update({'schema_version':2,'purpose':'qualified','engine':'pdflatex','max_ram_mib':512})
    put(Path(task['config']),c)
    assert set(mb.inputs(task,tmp_path))>={Path(rt['compiler']['path']),Path(rt['closure_manifest']['path'])}
    monkeypatch.setattr(mb,'_approved',lambda *a,**k:{'max_seconds':30}) # Only isolate runtime gate, never actual approval.
    monkeypatch.setattr(db,'execute_native',lambda *a,**k:pytest.fail('unqualified native dispatch'))
    with pytest.raises(ValueError,match='qualification'):mb.run(task,tmp_path,tmp_path/'not-run')
    assert not (tmp_path/'not-run').exists()


def test_operational_writer_intent_before_emission_and_shared_policy(tmp_path,monkeypatch):
    path=tmp_path/'complete.json';document={'full':list(range(6000))};consumed=ri.CustodyInputs();budget=ri.CustodyAccumulator(LIMITS)
    intended=ri._operational_new(path,document,limits=LIMITS,consumed=consumed,accumulator=budget)
    assert ri._operational_json(intended,tmp_path,consumed,limits=LIMITS,accumulator=budget)==document
    assert len(budget.members)==1
    with pytest.raises(ValueError,match='policy'):
        ri._dependency(intended,tmp_path,consumed,limits=None,accumulator=budget)
    real=state_io.atomic_json
    def changed(p,d):
        real(p,d);p.write_text('{"different":true}\n')
    monkeypatch.setattr(state_io,'atomic_json',changed)
    with pytest.raises(ValueError,match='changed'):ri._operational_new(tmp_path/'bad.json',document,limits=LIMITS)
    assert (tmp_path/'bad.json').exists()


@pytest.mark.parametrize('explicit',[False,True])
def test_existing_supervisor_exact_environment_receipt_without_process(tmp_path,monkeypatch,explicit):
    captured={};signals=[]
    class InertProcess:
        pid=987654321;returncode=0
        def __init__(self,command,**kwargs):captured.update(kwargs);captured['command']=command
        def poll(self):return 0
    monkeypatch.setattr(db.subprocess,'Popen',InertProcess)
    monkeypatch.setattr(db.os,'killpg',lambda pid,sig:signals.append((pid,sig)))
    monkeypatch.setenv('RAVEL_SYNTHETIC_INHERITANCE','not-a-secret')
    selected={'PATH':'/synthetic-only','LANG':'C'} if explicit else None
    result=db.execute_native(['/never-run'],tmp_path,{'max_ram_mib':16,'max_seconds':1},environment=selected)
    assert signals and all(pid==InertProcess.pid for pid,_ in signals)
    assert captured['start_new_session'] is True and captured['command']==['/never-run']
    assert captured['env']['OMP_NUM_THREADS']=='1'
    if explicit:
        assert captured['env']=={**selected,**pr._THREADS}
        assert result['effective_environment']==captured['env'] and result['environment_mode']=='explicit'
        assert result['pid']==InertProcess.pid and result['working_directory']==str(tmp_path.absolute())
        assert 'HOME' not in captured['env'] and 'RAVEL_SYNTHETIC_INHERITANCE' not in captured['env']
    else:assert captured['env']['RAVEL_SYNTHETIC_INHERITANCE']=='not-a-secret' and 'effective_environment' not in result
    assert json.loads((tmp_path/'native-execution.json').read_text())==result


def qualification_fixture(root,monkeypatch):
    """Real build/execution-custody APIs; explicitly inert native and approval seams.

    No process/native tool is executed. Synthetic loader/recorder bytes exercise
    consumers and must never be reported as actual platform qualification.
    """
    from test_manuscript_build import fixture,absolute_aux
    from ravel.workflow import execution,science
    task,c,_=fixture(root,monkeypatch);req,out,_,_=request(root/'selected');rt=pr.materialize(req,out)
    c.update({'schema_version':2,'custody_limits':LIMITS})
    c['runtime']={k:rt[k] for k in ('compiler','pdfinfo','svg_converter','asset_trees','environment','closure_manifest','snapshot_root','platform')}
    c['runtime'].update({'schema_version':2,'purpose':'qualification','engine':'pdflatex','max_ram_mib':512});put(Path(task['config']),c)
    monkeypatch.setattr(science,'execution_spec',lambda *a,**k:{'schema_version':2,'mode':'manuscript-build','task':deepcopy(task)}) # Explicit inert ordinary-spec fixture, not actual authority.
    calls=[];monkeypatch.setattr(mb,'_approved',lambda *a,**k:{'max_seconds':30})
    def native(argv,work,document,*,environment):
        work=Path(work);calls.append(deepcopy(argv));pid=7000+len(calls)
        receipt={'command':deepcopy(argv),'returncode':0,'resource_violation':None,'environment_mode':'explicit',
            'effective_environment':deepcopy(environment),'pid':pid,'working_directory':str(work.absolute())}
        (work/'native-stdout.log').write_text('Pages: 15\n' if Path(argv[0]).name=='pdfinfo' else 'Synthetic inert compiler\n')
        (work/'native-stderr.log').write_text(f'dyld[{pid}]: <{UUID}> {argv[0]}\n')
        put(work/'native-execution.json',receipt);put(work/'native-process.json',{'pid':pid,'synthetic':True})
        if Path(argv[0]).name=='pdflatex':
            (work/'note.pdf').write_bytes(b'%PDF-SYNTHETIC-NOT-NATIVE-QUALIFICATION\n')
            aux=absolute_aux()+''.join(r'\zref@newlabel{'+k+r'}{\abspage{'+str(v)+'}}\n' for k,v in [('main-start',1),('main-end',10),('refs-start',11),('refs-end',15)])
            (work/'note.aux').write_text(aux.replace('\\n','\n'));(work/'note.log').write_text('Synthetic only\n')
            fmt=Path(rt['snapshot_root'])/'selected/assets/pdflatex.fmt'
            (work/'note.fls').write_text('INPUT '+str(work/'note.tex')+'\nINPUT '+str(fmt)+'\n')
        return receipt
    monkeypatch.setattr(db,'execute_native',native)
    rd=root/'ordinary-custody';rd.mkdir();output=rd/'outputs';output.mkdir();build=output/'build'
    paths=mb.inputs(task,root)
    declaration=execution.plan_stage(rd,'capability',[sys.executable,'-c','pass'],[str(p) for p in paths],[str(output)],[],str(rd))
    record=execution.begin_attempt(rd,'capability',declaration,'logs/supervisor.log')
    result=mb.run(task,root,build);(rd/'logs/supervisor.log').write_text('Synthetic inert execution-custody control; no process launched.\n')
    execution.finish_attempt(rd,record,0);record=execution.load_execution(rd)['stages']['capability']
    receipt=pin(execution.resolve_path(rd,record['attempt_record']))
    observations={k:{'rundir':str(rd),'receipt':receipt,'observation':p} for k,p in result['qualification_observations'].items()}
    return task,c,rt,result,observations,calls,rd


def test_same_builder_qualification_then_qualified_build_interface(tmp_path,monkeypatch):
    task,c,rt,result,observations,calls,rd=qualification_fixture(tmp_path,monkeypatch)
    assert len(calls)==3 and result['runtime_purpose']=='qualification' and result['runtime_qualified'] is False
    assert not result['scientific_acceptance'] and not result['parent_task_accepted']
    qualified=pr.qualify(rt['closure_manifest'],observations,tmp_path/'qualified.json')
    c['runtime'].update({'purpose':'qualified','closure_manifest':qualified})
    task={'config':put(tmp_path/'qualified-build-config.json',c)['path']} # Never rewrite the qualification attempt's original config.
    assert pr.closure_inputs(c['runtime'],tmp_path,LIMITS,require_qualified=True)[0]['runtime_qualified'] is True
    second=mb.run(task,tmp_path,tmp_path/'qualified-build')
    assert len(calls)==6 and second['runtime_purpose']=='qualified' and second['runtime_qualified'] is True
    assert not second['scientific_acceptance'] and not second['visual_style_accepted']


@pytest.mark.parametrize('change',['failed','replay','source','environment','loader','recorder'])
def test_qualification_requires_current_complete_original_attempt(tmp_path,monkeypatch,change):
    from ravel.workflow import execution
    task,c,rt,result,observations,calls,rd=qualification_fixture(tmp_path,monkeypatch)
    if change=='failed':
        state=execution.load_execution(rd);state['stages']['capability']['status']='FAILED';state_io.atomic_json(rd/execution.STATE_NAME,state)
    if change=='replay':observations['compiler']['rundir']=str(tmp_path/'unrelated')
    if change=='source':Path(rt['compiler']['path']).write_bytes(b'changed')
    if change=='environment':
        q=Path(observations['compiler']['observation']['path']);d=json.loads(q.read_text());p=Path(d['native_execution']['path']);x=json.loads(p.read_text());x['effective_environment']['PATH']='/unlisted';put(p,x)
    if change in {'loader','recorder'}:
        q=Path(observations['compiler']['observation']['path']);d=json.loads(q.read_text());Path(d['stderr' if change=='loader' else 'tex_recorder']['path']).write_text('missing original evidence\n')
    with pytest.raises((ValueError,OSError,KeyError)):pr.qualify(rt['closure_manifest'],observations,tmp_path/'refused.json')
    assert not (tmp_path/'refused.json').exists()


def test_qualification_output_is_never_final_delivery(tmp_path,monkeypatch):
    from ravel.workflow import science
    task,c,rt,result,observations,calls,rd=qualification_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(science,'execution_spec',lambda *a,**k:{'schema_version':2,'mode':'manuscript-build','task':task})
    binding={'rundir':str(rd),'receipt':observations['compiler']['receipt'],'result':pin(rd/'outputs/build/manuscript-build.json')}
    with pytest.raises(ValueError,match='qualification-purpose'):mb.verified_result(binding,base_dir=tmp_path)
    assert len(calls)==3


def test_public_prepare_build_emits_v2_policy_and_real_intake_population(tmp_path,monkeypatch):
    from test_manuscript_build import fixture
    from ravel.workflow import science,manuscript_production as mp,route_prompt,task_completion as tc
    task,c,_=fixture(tmp_path,monkeypatch);req,out,_,_=request(tmp_path/'selected');rt=pr.materialize(req,out)
    runtime={k:rt[k] for k in ('compiler','pdfinfo','svg_converter','asset_trees','environment','closure_manifest','snapshot_root','platform')}
    runtime.update({'schema_version':2,'purpose':'qualification','engine':'pdflatex','max_ram_mib':512})
    prompt='Prepare a source-bound synthetic manuscript build plan only; do not run a compiler or infer any physics acceptance.'
    contract=route_prompt.route(prompt);requirements=tc.initial_requirements(prompt)
    requirements['assignments']=[{'id':'publication-build','purpose':'Bind the complete original synthetic preparation request.',
        'coverage':[{'obligation_id':row['id'],'criteria':deepcopy(row['criteria'])} for row in requirements['obligations']]}]
    contract['task_requirements']=requirements
    goal={'contract':put(tmp_path/'parent/inputs/task_contract.json',contract),'assignment_id':'publication-build'}
    assert tc.binding_projection(goal,base_dir=tmp_path)['original_request']==prompt
    captured={}
    def plan_boundary(rd,specpath):
        spec=json.loads(Path(specpath).read_text());captured.update({'spec':spec,'paths':science.task_inputs(spec,Path(specpath).parent)})
        return {'fixture':'read-only real task_inputs; no approval or native execution'}
    monkeypatch.setattr(science,'plan',plan_boundary)
    prepared=mp.prepare_build(c['package'],tmp_path/'prepared',base_dir=tmp_path,runtime=runtime,
        review_policy={'fixture':'not-an-approval'},goal_binding=goal,max_seconds=30,custody_limits=LIMITS)
    config=json.loads((tmp_path/'prepared/build-config.json').read_text())
    assert config['schema_version']==2 and config['custody_limits']==LIMITS and config['runtime']['purpose']=='qualification'
    assert Path(rt['closure_manifest']['path']) in captured['paths'] and Path(rt['compiler']['path']) in captured['paths']
    assert captured['spec']['max_seconds']==30 and not prepared['execution_authorized']
    assert not prepared['scientific_acceptance']
