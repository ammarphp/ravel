"""Portable replay of 295 inert guard cases; never probes the system or executes MG."""
import ast, copy, itertools, os
from pathlib import Path

OLD_BLOCK="    if any(env.get(k) not in (None, '') for k in FORBIDDEN_ENV):\n        raise ValueError('Unsupported build/import environment override')"
NEW_BLOCK="    blocked = sorted(k for k in FORBIDDEN_ENV if env.get(k) not in (None, ''))\n    if blocked:\n        raise ValueError('Unsupported build/import environment override: ' + ', '.join(blocked))"


def require(ok,message):
    if not ok:raise ValueError(message)


def check(old_source,current_source):
    """Arguments are already pinned source strings, not import paths or arbitrary recipes."""
    require(old_source.count(OLD_BLOCK)==1 and old_source.replace(OLD_BLOCK,NEW_BLOCK)==current_source,'Unexpected production source delta')
    trees=[ast.parse(text) for text in (old_source,current_source)]
    functions=[{n.name:ast.dump(n,include_attributes=False) for n in t.body if isinstance(n,ast.FunctionDef)} for t in trees]
    require(set(functions[0])==set(functions[1]),'Function population changed')
    require([n for n in functions[0] if functions[0][n]!=functions[1][n]]==['generation_decision'],'Other function changed')
    class ReachedPath(Exception):pass
    def stop_path(*args,**kwargs):raise ReachedPath()
    def stop_probe(*args,**kwargs):raise ValueError('Inert review reached an external probe')
    namespaces=[]
    for tree in trees:
        constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('FORBIDDEN_ENV','CONTEXT_KEYS')}
        node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='generation_decision'))
        # Only the prefix ending at the first filesystem operation is compiled.
        stop=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix' for t in n.targets))
        node.body=node.body[:stop+1]
        namespace={'os':os,'Path':stop_path,'probe':stop_probe,**constants}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<pinned-guard-prefix>','exec'),namespace)
        namespaces.append(namespace)
    old,new=namespaces
    require(old['FORBIDDEN_ENV']==new['FORBIDDEN_ENV'] and old['CONTEXT_KEYS']==new['CONTEXT_KEYS'],'Guard field policy changed')
    names=sorted(new['FORBIDDEN_ENV']);require(len(names)==19 and len(set(names))==19,'Exactly19 forbidden fields required')
    def result(namespace,env):
        try:namespace['generation_decision']('never-opened',environment=env,run=stop_probe)
        except ReachedPath:return None
        except ValueError as exc:return str(exc)
        raise ValueError('Unexpected guard exit')
    base={'PYTHONDONTWRITEBYTECODE':'1','PATH':'/explicit/directory'};cases=0
    for name,value in itertools.product(names,(None,'','private-canary-secret',' ','\nprivate-canary-secret','0')):
        env={**base,name:value};before=result(old,env);after=result(new,env)
        if value in (None,''):require(before is None and after is None,'Empty field changed admission')
        else:
            require(before=='Unsupported build/import environment override','Original refusal changed')
            require(after=='Unsupported build/import environment override: '+name,'Diagnostic exposed value or changed field')
        cases+=1
    for a,b in itertools.combinations(reversed(names),2):
        env={**base,a:'private-left-canary',b:'private-right-canary'}
        require(result(old,env)=='Unsupported build/import environment override','Original pair refusal')
        require(result(new,env)=='Unsupported build/import environment override: '+', '.join(sorted((a,b))),'Pair value privacy/order')
        cases+=1
    for bytecode in (None,'','0'):
        env={'PATH':'/explicit/directory',names[0]:'private-canary-secret'}
        if bytecode is not None:env['PYTHONDONTWRITEBYTECODE']=bytecode
        require(result(old,env)==result(new,env)=='Activated decision requires inherited bytecode suppression','Guard priority changed');cases+=1
    env={**base,**{k:'private-all-canary' for k in reversed(names)}}
    require(result(new,env)=='Unsupported build/import environment override: '+', '.join(names),'All-fields privacy/order');cases+=1
    for unknown in ('DYLD_UNKNOWN','LD_UNKNOWN','GCC_UNKNOWN','GFORTRAN_UNKNOWN','PYTHONUNKNOWN','_PYTHONUNKNOWN'):
        env={**base,unknown:'private-unknown-canary'}
        require(result(old,env)==result(new,env)=='Unknown build/import environment variable: '+unknown,'Unknown-prefix rule changed');cases+=1
    require(cases==295,'Case population')
    return {'passed_cases':cases,'forbidden_fields':19,'unchanged_other_functions':len(functions[0])-1,'external_probes':0,'raw_payload_reads':0,'new_events':0,'new_fits':0}
