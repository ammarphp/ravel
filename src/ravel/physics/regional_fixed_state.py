"""Optional fixed-state observer of an existing regional ModelConfig/NLL.

No ROOT imports, PDF construction, optimization or analytic reference values.
The admitted native worker supplies the workspace, NLL, state consumer and an
explicit RooArgSet factory for separate, non-authoritative PDF diagnostics.
"""
from copy import deepcopy
from fractions import Fraction
import json
import math
import re

MAX_STATES = 32


def same(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def finite(x):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise ValueError('finite numeric fixed-state coordinate required')
    return float(x)


def validate_request(request, response):
    if type(request) is not dict or set(request) != {'states','functions','pdf_diagnostics'}:
        raise ValueError('closed fixed-state observer request required')
    if not response or response.get('kind') != 'regional-poisson-construction/v1':
        raise ValueError('fixed-state observer requires exact regional construction')
    if request['functions'] != list(response['functions']) or type(request['pdf_diagnostics']) is not bool:
        raise ValueError('complete ordered count-function census required')
    if type(request['states']) is not list or not 1 <= len(request['states']) <= MAX_STATES:
        raise ValueError('one to 32 complete fixed states required')
    d=response['document']; names=response['coordinates']; seen=set()
    diagnostics=sum('shape' in t for t in d['terms']) if request['pdf_diagnostics'] else 0
    if 3+len(request['states'])*(len(request['functions'])+diagnostics+3)>1040:
        raise ValueError('fixed-state journal event denominator exceeds existing reader cap')
    for row in request['states']:
        if type(row) is not dict or set(row) != {'id','coordinates'} or not isinstance(row['id'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',row['id']) or row['id'] in seen:
            raise ValueError('unique literal fixed-state identity required')
        seen.add(row['id'])
        if type(row['coordinates']) is not dict or set(row['coordinates']) != set(names):
            raise ValueError('complete physical and whitened-nuisance state required')
        for name,value in row['coordinates'].items():
            v=finite(value); p=next((p for p in d['parameters'] if p['name']==name),None)
            bounds=p['bounds'] if p else d['auxiliary']['eta_bounds'][int(name.rsplit('_',1)[1])]
            if not float(Fraction(bounds[0])) <= v <= float(Fraction(bounds[1])) or p and p['fixed'] and v != float(Fraction(p['initial'])):
                raise ValueError('fixed state violates declared bounds/constant flag')
    return deepcopy(request)


def _literal(value):
    x=float(value)
    return {'hex':x.hex(),'finite':math.isfinite(x),'value':x if math.isfinite(x) else None}


def _initial(request,response,initial):
    byname={r['name']:r for r in initial['parameters']};d=response['document'];mc=initial['model_config']
    expected_nuisances={p['name'] for p in d['parameters'] if p['role']!='poi' and not p['fixed']}
    expected_nuisances.update('ravel_aux_'+str(i) for i in range(len(d['auxiliary']['names'])))
    if set(mc['nuisances']) != expected_nuisances or mc['pois'] != [response['domain']['name']]:
        raise ValueError('fixed-state ModelConfig POI/nuisance census differs')
    if set(mc['global_observables']) != {'ravel_aux_'+str(i)+'_In' for i in range(len(d['auxiliary']['names']))}:
        raise ValueError('fixed-state Gaussian global-observable census differs')
    for name in response['coordinates']:
        r=byname.get(name);p=next((p for p in d['parameters'] if p['name']==name),None)
        bounds=p['bounds'] if p else d['auxiliary']['eta_bounds'][int(name.rsplit('_',1)[1])]
        fixed=p['fixed'] if p else False
        if not r or r['kind']!='continuous' or r['constant']!=fixed or r['value'] != (float(Fraction(p['initial'])) if p else 0.0) or r['bounds']!={'min':float(Fraction(bounds[0])),'max':float(Fraction(bounds[1]))}:
            raise ValueError('fixed-state coordinate initial value/flags/bounds differ from source')
    return byname


def execute(workspace, mc, data, nll, request, response, consumer, normset_factory, *, recorder):
    request=validate_request(request,response)
    initial=consumer.capture(workspace,mc);_initial(request,response,initial)
    dataset=consumer.data_census(data);events=[];rows=[];result=None
    calls={'count_functions':0,'nll':0,'pdf_diagnostics':0,'fit':0}
    def emit(status,**payload):
        event={'sequence':len(events),'status':status,'payload':payload}
        recorder(deepcopy(event));events.append(event)
    emit('started',request=request,initial_state=initial,observed_data=dataset)
    try:
        for point in request['states']:
            assigned=deepcopy(initial)
            for p in assigned['parameters']:
                if p['name'] in point['coordinates']:p['value']=float(point['coordinates'][p['name']])
            consumer.restore(workspace,mc,assigned)
            if not same(consumer.data_census(data),dataset):raise ValueError('observed data/globals changed before fixed state')
            emit('assigned',id=point['id'],state=assigned)
            row={'id':point['id'],'coordinates':deepcopy(point['coordinates']),'means':{},'nll':None,'pdf_diagnostics':[]}
            for name in request['functions']:
                obj=workspace.function(name)
                if not obj:raise ValueError('count function absent: '+name)
                calls['count_functions']+=1
                literal=_literal(obj.getVal());emit('returned',id=point['id'],kind='count',name=name,literal=literal)
                if not literal['finite'] or literal['value'] <= 0:raise ValueError('nonfinite/nonpositive count mean')
                row['means'][name]=literal['value']
            calls['nll']+=1
            literal=_literal(nll.getVal());emit('returned',id=point['id'],kind='nll',name='existing_ModelConfig_NLL',literal=literal)
            if not literal['finite']:raise ValueError('nonfinite fixed NLL')
            row['nll']=literal['value']
            # These unused RooExponential normalizations are diagnostic only.
            # They never substitute for the count fractions or NLL above.
            if request['pdf_diagnostics']:
                for i,term in enumerate(response['document']['terms']):
                    if 'shape' not in term:continue
                    name='ravel_shape_'+str(i)+'_pdf';xname='ravel_shape_'+str(i)+'_x'
                    pdf=workspace.pdf(name);axis=workspace.var(xname)
                    if not pdf or not axis or not axis.isConstant():raise ValueError('declared fixed shape diagnostic object absent')
                    item={'name':name,'normalization_axis':xname,'used_in_count_means':False,'status':'failed','literal':None}
                    calls['pdf_diagnostics']+=1
                    try:
                        item['literal']=_literal(pdf.getVal(normset_factory(axis)))
                        item['status']='finite' if item['literal']['finite'] else 'nonfinite'
                    except Exception as exc:
                        item['error']={'type':type(exc).__name__,'message':str(exc)[:2048]}
                    emit('pdf_diagnostic_returned',id=point['id'],diagnostic=item)
                    row['pdf_diagnostics'].append(item)
            after=consumer.capture(workspace,mc)
            if not consumer._state_after_allowed(assigned,after):raise ValueError('fixed observer changed non-observable state')
            if not same(consumer.data_census(data),dataset):raise ValueError('observed data/globals changed during fixed state')
            emit('checked',id=point['id'],row=row,after_state=after);rows.append(row)
        result={'status':'passed','request':request,'initial_state':initial,'observed_data':dataset,'rows':rows,'calls':calls,
                'scope':'Complete regional count means and existing constrained NLL at declared fixed states; separate unused PDF diagnostic',
                'native_accuracy_qualified':False,'inference_qualified':False}
    except BaseException as exc:
        emit('failed',error={'type':type(exc).__name__,'message':str(exc)[:4096]},calls=calls)
        raise
    finally:
        try:
            try:
                ending_data=consumer.data_census(data)
            finally:
                consumer.restore(workspace,mc,initial)
            if not same(ending_data,dataset):raise ValueError('fixed observer ending data/globals changed')
            emit('reset',state=consumer.capture(workspace,mc),calls=calls)
        except BaseException as exc:
            emit('reset_failed',error={'type':type(exc).__name__,'message':str(exc)[:4096]},calls=calls)
            raise
    result['final_state']=consumer.capture(workspace,mc)
    emit('completed',calls=calls);result['journal']=events
    return result


def validate_delivery(result,request,response,consumer):
    request=validate_request(request,response)
    if result.get('status')!='passed' or not same(result.get('request'),request) or not same(result.get('initial_state'),result.get('final_state')):
        raise ValueError('fixed-state successful delivery/reset differs')
    _initial(request,response,result['initial_state'])
    events=result['journal'];expected_seq=list(range(len(events)))
    if [e.get('sequence') for e in events]!=expected_seq or events[0]['status']!='started' or events[-1]['status']!='completed':raise ValueError('fixed-state journal incomplete')
    if not same(events[0]['payload'],{'request':request,'initial_state':result['initial_state'],'observed_data':result['observed_data']}):raise ValueError('fixed-state initial journal differs')
    shape_count=sum('shape' in t for t in response['document']['terms']) if request['pdf_diagnostics'] else 0
    expected_calls={'count_functions':len(request['states'])*len(request['functions']),'nll':len(request['states']),'pdf_diagnostics':len(request['states'])*shape_count,'fit':0}
    if result['calls']!=expected_calls or [r['id'] for r in result['rows']]!=[r['id'] for r in request['states']]:raise ValueError('fixed-state complete call/row denominator differs')
    cursor=1
    for point,row in zip(request['states'],result['rows']):
        assigned=deepcopy(result['initial_state'])
        for p in assigned['parameters']:
            if p['name'] in point['coordinates']:p['value']=float(point['coordinates'][p['name']])
        expected=[('assigned',{'id':point['id'],'state':assigned})]
        if row['coordinates']!=point['coordinates'] or set(row['means'])!=set(request['functions']):raise ValueError('fixed-state parameter/function census differs')
        for name in request['functions']:
            v=finite(row['means'][name])
            if v<=0:raise ValueError('fixed-state mean not positive')
            expected.append(('returned',{'id':point['id'],'kind':'count','name':name,'literal':_literal(v)}))
        expected.append(('returned',{'id':point['id'],'kind':'nll','name':'existing_ModelConfig_NLL','literal':_literal(finite(row['nll']))}))
        if len(row['pdf_diagnostics'])!=shape_count:raise ValueError('PDF diagnostic census differs')
        diagnostic_ids=['ravel_shape_'+str(i)+'_pdf' for i,t in enumerate(response['document']['terms']) if 'shape' in t] if request['pdf_diagnostics'] else []
        if [q['name'] for q in row['pdf_diagnostics']]!=diagnostic_ids:raise ValueError('PDF diagnostic identities differ')
        for item in row['pdf_diagnostics']:
            if item.get('used_in_count_means') is not False or item.get('normalization_axis')!=item['name'][:-3]+'x':raise ValueError('PDF diagnostic semantics differ')
            literal=item.get('literal')
            if literal is not None:
                value=float.fromhex(literal['hex'])
                if not same(literal,_literal(value)) or item['status']!=('finite' if math.isfinite(value) else 'nonfinite'):raise ValueError('PDF diagnostic literal differs')
            elif item['status']!='failed' or not item.get('error'):raise ValueError('missing PDF diagnostic return')
            expected.append(('pdf_diagnostic_returned',{'id':point['id'],'diagnostic':item}))
        for status,payload in expected:
            if cursor>=len(events) or events[cursor]['status']!=status or not same(events[cursor]['payload'],payload):raise ValueError('fixed-state raw/derived journal differs')
            cursor+=1
        check=events[cursor]
        if check['status']!='checked' or not same(check['payload']['row'],row) or check['payload']['id']!=point['id']:raise ValueError('fixed-state checked row differs')
        if not consumer._state_after_allowed(assigned,check['payload']['after_state']):raise ValueError('recorded fixed state changed')
        cursor+=1
    tails=[('reset',{'state':result['final_state'],'calls':expected_calls}),('completed',{'calls':expected_calls})]
    if len(events)!=cursor+2:raise ValueError('fixed-state terminal event count differs')
    for e,(status,payload) in zip(events[cursor:],tails):
        if e['status']!=status or not same(e['payload'],payload):raise ValueError('fixed-state terminal journal differs')
    return {'passed':True,'scope':result['scope'],'calls':expected_calls,'native_accuracy_qualified':False,'inference_qualified':False}
