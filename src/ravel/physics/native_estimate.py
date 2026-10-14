"""Source-bound native one-axis ratio/efficiency/asymmetry estimate transport.

Preserves serialized values, signed labeled errors, undefined states, RAW estimate
and complete histogram operands. No bin-width conversion, moments from errors,
unit-area assertion, covariance construction, or inference is performed.
"""
import gzip
import hashlib
import io
import json
import math
import re
from pathlib import Path

class NativeEstimateError(ValueError):
    """A declared native derived output cannot be transported faithfully."""

def _require(value, message):
    if not value:
        raise NativeEstimateError(message)

def _keys(value, keys):
    _require(isinstance(value, dict) and set(value) == set(keys), 'exact native derived contract keys required')

def _text(value):
    _require(isinstance(value, str) and bool(value.strip()), 'explicit text identity required')
    return value

def validate_request(request):
    _keys(request, ('path','axes','representation','normalization','unit','quantity_kind','native_derived'))
    _require(request['quantity_kind'] == 'native_derived_estimate' and request['representation'] == 'native'
             and request['normalization'] == 'absolute' and request['unit'] == '1',
             'native derived estimate requires native representation, absolute normalization and dimensionless unit1')
    _require(isinstance(request['path'], str) and request['path'].startswith('/') and not request['path'].startswith('/RAW/'), 'final native output path required')
    _require(isinstance(request['axes'], list) and len(request['axes']) == 1, 'native derived estimate currently supports one continuous axis')
    for axis in request['axes']:
        _keys(axis, ('name','unit')); _text(axis['name']); _text(axis['unit'])
    contract=request['native_derived']
    _keys(contract, ('operation','source','native_error_semantics','raw_estimate_path','operands','flow_policy','group_covariance'))
    _require(contract['operation'] in ('ratio','efficiency','asymmetry'), 'explicit supported native derived operation required')
    _text(contract['native_error_semantics'])
    _require(contract['flow_policy']=='retain_all' and contract['group_covariance']=='not_supplied', 'all native flows retained; group covariance must remain separately supplied')
    _require(contract['raw_estimate_path']=='/RAW'+request['path'], 'exact matching RAW estimate path required')
    source=contract['source']; _keys(source, ('path','sha256','first_line','last_line','text'))
    _text(source['path']); _require(Path(source['path']).is_absolute(), 'absolute source-definition path required for the retained native worker')
    _require(isinstance(source['sha256'],str) and re.fullmatch('[0-9a-f]{64}',source['sha256']), 'source SHA256 required')
    _require(type(source['first_line']) is int and type(source['last_line']) is int and 1 <= source['first_line'] <= source['last_line'], 'exact source excerpt line interval required'); _text(source['text'])
    roles={'ratio':{'numerator','denominator'},'efficiency':{'passed','total'},'asymmetry':{'left','right'}}[contract['operation']]
    operands=contract['operands']; _require(isinstance(operands,list) and len(operands)==2, 'complete two histogram operand census required')
    for operand in operands:
        _keys(operand, ('id','role','path')); _text(operand['id'])
        _require(isinstance(operand['role'],str) and operand['role'] in roles, 'explicit supported operand role required')
        _require(isinstance(operand['path'],str) and operand['path'].startswith('/RAW/'), 'explicit RAW histogram operand path required')
    _require({o['role'] for o in operands}==roles and len({o['id'] for o in operands})==2 and len({o['path'] for o in operands})==2, 'exact distinct native operand roles/identities required')
    return request


def _source(contract, base_dir):
    source=contract['source']; path=Path(source['path'])
    if not path.is_absolute(): path=Path(base_dir)/path
    _require(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)), 'regular source-definition file required')
    data=path.read_bytes(); _require(hashlib.sha256(data).hexdigest()==source['sha256'], 'native derivation source hash differs')
    lines=data.decode('utf-8').splitlines(); _require(source['last_line']<=len(lines) and '\n'.join(lines[source['first_line']-1:source['last_line']])==source['text'], 'native derivation source excerpt differs')
    return path


