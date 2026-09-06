"""Verify source parity and inherited artifact arithmetic. Never opens event payloads."""
from pathlib import Path,PurePosixPath
import argparse,ast,csv,hashlib,json,math,runpy
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
TEST_FILES={'tests/unit/test_native_lhapdf.py','tests/unit/test_native_lhapdf_linker.py'}
ENGINEERING_FILES={'src/ravel/physics/native_pipeline.py','src/ravel/physics/native_lhapdf.py','src/ravel/physics/native_build.py','src/ravel/validation/native_doctor.py','src/ravel/paths.py','native/src/pythia_shower.cc'}
# Fixed original preservation contract; never infer these roles from a mutable tree.
PREDECESSOR_SHA256 = {'evidence/audits/2026-09-05-native-fidelity/README.md': 'f8ee1a13d14c053c5478be74a294666fae63f6449261d226f7bcd181b4c1ca99',
 'evidence/audits/2026-09-05-native-fidelity/cutflow-comparison.pdf': '682c66d5fa173d94e4e7e10b8a93625d54d71179ddd5cd8e1c0447bc51b2ea0e',
 'evidence/audits/2026-09-05-native-fidelity/cutflow-comparison.png': '5ef6d6ff0924cdb5e8c964089191802edeafc3c07c699626b6e6e5d47e90d852',
 'evidence/audits/2026-09-05-native-fidelity/erjr_differential.json': '90f1c87a55d3f17b1a97094e127dc7b72e040df3899b8d4135b4dade0745f62f',
 'evidence/audits/2026-09-05-native-fidelity/reference.json': 'd636f7a6a1a7ef4617fd507805c09eca35a126b33dbacae5b43b6e83362ce1c2',
 'evidence/audits/2026-09-05-native-fidelity/render.py': 'db2e3586530622fd28e2a4ca7b1b35db5c4005cb9165c752dacd8f08e13c54f8',
 'evidence/audits/2026-09-05-native-fidelity/verification.json': 'e0d1dd1682d3fd8cb648dcb97dba5466c1deaf77a3ce488da0be6e2f8e3a49c4',
 'evidence/audits/2026-09-05-native-fidelity/zero_lepton_cutflow.json': '965b3011bc83c2b66684b9f582dc7c818b1158602f0ffb6ae363914cb047edce',
 'evidence/audits/2026-09-06-native-fidelity-v2/README.md': '1d459b4882983580407c893341d78c7f632d47b696686ecebeac07fbe2cc6299',
 'evidence/audits/2026-09-06-native-fidelity-v2/comparisons.json': '08f5364146960fdae210d0ba6157959d0abbed370286983bdfd9f5e4c61e992b',
 'evidence/audits/2026-09-06-native-fidelity-v2/default-event-io-parity.json': 'e20c7a1c74636a01daabe4ca9e71759dd9eca24deb0051ea5b86b3813a5b17b8',
 'evidence/audits/2026-09-06-native-fidelity-v2/driver-counts.txt': '1a786f3c11b895bd31f6f21ead11051c880f39e6b647d5708066ebc4a1d1edb0',
 'evidence/audits/2026-09-06-native-fidelity-v2/erjr_differential.json': '90f1c87a55d3f17b1a97094e127dc7b72e040df3899b8d4135b4dade0745f62f',
 'evidence/audits/2026-09-06-native-fidelity-v2/integration-tests.log': 'ca3915aa2ce64730ca863e28ab42085adb95bbf94489362a0f62c06fabb284e9',
 'evidence/audits/2026-09-06-native-fidelity-v2/manifest.json': '9f1371b50f8a94a48268a58c3a8ee1629319380fc7a20c8c2a901744dacee75f',
 'evidence/audits/2026-09-06-native-fidelity-v2/prior_native_event_io.py': 'ad3e897adae8983e01b3758bd8820563009ce79f4cf2c93c727712e6c789eb2c',
 'evidence/audits/2026-09-06-native-fidelity-v2/reference.json': 'd636f7a6a1a7ef4617fd507805c09eca35a126b33dbacae5b43b6e83362ce1c2',
 'evidence/audits/2026-09-06-native-fidelity-v2/test_verify.py': 'a4c65b7b9dcdbcc415aaa5efb67a8084a04097249c644b46d699a5155a258c65',
 'evidence/audits/2026-09-06-native-fidelity-v2/tests.json': '5a1baad7076b42f4f53956fdc640fb5e4bf6888f7c30eff773a1594ed73d27a0',
 'evidence/audits/2026-09-06-native-fidelity-v2/verification.json': '20810800ca2aa8cac89640f9ebc31a972aae5be6e79723a10b40c0829dac1e38',
 'evidence/audits/2026-09-06-native-fidelity-v2/verify.py': '84df1355920c37bbcc131eaabea071118bdbb0eb7e0c95d7608e7aa1c3bfd3e0',
 'evidence/audits/2026-09-06-native-fidelity/README.md': '6e8b681d0f13920526c500efa0223eeb8214d40787a75755dec9d3b51eecb050',
 'evidence/audits/2026-09-06-native-fidelity/check_retained_sr_parity.py': '8c89a0358dc4531183b6418ca9ab1e33891891c5ea1571f6a8489fe37108c981',
 'evidence/audits/2026-09-06-native-fidelity/comparisons.json': '08f5364146960fdae210d0ba6157959d0abbed370286983bdfd9f5e4c61e992b',
 'evidence/audits/2026-09-06-native-fidelity/compressed-prior-verification.json': '3c441a2ec3367a9c986ca37d427b38d0c211d476b502492d62bae28051015e1a',
 'evidence/audits/2026-09-06-native-fidelity/compressed-sr-parity.json': '59140655e70dc8789a8ddde43b0b9f99efb4a3eb92c0cb5b8e5b35a2db198f77',
 'evidence/audits/2026-09-06-native-fidelity/driver-counts.txt': '1a786f3c11b895bd31f6f21ead11051c880f39e6b647d5708066ebc4a1d1edb0',
 'evidence/audits/2026-09-06-native-fidelity/erjr_differential.json': '90f1c87a55d3f17b1a97094e127dc7b72e040df3899b8d4135b4dade0745f62f',
 'evidence/audits/2026-09-06-native-fidelity/manifest.json': '85b6f55cfc2cb962df9f3fe04e83068d62709ed3bcc9f332e70876f0fa10abd5',
 'evidence/audits/2026-09-06-native-fidelity/reference.json': 'd636f7a6a1a7ef4617fd507805c09eca35a126b33dbacae5b43b6e83362ce1c2',
 'evidence/audits/2026-09-06-native-fidelity/replay-execution.json': 'd7cf0b6c886a8cfca91e13ac32d1da909124b2e46afa82c59eff7721a35d3874',
 'evidence/audits/2026-09-06-native-fidelity/tests.json': 'dc1fd21b8423cef850a82bf0f7d7c492c11269df0a9d4d1a40b50b4556245363',
 'evidence/audits/2026-09-06-native-fidelity/verification.json': 'd625c2755766ec89fa8f5335333217a28ab63a327507d35307031f1e83238105'}
