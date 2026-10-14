"""Construct complete source-bound SMEFT scan inputs without running MadGraph.

Port the released SFitterAgents defensive-zeroing procedure: enumerate the
actual restriction card's DIM6* entries, zero all, then activate only supplied
scan coordinates. Generated-source/coupling cleanliness remains unobserved.
"""
import hashlib
from fractions import Fraction
import json
from pathlib import Path
import re

from ravel.physics.ma5_saf import Capture
from ravel.physics.model_inputs import _fraction
from . import sfitter_workflow as workflow, agent_graph
from .state_io import atomic_json

MARKER = '{{SFITTER_DIM6_SETTINGS}}'


def _decimal(value):
    if type(value) is not str or len(value)>128:
        raise ValueError('literal bounded finite SLHA scan value required')
    match=re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd]([+-]?[0-9]+))?',value)
    if match is None or (match.group(1) is not None and abs(int(match.group(1)))>100):
        raise ValueError('bounded decimal exponent required')
    result = _fraction(value, 'Wilson coordinate')
    if abs(result)>10**100 or (result and abs(result)<Fraction(1,10**100)):
        raise ValueError('explicit bounded scan coordinate required')
    return value.replace('D','e').replace('d','e')


def restriction_census(raw):
    """Parse every DIM6* scalar entry from exactly these supplied SLHA bytes."""
    if type(raw) is not bytes or not 0<len(raw)<=16*1024**2:
        raise ValueError('bounded exact restriction-card bytes required')
    current=None;blocks={}
    for number,line in enumerate(raw.decode('utf-8').splitlines(),1):
        body=line.split('#',1)[0].strip()
        if not body:continue
        tokens=body.split()
        if tokens[0].upper()=='BLOCK':
            if len(tokens)<2:raise ValueError('complete SLHA block header required')
            current=tokens[1].upper() if tokens[1].upper().startswith('DIM6') else None
            if current is not None:
                if not re.fullmatch(r'DIM6[A-Z0-9_]*',current) or current in blocks:
                    raise ValueError('distinct literal model-specific DIM6 blocks required')
                if len(tokens)>2:
                    scale=''.join(tokens[2:])
                    if not scale.upper().startswith('Q='):raise ValueError('unsupported DIM6 block header')
                    _decimal(scale[2:])
                blocks[current]=[]
            continue
        if tokens[0].upper()=='DECAY':current=None;continue
        if current is None:continue
        if len(tokens)!=2 or not re.fullmatch(r'[0-9]+',tokens[0]):
            raise ValueError('only explicit scalar DIM6 block entries supported')
        if len(tokens[0])>10 or int(tokens[0])>2147483647:raise ValueError('bounded scalar DIM6 code required')
        code=int(tokens[0]);value=_decimal(tokens[1])
        if any(row['code']==code for row in blocks[current]):raise ValueError('duplicate DIM6 coordinate')
        blocks[current].append({'block':current,'code':code,'original_value':tokens[1],
                                'line':number,'zero_command':f'set param_card {current.lower()} {code} 0.0'})
    if not blocks or any(not rows for rows in blocks.values()):
        raise ValueError('complete nonempty model-specific DIM6 census required')
    return [row for rows in blocks.values() for row in rows]


