"""Source-bound categorical/mixed-axis native YODA V3 transport.

Literal S/I categories are never turned into numeric intervals. D axes retain
native finite/flow geometry. Native values/errors and per-fill RAW tokens remain
separate from event-group covariance and scientific inference. No native runner.
"""
import gzip,hashlib,io,json,math,os,re,stat
from pathlib import Path
class NativeCategoricalError(ValueError):pass

def require(ok,why):
 if not ok:raise NativeCategoricalError(why)
def object_pairs(pairs):
 out={}
 for k,v in pairs:require(k not in out,'duplicate JSON key');out[k]=v
 return out
def decode(value):
 return json.loads(value,object_pairs_hook=object_pairs,parse_constant=lambda _: (_ for _ in ()).throw(NativeCategoricalError('nonfinite JSON')))
def sha(data):return hashlib.sha256(data).hexdigest()
def number(token,nullable=False):
 if nullable and token.lower() in ('nan','+nan','-nan','---'):return None
 require(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',token) is not None,'finite native decimal token required')
 value=float(token);require(math.isfinite(value),'finite representable native token required');return value

def read_bytes(path):
 p=Path(path);require(p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'regular source file required')
 limit=32*1024*1024
 def identity(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
 before=p.stat(follow_symlinks=False)
 descriptor=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(descriptor,'rb') as stream:
  selected=os.fstat(stream.fileno())
  require(stat.S_ISREG(selected.st_mode) and identity(selected)==identity(before),'stable regular descriptor identity required')
  require(selected.st_size<=limit,'compressed byte bound')
  raw=stream.read(limit+1)
  require(len(raw)<=limit and len(raw)==selected.st_size,'bounded complete source read required')
  require(p.is_file() and not any(q.is_symlink() for q in (p,*p.parents)),'ending regular nonlinked leaf and ancestors required')
  require(identity(os.fstat(stream.fileno()))==identity(selected) and identity(p.stat(follow_symlinks=False))==identity(selected),'source changed during descriptor read')
 if p.suffix=='.gz':
  with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:data=stream.read(64*1024*1024+1)
 else:data=raw
 require(len(data)<=64*1024*1024,'decompressed byte bound');return raw,data.decode('utf-8')

def blocks(text):
 out={};lines=text.splitlines(keepends=True);i=0
 while i<len(lines):
  line=lines[i].rstrip('\r\n')
  if not line.strip() or line.startswith('#'):i+=1;continue
  m=re.fullmatch(r'BEGIN YODA_([A-Z0-9<>,]+)_V3 (\S+)',line);require(m is not None,'closed V3 native object format required');kind,path=m.groups();require(path not in out,'duplicate native object path')
  start=i;i+=1;body=i
  while i<len(lines) and lines[i].rstrip('\r\n')!='END YODA_'+kind+'_V3':
   require(not lines[i].startswith(('BEGIN ','END ')),'nested or mismatched native object');i+=1
  require(i<len(lines),'unterminated native object');out[path]={'type':kind,'path':path,'body':''.join(lines[body:i]),'block_sha256':sha(''.join(lines[start:i+1]).encode())};i+=1
 require(out,'empty native file');return out

def axes(block):
 m=re.fullmatch(r'BINNED(HISTO|ESTIMATE)<([DIS](?:,[DIS]){0,2})>',block['type']);require(m is not None,'one-to-three-axis typed BinnedHisto/Estimate required');kind=m[1];types=m[2].split(',');require(any(t!='D' for t in types),'categorical or mixed axis required')
 edge_rows=re.findall(r'^Edges\(A([1-9][0-9]*)\): (.+)$',block['body'],re.M);require([int(i) for i,_ in edge_rows]==list(range(1,len(types)+1)),'exact axis order/count required');out=[]
 for t,(_,literal) in zip(types,edge_rows):
  values=decode(literal);require(isinstance(values,list) and len(values)>0,'explicit nonempty native geometry')
  if t=='D':require(len(values)>=2 and all(type(v) in (int,float) and math.isfinite(v) for v in values) and all(a<b for a,b in zip(values,values[1:])),'finite ordered continuous edges');size=len(values)+1
  else:
   require(all(type(v) is (str if t=='S' else int) for v in values),'literal category type differs')
   require(len(set(values))==len(values),'duplicate category');size=len(values)+1
  out.append({'native_axis_type':t,'values':values,'literal':literal,'size_with_flows':size,'semantics':'continuous_half_open' if t=='D' else 'literal_categories_with_OTHER'})
 return kind,out

def coordinate(axis,index):
 values=axis['values'];t=axis['native_axis_type']
 if t in ('S','I'):return {'native_index':index,'kind':'otherflow' if index==0 else 'category','category':None if index==0 else values[index-1]}
 return {'native_index':index,'kind':'underflow' if index==0 else ('overflow' if index==len(values) else 'interval'),'low':None if index==0 else values[index-1],'high':None if index==len(values) else values[index]}

def parse(block):
 require(re.findall(r'^Path: (.+)$',block['body'],re.M)==[block['path']],'BEGIN/native Path identity must match exactly once')
 kind,ax=axes(block);size=math.prod(a['size_with_flows'] for a in ax);require(size<=100000,'bounded complete native row population')
 lines=block['body'].splitlines();headers=[i for i,l in enumerate(lines) if l.startswith('# value') or l.startswith('# sumW')];require(len(headers)==1,'one native numerical header required');h=headers[0];columns=lines[h][1:].split();require(len(set(columns))==len(columns),'duplicate native column')
 rows=[l.split() for l in lines[h+1:] if l.strip() and not l.startswith('#')];require(len(rows)==size and all(len(row)==len(columns) for row in rows),'complete finite/flow numerical census required')
 masks=re.findall(r'^MaskedBins: (.+)$',block['body'],re.M);require(len(masks)<=1,'unique masked-bin declaration');masked=decode(masks[0]) if masks else []
 require(isinstance(masked,list) and all(type(i) is int and 0<=i<size for i in masked) and len(set(masked))==len(masked),'exact masked-bin index census')
 labels=[]
 if kind=='ESTIMATE':
  error_labels=re.findall(r'^ErrorLabels: (.+)$',block['body'],re.M);require(len(error_labels)<=1,'unique native error labels');labels=decode(error_labels[0]) if error_labels else []
  require(isinstance(labels,list) and all(isinstance(v,str) for v in labels) and len(set(labels))==len(labels),'exact native labeled error order')
  expected=['value']
  for i,label in enumerate(labels,1):expected+=['totalDn','totalUp'] if label=='' else [f'errDn({i})',f'errUp({i})']
  require(columns==expected,'native error label/column mismatch')
 else:
  require(all(a['native_axis_type']!='D' for a in ax),'mixed continuous RAW moments require separately qualified writer column contract')
  require(columns==['sumW','sumW2','numEntries'],'complete categorical RAW primitive column order required')
 result=[]
 for ordinal,row in enumerate(rows):
  remainder=ordinal;coords=[]
  # Pinned YODA Binning.h localToGlobalIndex: x+y*width+z*width*height.
  for a in ax:index=remainder%a['size_with_flows'];remainder//=a['size_with_flows'];coords.append(coordinate(a,index))
  require(remainder==0,'native serialization index overflow');flow=any(c['kind'] not in ('category','interval') for c in coords)
  if kind=='ESTIMATE':
   value=number(row[0],True);errors=[]
   for i,label in enumerate(labels):
    down,up=(number(v,True) for v in row[1+2*i:3+2*i]);require((down is None)==(up is None),'partial error direction undefined');require(down is None or down<=0<=up,'signed native error convention required');errors.append({'label':label,'down':down,'up':up,'tokens':row[1+2*i:3+2*i]})
   data={'value':value,'native_errors':errors,'status':'undefined_value' if value is None else ('undefined_native_errors' if not labels or any(e['down'] is None for e in errors) else 'defined'),'variance':None}
  else:
   values=[number(v) for v in row];require(values[1]>=0 and values[-1]>=0,'native sumW2/entries nonnegative');data={'primitive_moments':dict(zip(columns,values)),'native_errors':None,'variance':None,'status':'native_per_fill_moments'}
  if ordinal in masked:data['status']='masked_'+data['status']
  result.append({'serialized_index':ordinal,'coordinates':coords,'flow':flow,'masked':ordinal in masked,'tokens':dict(zip(columns,row)),**data})
 return {'native_type':block['type'],'axes':ax,'columns':columns,'error_labels':labels,'rows':result,'block_sha256':block['block_sha256'],'native_text':block['body'],'histogram_width_transform_applied':False,'covariance':None,'native_group_moments_inferred':False}

def validate(request):
 require(isinstance(request,dict) and set(request)=={'schema_version','sources','objects','weight_mapping','interpretation'},'closed categorical request required');require(type(request['schema_version']) is int and request['schema_version']==1,'schema1 required')
 require(request['interpretation']=='untransformed_native','source categorical values already finalized; no rescaling/density inference')
 sources=request['sources'];require(isinstance(sources,list) and 1<=len(sources)<=128,'bound source/grammar inventory')
 for s in sources:require(set(s)=={'path','sha256','first_line','last_line','text'} and isinstance(s['path'],str) and isinstance(s['sha256'],str) and re.fullmatch('[0-9a-f]{64}',s['sha256']) and type(s['first_line']) is int and type(s['last_line']) is int and 1<=s['first_line']<=s['last_line'] and isinstance(s['text'],str),'source definition pin and excerpt required')
 require(len({(s['path'],s['first_line'],s['last_line']) for s in sources})==len(sources),'duplicate source definition excerpt')
 names=request['weight_mapping'];require(isinstance(names,list) and 1<=len(names)<=64 and all(set(w)=={'id','native','suffix'} and all(isinstance(v,str) for v in w.values()) and w['id'] for w in names),'complete weight identity mapping');require(all(len({w[k] for w in names})==len(names) for k in ('id','native','suffix')),'unique native selected weight mapping')
 objects=request['objects'];require(isinstance(objects,list) and 1<=len(objects)<=1024,'bound source object census')
 for o in objects:
  require(set(o)=={'id','weight','path','role','native_type','unit','source_definition'} and isinstance(o['id'],str) and o['id'] and o['weight'] in {w['id'] for w in names} and isinstance(o['path'],str) and o['path'].startswith('/') and o['role'] in ('final','raw_operand','raw_estimate','reference') and isinstance(o['unit'],str) and o['unit'] and type(o['source_definition']) is int and 0<=o['source_definition']<len(sources),'explicit object/weight/source/unit contract required')
  require((o['role'] not in ('raw_operand','raw_estimate') or o['path'].startswith('/RAW/')) and (o['role']!='reference' or o['path'].startswith('/REF/')),'native object role/path identity differs')
  require(isinstance(o['native_type'],str) and re.fullmatch(r'BINNED(HISTO|ESTIMATE)<[DIS](?:,[DIS]){0,2}>',o['native_type']) is not None,'supported categorical native type declaration required')
  suffix=next(w['suffix'] for w in names if w['id']==o['weight'])
  require(o['path'].endswith(suffix) if suffix else not any(o['path'].endswith(w['suffix']) for w in names if w['suffix']),'declared native weight suffix differs')
  require(o['role']!='raw_operand' or o['native_type'].startswith('BINNEDHISTO'),'RAW operand requires native histogram moments')
  require(o['role']!='raw_estimate' or o['native_type'].startswith('BINNEDESTIMATE'),'RAW estimate must retain native Estimate semantics')
 require(len({(o['id'],o['weight'],o['role']) for o in objects})==len(objects) and len({o['path'] for o in objects})==len(objects),'exact unique object/weight/role census');return request

def inputs(request,base_dir='.'):
 validate(request);out=[]
 for s in request['sources']:
  p=Path(s['path']);p=p if p.is_absolute() else Path(base_dir)/p;raw,text=read_bytes(p);require(sha(raw)==s['sha256'],'source definition digest mismatch');lines=text.splitlines();require(s['last_line']<=len(lines) and '\n'.join(lines[s['first_line']-1:s['last_line']])==s['text'],'source definition excerpt mismatch');out.append(p.resolve())
 return out+[Path(__file__).resolve()]

def transport(path,request,*,expected_sha256,base_dir='.'):
 inputs(request,base_dir);raw,text=read_bytes(path);require(sha(raw)==expected_sha256,'retained output hash mismatch');all_objects=blocks(text);result=[]
 for o in request['objects']:
  require(o['path'] in all_objects and all_objects[o['path']]['type']==o['native_type'],'complete exact requested typed object required');result.append({**o,'object':parse(all_objects[o['path']])})
 return {'schema_version':1,'kind':'native-categorical-observables','objects':result,'weight_mapping':request['weight_mapping'],'weight_identity_status':'declared_unverified','native_weight_identity_observed':False,'whole_native_object_inventory':[{'path':p,'native_type':b['type'],'block_sha256':b['block_sha256']} for p,b in all_objects.items()],'source_yoda_sha256':expected_sha256,'source_definitions':request['sources'],'interpretation':'untransformed_native','output_census_qualified':False,'covariance':None,'physics_validated':False,'limits':['Requested typed source objects transported exactly; whole observed file inventory retained separately, not a declared source-booking census proof.','Literal categories/OTHER and native mixed continuous UF/OF preserved, with first axis fastest source serialization.','Final native marginal signed/labeled errors are not per-fill sumW2, shared group covariance or calibrated inference.','No numeric-label coercion, widths, rebinning, scaling, normalization or cross-category geometry equivalence inferred.']}


def validate_request(request):
 """Normal Rivet quantity contract; preserves source native dimensions and states."""
 require(isinstance(request,dict) and set(request)=={'path','axes','representation','normalization','unit','quantity_kind','native_categorical'},'closed native categorical quantity required')
 require(request['quantity_kind']=='native_categorical' and request['representation']=='native' and request['normalization']=='absolute','untransformed native categorical quantity required')
 require(isinstance(request['path'],str) and request['path'].startswith('/') and not request['path'].startswith(('/RAW/','/REF/')),'literal finalized native path required')
 require(isinstance(request['unit'],str) and bool(request['unit'].strip()),'source dependent-variable unit required')
 c=request['native_categorical'];require(isinstance(c,dict) and set(c)=={'source','source_dependencies','final_native_type','raw_objects','source_finalization','native_error_semantics','flow_policy','group_covariance','native_weight'},'closed source finalization contract required')
 require(c['flow_policy']=='retain_all' and c['group_covariance']=='not_supplied','all flow states retained; native marginal errors are separate from group covariance')
 require(all(isinstance(c[k],str) and c[k].strip() for k in ('source_finalization','native_error_semantics')),'explicit source finalization/error semantics required')
 require(isinstance(c['source_dependencies'],list) and 1<=len(c['source_dependencies'])<=32,'source grammar/normalization dependencies required')
 require(isinstance(c['raw_objects'],list) and 1<=len(c['raw_objects'])<=32,'explicit complete source RAW states required')
 objects=[{'id':'final','weight':'selected','path':request['path'],'role':'final','native_type':c['final_native_type'],'unit':request['unit'],'source_definition':0}]
 for o in c['raw_objects']:
  require(isinstance(o,dict) and set(o)=={'id','path','role','native_type','unit'} and o['role'] in ('raw_operand','raw_estimate'),'literal RAW state contract required')
  objects.append({**o,'weight':'selected','source_definition':0})
 require(isinstance(c['native_weight'],dict) and set(c['native_weight'])=={'native','suffix'},'explicit selected native weight identity required')
 generic={'schema_version':1,'sources':[c['source'],*c['source_dependencies']],'objects':objects,'weight_mapping':[{'id':'selected',**c['native_weight']}],'interpretation':'untransformed_native'}
 validate(generic)
 m=re.fullmatch(r'BINNED(?:HISTO|ESTIMATE)<([DIS](?:,[DIS]){0,2})>',c['final_native_type']);types=m[1].split(',')
 require(isinstance(request['axes'],list) and len(request['axes'])==len(types),'exact typed axis census required')
 for axis,t in zip(request['axes'],types):
  require(isinstance(axis,dict) and set(axis)=={'name','unit','native_type'} and axis['native_type']==t and all(isinstance(axis[k],str) and axis[k].strip() for k in ('name','unit')),'named source axis contract required')
  require(t=='D' or axis['unit']=='1','categorical labels cannot be assigned numeric coordinate units')
 return generic

def quantity_inputs(request,base_dir='.'):
 return list(dict.fromkeys(inputs(validate_request(request),base_dir)))

def export_quantity(path,request):
 """Ordinary exporter seam. Output custody binds the newly produced source file."""
 generic=validate_request(request);raw,_=read_bytes(path);result=transport(path,generic,expected_sha256=sha(raw))
 final=result['objects'][0]['object']
 return {'contract':request,'quantity_kind':'native_categorical','native_finalized':final,'all_native_rows':final['rows'],'bins':[r for r in final['rows'] if not r['flow']],
  'raw_objects':result['objects'][1:],'transport':result,'weight_identity_status':'declared_unverified','native_weight_identity_observed':False,'flow_sumw':None,'flow_sumw2':None,'raw_flow_sumw':None,'covariance':None,
  'storage_semantics':'Source-native literal categorical/mixed geometry and complete native value/error or per-fill moment states; no transforms.',
  'variance_from_error_bars':False,'physics_validated':False}

def write_report(observables,output):
 """Portable complete token table, including undefined and OTHER/UF/OF states."""
 report=[];rows=[]
 for path,obj in observables.items():
  if obj.get('quantity_kind')!='native_categorical':continue
  validate_request(obj['contract']);require(path==obj['contract']['path'],'report source path differs')
  require(obj['all_native_rows']==obj['native_finalized']['rows'] and obj['covariance'] is None and obj['variance_from_error_bars'] is False,'complete native rows without inferred covariance required')
  report.append({'path':path,'observable':obj})
  for row in obj['all_native_rows']:
   cells=[path,row['serialized_index'],json.dumps(row['coordinates'],ensure_ascii=False),json.dumps(row['tokens']),obj['contract']['unit'],row['masked'],row['status']]
   rows.append('| '+' | '.join(str(c).replace('|','\\|').replace('\n',' ') for c in cells)+' |')
 if not report:return []
 from ravel.workflow.state_io import atomic_json
 out=Path(output);atomic_json(out/'native-categorical-observables.json',{'schema_version':1,'kind':'native_categorical_report','objects':report,'covariance':None,'physics_validated':False})
 (out/'native-categorical-observables.md').write_text('# Native categorical observables\n\n| Observable | Native index | Literal coordinates | Native tokens | Unit | Masked | Status |\n|---|---|---|---|---|---|---|\n'+'\n'.join(rows)+'\n\nFull final/RAW states and all flows are retained in JSON. Labels are categorical identities, not numeric intervals. No values/errors/units are converted; declared weight names/suffixes are unverified mappings, not observed native weight identity. No event-group covariance or physics acceptance is inferred.\n')
 return [{'stem':'native-categorical-observables','files':['native-categorical-observables.json','native-categorical-observables.md'],'normalization':'Source-native values, errors, categories and flows; no transformations'}]
