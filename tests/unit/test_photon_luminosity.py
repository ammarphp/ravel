"""Synthetic density, kernel, comparison and separate-process protocol controls."""
import ast
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import pytest


def api():
    from ravel.physics import photon_luminosity
    return photon_luminosity


def spec():
    return {'energy_gev': 1370., 'beams': [2212, 2212],
            'process': {'initial': [22, 22], 'final': [13, -13]},
            'pdf': {'name': 'synthetic-density', 'member': 0, 'flavours': [22]},
            'scale': {'kind': 'pair_mass', 'factor': 1.}, 'lepton_mass_gev': 2.3,
            'alpha': 0.0071, 'cuts': {'mass_window_gev': [27., 83.], 'pair_abs_rapidity_max': 0.4}}


@pytest.mark.parametrize('mutation,reason', [
    (lambda s: s['pdf'].update(flavours=[21]), 'photon'),
    (lambda s: s['process'].update(final=[21, 21]), 'charged-lepton pair'),
    (lambda s: s['cuts'].update(individual_eta_max=2.), 'cut'),
    (lambda s: s.update(beams=[11, -11]), 'beam'),
    (lambda s: s.update(lepton_mass_gev=0.), 'mass'),
    (lambda s: s['scale'].update(kind='arbitrary'), 'scale'),
    (lambda s: s['cuts'].update(mass_window_gev=[83., 27.]), 'window'),
    (lambda s: s.update(alpha=float('nan')), 'alpha'),
    (lambda s: s['pdf'].update(member=True), 'member'),
    (lambda s: s.update(unrecognized=True), 'field'),
])
def test_spec_refusals(mutation, reason):
    s = spec(); mutation(s)
    with pytest.raises(ValueError, match=reason):
        api().cross_section(s, lambda x, q: x)


@pytest.mark.parametrize('field', ['pdf.name', 'pdf.member', 'energy_gev', 'cuts.mass_window_gev',
                                    'scale.factor', 'beams', 'lepton_mass_gev', 'alpha', 'process.final'])
def test_comparator_refuses_setup_mismatch(field):
    s = spec()
    check = api().cross_section(s, lambda x, q: x)
    g = {'spec': deepcopy(s), 'cross_section_pb': check['cross_section_pb'], 'statistical_error_pb': 0.}
    obj = g['spec']; parts = field.split('.')
    for p in parts[:-1]: obj = obj[p]
    k = parts[-1]; value = obj[k]
    obj[k] = {'beams': [2212,-2212], 'final': [11,-11], 'mass_window_gev': [28.,84.]}.get(k, 'different-density' if isinstance(value,str) else value+1 if not isinstance(value,list) else value)
    with pytest.raises(ValueError, match='setup|window'):
        api().compare(check, g, .01)


@pytest.mark.parametrize('bad', [-1., float('nan'), float('inf')])
def test_density_refuses_nonphysical_values(bad):
    with pytest.raises(ValueError, match='density'):
        api().cross_section(spec(), lambda x, q: bad)


@pytest.mark.parametrize('mode,reason', [('exit', 'exit'), ('malformed', 'JSON'), ('identity', 'set'),
                                       ('member', 'member'), ('grid', 'grid'), ('flavours', 'photon'),
                                       ('values', 'values'), ('version', 'version')])
def test_worker_refuses_bad_reply(tmp_path, mode, reason):
    fake = tmp_path / 'fake.py'
    fake.write_text("import json,sys\nr=json.load(sys.stdin)\n"
                    "t=dict(r, schema_version=1, flavours=[22], lhapdf_version='synthetic', values=[[x for q in r['q_gev']] for x in r['x']])\n"
                    f"mode={mode!r}\n"
                    "if mode=='exit': sys.exit(7)\n"
                    "if mode=='malformed': print('broken'); sys.exit()\n"
                    "if mode=='identity': t['set']='different'\n"
                    "if mode=='member': t['member']=1\n"
                    "if mode=='grid': t['x']=[.2,.8]\n"
                    "if mode=='flavours': t['flavours']=[21]\n"
                    "if mode=='values': t['values']=[[float('nan')]]\n"
                    "if mode=='version': t['lhapdf_version']=''\n"
                    "print(json.dumps(t))\n")
    with pytest.raises(ValueError, match=reason):
        api().density_from_worker([sys.executable, str(fake)], request())


