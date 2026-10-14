"""Pure synthetic source population; no ROOT/data/site/native operation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from ravel.physics import root_stream_core as c


def pin(p):
    p=Path(p);raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def put(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode() if not isinstance(value,bytes) else value)
    return pin(p)


def quantity():
    return {'schema_version':1,'axes':[{'name':'region_index','unit':'1'}],
        'bins':[{'id':n,'low':[i],'high':[i+1]} for i,n in enumerate(('CR','VR','SR'))],
        'weight_names':['nominal','up'],'input_weight_unit':'1','representation':'integrated',
        'normalization':{'kind':'absolute','scale':1.0,'unit':'events'}}


def population(root):
    proof=put(root,'proof.json',{'source':'synthetic software fixture only'})
    samples=[]
    for identity,kind,dsid,sumw,xsec,entries in (('background','background_mc',101,10,2,5),('signal','signal_mc',102,4,1,3),('data','data',None,None,None,4)):
        norm=None
        member={'id':identity+'_file','did':'synthetic:'+identity,'guid':'guid-'+identity,
                'uri':'file://'+str(root/(identity+'.root')),'tree':'mini','entries':entries,
                'size_bytes':1,'checksum':{'algorithm':'sha256','value':hashlib.sha256(b'x').hexdigest(),'authority':proof}}
        (root/(identity+'.root')).write_bytes(b'x')
        if kind!='data':
            original=put(root,identity+'-original.json',{'schema_version':1,'sample_id':identity,'dsid':dsid,'members':[{k:member[k] for k in ('guid','did','entries')}]})
            normal={'sum_weights':sumw,'luminosity_fb_inverse':1,'cross_section_pb':xsec,'filter_efficiency':1,'k_factor':1}
            source=put(root,identity+'-normal.json',{'schema_version':1,'sample_id':identity,'dsid':dsid,'original_population_sha256':original['sha256'],**normal})
            norm={'source':source,'original_population':original,**normal}
        samples.append({'id':identity,'kind':kind,'dsid':dsid,'process':'synthetic-'+identity,'normalization':norm,'members':[member]})
    authority=put(root,'members.json',{'schema_version':1,'samples':samples})
    ds={'schema_version':1,'membership_authority':authority,'ordering':'declared_sample_member_source_entry','samples':samples}
    blind_policy=put(root,'blind-domain.json',{'schema_version':1,'kind':'root-stream-blind-domain','domain_id':'synthetic-original-domain',
        'original_goal_sha256':proof['sha256'],'allowed_regions':['CR','VR'],'model_fields':{'regions':['CR','VR']},'protected_regions':['SR'],'review_source':proof})
    analysis={'schema_version':1,'original_goal':proof,'branch_contract':[{'name':n,'shape':'scalar','dtype':'float64','unit':'1'} for n in ('w','sf','variation','x')],
        'weight_contract':{'raw_mc_weight':'w','scale_factors':['sf'],'variations':[{'name':'up','branch':'variation','semantics':'multiplicative_event_factor'}]},
        'quantities':[{'id':'regions','contract':quantity()}],
        'blinding':{'policy':'exclude_signal_regions','source':blind_policy,'blind_entry':'blind.py','allowed_regions':['CR','VR'],'model_fields':{'regions':['CR','VR']}}}
    kernel=put(root,'kernel.py',b'def analyze(table, entries, sample):\n    return [{"source_entry":int(e),"fills":{"regions":[[float(x)]]}} for e,x in zip(entries,table["x"])]\n')
    blind=put(root,'blind.py',b'def allow(table, regions):\n    import numpy as np\n    return np.asarray(table["x"] < 2,dtype=bool)\n')
    rt=root/'runtime';rt.mkdir();python=put(rt,'python',b'fake interpreter metadata, never executed\n');(rt/'python').chmod(0o755)
    manifest=put(root,'runtime.json',{'schema_version':1,'files':{'python':{k:python[k] for k in ('sha256','size')}}})
    cfg={'schema_version':1,'dataset':put(root,'dataset.json',ds),'analysis':put(root,'analysis.json',analysis),
         'bundle':{'entry':'kernel.py','blind_entry':'blind.py','files':{'kernel.py':kernel,'blind.py':blind},'review_source':proof},
         'runtime':{'python':python,'site_roots':[str(rt)],'trees':[{'root':str(rt),'manifest':manifest}],'versions':deepcopy(c.VERSIONS)},
         'site':{'id':'synthetic','rse':'synthetic','allowed_hosts':['test.invalid'],'read_timeout_seconds':5,'credential_reference':None,'durable_output_policy':'persistent_site_output'},
         'limits':{'max_seconds':20,'max_ram_mib':128,'max_output_bytes':1048576,'chunk_entries':2,'max_members':10,'max_chunks':100,'max_quantity_dimensions':64}}
    task={'config':put(root,'config.json',cfg)}
    return ds,analysis,cfg,task,proof


def event_population():
    return {'background':[(2,.5,2,[[0.5],[1.5]]),(-1,2,.5,[[2.5]]),(0,1,2,[]),(3,1,1,[[2.5],[2.5]]),(1,1,2,[[0.5]])],
            'signal':[(1,1,2,[[2.5]]),(-1,.5,1,[[0.5]]),(2,1,.5,[[2.5]])],
            'data':[(1,1,1,[[0.5]]),(1,1,1,[[1.5]]),(1,1,1,[[2.5]]),(1,1,1,[])]}


def accumulate(ds,a,limits,chunk,events=None):
    limits={**limits,'chunk_entries':chunk};acc=c.Stream(ds,a,limits);events=event_population() if events is None else events
    for sample in ds['samples']:
        rows=events[sample['id']];member=sample['members'][0]
        for start in range(0,len(rows),chunk):
            stop=min(start+chunk,len(rows));entries=[];records=[];weights=[]
            for i in range(start,stop):
                raw,sf,v,fills=rows[i]
                if sample['kind']=='data' and any(fill[0]>=2 for fill in fills):continue
                entries.append(i);records.append({'source_entry':i,'fills':{'regions':deepcopy(fills)}})
                weights.append({'w':raw,'sf':sf,'variation':v})
            acc.chunk(sample['id'],member['id'],start,stop,entries,records,weights)
    return acc.finish()