PREDECESSOR_FILES=set(PREDECESSOR_SHA256)
V2="evidence/audits/2026-09-06-native-fidelity-v2"
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

EXPECTED_BRIDGE = {'current_source_sha256': '91d76171c0a815f5a937a83a5ec09de61430d12ff75ea65de523a7abe488d5b4',
 'current_test_sha256': 'dd750acfac03bd8a4419d1a3ea01e48a66b9f088bc30c33343afe3fc93ca6051',
 'forbidden_fields': 19,
 'new_physics_claim': False,
 'new_successful_generation_behavior': False,
 'old_source_sha256': '42938ea753a8407fb88abea874bcca9889ef16090573deba11e4761e31d5cf42',
 'old_test_sha256': 'febff2f6c436ff47478690f11d48ca1a2b47b1c9961f35fdee0c90dbaf903936',
 'only_change': 'Sorted names of nonempty fixed forbidden environment fields; no values. Same refusal '
                'predicate before probes.',
 'prior_audit': 'evidence/audits/2026-09-06-native-fidelity-v2/verification.json',
 'prior_audit_sha256': '20810800ca2aa8cac89640f9ebc31a972aae5be6e79723a10b40c0829dac1e38',
 'prior_source_copy': 'prior_native_lhapdf.py',
 'prior_test_copy': 'prior_test_native_lhapdf.py',
 'production_path': 'src/ravel/physics/native_lhapdf.py',
 'test_path': 'tests/unit/test_native_lhapdf.py',
 'unchanged_other_functions': 15}
