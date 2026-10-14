from decimal import Decimal, localcontext
import gzip,hashlib,json
from pathlib import Path
import pytest
import xml.etree.ElementTree as ET
from xml.parsers import expat
from ravel.physics import svj_lhe_transform as t,model_event_weights as w

GROUPS=[{'name':'scale_variation','combine':'envelope','ids':['a','b']}]

def fixture(*, compact=False, both=False):
 header='<header><!-- 49001011 is source text, not a particle -->\n<initrwgt><weightgroup name="scale_variation" combine="envelope"><weight id="a" MUR=".5">MUR=.5</weight><weight id="b" MUR="2">MUR=2</weight></weightgroup></initrwgt></header>'
 init='<init>\n2212 2212 6500 6500 0 0 315000 315000 -3 1\n1 .01 49001011 1 #49001014 remains init metadata\n</init>\n'
 events=[]
 for weight,a,b in [('1D-2','2.0','3'),('-1D-2','-2.0','-3'),('-0D0','0','-0')]:
  particles=''.join(f'{sign}{pdg} 1 0 0 501 502 49001011.0 0 1 2 10 0 9 #49001013 comment\n' for pdg in t.PRESENT for sign in ['','-'])
  detailed=f'<rwgt><wgt id="a"> {a} </wgt><wgt id="b">{b}</wgt></rwgt>'
  dense=f'<weights> {a}\t{b} </weights>'
  events.append('<event>\n8 1 '+weight+' 100 .007 .1 #49001011 event-header-comment\n'+particles+(detailed+dense if both else dense if compact else detailed)+'\n</event>\n')
 return ('<LesHouchesEvents version="3.0">'+header+'\n'+init+''.join(events)+'</LesHouchesEvents>\n').encode()

def execute(tmp, raw, **kwargs):
 source=tmp/'source.lhe.gz'
 with gzip.open(source,'wb') as f:f.write(raw)
 before=source.read_bytes()
 result=t.transform(source,tmp/'delivery',expected_events=3,expected_groups=GROUPS,
                    maximum_bytes=1000000,maximum_event_bytes=100000,**kwargs)
 assert source.read_bytes()==before
 assert Path(result['raw_hard']['path']).read_bytes()==before
 return result,gzip.decompress(Path(result['derived_shower_input']['path']).read_bytes())

@pytest.mark.parametrize('compact,both',[(False,False),(True,False),(False,True)])
def test_exact_all_scalar_encodings_signs_and_nonparticle_immunity(tmp_path,compact,both):
 raw=fixture(compact=compact,both=both);r,derived=execute(tmp_path,raw)
 assert t.verify(r)
 assert r['complete_original_N']==3 and r['original_population']['init']['idwtup']==-3
 assert r['derived_shower_input_population']['init']==dict(r['original_population']['init'],idwtup=-4)
 assert r['original_population']['signed_nominal_counts']=={'positive':1,'negative':1,'zero':1}
 assert b'49001011.0' in derived and b'#49001013 comment' in derived and b'<!-- 49001011' in derived
 rows=[json.loads(x) for x in Path(r['change_journal']['path']).read_text().splitlines()]
 assert len([x for x in rows if x['role']=='IDUP'])==24
 assert len([x for x in rows if x['role']=='IDWTUP'])==1
 for x in rows:
  a=bytes.fromhex(x['original_hex']);b=bytes.fromhex(x['derived_hex'])
  if x['role'].endswith('weight') or x['role']=='XWGTUP':assert w.number(b.decode())==3*w.number(a.decode())
 assert b'-0D0' in derived and b'>-0<' in derived if not compact else b'-0' in derived
 assert set(x['role'] for x in rows)<={'IDUP','IDWTUP','XWGTUP','detailed_weight','compact_weight'}

@pytest.mark.parametrize('literal,n,result',[(b'1D-2',3,Decimal('.03')),(b'-1e-300',3,Decimal('-3e-300')),(b'+0.010',7,Decimal('.070')),(b'-0e-300',9,Decimal('-0e-300'))])
def test_integer_scaling_does_not_use_active_decimal_rounding(literal,n,result):
 with localcontext() as context:
  context.prec=2
  transformed=t.scaled_token(literal,n)
 assert w.number(transformed.decode())==result
 if literal.startswith(b'-0'):assert transformed==literal

@pytest.mark.parametrize('literal',[b'1e308',b'-1e308',b'1e-400',b'-1e-400',b'NaN',b'Infinity',b'1e9999'])
def test_native_nonzero_finite_representation_refuses(literal):
 with pytest.raises(ValueError):t.scaled_token(literal,3)

@pytest.mark.parametrize('defect',['absent_pdg','last_nup','last_weight','both_unequal','wrong_strategy','short','foreign_process'])
def test_late_invalid_complete_cohort_has_no_accepted_delivery(tmp_path,defect):
 raw=fixture(both=defect=='both_unequal')
 if defect=='absent_pdg':raw=raw.replace(b'\n49001011 1 0',b'\n49001010 1 0',1)
 elif defect=='last_nup':a=raw.rfind(b'8 1 -0D0');raw=raw[:a]+raw[a:].replace(b'8 1 -0D0',b'9 1 -0D0',1)
 elif defect=='last_weight':a=raw.rfind(b'<wgt id="b">-0</wgt>');raw=raw[:a]+raw[a:].replace(b'<wgt id="b">-0</wgt>',b'<wgt id="b">NaN</wgt>',1)
 elif defect=='both_unequal':raw=raw.replace(b'<weights> 2.0\t3',b'<weights> 2.0\t4',1)
 elif defect=='wrong_strategy':raw=raw.replace(b'315000 -3 1',b'315000 -4 1')
 elif defect=='short':raw=raw[:-23]
 elif defect=='foreign_process':raw=raw.replace(b'8 1 1D',b'8 2 1D',1)
 source=tmp_path/'source.lhe';source.write_bytes(raw)
 with pytest.raises((ValueError,ET.ParseError,expat.ExpatError)):
  t.transform(source,tmp_path/'delivery',expected_events=3,expected_groups=GROUPS,maximum_bytes=1000000,maximum_event_bytes=100000)
 assert not (tmp_path/'delivery/transform.json').exists()
 assert not (tmp_path/'delivery/derived-shower.lhe.gz').exists()
 assert source.read_bytes()==raw

def test_compact_only_not_assumed_native_detailed_map(tmp_path):
 source=tmp_path/'source.lhe';source.write_bytes(fixture(compact=True))
 with pytest.raises(ValueError,match='requires complete detailed'):
  t.transform(source,tmp_path/'delivery',expected_events=3,expected_groups=GROUPS,maximum_bytes=1000000,maximum_event_bytes=100000,require_detailed=True)
 assert not (tmp_path/'delivery/derived-shower.lhe.gz').exists()

def test_unmodified_default_scanner_refuses_dual_encoding(tmp_path):
 source=tmp_path/'source.lhe';source.write_bytes(fixture(both=True))
 with pytest.raises(ValueError,match='ambiguous event weight'):
  w.scan(source,expected_events=3,expected_groups=GROUPS,maximum_bytes=1000000,journal_path=tmp_path/'default.jsonl')

def test_exact_inverse_refuses_changed_unaffected_particle_byte(tmp_path):
 r,derived=execute(tmp_path,fixture());p=Path(r['derived_shower_input']['path'])
 with gzip.open(p,'wb') as f:f.write(derived.replace(b'501 502',b'601 502',1))
 with pytest.raises(ValueError,match='evidence changed'):t.verify(r)
