"""Bounded static ONNX tensor/metadata/dependency census; never runs a model.

Field numbers follow the separately pinned official onnx.proto. Unknown fields
remain in the whole model digest; this is not an ONNX checker/runtime substitute.
"""
import hashlib
import json,os,stat
from pathlib import Path
import math
import struct

LIMIT=4*1024*1024


def varint(raw, i):
    value=0
    for shift in range(0,70,7):
        if i>=len(raw):raise ValueError('truncated protobuf integer')
        byte=raw[i];i+=1
        if shift==63 and byte>1:raise ValueError('protobuf integer exceeds64bits')
        value|=(byte&127)<<shift
        if not byte&128:return value,i
    raise ValueError('unbounded protobuf integer')


def fields(raw):
    if type(raw) is not bytes or len(raw)>LIMIT:raise ValueError('bounded static protobuf bytes required')
    out={};i=0;count=0
    while i<len(raw):
        key,i=varint(raw,i);number,wire=key>>3,key&7
        if number==0 or wire not in (0,1,2,5):raise ValueError('unserved protobuf field/wire')
        if wire==0:value,i=varint(raw,i)
        else:
            if wire==2:size,i=varint(raw,i)
            else:size=8 if wire==1 else 4
            if size>len(raw)-i:raise ValueError('truncated protobuf field')
            value=raw[i:i+size];i+=size
        out.setdefault(number,[]).append((wire,value));count+=1
        if count>100000:raise ValueError('bounded protobuf field census')
    return out


def one(f,n,wire,default=None):
    values=f.get(n,[])
    if not values:return default
    if len(values)!=1 or values[0][0]!=wire:raise ValueError('unique typed protobuf field required')
    return values[0][1]


def text(value):
    if value is None:return None
    return value.decode('utf-8')


def messages(f,n):
    if any(w!=2 for w,v in f.get(n,[])):raise ValueError('length-delimited message field required')
    return [fields(v) for w,v in f.get(n,[])]


def pairs(f,n):
    result={}
    for p in messages(f,n):
        k=text(one(p,1,2));v=text(one(p,2,2))
        if k is None or v is None or k in result:raise ValueError('unique complete metadata key/value required')
        result[k]=v
    return result


def value_info(value):
    t=fields(one(value,2,2,b''));tensor=one(t,1,2)
    out={'name':text(one(value,1,2)),'tensor':tensor is not None}
    if tensor is None:return out|{'non_tensor_type_fields':sorted(t)}
    tensor=fields(tensor);shape=fields(one(tensor,2,2,b''));dims=[]
    for d in messages(shape,1):
        v=one(d,1,0);symbol=text(one(d,2,2))
        if v is not None and symbol is not None:raise ValueError('tensor dimension oneof conflict')
        if v is not None:
            if v>=2**63:v-=2**64
            dims.append({'value':v})
        elif symbol is not None:dims.append({'symbol':symbol})
        else:dims.append({'unknown':True})
    return out|{'element_type':one(tensor,1,0),'shape':dims,
                 'fixed_element_count':math.prod(d['value'] for d in dims) if all('value' in d and d['value']>0 for d in dims) else None}


def inspect(raw):
    f=fields(raw);graph=fields(one(f,7,2,b''))
    if not graph or one(f,1,0) is None:raise ValueError('source model graph and IRversion required')
    inputs=[value_info(v) for v in messages(graph,11)];outputs=[value_info(v) for v in messages(graph,12)]
    if not inputs or not outputs or len({v['name'] for v in inputs})!=len(inputs) or len({v['name'] for v in outputs})!=len(outputs):
        raise ValueError('complete unique model input/output census')
    initializers=[]
    for t in messages(graph,5):
        dims=[]
        for wire,value in t.get(1,[]):
            if wire==0:dims.append(value)
            elif wire==2:
                i=0
                while i<len(value):v,i=varint(value,i);dims.append(v)
            else:raise ValueError('unserved initializer dimension wire')
        initializers.append({'name':text(one(t,8,2)),'element_type':one(t,2,0),'dims':dims,
                             'external_data':pairs(t,13),'data_location':one(t,14,0,0)})
    if len({v['name'] for v in initializers})!=len(initializers):raise ValueError('unique initializer names required')
    nodes=[]
    for n in messages(graph,1):
        nodes.append({'name':text(one(n,3,2)), 'operator':text(one(n,4,2)), 'domain':text(one(n,7,2,b'')),
                      'inputs':[text(v) for w,v in n.get(1,[]) if w==2], 'outputs':[text(v) for w,v in n.get(2,[]) if w==2],
                      'attribute_count':len(n.get(5,[]))})
    return {'kind':'static-source-onnx-contract','source_sha256':hashlib.sha256(raw).hexdigest(),
            'ir_version':one(f,1,0),'opsets':[{'domain':text(one(v,1,2,b'')),'version':one(v,2,0)} for v in messages(f,8)],
            'inputs':inputs,'outputs':outputs,'metadata':pairs(f,14),'initializers':initializers,'nodes':nodes,
            'external_payload_dependencies':[t for t in initializers if t['external_data'] or t['data_location']!=0],
            'local_function_count':len(f.get(25,[])),'training_graph_count':len(f.get(20,[])),
            'native_runtime_qualified':False,'inference_executed':False,
            'scope':'Static tensor/metadata/operator/dependency census only; attributes/weights/operator semantics require the pinned native runtime. Symbolic dimensions are not silently fixed.'}


