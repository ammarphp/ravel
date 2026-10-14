"""Source-bound production ancestry and reconstructed-origin accounting.

All categories, root predicates, channel mappings and selection evidence come
from supplied contracts. Signed weights and complete source populations remain.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import gzip
import inspect
import json
import math
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

from . import compressed_validation as cv
from . import truth_reco_response as truth
from .native_normalization import load_normalization
from .native_pipeline import plan_hash
from .pool_replicas import historical_receipts, pinned, scalar_arrays
from ravel.workflow.state_io import read_json

def origin_contract(contract):
    required={'response','root_selector','categories','unresolved_category','reco_rules','overlays','join'}
    if not isinstance(contract,dict) or not required<=set(contract):raise truth.ResponseInputError('supplied ancestry accounting contract required','missing_input')
    if set(contract)!=required:raise truth.ResponseInputError('closed ancestry accounting contract required')
    truth.response_contract(contract['response'])
    selector=contract['root_selector']
    if set(selector)!={'minimum_abs_pid','modulus','remainders'} or type(selector['minimum_abs_pid']) is not int or selector['minimum_abs_pid']<0 or type(selector['modulus']) is not int or selector['modulus']<=0 or not isinstance(selector['remainders'],list) or any(type(x) is not int or not 0<=x<selector['modulus'] for x in selector['remainders']):raise truth.ResponseInputError('supplied integer root predicate required')
    rows=contract['categories']
    if not isinstance(rows,list) or not rows or any(set(r)!={'id','any_root_pids'} or not isinstance(r['id'],str) or not r['id'] or not isinstance(r['any_root_pids'],list) or any(type(v) is not int or v<=0 for v in r['any_root_pids']) for r in rows) or len({r['id'] for r in rows})!=len(rows) or contract['unresolved_category'] not in {r['id'] for r in rows} or sum(not r['any_root_pids'] and r['id']!=contract['unresolved_category'] for r in rows)!=1:raise truth.ResponseInputError('explicit unique category population required')
    rules=contract['reco_rules']
    if not isinstance(rules,list) or not rules or any(set(r)!={'id','kind','root_pids','via_pids'} or r['kind'] not in ('ambiguous','root_via','ancestor','root','direct','other') or not isinstance(r['id'],str) or not r['id'] or any(not isinstance(r[k],list) or any(type(v) is not int or v<=0 for v in r[k]) for k in ('root_pids','via_pids')) for r in rules) or rules[-1]['kind']!='other':raise truth.ResponseInputError('ordered complete reco origin rules required')
    if not isinstance(contract['overlays'],dict) or any(not isinstance(k,str) or not k or v not in {r['id'] for r in rules} for k,v in contract['overlays'].items()):raise truth.ResponseInputError('explicit reco-origin overlays required')
    return contract


def close(a,b,*,tolerance=1e-10):
    return math.isclose(truth.finite(a,'weight/moment'),truth.finite(b,'weight/moment'),rel_tol=tolerance,abs_tol=1e-15)


def selected_root(pid,contract):
    selector=contract['root_selector'];pid=abs(pid)
    return pid>=selector['minimum_abs_pid'] and pid%selector['modulus'] in selector['remainders']


def classify_pair(pids,stable_count=None,*,contract=None):
    contract=origin_contract(contract);response=contract['response'];reasons=[]
    allowed={r['parent_pid'] for r in response['parent_relations']}
    if any(abs(p) not in allowed for p in pids):reasons.append('unsupported_root_code')
    for rule in response['topology']:
        kind,value=rule['kind'],rule['value']
        if kind=='root_count' and len(pids)!=value:reasons.append('root_count_differs')
        elif kind=='opposite_signed_pair' and value and (len(pids)!=2 or (pids[0]>0)==(pids[1]>0)):reasons.append('same_sign_pair')
        elif kind=='stable_count' and stable_count is not None and stable_count!=value:reasons.append('stable_count_differs')
    category=contract['unresolved_category'] if reasons else next((r['id'] for r in contract['categories'] if r['any_root_pids'] and any(abs(pid) in r['any_root_pids'] for pid in pids)),next(r['id'] for r in contract['categories'] if not r['any_root_pids'] and r['id']!=contract['unresolved_category']))
    return category,reasons


def analyze_origin(event,*,contract=None):
    """Validate the complete DAG/TRefs and retain ambiguous supplied ancestry."""
    contract=origin_contract(contract);policy=dict(contract['response'],topology=[])
    validated=truth.analyze_event(event,contract=policy)
    particles=event['particles'];mothers,order=truth.mothers_and_order(particles)
    roots=[i for i,p in enumerate(particles) if selected_root(p['pid'],contract) and not any(particles[m]['pid']==p['pid'] for m in mothers[i])]
    root_set=set(roots);ancestors=[set() for _ in particles];via={r['id']:[set() for _ in particles] for r in contract['reco_rules'] if r['kind']=='root_via'}
    for i in order:
        if i in root_set:ancestors[i].add(i)
        for m in mothers[i]:
            ancestors[i].update(ancestors[m])
            for states in via.values():states[i].update(states[m])
        for rule in contract['reco_rules']:
            if rule['kind']=='root_via' and abs(particles[i]['pid']) in rule['via_pids']:
                via[rule['id']][i].update(r for r in ancestors[i] if abs(particles[r]['pid']) in rule['root_pids'])
    pids=sorted(particles[i]['pid'] for i in roots);category,reasons=classify_pair(pids,validated['stable_particle_count'],contract=contract);reco=[]
    for obj in validated['reco_particles']:
        i=obj['particle_index'];root_indices=sorted(ancestors[i]);ancestor_indices=truth._ancestor_indices(i,mothers)|{i};lineage={key:sorted(states[i]) for key,states in via.items()}
        for rule in contract['reco_rules']:
            kind=rule['kind']
            applies=(len(root_indices)>1 if kind=='ambiguous' else bool(lineage[rule['id']]) if kind=='root_via' else any(abs(particles[a]['pid']) in rule['via_pids'] for a in ancestor_indices) if kind=='ancestor' else any(abs(particles[r]['pid']) in rule['root_pids'] for r in root_indices) if kind=='root' else obj['origin']==policy['origin_labels']['direct'] if kind=='direct' else True)
            if applies:origin=rule['id'];break
        reco.append({'particle_uid':obj['particle_uid'],'particle_index':i,'flavour':obj['flavour'],'origin':origin,'root_indices':root_indices,'via_root_indices':lineage})
    origins={x['origin'] for x in reco}
    return {'event_id':validated['delphes_event_number'],'source_entry':validated['source_entry'],'weight_raw':validated['weight_raw'],'category':category,'topology_issues':reasons,'signed_root_pair':pids,'root_particle_indices':roots,'stable_particle_count':validated['stable_particle_count'],'reco_particles':reco,'overlays':{key:value in origins for key,value in contract['overlays'].items()}}


class Moments:
    def __init__(self):self.weights=[]
    def add(self,w):self.weights.append(truth.finite(w,'normalized event weight'))
    def result(self,lumi):
        total=math.fsum(self.weights);square=math.fsum(w*w for w in self.weights)
        if not all(math.isfinite(x) for x in (total,square,total*lumi,square*lumi*lumi)):raise ValueError('moment overflow')
        nonzero=sum(w!=0 for w in self.weights)
        return {'count':len(self.weights),'nonzero_weights':nonzero,'negative_weights':sum(w<0 for w in self.weights),
                'sumw_pb':total,'sumw2_pb2':square,'yield':total*lumi,'mc_error':math.sqrt(square)*lumi,
                'effective_events':total*total/square if square else None,
                'precision_status':'zero_selected_precision_unresolved' if not self.weights else
                    'zero_weight_or_signed_cancellation_precision_unresolved' if total==0 else 'poissonized_independent_event_moments'}


def subset_fraction(part,total):
    d=total['sumw_pb'];n=part['sumw_pb']
    result={'numerator_denominator_covariance_pb2':part['sumw2_pb2'],'ratio':n/d if d else None,
            'standard_error':None,'status':'precision_unresolved',
            'method':'shared-event delta approximation; not fixed-N multinomial variance or calibration'}
    if d and part['count'] not in (0,total['count']) and part['sumw2_pb2']:
        r=n/d;complement=total['sumw2_pb2']-part['sumw2_pb2']
        if complement < -1e-12*max(total['sumw2_pb2'],1e-100):raise ValueError('subset covariance inconsistent')
        variance=(part['sumw2_pb2']*(1-r)**2+max(0.,complement)*r*r)/(d*d)
        if not math.isfinite(variance):raise ValueError('ratio variance overflow')
        result.update(standard_error=math.sqrt(variance),status='signed_weight_delta_approximation' if total['negative_weights'] else 'shared_event_delta_approximation')
    return result


def indexed(rows, label):
    result={}
    for row in rows:
        key=truth.integer(row['event_id'],label+' Event')
        if key in result:raise ValueError('duplicate '+label+' Event')
        result[key]=row
    return result


def prepare_join(native_rows,trace_rows,arrays,mapping,*,contract=None):
    """Complete keyed join with source-selected predicate/channel semantics."""
    contract=origin_contract(contract);join=contract['join'];native=indexed(native_rows,'converted');traces=indexed(trace_rows,'trace')
    if not native or set(native)!=set(traces):raise ValueError('trace/converted full population differs')
    flags=join['flavour_flags'];required={'Event','eventWeight',*flags,*(v['region'] for v in mapping.values())}
    if not required<=set(arrays):raise ValueError('analysis ROOT lacks required channel/identity branches')
    size=len(arrays['Event'])
    if any(len(v)!=size for v in arrays.values()):raise ValueError('analysis branch length mismatch')
    analysis={}
    for i,key in enumerate(arrays['Event']):
        if isinstance(key,bool) or not hasattr(key,'__index__'):raise ValueError('analysis Event must be integer')
        key=int(key)
        if key in analysis:raise ValueError('duplicate analysis Event')
        analysis[key]=i
    solved={};region_names=set(arrays)-{'Event','eventWeight',*flags}
    for key,row in traces.items():
        truth.validate_trace_row(row,join['trace'])
        if not close(native[key]['weight_pb'],row['weight_pb']):raise ValueError('trace/converted weight differs')
        status=row.get(join['state_field']);accepted=set(row['accepted_regions'])
        if status not in (join['passed_state'],join['failed_state']):raise ValueError('unknown or unsuccessful native state')
        if not accepted<=region_names:raise ValueError('trace contains unknown analysis region')
        preconditions=join['object_preconditions']
        if 'trace_definition' in row and set(cv.object_preconditions(row))!=set(preconditions):raise ValueError('join contract and trace definition disagree on object preconditions')
        if status==join['passed_state']:
            if not all(row['predicates'][p] is True for p in preconditions):raise ValueError('solved trace lacks passed object preconditions')
            solved[key]=row
        elif accepted or not any(row['predicates'][p] is False for p in preconditions):raise ValueError('rejected trace lacks an actual failed object predicate')
    if set(analysis)!=set(solved):raise ValueError('analysis selected-row population differs from solved trace; no absent-row zero inference')
    channels={key:[] for key in native}
    for key,i in analysis.items():
        weight=truth.finite(float(arrays['eventWeight'][i]),'analysis weight')
        if weight!=native[key]['weight_pb']:raise ValueError('analysis weight differs from original normalized exposure')
        actual_flags={flag:arrays[flag][i] for flag in flags}
        if any(v not in (0,1) for v in actual_flags.values()) or sum(actual_flags.values())>1:raise ValueError('invalid analysis flavour flags')
        row=traces[key];objects=row.get(join['objects_field'],[]);selected=row['predicates'][join['selected_predicate']]
        if selected is True:
            if len(objects)!=join['selected_count'] or any(type(x.get(join['flavour_field'])) is not int or x[join['flavour_field']] not in flags.values() for x in objects):raise ValueError('trace object flavour evidence missing')
            expected={flag:int(all(x[join['flavour_field']]==value for x in objects)) for flag,value in flags.items()}
            if actual_flags!=expected:raise ValueError('analysis flavour flags disagree with trace')
        elif selected is not False:raise ValueError('analysis row lacks selected-object trace evidence')
        accepted=set(row['accepted_regions'])
        for region in region_names:
            if truth.finite(float(arrays[region][i]),'region weight')!=(weight if region in accepted else 0.):raise ValueError('region branch disagrees with trace/original event weight')
        for channel,entry in mapping.items():
            if entry['region'] in accepted:
                if selected is not True:raise ValueError('channel lacks supplied selected-object evidence')
                if entry.get('flavour') is None or actual_flags[entry['flavour']]:channels[key].append(channel)
        if len(channels[key])>1:raise ValueError('independent model channels overlap')
    return native,traces,channels


class OriginSummary:
    def __init__(self,mapping,lumi,contract):
        self.contract=json.loads(json.dumps(origin_contract(contract),allow_nan=False));categories=[r["id"] for r in contract["categories"]];overlays=contract["overlays"]
        self.mapping=mapping;self.lumi=truth.finite(lumi,'luminosity')
        if self.lumi<=0:raise ValueError('positive luminosity required')
        self.all=Moments();self.categories={k:Moments() for k in categories};self.pairs=defaultdict(Moments)
        self.channels={c:{'total':Moments(),'categories':{k:Moments() for k in categories},'pairs':defaultdict(Moments),'overlays':{k:Moments() for k in overlays}} for c in mapping}
        self.reco_origins=Counter();self.issues=Counter()
    def add(self,row,weight,channels):
        self.all.add(weight);category=row['category'];pair=','.join(map(str,row['signed_root_pair'])) or 'no_root'
        self.categories[category].add(weight);self.pairs[pair].add(weight);self.issues.update(row['topology_issues'])
        self.reco_origins.update((l['flavour']+':'+l['origin']) for l in row['reco_particles'])
        for channel in channels:
            target=self.channels[channel];target['total'].add(weight);target['categories'][category].add(weight);target['pairs'][pair].add(weight)
            for name,value in row['overlays'].items():
                if value:target['overlays'][name].add(weight)
    def result(self):
        render=lambda x:x.result(self.lumi)
        total=render(self.all);cats={k:render(v) for k,v in self.categories.items()};channels=[]
        for name,data in self.channels.items():
            full=render(data['total']);categories={k:render(v) for k,v in data['categories'].items()}
            pairs={k:render(v) for k,v in data['pairs'].items()}
            for parts in (categories,pairs):
                if sum(x['count'] for x in parts.values())!=full['count'] or any(not close(math.fsum(x[key] for x in parts.values()),full[key]) for key in ('sumw_pb','sumw2_pb2')):raise ValueError('category/pair channel moment closure failed')
            channels.append({'channel':name,'mapping':self.mapping[name],'total':full,'categories':categories,'signed_pairs':pairs,
                'category_fractions':{k:subset_fraction(v,full) for k,v in categories.items()},
                'overlapping_reco_origin_event_subsets':{k:{'moments':render(v),'fraction':subset_fraction(render(v),full)} for k,v in data['overlays'].items()},
                'relative_to_original_generated_weight':subset_fraction(full,total)})
        return {'input_events':total['count'],'contract':self.contract,'all_events':total,'categories':cats,'signed_pairs':{k:render(v) for k,v in self.pairs.items()},
            'topology_issue_counts':dict(self.issues),'reco_lepton_origin_counts':dict(self.reco_origins),'channels':channels,
            'category_attribution_status':'unresolved_selected_topology' if any(c['categories'][self.contract['unresolved_category']]['count'] for c in channels) else 'complete_within_stored_ancestry',
            'physics_certified':False}


def decompose(events,native_rows,trace_rows,arrays,mapping,*,lumi,scale,expected_events,on_event=None,contract=None):
    native,traces,channels=prepare_join(native_rows,trace_rows,arrays,mapping,contract=contract)
    if type(expected_events) is not int or expected_events<1 or len(native)!=expected_events:raise ValueError('original generated exposure differs from native population')
    scale=truth.finite(scale,'raw to normalized weight scale')
    if scale<=0:raise ValueError('positive raw-to-normalized scale required')
    summary=OriginSummary(mapping,lumi,contract);seen=set()
    for event in events:
        key=event.get('event_number')
        try:
            truth.integer(key,'Delphes Event')
            if key in seen or key not in native:raise ValueError('duplicate or absent Delphes Event')
            if not close(native[key]['weight_pb'],truth.finite(event['weight'],'raw weight')*scale,tolerance=2e-5):raise ValueError('Delphes/converted original weight differs')
            row=analyze_origin(event,contract=contract);seen.add(key);row.update(weight_pb=native[key]['weight_pb'],model_channels=channels[key])
            summary.add(row,native[key]['weight_pb'],channels[key])
            if on_event:on_event(row)
        except (ValueError,KeyError,TypeError) as exc:
            raise ValueError(f'event {key!r}: {exc}') from exc
    if seen!=set(native):raise ValueError('missing Delphes events from complete denominator')
    return summary.result()


def validate_model_moments(result,metadata,background,patch):
    import jsonpatch
    if metadata['additional_scale']!=1 or metadata['acceptance_certified']:
        raise ValueError('original-exposure diagnostic model required')
    records={x['channel']:x for x in metadata['channels']}
    if len(records)!=len(metadata['channels']) or set(records)!={x['channel'] for x in result['channels']}:raise ValueError('model metadata channel denominator')
    spec=jsonpatch.apply_patch(background,patch,in_place=False)
    if [x['name'] for x in spec['channels']]!=[x['channel'] for x in result['channels']]:raise ValueError('workspace order/denominator changed')
    for row,channel in zip(result['channels'],spec['channels']):
        record=records[row['channel']];moment=row['total']
        if record['mapping']!=row['mapping']:raise ValueError('signal mapping differs')
        for name,key in [('sumw','sumw_pb'),('sumw2','sumw2_pb2'),('nominal_yield','yield'),('mc_stat_error','mc_error')]:
            if not close(record[name],moment[key]):raise ValueError('signal metadata moment closure failed')
        if record['nonzero_weights']!=moment['nonzero_weights'] or record['negative_weights']!=moment['negative_weights']:raise ValueError('signal metadata selected/sign count differs')
        samples=[s for s in channel['samples'] if s['name']==metadata['sample']]
        if len(samples)!=1 or len(samples[0]['data'])!=1 or not close(samples[0]['data'][0],moment['yield']):raise ValueError('patch nominal yield closure failed')
        error_mod=[m for m in samples[0]['modifiers'] if m['type'] in ('shapesys','staterror')]
        if error_mod and (len(error_mod)!=1 or len(error_mod[0]['data'])!=1 or not close(error_mod[0]['data'][0],moment['mc_error'])):raise ValueError('patch absolute MC error closure failed')
        expected_type=metadata['mc_stat_policy']
        if expected_type not in ('none','shapesys','staterror'):raise ValueError('unsupported signal MC policy')
        if expected_type!='none' and moment['sumw2_pb2']>0:
            if len(error_mod)!=1 or error_mod[0]['type']!=expected_type or error_mod[0]['name']!=record['mc_stat_modifier']:raise ValueError('patch omits declared signal MC constraint')
        elif error_mod:raise ValueError('patch introduces unsupported MC constraint')


def lhe_rows(lines):
    """Separate exactly NUP particle rows from explicitly supported weight XML.

    Auxiliary weights are recognized and left unapplied. They never repair a
    contradictory nominal particle population or supply a theory nuisance.
    """
    if not lines:raise ValueError('empty LHE event')
    header=lines[0].split()
    if len(header)!=6:raise ValueError('LHE event header needs six fields')
    n=int(header[0]);int(header[1])
    for value in header[2:]:truth.finite(float(value),'LHE event header')
    if n<1 or len(lines)<n+1:raise ValueError('LHE particle count mismatch')
    particles=[line.split() for line in lines[1:n+1]]
    if any(len(row)!=13 for row in particles):raise ValueError('LHE particle count/record mismatch')
    footer='\n'.join(lines[n+1:]);metadata=[]
    if footer:
        try:root=ET.fromstring('<metadata>'+footer+'</metadata>')
        except ET.ParseError as exc:raise ValueError('LHE extra particle records or malformed auxiliary metadata') from exc
        if root.text and root.text.strip():raise ValueError('LHE particle count mismatch: extra records')
        for block in root:
            if block.tail and block.tail.strip():raise ValueError('LHE particle count mismatch: extra records')
            if block.tag=='rwgt':
                if block.attrib or (block.text and block.text.strip()):raise ValueError('invalid LHE rwgt metadata')
                ids=set()
                for weight in block:
                    if weight.tag!='wgt' or set(weight.attrib)!={'id'} or not weight.attrib['id'].strip() or len(weight):raise ValueError('invalid LHE wgt metadata')
                    if weight.attrib['id'] in ids:raise ValueError('duplicate LHE auxiliary weight id')
                    if weight.tail and weight.tail.strip():raise ValueError('extra records inside LHE rwgt metadata')
                    truth.finite(float(weight.text or ''),'LHE auxiliary weight');ids.add(weight.attrib['id'])
                if not ids:raise ValueError('empty LHE rwgt metadata')
                metadata.append(('rwgt',tuple(sorted(ids))))
            elif block.tag=='weights' and not block.attrib and not len(block):
                values=(block.text or '').split()
                if not values:raise ValueError('empty LHE weights metadata')
                for value in values:truth.finite(float(value),'LHE auxiliary weight')
                metadata.append(('weights',len(values)))
            else:raise ValueError('unsupported LHE auxiliary metadata: '+block.tag)
        if len({item[0] for item in metadata})!=len(metadata):raise ValueError('duplicate LHE auxiliary weight block')
    return header,particles,metadata


def lhe_inventory(path,*,expected_events,applied_cross_section_pb,contract=None):
    contract=origin_contract(contract);categories=[r["id"] for r in contract["categories"]]
    """Separate LHE production inventory; never infer a Delphes identity by index."""
    opener=gzip.open if str(path).endswith('.gz') else open
    records=[];rows=None;closed=False;auxiliary=Counter();weight_ids=Counter()
    with opener(path,'rt') as stream:
        for raw in stream:
            line=raw.split('#',1)[0].strip()
            if line=='<event>':
                if rows is not None:raise ValueError('nested LHE event')
                rows=[]
            elif line=='</event>':
                if not rows:raise ValueError('empty LHE event')
                header,particle_rows,metadata=lhe_rows(rows)
                n=int(header[0]);weight=truth.finite(float(header[2]),'LHE weight');process=int(header[1])
                for kind,labels in metadata:
                    auxiliary[kind]+=1
                    if kind=='rwgt':weight_ids.update(labels)
                particles=[]
                for i,fields in enumerate(particle_rows):
                    pid,status,m1,m2=map(int,fields[:4])
                    if not 0<=m1<=m2<=n or (m1==0)!=(m2==0):raise ValueError('invalid LHE mother range')
                    for value in fields[6:13]:truth.finite(float(value),'LHE particle kinematics')
                    particles.append({'pid':pid,'status':status,'m1':m1,'m2':m2})
                pending=set(range(n));done=set()
                while pending:
                    ready={i for i in pending if {j-1 for j in range(particles[i]['m1'],particles[i]['m2']+1) if j}<=done}
                    if not ready:raise ValueError('cycle in LHE mother graph')
                    pending-=ready;done|=ready
                roots=[p['pid'] for p in particles if selected_root(p['pid'],contract) and p['status'] in (1,2)
                    and not any(particles[m-1]['pid']==p['pid'] for m in range(p['m1'],p['m2']+1) if m)]
                category,issues=classify_pair(roots,contract=contract);records.append((weight,category,','.join(map(str,sorted(roots))) or 'no_root',process,issues));rows=None
            elif rows is not None and line:rows.append(line)
            elif line=='</LesHouchesEvents>':closed=True
    if rows is not None or not closed or len(records)!=expected_events:raise ValueError('LHE incomplete original generated population')
    raw_total=math.fsum(r[0] for r in records)
    if raw_total<=0:raise ValueError('LHE total weight cannot define positive exposure')
    scale=applied_cross_section_pb/raw_total;categories={k:Moments() for k in categories};pairs=defaultdict(Moments);processes=Counter()
    for weight,category,pair,process,_ in records:categories[category].add(weight*scale);pairs[pair].add(weight*scale);processes[str(process)]+=1
    return {'events':len(records),'raw_sumw':raw_total,'raw_sumw2':math.fsum(r[0]**2 for r in records),'applied_cross_section_pb':applied_cross_section_pb,
        'categories':{k:v.result(1) for k,v in categories.items()},'signed_pairs':{k:v.result(1) for k,v in pairs.items()},'subprocess_counts':dict(processes),
        'auxiliary_weights':{'recognized_blocks':dict(auxiliary),'rwgt_id_event_counts':dict(weight_ids),'policy':'validated XML metadata retained in pinned source; only original nominal weights applied'},
        'weight_basis':'original applied tagged rate / original raw LHE weight sum; yield field at 1 inverse pb',
        'event_join_to_delphes':'not_established; populations only, no entry-number identity inference'}


def run(plan_record,out):
    """Validate retained ancestors, write new diagnostic artifacts, never compute events."""
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    try:
        plan_path=pinned(plan_record,Path.cwd());plan=read_json(plan_path);rundir=Path(plan['rundir']).resolve()
        if plan_hash(plan)!=plan['plan_sha256'] or Path(plan['plan_path']).resolve()!=plan_path:raise ValueError('native plan integrity/location mismatch')
        config=plan.get('origin_accounting')
        if not isinstance(config,dict) or not {'contract','artifacts','mapping'}<=set(config):raise truth.ResponseInputError('supplied origin_accounting plan input required','missing_input')
        contract=origin_contract(config['contract'])
        receipts,stages,sources=historical_receipts(rundir,plan,terminal='sa2json')
        sources[str(plan_path)]=plan_record['sha256']
        for source in plan['sources']:pinned(source,rundir);sources[source['path']]=source['sha256']
        norm_path=Path(stages['normalization']['outputs'][0]);normalization=load_normalization(norm_path)
        n=plan['nevents']
        if normalization['generation']['n_events']!=n or normalization['kfactor']!=plan['kfactor']:raise ValueError('normalization plan exposure/correction mismatch')
        delphes=Path(stages['delphes']['outputs'][0]);native=Path(stages['analysis']['outputs'][0]);analysis=Path(stages['simpleanalysis']['outputs'][0])
        trace=rundir/config['artifacts']['trace'];metadata_path=rundir/config['artifacts']['metadata'];patch_path=rundir/config['artifacts']['patch'];background_path=Path(plan['inputs']['likelihood'])
        required=[norm_path,delphes,native,analysis,trace,metadata_path,patch_path,background_path]
        if any(str(path.resolve()) not in sources for path in required):raise ValueError('diagnostic input not owned by verified ancestor receipts')
        native_rows=truth.read_native_rows(native)
        traces,scale,deps,header=truth.validate_native_join(delphes,native,trace,native_rows=native_rows,join_contract=contract["join"]["trace"])
        conversion=read_json(str(native)+'.normalization.json')
        if not conversion.get('generation_reconciled') or not close(conversion['applied_cross_section_pb'],normalization['applied_cross_section_pb']):raise ValueError('conversion does not reconcile original generated rate')
        if not close(math.fsum(r['weight_pb'] for r in native_rows),normalization['applied_cross_section_pb'],tolerance=2e-5):raise ValueError('all-event normalized rate differs')
        for d in deps:sources[d['path']]=d['sha256']
        reader_modules={sys.modules[__name__],truth,*[inspect.getmodule(f) for f in (load_normalization,plan_hash,historical_receipts,read_json)]}
        from ravel.workflow import execution
        reader_modules.add(execution)
        for module in reader_modules:sources[str(Path(module.__file__).resolve())]=truth.fingerprint(module.__file__)['sha256']
        sources[str(Path(sys.executable).resolve())]=truth.fingerprint(sys.executable)['sha256']
        background=read_json(background_path);metadata=read_json(metadata_path);mapping=config['mapping']
        if set(mapping)!={row['name'] for row in background['channels']} or metadata['luminosity_pb_inverse']!=plan['luminosity_pb_inverse']:raise ValueError('complete supplied channel/luminosity contract required')
        arrays=scalar_arrays(analysis)
        with tempfile.TemporaryDirectory(prefix='.origin-',dir=out) as temporary:
            event_name='events.jsonl.gz' if contract['response']['output_format']=='jsonl.gz' else 'events.json'
            staged=Path(temporary)/event_name;opener=gzip.open if event_name.endswith('.gz') else open
            with opener(staged,'wt') as stream:
                header={'kind':'header','schema_version':1,'contract':contract,'scope':'Original-exposure production categories; stored TRefs do not identify native-selected objects'}
                stream.write(('[' if event_name.endswith('.json') else '')+json.dumps(header,allow_nan=False)+'\n')
                result=decompose(truth.delphes_events(delphes,contract=contract["response"]),native_rows,list(traces.values()),arrays,mapping,lumi=plan['luminosity_pb_inverse'],scale=scale,expected_events=n,contract=contract,on_event=lambda row:stream.write((',' if event_name.endswith('.json') else '')+json.dumps(row,allow_nan=False)+'\n'))
                if event_name.endswith('.json'):stream.write(']\n')
            validate_model_moments(result,metadata,background,read_json(patch_path))
            lhe=Path(normalization['sources'][0]['path'])
            generated=lhe_inventory(lhe,expected_events=n,applied_cross_section_pb=normalization['applied_cross_section_pb'],contract=contract)
            for path,sha in sources.items():
                if truth.fingerprint(path)['sha256']!=sha:raise ValueError('source changed during diagnostic: '+path)
            result.update(schema_version=1,status='complete_diagnostic',normalization=normalization,
                original_generated_events=n,luminosity_pb_inverse=plan['luminosity_pb_inverse'],lhe_population=generated,
                source_sha256=sources,producer_receipts=receipts,reader_runtime=truth.reader_runtime(),
                event_artifact={'path':event_name,'sha256':truth.fingerprint(staged)['sha256']},
                checks={'full_event_key_join':True,'original_weight_preserved':True,'all_supplied_channel_moments_match_metadata_and_patch':True,'category_and_pair_moment_closure':True,'source_bytes_preserved':True},
                scope={'primary':'selected event contribution by production origin at original supplied normalization; no selected-subset renormalization',
                       'reco_overlays':'overlapping subsets of selected events containing any raw reconstructed objects with declared ancestry; not individual native-selected-object attribution',
                       'ancestry':'stored M1/M2 endpoints may omit additional mothers; ambiguous ancestry/topologies preserved',
                       'lhe_join':'separate population inventory; no LHE-to-Delphes event identity asserted',
                       'uncertainty':'Poissonized independent-event weighted moments and shared-event ratio covariance; generator integration, K, detector/theory and calibration uncertainty separate',
                       'certification':'no acceptance, detector-efficiency, likelihood or coverage certificate'})
            staged_summary=Path(temporary)/'origin.json';staged_summary.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            (out/event_name).hardlink_to(staged)
            try:(out/'origin.json').hardlink_to(staged_summary)
            except BaseException:
                if (out/event_name).samefile(staged):(out/event_name).unlink()
                raise
        return result
    except (ValueError,KeyError,TypeError,OSError,ArithmeticError) as exc:
        with (out/'failure.json').open('x') as stream:json.dump({'status':'failed_diagnostic','complete_population':False,'error':str(exc),'physics_certified':False},stream,indent=2)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',required=True);parser.add_argument('--plan-sha256',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    try:
        result=run({'path':args.plan,'sha256':args.plan_sha256},args.out)
        print(json.dumps({'status':result['status'],'input_events':result['input_events'],'categories':{k:v['count'] for k,v in result['categories'].items()},'channels':len(result['channels']),'physics_certified':False}));return 0
    except (ValueError,KeyError,TypeError,OSError) as exc:print(str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