def request():
    return {'set': 'synthetic-density', 'member': 0, 'x': [.001, 1.], 'q_gev': [20., 100.]}


@pytest.mark.parametrize('mutation', [lambda r: r.update(x=[.2,.1]), lambda r: r.update(q_gev=[0.,2.]),
                                      lambda r: r.update(member=-1), lambda r: r.update(unknown=True)])
def test_worker_request_refused_before_process(mutation):
    r = request(); mutation(r)
    with pytest.raises(ValueError): api().density_from_worker(['/absent/interpreter'], r)


def test_table_refuses_extrapolation_and_setup_mismatch():
    a = api(); r = request()
    t = dict(r, schema_version=1, flavours=[22], lhapdf_version='synthetic', values=[[x,x] for x in r['x']])
    provider = a.DensityTable(t)
    with pytest.raises(ValueError, match='grid'): provider(.0001, 30.)
    with pytest.raises(ValueError, match='grid'): provider(.2, 200.)
    s = spec(); s['pdf']['member'] = 1
    with pytest.raises(ValueError, match='member'): a.cross_section(s, provider)


def test_comparator_refuses_invalid_numbers():
    a = api(); c = a.cross_section(spec(), lambda x,q: x)
    g = {'spec': spec(), 'cross_section_pb': c['cross_section_pb'], 'statistical_error_pb': 0.}
    for bad in [-.1, 0., float('nan'), 2.]:
        with pytest.raises(ValueError, match='tolerance'): a.compare(c,g,bad)
    for k in ['cross_section_pb', 'statistical_error_pb']:
        bad = deepcopy(g); bad[k] = float('nan')
        with pytest.raises(ValueError): a.compare(c,bad,.01)


def test_pdf_uncertainty_refuses_incomplete_or_changed_members():
    a = api(); c = a.cross_section(spec(), lambda x,q: x)
    p = {'kind': 'replicas', 'members': [1,2], 'confidence_level': .68, 'rescale': 1.}
    with pytest.raises(ValueError, match='members'): a.with_pdf_uncertainty(c, [c], p)


def test_host_never_imports_density_binding():
    source = Path(api().__file__).read_text()
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import): names.extend(n.name for n in node.names)
        if isinstance(node, ast.ImportFrom): names.append(node.module or '')
    assert not any(n.split('.')[0] == 'lhapdf' for n in names)


def total_kernel_reference(shat, mass, alpha):
    """Independent total formula in log(beta) form, used only by synthetic fixtures."""
    beta = math.sqrt(1-4*mass*mass/shat)
    return 4*math.pi*alpha**2/shat*((3-beta**4)/2*math.log((1+beta)/(1-beta))
                                  -beta*(2-beta**2))*389379372.1


@pytest.mark.parametrize('energy,window,mass,factor', [
    (1370.,[27.,83.],2.3,1.), (2190.,[41.,109.],3.7,1.6),
    (2190.,[27.,83.],2.3,1.), (1370.,[41.,109.],2.3,1.),
    (1370.,[27.,83.],3.7,1.), (1370.,[27.,83.],2.3,1.6),
])
def test_closed_form_convolution_and_supplied_input_variation(energy,window,mass,factor):
    s = spec(); s.update(energy_gev=energy,lepton_mass_gev=mass)
    s['cuts']['mass_window_gev'] = window; s['scale']['factor'] = factor
    # An engineered analytic density cancels the independent total Born kernel.
    # f(x,Q)=m*Q/sqrt(sigma_hat((Q/factor)**2,m)); fixed pair rapidity
    # gives sigma=Y*m**2*factor**2*(Mhi**4-Mlo**4)/s exactly.
    def density(x,q):
        return x*mass*q/math.sqrt(total_kernel_reference((q/factor)**2,mass,s['alpha']))
    check = api().cross_section(s,density)
    expected = s['cuts']['pair_abs_rapidity_max']*mass**2*factor**2*(window[1]**4-window[0]**4)/energy**2
    assert check['cross_section_pb'] == pytest.approx(expected,rel=1e-4)
    assert check['integration_error_pb']/expected < 1e-6
    assert check['spec'] == s
    assert check['integration']['error_scope'].startswith('quadrature only')


