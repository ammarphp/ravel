"""Verify source parity and inherited artifact arithmetic. Never opens event payloads."""
from pathlib import Path,PurePosixPath
import argparse,ast,csv,hashlib,json,math
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
TEST_FILES={'tests/unit/'+n for n in('test_lhe_provenance.py','test_native_event_io.py','test_native_lhapdf.py','test_native_lhapdf_linker.py','test_native_dispatch.py')}
ENGINEERING_FILES={'src/ravel/physics/native_pipeline.py','src/ravel/physics/native_lhapdf.py','src/ravel/physics/native_build.py','src/ravel/validation/native_doctor.py','src/ravel/paths.py','native/src/pythia_shower.cc'}
# Fixed original preservation contract; never infer these roles from a mutable tree.
PREDECESSOR_FILES={
 'evidence/audits/2026-09-05-native-fidelity/README.md',
 'evidence/audits/2026-09-05-native-fidelity/cutflow-comparison.pdf',
 'evidence/audits/2026-09-05-native-fidelity/cutflow-comparison.png',
 'evidence/audits/2026-09-05-native-fidelity/erjr_differential.json',
 'evidence/audits/2026-09-05-native-fidelity/reference.json',
 'evidence/audits/2026-09-05-native-fidelity/render.py',
 'evidence/audits/2026-09-05-native-fidelity/verification.json',
 'evidence/audits/2026-09-05-native-fidelity/zero_lepton_cutflow.json',
 'evidence/audits/2026-09-06-native-fidelity/README.md',
 'evidence/audits/2026-09-06-native-fidelity/check_retained_sr_parity.py',
 'evidence/audits/2026-09-06-native-fidelity/comparisons.json',
 'evidence/audits/2026-09-06-native-fidelity/compressed-prior-verification.json',
 'evidence/audits/2026-09-06-native-fidelity/compressed-sr-parity.json',
 'evidence/audits/2026-09-06-native-fidelity/driver-counts.txt',
 'evidence/audits/2026-09-06-native-fidelity/erjr_differential.json',
 'evidence/audits/2026-09-06-native-fidelity/manifest.json',
 'evidence/audits/2026-09-06-native-fidelity/reference.json',
 'evidence/audits/2026-09-06-native-fidelity/replay-execution.json',
 'evidence/audits/2026-09-06-native-fidelity/tests.json',
 'evidence/audits/2026-09-06-native-fidelity/verification.json',
}
COPIED={'erjr_differential.json','comparisons.json','driver-counts.txt','reference.json'}
FUNCTIONS=('validate_hepmc','compress_events','shower','delphes')
REQUIRED={'src/ravel/physics/native_event_io.py','src/ravel/physics/pool_replicas.py','src/ravel/physics/lhe_provenance.py'}
def require(v,m):
 if not v:raise ValueError(m)