def inputs(request, base_dir='.'):
    """Bind the formula bytes and this transport implementation before execution."""
    validate_request(request)
    return [_source(request['native_derived'], base_dir), Path(__file__).resolve()]


def _read(path):
    path=Path(path); _require(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)), 'regular retained YODA source file required')
    bytes_=path.read_bytes(); _require(len(bytes_)<=32*1024*1024, 'native text byte budget exceeded')
    try:
        if path.suffix=='.gz':
            with gzip.GzipFile(fileobj=io.BytesIO(bytes_)) as stream:
                decoded=stream.read(64*1024*1024+1)
            _require(len(decoded)<=64*1024*1024, 'native decompressed text budget exceeded')
        else:
            decoded=bytes_
        text=decoded.decode('utf-8')
    except (OSError,EOFError,UnicodeError) as exc: raise NativeEstimateError('retained YODA V3 text required') from exc
    _require(len(text)<=64*1024*1024, 'native decompressed text budget exceeded')
    blocks={}; pattern=r'^BEGIN YODA_([A-Z0-9<>]+)_V3 ([^\n]+)\n(.*?)^END YODA_\1_V3\s*$'
    matches=list(re.finditer(pattern,text,re.M|re.S))
    _require(len(matches)==text.count('BEGIN YODA_'), 'every native text object must close in V3 format')
    for match in matches:
        kind,name,body=match.groups(); _require(name not in blocks, 'duplicate native text object')
        blocks[name]={'type':kind,'body':body}
    return blocks, hashlib.sha256(bytes_).hexdigest()


def _data(block):
    body=block['body']; edges=re.findall(r'^Edges\(A1\): (.+)$',body,re.M)
    _require(len(edges)==1 and 'Edges(A2):' not in body, 'one continuous native axis required')
    try: values=json.loads(edges[0])
    except ValueError as exc: raise NativeEstimateError('native edges must be numeric JSON') from exc
    _require(isinstance(values,list) and len(values)>=2 and all(type(v) in (int,float) and math.isfinite(v) for v in values)
             and all(a<b for a,b in zip(values,values[1:])), 'finite strictly ordered native axis geometry required')
    lines=body.splitlines(); headers=[i for i,line in enumerate(lines) if line.startswith('# value') or line.startswith('# sumW')]
    _require(len(headers)==1,'one complete native column header required'); head=headers[0]; columns=lines[head][1:].split()
    _require(len(set(columns))==len(columns),'duplicate native columns')
    rows=[line.split() for line in lines[head+1:] if line.strip() and not line.startswith('#')]
    _require(len(rows)==len(values)+1 and all(len(row)==len(columns) for row in rows), 'complete native finite/flow row and column census required')
    return values,columns,rows


