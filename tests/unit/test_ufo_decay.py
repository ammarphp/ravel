"""Source-safe scientific construction controls; no native/model/tool process."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

import pytest
from ravel.physics import ufo_decay as u
from ravel.physics import diagrammatica_code as d
from ravel.physics import model_tool_bridge as custody


@pytest.fixture(autouse=True)
def prohibit_process(monkeypatch):
    def deny(*a,**k): raise OSError('source-only control prohibits external process; identity fallback only')
    monkeypatch.setattr(subprocess,'Popen',deny);monkeypatch.setattr(os,'system',deny)


def pin(path): return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def external(name,block,index,value):
    return f"{name}=Parameter(name='{name}',nature='external',type='real',value={value!r},lhablock='{block}',lhacode=[{index}])\n"


def particle(symbol,pdg,spin,color,mass,charge=0,anti=None):
    return f"{symbol}=Particle(name='{symbol}',antiname='{anti or symbol}',pdg_code={pdg},spin={spin},color={color},mass=Param.{mass},width=Param.ZERO,charge={charge})\n"


def fixture(tmp_path,family='SFF',same=False,triplet=False):
    model=tmp_path/'ufo';model.mkdir()
    (model/'__init__.py').write_text('raise RuntimeError("UFO must never be imported")\n')
    (model/'object_library.py').write_text('raise RuntimeError("UFO constructors must not execute")\n')
    params=external('MX','MASS',25,13)+external('MF','MASS',11,2)+external('Y','YUKAWA',11,.2)
    params+="ZERO=Parameter(name='ZERO',nature='internal',type='real',value='0.0')\n"
    params+="phase=Parameter(name='phase',nature='internal',type='complex',value='complex(0,1)*Y')\n"
    (model/'parameters.py').write_text(params)
    (model/'function_library.py').write_text("complexconjugate=Function(name='complexconjugate',arguments=('z',),expression='z.conjugate()')\n")
    if family=='SSS':
        ps=particle('X',25,1,1,'MX')+particle('s',11,1,1,'MF')
        if not same: ps+=particle('t',12,1,1,'MF')
        incidence="[P.s,P.s,P.X]" if same else "[P.s,P.t,P.X]"
        tensors="SSS=Lorentz(name='SSS',spins=[1,1,1],structure='1')\n"
        coefficient="C1=Coupling(name='C1',value='complex(0,1)*Y',order={'QED':1})\n"
        vertex=f"V=Vertex(name='V',particles={incidence},color=['1'],lorentz=[L.SSS],couplings={{(0,0):C.C1}})\n"
    else:
        ps=particle('X',25,1 if family=='SFF' else 3,1,'MX')+particle('f',11,2,3 if triplet else 1,'MF',-1,'fbar')+'fbar=f.anti()\n'
        spin=1 if family=='SFF' else 3
        tensors=f"LEFT=Lorentz(name='LEFT',spins=[2,2,{spin}],structure='{('ProjM(2,1)' if family=='SFF' else 'Gamma(3,2,-1)*ProjM(-1,1)')}')\n"
        tensors+=f"RIGHT=Lorentz(name='RIGHT',spins=[2,2,{spin}],structure='{('ProjP(2,1)' if family=='SFF' else 'Gamma(3,2,-1)*ProjP(-1,1)')}')\n"
        coefficient="C1=Coupling(name='C1',value='complex(0,1)*(Y+phase)',order={'QED':1})\nC2=Coupling(name='C2',value='complex(0,1)*(2*Y-complexconjugate(phase))',order={'QED':1})\n"
        color='Identity(1,2)' if triplet else '1'
        vertex=f"V=Vertex(name='V',particles=[P.fbar,P.f,P.X],color=['{color}'],lorentz=[L.LEFT,L.RIGHT],couplings={{(0,1):C.C2,(0,0):C.C1}})\n"
    for name,text in [('particles.py',ps),('lorentz.py',tensors),('couplings.py',coefficient),('vertices.py',vertex)]: (model/name).write_text(text)
    card=tmp_path/'point.dat';card.write_text('BLOCK MASS\n25 13\n11 2\nBLOCK YUKAWA\n11 .2\n')
    manifest=tmp_path/'ufo-source.json';custody._write(manifest,custody.source_tree(model))
    backend_root=os.environ.get('RAVEL_HEPTAPOD_TEST_SOURCE')
    backend={rel: {'path':str(Path(backend_root)/rel) if backend_root else 'NOT-SUPPLIED/'+rel,'sha256':digest} for rel,digest in d.BACKEND.items()}
    doc={'schema_version':2,'operation':u.OPERATION,'units':'GeV','source':'explicit synthetic declared tree source, not a validated BSM model',
         'model_tree':{'root':str(model),'manifest':pin(manifest)},'parameter_card':pin(card),'parent_pdg':25,'vertex':'V',
         'release':d.RELEASE,'backend_files':backend,'max_seconds':20}
    request=tmp_path/'request.json';custody._write(request,doc)
    return {'input':str(request)},doc,model,card,manifest,request


def refresh(doc,model,card,manifest,request):
    custody._write(manifest,custody.source_tree(model));doc['model_tree']['manifest']=pin(manifest);doc['parameter_card']=pin(card);custody._write(request,doc)


def compile_local(doc,model,card,manifest,request):
    captured={str(p):p.read_bytes() for p in [request,card,*model.iterdir()] if p.is_file()}
    return u._compile(doc,request,model,card,captured)


@pytest.mark.parametrize('family,same,triplet',[('SSS',False,False),('SSS',True,False),('SFF',False,False),('SFF',False,True),('VFF',False,False),('VFF',False,True)])
def test_complete_selected_coefficient_mapping(tmp_path,family,same,triplet):
    task,doc,model,card,manifest,request=fixture(tmp_path,family,same,triplet)
    compiled,details=compile_local(doc,model,card,manifest,request)
    assert d._diagram(compiled)[1]==family and details['family']==family
    assert details['external_card_address_count']==3
    assert not details['whole_model_evaluated'] and not details['source_UFO_Python_imported']
    assert details['tree_reference']['partial_width_GeV']>0
    assert details['tree_reference']['identical_final_symmetry_divisor']==(2 if same else 1)
    assert details['tree_reference']['final_color_sum']==(3 if triplet else 1)
    if family!='SSS':
        assert details['coefficient_coordinates']['gL']=={'real':.2,'imag':.2}
        assert details['coefficient_coordinates']['gR']=={'real':.4,'imag':.2}
        assert [r['source_index'] for r in details['selected_lorentz_coupling_rows']]==[[0,1],[0,0]]
        assert set(details['selected_parameter_evaluation'])=={'Y','phase','ZERO','MX','MF'}


def test_source_card_overrides_yukawa_and_mass_separately(tmp_path):
    task,doc,model,card,manifest,request=fixture(tmp_path)
    card.write_text(card.read_text().replace('11 .2','11 .4').replace('11 2','11 3'))
    refresh(doc,model,card,manifest,request);_,details=compile_local(doc,model,card,manifest,request)
    assert details['coefficient_coordinates']['gL']=={'real':.4,'imag':.4}
    assert details['tree_reference']['three_masses_GeV']==[13.,3.,3.]
    assert details['supplied_total_widths_GeV']==[0.,0.,0.] and not details['tree_reference']['supplied_total_width_replaced']


@pytest.mark.parametrize('mutation',[
    lambda s:s.replace('11 .2','11 .2\n11 .3'),
    lambda s:s.replace('11 .2',''),
    lambda s:s+'BLOCK EXTRA\n1 9\n',
    lambda s:s.replace('25 13','25 -13'),
    lambda s:s.replace('25 13','25 4'),
    lambda s:s.replace('11 .2','11 nan'),
    lambda s:s.replace('11 .2','11 0'),
])
def test_bad_points_do_not_become_constructed_decays(tmp_path,mutation):
    task,doc,model,card,manifest,request=fixture(tmp_path);card.write_text(mutation(card.read_text()));refresh(doc,model,card,manifest,request)
    with pytest.raises(ValueError): compile_local(doc,model,card,manifest,request)


@pytest.mark.parametrize('name,old,new',[
    ('vertices.py','(0,1):C.C2','(0,0):C.C2'),
    ('vertices.py','C.C2','C.MISSING'),
    ('vertices.py','P.fbar,P.f,P.X','P.f,P.fbar,P.X'),
    ('vertices.py','P.fbar,P.f,P.X','P.fbar,P.f,P.X,P.X'),
    ('vertices.py',"color=['1']","color=['Identity(1,2)']"),
    ('lorentz.py','ProjM(2,1)','P(1,2)*ProjM(2,1)'),
    ('lorentz.py','spins=[2,2,1]','spins=[2,2,3]'),
    ('lorentz.py',"structure='ProjM(2,1)'","structure='ProjM(2,1)',formfactor='x'"),
    ('couplings.py','Y+phase',"__import__('os').system('true')"),
    ('parameters.py','complex(0,1)*Y','phase+Y'),
    ('parameters.py','complex(0,1)*Y','missing+Y'),
    ('particles.py','color=1,mass=Param.MF','color=8,mass=Param.MF'),
    ('particles.py',"antiname='fbar'","antiname='f'"),
    ('particles.py','width=Param.ZERO,charge=-1','width=Param.ZERO,charge=-1,GhostNumber=1'),
    ('particles.py','spin=1','spin=True'),
    ('particles.py','color=1','color=True'),
])
def test_source_semantics_refuse_uninterpreted_changes(tmp_path,name,old,new):
    task,doc,model,card,manifest,request=fixture(tmp_path)
    path=model/name;assert old in path.read_text();path.write_text(path.read_text().replace(old,new));refresh(doc,model,card,manifest,request)
    with pytest.raises((ValueError,SyntaxError)): compile_local(doc,model,card,manifest,request)


def test_parameter_type_no_imaginary_part_discard(tmp_path):
    task,doc,model,card,manifest,request=fixture(tmp_path)
    p=model/'parameters.py';p.write_text(p.read_text().replace("name='phase',nature='internal',type='complex'","name='phase',nature='internal',type='real'"))
    with pytest.raises(ValueError,match='declared real'):compile_local(doc,model,card,manifest,request)


@pytest.mark.parametrize('structure,family,expected',[
    ('ProjM(2,1)+ProjP(2,1)','SFF',(1,1)),
    ('ProjM(2,1)-ProjP(2,1)','SFF',(1,-1)),
    ('Gamma5(2,1)','SFF',(-1,1)),
    ('2*Gamma(3,2,-1)*ProjM(-1,1)','VFF',(2,0)),
    ('Gamma(3,2,-1)*ProjM(-1,1)-2*Gamma(3,2,-1)*ProjP(-1,1)','VFF',(1,-2)),
    ('Gamma(3,2,1)','VFF',(1,1)),
])
def test_basis_uses_explicit_projectors(structure,family,expected):
    assert u._linear(structure,family)==expected


@pytest.mark.parametrize('structure,family',[
    ('ProjM(1,2)','SFF'),('Gamma(3,2,1)*ProjM(-1,1)','VFF'),
    ('ProjM(-1,1)*Gamma(3,2,-1)','VFF'),('Sigma(3,1,2,1)','VFF'),('Identity(2,1)','VFF'),
])
def test_no_guessed_matrix_contractions(structure,family):
    with pytest.raises(ValueError):u._linear(structure,family)


def test_scalar_and_vector_closed_form_limits():
    m,f,g=125.,4.7,.024
    scalar=u.tree_reference('SFF',[m,f,f],{'gL':g,'gR':g},3)
    expected=3*g*g*m/(8*math.pi)*(1-4*f*f/m/m)**1.5
    assert scalar['partial_width_GeV']==pytest.approx(expected,rel=1e-14)
    vector=u.tree_reference('VFF',[m,f,f],{'gL':g,'gR':g},3)
    expected=3*g*g*m/(12*math.pi)*(1+2*f*f/m/m)*math.sqrt(1-4*f*f/m/m)
    assert vector['partial_width_GeV']==pytest.approx(expected,rel=1e-14)
    axial=u.tree_reference('VFF',[m,f,f],{'gL':-g,'gR':g},3)
    assert axial['partial_width_GeV']==pytest.approx(3*g*g*m/(12*math.pi)*(1-4*f*f/m/m)**1.5,rel=1e-14)


# Independent small Dirac matrix trace, not the product closed-form algebra.
def trace_reference(family,masses,left,right):
    zero=lambda:[[0j]*4 for _ in range(4)]
    def add(a,b): return [[a[i][j]+b[i][j] for j in range(4)] for i in range(4)]
    def scale(c,a):return [[c*a[i][j] for j in range(4)] for i in range(4)]
    def mul(a,b):return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    eye=zero()
    for i in range(4):eye[i][i]=1
    g0=zero()
    for i in range(4):g0[i][i]=1 if i<2 else -1
    gammas=[g0]
    for pauli in ([[0,1],[1,0]],[[0,-1j],[1j,0]],[[1,0],[0,-1]]):
        g=zero()
        for i in range(2):
            for j in range(2):g[i][j+2]=pauli[i][j];g[i+2][j]=-pauli[i][j]
        gammas.append(g)
    g5=scale(1j,mul(mul(mul(gammas[0],gammas[1]),gammas[2]),gammas[3]))
    project=add(scale(left/2,add(eye,scale(-1,g5))),scale(right/2,add(eye,g5)))
    m,a,b=masses;p=math.sqrt((m*m-(a+b)**2)*(m*m-(a-b)**2))/(2*m)
    e1=(m*m+a*a-b*b)/(2*m);e2=m-e1
    first=add(add(scale(e1,g0),scale(-p,gammas[3])),scale(a,eye))
    second=add(add(scale(e2,g0),scale(p,gammas[3])),scale(-b,eye))
    total=0j
    for vertex in ([project] if family=='SFF' else [mul(g,project) for g in gammas[1:]]):
        dag=[[vertex[j][i].conjugate() for j in range(4)] for i in range(4)]
        bar=mul(mul(g0,dag),g0)
        matrix=mul(mul(mul(first,vertex),second),bar);total+=sum(matrix[i][i] for i in range(4))
    assert abs(total.imag)<1e-9
    return total.real


@pytest.mark.parametrize('family',['SFF','VFF'])
@pytest.mark.parametrize('masses,left,right',[
    ([13.,2.,2.],.2+.3j,-.4+.1j),([13.,2.,3.],.2+.3j,.4-.1j),
    ([125.,4.7,4.7],-.023, -.023),([15.,0.,0.],.1j,.0),
    ([10.0001,5.,5.],1.,-1.),
])
def test_complex_interference_against_independent_trace(family,masses,left,right):
    reference=u.tree_reference(family,masses,{'gL':left,'gR':right},1)
    assert reference['spin_polarization_sum_without_color']==pytest.approx(trace_reference(family,masses,left,right),rel=1e-10,abs=1e-10)


def retained_backend():
    source=os.environ.get('RAVEL_HEPTAPOD_TEST_SOURCE')
    if not source:pytest.skip('exact inspected optional GPL HEPTAPOD fixture not supplied')
    for rel,digest in d.BACKEND.items():assert pin(Path(source)/rel)['sha256']==digest
    return source


def test_actual_released_backend_through_ordinary_mode(tmp_path):
    retained_backend();task,doc,model,card,manifest,request=fixture(tmp_path,'VFF',triplet=True)
    assert request in d.inputs(task,tmp_path) and d.execution_seconds(task,tmp_path)==20
    r=d.run(task,tmp_path,tmp_path/'output')
    assert r['status']=='passed' and r['native_calls']==0 and not r['physics_validated']
    assert r==custody._read(tmp_path/'output/ufo-decay-construction.json')
    script=(tmp_path/'output/decay-supplied-point.wl').read_text()
    assert 'gL -> Complex[0.20000000000000001,0.20000000000000001]' in script
    assert script.index('ampCC = ampCC /.') < script.index('ravelPointRules =')
    assert 'gL = ' not in script and 'gR = ' not in script
    assert 'nInit = 3;' in script and 'colorFactor = 3;' in script
    assert (tmp_path/'output/diagrammatica/upstream-symbolic.wl').is_file()
    assert r['selected_construction']['tree_reference']['native_amplitude_evaluated'] is False


def test_actual_source_standard_model_bottom_and_z(tmp_path):
    retained_backend();source=os.environ.get('RAVEL_UFO_SM_TEST_SOURCE')
    if not source:pytest.skip('original retained MG5 SM source not supplied')
    model=Path(source)
    from ravel.physics import model_derivation_bridge
    text,rows=model_derivation_bridge.literal_external_card((model/'parameters.py').read_text())
    card=tmp_path/'explicit-full-export-default-card.dat';card.write_text(text)
    manifest=tmp_path/'source.json';custody._write(manifest,custody.source_tree(model))
    doc={'schema_version':2,'operation':u.OPERATION,'units':'GeV','source':'Retained actual MG5 SM source; explicit full source-default card derivative, no import/native check',
        'model_tree':{'root':str(model),'manifest':pin(manifest)},'parameter_card':pin(card),'parent_pdg':25,'vertex':'V_78',
        'release':d.RELEASE,'backend_files':{rel:pin(Path(retained_backend())/rel) for rel in d.BACKEND},'max_seconds':20}
    request=tmp_path/'request.json';custody._write(request,doc)
    compiled,r,captured=u.prepare({'input':str(request)},tmp_path)
    assert r['source_leg_symbols']==['b__tilde__','b','H']
    assert r['selected_lorentz_coupling_rows'][0]['structure']=='ProjM(2,1) + ProjP(2,1)'
    assert r['selected_parameter_evaluation']['ymb']['value']['real']==4.2
    assert r['tree_reference']['three_masses_GeV']==[125.,4.7,4.7]
    g=r['coefficient_coordinates']['gL']['real'];v=r['selected_parameter_evaluation']['vev']['value']['real']
    assert g==pytest.approx(-4.2/v) and r['coefficient_coordinates']['gL']==r['coefficient_coordinates']['gR']
    assert r['tree_reference']['partial_width_GeV']==pytest.approx(3*(4.2/v)**2*125/(8*math.pi)*(1-4*4.7**2/125**2)**1.5,rel=1e-13)
    doc.update(parent_pdg=23,vertex='V_81');custody._write(request,doc)
    _,r,_=u.prepare({'input':str(request)},tmp_path)
    assert len(r['selected_lorentz_coupling_rows'])==2
    assert [row['chiral_projection_weights'] for row in r['selected_lorentz_coupling_rows']]==[[1.,-2.],[1,0]]
    assert r['tree_reference']['initial_spin_average']==3 and r['tree_reference']['final_color_sum']==3


def test_changed_card_after_validation_is_refused(tmp_path,monkeypatch):
    retained_backend();task,doc,model,card,manifest,request=fixture(tmp_path)
    original=u.card_values
    def drift(text):
        values=original(text);card.write_text(text+'BLOCK EXTRA\n1 9\n');return values
    monkeypatch.setattr(u,'card_values',drift)
    with pytest.raises(ValueError,match='source changed'):u.prepare(task,tmp_path)


def test_changed_ufo_source_pin_refused(tmp_path):
    retained_backend();task,doc,model,card,manifest,request=fixture(tmp_path)
    (model/'couplings.py').write_text((model/'couplings.py').read_text().replace('2*Y','4*Y'))
    with pytest.raises(ValueError,match='source tree differs'):d.inputs(task,tmp_path)


def test_added_source_after_backend_construction_is_retained_failed(tmp_path,monkeypatch):
    retained_backend();task,doc,model,card,manifest,request=fixture(tmp_path)
    from contextlib import contextmanager
    backend=d._backend
    @contextmanager
    def add_member(sources):
        with backend(sources) as modules:
            yield modules
            (model/'new-hidden-definition.py').write_text('undeclared source population change\n')
    monkeypatch.setattr(d,'_backend',add_member)
    report=d.run(task,tmp_path,tmp_path/'output')
    assert report['status']=='failed' and str(model) in report['source_drift']
    assert not (tmp_path/'output/decay-supplied-point.wl').exists()
    assert (tmp_path/'output/diagrammatica/upstream-symbolic.wl').exists()


def test_fresh_output_required(tmp_path):
    retained_backend();task,*rest=fixture(tmp_path)
    out=tmp_path/'output';out.mkdir();(out/'prior.json').write_text('{}')
    with pytest.raises(FileExistsError):d.run(task,tmp_path,out)


def test_original_UFO_procedural_mutation_is_not_a_static_record(tmp_path):
    task,doc,model,card,manifest,request=fixture(tmp_path)
    path=model/'couplings.py';path.write_text(path.read_text()+'C1.value="complex(0,1)*999"\n')
    with pytest.raises(ValueError,match='procedural'):compile_local(doc,model,card,manifest,request)


def test_complex_Function_declaration_is_consumed_instead_of_named_default(tmp_path):
    task,doc,model,card,manifest,request=fixture(tmp_path)
    path=model/'function_library.py';path.write_text(path.read_text()+"sin=Function(name='sin',arguments=('z',),expression='2*z')\n")
    path=model/'couplings.py';path.write_text(path.read_text().replace('Y+phase','sin(Y)+phase'))
    _,details=compile_local(doc,model,card,manifest,request)
    assert details['coefficient_coordinates']['gL']=={'real':.4,'imag':.2}


@pytest.mark.parametrize('value',[1e-17,-3.25e17,.0,4.2,-.022])
def test_Wolfram_literal_derivative_uses_Wolfram_exponent_grammar(value):
    token=u._wl_number(value)
    assert 'e' not in token.lower() and float(token.replace('*^','e'))==value


def test_ordinary_schema2_plan_includes_full_source_and_remains_unapproved(tmp_path):
    retained_backend();task,doc,model,card,manifest,request=fixture(tmp_path)
    from ravel.workflow import science
    actors={'proposer':'unit-proposer','executor':'unit-executor','physics_critic':'unit-critic',
            'skeptical_verifier':'unit-verifier','physics_decider':'unit-decider'}
    policy={'schema_version':1,'actors':actors,'max_redos':0,'allowed_changed_paths':[],
            'allowed_stages':['science'],'required_checks':[{'id':'source','kind':'integrity'}],
            'claim_scopes':{'source_construction':{'checks':['source'],'actions':['delivery']}}}
    spec={'schema_version':2,'mode':'diagrammatica-code','source':doc['source'],
        'assumptions':['Source-backed finite vertex/point construction only; no native amplitude or complete model acceptance.'],
        'max_seconds':45,'approval_mode':'scripted_yes','max_attempts':1,'task':task,
        'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    source=tmp_path/'study.json';custody._write(source,spec);root=tmp_path/'ordinary-study'
    plan=science.plan(root,source)
    assert plan['schema_version']==2 and not (root/'inputs/science-approval.json').exists()
    assert not (root/'outputs').exists()
    inputs=set(science.task_inputs(spec,tmp_path))
    assert {card,manifest,request,*model.iterdir()} <= inputs
    science.verify_plan(root,approved=False)
    card.write_text(card.read_text().replace('11 .2','11 .4'))
    with pytest.raises(ValueError):science.verify_plan(root,approved=False)


@pytest.mark.parametrize('left,right',[({'real':1.,'imag':1.},{'real':1.,'imag':-1.}),({'real':2.,'imag':1.},{'real':3.,'imag':-4.}),({'real':.2,'imag':.2},{'real':.4,'imag':.2})])
def test_completed_symbolic_conjugation_precedes_point_rules(left,right):
    raw='ampCC = ComplexConjugate[amp];\nampCC = ampCC /. {gL -> Conjugate[gL], gR -> Conjugate[gR]};\nampSqKin = amp ampCC;\nwidth = ampSqKin/3;\n'
    points={'gL':left,'gR':right,'mX':{'real':13.,'imag':0.}}
    script=u._point_script(raw,points,{})
    assert script.startswith(raw)
    assert script.index('width = ampSqKin/3;') < script.index('ravelPointRules =')
    assert 'gL = ' not in script and 'gR = ' not in script and 'mX = ' not in script
    assert 'N[ampSqKin /. ravelPointRules]' in script and 'N[width /. ravelPointRules]' in script
    assert 'POINT_NUMERICAL_RESULT[width_GeV]' in script


def test_same_species_numeric_alias_is_collapsed_without_early_mass_assignment():
    points={'mX':{'real':13.,'imag':0.},'mf':{'real':2.,'imag':0.},'mfbar':{'real':2.,'imag':0.},'gL':{'real':1.,'imag':1.}}
    raw='mfbar = mf;\nampCC = ComplexConjugate[amp];\nwidth = expression;\n'
    script=u._point_script(raw,points,{'mfbar':'mf'})
    assert script.startswith(raw) and 'mf -> Complex[2,0]' in script
    assert 'mfbar ->' not in script and 'mf = Complex[' not in script
    points['mfbar']['real']=3.
    with pytest.raises(ValueError,match='mass substitution'):u._point_script(raw,points,{'mfbar':'mf'})