def cast(value, kind):
    if kind=='float32':
        try:value=struct.unpack('<f',struct.pack('<f',value))[0]
        except (OverflowError,struct.error):raise ValueError('source cast is unrepresentable')
    elif kind!='float64':raise ValueError('closed source scalar type required')
    if not math.isfinite(value):raise ValueError('source feature transformation nonfinite')
    return value


def prepare_features(contract, values):
    """Declared source scalar arithmetic. No object reconstruction or inference.

    binary32_each mirrors float operands/subtraction/division; binary64_then_cast
    retains double operations before the source float cast. libm log rounding and
    ORT execution require separate qualification, not inferred from these values.
    """
    features=contract['features']
    if not features or set(values)!={f['id'] for f in features} or len({f['id'] for f in features})!=len(features):
        raise ValueError('complete unique ordered feature values required')
    result=[]
    for f in features:
        if not f.get('source_expression') or f.get('operation') not in ('identity','log10','normalize','jet_log10_or_default') or f.get('cast') not in ('float32','float64') or f.get('arithmetic') not in ('binary32_each','binary64_then_cast'):
            raise ValueError('explicit source operation/expression/cast/arithmetic required')
        value=values[f['id']]
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite supplied source-feature scalar required')
        if f['operation']=='log10':
            if value<=0:raise ValueError('positive source log10 operand required')
            value=math.log10(value)
        elif f['operation']=='jet_log10_or_default':
            if value<0:raise ValueError('nonnegative selected leading jet pt or0absence required')
            value=math.log10(value) if value>10.0 else 1.0
        elif f['operation']=='normalize':
            offset,scale=f['offset'],f['scale']
            if type(offset) not in (int,float) or type(scale) not in (int,float) or not math.isfinite(offset) or not math.isfinite(scale) or scale==0:
                raise ValueError('finite nonzero source normalization scale required')
            if f['arithmetic']=='binary32_each':
                value=cast(value,'float32');offset=cast(offset,'float32');scale=cast(scale,'float32')
                if scale==0:raise ValueError('nonzero scale lost in source cast')
                value=cast(value-offset,'float32')/scale
            else:value=(value-offset)/scale
        result.append(cast(value,f['cast']))
    return {'values':result,'feature_ids':[f['id'] for f in features],
            'interpretation':'Declared source-feature scalar arithmetic; event reconstruction/libm/native inference unqualified.'}


def admit(contract, values, *, expected_contract_sha256, preprocess=True):
    """Rebind reviewed literal source excerpts and model bytes; return features."""
    if contract.get('kind')!='source-classifier-feature-contract/v2':raise ValueError('closed contract required')
    import json
    declaration_digest=hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if declaration_digest!=expected_contract_sha256:raise ValueError('reviewed declaration digest mismatch')
    raw={}
    for name in ('model','source'):
        p=contract[name];data=bounded_read(Path(p['path']),limit=LIMIT)
        if hashlib.sha256(data).hexdigest()!=p['sha256']:raise ValueError('source/model digest mismatch')
        raw[name]=data
    for excerpt in contract['source_excerpts']:
        if excerpt['file']!=contract['source']:raise ValueError('literal source excerpt binding required')
        a,b=excerpt['start'],excerpt['end']
        if type(a) is not int or type(b) is not int or not 1<=a<=b:raise ValueError('source range required')
        if '\n'.join(raw['source'].decode().splitlines()[a-1:b])!=excerpt['text']:raise ValueError('source excerpt mismatch')
    model=inspect(raw['model'])
    if model!=contract['model_static']:raise ValueError('complete static model census changed')
    if model['external_payload_dependencies'] or model['local_function_count'] or model['training_graph_count']:
        raise ValueError('external/functions/training closure unserved')
    output=output_contract(contract,model)
    if not preprocess:
        if values:raise ValueError('static census cannot claim prepared feature values')
        return {'model_static':model,'source':contract['source'],'model':contract['model'],'source_output_operation':output,'runtime_obligations':contract['runtime_obligations'],'routing':contract['routing'],'source_bound':True,'source_interpretation_independently_qualified':False,'native_runtime_qualified':False,'inference_executed':False,'symbolic_batch_resolved':False}
    inputs=model['inputs']
    if len(inputs)!=1 or inputs[0].get('element_type') not in (1,11) or len(inputs[0]['shape'])!=2 or inputs[0]['shape'][1]!={'value':len(contract['features'])}:
        raise ValueError('declared scalar feature/input basis mismatch')
    expected='float32' if inputs[0]['element_type']==1 else 'float64'
    if any(f['cast']!=expected for f in contract['features']):raise ValueError('source input/model tensor type mismatch')
    result=prepare_features(contract,values)
    return result|{'source':contract['source'],'model':contract['model'],'model_input':inputs[0],
                  'model_static':model,'source_output_operation':output,'routing':contract['routing'],'runtime_obligations':contract['runtime_obligations'],
                  'source_bound':True,'source_interpretation_independently_qualified':False,
                  'native_runtime_qualified':False,'inference_executed':False,'symbolic_batch_resolved':False}