EXPECTED_UNIT_TEST_SCOPE = {'counts_are_separate_not_added': True, 'current_lhapdf_passed': 180, 'inherited_independent_source_passed': 86, 'inherited_integrated_passed': 316, 'record': 'tests.json', 'separate_independent_guard_cases': 295}
CURRENT_TEST_RECORD = {'argv': ['env',
          '-u',
          'PYTHONPATH',
          'PYTHONDONTWRITEBYTECODE=1',
          '<locked-python312-env>/bin/python',
          '-B',
          '-m',
          'pytest',
          '<publication-stage>/tests/unit/test_native_lhapdf.py',
          '<publication-stage>/tests/unit/test_native_lhapdf_linker.py',
          '-q'],
 'failed': 0,
 'log': 'current-tests.log',
 'log_sha256': '6eb6a751d499460ca0b088f8cbed74117d021a30e9e2ea4702ab83299a6381e8',
 'origin': 'local-runs/rrr-closure/physics-review/lhapdf-override-diagnostics-independent-v1/tests.log',
 'original_sha256': '6eb6a751d499460ca0b088f8cbed74117d021a30e9e2ea4702ab83299a6381e8',
 'passed': 180,
 'path_translation_only': True,
 'seconds': 9.44,
 'skipped': 0,
 'working_directory': 'parent of <source-repo>'}
INDEPENDENT_RECORD_SHA256 = '4f51112dfa4c12c8d0dc7a30791d97d3561301477c68712b2189f6f23c11a0b8'

EXPECTED_INDEPENDENT_REVIEW = {'cases': 295,
 'current_source_sha256': '91d76171c0a815f5a937a83a5ec09de61430d12ff75ea65de523a7abe488d5b4',
 'fields': 19,
 'original_source': 'local-runs/rrr-closure/physics-review/lhapdf-override-diagnostics-independent-v1/check.py',
 'original_source_sha256': '89426807cd4fd1cdb27ad7736a99294b2cd007dac755ba78b8361b7959cd635f',
 'record': 'independent-override-checks.json',
 'scope': 'Separate early-guard source/privacy review with all filesystem/linker probes stopped; '
          'no successful generation decision or physics execution.',
 'sha256': '4f51112dfa4c12c8d0dc7a30791d97d3561301477c68712b2189f6f23c11a0b8'}
EXPECTED_VERIFICATION_SCOPE = 'Current LHAPDF refusal-message source bridge plus unchanged-source and retained-summary arithmetic. Prior316 integrated/86 independent controls are inherited at their original sources. Current180 tests and separate295 independent early-guard cases do not repeat event generation, ROOT selection, inference or acceptance validation.'
EXPECTED_TEST_SCOPE = 'Current refusal diagnostic and unchanged-path engineering controls; inherited populations are not relabeled as current tests.'
EXPECTED_IO_SCOPE = {'functions': ['validate_hepmc', 'compress_events', 'shower', 'delphes'], 'new_default_physics_claimed': False, 'new_optional_interface': 'shower-original / original-LHA sidecar and content verification', 'old_source_sha256': 'ad3e897adae8983e01b3758bd8820563009ce79f4cf2c93c727712e6c789eb2c', 'record': 'default-event-io-parity.json', 'scope': 'Rechecked unchanged IO AST evidence inherited from v2; no new optional-interface change in v3.'}