@pytest.mark.parametrize('scale', [{'kind':'fixed','q_gev':37.}, {'kind':'pair_mass','factor':1.4}])
@pytest.mark.parametrize('mass', [2.3,4.1])
def test_scale_and_mass_against_independent_one_dimensional_reference(scale,mass):
    from scipy.integrate import quad
    s = spec(); s['scale'] = scale; s['lepton_mass_gev'] = mass
    def integrand(pair_mass):
        q = scale['q_gev'] if scale['kind']=='fixed' else pair_mass*scale['factor']
        return 4*s['cuts']['pair_abs_rapidity_max']*pair_mass/s['energy_gev']**2*q*q*total_kernel_reference(pair_mass**2,mass,s['alpha'])
    expected = quad(integrand,*s['cuts']['mass_window_gev'],epsabs=1e-10)[0]
    result = api().cross_section(s,lambda x,q: x*q)
    assert result['cross_section_pb'] == pytest.approx(expected,rel=1e-8)


@pytest.mark.parametrize('shat,mass,pt', [(47.**2,3.2,0.), (91.**2,4.6,8.), (12.**2,5.9,.1)])
def test_partonic_kernel_against_differential_integral(shat,mass,pt):
    from scipy.integrate import quad
    alpha=.0067; beta=math.sqrt(1-4*mass**2/shat)
    c=math.sqrt(1-4*pt**2/(shat-4*mass**2))
    def differential(z):
        # Algebraically distinct sum of rational pieces.
        return 2*math.pi*alpha**2*beta/shat*((1+beta**2*z*z)/(1-beta**2*z*z)
               +2*beta**2*(1-beta**2)*(1-z*z)/(1-beta**2*z*z)**2)*389379372.1
    expected = quad(differential,-c,c,epsabs=1e-9,epsrel=1e-10)[0]
    assert api().partonic_cross_section(shat,mass,alpha,pt) == pytest.approx(expected,rel=1e-9)


def test_threshold_and_cut_limits():
    a=api(); s=spec(); base=a.cross_section(s,lambda x,q: x)
    for key,value in [('lepton_pt_min_gev',9.), ('pair_abs_rapidity_max',.2)]:
        cut=deepcopy(s); cut['cuts'][key]=value
        assert 0 < a.cross_section(cut,lambda x,q:x)['cross_section_pb'] < base['cross_section_pb']
    s['cuts']['lepton_pt_min_gev']=100.
    assert a.cross_section(s,lambda x,q: x)['cross_section_pb']==0
    assert a.partonic_cross_section(4.,1.,.007)==0
    # The positive mass regulator remains finite when beta rounds to one.
    assert math.isfinite(a.partonic_cross_section(1e12,1e-4,.007))


def test_comparator_pass_fail_and_record():
    a=api(); c=a.cross_section(spec(),lambda x,q:x)
    original=deepcopy(c)
    g={'spec':spec(), 'cross_section_pb':c['cross_section_pb']*1.005,
       'statistical_error_pb':c['cross_section_pb']*.001}
    assert a.compare(c,g,.01)['status']=='pass'
    g['cross_section_pb']=c['cross_section_pb']*1.02
    record=a.compare(c,g,.01)
    assert record['status']=='fail'
    assert record['relative_difference']==pytest.approx(.02)
    assert record['integration_error_pb']==c['integration_error_pb']
    assert record['statistical_error_pb']==g['statistical_error_pb']
    assert record['tolerance']==.01
    assert record['check']==c and record['generator_result']==g and c==original
    g['cross_section_pb']=c['cross_section_pb']
    unresolved=deepcopy(c); unresolved['integration_error_pb']=c['cross_section_pb']*.02
    assert a.compare(unresolved,g,.01)['status']=='fail'