def _number(token, nullable=False):
    if nullable and token.lower() in ('nan','+nan','-nan','---'):return None
    _require(bool(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',token)), 'finite decimal native token required')
    value=float(token); _require(math.isfinite(value), 'finite native value required')
    return value


def _geometry(edges,index):
    return {'bin':'underflow' if index==0 else ('overflow' if index==len(edges) else str(index-1)),
            'low':[None if index==0 else edges[index-1]], 'high':[None if index==len(edges) else edges[index]],
            'flow':index in (0,len(edges))}


def _estimate(block):
    _require(block['type']=='ESTIMATE1D', 'final/RAW derived object must be a native Estimate1D')
    edges,columns,rows=_data(block)
    labels=re.findall(r'^ErrorLabels: (.+)$',block['body'],re.M); _require(len(labels)<=1, 'literal native error-label census required')
    try: labels=json.loads(labels[0]) if labels else []
    except ValueError as exc: raise NativeEstimateError('native error-label list required') from exc
    _require(isinstance(labels,list) and all(isinstance(v,str) for v in labels) and len(set(labels))==len(labels), 'complete unique native error labels required')
    expected=['value']
    for i,label in enumerate(labels,1):expected+=['totalDn','totalUp'] if label=='' else [f'errDn({i})',f'errUp({i})']
    _require(columns==expected, 'source error-label/column order differs')
    bins=[]
    for i,row in enumerate(rows):
        value=_number(row[0],True); errors=[]
        for k,label in enumerate(labels):
            down,up=(_number(token,True) for token in row[1+2*k:3+2*k])
            _require((down is None)==(up is None), 'partial native error direction missing')
            _require(down is None or down<=0<=up, 'native signed error directions invalid')
            errors.append({'label':label,'down':down,'up':up,'down_token':row[1+2*k],'up_token':row[2+2*k]})
        # A missing native value/error stays missing. Defined value with unavailable
        # native errors is not silently given a zero uncertainty or a covariance.
        summary=next((e for e in errors if e['label']==''), errors[0] if len(errors)==1 else None)
        bins.append({**_geometry(edges,i),'status':'undefined_value' if value is None else ('undefined_native_errors' if not errors or any(e['down'] is None for e in errors) else 'defined'),
                     'value':value,'value_token':row[0],'native_errors':errors,
                     'error_low':None if summary is None or summary['down'] is None else abs(summary['down']),
                     'error_high':None if summary is None else summary['up'],
                     'marginal_summary':'explicit_native_total' if summary is not None and summary['label']=='' else ('sole_native_error_label' if summary is not None else 'no_total_reported_multiple_labels'),
                     'variance':None,'integrated_sumw':None,'entries':None,'tokens':dict(zip(columns,row))})
    return {'native_type':'Estimate1D','edges':edges,'columns':columns,'error_labels':labels,'bins':bins,'native_text':block['body']}


def _histogram(block):
    _require(block['type']=='HISTO1D','derived operands must be actual RAW Histo1D objects')
    edges,columns,rows=_data(block); _require(columns==['sumW','sumW2','sumW(A1)','sumW2(A1)','numEntries'], 'complete RAW histogram primitive columns required')
    bins=[]
    for i,row in enumerate(rows):
        w,q,x,x2,entries=[_number(token) for token in row]
        _require(q>=0 and entries>=0,'nonnegative RAW second moment/entries required')
        bins.append({**_geometry(edges,i),'sumw':w,'sumw2':q,'coordinate_sumw':x,'coordinate_squared_sumw':x2,'entries':entries,'tokens':dict(zip(columns,row))})
    return {'native_type':'Histo1D','edges':edges,'columns':columns,'bins':bins,'native_text':block['body'],'moment_scope':'Native per-fill primitive moments; event-group outer products and cross-output covariance are not inferred.'}


def transport(path,request,*,base_dir='.'):
    """Read source-bound native text; keep all final, RAW-estimate and operand rows."""
    validate_request(request); contract=request['native_derived']; _source(contract,base_dir)
    objects,hash_= _read(path); name=request['path']; raw_name=contract['raw_estimate_path']
    _require(name in objects and raw_name in objects,'complete final and RAW derived Estimate objects required')
    final,raw=_estimate(objects[name]),_estimate(objects[raw_name]); _require(final['edges']==raw['edges'],'final and RAW estimate geometry differs')
    operands=[]
    for operand in contract['operands']:
        _require(operand['path'] in objects,'declared RAW histogram operand missing')
        value=_histogram(objects[operand['path']]); _require(value['edges']==final['edges'],'RAW operand and final estimate literal geometry differs')
        operands.append({**operand,'object':value})
    return {'contract':request,'quantity_kind':'native_derived_estimate','bins':[b for b in final['bins'] if not b['flow']],
            'all_native_bins':final['bins'],'native_finalized':final,'raw_estimate':raw,'raw_operands':operands,
            'yoda_text_sha256':hash_,'all_object_paths':sorted(objects),
            'storage_semantics':'Untransformed native dimensionless derived estimate; signed labeled errors and undefined value/error tokens preserved, including all flows.',
            'source_definition':contract['source'],'native_error_semantics':contract['native_error_semantics'],
            'flow_sumw':None,'flow_sumw2':None,'raw_flow_sumw':None,'covariance':None,
            'covariance_scope':'Native marginal errors transported only. No bin/group covariance, Gaussian calibration, efficiency reinterpretation, or variance from error bars.',
            'unit_scope':'Caller-declared dimensionless native value. No width conversion or unit-area normalization assertion.',
            'physics_validated':False}
