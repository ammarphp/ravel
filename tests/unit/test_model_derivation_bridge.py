"""Mechanical source/receipt/handoff controls; no Wolfram or model execution."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from ravel.physics import model_derivation_bridge as bridge
from ravel.physics import model_tool_bridge as custody
from ravel.validation.model_tool_witness import card_values


def config():
    pin = {'path':'/bound/file','sha256':'a'*64}
    return {'schema_version':1,'operation':'feynrules-source-ufo','source':'Literal bound model source',
        'kernel':pin,'application_metadata':pin,'provider_tree':{'root':'/bound/provider','manifest':pin},
        'model_tree':{'root':'/bound/model','manifest':pin},'model_files':['SM.fr'],'restrictions':[],
        'lagrangian_symbol':'LSM','trusted_provider_source':True,'trusted_model_source':True,
        'provider_readiness_receipt':pin,'expected_kernel_version':14.3,'expected_provider_version':'2.3.49',
        'provider_readiness_run':{'path':'/qualified/run','attempt_id':'fixture','attempt_record':pin},
        'max_seconds':900,'max_ram_mib':8192}


def mass_row(name='h', calculated=125., model_file=125.):
    return {'particle':name,'analytic':'Sqrt[2 lam] vev',
            'calculated':{'real':calculated,'imag':0},'model_file':{'real':model_file,'imag':0}}


def native():
    return {'process_id':123,'kernel_version':14.3,'provider_version':'2.3.49',
        'provider_root':'/owned/provider','model_root':'/owned/model','export_root':'/owned/ufo',
        'model_files':['/owned/model/SM.fr'],'restrictions':[],'lagrangian_symbol':'LSM',
        'namespace_compatibility':{'mode':'package_context_symbols_v1','message_free_load':True,
            'load_messages':[],'system_definitions_unchanged':True,
            'package_commutator_downvalues':2,'package_matrix_symbol_downvalues':8},
        'source_loads':{'provider_load_without_messages':True,'model_load_without_messages':True,
            'requested_model_files':['/owned/model/SM.fr']},
        'restriction_loads':[],'electric_charge_symbol_defined':True,
        'lagrangian_defined':True,'lagrangian_nonzero':True,'lagrangian_leaf_count':100,
        'class_count':5,'parameter_count':10,'kinetic_result':True,'kinetic_result_expression':'True',
        'kinetic_nonzero':True,'kinetic_leaf_count':15,'kinetic_api_downvalues':1,'mass_api_downvalues':1,
        'kinetic_printed':'All kinetic terms are diagonal.\nAll kinetic terms are correctly normalized.',
        'mass_printed':'All mass terms are diagonal.','fermion_kinetic_witness':[],
        'mass_coefficients':[{'fields':['h','h'],'coefficient':{'real':-7812.5,'imag':0}}],
        'mass_rows':[mass_row()],'parallel_disabled':True,'parallel_kernels_list':True,
        'parallel_kernel_count':0,'decay_calculation_requested':False,'generated_events':0}


def adjudicate(receipt):
    return bridge.adjudicate(receipt,config(),Path('/owned/provider'),Path('/owned/model'),Path('/owned/ufo'),123)


def test_derivation_admission_is_nonvacuous_and_scoped():
    result = adjudicate(native())
    assert result['passed']
    assert result['mass_witness']['rows'][0]['relative_difference'] == 0
    assert 'returned' in result['scope']


@pytest.mark.parametrize('witness',[None,{}, {'message_free_load':True}])
def test_derivation_requires_complete_namespace_observations(witness):
    receipt=native();receipt['namespace_compatibility']=witness
    assert not adjudicate(receipt)['passed']


def test_derivation_rejects_system_mutation_even_with_successful_mass_checks():
    receipt=native();receipt['namespace_compatibility']['system_definitions_unchanged']=False
    result=adjudicate(receipt)
    assert result['mass_witness']['passed'] and not result['passed']


@pytest.mark.parametrize('field,value',[
    ('process_id',124),('process_id',True),('provider_root','/wrong'),('model_files',[]),
    ('restrictions',['implicit.rst']),('lagrangian_symbol','Other'),('lagrangian_defined',False),
    ('lagrangian_leaf_count',1),('class_count',0),('kinetic_result','True'),
    ('kinetic_result_expression','CheckKineticTerms[LSM]'),('kinetic_nonzero',False),
    ('kinetic_leaf_count',1),('kinetic_api_downvalues',0),('mass_api_downvalues',0),
    ('parallel_kernel_count',1),('parallel_kernel_count',False),('decay_calculation_requested',True),
    ('generated_events',1),('generated_events',False),
    ('electric_charge_symbol_defined',False),('restriction_loads',[{'path':'implicit.rst'}]),
])
def test_unevaluated_vacuous_wrong_source_or_unbounded_receipts_refused(field,value):
    receipt=native();receipt[field]=value
    assert not adjudicate(receipt)['passed']


CHIRAL_KINETIC = ('All kinetic terms are diagonal.\n'
                  'Warning: Kinetic term for {vx, vxbar} seems not to be correctly normalized.\n'
                  'Warning: Kinetic term for {vy, vybar} seems not to be correctly normalized.')
VANISHING_MASS = ('All mass terms are diagonal.\n'
                  'Warning: mass term for {S0, S0}seems not to have the correct sign.\n'
                  'Warning: mass term for {SP, SPbar}seems not to have the correct sign.')


def chiral_row(field, *, counts=(1,), projectors=('ProjM',), coefficient=(0, 1.0), in_mass=False):
    return {'fields':[field, field+'bar'],'monomials':len(counts),'projector_counts':list(counts),
            'projectors':list(projectors),'unprojected_coefficient':{'real':coefficient[0],'imag':coefficient[1]},
            'in_mass_terms':in_mass}


def mass_coefficient(a, b, real):
    return {'fields':[a, b],'coefficient':{'real':real,'imag':0}}


def chiral_receipt():
    """A receipt with the diagnostics a left-handed fermion and a vanishing scalar mass term produce."""
    receipt=native()
    receipt.update(kinetic_result=False,kinetic_result_expression='Null',kinetic_printed=CHIRAL_KINETIC,
                   fermion_kinetic_witness=[chiral_row('vx'),chiral_row('vy'),chiral_row('ex',counts=(1,1),
                                                                                       projectors=('ProjM','ProjP'))],
                   mass_printed=VANISHING_MASS,
                   mass_coefficients=[mass_coefficient('h','h',-7812.5),mass_coefficient('S0','S0',2.3e-13),
                                      mass_coefficient('SP','SPbar',4.5e-13),mass_coefficient('V','Vbar',6371.)])
    return receipt


def test_chiral_kinetic_and_vanishing_mass_diagnostics_are_adjudicated_not_ignored():
    result=adjudicate(chiral_receipt())
    assert result['passed'], result['checks']
    assert [w['fields'] for w in result['kinetic_diagnostics']['waived']]==[['vx','vxbar'],['vy','vybar']]
    assert [w['fields'] for w in result['mass_sign_diagnostics']['waived']]==[['S0','S0'],['SP','SPbar']]


@pytest.mark.parametrize('change',[
    {'counts':(0,)},                       # no projector: a genuinely non-canonical Dirac term
    {'counts':(1,2)},                      # a monomial with two projectors
    {'projectors':('ProjM','ProjP')},      # both chiralities: a Dirac field
    {'coefficient':(0,2.0)},               # chiral but twice the canonical normalization
    {'coefficient':(0.1,1.0)},
    {'in_mass':True},                      # a massive field needs both chiralities
])
def test_kinetic_warning_is_not_waived_without_the_chiral_canonical_witness(change):
    receipt=chiral_receipt();receipt['fermion_kinetic_witness'][0]=chiral_row('vx',**change)
    result=adjudicate(receipt)
    assert not result['passed'] and not result['checks']['evaluated_kinetic_normalisation']
    assert any('{vx, vxbar}' in f for f in result['kinetic_diagnostics']['failures'])


@pytest.mark.parametrize('mutate',[
    lambda r: r['mass_coefficients'].__setitem__(1, mass_coefficient('S0','S0',125.)),   # real wrong sign
    lambda r: r['mass_coefficients'].pop(1),                                              # no witness row
    lambda r: r.__setitem__('mass_printed', r['mass_printed']+'\nWarning: non numerical value encountered for {X, X}. Unable to get numerical value.'),
    lambda r: r.pop('mass_printed'),
])
def test_mass_sign_warning_is_not_waived_without_a_vanishing_coefficient(mutate):
    receipt=chiral_receipt();mutate(receipt)
    result=adjudicate(receipt)
    assert not result['passed'] and not result['checks']['adjudicated_mass_sign_diagnostics']


@pytest.mark.parametrize('mutate',[
    lambda r: r.pop('kinetic_printed'),
    lambda r: r.__setitem__('kinetic_printed','All kinetic terms are diagonal.'),     # Null without warnings
    lambda r: r.__setitem__('kinetic_result_expression','CheckKineticTermNormalisation[LSM]'),
    lambda r: r.__setitem__('kinetic_printed',CHIRAL_KINETIC+'\nWarning: non numerical value encountered for {vz, vzbar}. Unable to check normalisation.'),
])
def test_uncaptured_or_unexplained_kinetic_results_fail(mutate):
    receipt=chiral_receipt();mutate(receipt)
    assert not adjudicate(receipt)['checks']['evaluated_kinetic_normalisation']


def test_script_captures_printed_diagnostics_and_computes_the_witnesses():
    text=bridge.script(config(),Path('/p'),Path('/m'),Path('/e'),Path('/r.json'))
    assert '{kin, kinPrinted} = ravelPrinted[FeynRules`CheckKineticTermNormalisation[' in text
    assert '{spectrum, massPrinted} = ravelPrinted[FeynRules`GetMassSpectrum[' in text
    assert '"kinetic_printed"->kinPrinted,"mass_printed"->massPrinted' in text
    assert '"fermion_kinetic_witness"->fermionKinetic,"mass_coefficients"->massCoefficients' in text
    assert text.index('massRows = ') < text.index('fermionKinetic = ') < text.index('WriteUFO[')
    assert 'FeynRules`GetMassTerms[lag, FeynRules`FlavorExpand -> True]' in text


def test_provider_digest_pin_is_checked_when_configured(tmp_path):
    fr=tmp_path/'provider';(fr/'Core').mkdir(parents=True);(fr/'FeynRules.m').write_text('(* provider *)\n')
    digest=bridge.provider_digest(custody.source_tree(fr))
    c={**config(),'expected_provider_digest':digest}
    assert bridge.validate_config(c)==c
    receipt=native();receipt['provider_root']=str(fr)
    assert bridge.adjudicate(receipt,c,fr,Path('/owned/model'),Path('/owned/ufo'),123)['checks']['pinned_provider_digest']
    c['expected_provider_digest']='0'*64
    assert not bridge.adjudicate(receipt,c,fr,Path('/owned/model'),Path('/owned/ufo'),123)['passed']
    with pytest.raises(ValueError):bridge.validate_config({**config(),'expected_provider_digest':'latest'})


def test_plan_time_pin_refuses_a_different_provider_tree(tmp_path,monkeypatch):
    fr=tmp_path/'provider';fr.mkdir();(fr/'FeynRules.m').write_text('(* provider *)\n')
    digest=bridge.provider_digest(custody.source_tree(fr))
    monkeypatch.setattr(bridge,'pinned_provider_digest',lambda version:digest)
    assert bridge.provider_pin(fr,'2.3.49')==digest
    (fr/'FeynRules.m').write_text('(* changed *)\n')
    with pytest.raises(ValueError,match='differs from the pinned'):bridge.provider_pin(fr,'2.3.49')


def test_packaged_feynrules_pin_is_a_digest():
    pin=bridge.pinned_provider_digest('2.3.49')
    assert len(pin)==64 and int(pin,16) >= 0
    with pytest.raises(ValueError):bridge.pinned_provider_digest('9.9.9')


def test_python2_export_refusal_names_the_supported_conversion(tmp_path):
    (tmp_path/'object_library.py').write_text('class UFOError(Exception):\n    pass\n\n\ndef f():\n    raise UFOError, "x"\n')
    (tmp_path/'other.py').write_text('print "x"\n')
    tree=custody.source_tree(tmp_path)
    rows={r['file']:r for r in bridge.python_syntax_diagnostics(tmp_path,tree,'none')}
    assert 'feynrules-2.3.49-literal-UFOError-raise-v1' in rows['object_library.py']['remedy']
    assert 'remedy' not in rows['other.py']


def test_export_admission_refuses_a_charge_violating_vertex(tmp_path):
    from test_model_admission import ufo, VERTEX_HEAD, GOOD_VERTICES, vertex
    good=ufo(tmp_path/'good')
    assert bridge.export_admission(good,tmp_path)['decision']=='passed'
    assert json.loads((tmp_path/'export-static-admission.json').read_text())['kind']=='model-admission'
    bad=ufo(tmp_path/'bad',**{'vertices.py':VERTEX_HEAD+GOOD_VERTICES+vertex('V_9','e__minus__','e__minus__','a')})
    out=tmp_path/'o';out.mkdir()
    record=bridge.export_admission(bad,out)
    assert record['decision']=='refused' and 'V_9 charge sums to -2' in record['refusals'][0]


def test_mass_witness_recalculates_discrepancy_instead_of_accepting_printed_native_verdict():
    row=mass_row(calculated=125.2);row['native_status']='OK'
    with pytest.raises(ValueError):bridge.mass_witness([row])
    row.pop('native_status')
    assert not bridge.mass_witness([row])['passed']


@pytest.mark.parametrize('rows',[[],[mass_row(),mass_row()],
    [mass_row(calculated=float('nan'))],[mass_row(calculated=-1)],
    [mass_row(calculated=True)],[mass_row(calculated=0,model_file=0)],
    [{'malformed':'TableForm[GetMassSpectrum[LSM]]'}],
])
def test_invalid_empty_duplicate_and_massless_only_mass_populations_do_not_pass(rows):
    try:result=bridge.mass_witness(rows)
    except ValueError:return
    assert not result['passed']


@pytest.mark.parametrize('field,value',[
    ('trusted_model_source',False),('trusted_provider_source',False),('model_files',[]),
    ('model_files',['../model.fr']),('model_files',['SM.fr','SM.fr']),('model_files',[{}]),
    ('restrictions',['/tmp/hidden.rst']),('restrictions',['Default.fr']),
    ('lagrangian_symbol','Get["evil"]'),('lagrangian_symbol','Private`LSM'),
    ('max_seconds',901),('max_ram_mib',8193),('expected_provider_version','latest'),
])
def test_only_attributed_bounded_explicit_source_selection_allowed(field,value):
    document=config();document[field]=value
    with pytest.raises(ValueError):bridge.validate_config(document)


def test_script_follows_actual_api_and_explicit_export_controls():
    document=config();document['restrictions']=['DiagonalCKM.rst']
    text=bridge.script(document,Path('/private/provider'),Path('/private/model'),Path('/private/export'),Path('/private/result.json'))
    assert 'FR$Parallel = False' in text
    assert 'FeynRules`CheckKineticTermNormalisation[' in text and 'CheckKineticTerms[' not in text
    assert 'FeynRules`GetMassSpectrum[' in text and 'massRows' in text
    assert 'FeynRules`AddDecays -> False' in text and 'FeynRules`DialogBox -> Off' in text
    assert 'FeynRules`Optimization -> False' in text
    assert 'loadRestriction["/private/model/DiagonalCKM.rst"]' in text
    assert 'Check[FeynRules`LoadRestriction[file];True,False]' in text
    assert 'Clear[FeynRules`M$Restrictions]' in text and 'counter=PRIVATE`FR$restrictionCounter' in text
    assert 'FeynRules`PRIVATE`FR$restrictionCounter' not in text
    assert 'FeynRules`PRIVATE`MR$Restrictions' not in text
    assert 'loaded = CheckAbort[Check[Get[' in text and 'providerLoad = TrueQ[loaded]' in text
    assert text.startswith(bridge.provider.namespace_load_script(Path('/private/provider')))
    assert 'modelLoad=CheckAbort[Check[FeynRules`LoadModel[' in text
    assert text.index('Exit[2]') < text.index('CheckKineticTermNormalisation[') < text.index('WriteUFO[')
    assert 'Length[FeynRules`M$ClassesDescription]' in text and 'Global`M$ClassesDescription' not in text
    assert 'OwnValues[Global`LSM]' in text
    assert 'LaunchKernels' not in text and 'GetUFODecays[' not in text
    assert '$PasswordFile' not in text


PARAMETERS = """
from object_library import Parameter
ZERO=Parameter(name='ZERO', nature='internal', type='real', value='0.0')
M=Parameter(name='M', nature='external', type='real', value=125.0, lhablock='MASS', lhacode=[25])
V=Parameter(name='V', nature='external', type='real', value=0.23, lhablock='CKM', lhacode=[1,2])
W=Parameter(name='W', nature='external', type='real', value=0.004, lhablock='DECAY', lhacode=[25])
"""


def exported_model(exported,**overrides):
    """Synthetic exported UFO that the static export admission accepts.

    The export is admitted only with parsed vertices, Lorentz structures and declared
    mass and width parameters. parameters.py keeps this file's three external addresses.
    """
    from test_model_admission import FILES
    files={**FILES,'parameters.py':PARAMETERS,
        'particles.py':FILES['particles.py'].replace('Param.MS1','Param.M').replace('Param.WS1','Param.W'),**overrides}
    assert set(files)==set(bridge.REQUIRED_UFO)
    exported.mkdir()
    for name,text in files.items():(exported/name).write_text(text)
    return exported


def test_literal_source_card_preserves_every_address_and_value():
    text,rows=bridge.literal_external_card(PARAMETERS)
    assert len(rows)==3 and len(card_values(text))==3
    assert card_values(text)[('ckm',(1,2))]==0.23
    assert card_values(text)[('decay',(25,))]==0.004
    assert card_values(text)[('mass',(25,))]==125.
    assert all(type(row['source_line']) is int for row in rows)


@pytest.mark.parametrize('changed',[
    PARAMETERS.replace('value=125.0','value=default_mass()'),
    PARAMETERS.replace('value=125.0','value=True'),
    PARAMETERS.replace("name='M'","name='W'"),
    PARAMETERS.replace("lhablock='CKM', lhacode=[1,2]","lhablock='MASS', lhacode=[25]"),
    PARAMETERS.replace('value=0.004','value=-0.004'),
    PARAMETERS.replace("type='real', value=125.0","type='complex', value=125.0"),
    PARAMETERS.replace('lhacode=[1,2]','lhacode=[False,2]'),
    "X=Parameter(name='x',nature='internal',type='real',value='1')",
])
def test_card_never_evaluates_defaults_duplicates_complex_values_or_auto_widths(changed):
    with pytest.raises(ValueError):bridge.literal_external_card(changed)


def test_unsafe_exported_python_is_not_imported_for_card_selection(tmp_path):
    marker=tmp_path/'executed'
    changed=PARAMETERS.replace('value=125.0',"value=__import__('pathlib').Path("+repr(str(marker))+").touch()")
    with pytest.raises(ValueError):bridge.literal_external_card(changed)
    assert not marker.exists()


def readiness(root, kernel):
    native_provider={'provider_root':str(root),'process_id':123,'kernel_version':14.3,'kernel_arithmetic_control':4,
        'provider_loaded':True,'provider_version':'2.3.49','parallel_disabled':True,'parallel_kernels_list':True,
        'namespace_compatibility':native()['namespace_compatibility'],
        'parallel_kernel_count':0,'entrypoint_downvalues':{name:1 for name in bridge.provider.ENTRYPOINTS},
        'obsolete_undefined_entrypoint_downvalues':0,'model_calculation_performed':False,'generated_events':0}
    return {'status':'passed','physics_validated':False,'model_calculation_performed':False,'generated_events':0,
        'checks':bridge.provider.adjudicate(native_provider,config(),root,123),
        'native_provider':native_provider,
        'native_execution':{'returncode':0,'resource_violation':None,'command':[str(kernel),'-noinit']}}


@pytest.fixture
def bound(tmp_path,monkeypatch):
    fr=tmp_path/'provider';fr.mkdir()
    for name,content in [('FeynRules.m','fixture'),('FeynRulesPackage.m','FR$VersionNumber="2.3.49";'),('ToolBox.m','fixture')]:
        (fr/name).write_text(content)
    prior=tmp_path/'qualified-copy';shutil.copytree(fr,prior)
    model=tmp_path/'model';model.mkdir();(model/'SM.fr').write_text('LSM := fixture;')
    kernel=tmp_path/'kernel';kernel.write_text('mechanical fixture, never execute');kernel.chmod(0o700)
    metadata=tmp_path/'metadata';metadata.write_text('fixture')
    qualified=tmp_path/'qualified-run';(qualified/'outputs/attempt-1').mkdir(parents=True);(qualified/'inputs').mkdir()
    prior_receipt=qualified/'outputs/attempt-1/model-provider-bridge.json';custody._write(prior_receipt,readiness(prior,kernel))
    custody._write(prior_receipt.parent/'native-process.json',{'pid':123})
    pin=lambda p:{'path':str(p),'sha256':custody._hash(p)}
    def tree(root,name):
        manifest=tmp_path/name;custody._write(manifest,custody.source_tree(root));return {'root':str(root),'manifest':pin(manifest)}
    c=config();c.update(kernel=pin(kernel),application_metadata=pin(metadata),
        provider_tree=tree(fr,'provider.json'),model_tree=tree(model,'model.json'),provider_readiness_receipt=pin(prior_receipt))
    original={k:copy.deepcopy(c[k]) for k in ('schema_version','source','kernel','application_metadata','provider_tree',
        'trusted_provider_source','expected_kernel_version','expected_provider_version','max_seconds','max_ram_mib')}
    original.update(operation='wolfram-feynrules-readiness',existing_installation_license_status='unverified_no_activation_or_credentials_requested',
        max_seconds=60,max_ram_mib=2048)
    original_path=tmp_path/'original-qualified-config.json';custody._write(original_path,original)
    custody._write(qualified/'inputs/science.json',{'schema_version':2,'mode':'model-provider-bridge','task':{'config':str(original_path)}})
    # The planner's own plan version and fields; an unversioned plan is not a plan the approval can bind.
    custody._write(qualified/'inputs/science-plan.json',{'schema_version':2,'mode':'model-provider-bridge',
        'base_dir':str(tmp_path),'expert_review':False})
    custody._write(qualified/'inputs/checkin1.json',{'fixture':True})
    custody._write(qualified/'inputs/physics_review_policy.json',{'fixture':True})
    from ravel.workflow import science,accepted_prior_science
    custody._write(qualified/'inputs/science-approval.json',{'schema_version':2,'expert_review':False,
        'plan_sha256':custody._hash(qualified/'inputs/science-plan.json'),'checkin_sha256':custody._hash(qualified/'inputs/checkin1.json'),
        'input_fingerprint':science._approval_fingerprint(science.approval_input_paths(qualified))})
    record=qualified/'fixture-attempt.json';custody._write(record,{'scope':'mechanical fixture, no actual execution'})
    state={'stages':{'science':{'status':'succeeded','attempt_id':'fixture','attempt_record':str(record),
        'outputs':['outputs/attempt-1'],'input_snapshot':{str(original_path):{'kind':'file','files':[{'name':'.','sha256':custody._hash(original_path)}]}}}}}
    custody._write(qualified/'execution_state.json',state)
    review_file=qualified/'fixture-accepted-review.json'
    custody._write(review_file,{'scope':'mechanical accepted-review binding fixture, no actual review'})
    # This narrow adapter fixture does not establish prior acceptance. The public
    # approval/receipt/review replay is exercised in test_accepted_prior_science.
    monkeypatch.setattr(accepted_prior_science,'accepted',lambda *args,**kwargs:
        {'receipt':state['stages']['science'],'paths':[str(review_file)]})
    c['provider_readiness_run']={'path':str(qualified),'attempt_id':'fixture','attempt_record':pin(record)}
    config_path=tmp_path/'config.json';custody._write(config_path,c)
    return tmp_path,c,config_path,prior,prior_receipt


def test_preparation_binds_actual_qualified_source_copy_and_never_executes(bound):
    base,c,path,prior,receipt=bound
    rows=bridge.inputs({'config':str(path)},base)
    assert receipt in rows and base/'original-qualified-config.json' in rows


def test_changed_originally_qualified_source_is_refused(bound):
    base,c,path,prior,receipt=bound
    (base/'provider/ToolBox.m').write_text('changed')
    with pytest.raises(ValueError):
        bridge.inputs({'config':str(path)},base)


def test_previously_qualified_other_kernel_is_refused(bound):
    base,c,path,prior,receipt=bound
    raw=json.loads(receipt.read_text());raw['native_execution']['command'][0]='/other/kernel'
    custody._write(receipt,raw);c['provider_readiness_receipt']['sha256']=custody._hash(receipt);custody._write(path,c)
    with pytest.raises(ValueError,match='qualified kernel command'):
        bridge.inputs({'config':str(path)},base)


def test_no_actual_worker_means_no_kernel_or_workspace(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db,'execute_native',lambda *a:pytest.fail('unapproved derivation call'))
    output=tmp_path/'output'
    with pytest.raises(ValueError,match='approved supervised'):
        bridge.run({'config':'missing'},tmp_path,output)
    assert not output.exists()


@pytest.mark.parametrize('passes',[True,False])
def test_mechanical_export_handoff_stays_inside_receipt_bound_output_tree(bound,monkeypatch,passes):
    """The derived scientific bytes, not just their path, must enter the receipt."""
    base,c,path,prior,receipt=bound
    out=base/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda task,output:(base,{'max_seconds':900}))
    from ravel.physics import reinterpret_db
    def fixture_native(command,output,document):
        assert command[1:4]==['-noinit','-noprompt','-script']
        work=base/'work/model-derivation-bridge/attempt-1'
        exported=exported_model(output/'exported-ufo')
        raw=native();raw.update(provider_root=str(work/'feynrules'),model_root=str(work/'model_source'),
            export_root=str(exported),model_files=[str(work/'model_source/SM.fr')])
        raw['source_loads']['requested_model_files']=raw['model_files'][:]
        if not passes:raw.update(kinetic_result=False,kinetic_result_expression='Null')
        custody._write(output/'native-derivation.json',raw)
        custody._write(output/'native-process.json',{'pid':123})
        return {'returncode':0,'command':command,'scope':'mechanical fixture, no execution'}
    monkeypatch.setattr(reinterpret_db,'execute_native',fixture_native)
    result=bridge.run({'config':str(path)},base,out)
    assert result['export_diagnostics']==[]
    assert json.loads((out/'export-static-admission.json').read_text())['decision']=='passed'
    assert result['status']==('passed' if passes else 'failed') and result['physics_validated'] is False
    exported=Path(result['exported_source']['ufo'])
    assert exported.is_relative_to(out) and (exported/'parameters.py').is_file()
    assert len(result['exported_source']['external_parameters'])==3
    assert result['exported_source']['native_madgraph_run_performed'] is False
    candidate=out/'model-tool-handoff-candidate.json'
    if passes:
        handoff=json.loads(candidate.read_text())
        assert handoff['derivation_result']['sha256']==custody._hash(out/'model-derivation-bridge.json')
        assert handoff['requires_successful_supervised_derivation_receipt_and_scoped_review'] is True
    else:assert not candidate.exists()
    assert json.loads((out/'exported-ufo-source.json').read_text())==custody.source_tree(exported)


def restriction_report():
    return {'path':'/model/DiagonalCKM.rst','load_without_messages':True,'rules_are_valid':True,
        'source_rule_count':3,'processed_rule_count':3,'registry_count_before':0,'registry_count_after':6,
        'evaluated_rule_expressions':['CKM[i_,i_]->1','CKM[i_,j_]:>0','cabi->0']}


@pytest.mark.parametrize('field,value',[('load_without_messages',False),('rules_are_valid',False),
    ('source_rule_count',0),('processed_rule_count',2),('processed_rule_count',True),
    ('registry_count_after',0),('evaluated_rule_expressions',[]),('path','/implicit/other.rst')])
def test_missing_stale_unevaluated_or_unregistered_restrictions_fail(field,value):
    c=config();c['restrictions']=['DiagonalCKM.rst'];r=restriction_report();r[field]=value
    assert not bridge.restriction_witness([r],c,Path('/model'))


def test_effective_rule_census_not_path_echo_is_required():
    c=config();c['restrictions']=['DiagonalCKM.rst']
    assert bridge.restriction_witness([restriction_report()],c,Path('/model'))
    assert not bridge.restriction_witness([],c,Path('/model'))


@pytest.mark.parametrize('field,value',[('provider_load_without_messages',False),
    ('provider_load_without_messages',1),('model_load_without_messages',False),('model_load_without_messages','True'),
    ('model_load_without_messages',1),
    ('requested_model_files',[]),('requested_model_files',['/owned/model/other.fr'])])
def test_good_aggregate_model_does_not_override_failed_source_loading(field,value):
    raw=native();raw['source_loads'][field]=value
    assert not adjudicate(raw)['passed']


def test_valid_base_plus_failed_extension_cannot_pass_by_echoing_requested_paths():
    c=config();c['model_files'].append('Extension.fr')
    raw=native();raw['model_files'].append('/owned/model/Extension.fr')
    raw['source_loads']['requested_model_files']=raw['model_files'][:]
    raw['source_loads']['model_load_without_messages']=False
    result=bridge.adjudicate(raw,c,Path('/owned/provider'),Path('/owned/model'),Path('/owned/ufo'),123)
    assert result['checks']['nonvacuous_model'] is True
    assert result['checks']['literal_source_selection'] is True
    assert result['checks']['complete_message_free_source_load'] is False
    assert result['passed'] is False


def test_masked_or_unreported_native_mass_population_is_quarantined():
    result=bridge.mass_witness([mass_row()])
    assert result['passed'] and result['complete_mass_population_checked'] is False
    assert 'negative/imaginary' in result['quarantine'] and 'complete' in result['scope']


def test_replaced_kernel_at_same_path_cannot_reuse_old_qualification(bound):
    base,c,path,prior,receipt=bound
    kernel=Path(c['kernel']['path']);kernel.write_text('replacement kernel, still never execute')
    c['kernel']['sha256']=custody._hash(kernel);custody._write(path,c)
    with pytest.raises(ValueError,match='originally qualified bytes'):
        bridge.inputs({'config':str(path)},base)


def test_rewritten_qualified_config_cannot_replace_original_closed_stage_commitment(bound):
    base,c,path,prior,receipt=bound
    original=base/'original-qualified-config.json';document=json.loads(original.read_text())
    document['source']='rewritten after the claimed original execution';custody._write(original,document)
    with pytest.raises(ValueError,match='closed-stage bytes'):
        bridge.inputs({'config':str(path)},base)


def test_mutating_both_source_copies_does_not_establish_historical_readiness(bound):
    base,c,path,prior,receipt=bound
    (base/'provider/ToolBox.m').write_text('same new bytes in both mutable copies')
    (prior/'ToolBox.m').write_text('same new bytes in both mutable copies')
    manifest=Path(c['provider_tree']['manifest']['path'])
    custody._write(manifest,custody.source_tree(base/'provider'))
    c['provider_tree']['manifest']['sha256']=custody._hash(manifest);custody._write(path,c)
    with pytest.raises(ValueError,match='source pin changed'):
        bridge.inputs({'config':str(path)},base)


def test_arbitrary_true_check_labels_are_not_native_readiness(bound):
    base,c,path,prior,receipt=bound
    previous=json.loads(receipt.read_text());previous['checks']['checks']={'arbitrary':True}
    with pytest.raises(ValueError,match='readiness receipt'):bridge.qualified_receipt(previous)


@pytest.mark.parametrize('version',[14.3,15.0])
def test_derivation_version_follows_qualified_runtime_and_observed_kernel(version):
    c=config();c['expected_kernel_version']=version
    bridge.validate_config(c)
    receipt=native();receipt['kernel_version']=version
    paths=(Path('/owned/provider'),Path('/owned/model'),Path('/owned/ufo'),123)
    assert bridge.adjudicate(receipt,c,*paths)['passed']
    receipt['kernel_version']=15.0 if version==14.3 else 14.3
    assert not bridge.adjudicate(receipt,c,*paths)['checks']['qualified_versions']
    prior=readiness(Path('/provider'),Path('/kernel'))
    prior['native_provider']['kernel_version']=version
    assert bridge.qualified_receipt(prior,version) is prior
    with pytest.raises(ValueError,match='runtime differs'):
        bridge.qualified_receipt(prior,15.0 if version==14.3 else 14.3)


@pytest.mark.parametrize('version',[True,'15.0',16.0,float('nan'),float('inf'),None])
def test_derivation_and_readiness_reject_unbound_or_malformed_version(version):
    c=config();c['expected_kernel_version']=version
    with pytest.raises(ValueError):bridge.validate_config(c)
    prior=readiness(Path('/provider'),Path('/kernel'))
    prior['native_provider']['kernel_version']=version
    with pytest.raises(ValueError):bridge.qualified_receipt(prior)


def test_new_derivation_version_cannot_relabel_old_readiness(bound):
    base,c,path,prior,receipt=bound
    c['expected_kernel_version']=15.0;custody._write(path,c)
    with pytest.raises(ValueError,match='version differs from original'):
        bridge.inputs({'config':str(path)},base)


@pytest.mark.parametrize('state',['awaiting_review','send_back','scientific_hold','stopped'])
def test_succeeded_readiness_without_accepted_review_cannot_feed_derivation(bound,monkeypatch,state):
    from ravel.workflow import accepted_prior_science
    base,c,path,prior,receipt=bound
    def refuse(*args,**kwargs):
        raise ValueError('prior review does not authorize reuse: '+state)
    monkeypatch.setattr(accepted_prior_science,'accepted',refuse)
    with pytest.raises(ValueError,match='prior review does not authorize reuse'):
        bridge.inputs({'config':str(path)},base)


def test_derivation_rechecks_review_scope_live_reuse_gate_and_binds_review_bytes(bound,monkeypatch):
    from ravel.workflow import accepted_prior_science
    base,c,path,prior,receipt=bound
    proof=bridge.inputs({'config':str(path)},base)
    assert base/'qualified-run/fixture-accepted-review.json' in proof
    def held(*args,**kwargs):
        raise ValueError('prior review does not authorize reuse: new scientific hold')
    monkeypatch.setattr(accepted_prior_science,'accepted',held)
    with pytest.raises(ValueError,match='new scientific hold'):
        bridge.inputs({'config':str(path)},base)
    def unrelated(*args,**kwargs):
        raise ValueError('prior accepted claim scope differs')
    monkeypatch.setattr(accepted_prior_science,'accepted',unrelated)
    with pytest.raises(ValueError,match='claim scope differs'):
        bridge.inputs({'config':str(path)},base)


def test_candidate_cannot_be_qualified_before_actual_scoped_review(tmp_path,monkeypatch):
    from ravel.workflow import science,execution,physics_review
    monkeypatch.setattr(science,'verify_approval_envelope',lambda root:[])
    monkeypatch.setattr(execution,'stage_errors',lambda *args:[])
    monkeypatch.setattr(physics_review,'status',lambda root:{'state':'awaiting_review','claim_scope':None})
    with pytest.raises(ValueError,match='actual accepted'):
        bridge.qualified_handoff(tmp_path,tmp_path/'qualified.json')
    assert not (tmp_path/'qualified.json').exists()


from ravel.physics import model_physical_checks as physical

def physical_request_fixture():
    f = lambda name, anti=False: {'symbol': name, 'antiparticle': anti}
    return {'schema_version': 1, 'hermiticity': True, 'feynman_gauge': True, 'partial_widths': {'mass_unit': 'GeV', 'width_unit': 'GeV', 'simplify_decays': True, 'channels': [{'id': 'H-muon-pair', 'parent': f('H'), 'daughters': [f('mu'), f('mu', True)], 'reference': {'kind': 'scalar-dirac-yukawa', 'coupling_numerator': 'ymm', 'coupling_denominator': 'vev', 'color_multiplicity': 1, 'source_interaction': 'L_int = -(ymm/vev) H bar(mu) mu', 'source_basis': {'path': 'SM.fr', 'sha256': 'a' * 64}, 'absolute_tolerance': 1e-12, 'relative_tolerance': 1e-07}}]}}

def physical_number_fixture(x):
    return {'real': x, 'imag': 0}

def physical_native_fixture(r=None):
    r = r or physical_request_fixture()
    value = physical.scalar_dirac_width(125, 0.10566, 0.10566 / 246, 1)
    return {'schema_version': 1, 'request': copy.deepcopy(r), 'gauge_before': 'True', 'gauge_after': 'True', 'hermiticity': {'requested': True, 'message_free': True, 'returned_list': True, 'vertex_count': 0, 'expression': '{}'}, 'widths_message_free': True, 'vertices_returned_list': True, 'vertex_count': 1, 'widths_returned_list': True, 'raw_width_rows': [{'fields': ['H', 'mu', 'mubar'], 'symbolic': 'ymm^2 MH (1-4 MMU^2/MH^2)^(3/2)/(8 Pi vev^2)', 'numeric': physical_number_fixture(value)}], 'channels': [{'request': copy.deepcopy(r['partial_widths']['channels'][0]), 'resolved_fields': ['H', 'mu', 'mubar'], 'fields_recognized': True, 'parent_scalar': True, 'daughters_dirac': True, 'masses': [physical_number_fixture(125), physical_number_fixture(0.10566), physical_number_fixture(0.10566)], 'matched_count': 1, 'raw_row_index': 0}], 'parameters': {'ymm': physical_number_fixture(0.10566), 'vev': physical_number_fixture(246)}, 'partial_width_cache_before': '{}', 'partial_width_cache_after': '{}', 'selected_supplied_widths_before': [physical_number_fixture(0.004)], 'selected_supplied_widths_after': [physical_number_fixture(0.004)], 'global_partial_width_cache_written': False, 'total_width_card_updated': False}

@pytest.mark.parametrize('match',[True,False])
def test_connected_requested_physical_checks_keep_actual_export_card_and_failed_results(bound,monkeypatch,match):
    """Full bridge body with explicit native/approval stand-ins; zero kernel calls."""
    base,c,path,prior,receipt=bound
    c['physical_checks']=physical_request_fixture()
    reference=c['physical_checks']['partial_widths']['channels'][0]['reference']
    basis=base/'model/SM.fr';reference['source_basis']={'path':str(basis),'sha256':custody._hash(basis)}
    custody._write(path,c)
    assert basis in bridge.inputs({'config':str(path)},base)
    out=base/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda task,output:(base,{'max_seconds':900}))
    from ravel.physics import reinterpret_db
    def fixture_native(command,output,document):
        assert command[1:4]==['-noinit','-noprompt','-script']
        text=Path(command[-1]).read_text()
        assert 'System`Save->False' in text and 'FeynRules`AddDecays -> False' in text
        work=base/'work/model-derivation-bridge/attempt-1'
        exported=exported_model(output/'exported-ufo')
        raw=native();raw.update(provider_root=str(work/'feynrules'),model_root=str(work/'model_source'),
            export_root=str(exported),model_files=[str(work/'model_source/SM.fr')],decay_calculation_requested=True)
        raw['source_loads']['requested_model_files']=raw['model_files'][:]
        raw['physical_checks']=physical_native_fixture(c['physical_checks'])
        if not match:raw['physical_checks']['raw_width_rows'][0]['numeric']['real']*=2
        custody._write(output/'native-derivation.json',raw);custody._write(output/'native-process.json',{'pid':123})
        return {'returncode':0,'command':command,'scope':'mechanical stand-in; no kernel or model execution'}
    monkeypatch.setattr(reinterpret_db,'execute_native',fixture_native)
    outcome=bridge.run({'config':str(path)},base,out)
    assert outcome['status']==('passed' if match else 'failed')
    assert outcome['requested_physical_checks']==c['physical_checks']
    assert outcome['decay_calculation_requested'] and not outcome['physics_validated']
    card=card_values((out/'exported-source-card.dat').read_text())
    assert card[('decay',(25,))]==.004 # selected partial width never substitutes total width
    handoff=out/'model-tool-handoff-candidate.json'
    assert handoff.exists() is match
    if match:
        retained=custody._read(handoff)
        assert retained['physical_checks']['passed'] and retained['total_width_substitution_requested'] is False
        assert retained['execution_authority_granted'] is False
