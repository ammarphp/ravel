"""Full supplied SModelS coverage -> existing located knowledge/research inputs.

This pure preparation grants no parent acceptance, response, study or dispatch.
The existing research cycle binds the resulting request to its actual premises.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from ravel.workflow import physics_knowledge as knowledge
from ravel.workflow.state_io import atomic_json


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('finite nonnegative '+label+' required')


def prepare(native_pin, report_pin, output, *, base=None):
    """Produce a complete located index and normal physics-knowledge request.

    Pins have exact path/sha256/size. Original two JSON files remain parents;
    every coverage signature, including zero rows, is retained without sums.
    Missing response/acceptance is unknown, never a numerical efficiency zero.
    """
    raw_output=Path(output)
    if '..' in raw_output.parts:
        raise ValueError('parent-directory aliases are not permitted in the fresh knowledge output')
    base=Path.cwd() if base is None else Path(base)
    np, nb=knowledge._snapshot(native_pin,base)
    rp, rb=knowledge._snapshot(report_pin,base)
    if np['path']==rp['path']:
        raise ValueError('distinct native/report original files required')
    native,report=knowledge._json(nb),knowledge._json(rb)
    native_keys={'output_status','predictions','decomposition','coverage','supplied_physics','loaded_database_census'}
    report_keys={'status','physics_validated','scope','conclusion','selection','coverage','follow_up','source','database','runtime',
                 'protocol','output_status','predictions','supplied_physics','native_artifacts','limitations'}
    if (type(native) is not dict or type(report) is not dict
            or set(native)!=native_keys or set(report)!=report_keys
            or report.get('physics_validated') is not False
            or report.get('output_status')!=native.get('output_status')
            or report.get('predictions')!=native.get('predictions')
            or report.get('supplied_physics')!=native.get('supplied_physics')
            or report.get('coverage')!={'groups':native.get('coverage'),'groups_overlap':True,
                                      'groups_must_not_be_summed':True,'omitted_below_sigmacut_not_zero':True}):
        raise ValueError('complete matching original native/report population and unknown-coverage semantics required')
    if (type(native['output_status']) is not dict
            or type(native['output_status'].get('decomposition status')) is not int
            or report['status']!=('passed' if native['output_status']['decomposition status']>=0 else 'failed')
            or type(native['predictions']) is not list or type(native['decomposition']) is not list
            or type(native['supplied_physics']) is not dict
            or type(report['database']) is not dict or report['database'].get('version') != '3.1.1'
            or type(report['runtime']) is not dict or report['runtime'].get('smodels_version') != '3.1.1'
            or type(report['protocol']) is not dict
            or type(report['source']) is not str or not report['source'].strip()
            or type(report['limitations']) is not list or not report['limitations']
            or any(type(x) is not str or not x.strip() for x in report['limitations'])):
        raise ValueError('original decomposition disposition, version3.1.1 and complete supplied protocol/physics attribution required')
    groups=native['coverage']
    if type(groups) is not list or len(groups)>64:
        raise ValueError('bounded complete coverage group census required')
    group_labels=set();members=[]
    for gi,group in enumerate(groups):
        if type(group) is not dict or set(group)!={'label','description','sqrts_tev','total_xsec_fb','signatures'}:
            raise ValueError('full native coverage group fields required')
        for name in ('label','description'):
            if type(group[name]) is not str or not group[name].strip():raise ValueError('located native label/description required')
        if group['label'] in group_labels:raise ValueError('duplicate native coverage group label')
        group_labels.add(group['label'])
        _number(group['sqrts_tev'],'TeV energy');_number(group['total_xsec_fb'],'fb coverage weight')
        if type(group['signatures']) is not list:raise ValueError('complete signature list required')
        for si,sig in enumerate(group['signatures']):
            if (type(sig) is not dict or set(sig)!={'sms','weight_fb','native_sms_ids'}
                    or type(sig['sms']) is not str or not sig['sms'].strip()
                    or type(sig['native_sms_ids']) is not list
                    or any(type(x) is not int or x<0 for x in sig['native_sms_ids'])
                    or len(set(sig['native_sms_ids']))!=len(sig['native_sms_ids'])):
                raise ValueError('full located SMS text, weight and unique native identities required')
            _number(sig['weight_fb'],'fb signature weight')
            members.append((gi,si,sig))
    if 1+len(groups)+len(members)>knowledge.MAX_NODES:
        raise ValueError('complete population exceeds existing knowledge bound; no automatic truncation')
    lines=[];nodes=[];edges=[]
    def line(value,locator):
        payload=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(payload)>16000:raise ValueError('located evidence exceeds existing excerpt bound')
        lines.append(payload)
        return [{'source':'coverage-extract','line_start':len(lines),'line_end':len(lines),
                 'excerpt_sha256':hashlib.sha256(payload).hexdigest(),'locator':locator}]
    def node(identity,statement,evidence,obligations=None):
        return {'id':identity,'kind':'fact','statement':statement,'tags':['SModelS','unsupported-SMS'],
                'domain':['collider','supplied-model','SModelS3.1.1'],
                'conventions':['fb weights and TeV energy','native groups overlap; never sum across groups','no missing efficiency as zero'],
                'applicability':'Located supplied native/report evidence only. Parent science acceptance and response/model applicability are not established by this producer.',
                'equations':[],'evidence':evidence,'obligations':[] if obligations is None else obligations}
    basis={'status':report.get('status'),'conclusion':report.get('conclusion'),'protocol':report.get('protocol'),
           'source':report.get('source'),'limitations':report.get('limitations'),
           'complete_groups':len(groups),'complete_signatures':len(members),
           'groups_overlap':True,'groups_must_not_be_summed':True,'omitted_below_sigmacut_not_zero':True}
    nodes.append(node('coverage-basis','Supplied SModelS coverage is overlapping lifetime/topology applicability evidence. Missing or cutoff-omitted response remains unknown; no global exclusion or zero efficiency follows.',
                      line(basis,'portfolio.json#/coverage; original protocol/conclusion/limitations')))
    for gi,group in enumerate(groups):
        identity='group.'+str(gi)
        header={k:deepcopy(v) for k,v in group.items() if k!='signatures'};header['signature_count']=len(group['signatures'])
        nodes.append(node(identity,'Native coverage group '+group['label']+' contains '+str(len(group['signatures']))+' supplied signatures. Its original total weight is retained as source evidence, not an additive missing-model total.',
                          line(header,'portfolio-native.json#/coverage/'+str(gi))))
        edges.append({'id':'basis.'+str(gi),'kind':'requires','source':identity,'target':'coverage-basis',
                      'statement':'Keep source protocol, lifetime/domain and overlapping-group limitations.','assessment':'source_assertion'})
    for gi,si,sig in members:
        identity='signature.'+str(gi)+'.'+str(si)
        obligations=[]
        if sig['weight_fb']>0:
            obligations=[{'id':'response.'+str(gi)+'.'+str(si),'resource_class':'source_inspection','check':None,
                          'description':'Locate a response/likelihood for this exact supplied SMS, masses, lifetime and energy, or retain unavailable applicability.'},
                         {'id':'study.'+str(gi)+'.'+str(si),'resource_class':'prospective_study','check':None,
                          'description':'If an event-level route is proposed, design a source/model/domain/response-bound ordinary study with supplied inputs and explicit root resources. No events or response are authorized here.'}]
        nodes.append(node(identity,'Complete supplied signature '+sig['sms']+' has native missing weight '+str(sig['weight_fb'])+' fb in group '+groups[gi]['label']+'. Response and event-level efficiency remain unknown; the weight is not an efficiency.',
                          line(sig,'portfolio-native.json#/coverage/'+str(gi)+'/signatures/'+str(si)),obligations))
        edges.append({'id':'group-link.'+str(gi)+'.'+str(si),'kind':'requires','source':identity,'target':'group.'+str(gi),
                      'statement':'Preserve native group context and overlapping membership.','assessment':'source_assertion'})
    # Refuse all known data/population/size problems before creating output files.
    if sum(map(len,lines))>knowledge.MAX_DOCUMENT_BYTES:raise ValueError('complete extraction exceeds knowledge source bound')
    out=raw_output.absolute()
    if any(p.is_symlink() for p in (out,*out.parents)):raise ValueError('ordinary fresh knowledge output required')
    if any(out.is_relative_to(Path(p['path']).parent) for p in (np,rp)):
        raise ValueError('new knowledge must not change either original output directory inventory')
    knowledge._snapshot(np,base);knowledge._snapshot(rp,base)
    out.mkdir(parents=True,exist_ok=False)
    text=out/'coverage-evidence.jsonl';text.write_bytes(b''.join(lines))
    def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    sources=[{'id':identity,'pin':p,'citation':'Complete supplied ordinary SModelS '+label+'; not an independent physics oracle',
              'version':'native3.1.1 supplied record','format':'binary','parents':[]}
             for identity,p,label in [('native-original',np,'native output'),('report-original',rp,'report')]]
    sources.append({'id':'coverage-extract','pin':pin(text),'citation':'Deterministic full native coverage census and original report protocol',
                    'version':'model-portfolio-knowledge/v1','format':'text','parents':['native-original','report-original']})
    graph={'schema_version':1,'id':'supplied-model-portfolio.coverage','sources':sources,'nodes':nodes,'edges':edges}
    gp=out/'knowledge.json';atomic_json(gp,graph)
    request={'schema_version':1,'knowledge':pin(gp),'query':{'text':'Complete unknown simplified-model coverage follow-up',
             'tags':['unsupported-SMS'],'roots':[n['id'] for n in nodes],'domain':['collider'], 'max_nodes':len(nodes)}}
    # Use the actual existing consumer now. It checks located excerpts/parents,
    # full retrieval closure, source pins and packet bounds; no operation runs.
    packet=knowledge.retrieve(request,out)
    assert len(packet['nodes'])==len(nodes) and not packet['selection']['omitted']
    assert not packet['claims']['execution_authorized'] and not packet['claims']['physics_verified']
    atomic_json(out/'request.json',request)
    atomic_json(out/'PREPARATION.json',{'schema_version':1,'kind':'complete-model-portfolio-knowledge-source',
                'source_pins':[np,rp],'coverage_groups':len(groups),'coverage_signatures':len(members),
                'request':pin(out/'request.json'),'input_pins':knowledge.input_pins(request,out),
                'accepted_parent_validated':False,'native_calls':0,'provider_calls':0,
                'execution_authorized':False,'physics_verified':False,
                'next':'Existing Host physics-knowledge retrieval or research_cycle.bind_knowledge with explicit premise mapping, then normal knowledge_next/propose/design/select. Parent acceptance, study approval and root lease remain separate.'})
    return request
