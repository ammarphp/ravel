"""Provider custody and evaluated-readiness controls; never start a kernel."""
from pathlib import Path
import pytest
from ravel.physics import model_provider_bridge as bridge


def config():
    pin={'path':'/bound/file','sha256':'a'*64}
    return {'schema_version':1,'operation':'wolfram-feynrules-readiness','source':'Attributed exact local source',
       'kernel':pin,'application_metadata':pin,'provider_tree':{'root':'/bound/source','manifest':pin},
       'trusted_provider_source':True,'expected_kernel_version':14.3,'expected_provider_version':'2.3.49',
       'existing_installation_license_status':'unverified_no_activation_or_credentials_requested',
       'max_seconds':60,'max_ram_mib':2048}


def receipt():
    return {'provider_root':'/owned/feynrules','process_id':123,'kernel_version':14.3,'kernel_arithmetic_control':4,
        'provider_loaded':True,'provider_version':'2.3.49','parallel_disabled':True,
        'namespace_compatibility':{'mode':'package_context_symbols_v1','message_free_load':True,
            'load_messages':[],'system_definitions_unchanged':True,
            'package_commutator_downvalues':2,'package_matrix_symbol_downvalues':8},
        'parallel_kernels_list':True,'parallel_kernel_count':0,
        'entrypoint_downvalues':{name:1 for name in bridge.ENTRYPOINTS},
        'obsolete_undefined_entrypoint_downvalues':0,'model_calculation_performed':False,'generated_events':0}


def test_nonvacuous_operational_readiness_scope():
    result=bridge.adjudicate(receipt(),config(),Path('/owned/feynrules'),123)
    assert result['passed'] and 'no model validity' in result['scope']


@pytest.mark.parametrize('field,value',[('provider_root','/unbound/provider'),('process_id',124),
    ('kernel_version',13.0),('kernel_arithmetic_control','2+2'),('provider_loaded','True'),
    ('provider_version','2.3.26'),('parallel_disabled',False),('parallel_kernels_list',False),
    ('parallel_kernel_count',1),('entrypoint_downvalues',{'FeynmanRules':1}),
    ('obsolete_undefined_entrypoint_downvalues',1),('model_calculation_performed',True),('generated_events',1)])
def test_false_unevaluated_or_wrong_provider_receipts_fail(field,value):
    r=receipt();r[field]=value
    assert not bridge.adjudicate(r,config(),Path('/owned/feynrules'),123)['passed']


def test_declared_symbols_must_have_evaluated_definitions():
    r=receipt();r['entrypoint_downvalues']['WriteUFO']=0
    assert not bridge.adjudicate(r,config(),Path('/owned/feynrules'),123)['passed']


@pytest.mark.parametrize('field,value',[('trusted_provider_source',False),('expected_kernel_version',16.0),
    ('expected_provider_version','latest'),('existing_installation_license_status','licensed'),
    ('max_seconds',121),('max_ram_mib',4097)])
def test_qualification_contract_requires_exact_source_runtime_and_uncertainty(field,value):
    c=config();c[field]=value
    with pytest.raises(ValueError):bridge.validate_config(c)


@pytest.mark.parametrize('version', [14.3, 15.0])
def test_readiness_requires_observed_explicit_runtime_version(version):
    c=config();c['expected_kernel_version']=version
    assert bridge.validate_config(c) is c
    r=receipt();r['kernel_version']=version
    assert bridge.adjudicate(r,c,Path('/owned/feynrules'),123)['passed']
    r['kernel_version']=15.0 if version==14.3 else 14.3
    assert not bridge.adjudicate(r,c,Path('/owned/feynrules'),123)['passed']


def test_cli_binds_requested_version_and_preserves_legacy_default(monkeypatch):
    seen=[]
    monkeypatch.setattr(bridge,'prepare',lambda args:seen.append(args.expected_kernel_version) or 0)
    argv=['plan','--kernel','kernel','--application-metadata','metadata','--feynrules','source',
          '--source','test','--rundir','fresh','--review-policy','policy','--trust-provider-source']
    assert bridge.main(argv)==0
    assert bridge.main(argv+['--expected-kernel-version','15.0'])==0
    with pytest.raises(SystemExit):bridge.main(argv+['--expected-kernel-version','16.0'])
    assert seen==[14.3,15.0]


def test_fixed_script_disables_parallel_and_never_loads_model_or_licenses():
    text=bridge.script(Path('/owned/feynrules'),Path('/owned/receipt.json'))
    assert 'FR$Parallel = False' in text and 'DownValues[FeynRules`WriteUFO]' in text
    assert 'LoadModel[' not in text and 'FeynmanRules[' not in text and 'WriteUFO[' not in text
    assert '$PasswordFile' not in text and 'LaunchKernels' not in text
    assert text.index('FeynRules`Commutator;') < text.index('Get[FileNameJoin[')
    assert text.index('FeynRules`MatrixSymbol;') < text.index('Get[FileNameJoin[')
    assert 'Unprotect[' not in text and 'Quiet[' not in text
    assert '$MessageList =' not in text
    assert 'CheckAbort[Check[Get[' in text and 'SameQ[systemBefore,systemAfter]' in text


@pytest.mark.parametrize('field,value',[
    ('mode','unknown'),('message_free_load',False),('message_free_load','True'),
    ('load_messages',['SetDelayed::write']),('system_definitions_unchanged',False),
    ('system_definitions_unchanged',1),('package_commutator_downvalues',0),
    ('package_commutator_downvalues',True),('package_matrix_symbol_downvalues',0),
    ('package_matrix_symbol_downvalues',8.0),
])
def test_namespace_collision_or_system_mutation_cannot_qualify(field,value):
    r=receipt();r['namespace_compatibility'][field]=value
    assert not bridge.adjudicate(r,config(),Path('/owned/feynrules'),123)['passed']


def test_old_readiness_without_namespace_witness_requires_fresh_qualification():
    r=receipt();r.pop('namespace_compatibility')
    assert not bridge.adjudicate(r,config(),Path('/owned/feynrules'),123)['passed']


def test_refusal_before_kernel_or_workspace_without_actual_worker(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db,'execute_native',lambda *a:pytest.fail('unapproved kernel call'))
    output=tmp_path/'output'
    with pytest.raises(ValueError,match='approved supervised'):bridge.run({'config':'absent'},tmp_path,output)
    assert not output.exists()