def _load(request,base):
    workflow._closed(request,('schema_version','id','workflow','restriction_card','launch_template','operator_map','scans'),'scan-input request')
    if type(request['schema_version']) is not int or request['schema_version']!=1:
        raise ValueError('scan-input schema_version1 required')
    workflow.sfitter_native._text(request['id'],'scan input identity')
    capture=Capture();wp,raw=capture.pin(request['workflow'],base);wf=workflow._strict_document(raw)
    _,phase=workflow._resolve(wf,wp.parent)
    if phase not in ('sm_template','parameterization'):
        raise ValueError('current SM/template or parameterization workflow required')
    for pin in workflow.input_pins(wf,wp.parent):capture.pin(pin,wp.parent)
    for name in ('restriction_card','launch_template','operator_map'):
        capture.pin(request[name],base)
    card=workflow.custody._pin(request['restriction_card'],base)
    template=workflow.custody._pin(request['launch_template'],base)
    mapping_path=workflow.custody._pin(request['operator_map'],base)
    mapping=workflow._strict_document(capture.files[mapping_path][1])
    workflow._closed(mapping,('schema_version','model_source','eft','operators','sources'),'declared parameter/operator map')
    if (type(mapping['schema_version']) is not int or mapping['schema_version']!=1 or
        mapping['model_source']!=wf['target']['model_source'] or mapping['eft']!=wf['target']['eft']):
        raise ValueError('exact supplied model and full coefficient convention required')
    if type(mapping['sources']) is not list or not mapping['sources']:
        raise ValueError('actual operator mapping source required; no inferred model map')
    for pin in mapping['sources']:capture.pin(pin,mapping_path.parent)
    census=restriction_census(capture.files[card][1]);slots={(r['block'],r['code']) for r in census}
    basis=wf['target']['eft']['basis'];axes={}
    if type(mapping['operators']) is not list or len(mapping['operators'])!=len(basis):
        raise ValueError('whole declared operator mapping required')
    used=set()
    for wanted,row in zip(basis,mapping['operators']):
        workflow._closed(row,('axis','block','code'),'mapped Wilson coordinate')
        if row['axis']!=wanted or type(row['block']) is not str or type(row['code']) is not int:
            raise ValueError('complete ordered native-axis mapping required')
        slot=(row['block'],row['code'])
        if slot not in slots or slot in used:raise ValueError('map must select distinct actual restriction-card entries')
        used.add(slot);axes[wanted]=slot
    text=capture.files[template][1].decode('utf-8')
    lines=text.splitlines();markers=[i for i,line in enumerate(lines) if line.strip()==MARKER]
    if len(markers)!=1 or text.count(MARKER)!=1:
        raise ValueError('exact unique standalone hygiene marker required')
    launch=[i for i,line in enumerate(lines) if line.split('#',1)[0].split() and line.split('#',1)[0].split()[0].lower()=='launch']
    if len(launch)!=1 or launch[0]>=markers[0]:raise ValueError('one supplied launch before hygiene settings required')
    for line in lines:
        body=line.split('#',1)[0].strip();words=body.split()
        if words and words[0].lower()=='set' and (len(words)<3 or words[1].lower()!='run_card'):
            raise ValueError('template may only set explicit run_card fields; parameter settings come from the compiler')
    scans=request['scans']
    if type(scans) is not list or not 1<=len(scans)<=4096:raise ValueError('bounded explicit scan population required')
    names=set();results=[];zero_commands=[r['zero_command'] for r in census]
    for row in scans:
        workflow._closed(row,('id','values'),'supplied scan point')
        if type(row['id']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,47}',row['id']) or row['id'] in names:
            raise ValueError('distinct safe scan point identity required')
        names.add(row['id']);values=row['values']
        if type(values) is not dict or len(values)>2 or not set(values)<=set(axes):
            raise ValueError('explicit SM, single-operator or declared mixed-pair point required')
        if len(values)==2 and (not wf['target']['eft']['quadratic'] or
            sorted(values) not in [sorted(p) for p in wf['target']['eft']['mixed_pairs']]):
            raise ValueError('mixed scan must belong to declared full EFT population')
        active=[]
        for axis in basis:
            if axis in values:
                block,code=axes[axis];value=_decimal(values[axis])
                active.append(f'set param_card {block.lower()} {code} {value}')
        generated=text.replace(MARKER,'\n'.join([*zero_commands,*active]))
        results.append({'id':row['id'],'values':values,'active_commands':active,'script':generated,
            'script_sha256':hashlib.sha256(generated.encode('utf-8')).hexdigest()})
    capture.finish()
    return capture,wf,census,axes,results


def input_pins(request,base):
    capture,*_=_load(request,base)
    return [{'path':str(p),'sha256':hashlib.sha256(v[1]).hexdigest()} for p,v in sorted(capture.files.items())]


