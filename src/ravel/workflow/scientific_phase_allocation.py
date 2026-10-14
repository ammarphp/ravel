"""Pure scientific phase policy: reserve declared checks before new work/polish.

This does not schedule, authorize, price or execute work. Costs are supplied
ceilings; completed checks and actual usage need caller-owned execution evidence.
Every affordable design is individually feasible, not a jointly feasible batch.
"""
from copy import deepcopy
import math

RESOURCES=('calls','output_tokens','wall_seconds','native_attempts')
ZERO={key:0 for key in RESOURCES}

def _closed(value,fields,label):
    if type(value) is not dict or set(value)!=set(fields):
        raise ValueError(label+' requires exact fields '+','.join(fields))

def _vector(value,label):
    _closed(value,RESOURCES,label)
    for key,v in value.items():
        if key=='wall_seconds':
            valid=type(v) in (int,float) and math.isfinite(v) and v>=0
        else:valid=type(v) is int and v>=0
        if not valid:raise ValueError(label+'.'+key+' requires a finite nonnegative '+('number' if key=='wall_seconds' else 'integer'))
    return deepcopy(value)

def _ids(value,known,label):
    if type(value) is not list or any(type(v) is not str or not v.strip() for v in value) or len(set(value))!=len(value):
        raise ValueError(label+' requires unique nonblank IDs')
    if set(value)-set(known):raise ValueError(label+' references unknown IDs')
    return value[:]

def _id(value,label):
    if type(value) is not str or not value.strip():raise ValueError(label+' requires a nonblank ID')
    return value

def _add(*vectors):
    result={key:sum(v[key] for v in vectors) for key in RESOURCES}
    if not math.isfinite(result['wall_seconds']):raise ValueError('summed wall ceiling is nonfinite')
    return result

def _deficit(required,available):return {k:max(0,required[k]-available[k]) for k in RESOURCES}
def _feasible(deficit):return not any(deficit.values())

def allocate(request):
    """Return pending check reservation and individually affordable next phases.

    Closed request: schema_version1, budget/usage resource vectors; checks{id,cost};
    designs{id,construction_cost,check_ids,polish_cost}; completed_check_ids,
    retained_design_ids and mandatory_check_ids. A design's checks reserve once
    across the global and retained union. Unknown/failed checks stay pending.
    Completed IDs are supplied facts, never inferred from fit/optimizer success.
    """
    _closed(request,('schema_version','budget','usage','checks','designs','completed_check_ids','retained_design_ids','mandatory_check_ids'),'request')
    if type(request['schema_version']) is not int or request['schema_version']!=1:raise ValueError('schema_version must be integer1')
    budget=_vector(request['budget'],'budget');usage=_vector(request['usage'],'usage')
    checks={};designs={}
    for field in ('checks','designs'):
        if type(request[field]) is not list:raise ValueError(field+' must be a list')
    for row in request['checks']:
        _closed(row,('id','cost'),'check');identity=_id(row['id'],'check')
        if identity in checks:raise ValueError('duplicate check ID')
        checks[identity]=_vector(row['cost'],'check '+identity)
    for row in request['designs']:
        _closed(row,('id','construction_cost','check_ids','polish_cost'),'design');identity=_id(row['id'],'design')
        if identity in designs:raise ValueError('duplicate design ID')
        designs[identity]={'construction_cost':_vector(row['construction_cost'],'construction '+identity),'check_ids':_ids(row['check_ids'],checks,'design check_ids'),'polish_cost':_vector(row['polish_cost'],'polish '+identity)}
    complete=set(_ids(request['completed_check_ids'],checks,'completed_check_ids'))
    retained=_ids(request['retained_design_ids'],designs,'retained_design_ids')
    mandatory=_ids(request['mandatory_check_ids'],checks,'mandatory_check_ids')
    standing=set(mandatory)
    for identity in retained:standing.update(designs[identity]['check_ids'])
    standing-=complete
    # Retain user declaration order; shared checks appear only once.
    ordered=[identity for identity in checks if identity in standing]
    reserve=_add(*[checks[x] for x in ordered]) if ordered else ZERO.copy()
    available={k:max(0,budget[k]-usage[k]) for k in RESOURCES}
    overrun=_deficit(usage,budget)
    reservation_deficit=_deficit(reserve,available)
    rows=[]
    for identity,design in designs.items():
        extra=[x for x in design['check_ids'] if x not in complete and x not in standing]
        new_cost=_add(design['construction_cost'],reserve,*[checks[x] for x in extra])
        deficits=_deficit(new_cost,available)
        if identity in retained:
            construction={'status':'retained','cost':design['construction_cost'],'pending_check_ids':[x for x in design['check_ids'] if x not in complete]}
        else:
            construction={'status':'affordable' if _feasible(deficits) and _feasible(overrun) else 'blocked','cost':design['construction_cost'],'required_total_with_reservation':new_cost,'additional_check_ids':extra,'deficits':deficits}
        missing=list(dict.fromkeys([x for x in [*mandatory,*design['check_ids']] if x not in complete]))
        polish_total=_add(design['polish_cost'],reserve);polish_deficit=_deficit(polish_total,available)
        reason='design_not_retained' if identity not in retained else 'checks_pending' if missing else 'budget' if not _feasible(polish_deficit) or not _feasible(overrun) else None
        rows.append({'id':identity,'construction':construction,'polish':{'status':'affordable' if reason is None else 'blocked','reason':reason,'cost':design['polish_cost'],'pending_check_ids':missing,'deficits':polish_deficit}})
    return {'schema_version':1,'budget':budget,'actual_usage':usage,'available_before_reservation':available,'actual_usage_overrun':overrun,'pending_reserved_check_ids':ordered,'check_reservation':reserve,'check_reservation_deficits':reservation_deficit,'available_after_reservation':{k:max(0,available[k]-reserve[k]) for k in RESOURCES},'designs':rows,'affordable_design_ids':[r['id'] for r in rows if r['construction']['status']=='affordable'],'blocked_design_ids':[r['id'] for r in rows if r['construction']['status']=='blocked'],'polishable_design_ids':[r['id'] for r in rows if r['polish']['status']=='affordable'],'individual_feasibility_only':True,'execution_authorized':False,'scientific_completion_inferred':False,'limitations':['Declared ceilings are not prices, observed runtime or cancellation guarantees.','Caller must debit actual receipts and retain failures/overruns before reallocating.','Unknown or failed independent checks must not enter completed_check_ids.','Reservation is resource policy, not evidence that scientific checks passed.']}