def exact(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def read(p):
 def pairs(rows):
  out={}
  for k,v in rows:require(k not in out,'Duplicate JSON key');out[k]=v
  return out
 v=json.loads(Path(p).read_text(),object_pairs_hook=pairs);exact(v);return v
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def path(root,relative):
 require(type(relative)is str and relative and '\\'not in relative and PurePosixPath(relative).as_posix()==relative and not PurePosixPath(relative).is_absolute()and '..'not in PurePosixPath(relative).parts,'Invalid relative evidence path')
 p=Path(root)/relative;require(p.is_file()and not p.is_symlink()and not any(q.is_symlink()for q in p.parents),'Missing/aliased evidence');return p
def number(v):require(type(v)in(int,float)and math.isfinite(v),'Finite numeric required');return v
def verify(root=ROOT,audit=HERE):
 root=Path(root);audit=Path(audit);v=read(audit/'verification.json');m=read(audit/'manifest.json')
 require(set(m)=={'schema_version','files'}and type(m['schema_version'])is int and m['schema_version']==1,'Audit manifest schema')
 require(not any(p.is_symlink()for p in audit.rglob('*')),'Aliased audit transport')
 actual={str(p.relative_to(audit)):sha(p)for p in audit.rglob('*')if p.is_file()and p!=audit/'manifest.json'}
 require(m['files']==actual,'Audit transport inventory/hash differs')
 require(sha(audit/'verify.py')==sha(Path(__file__)),'Canonical audit verifier differs')
 predecessors={str(p.relative_to(root))for folder in('2026-09-05-native-fidelity','2026-09-06-native-fidelity')for p in(root/'evidence/audits'/folder).rglob('*')if p.is_file()}
 require(set(v['predecessor_files_sha256'])==PREDECESSOR_FILES and predecessors==PREDECESSOR_FILES,'Exact original twenty predecessor roles required')
 require(set(v['copied_artifacts'])==COPIED,'Exact inherited artifact roles required')
 for name,record in v['copied_artifacts'].items():require(record['origin']=='evidence/audits/2026-09-06-native-fidelity/'+name,'Inherited artifact role/origin differs')
 require(v['physics_certified']is False and v['retained_replay_provenance']['repeated_in_this_version']is False and v['retained_replay_provenance']['new_raw_input_hash_claimed']is False,'Inherited observation scope changed')
 for name,digest in v['predecessor_files_sha256'].items():require(sha(path(root,name))==digest,'Historical audit changed')
 previous=read(path(root,v['retained_replay_provenance']['predecessor']));require(sha(path(root,v['retained_replay_provenance']['predecessor']))==v['retained_replay_provenance']['predecessor_sha256'],'Predecessor identity')
 require(v['engine_sha256']==previous['engine_sha256'],'Unchanged selection source scope differs')
 require(exact(v['retained_erjr_replay'])==exact(previous['retained_erjr_replay']),'Inherited replay claims changed')
 compressed=v['compressed_sr_parity'];require(compressed['selection_repeated_in_this_version']is False and compressed['root_branch_read_repeated_in_this_version']is False and compressed['whole_output_byte_identity_claimed']is False,'Compressed inheritance scope changed')
 require(compressed['prior_record']=='evidence/audits/2026-09-06-native-fidelity/compressed-sr-parity.json'and sha(path(root,compressed['prior_record']))==compressed['sha256'],'Compressed inherited proof differs')
 for name,digest in v['engine_sha256'].items():require(sha(path(root,'src/ravel/physics/'+name))==digest,'Scientific implementation changed')
 require(REQUIRED<=set(v['additional_engine_sha256']),'Required current IO/replica/provenance pin missing')
 for name,digest in v['additional_engine_sha256'].items():require(sha(path(root,name))==digest,'Additional implementation changed')
 require(v['additional_engine_sha256']['src/ravel/physics/pool_replicas.py']==previous['additional_engine_sha256']['src/ravel/physics/pool_replicas.py'],'Replica calculation changed')
 parity=read(audit/'default-event-io-parity.json');old=path(audit,parity['prior_source']['path']);new=path(root,parity['current_source']['path'])
 require(sha(old)==parity['prior_source']['sha256']==previous['additional_engine_sha256']['src/ravel/physics/native_event_io.py'],'Prior IO source unbound')
 require(sha(new)==parity['current_source']['sha256']==v['additional_engine_sha256']['src/ravel/physics/native_event_io.py'],'Current IO source unbound')
 trees=[{n.name:ast.dump(n,include_attributes=False)for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef)}for p in(old,new)]
 require(parity['functions']==[{'function':name,'ast_sha256':hashlib.sha256(trees[0][name].encode()).hexdigest(),'identical':True}for name in FUNCTIONS],'Source AST claim changed')
 require(all(trees[0][n]==trees[1][n]for n in FUNCTIONS),'Default function implementation changed')
 for name,record in v['copied_artifacts'].items():require(sha(path(audit,name))==record['sha256']==sha(path(root,record['origin'])),'Inherited artifact changed')
 d=read(audit/'erjr_differential.json');prior=read(path(root,'evidence/audits/2026-09-06-native-fidelity/erjr_differential.json'))
 require(exact(d)==exact(prior),'Inherited differential summary changed')
 require(d['entries']==v['retained_erjr_replay']['entries']==200000 and type(d['entries'])is int,'Original exposure differs')
 require(d['input_sha256']==v['retained_replay_provenance']['original_input_sha256']==v['retained_erjr_replay']['source_event_sha256'],'Original raw commitment differs')
 require(number(d['weights_min'])>0 and d['weights_min']==d['weights_max']and math.isclose(number(d['sum_weights']),d['entries']*d['weights_min'],rel_tol=1e-12),'Uniform-positive moment basis differs')
 require(d['selection_sha256']==v['engine_sha256']['sa_routines/ewkthreeleptonerjr2018.py']and d['core_sha256']==v['engine_sha256']['sa_native_core.py'],'Differential source binding differs')
 regions=set(d['counts']['paper']);require(len(regions)==9 and set(d['counts'])=={'historical','paper'}and all(set(x)==regions for x in d['counts'].values()),'18 region summary cells required')
 for mode,counts in d['counts'].items():
  for name,n in counts.items():require(type(n)is int and 0<=n<=d['entries']and math.isclose(number(d['acceptance'][mode][name]),n/d['entries'],rel_tol=0,abs_tol=1e-12),'Acceptance arithmetic differs')
  cut=d['cutflow'][mode];require(len(cut)==6 and set(cut)==set(d['cutflow_order'])and all(type(n)is int and 0<=n<=d['entries']for n in cut.values()),'12 cutflow summary cells required')
 changed=d['changed_events'];require(len(changed)==v['retained_erjr_replay']['changed_events']==73 and len({r['entry']for r in changed})==73,'Changed-event denominator/identity differs')
 for row in changed:
  require(type(row['entry'])is int and 0<=row['entry']<d['entries']and type(row['event'])is int,'Malformed changed-event identifier')
  for mode in('historical','paper'):require(len(row[mode])==len(set(row[mode]))and set(row[mode])<=regions,'Changed-event membership differs')
 for name in regions:require(sum((name in r['paper'])-(name in r['historical'])for r in changed)==d['counts']['paper'][name]-d['counts']['historical'][name],'Changed-event contribution differs')
 rows=list(csv.DictReader((audit/'driver-counts.txt').open()));require(len(rows)==10 and rows[0]['SR']=='All'and int(rows[0]['events'])==d['entries'],'Inherited driver population differs')
 for row in rows[1:]:require(int(row['events'])==d['counts']['paper'][row['SR']]and math.isclose(float(row['acceptance']),int(row['events'])/d['entries'],rel_tol=0,abs_tol=1e-12),'Inherited driver summary differs')
 ref=read(audit/'reference.json');acc=d['counts']['paper']['SRlow']/d['entries'];reference=number(ref['regions']['SRlow']['acceptance_times_efficiency']);res=acc/reference-1;remaining=v['remaining_acceptance_discrepancy']
 require(remaining==previous['remaining_acceptance_discrepancy']and math.isclose(res,number(remaining['relative_difference']),rel_tol=0,abs_tol=1e-12)and abs(res)>ref['driving_relative_tolerance']and remaining['passes_existing_tolerance']is False and remaining['new_certificate']is False,'Acceptance limitation changed')
 tests=read(audit/'tests.json')
 require(set(tests['test_source_sha256'])==TEST_FILES and set(tests['engineering_source_sha256'])==ENGINEERING_FILES,'Exact integrated test/engineering source scope required')
 for name,digest in {**tests['test_source_sha256'],**tests['engineering_source_sha256']}.items():require(sha(path(root,name))==digest,'Integrated test/engineering source changed')
 require(tests['integrated']['passed']==316 and tests['integrated']['failed']==tests['integrated']['skipped']==0 and tests['independent_source_controls']['passed']==86,'Recorded separate test populations changed')
 require(sha(audit/'integration-tests.log')==tests['integrated']['sanitized_log_sha256']and '316 passed, 8 warnings in 115.96s'in(audit/'integration-tests.log').read_text(),'Integrated test record differs')
 return {'status':'passed_source_and_retained_summary_checks','unchanged_default_functions':4,'original_exposure_represented':200000,'retained_region_cells':18,'retained_cutflow_cells':12,'retained_changed_event_records':73,'new_event_payload_reads':0,'new_replay':False,'physics_certified':False}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args();print(json.dumps(verify(a.root),indent=2))
