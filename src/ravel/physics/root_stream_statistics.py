"""Authenticated stream moments -> existing CR and expected SR/CR constructions.

The caller supplies both complete laws, roles, transfer/response assumptions and
native runtime/fit contracts. No background transfer, sampling auxiliary,
uncertainty Gaussianization, observed SR, fit or sensitivity value is invented.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from ravel.physics import root_stream as stream, root_stream_core as core
from ravel.physics import statistical_construction as regional


def _quantity(delivery,sample,quantity):
    s=next((x for x in delivery['samples'] if x['id']==sample),None)
    core.require(s is not None and quantity in s['quantities'],'actual complete sample/quantity binding required')
    return s,s['quantities'][quantity]


def _counts(q,ids):
    c=q['contract'];core.require(c['representation']=='integrated' and c['normalization']['scale']==1.0,'unweighted integrated physical event counts required')
    allids=[b['id'] for b in c['bins']];core.require(len(set(ids))==len(ids) and set(ids)<=set(allids),'unique original count bin support required')
    indices=[allids.index(x) for x in ids];cov=q['covariance'];values=q['values']['nominal']
    result=[]
    for i in indices:
        n=values[i];core.require(type(n) in (int,float) and n>=0 and n==int(n) and cov[i][i]==n,'multifill/weighted/noninteger observations cannot become Poisson counts')
        core.require(all(cov[i][j]==0 for j in indices if i!=j),'same-event overlapping counts cannot become independent Poissons')
        result.append(int(n))
    return result


def project(delivery,design,roles):
    """Pure projection with independent-source law and all moments retained."""
    core.keys(design,('schema_version','background','expected_sensitivity','term_bindings','control_counts','validation','region_roles','statement','native_bundle'),'complete scientific design')
    core.require(type(design['schema_version']) is int and design['schema_version']==1,'statistical handoff schema1 required');core.text(design['statement'])
    core.keys(roles,('schema_version','quantity','bins','statement'),'original region roles');core.require(type(roles['schema_version']) is int and roles['schema_version']==1,'roles schema1 required')
    rolemap={}
    for row in roles['bins']:
        core.keys(row,('id','role'),'original region');core.text(row['id']);core.require(row['id'] not in rolemap and row['role'] in ('signal_region','control_region','validation_region'),'unique original role support required');rolemap[row['id']]=row['role']
    docs={k:deepcopy(design[k]) for k in ('background','expected_sensitivity')}
    core.require(all(b['role']=='control_region' for b in docs['background']['bins']),'blinded background fit may contain only actual control bins, not VR/SR')
    expected=docs['expected_sensitivity'];core.require(expected.get('expected_data',{}).get('conditioning')=='supplied_nominal' and all(b['observed'] is None for b in expected['bins']),'expected sensitivity requires null observations, never zero-masked SR data')
    core.require(set(b['role'] for b in expected['bins'])<= {'signal_region','control_region'},'VR must remain unfit held-out')
    bindings=design['term_bindings'];core.require(type(bindings) is list and bindings,'complete term bindings required');seen=set()
    for row in bindings:
        core.keys(row,('model','term','sample','quantity','bin_ids'),'all-region template binding')
        core.require(row['model'] in docs and (row['model'],row['term']) not in seen,'unique actual mean term mapping required');seen.add((row['model'],row['term']))
        doc=docs[row['model']];term=next((t for t in doc['terms'] if t['id']==row['term']),None);core.require(term is not None,'actual source mean term required')
        s,q=_quantity(delivery,row['sample'],row['quantity']);core.require(s['kind']!='data' and q['contract']['representation']=='integrated','MC expected-event integral required')
        core.require((term['basis']=='bsm' and s['kind']=='signal_mc') or (term['basis'] in ('background','sm') and s['kind']=='background_mc'),'explicit background/signal physical basis must match sample')
        binids=[b['id'] for b in q['contract']['bins']];core.require(type(row['bin_ids']) is list and len(row['bin_ids'])==len(doc['bins']) and len(set(row['bin_ids']))==len(row['bin_ids']) and set(row['bin_ids'])<=set(binids),'complete all-region source bin mapping, including control signal, required')
        core.require(row['quantity']==roles['quantity'] and all(rolemap.get(x)==b['role'] for x,b in zip(row['bin_ids'],doc['bins'])),'source region roles cannot be relabelled')
        term['coefficients']=[str(Fraction(q['values']['nominal'][binids.index(x)])) for x in row['bin_ids']]
        term['source']='stream_delivery'
    core.require(seen=={(k,t['id']) for k,d in docs.items() for t in d['terms']},'every complete mean term must use a declared source table; no omitted contribution')
    obs=design['control_counts'];core.keys(obs,('sample','quantity','bin_ids'),'original observed CR count mapping')
    sample,q=_quantity(delivery,obs['sample'],obs['quantity']);core.require(sample['kind']=='data' and obs['quantity']==roles['quantity'] and all(rolemap.get(x)=='control_region' for x in obs['bin_ids']),'only actual blinded CR data may enter observed construction')
    core.require(len(obs['bin_ids'])==len(docs['background']['bins']),'all original background CR observations required')
    for b,n in zip(docs['background']['bins'],_counts(q,obs['bin_ids'])):b['observed']=n;b['source']='stream_delivery'
    validation=design['validation'];core.keys(validation,('sample','quantity','bin_ids'),'held-out VR mapping')
    vs,vq=_quantity(delivery,validation['sample'],validation['quantity']);core.require(vs['kind']=='data' and validation['quantity']==roles['quantity'] and all(rolemap.get(x)=='validation_region' for x in validation['bin_ids']),'validation rows remain explicitly held out')
    core.require(not set(validation['bin_ids'])&set(obs['bin_ids']),'VR cannot be re-used as fitted CR')
    held={'bin_ids':deepcopy(validation['bin_ids']),'counts':_counts(vq,validation['bin_ids']),'fit_executed':False,'held_out':True}
    # Data covariance proves count support only within this one quantity/sample.
    core.require((validation['sample'],validation['quantity'])==(obs['sample'],obs['quantity']),'one joint data support required to preserve CR/VR overlap evidence')
    _counts(q,[*obs['bin_ids'],*validation['bin_ids']])
    return docs,held


def materialize(request,base,output):
    core.keys(request,('schema_version','stream_task','stream_result','stream_closure','design'),'statistical handoff request')
    core.require(type(request['schema_version']) is int and request['schema_version']==1,'source handoff schema1 required')
    capture=core.Capture();task=capture.document(request['stream_task'],base)
    p,c,ds,a=stream._load(task,base,capture)
    result_path,raw=capture.read(request['stream_result'],base,max(8*1024**2,request['stream_result']['size']))
    core.require(result_path.name=='root-stream-result.json','canonical stream result required')
    value=core.strict(raw);result={**value,'commitment':request['stream_closure']}
    guard=stream.guard(result,result_path.parent)
    receipt=stream.ordinary_stream_delivery(result,result_path.parent,task)
    core.require(value['status']=='passed','failed/partial stream cannot become a statistical table')
    original_native,original_request=stream.private_delivery(guard)
    core.require(original_native['delivery']['kind']=='root-stream-moments','incomplete raw partition is not a complete statistical study')
    core.require(original_request['dataset']==ds and original_request['analysis']==a,'original stream source/domain differs')
    core.require(value['delivery']==stream.public_delivery(original_native,ds,a,original_request['config']),'public stream projection differs')
    design=capture.document(request['design'],base);roles=capture.document(design['region_roles'],base)
    docs,held=project(original_native['delivery'],design,roles)
    allowed=set(a['blinding']['model_fields'][design['control_counts']['quantity']]) if a['blinding'] is not None else set()
    core.require(set(design['control_counts']['bin_ids'])|set(design['validation']['bin_ids'])<=allowed,'fitted/validation data support must be admitted by original blind policy')
    out=Path(output).absolute();core.require(not out.exists(),'fresh statistical handoff required');stream.custody._ordinary(out.parent,base,directory=True);out.mkdir()
    intended=[];handoffs={}
    for name,doc in docs.items():
        core.require(not any(x['id'] in ('stream_delivery','stream_design','stream_roles') for x in doc['sources']),'source IDs reserved for exact stream join')
        for identity,declaration in (('stream_delivery',request['stream_result']),('stream_design',request['design']),('stream_roles',design['region_roles'])):
            sourcepath,_=capture.read(declaration,base,max(8*1024**2,declaration['size']))
            doc['sources'].append({'id':identity,'path':str(sourcepath),'sha256':declaration['sha256']})
        for row in doc['sources']:
            q=stream.custody._ordinary(row['path'],base);capture.read({'path':str(q),'sha256':row['sha256'],'size':q.stat().st_size},base)
        regional.validate(doc);regional.source_inputs(doc,base);regional.response(doc)
        intended.append(stream.write_new(out/(name+'.json'),doc))
        declaration=design['native_bundle']
        if declaration is None:
            handoffs[name]={'state':'blocked_missing_original_native_runtime_and_fit','construction':intended[-1],
                            'consumer':'ravel.physics.statistical_construction.write_native_bundle','execution_authorized':False}
        else:
            native=capture.document(declaration,base);core.keys(native,('runtime','background_fit','expected_sensitivity_fit','max_seconds'),'actual native consumer inputs')
            # Existing consumer owns lowering and actual runtime/fit contract.
            folder=out/(name+'-native')
            # Retain expected publication semantics BEFORE the existing writer;
            # neither its returned aliases nor first on-disk pins are authority.
            fit=deepcopy(native[name+'_fit']);construction_raw=stream.encoded(doc);card_raw=regional.datacard(doc)
            construction_path=folder/'construction.json';card_path=folder/'model.txt'
            import hashlib
            construction_pin={'path':str(construction_path),'sha256':hashlib.sha256(construction_raw).hexdigest()}
            model={'files':[{'path':str(card_path),'sha256':hashlib.sha256(card_raw).hexdigest(),'staged_path':'model.txt'}],
                   'card':'model.txt','regions':[{'channel':b['id'],'role':b['role']} for b in doc['bins']],
                   'physics_model':None,'signal_replacement':None,'construction':construction_pin}
            expected_config={'schema_version':2 if 'saved_fit' in fit else 1,'source':doc['question'],'model':model,
                             'runtime':deepcopy(native['runtime']),'fit':fit,'max_seconds':native['max_seconds']}
            if 'expected_data' in doc:expected_config['expected_data']=deepcopy(doc['expected_data'])
            expected_handoff={'mode':'native-likelihood','task':{'input':str(folder/'native-input.json')},'construction':construction_pin,
                'source_law':regional.KIND,'build_or_fit_executed':False,'native_parity_qualified':False,
                'remaining':['ordinary source/runtime/fit admission','native full-mean, auxiliary and domain qualification','actual saved-fit/profile diagnostics','interval/calibration/applicability if requested']}
            handoff=regional.write_native_bundle(doc,folder,runtime=native['runtime'],fit=fit,max_seconds=native['max_seconds'])
            core.require(handoff==expected_handoff,'existing consumer returned a changed handoff')
            for filename,expected_raw in (('construction.json',construction_raw),('model.txt',card_raw),
                   ('native-input.json',( __import__('json').dumps(expected_config,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()),
                   ('handoff.json',( __import__('json').dumps(expected_handoff,sort_keys=True,indent=2)+'\n').encode())):
                declaration={'path':str(folder/filename),'sha256':hashlib.sha256(expected_raw).hexdigest(),'size':len(expected_raw)}
                capture.read(declaration,folder,max(8*1024**2,len(expected_raw)));intended.append(declaration)
            core.require({x.name for x in folder.iterdir()}=={'construction.json','model.txt','native-input.json','handoff.json'},'complete native bundle roster required')
            from ravel.physics import native_likelihood
            native_likelihood.inputs(handoff['task'],folder)
            handoffs[name]=deepcopy(expected_handoff)
    evidence={'schema_version':1,'kind':'root-stream-statistical-handoff','background':handoffs['background'],'expected_sensitivity':handoffs['expected_sensitivity'],
              'held_out_validation':held,'original_goal':a['original_goal'],'complete_stream_result':request['stream_result'],
              'moment_and_variation_evidence':value['delivery']['samples'],
              'fit_executed':False,'sensitivity_computed':False,'physics_validated':False,
              'limitations':['Full source-defined background and expected-sensitivity laws are supplied, not inferred from tables.',
                              'Signed MC moments/variation covariance are retained; no Poisson MC auxiliary or Gaussian nuisance law is fabricated.',
                              'VR remains held out; SR observed data is never supplied or replaced with masked zero.']}
    intended.append(stream.write_new(out/'handoff.json',evidence));original_members=stream.census(out);capture.finish();guard.finish(result)
    core.require(stream.census(out)==original_members,'ending complete statistical handoff membership differs')
    stream.custody.asset_check({x['path']:x for x in intended})
    core.require(stream.ordinary_stream_delivery(result,result_path.parent,task)==receipt,'ending original ordinary stream delivery differs')
    guard.finish(result);capture.finish()
    stream.custody.asset_check({x['path']:x for x in intended})
    return evidence