def compile(request,base):
    capture,wf,census,axes,results=_load(request,base)
    result={'schema_version':1,'kind':'sfitter_scan_inputs','workflow':request['workflow'],
        'model_source':wf['target']['model_source'],'eft':wf['target']['eft'],
        'restriction_card':request['restriction_card'],'launch_template':request['launch_template'],
        'operator_map':request['operator_map'],'dim6_census':census,
        'zeroing_commands':[r['zero_command'] for r in census],'scans':results,
        'generated_coupling_cleanliness':'unobserved','native_parameter_consumption':'unobserved',
        'mapping_semantics':'source-supplied premise, not independent model translation',
        'execution_authorized':False,'physics_validated':False}
    capture.finish();return result


def materialize(request_pin,base,output):
    capture=Capture();rp,raw=capture.pin(request_pin,base);request=workflow._strict_document(raw)
    original,_,_,_,_=_load(request,rp.parent)
    out=Path(output).absolute()
    if ('..' in out.parts or out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents)
        or any(out.is_relative_to(p.parent) for p in [rp,*original.files])):
        raise ValueError('fresh scan output must preserve original source/input directories')
    result=compile(request,rp.parent)
    if result['scans']!=_load(request,rp.parent)[4]:raise ValueError('scan inputs changed during compilation')
    original.finish();capture.finish();out.mkdir(parents=True)
    outputs=Capture()
    for row in result['scans']:
        path=out/(row['id']+'.mg5');path.write_bytes(row['script'].encode('utf-8'))
        outputs.read(path,out,row['script_sha256'])
    raw=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode('utf-8')
    atomic_json(out/'scan-inputs.json',result);outputs.read(out/'scan-inputs.json',out,hashlib.sha256(raw).hexdigest())
    expected={row['id']+'.mg5' for row in result['scans']}|{'scan-inputs.json'}
    members=list(out.rglob('*'))
    if {p.relative_to(out).as_posix() for p in members}!=expected:
        raise ValueError('ending generated scan member census changed')
    for p in members:outputs.ordinary(p)
    original.finish();capture.finish();outputs.finish()
    return {'path':str(out/'scan-inputs.json'),'sha256':hashlib.sha256(raw).hexdigest()}


def graph(request,base,request_pin):
    pins=[request_pin,*input_pins(request,base)]
    if len(pins)>128:raise ValueError('whole scan source population exceeds Graph input bound')
    return agent_graph.validate({'schema_version':1,'graph_id':request['id']+'_scan_inputs',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':60,'max_reworks':0},
        'nodes':[{'id':'scan_inputs','kind':'tool','role':'designer','depends_on':[],
          'inputs':[{'id':'request' if i==0 else 'source'+str(i),**pin} for i,pin in enumerate(pins)],
          'packet':None,'action':'sfitter-scan-inputs','parameters':{'request_input':'request'},'max_attempts':1}]})


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request',required=True);p.add_argument('--output',required=True)
    p.add_argument('--graph',action='store_true');a=p.parse_args(argv)
    rp=workflow._pin(workflow.custody._regular(a.request,Path.cwd()))
    if a.graph:
        capture=Capture();path,raw=capture.pin(rp,Path.cwd())
        request=workflow._strict_document(raw);original,*_=_load(request,path.parent)
        out=Path(a.output).absolute()
        if ('..' in out.parts or out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents)
            or any(out.is_relative_to(p.parent) for p in [path,*original.files])):
            raise ValueError('fresh graph destination must preserve original inputs')
        result=graph(request,path.parent,rp);original.finish();capture.finish()
        written=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode('utf-8')
        atomic_json(out,result);ending=Capture();ending.read(out,out.parent,hashlib.sha256(written).hexdigest())
        original.finish();capture.finish();ending.finish()
    else:materialize(rp,Path.cwd(),a.output)
    return 0


if __name__=='__main__':raise SystemExit(main())