def test_worker_fake_interpreter_matches_analytic_table(tmp_path):
    fake=tmp_path/'fake.py'
    fake.write_text("import json,math,sys\nfrom pathlib import Path\n"
                    "assert Path(sys.argv[-1]).name=='photon_density_worker.py'\n"
                    "r=json.load(sys.stdin)\n"
                    "v=[[.3+.01*math.log(x)+.02*math.log(q) for q in r['q_gev']] for x in r['x']]\n"
                    "print(json.dumps(dict(r,schema_version=1,flavours=[22],lhapdf_version='synthetic',values=v)))\n")
    a=api(); provider=a.density_from_worker([sys.executable,str(fake)],request())
    analytic=lambda x,q:.3+.01*math.log(x)+.02*math.log(q)
    for x,q in [(.003,23.),(.05,49.),(.99,99.)]:
        assert provider(x,q)==pytest.approx(analytic(x,q),abs=2e-16)
    table=a.cross_section(spec(),provider)
    expected=a.cross_section(spec(),analytic)
    # Bilinear interpolation is exact for this affine function of log(x), log(Q).
    assert table['cross_section_pb']==pytest.approx(expected['cross_section_pb'],rel=1e-10)
    assert table['density_table']['lhapdf_version']=='synthetic'


@pytest.mark.parametrize('kind,values,expected', [
    ('replicas',[.8,1.2],math.sqrt(.08)),
    ('symmetric_hessian',[.9,1.1,.8,1.2],math.sqrt(.05)),
])
def test_requested_pdf_uncertainty_is_recorded(kind,values,expected):
    a=api(); c=a.cross_section(spec(),lambda x,q:x)
    members=[]
    for i,value in enumerate(values,1):
        member=deepcopy(c); member['spec']['pdf']['member']=i
        member['cross_section_pb']=c['cross_section_pb']*value
        members.append(member)
    prescription={'kind':kind,'members':list(range(1,len(values)+1)), 'confidence_level':.68,'rescale':1.}
    combined=a.with_pdf_uncertainty(c,members,prescription)
    assert combined['pdf_uncertainty']['error_pb']==pytest.approx(c['cross_section_pb']*expected)
    assert combined['pdf_uncertainty']['member_results']==members
    g={'spec':spec(),'cross_section_pb':c['cross_section_pb'],'statistical_error_pb':0.}
    assert a.compare(combined,g,.01)['pdf_uncertainty']==combined['pdf_uncertainty']
    assert 'pdf_uncertainty' not in c


def test_finished_result_cli_reads_only(tmp_path,monkeypatch):
    a=api(); r=request()
    t=dict(r,schema_version=1,flavours=[22],lhapdf_version='synthetic',values=[[.3,.3],[.3,.3]])
    c=a.cross_section(spec(),a.DensityTable(t))
    records={'spec':spec(),'table':t,'generator':{'spec':spec(),'cross_section_pb':c['cross_section_pb'],'statistical_error_pb':0.}}
    for name,value in records.items(): (tmp_path/f'{name}.json').write_text(json.dumps(value))
    def forbidden(*args,**kwargs): raise AssertionError('finished-result CLI launched a subprocess')
    monkeypatch.setattr(a.subprocess,'run',forbidden)
    output=tmp_path/'comparison.json'
    args=['--spec',str(tmp_path/'spec.json'),'--density-table',str(tmp_path/'table.json'),
          '--generator-result',str(tmp_path/'generator.json'),'--tolerance','.01','--output',str(output)]
    assert a.main(args)==0
    assert json.loads(output.read_text())['status']=='pass'


@pytest.mark.parametrize('energy,window', [(1370.,[27.,83.]), (2190.,[41.,109.])])
def test_mass_window_only_closed_form(energy,window):
    s=spec(); s['energy_gev']=energy; s['cuts']={'mass_window_gev':window}
    mass=s['lepton_mass_gev']
    def density(x,q): return x*mass*q/math.sqrt(total_kernel_reference(q*q,mass,s['alpha']))
    def primitive(pair_mass):
        return mass**2/energy**2*pair_mass**4*(math.log(energy/pair_mass)+.25)
    expected=primitive(window[1])-primitive(window[0])
    assert api().cross_section(s,density)['cross_section_pb']==pytest.approx(expected,rel=1e-4)