def verify_diagnostic_bridge(root,audit,v):
 require(v["scope"]==EXPECTED_VERIFICATION_SCOPE and exact(v["fresh_source_validation"])==exact(EXPECTED_IO_SCOPE),"Current versus inherited audit scope changed")
 require(exact(v['diagnostic_bridge'])==exact(EXPECTED_BRIDGE),'Exact reviewed diagnostic bridge required')
 require(exact(v['unit_tests'])==exact(EXPECTED_UNIT_TEST_SCOPE),'Current and inherited test populations conflated')
 bridge=v['diagnostic_bridge'];old=path(audit,bridge['prior_source_copy']);new=path(root,bridge['production_path'])
 oldtest=path(audit,bridge['prior_test_copy']);newtest=path(root,bridge['test_path'])
 require(sha(old)==bridge['old_source_sha256']and sha(new)==bridge['current_source_sha256'],'Production diagnostic source changed')
 require(sha(oldtest)==bridge['old_test_sha256']and sha(newtest)==bridge['current_test_sha256'],'Diagnostic test source changed')
 prior=read(path(root,V2+'/verification.json'));prior_tests=read(path(root,V2+'/tests.json'))
 require(sha(path(root,bridge['prior_audit']))==bridge['prior_audit_sha256'],'Inherited v2 audit identity')
 require(prior_tests['engineering_source_sha256'][bridge['production_path']]==sha(old)and prior_tests['test_source_sha256'][bridge['test_path']]==sha(oldtest),'Prior source copies do not match dated test record')
 require(exact(v['engine_sha256'])==exact(prior['engine_sha256'])and exact(v['additional_engine_sha256'])==exact(prior['additional_engine_sha256']),'Scientific/IO scope changed from v2')
 for field in('retained_erjr_replay','retained_replay_provenance','remaining_acceptance_discrepancy','compressed_sr_parity','copied_artifacts','not_repeated'):
  require(exact(v[field])==exact(prior[field]),'Inherited scientific scope changed: '+field)
 # All prior integrated source bindings remain enforced, with the two explicitly bridged exceptions.
 require(set(prior_tests['engineering_source_sha256'])==ENGINEERING_FILES,'Original engineering population')
 old_test_roles={'tests/unit/'+n for n in('test_lhe_provenance.py','test_native_event_io.py','test_native_lhapdf.py','test_native_lhapdf_linker.py','test_native_dispatch.py')}
 require(set(prior_tests['test_source_sha256'])==old_test_roles,'Original integrated test population')
 for role,pins in(('engineering_source_sha256',prior_tests['engineering_source_sha256']),('test_source_sha256',prior_tests['test_source_sha256'])):
  for name,digest in pins.items():
   if name==bridge['production_path']:require(sha(old)==digest,'Original module commitment')
   elif name==bridge['test_path']:require(sha(oldtest)==digest,'Original test commitment')
   else:require(sha(path(root,name))==digest,'Unchanged inherited engineering/test source drift')
 require(prior_tests['integrated']['passed']==316 and prior_tests['integrated']['failed']==prior_tests['integrated']['skipped']==0 and prior_tests['independent_source_controls']['passed']==86,'Original separate test populations changed')
 require(sha(path(root,V2+'/integration-tests.log'))==prior_tests['integrated']['sanitized_log_sha256']and '316 passed, 8 warnings in 115.96s'in path(root,V2+'/integration-tests.log').read_text(),'Original integrated log changed')
 tests=read(audit/'tests.json')
 require(set(tests)=={'schema_version','scope','current','test_source_sha256','engineering_source_sha256','independent_guard_review','inherited'},'New test record schema')
 require(type(tests['schema_version'])is int and tests['schema_version']==1,'Test record version')
 require(set(tests['test_source_sha256'])==TEST_FILES and set(tests['engineering_source_sha256'])==ENGINEERING_FILES,'Exact current engineering and executed test roles')
 for name,digest in {**tests['test_source_sha256'],**tests['engineering_source_sha256']}.items():require(sha(path(root,name))==digest,'Current engineering/test source changed')
 require(exact(tests['current'])==exact(CURRENT_TEST_RECORD),'Current180 test provenance changed')
 require(sha(path(audit,tests['current']['log']))==tests['current']['log_sha256']and '180 passed in 9.44s'in path(audit,tests['current']['log']).read_text(),'Current180 test log changed')
 expected_inherited={'record':V2+'/tests.json','sha256':sha(path(root,V2+'/tests.json')),'integrated_passed':316,'independent_source_passed':86,'repeated_in_v3':False,'applies_to_original_source_pins_only':True}
 require(exact(tests['inherited'])==exact(expected_inherited),'Inherited tests relabeled as current')
 require(tests['scope']==EXPECTED_TEST_SCOPE,'Engineering test scope changed')
 independent=tests['independent_guard_review']
 require(exact(independent)==exact(EXPECTED_INDEPENDENT_REVIEW),'Exact independent review origin/scope required')
 require(independent['cases']==295 and type(independent['cases'])is int and independent['fields']==19 and independent['record']=='independent-override-checks.json'and independent['sha256']==INDEPENDENT_RECORD_SHA256,'Independent case population/record changed')
 require(sha(path(audit,independent['record']))==INDEPENDENT_RECORD_SHA256,'Independent review changed')
 original=read(path(audit,independent['record']))
 require(original['independent_guard_cases']==len(original['cases'])==295 and original['forbidden_field_count']==19 and original['unchanged_top_level_functions']==15,'Independent proof population')
 require(original['source']['current_sha256']==sha(new)and original['source']['old_sha256']==sha(old)and original['test_source']['current_sha256']==sha(newtest),'Independent proof source identity')
 require(original['scope']=={'generator_started':False,'external_linker_probes_executed':False,'raw_events_read':False,'old_audits_changed':False,'physics_or_successful_decision_semantics_changed':False},'Independent proof scope changed')
 # Execute only our canonical root helper, never code supplied by a copied audit.
 helper=HERE/'check_override_guards.py';require(sha(path(audit,'check_override_guards.py'))==sha(helper),'Canonical guard checker changed')
 checker=runpy.run_path(str(helper));result=checker['check'](old.read_text(),new.read_text())
 require(result=={'passed_cases':295,'forbidden_fields':19,'unchanged_other_functions':15,'external_probes':0,'raw_payload_reads':0,'new_events':0,'new_fits':0},'Portable guard control result')
 old_functions={n.name:ast.dump(n,include_attributes=False)for n in ast.parse(oldtest.read_text()).body if isinstance(n,ast.FunctionDef)}
 new_functions={n.name:ast.dump(n,include_attributes=False)for n in ast.parse(newtest.read_text()).body if isinstance(n,ast.FunctionDef)}
 require(all(new_functions.get(n)==body for n,body in old_functions.items()),'Earlier test functions changed')
 require(set(new_functions)-set(old_functions)=={'test_forbidden_override_reports_name_without_value_or_probe','test_multiple_overrides_are_named_in_stable_order_without_empty_fields'},'Unexpected new test functions')

