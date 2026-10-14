"""Pure saved-native-state adversaries; no ROOT calls or reconstructed density."""
from copy import deepcopy
from fractions import Fraction as F
import struct
import pytest
from ravel.physics import background_construction as b, background_discrete_profile as d
from ravel.physics import native_likelihood as native
from test_background_construction import specification, prepare, result


def f32(x):return struct.unpack('>f',struct.pack('>f',x))[0]


def complete(spec,fit):
    out=[]
    for c in b.construct(spec):
        r=result(fit)
        for row in r['inference']['rows']:
            for i in range(len(c['document']['auxiliary']['names'])):row['ravel_aux_'+str(i)]=0.
        r['inference']=native.extract_rows(r['inference']['rows'],fit)
        out.append({'id':c['id'],'result':r})
    return out


@pytest.mark.parametrize('name,value', [('b0',-1.),('b0',101.),('ravel_aux_0',20.),('ravel_aux_1',-5.)])
def test_finite_coordinate_outside_declared_domain_refuses(tmp_path,name,value):
    spec=specification(tmp_path,True);_,fit,_=prepare(tmp_path,spec);r=complete(spec,fit)
    raw=r[0]['result']['inference']['rows'];raw[1][name]=value
    r[0]['result']['inference']=native.extract_rows(raw,fit)
    with pytest.raises(ValueError,match='incompatible with declared domain'):d.envelope(spec,r,fit)


@pytest.mark.parametrize('value',[-2.,0.,-0.])
def test_native_full_mean_nonpositive_refuses_even_with_good_status(tmp_path,value):
    spec,fit,_=prepare(tmp_path);r=complete(spec,fit)
    raw=r[0]['result']['inference']['rows'];raw[1]['ravel_mean_0']=value
    r[0]['result']['inference']=native.extract_rows(raw,fit)
    with pytest.raises(ValueError,match='not strictly positive'):d.envelope(spec,r,fit)


def test_saved_mean_and_parameter_format_population(tmp_path):
    spec,fit,_=prepare(tmp_path);r=complete(spec,fit)
    for kind in ('missing','nonliteral'):
        bad=deepcopy(r);raw=bad[0]['result']['inference']['rows']
        if kind=='missing':raw[0].pop('ravel_mean_0')
        else:raw[0]['b0']=.1 # This Python double is not a literal native Float_t.
        bad[0]['result']['inference']=native.extract_rows(raw,fit)
        with pytest.raises(ValueError):d.envelope(spec,bad,fit)


def test_legitimate_float32_endpoint_rounding_no_clipping(tmp_path):
    spec=specification(tmp_path);doc=b.construct(spec)[0]['document']
    p=next(p for p in doc['parameters'] if p['name']=='b0');p.update(bounds=['0','1/10'],initial='0')
    _,fit,_=prepare(tmp_path);row=result(fit)['inference']['rows'][0];row['b0']=f32(.1)
    before=deepcopy(row);receipt=d.native_state_admission(doc,[row])
    assert F(row['b0'])>F(1,10) and row==before
    assert receipt['rounded_coordinates_are_exact_native_state'] is False
    # One more Float_t step has no intersection with the source box.
    bits=struct.unpack('>I',struct.pack('>f',row['b0']))[0]
    row['b0']=struct.unpack('>f',struct.pack('>I',bits+1))[0]
    with pytest.raises(ValueError):d.native_state_admission(doc,[row])


def test_exact_rounding_cells_zero_subnormal_and_extreme():
    lo,hi=d._float32_cell(0.)
    assert (lo,hi)==(-F(1,2**150),F(1,2**150))
    q=f32(2**-149);lo,hi=d._float32_cell(q)
    assert (lo,hi)==(F(1,2**150),F(3,2**150))
    q=struct.unpack('>f',struct.pack('>I',0x7f7fffff))[0]
    lo,hi=d._float32_cell(q)
    assert hi-F(q)==2**103 and d._float32_cell(-q)==(-hi,-lo)


def test_native_command_observes_each_source_defined_total_mean(tmp_path):
    _,_,h=prepare(tmp_path);entries=d._configuration(h['task'],tmp_path)[2]
    for e in entries:
        _,cmd=native.commands(e['config'],{'combine':'inert','text2workspace':'inert'},tmp_path)
        assert cmd[cmd.index('--saveSpecifiedFunc')+1]=='ravel_mean_0,ravel_mean_1,ravel_mean_2,ravel_mean_3'
        assert cmd[cmd.index('--saveSpecifiedNuis')+1]=='all'


def test_raw_nonpositive_return_is_preserved_before_refusal(tmp_path,monkeypatch):
    _,fit,h=prepare(tmp_path);calls=[]
    def fake(*args):
        calls.append(args);r=result(fit);r['inference']['rows'][1]['ravel_mean_0']=-2.
        r['inference']=native.extract_rows(r['inference']['rows'],fit);return r
    monkeypatch.setattr(native,'run',fake)
    out=tmp_path/'run';r=d.run(h['task'],tmp_path,out)
    assert r['status']=='failed' and r['envelope'] is None
    assert r['returns'][0]['result']['inference']['rows'][1]['ravel_mean_0']==-2.
    assert len(calls)==1 and r['population'][1]['status']=='not_executed'