def curved(x,q):
    return .02*math.log(q/.5)*(1-x)**4*x**.05


def tabulated(nx,nq):
    xs=[10**(-4+4*i/(nx-1)) for i in range(nx)]; xs[-1]=1.
    qs=[20.*5**(j/(nq-1)) for j in range(nq)]; qs[-1]=100.
    return dict(request(),x=xs,q_gev=qs,schema_version=1,flavours=[22],lhapdf_version='synthetic',
                values=[[curved(x,q) for q in qs] for x in xs])


@pytest.mark.parametrize('scale', [{'kind':'pair_mass','factor':1.}, {'kind':'fixed','q_gev':37.}])
@pytest.mark.parametrize('rapidity', [None,.9])
def test_curved_table_resolves_at_default_precision_and_refines(scale,rapidity):
    a=api(); s=spec(); s['scale']=scale; s['cuts']={'mass_window_gev':[27.,83.]}
    if rapidity: s['cuts']['pair_abs_rapidity_max']=rapidity
    exact=a.cross_section(s,curved)['cross_section_pb']
    coarse,fine=[a.cross_section(s,a.DensityTable(tabulated(nx,nq))) for nx,nq in [(25,5),(49,9)]]
    # Table nodes are quadrature breakpoints, so the slope changes of the
    # interpolant do not stop the default precision from being reached.
    for result in (coarse,fine): assert result['integration_error_pb'] < 1e-6*exact
    # What remains is bilinear interpolation error: below 0.5% on the coarse
    # grid here, and at least halved when both axes are refined twofold.
    coarse_error=abs(coarse['cross_section_pb']-exact); fine_error=abs(fine['cross_section_pb']-exact)
    assert fine_error < .5*coarse_error < .005*exact


def test_density_provider_may_return_numpy_reals():
    import numpy as np
    a=api(); expected=a.cross_section(spec(),lambda x,q:x)['cross_section_pb']
    for cast in (np.float64,np.float32):
        assert a.cross_section(spec(),lambda x,q:cast(x))['cross_section_pb']==pytest.approx(expected,rel=1e-6)
    for bad in (True,'1',1j,None):
        with pytest.raises(ValueError, match='density'): a.cross_section(spec(),lambda x,q:bad)


STUB_BINDING = '''
import os
class _Set:
    def __init__(self,name): self.name=name
class _Member:
    def __init__(self,member): self.memberID=member
    def flavors(self): return [21] if os.environ.get('STUB_PHOTONLESS') else [21,22]
    def inRangeXQ(self,x,q): return 1e-5<=x<=1 and 2<=q<=1e4
    def xfxQ(self,pid,x,q):
        assert pid==22
        return .25*x
def setVerbosity(level): pass
def mkPDF(name,member): return _Member(member)
def getPDFSet(name): return _Set(name)
def version(): return 'stub-binding'
'''


def test_worker_script_runs_under_a_stub_binding_in_its_own_process(tmp_path,monkeypatch):
    # The shipped worker runs in a child interpreter whose path holds a stand-in
    # binding module; this process never imports a module of that name.
    (tmp_path/'lhapdf.py').write_text(STUB_BINDING)
    monkeypatch.setenv('PYTHONPATH',str(tmp_path))
    a=api(); provider=a.density_from_worker([sys.executable,'-B'],request())
    assert provider.table['lhapdf_version']=='stub-binding' and provider.table['flavours']==[21,22]
    assert provider.table['values']==[[.25*x,.25*x] for x in request()['x']]
    assert provider(1.,20.)==pytest.approx(.25)
    outside=dict(request(),q_gev=[20.,1e5])
    with pytest.raises(ValueError, match='validity domain'): a.density_from_worker([sys.executable,'-B'],outside)
    monkeypatch.setenv('STUB_PHOTONLESS','1')
    with pytest.raises(ValueError, match='no photon density'): a.density_from_worker([sys.executable,'-B'],request())
    assert 'lhapdf' not in sys.modules