def verify(root=ROOT,audit=HERE):
 root=Path(root);audit=Path(audit);v=read(audit/'verification.json');m=read(audit/'manifest.json')
 require(set(m)=={'schema_version','files'}and type(m['schema_version'])is int and m['schema_version']==1,'Audit manifest schema')
 require(not any(p.is_symlink()for p in audit.rglob('*')),'Aliased audit transport')
 actual={str(p.relative_to(audit)):sha(p)for p in audit.rglob('*')if p.is_file()and p!=audit/'manifest.json'}
 require(set(actual)==set(['README.md', 'check_override_guards.py', 'comparisons.json', 'current-tests.log', 'default-event-io-parity.json', 'driver-counts.txt', 'erjr_differential.json', 'independent-override-checks.json', 'prior_native_event_io.py', 'prior_native_lhapdf.py', 'prior_test_native_lhapdf.py', 'reference.json', 'test_verify.py', 'tests.json', 'verification.json', 'verify.py']),'Exact v3 artifact roles required')
 require(m['files']==actual,'Audit transport inventory/hash differs')
 require(sha(audit/'verify.py')==sha(Path(__file__)),'Canonical audit verifier differs')
 predecessors={str(p.relative_to(root))for folder in('2026-09-05-native-fidelity','2026-09-06-native-fidelity','2026-09-06-native-fidelity-v2')for p in(root/'evidence/audits'/folder).rglob('*')if p.is_file()}
 require(v['predecessor_files_sha256']==PREDECESSOR_SHA256 and predecessors==PREDECESSOR_FILES,'Exact original thirty-three predecessor roles and hashes required')
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
 verify_diagnostic_bridge(root,audit,v)
 return {'status':'passed_source_and_retained_summary_checks','unchanged_default_functions':4,'current_lhapdf_tests':180,'separate_independent_guard_cases':295,'inherited_integrated_tests':316,'inherited_independent_source_tests':86,'original_exposure_represented':200000,'retained_region_cells':18,'retained_cutflow_cells':12,'retained_changed_event_records':73,'new_event_payload_reads':0,'new_replay':False,'physics_certified':False}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args();print(json.dumps(verify(a.root),indent=2))
