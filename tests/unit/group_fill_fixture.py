"""Independent fictional repeated-fill and RAW primitive construction."""
import copy,gzip,json
from pathlib import Path
from test_native_group_fills import pin,block
from ravel.physics import native_group_fills as n

def supplied(root,identity,weights,edges,sites,formats):
    root=Path(root);root.mkdir();source=root/'source.cc';source.write_text('\n'.join('fill'+str(i)+'();' for i in range(sites)))
    ref=root/'reference.gz';ref.write_bytes(gzip.compress(''.join(block('ESTIMATE1D',f'/REF/{identity}/q{i}','Edges(A1): '+json.dumps(edges)+'\n---') for i in range(sites)).encode()))
    outputs=[{'id':'quantity'+str(i),'site':i,'path':f'/{identity}/q{i}','edges':edges,'axis_unit':'1','unit':'1','source_fill_weight':1,'source_fill_fraction':1,'reference_path':f'/{identity}/q{i}'} for i in range(sites)]
    inputs=[];events=[];traces=[]
    for i,w in enumerate(weights):
        event=root/('events'+str(i));event.write_text('Fictional event population '+str(i));inputs.append(pin(event))
        e={'input_sha256':pin(event)['sha256'],'encounter_ordinal':0,'event_number':i+10,'selected_weights':[w]};events.append(e)
        fills=[{'site':j,'coordinates':[edges[0]+(edges[1]-edges[0])/2]} for j in range(sites) for k in range(2 if i==0 else 1)]
        traces.append({'schema':'ravel-native-fills/v1','routine':identity,'original_source_sha256':pin(source)['sha256'],'ordinal':i,'event_number':i+10,'pid':42,'unwinding':False,'native_weight_names':[''],'weights':[w],'fills':fills})
    trace=root/'trace.jsonl';trace.write_text('\n'.join(json.dumps(t) for t in traces)+'\n');text=''
    for o in outputs:
        x=(edges[0]+edges[1])/2;values=[]
        for bi in range(len(edges)+1):
            terms=[(w,x) for i,w in enumerate(weights) for k in range(2 if i==0 else 1)] if bi==1 else []
            cells=[sum(w for w,x in terms),sum(w*w for w,x in terms),sum(w*x for w,x in terms),sum(w*x*x for w,x in terms),len(terms)]
            values.append(' '.join(format(v,'.17e') for v in cells))
        text+=block('HISTO1D','/RAW'+o['path'],'Edges(A1): '+json.dumps(edges)+'\n---\n# sumW sumW2 sumW(A1) sumW2(A1) numEntries\n'+'\n'.join(values))
    text+=block('COUNTER','/RAW/_EVTCOUNT','---\n# sumW sumW2 numEntries\n'+' '.join(format(v,'.17e') for v in (sum(weights),sum(w*w for w in weights),len(weights))))
    raw=root/'native.yoda';raw.write_text(text);inventory=n.native_inventory(text)
    schema={'schema_version':1,'routine':identity,'native_analysis_alias':identity,'source':pin(source),'sources':[],'sites':[{'id':i,'arity':1,'anchor':'fill'+str(i)+'();','count':1,'max_per_event':2} for i in range(sites)],'outputs':copy.deepcopy(outputs),'rules':[],'native_object_paths':[r['path'] for r in inventory],'study':{'study_id':identity,'parameter_grid':[{'coordinate':v} for v in edges],'datasets':[p['path'] for p in inputs],'output':{'stem':identity+'-table','formats':formats}}}
    c={'schema_version':2,'routine':identity,'native_analysis_alias':identity,'original_source_sha256':pin(source)['sha256'],'group_rule':'independent_single_subevent','native_weight_cap':0,'same_process_pid':42,'events':events,'weight_mapping':[{'id':'nominal','native':'','raw_suffix':''}],'outputs':outputs,'reference':pin(ref),'native_object_inventory':inventory,'fill_schema':schema}
    return c,trace,raw
