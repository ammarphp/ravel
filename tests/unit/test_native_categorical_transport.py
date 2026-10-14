"""Portable fabricated native categorical transport controls; no real corpus/native run."""
import copy,gzip,json,tempfile,unittest
from pathlib import Path
from ravel.physics import native_categorical as n
import pytest
SOURCE = REF = None

@pytest.fixture(autouse=True)
def synthetic_source(tmp_path):
 global SOURCE, REF
 root = tmp_path.resolve()
 SOURCE = root / 'synthetic_analysis.cc'
 SOURCE.write_text(''.join('synthetic source line %d\n' % i for i in range(1, 51)))
 REF = root / 'synthetic_reference.yoda.gz'
 REF.write_bytes(gzip.compress(block('BINNEDESTIMATE<S>', '/REF/SYN_9392_I1403/d01-x01-y01', [['synthetic']], ['value','totalDn','totalUp'], [['nan','---','---'],['1','-1','1']], ['']).encode()))

def pin(p,start,end):
 return {'path':str(p),'sha256':n.sha(p.read_bytes()),'first_line':start,'last_line':end,'text':'\n'.join(p.read_text().splitlines()[start-1:end])}
def request(objects):return {'schema_version':1,'sources':[pin(SOURCE,20,49)],'objects':objects,'weight_mapping':[{'id':'nominal','native':'','suffix':''}],'interpretation':'untransformed_native'}
def block(kind,path,edges,columns,rows,labels=None):
 body=[f'BEGIN YODA_{kind}_V3 {path}',f'Path: {path}','---']+[f'Edges(A{i+1}): '+json.dumps(e) for i,e in enumerate(edges)]
 if labels is not None:body+=['ErrorLabels: '+json.dumps(labels)]
 return '\n'.join(body+['# '+' '.join(columns)]+[' '.join(r) for r in rows]+[f'END YODA_{kind}_V3',''])
def obj(path,kind,role='final',ident='output',weight='nominal'):
 return {'id':ident,'weight':weight,'path':path,'role':role,'native_type':kind,'unit':'1','source_definition':0}
