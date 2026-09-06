"""Source-only positive and copied-bundle semantic controls; no event reads."""
from pathlib import Path
import copy,hashlib,importlib.util,json,shutil
import pytest
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('native_audit_v3_verifier',HERE/'verify.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

def manifest(root):
 data={'schema_version':1,'files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted(root.rglob('*'))if p.is_file()and p!=root/'manifest.json'}}
 (root/'manifest.json').write_text(json.dumps(data))

def test_current_version3_source_and_retained_summary_positive():
 result=v.verify(ROOT,HERE);assert result['original_exposure_represented']==200000 and result['retained_changed_event_records']==73 and result['new_event_payload_reads']==0 and result['new_replay']is False

@pytest.mark.parametrize('mutation',['replay','raw_hash','certification','old_source','drop_provenance','wrong_provenance','ast','residual','scope','tests','driver','differential','extra','compressed_scope','replay_claim'])
def test_semantic_tamper_cannot_pass_by_rehashing_transport(tmp_path,mutation):
 target=tmp_path/'audit';shutil.copytree(HERE,target)
 name='verification.json';data=json.loads((target/name).read_text())
 if mutation=='compressed_scope':data['compressed_sr_parity']['selection_repeated_in_this_version']=True
 elif mutation=='replay_claim':data['retained_erjr_replay']['production_driver_all_paper_counts_agree']=False
 elif mutation=='replay':data['retained_replay_provenance']['repeated_in_this_version']=True
 elif mutation=='raw_hash':data['retained_replay_provenance']['new_raw_input_hash_claimed']=True
 elif mutation=='certification':data['physics_certified']=True
 elif mutation=='old_source':data['engine_sha256']['sa_native_core.py']='0'*64
 elif mutation=='drop_provenance':data['additional_engine_sha256'].pop('src/ravel/physics/lhe_provenance.py')
 elif mutation=='wrong_provenance':data['additional_engine_sha256']['src/ravel/physics/lhe_provenance.py']='0'*64
 elif mutation=='residual':data['remaining_acceptance_discrepancy']['passes_existing_tolerance']=True
 elif mutation=='scope':data['retained_replay_provenance']['original_input_sha256']='0'*64
 elif mutation=='ast':
  name='default-event-io-parity.json';data=json.loads((target/name).read_text());data['functions'][0]['identical']=False
 elif mutation=='tests':
  name='tests.json';data=json.loads((target/name).read_text());data['current']['passed']=402
 elif mutation=='differential':
  name='erjr_differential.json';data=json.loads((target/name).read_text());data['counts']['paper']['SRlow']=200
 elif mutation=='driver':
  path=target/'driver-counts.txt';path.write_text(path.read_text().replace('SRlow,95,','SRlow,99,'))
 elif mutation=='extra':(target/'unlisted.txt').write_text('unexpected')
 if mutation not in('driver','extra'):(target/name).write_text(json.dumps(data))
 if mutation!='extra':manifest(target)
 with pytest.raises(ValueError):v.verify(ROOT,target)

@pytest.mark.parametrize('path',['../escape','/absolute','a/../file','./file','a//file','a\\file'])
def test_relative_sources_do_not_escape(tmp_path,path):
 with pytest.raises(ValueError):v.path(tmp_path,path)

def test_same_byte_audit_symlink_rejected(tmp_path):
 target=tmp_path/'audit';shutil.copytree(HERE,target);path=target/'reference.json';path.unlink();path.symlink_to(HERE/'reference.json')
 with pytest.raises(ValueError):v.verify(ROOT,target)

@pytest.mark.parametrize('role', ['predecessor_files_sha256', 'copied_artifacts'])
def test_preservation_scope_cannot_be_narrowed(tmp_path,role):
 target=tmp_path/'audit';shutil.copytree(HERE,target);path=target/'verification.json';data=json.loads(path.read_text());data[role].pop(next(iter(data[role])));path.write_text(json.dumps(data));manifest(target)
 with pytest.raises(ValueError):v.verify(ROOT,target)

@pytest.mark.parametrize('role', ['test_source_sha256', 'engineering_source_sha256'])
@pytest.mark.parametrize('change', ['missing', 'hash'])
def test_integrated_source_claim_is_not_a_freeform_annotation(tmp_path,role,change):
 target=tmp_path/'audit';shutil.copytree(HERE,target);path=target/'tests.json';data=json.loads(path.read_text());name=next(iter(data[role]))
 if change=='missing':data[role].pop(name)
 else:data[role][name]='0'*64
 path.write_text(json.dumps(data));manifest(target)
 with pytest.raises(ValueError):v.verify(ROOT,target)


def minimal_root(tmp_path):
 target=tmp_path/'root';audit=target/'evidence/audits'/HERE.name
 shutil.copytree(HERE,audit)
 data=json.loads((HERE/'verification.json').read_text());tests=json.loads((HERE/'tests.json').read_text())
 sources=set(data['predecessor_files_sha256'])|set(data['additional_engine_sha256'])|set(tests['test_source_sha256'])|set(tests['engineering_source_sha256'])|{'src/ravel/physics/'+name for name in data['engine_sha256']}
 sources|=set(json.loads((ROOT/'evidence/audits/2026-09-06-native-fidelity-v2/tests.json').read_text())['test_source_sha256'])
 for name in sources:
  dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
 return target,audit

@pytest.mark.parametrize('change',['none','paired_delete','paired_add'])
def test_fixed_original_history_roles_survive_mutated_tree(tmp_path,change):
 root,audit=minimal_root(tmp_path);p=audit/'verification.json';data=json.loads(p.read_text())
 if change=='paired_delete':
  name='evidence/audits/2026-09-05-native-fidelity/README.md';(root/name).unlink();data['predecessor_files_sha256'].pop(name)
 elif change=='paired_add':
  name='evidence/audits/2026-09-05-native-fidelity/extra-history.txt';(root/name).write_text('unexpected role');data['predecessor_files_sha256'][name]=v.sha(root/name)
 p.write_text(json.dumps(data));manifest(audit)
 if change=='none':assert v.verify(root,audit)['new_replay']is False
 else:
  with pytest.raises(ValueError,match='thirty-three predecessor roles'):v.verify(root,audit)

@pytest.mark.parametrize('change',['current_source','current_test','old_source_copy','old_test_copy','copied_helper','nested_manifest','new_artifact'])
def test_exact_bridge_and_transport_cannot_be_rebound(tmp_path,change):
 root,audit=minimal_root(tmp_path)
 if change=='current_source':
  p=root/'src/ravel/physics/native_lhapdf.py';p.write_text(p.read_text().replace("sorted(k for k in FORBIDDEN_ENV", "list(k for k in FORBIDDEN_ENV"))
 elif change=='current_test':
  p=root/'tests/unit/test_native_lhapdf.py';p.write_text(p.read_text().replace('private-value-canary','changed-canary'))
 elif change=='old_source_copy':
  p=audit/'prior_native_lhapdf.py';p.write_text(p.read_text()+'# changed old byte commitment\n')
 elif change=='old_test_copy':
  p=audit/'prior_test_native_lhapdf.py';p.write_text(p.read_text()+'# changed old tests\n')
 elif change=='copied_helper':
  (audit/'check_override_guards.py').write_text("raise RuntimeError('copied helper must not execute')\n")
 elif change=='nested_manifest':
  (audit/'nested').mkdir();(audit/'nested/manifest.json').write_text('{}')
 else:(audit/'unplanned.txt').write_text('extra')
 manifest(audit)
 with pytest.raises(ValueError):v.verify(root,audit)

@pytest.mark.parametrize('field,value',[
 ('current_lhapdf_passed',496),('separate_independent_guard_cases',0),
 ('inherited_integrated_passed',180),('inherited_independent_source_passed',402),
 ('counts_are_separate_not_added',False)])
def test_population_scope_cannot_change_with_refreshed_manifest(tmp_path,field,value):
 target=tmp_path/'audit';shutil.copytree(HERE,target);p=target/'verification.json';d=json.loads(p.read_text());d['unit_tests'][field]=value;p.write_text(json.dumps(d));manifest(target)
 with pytest.raises(ValueError,match='populations conflated'):v.verify(ROOT,target)

@pytest.mark.parametrize('change',['inherited_as_current','unknown_current_test','missing_inherited','changed_current_log','review_origin','review_cases','review_source','review_file','scope'])
def test_exact_current_and_inherited_test_provenance(tmp_path,change):
 target=tmp_path/'audit';shutil.copytree(HERE,target);p=target/'tests.json';d=json.loads(p.read_text())
 if change=='inherited_as_current':d['inherited']['repeated_in_v3']=True
 elif change=='unknown_current_test':d['test_source_sha256']['tests/unit/test_unrun.py']='0'*64
 elif change=='missing_inherited':d.pop('inherited')
 elif change=='changed_current_log':(target/'current-tests.log').write_text('180 passed in 9.44s but changed')
 elif change=='review_origin':d['independent_guard_review']['original_source']='other/source.py'
 elif change=='review_cases':d['independent_guard_review']['cases']=True
 elif change=='review_source':d['independent_guard_review']['current_source_sha256']='0'*64
 elif change=='review_file':(target/'independent-override-checks.json').write_text('{}')
 else:d['scope']='fresh full physics replay'
 p.write_text(json.dumps(d));manifest(target)
 with pytest.raises(ValueError):v.verify(ROOT,target)

@pytest.mark.parametrize('case',['extra_role','missing_role','wrong_hash'])
def test_full_v2_history_cannot_be_narrowed_or_rebound(tmp_path,case):
 root,audit=minimal_root(tmp_path);p=audit/'verification.json';d=json.loads(p.read_text());name='evidence/audits/2026-09-06-native-fidelity-v2/tests.json'
 if case=='missing_role':(root/name).unlink();d['predecessor_files_sha256'].pop(name)
 elif case=='wrong_hash':d['predecessor_files_sha256'][name]='0'*64
 else:
  name='evidence/audits/2026-09-06-native-fidelity-v2/unexpected.json';(root/name).write_text('{}');d['predecessor_files_sha256'][name]=v.sha(root/name)
 p.write_text(json.dumps(d));manifest(audit)
 with pytest.raises(ValueError,match='thirty-three predecessor roles'):v.verify(root,audit)

@pytest.mark.parametrize('mutation',['predicate','values','field_population','unrelated_function'])
def test_portable_guard_replay_rejects_unreviewed_semantics(mutation):
 import runpy
 c=runpy.run_path(str(HERE/'check_override_guards.py'));old=(HERE/'prior_native_lhapdf.py').read_text();new=(ROOT/'src/ravel/physics/native_lhapdf.py').read_text()
 if mutation=='predicate':new=new.replace("env.get(k) not in (None, '')", "env.get(k) is not None")
 elif mutation=='values':new=new.replace("', '.join(blocked)","str(env)")
 elif mutation=='field_population':new=new.replace("'MAKEFLAGS', 'MFLAGS'","'MFLAGS'")
 else:new=new.replace("PDF_ID = 260000","PDF_ID = 260001")
 with pytest.raises(ValueError):c['check'](old,new)
