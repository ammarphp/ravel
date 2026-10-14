"""V2 exact released source and ordinary inert custody; no native engines."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest
from ravel.physics import generator_reuse as r, model_events as m, model_event_process as observer
from ravel.workflow import execution, model_event_plan, science
from test_generator_reuse import export, options, fixtures

F=Path(__file__).parent/'fixtures/mg5-reuse-markers'


def released(root):
    mapping={'export_v4.py':'madgraph/iolibs/export_v4.py','misc.py':'madgraph/various/misc.py',
        'clean_template':'Template/LO/bin/internal/clean_template','Events.keep':'Template/LO/Events/.keep','VERSION':'VERSION'}
    for source,target in mapping.items():
        p=root/target;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(F/source,p)
    return root


def marked_export(base):
    process,old=export(base);mg=released(base/'released-mg')
    (process/'Cards/me5_configuration.txt').write_text('mg5_path = '+str(mg)+'\n')
    (process/'Events/.keep').write_bytes((F/'Events.keep').read_bytes())
    (process/'SubProcesses/done').write_bytes(b'')
    (process/'Source/empty-native-source.inc').write_bytes(b'')
    record=r.capture_export(process,base/'marked-capsule',options(),{'process':str(process),'madgraph':str(mg),'model':'/old/model'})
    return process,record,mg


def test_released_keep_done_and_zero_source_are_lossless_nonempty_capsule_storage(tmp_path):
    process,record,mg=marked_export(tmp_path)
    zero=[x for x in record['rows'] if x.get('encoding')]
    assert {x['relative'] for x in zero}=={'Events/.keep','SubProcesses/done','Source/empty-native-source.inc'}
    assert all(x['blob']['size']>0 and r._blob_bytes(x,options()['max_member_bytes'])==b'' for x in zero)
    fresh=tmp_path/'fresh';r.materialize(record,fresh,{'process':str(fresh),'madgraph':str(mg),'model':'/new/model'})
    assert all((fresh/x['relative']).read_bytes()==b'' for x in zero)
    assert [p.name for p in (fresh/'Events').iterdir()]==['.keep'] and (fresh/'Events/.keep').stat().st_size==0
    assert all(p.stat().st_size>0 for p in Path(record['root']).rglob('*') if p.is_file())
    assert r.verify_tree(record)==record


@pytest.mark.parametrize('defect',['other-empty','nonempty-keep','nested-marker','marker-alias','source-copy-change','source-template-change'])
def test_only_exact_source_defined_incidental_events_marker_is_admitted(tmp_path,defect):
    process,old=export(tmp_path);mg=released(tmp_path/'mg');marker=process/'Events/.keep';marker.write_bytes(b'')
    if defect=='other-empty':(process/'Events/unknown').write_bytes(b'')
    elif defect=='nonempty-keep':marker.write_bytes(b'event bytes')
    elif defect=='nested-marker':(process/'Events/run').mkdir();(process/'Events/run/.keep').write_bytes(b'')
    elif defect=='marker-alias':marker.unlink();marker.symlink_to(mg/'Template/LO/Events/.keep')
    elif defect=='source-copy-change':(mg/'madgraph/various/misc.py').write_text('changed source')
    else:(mg/'Template/LO/Events/.keep').write_bytes(b'changed')
    with pytest.raises((ValueError,OSError)):r.capture_export(process,tmp_path/'bad',options(),{'process':str(process),'madgraph':str(mg),'model':'/old/model'})
    assert not (tmp_path/'bad/export.json').exists()


@pytest.mark.parametrize('defect',['bytes','encoding','removed','added-zero','marker-source-drift'])
def test_zero_capsule_envelope_and_late_namespace_do_not_rebaseline(tmp_path,defect):
    _,record,mg=marked_export(tmp_path);row=next(x for x in record['rows'] if x['relative']=='Events/.keep')
    if defect=='bytes':Path(row['blob']['path']).write_bytes(b'')
    elif defect=='encoding':row['encoding']='foreign';(Path(record['root'])/'export.json').write_bytes(r.encoded(record))
    elif defect=='removed':Path(row['blob']['path']).unlink()
    elif defect=='added-zero':(Path(record['root'])/'extra').write_bytes(b'')
    else:(mg/'madgraph/iolibs/export_v4.py').write_text('changed source')
    with pytest.raises((ValueError,OSError)):r.verify_tree(record)


def test_storage_envelope_overhead_is_charged_not_hidden_by_zero_raw_size(tmp_path):
    process,_=export(tmp_path);(process/'Source/zero.inc').write_bytes(b'')
    bounds=options();plain=sum(p.stat().st_size for p in process.rglob('*') if p.is_file() and not p.is_symlink())
    bounds['max_bytes']=plain;bounds['max_member_bytes']=plain
    with pytest.raises(ValueError,match='ceiling'):r.capture_export(process,tmp_path/'bounded',bounds,{'process':str(process),'madgraph':'/old/mg','model':'/old/model'})
    assert not (tmp_path/'bounded/export.json').exists()


def test_actual_worker_source_uses_same_origin_association_for_both_seed_reads():
    source=ast.parse(Path(m.__file__).read_text())
    worker=next(x for x in source.body if isinstance(x,ast.FunctionDef) and x.name=='native_worker')
    calls=[x for x in ast.walk(worker) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and
        isinstance(x.func.value,ast.Name) and x.func.value.id=='model_event_seed' and x.func.attr=='observe']
    assert len(calls)==2 and all(next(k.value for k in x.keywords if k.arg=='model_path').id=='imported_model' for x in calls)
    assert 'generator_reuse.model_import_path(reuse, model)' in ast.unparse(worker)


def test_public_preparation_binds_exact_four_raw_logs_and_preserves_scientific_empty_refusal(tmp_path):
    f=fixtures();request,c=f.setup_request(tmp_path);c['generator_reuse']=options();request['config']=f.write(tmp_path/'config.json',c)
    result=model_event_plan.prepare(request,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    spec=json.loads(Path(result['specification']['path']).read_text())
    assert spec['output_policy']==m.output_policy() and len(spec['output_policy']['allow_empty_directory_members'])==4
    p=science.plan(tmp_path/'run',result['specification']['path'])
    assert p['stage_binding']['output_policy']==m.output_policy() and science.verify_plan(tmp_path/'run')==p
    original=dict(spec['output_policy']['allow_empty_directory_members'][0]);spec['output_policy']['allow_empty_directory_members'][0]['path']='outputs/attempt-1/events.lhe'
    with pytest.raises(ValueError):science.validate(spec)
    assert original['role']=='incidental_log'


def test_split_branch_policy_retains_actual_source_defined_log_labels():
    policy=m.output_policy({'pre_shower_lhe_transform':{}})
    assert {x['path'] for x in policy['allow_empty_directory_members']}=={
        'outputs/attempt-1/'+label+'-'+stream+'.log'
        for label in ('build','hard-generate','shower-reentry') for stream in ('stdout','stderr')}
    assert len(policy['allow_empty_directory_members'])==6
    assert all(x['role']=='incidental_log' for x in policy['allow_empty_directory_members'])