class Categorical(unittest.TestCase):
 def test_mixed_estimate_axis_first_fastest_and_other_flow(self):
  t=block('BINNEDESTIMATE<D,S>','/a',[[0,1],['one','two']],['value','totalDn','totalUp'],[[str(i),'-1','1'] for i in range(9)],[''])
  p=n.parse(n.blocks(t)['/a']);self.assertEqual(len(p['rows']),9)
  self.assertEqual(p['rows'][4]['coordinates'],[{'native_index':1,'kind':'interval','low':0,'high':1},{'native_index':1,'kind':'category','category':'one'}]);self.assertFalse(p['rows'][4]['flow']);self.assertTrue(p['rows'][3]['flow']);self.assertEqual(p['rows'][7]['coordinates'][1]['category'],'two')
 def test_integer_categories_not_continuous_intervals(self):
  t=block('BINNEDESTIMATE<I>','/a',[[3,1,7]],['value','totalDn','totalUp'],[['1','-1','1']]*4,['']);p=n.parse(n.blocks(t)['/a']);self.assertEqual(p['rows'][2]['coordinates'][0]['category'],1);self.assertEqual(p['axes'][0]['values'],[3,1,7]);self.assertEqual(p['rows'][0]['coordinates'][0]['kind'],'otherflow')
 def test_categorical_hist_signed_zero_fill_moments_separate_from_errors(self):
  t=block('BINNEDHISTO<S>','/RAW/a',[['1.0','1e0']],['sumW','sumW2','numEntries'],[['0','0','2'],['-2','4','1'],['0','8','2']]);p=n.parse(n.blocks(t)['/RAW/a']);self.assertEqual(p['rows'][2]['primitive_moments'],{'sumW':0,'sumW2':8,'numEntries':2});self.assertEqual(p['rows'][1]['coordinates'][0]['category'],'1.0');self.assertIsNone(p['rows'][1]['variance']);self.assertIsNone(p['rows'][1]['native_errors'])
 def test_all_requested_states_weights_exact_and_undefined_tokens(self):
  objects=[];texts=[]
  for weight,suffix in [('nominal',''),('up','[up]')]:
   for role,path,kind in [('final','/a','BINNEDESTIMATE<S>'),('raw_estimate','/RAW/a','BINNEDESTIMATE<S>'),('raw_operand','/RAW/tmp','BINNEDHISTO<S>')]:
    actual=path+suffix;objects.append(obj(actual,kind,role,role,weight));texts.append(block(kind,actual,[['a']],['sumW','sumW2','numEntries'] if kind.startswith('BINNEDHISTO') else ['value','totalDn','totalUp'],[['0','0','1'],['-2','4','1']] if kind.startswith('BINNEDHISTO') else [['nan','---','---'],['1','-0','0']],None if kind.startswith('BINNEDHISTO') else ['']))
  c=request(objects);c['weight_mapping'].append({'id':'up','native':'up','suffix':'[up]'})
  with tempfile.TemporaryDirectory() as td:
   p=Path(td).resolve()/'native.yoda';p.write_text(''.join(texts));r=n.transport(p,c,expected_sha256=n.sha(p.read_bytes()));self.assertEqual(len(r['objects']),6);self.assertEqual(len(r['whole_native_object_inventory']),6);self.assertEqual(r['objects'][0]['object']['rows'][0]['tokens'],{'value':'nan','totalDn':'---','totalUp':'---'});self.assertIsNone(r['objects'][0]['object']['rows'][0]['native_errors'][0]['down'])
   bad=copy.deepcopy(c);bad['objects'][0]['path']='/missing'
   with self.assertRaises(n.NativeCategoricalError):n.transport(p,bad,expected_sha256=n.sha(p.read_bytes()))
 def test_refuses_duplicate_or_wrong_type_category_and_row_population(self):
  for kind,edges,rows in [('BINNEDESTIMATE<S>',[['x','x']],[['1']]*3),('BINNEDESTIMATE<S>',[[1,2]],[['1']]*3),('BINNEDESTIMATE<I>',[[True,2]],[['1']]*3),('BINNEDESTIMATE<S>',[['x','y']],[['1']]*2),('BINNEDESTIMATE<D>',[[0,1]],[['1']]*3)]:
   with self.assertRaises(n.NativeCategoricalError):n.parse(n.blocks(block(kind,'/a',edges,['value'],rows))['/a'])
 def test_refuses_raw_mixed_moments_without_writer_contract(self):
  with self.assertRaisesRegex(n.NativeCategoricalError,'writer'):n.parse(n.blocks(block('BINNEDHISTO<D,S>','/a',[[0,1],['x']],['sumW','sumW2','sumW(A1)','sumW2(A1)','numEntries'],[['0']*5]*6))['/a'])
 def test_complete_errors_and_finite_primitive_failures(self):
  for row in [['1','---','1'],['1','1','2'],['inf','-1','1']]:
   with self.assertRaises(n.NativeCategoricalError):n.parse(n.blocks(block('BINNEDESTIMATE<S>','/a',[['x']],['value','totalDn','totalUp'],[row]*2,['']))['/a'])
  for row in [['1','-1','1'],['1','1','-1'],['nan','1','1']]:
   with self.assertRaises(n.NativeCategoricalError):n.parse(n.blocks(block('BINNEDHISTO<S>','/a',[['x']],['sumW','sumW2','numEntries'],[row]*2))['/a'])
 def test_masked_undefined_multierror_tokens_no_covariance_fabricated(self):
  t=block('BINNEDESTIMATE<S>','/a',[['x']],['value','errDn(1)','errUp(1)','errDn(2)','errUp(2)'],[['nan','---','---','---','---'],['1','-2','3','---','---']],['stat','sys']);t=t.replace('---\nEdges','---\nMaskedBins: [1]\nEdges',1);p=n.parse(n.blocks(t)['/a']);self.assertTrue(p['rows'][1]['masked']);self.assertEqual(p['rows'][1]['status'],'masked_undefined_native_errors');self.assertIsNone(p['covariance'])
 def test_closed_hash_source_and_contract_controls(self):
  c=request([obj('/REF/SYN_9392_I1403/d01-x01-y01','BINNEDESTIMATE<S>','reference')]);bad=copy.deepcopy(c);bad['sources'][0]['text']+='changed'
  with self.assertRaises(n.NativeCategoricalError):n.inputs(bad)
  with self.assertRaises(n.NativeCategoricalError):n.transport(REF,c,expected_sha256='0'*64)
  for edit in [lambda c:c.update(interpretation='differential'),lambda c:c['weight_mapping'].append(c['weight_mapping'][0]),lambda c:c['objects'].append(c['objects'][0]),lambda c:c['objects'][0].update(role='raw_operand')]:
   bad=copy.deepcopy(c);edit(bad)
   with self.assertRaises(n.NativeCategoricalError):n.validate(bad)
 def test_bounded_descriptor_refuses_oversize_before_read_and_links(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();p=root/'big.yoda'
   with p.open('wb') as stream:stream.truncate(32*1024*1024+1)
   with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded path read forbidden')):
    with self.assertRaisesRegex(n.NativeCategoricalError,'byte bound'):n.read_bytes(p)
    p.write_text('small');self.assertEqual(n.read_bytes(p),(b'small','small'))
   linked=root/'link';linked.symlink_to(p)
   with self.assertRaisesRegex(n.NativeCategoricalError,'regular'):n.read_bytes(linked)
 def test_real_parent_alias_after_read_refused(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();parent=root/'original';parent.mkdir();p=parent/'a';p.write_text('same inode retained');original=n.os.fdopen
   class AliasAfterRead:
    def __init__(self,stream):self.stream=stream
    def __enter__(self):return self
    def __exit__(self,*args):self.stream.close()
    def fileno(self):return self.stream.fileno()
    def read(self,size):
     data=self.stream.read(size);parent.rename(root/'moved');parent.symlink_to(root/'moved',target_is_directory=True);return data
   with patch.object(n.os,'fdopen',side_effect=lambda *args:AliasAfterRead(original(*args))):
    with self.assertRaisesRegex(n.NativeCategoricalError,'ending'):n.read_bytes(p)
 def test_descriptor_metadata_change_refused(self):
  from unittest.mock import patch
  import os,types
  with tempfile.TemporaryDirectory() as td:
   p=Path(td).resolve()/'a';p.write_text('a');st=p.stat();calls=0
   def changed(fd):
    nonlocal calls
    calls+=1
    return st if calls==1 else types.SimpleNamespace(st_dev=st.st_dev,st_ino=st.st_ino,st_size=st.st_size,st_mtime_ns=st.st_mtime_ns+1,st_ctime_ns=st.st_ctime_ns)
   with patch.object(n.os,'fstat',side_effect=changed):
    with self.assertRaisesRegex(n.NativeCategoricalError,'changed'):n.read_bytes(p)
 def test_declared_weight_name_not_observed(self):
  p='/REF/SYN_9392_I1403/d01-x01-y01';c=request([obj(p,'BINNEDESTIMATE<S>','reference')]);c['weight_mapping'][0]['native']='arbitrary declared default'
  r=n.transport(REF,c,expected_sha256=n.sha(REF.read_bytes()));self.assertFalse(r['native_weight_identity_observed']);self.assertEqual(r['weight_identity_status'],'declared_unverified')
 def test_closed_native_block_and_json_controls(self):
  for text in ['BEGIN YODA_BINNEDESTIMATE<S>_V3 /a\n','unexpected\n','BEGIN YODA_BINNEDESTIMATE<S>_V3 /a\nEND YODA_BINNEDHISTO<S>_V3\n']:
   with self.assertRaises(n.NativeCategoricalError):n.blocks(text)
  for text in ['{"x":1,"x":2}','[NaN]']:
   with self.assertRaises(n.NativeCategoricalError):n.decode(text)
if __name__=='__main__':unittest.main()