def bounded_read(path, limit=LIMIT):
    path=Path(path)
    if not path.is_file() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('ordinary bounded supplied resource required')
    def identity(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
    before=path.stat(follow_symlinks=False)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        selected=os.fstat(stream.fileno())
        if not stat.S_ISREG(selected.st_mode) or identity(before)!=identity(selected) or selected.st_size>limit:
            raise ValueError('stable bounded regular descriptor required')
        raw=stream.read(limit+1)
        if len(raw)>limit or len(raw)!=selected.st_size or not path.is_file() or any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('bounded complete ending nonlinked source required')
        if identity(os.fstat(stream.fileno()))!=identity(selected) or identity(path.stat(follow_symlinks=False))!=identity(selected):
            raise ValueError('resource changed during read')
    return raw


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def output_contract(contract,model):
    """Check a declared output interpretation; never synthesize model scores."""
    outputs=model['outputs'];op=contract['source_output_operation']
    if op is None:
        if contract['features']:raise ValueError('complete declared source output operation required')
        return None
    if len(outputs)!=1 or not outputs[0].get('tensor') or len(outputs[0]['shape'])!=2 or set(outputs[0]['shape'][1])!={'value'}:
        raise ValueError('single complete rank2 model output required for scalar interpretation')
    width=outputs[0]['shape'][1]['value']
    if type(width) is not int or width<=0 or type(op) is not dict or type(op.get('complete_model_output_width')) is not int or op['complete_model_output_width']!=width:
        raise ValueError('exact full model output width required')
    kind=op.get('kind')
    def index(name):
        v=op.get(name)
        if type(v) is not int or not 0<=v<width:raise ValueError('literal in-range output index required')
        return v
    if kind=='scalar_index':
        if set(op)!={'kind','index','complete_model_output_width','unused_output_indices','downstream_categorical_lowering','source_fill_weight'}:raise ValueError('closed scalar output declaration')
        used={index('index')}
        if not all(type(op[k]) is str and op[k] for k in ('downstream_categorical_lowering','source_fill_weight')):raise ValueError('explicit downstream/weight obligations required')
    elif kind=='difference':
        if set(op)!={'kind','positive_index','negative_index','complete_model_output_width','unused_output_indices'}:raise ValueError('closed difference output declaration')
        used={index('positive_index'),index('negative_index')}
        if len(used)!=2:raise ValueError('distinct source difference indices required')
    elif kind=='strict_score_threshold':
        if set(op)!={'kind','index','complete_model_output_width','nn_enabled_required','threshold'}:raise ValueError('closed threshold output declaration')
        used={index('index')}
        if op['nn_enabled_required'] is not True or type(op['threshold']) not in (float,int) or not math.isfinite(op['threshold']):raise ValueError('explicit finite threshold and enabled-network condition required')
    else:raise ValueError('unserved output interpretation')
    if 'unused_output_indices' in op and op['unused_output_indices']!=[i for i in range(width) if i not in used]:raise ValueError('complete used/unused output census required')
    return dict(op)


def validate(task):
    if type(task) is not dict or set(task)!={'schema_version','operation','input','input_sha256'} or type(task['schema_version']) is not int or task['schema_version']!=1:
        raise ValueError('closed classifier-input task/v1 required')
    if task['operation'] not in ('static-census','prepare-features') or type(task['input']) is not str or not task['input']:
        raise ValueError('closed classifier operation and input path required')
    if type(task['input_sha256']) is not str or len(task['input_sha256'])!=64 or any(v not in '0123456789abcdef' for v in task['input_sha256']):raise ValueError('literal input file SHA256 required')
    return dict(task)


def _input(task,base):
    from ravel.workflow.science import regular
    import copy
    task=validate(task);p=regular(task['input'],base);raw=bounded_read(p)
    if hashlib.sha256(raw).hexdigest()!=task['input_sha256']:raise ValueError('classifier input file digest mismatch')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate classifier JSON key')
            d[k]=v
        return d
    doc=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite classifier JSON')))
    if type(doc) is not dict or set(doc)!={'kind','contract','values'} or doc['kind']!='source-classifier-input/v1' or type(doc['values']) is not dict:raise ValueError('closed source classifier input required')
    c=doc['contract'];required={'kind','routine','model','source','model_static','source_excerpts','features','feature_preprocessing_state','routing','runtime_obligations','source_output_operation','event_reconstruction_qualified','native_runtime_qualified','source_arithmetic_not_native_bitwise_equivalence'}
    if type(c) is not dict or set(c)!=required or c['event_reconstruction_qualified'] is not False or c['native_runtime_qualified'] is not False or c['source_arithmetic_not_native_bitwise_equivalence'] is not True:
        raise ValueError('complete classifier declaration with unqualified native boundary required')
    if type(c['routine']) is not str or not c['routine'] or type(c['runtime_obligations']) is not list or not c['runtime_obligations'] or any(type(v) is not str or not v for v in c['runtime_obligations']):raise ValueError('explicit routine/runtime obligations required')
    resolved=copy.deepcopy(doc);pins={}
    def walk(v):
        if isinstance(v,dict):
            if 'path' in v and 'sha256' in v:
                if type(v['sha256']) is not str:raise ValueError('literal source hash required')
                q=regular(v['path'],p.parent);data=bounded_read(q)
                if hashlib.sha256(data).hexdigest()!=v['sha256']:raise ValueError('nested classifier source digest mismatch')
                if q in pins and pins[q]!=v['sha256']:raise ValueError('conflicting nested source hash')
                pins[q]=v['sha256'];v['path']=str(q)
            for x in v.values():walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    walk(resolved)
    if p in pins or not 2<=len(pins)<=32:raise ValueError('complete bounded distinct source/model graph required')
    result=admit(resolved['contract'],resolved['values'],expected_contract_sha256=digest(resolved['contract']),preprocess=task['operation']=='prepare-features')
    return p,doc,resolved,list(pins),result


def inputs(task,base):
    p,doc,resolved,pins,result=_input(task,base)
    return [p,*pins]


def run(task,base,out):
    from ravel.workflow.state_io import atomic_json
    p,doc,resolved,pins,result=_input(task,base)
    result.update(kind='source-classifier-input-delivery',status='passed',physics_validated=False,
        status_scope='Source-bound static census and declared scalar preparation only',
        operation=task['operation'],input={'path':str(p),'sha256':task['input_sha256']},
        original_declared_contract_sha256=digest(doc['contract']),resolved_contract_sha256=digest(resolved['contract']),
        schema_field_mapping_reference={'url':'https://raw.githubusercontent.com/onnx/onnx/main/onnx/onnx.proto','sha256':'795fcd38a3267a6c085190e90bd71c799a98bbba35c6a23f19c8bc672b62ed92','scope':'Field-number interpretation in this parser; not a runtime or ONNX checker'},
        batch_resolution='Native runtime binding required; unknown and symbolic dimensions retained literally',
        statistical_inference=None,model_scores=None,objects_reconstructed=False)
    out=Path(out)
    if out.exists() or out.is_symlink() or any(q.is_symlink() for q in out.parents):raise ValueError('fresh unlinked classifier output required')
    out.mkdir(parents=True,exist_ok=False);atomic_json(out/'classifier-inputs.json',result)
    return result


def write_report(result,out):
    from ravel.workflow.state_io import atomic_json
    if result.get('kind')!='source-classifier-input-delivery' or result.get('physics_validated') is not False or result.get('inference_executed') is not False:raise ValueError('literal classifier input delivery required')
    out=Path(out);atomic_json(out/'classifier-input-report.json',result)
    rows=[]
    for group in ('inputs','outputs'):
        for t in result['model_static'][group]:
            cells=(group,t['name'],t.get('element_type'),json.dumps(t.get('shape'),sort_keys=True))
            rows.append('| '+' | '.join(str(x).replace('|','\\|') for x in cells)+' |')
    (out/'classifier-input-report.md').write_text('# Source classifier inputs\n\n| Tensor | Name | Native element type | Literal dimensions |\n|---|---|---|---|\n'+'\n'.join(rows)+'\n\nDeclared source output operation: `'+json.dumps(result['source_output_operation'],sort_keys=True)+'`\n\nSupplied feature scalars, full model census, routing and runtime obligations are retained in JSON. No scores, reconstructed event objects, resolved symbolic batch, native inference or physics validation are supplied.\n')
    return [{'stem':'classifier-input-report','files':['classifier-input-report.json','classifier-input-report.md'],'normalization':'Declared feature arithmetic and literal tensor/output interpretation without inference'}]
