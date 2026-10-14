"""Bounded source-only Asciiv3 to legacy IO_GenEvent conversion and readback.

No HepMC/ROOT/Delphes import. Producer header is retained independently of wire
grammar. Original attributes are retained in a sidecar; unsupported metadata is
explicitly absent from the legacy stream. No full-metadata losslessness claim.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, localcontext
import gzip
import hashlib
import json
from pathlib import Path
import re

MAX_BYTES=128*1024*1024

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as s:
        for b in iter(lambda:s.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def number(text):
    x=Decimal(text)
    if not x.is_finite():raise ValueError('nonfinite event number')
    with localcontext() as c:
        c.prec=max(100,len(text)*2)
        return str(x.normalize())

def _particle(f):
    if len(f)!=10:raise ValueError('complete Asciiv3 particle record required')
    p={'id':int(f[1]),'production':int(f[2]),'pdg':int(f[3]),'p4':f[4:8],'mass':f[8],'status':int(f[9])}
    if p['id']<=0:raise ValueError('positive unique particle ID required')
    for n in p['p4']+[p['mass']]:number(n)
    return p

def _graph(e):
    # GenVertex::position() bypasses ancestor recursion when the source cycles
    # flag is1. With default event position, unset vertices then have zero
    # position, matching the literal geometry given to DelphesHepMC2Reader.
    # Other source position/ancestry conventions need a distinct conversion.
    if _attrs(e).get((0,'cycles'))!='1':
        raise ValueError('first retained conversion requires explicit cycles1/default event-position semantics')
    ps=e['particles']; vertices=e['vertices']; outgoing=defaultdict(list)
    for p in ps.values():
        if p['production']>0:
            key=('implicit',p['production'])
            if p['production'] not in ps:raise ValueError('missing implicit parent particle')
            vertices.setdefault(key,{'status':0,'position':['0']*4,'incoming':[p['production']]})
        elif p['production']<0:key=('explicit',p['production'])
        else:continue
        if key not in vertices:raise ValueError('missing explicit production vertex')
        outgoing[key].append(p['id'])
    ends={}
    for key,v in vertices.items():
        v['outgoing']=sorted(outgoing[key])
        if len(v['incoming'])!=len(set(v['incoming'])):raise ValueError('duplicate incoming edge')
        for pid in v['incoming']:
            if pid not in ps or pid in ends:raise ValueError('missing particle or multiple end vertices')
            ends[pid]=key
    if len(vertices)!=e['declared_vertices']:raise ValueError('Asciiv3 declared vertex count differs')
    if len(ps)!=e['declared_particles']:raise ValueError('Asciiv3 declared particle count differs')
    if any(p['production']==0 and p['id'] not in ends for p in ps.values()):
        raise ValueError('isolated particle cannot be encoded without adding a vertex')
    beams=sorted(p['id'] for p in ps.values() if p['status']==4)
    if len(beams)!=2:raise ValueError('first retained route requires two explicit status4 beam records')
    e['beams']=beams;e['ends']=ends
    if e.get('units')!=['GEV','MM']:raise ValueError('first retained route requires explicit GEV MM units')
    if len(e.get('weights',[]))!=1:raise ValueError('exactly one explicit retained weight required')
    number(e['weights'][0])
    return e

def read_prefix(path,count):
    if type(count) is not int or not 1<=count<=1000:raise ValueError('bounded1..1000event selection required')
    op=gzip.open if str(path).endswith('.gz') else open
    events=[]; e=None; header=[]; raw=[]; total=0; seen_ids=set(); first=True
    with op(path,'rt') as s:
        for line in s:
            total+=len(line.encode())
            if total>MAX_BYTES:raise ValueError('source decompression/selection ceiling exceeded')
            f=line.split()
            if f and f[0]=='E':
                if e is not None:
                    events.append(_graph(e))
                    if len(events)==count:break
                if len(f)!=4:raise ValueError('complete Asciiv3 E record required')
                e={'event':int(f[1]),'declared_vertices':int(f[2]),'declared_particles':int(f[3]),
                   'particles':{},'vertices':{},'attributes':[]}
                if e['event'] in seen_ids:raise ValueError('duplicate event ID')
                seen_ids.add(e['event'])
            raw.append(line)
            if not f:continue
            if e is None:
                header.append(line.rstrip())
                if first:
                    if len(f)!=2 or f[0]!='HepMC::Version' or not f[1].startswith('3.'):
                        raise ValueError('explicit producerVersion3 required')
                    first=False
                elif f[0] not in ('HepMC::Asciiv3-START_EVENT_LISTING','W','T','A'):
                    raise ValueError('unsupported run header')
            elif f[0]=='E':pass
            elif f[0]=='P':
                p=_particle(f)
                if p['id']!=len(e['particles'])+1 or p['production']>0 and p['production'] not in e['particles']:
                    raise ValueError('ReaderAscii consecutive particle IDs/earlier positive mother required')
                if p['id'] in e['particles']:raise ValueError('duplicate particle ID')
                e['particles'][p['id']]=p
            elif f[0]=='V':
                m=re.fullmatch(r'V\s+(-\d+)\s+(-?\d+)\s+\[([^]]*)\](?:\s+@\s+(.+))?\s*',line)
                if not m:raise ValueError('unsupported complete Asciiv3 vertex record')
                key=('explicit',int(m[1]))
                if key in e['vertices']:raise ValueError('duplicate explicit vertex')
                position=m[4].split() if m[4] else ['0']*4
                if len(position)!=4:raise ValueError('complete vertex position required')
                for x in position:number(x)
                incoming=[int(x) for x in m[3].split(',')] if m[3] else []
                e['vertices'][key]={'status':int(m[2]),'position':position,'incoming':incoming}
            elif f[0]=='U':
                if 'units' in e or len(f)!=3:raise ValueError('duplicate/invalid units')
                e['units']=f[1:]
            elif f[0]=='W':
                if 'weights' in e:raise ValueError('duplicate event weights')
                e['weights']=f[1:]
            elif f[0]=='A':
                if len(f)<4:raise ValueError('incomplete attribute')
                key=(int(f[1]),f[2])
                if any((a['id'],a['name'])==key for a in e['attributes']):raise ValueError('duplicate attribute')
                e['attributes'].append({'id':key[0],'name':key[1],'value':' '.join(f[3:])})
            elif f[0]=='HepMC::Asciiv3-END_EVENT_LISTING':
                if e is not None:events.append(_graph(e));e=None
                break
            else:raise ValueError('unsupported Asciiv3 record')
        else:
            raise ValueError('source EOF before bounded complete event closure')
    if len(events)!=count or 'HepMC::Asciiv3-START_EVENT_LISTING' not in header:
        raise ValueError('requested complete prefix/framing unavailable')
    return header,events,''.join(raw)

def canonical(e):
    particles=[{'id':p['id'],'pdg':p['pdg'],'p4':[number(x) for x in p['p4']],
                'mass':number(p['mass']),'status':p['status']} for p in sorted(e['particles'].values(),key=lambda p:p['id'])]
    vertices=[{'incoming':sorted(v['incoming']),'outgoing':sorted(v['outgoing']),
       'position':[number(x) for x in v['position']],'status':v['status']} for v in e['vertices'].values()]
    vertices.sort(key=lambda v:json.dumps(v,sort_keys=True))
    return {'event':e['event'],'beams':e['beams'],'units':e['units'],
            'weights':[number(x) for x in e['weights']],'particles':particles,'vertices':vertices}

def _attrs(e):return {(a['id'],a['name']):a['value'] for a in e['attributes']}

def serialize(header,events):
    # Preserve the original producer label. The following listing and records
    # identify the actual legacy wire grammar; no HepMC2 library is claimed.
    lines=[header[0],'HepMC::IO_GenEvent-START_EVENT_LISTING']; losses=[]
    for e in events:
        a=_attrs(e); keys=sorted(e['vertices']); vids={k:-i-1 for i,k in enumerate(keys)}
        scalar=lambda k,default:a.get((0,k),default)
        values=[scalar('event_scale','-1'),scalar('alphaQCD','-1'),scalar('alphaQED','-1')]
        for x in values:number(x)
        process=int(scalar('signal_process_id','0')); mpi=int(scalar('mpi','-1'))
        if (0,'random_states') in a or any(k[1].startswith('random_states') for k in a):
            raise ValueError('random-state attribute conversion is outside this retained route')
        if (0,'signal_process_vertex') in a:raise ValueError('signal vertex attribute mapping requires explicit source-ID semantics')
        lines.append('E '+' '.join(map(str,[e['event'],mpi,*values,process,0,len(keys),*e['beams'],0,1,*e['weights']])))
        lines.append('U '+' '.join(e['units']))
        mapped={(0,k) for k in ('event_scale','alphaQCD','alphaQED','signal_process_id','mpi') if (0,k) in a}
        partial={}
        if (0,'GenCrossSection') in a:
            f=a[(0,'GenCrossSection')].split()
            if len(f)!=4:raise ValueError('source cross section shape requires explicit mapping')
            for x in f[:2]:number(x)
            lines.append('C '+' '.join(f[:2]));partial[(0,'GenCrossSection')]='legacyC carries first two values; accepted/attempted counts retained only in sidecar'
        if (0,'GenPdfInfo') in a:
            f=a[(0,'GenPdfInfo')].split()
            if len(f)!=9:raise ValueError('source PDF metadata shape requires explicit mapping')
            for x in f:number(x)
            lines.append('F '+' '.join(f));mapped.add((0,'GenPdfInfo'))
        for key in keys:
            v=e['vertices'][key]; orphan=[pid for pid in sorted(v['incoming']) if e['particles'][pid]['production']==0]
            lines.append('V '+' '.join(map(str,[vids[key],v['status'],*v['position'],len(orphan),len(v['outgoing']),0])))
            for pid in orphan+sorted(v['outgoing']):
                p=e['particles'][pid]; flow=[]
                for index in (1,2,3):
                    ak=(pid,'flow'+str(index))
                    if ak in a:flow += [index,int(a[ak])];mapped.add(ak)
                lines.append('P '+' '.join(map(str,[pid,p['pdg'],*p['p4'],p['mass'],p['status'],0,0,
                    vids.get(e['ends'].get(pid),0),len(flow)//2,*flow])))
        losses.append({'event':e['event'],'all_original_attributes':e['attributes'],
           'attribute_dispositions':[{'id':k[0],'name':k[1],
             'disposition':'encoded' if k in mapped else 'partially encoded' if k in partial else 'sidecar only',
             'detail':partial.get(k,'')} for k in sorted(a)],
           'required_wire_defaults':['absent polarization encoded0/0','absent signal vertex encoded0','absent random-state vector encodedempty'],
           'vertex_barcode_remap':[{'source_kind':k[0],'source_id':k[1],'legacy_id':vids[k]} for k in keys]})
    lines.append('HepMC::IO_GenEvent-END_EVENT_LISTING')
    return '\n'.join(lines)+'\n',losses

def read_legacy(path):
    events=[];e=None;v=None; started=False;ended=False
    for line in Path(path).read_text().splitlines():
        f=line.split()
        if not f:continue
        if ended:raise ValueError('trailing legacy records')
        if f[0]=='HepMC::Version':continue
        if f[0]=='HepMC::IO_GenEvent-START_EVENT_LISTING':
            if started:raise ValueError('duplicate listing')
            started=True;continue
        if f[0]=='HepMC::IO_GenEvent-END_EVENT_LISTING':ended=True;continue
        if not started:raise ValueError('legacy record before listing')
        if f[0]=='E':
            if e is not None:events.append(e)
            if int(f[11])!=0 or int(f[12])!=1 or len(f)!=14:raise ValueError('first route requires explicit single weight/no random states')
            e={'event':int(f[1]),'beams':[int(x) for x in f[9:11]],'weights':f[13:],'particles':{},'vertices':{},'ends':{},'declared_vertices':int(f[8])};v=None
        elif f[0]=='U':e['units']=f[1:]
        elif f[0]=='V':
            if len(f)!=10 or int(f[9])!=0:raise ValueError('unsupported legacy vertex weight format')
            vid=int(f[1]);v={'status':int(f[2]),'position':f[3:7],'incoming':[],'outgoing':[],'orphans':int(f[7]),'expected_out':int(f[8]),'seen':0}
            if vid in e['vertices']:raise ValueError('duplicate legacy vertex')
            e['vertices'][vid]=v
        elif f[0]=='P':
            if v is None or len(f)!=13+2*int(f[12]):raise ValueError('invalid legacy particle/flow record')
            pid=int(f[1]);prod=0 if v['seen']<v['orphans'] else vid
            if pid in e['particles']:raise ValueError('duplicate legacy particle')
            e['particles'][pid]={'id':pid,'pdg':int(f[2]),'p4':f[3:7],'mass':f[7],'status':int(f[8]),'production':prod}
            v['seen']+=1
            if prod:v['outgoing'].append(pid)
            end=int(f[11])
            if end:e['ends'][pid]=end
        elif f[0] not in ('C','F','N'):raise ValueError('unsupported legacy record')
    if not started or not ended or e is None:raise ValueError('complete legacy listing required')
    events.append(e)
    for e in events:
        if len(e['vertices'])!=e['declared_vertices']:raise ValueError('legacy vertex count changed')
        for pid,end in e['ends'].items():
            if end not in e['vertices']:raise ValueError('unresolved legacy end vertex')
            e['vertices'][end]['incoming'].append(pid)
        for v in e['vertices'].values():
            if v['seen']!=v['orphans']+v['expected_out']:raise ValueError('legacy particle listing count differs')
    return events

def convert(source,expected_sha,count,out):
    source=Path(source).resolve();out=Path(out).resolve()
    if sha(source)!=expected_sha:raise ValueError('original source hash differs')
    if out.exists():raise FileExistsError(out)
    header,events,raw=read_prefix(source,count);text,losses=serialize(header,events)
    out.mkdir(parents=True);event=out/'events.hepmc';event.write_text(text)
    try:
        roundtrip=read_legacy(event)
        if [canonical(e) for e in events]!=[canonical(e) for e in roundtrip]:raise ValueError('graph/units/weights/kinematic identity changed')
        prefix=out/'original-prefix.asciiv3';prefix.write_text(_closed_prefix(raw))
        side=out/'metadata-sidecar.json';side.write_text(json.dumps({'original_run_header':header,'events':losses},indent=2)+'\n')
        result={'schema_version':1,'kind':'retained-hepmc-legacy-conversion','source':{'path':str(source),'sha256':expected_sha},
          'original_prefix':{'path':str(prefix),'sha256':sha(prefix)},'event_output':{'path':str(event),'sha256':sha(event)},
          'metadata_sidecar':{'path':str(side),'sha256':sha(side)},'converter':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__)},
          'events':count,'event_ids':[e['event'] for e in events],
          'canonical': [canonical(e) for e in events],
          'producer_header':header[0],'wire_grammar':'HepMC2 IO_GenEvent',
          'invariants':['complete source particle census','graph incidence','exact numerical four-vectors/masses','status/PDG','units','beam IDs','one explicit weight per event'],
          'full_metadata_wire_lossless':False,'native_parse_observed':False,'physics_validated':False}
        (out/'conversion.json').write_text(json.dumps(result,indent=2)+'\n')
    except Exception:
        # Failed derivative retained for inspection, never promoted as valid.
        (out/'FAILED.txt').write_text('Conversion/roundtrip validation failed; no qualification authority.\n')
        raise
    return result

def verify_manifest(path):
    result=json.loads(Path(path).read_text())
    for name in ('source','original_prefix','event_output','metadata_sidecar','converter'):
        p=result[name]
        if sha(p['path'])!=p['sha256']:raise ValueError('conversion input/output/source changed: '+name)
    header,original,raw=read_prefix(result['source']['path'],result['events'])
    expected,losses=serialize(header,original)
    if Path(result['event_output']['path']).read_text()!=expected:
        raise ValueError('legacy derivative differs from exact source serialization')
    if Path(result['original_prefix']['path']).read_text()!=_closed_prefix(raw):
        raise ValueError('saved prefix differs from exact original source bytes')
    if json.loads(Path(result['metadata_sidecar']['path']).read_text())!={'original_run_header':header,'events':losses}:
        raise ValueError('metadata sidecar differs from exact source/loss inventory')
    before=[canonical(e) for e in original];after=[canonical(e) for e in read_legacy(result['event_output']['path'])]
    if before!=after or before!=result['canonical']:raise ValueError('conversion graph/kinematics/weights changed')
    if result['converter']['path']!=str(Path(__file__).resolve()):raise ValueError('different conversion source module')
    if result['full_metadata_wire_lossless'] is not False or result['native_parse_observed'] is not False or result['physics_validated'] is not False:
        raise ValueError('conversion receipt cannot claim native/scientific/full-metadata qualification')
    return result

def _closed_prefix(raw):
    return raw if raw.rstrip().endswith('HepMC::Asciiv3-END_EVENT_LISTING') else raw+'HepMC::Asciiv3-END_EVENT_LISTING\n'

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--events',type=int,required=True);p.add_argument('--out',required=True);a=p.parse_args(argv)
    convert(a.source,a.sha256,a.events,a.out);return 0

if __name__=='__main__':raise SystemExit(main())
