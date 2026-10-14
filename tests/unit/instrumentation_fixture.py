"""Fictional instrumentation packages and complete native observations."""
import copy,hashlib,json
from pathlib import Path
from test_classifier_inputs import setup,pin
from ravel.physics import analysis_response_features as ar,hhh_response as response

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def path(*keys):return {'path':list(keys)}
def op(name,*args):return {'op':name,'args':list(args)}

def assets(root,identity='ANA_0001',models=1):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);_,base,_=setup(root)
    source=Path(base['source']['path']);base['routine']=identity
    contracts={f'model{i}':copy.deepcopy(base) for i in range(models)}
    cp=root/'contracts.json';cp.write_text(json.dumps(contracts))
    original=source.read_text();replacement=original+'// fictional observation hook\n'
    phases=[{'phase':'identity','min':1,'max':1},{'phase':'features','min':1,'max':1}]
    classifiers=[]
    for i in range(models):
        phases += [{'phase':'input'+str(i),'min':1,'max':1},{'phase':'output'+str(i),'min':1,'max':1}]
        classifiers.append({'id':'model'+str(i),'contract':'model'+str(i),'select':True,'features_phase':'features','input_phase':'input'+str(i),'output_phase':'output'+str(i)})
    allocations=[op('sub',path('outputs','model'+str(i),1),path('outputs','model'+str(i),0)) for i in range(models)]+[1]
    manifest={'schema_version':1,'prefix':'SYNTHETIC_TRACE ','header':{'schema':1,'analysis':identity,'source_sha256':sha(source)},'event_paths':[{'id':'selected','phases':phases,'checks':[op('eq',op('len',path('phases','features',0)),2)],'allocation':allocations}],'classifiers':classifiers,'destinations':[identity+'/category'+str(i) for i in range(models)]+[identity+'/all'],'normalization_phase':'normalization','identity_phase':'identity'}
    descriptor={'schema_version':1,'routine':identity,'instrumented_routine':identity+'_TRACE','instrumentation':{'schema_version':1,'source_sha256':sha(source),'edits':[{'old':original,'new':replacement,'count':1}]},'trace':manifest,'models':{k:{'filename':k+'.onnx','contract':k} for k in contracts},'final_histograms':['/'+identity+'_TRACE/q'+str(i) for i in range(models)],'build':{'compile_unit':'observer.cc','output':'observer.so','flags':['-std=c++17']},'runtime_version':'4.1.4','analysis_options':{},'normalization_scale':7.,'beam_pdg':[2212,2212],'beam_energy_gev':[6500,6500],'limitations':['Fictional observation semantics only.'],'coordinate_fields':{'coordinate':['seed']},'study':{'study_id':identity,'parameter_grid':[{'coordinate':i} for i in range(models)],'datasets':['DATA-'+str(i) for i in range(models)],'output':{'stem':'analysis-response-report','formats':['json','markdown']}}}
    dp=root/'instrumentation.json';dp.write_text(json.dumps(descriptor))
    info=root/'source.info';info.write_text('Name: '+identity+'\nStatus: VALIDATED\n');ref=root/'reference.yoda';ref.write_text('Fictional reference bytes only.\n')
    d={'schema_version':1,'instrumentation':pin(dp),'source':pin(source),'info':pin(info),'reference':pin(ref),'models':{k:dict(v['model']) for k,v in contracts.items()},'contracts':pin(cp),'dependencies':[]}
    p=root/'prepare-input.json';p.write_text(json.dumps(d));return root

def contracts(root):return json.loads((Path(root)/'contracts.json').read_text())
def descriptor(root):return json.loads((Path(root)/'instrumentation.json').read_text())

def census(count=3):
    out=[]
    for i in range(count):
        weight=2. if i%3==0 else -1. if i%3==1 else 0.
        identity={'event_number':i+1,'raw_weight_names':['nominal'],'raw_weights':[weight],'selected_weight_names':[''],'selected_weights':[weight]}
        out.append({'event_id':str(i),'group_id':str(i//2),'weights':{'nominal':weight},'native_identity':identity})
    return out

def log(events,manifest):
    records=[{'event':0,'phase':'header','data':manifest['header']}]
    for i,e in enumerate(events,1):
        records += [{'event':i,'phase':'identity','data':e['native_identity']},{'event':i,'phase':'features','data':{'x':1.25,'y':2.75}}]
        for c in manifest['classifiers']:
            records += [{'event':i,'phase':c['input_phase'],'data':[1.25,2.75]},{'event':i,'phase':c['output_phase'],'data':[.125,.625,.875]}]
    W=sum(e['weights']['nominal'] for e in events)
    records.append({'event':len(events),'phase':manifest['normalization_phase'],'data':{'events':len(events),'weight_index':0,'weight_name':'','sumW':W,'cross_section_pb':1.,'scale_factor':7./W}})
    return ''.join(manifest['prefix']+json.dumps(dict(seq=i+1,**r))+'\n' for i,r in enumerate(records)).encode()
