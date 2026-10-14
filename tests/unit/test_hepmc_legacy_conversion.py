"""Portable conversion/source controls; fixtures are parser examples, not physics."""
import ast
import builtins
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import hepmc_legacy_conversion as h,checkmate_252_compat as c,backend_provider as p,checkmate_reader_observation as reader,checkmate_events as events


def source(weight='1',extra=''):
    return f'''HepMC::Version 3.03.01
HepMC::Asciiv3-START_EVENT_LISTING
W Weight
E 0 1 3
U GEV MM
W {weight}
A 0 cycles 1
{extra}P 1 0 2212 0 0 1 1 0 4
P 2 0 2212 0 0 -1 1 0 4
V -1 0 [1,2] @ 1 2 3 4
P 3 -1 22 0 0 0 2 2 1
HepMC::Asciiv3-END_EVENT_LISTING
'''

@pytest.fixture
def converted(tmp_path):
    s=tmp_path/'original.asciiv3';s.write_text(source(extra='A 3 flow1 502\nA 0 commentary exact original wording\n'))
    out=tmp_path/'converted';result=h.convert(s,h.sha(s),1,out)
    return out,result,s

def test_exact_roundtrip_and_explicit_attribute_dispositions(converted):
    out,r,s=converted;assert h.verify_manifest(out/'conversion.json')['events']==1
    assert (out/'events.hepmc').read_text().startswith('HepMC::Version 3.03.01\nHepMC::IO_GenEvent')
    assert not r['full_metadata_wire_lossless'] and not r['native_parse_observed']
    side=json.loads((out/'metadata-sidecar.json').read_text())
    dispositions={(x['id'],x['name']):x['disposition'] for x in side['events'][0]['attribute_dispositions']}
    assert dispositions[(3,'flow1')]=='encoded' and dispositions[(0,'cycles')]=='sidecar only' and dispositions[(0,'commentary')]=='sidecar only'
    assert h.canonical(h.read_legacy(out/'events.hepmc')[0])==r['canonical'][0]

@pytest.mark.parametrize('weight',['-1','0','1.234567890123456789012345'])
def test_signed_zero_and_exact_decimal_weight_preserved(tmp_path,weight):
    s=tmp_path/'original';s.write_text(source(weight));r=h.convert(s,h.sha(s),1,tmp_path/'out')
    assert r['canonical'][0]['weights']==[h.number(weight)]

@pytest.mark.parametrize('before,after',[
 ('P 3 -1 22','P 3 -99 22'),('P 2 0 2212','P 3 0 2212'),
 ('P 1 0 2212','P 1 2 2212'),('E 0 1 3','E 0 2 3'),
 ('A 0 cycles 1','A 0 cycles 0'),('W 1\n','W 1 2\n'),
 ('0 0 1 1 0 4','nan 0 1 1 0 4'),('U GEV MM','U MEV CM'),
 ('V -1 0 [1,2]','V -1 0 [1,1]'),('P 3 -1 22','P 3 0 22'),
 ('HepMC::Asciiv3-END_EVENT_LISTING\n',''),('E 0 1 3','E 0 1 3 @ 1 2 3 4')])
def test_unsupported_or_altered_source_refuses_without_valid_derivative(tmp_path,before,after):
    s=tmp_path/'source';s.write_text(source().replace(before,after))
    with pytest.raises(ValueError):h.convert(s,h.sha(s),1,tmp_path/'out')
    assert not (tmp_path/'out/conversion.json').exists()

@pytest.mark.parametrize('mutation',['particle','weight','sidecar','prefix','claim'])
def test_rebound_output_hash_cannot_hide_semantic_or_origin_drift(converted,mutation):
    out,r,s=converted
    key={'particle':'event_output','weight':'event_output','sidecar':'metadata_sidecar','prefix':'original_prefix'}.get(mutation)
    if mutation=='claim':r['full_metadata_wire_lossless']=True
    else:
        path=Path(r[key]['path']);text=path.read_text()
        if mutation=='particle':text=text.replace('P 3 22','P 3 23')
        elif mutation=='weight':
            lines=text.splitlines();index=next(i for i,x in enumerate(lines) if x.startswith('E '));fields=lines[index].split();fields[-1]='2';lines[index]=' '.join(fields);text='\n'.join(lines)+'\n'
        elif mutation=='sidecar':text=text.replace('exact original wording','altered wording')
        else:text=text.replace('P 3 -1 22','P 3 -1 23')
        path.write_text(text);r[key]['sha256']=h.sha(path)
    (out/'conversion.json').write_text(json.dumps(r))
    with pytest.raises(ValueError):h.verify_manifest(out/'conversion.json')

def _observation(out):
    types={'GenParticle.PID':'Int_t','GenParticle.Status':'Int_t',**{'GenParticle.'+k:'Float_t' for k in ('Px','Py','Pz','E','Mass','X','Y','Z','T')},'HepMCEvent.Weight':'Float_t','Event.Number':'Long64_t'}
    return {'kind':'delphes-persisted-original-event-census','rows':reader.expected(h.read_legacy(out/'events.hepmc')),
      'root_version':'synthetic source control','library_load_request':'not launched','dictionary_types':types}

def test_complete_reader_float_projection_supplied_control(converted):
    out,_,_=converted;ob=_observation(out);result=reader.validate(ob,h.read_legacy(out/'events.hepmc'))
    assert result['events']==1 and result['particles']==3
    assert ob['rows'][0]['particles'][-1]['position'][-1]==reader.f32(4e-3/2.99792458e8)

@pytest.mark.parametrize('mutation',['weight','missing','status','momentum','geometry','bool','dictionary'])
def test_reader_adverse_complete_census_refuses(converted,mutation):
    out,_,_=converted;ob=_observation(out)
    if mutation=='weight':ob['rows'][0]['weight']=2.0
    elif mutation=='missing':ob['rows'][0]['particles'].pop()
    elif mutation=='status':ob['rows'][0]['particles'][-1]['status']=2
    elif mutation=='momentum':ob['rows'][0]['particles'][-1]['p4'][3]=3.0
    elif mutation=='geometry':ob['rows'][0]['particles'][-1]['position'][0]=0.0
    elif mutation=='bool':ob['rows'][0]['weight']=True
    else:ob['dictionary_types']['HepMCEvent.Weight']='Double_t'
    with pytest.raises(ValueError):reader.validate(ob,h.read_legacy(out/'events.hepmc'))




def test_version3_producer_legacy_listing_and_leading_blank_source_guard(converted,tmp_path):
    out,_,_=converted;event=out/'events.hepmc';event.write_text('\n'+event.read_text())
    assert p.legacy_framing(event)['wire_grammar']=='HepMC2 IO_GenEvent'
    assert events.hepmc2_census(event,1)['events']==1
    event.write_text(event.read_text().replace('IO_GenEvent','Asciiv3'))
    with pytest.raises(ValueError):p.legacy_framing(event)
    with pytest.raises(ValueError):events.hepmc2_census(event,1)

