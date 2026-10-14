"""Complete signed LHE weight populations; no envelope or independence inference."""
from decimal import Decimal, localcontext
import gzip
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(token):
    value = Decimal(str(token).replace('D', 'E').replace('d', 'e'))
    require(value.is_finite(), 'nonfinite LHE number')
    return value


def raw_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(65536),b''):digest.update(block)
    return digest.hexdigest()


def identity(st):
    return st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns


def regular_stream(path):
    path=Path(path)
    require(not any(p.is_symlink() for p in (path,*path.parents)) and path.is_file(),'regular unaliased native stream required')
    return identity(path.stat())


class BoundedReader:
    """Limit total decoded bytes before XML consumption, including gzip expansion."""
    def __init__(self, stream, maximum):
        self.stream, self.maximum, self.size = stream, maximum, 0
        self.digest = hashlib.sha256()
        self.tail = b''

    def read(self, size=-1):
        size = min(65536, self.maximum - self.size + 1) if size < 0 else min(size, self.maximum - self.size + 1)
        raw = self.stream.read(size)
        self.size += len(raw)
        require(self.size <= self.maximum, 'decoded LHE exceeds declared byte ceiling')
        self.digest.update(raw)
        inspect=(self.tail+raw).upper();self.tail=raw[-16:]
        require(b'<!DOCTYPE' not in inspect and b'<!ENTITY' not in inspect, 'LHE external/entity declarations are forbidden')
        return raw


def scan(path, *, expected_events, expected_groups, maximum_bytes, journal_path, allow_equal_encodings=False):
    """Consume EOF, all named/compact weights, and the full original denominator.

    Decimal sums are transport diagnostics of the literal generator weights.
    They do not define an MC sampling law, luminosity normalization, covariance,
    scale/PDF envelope or coefficient expansion.
    """
    require(type(allow_equal_encodings) is bool, 'explicit equal-encoding source arm required')
    encodings = {'detailed_only':0,'compact_only':0,'both_equal':0,'none':0}
    require(type(expected_events) is int and expected_events > 0, 'positive generated exposure required')
    require(type(maximum_bytes) is int and maximum_bytes > 0, 'positive decoded byte bound required')
    ids = [i for g in expected_groups for i in g['ids']]
    require(len(ids) == len(set(ids)) and 'nominal' not in ids, 'duplicate or reserved nominal weight identity')
    path, journal_path = Path(path), Path(journal_path)
    require(not journal_path.exists(), 'fresh weight journal required')
    path_identity=regular_stream(path)
    raw_sha = raw_hash(path)
    opener = gzip.open if path.suffix == '.gz' else open
    counts = {'positive': 0, 'negative': 0, 'zero': 0}
    totals = {i: [Decimal(0), Decimal(0)] for i in ['nominal', *ids]}
    observed_groups, init, events, root = None, None, 0, None
    header_definitions=[]
    with opener(path, 'rb') as stream, journal_path.open('x') as journal, localcontext() as context:
        context.prec = 80
        reader = BoundedReader(stream, maximum_bytes)
        for action, node in ET.iterparse(reader, events=('start', 'end')):
            if root is None:
                require(action == 'start' and node.tag == 'LesHouchesEvents', 'LHE root framing required')
                root = node
            if action != 'end':
                continue
            if node.tag == 'initrwgt':
                require(observed_groups is None and events == 0, 'one weight header before events required')
                groups = []
                for group in node:
                    require(group.tag == 'weightgroup', 'ungrouped or unknown weight header')
                    group_ids = []
                    for weight in group:
                        require(weight.tag == 'weight' and 'id' in weight.attrib and set(weight.attrib) <= {'id','MUR','MUF','PDF','DYN_SCALE','ALPSFACT'}, 'explicit source-backed weight header required')
                        group_ids.append(weight.attrib['id'])
                        header_definitions.append({'id':weight.attrib['id'],'attributes':dict(weight.attrib),'description':''.join(weight.itertext()).strip(),
                                                   'canonical_header_xml':ET.tostring(weight,encoding='unicode')})
                    name = group.attrib.get('name', group.attrib.get('type'))
                    require(set(group.attrib) <= {'name', 'type', 'combine','weight_name_strategy'} and name, 'explicit weight group identity required')
                    require(group.attrib.get('weight_name_strategy') in (None,'includeIdInWeightName'),'unknown native weight naming strategy')
                    groups.append({'name': name, 'combine': group.attrib.get('combine'), 'ids': group_ids})
                require(groups == expected_groups, 'complete LHE weight-group census differs from declared population')
                observed_groups = groups
            elif node.tag == 'init':
                require(init is None and events == 0, 'one LHE init before events required')
                lines = [line.split('#', 1)[0].split() for line in (node.text or '').splitlines()]
                lines = [line for line in lines if line]
                require(lines and len(lines[0]) == 10, 'complete ten-field LHE init required')
                head = lines[0]
                nproc = int(head[9])
                require(nproc > 0 and len(lines) == nproc + 1 and all(len(line) == 4 for line in lines[1:]), 'complete init cross-section population required')
                init = {'beam_pdg': [int(x) for x in head[:2]], 'energy_gev': [str(number(x)) for x in head[2:4]],
                        'pdf_group': [int(x) for x in head[4:6]], 'pdf_set': [int(x) for x in head[6:8]],
                        'idwtup': int(head[8]), 'processes': [{'cross_section_pb': str(number(line[0])),
                        'error_pb': str(number(line[1])), 'max_weight': str(number(line[2])), 'process_id': int(line[3])} for line in lines[1:]]}
            elif node.tag == 'event':
                require(init is not None, 'events require initial-state normalization metadata')
                require(observed_groups is not None or not expected_groups, 'declared weights missing from header')
                lines = [line.split('#', 1)[0].split() for line in (node.text or '').splitlines()]
                lines = [line for line in lines if line]
                require(lines and len(lines[0]) == 6, 'complete event header required')
                nup = int(lines[0][0])
                require(nup > 0 and len(lines) == nup + 1 and all(len(line) == 13 for line in lines[1:]), 'complete particle population required')
                for line in lines[1:]:
                    for token in line[:6]:int(token)
                    for token in line[6:]:
                        number(token)
                nominal = number(lines[0][2])
                for token in lines[0][3:]: number(token)
                require(int(lines[0][1]) in {x['process_id'] for x in init['processes']},'event process id absent from init normalization')
                explicit = node.findall('rwgt')
                compact = node.findall('weights')
                require((len(explicit) <= 1 and len(compact) <= 1) if allow_equal_encodings else len(explicit) + len(compact) <= 1,
                        'ambiguous event weight representation')
                values = {}
                if explicit:
                    for weight in explicit[0]:
                        require(weight.tag == 'wgt' and set(weight.attrib) == {'id'}, 'named LHE weight required')
                        identity = weight.attrib['id']
                        require(identity not in values, 'duplicate event weight')
                        values[identity] = number(weight.text.strip())
                    require(set(values) == set(ids), 'event missing/extra named weights')
                elif compact:
                    tokens = (compact[0].text or '').split()
                    require(len(tokens) == len(ids), 'compact weight population differs from header')
                    values = dict(zip(ids, map(number, tokens)))
                if explicit and compact:
                    tokens = (compact[0].text or '').split()
                    require(len(tokens) == len(ids) and list(map(number,tokens)) == [values[i] for i in ids],
                            'simultaneous detailed/compact weight identity or values differ')
                if allow_equal_encodings:
                    encodings['both_equal' if explicit and compact else 'detailed_only' if explicit else 'compact_only' if compact else 'none'] += 1
                require(set(values) == set(ids), 'complete event weight population required')
                events += 1
                require(events <= expected_events, 'event exposure exceeds approval')
                counts['positive' if nominal > 0 else 'negative' if nominal < 0 else 'zero'] += 1
                for identity, value in {'nominal': nominal, **values}.items():
                    totals[identity][0] += value
                    totals[identity][1] += value * value
                row = {'ordinal': events - 1, 'nup': nup, 'process_id': int(lines[0][1]), 'nominal': str(nominal),
                       'weights': [{'id': i, 'value': str(values[i])} for i in ids],
                       'canonical_event_sha256': hashlib.sha256(ET.tostring(node)).hexdigest()}
                journal.write(json.dumps(row, allow_nan=False) + '\n'); journal.flush()
                node.clear(); root.clear()
        require(events == expected_events and init is not None, 'complete generated denominator was not returned')
    # A second raw hash prevents the parser from binding its observations to a replaced file.
    require(raw_hash(path) == raw_sha and regular_stream(path)==path_identity, 'raw LHE changed during complete population scan')
    return {**({'weight_encodings':encodings} if allow_equal_encodings else {}),
            'raw_sha256': raw_sha, 'decoded_sha256': reader.digest.hexdigest(), 'decoded_bytes': reader.size,
            'complete_eof': True, 'generated_events': events, 'signed_nominal_counts': counts, 'init': init,
            'groups': observed_groups or [], 'native_weight_header_definitions':header_definitions,
            'weight_moments': {i: {'sumw': str(v[0]), 'sumw2': str(v[1])} for i, v in totals.items()},
            'shared_original_event_groups': True, 'sampling_law': 'unknown', 'cross_variation_independence': False,
            'cross_section_normalization_applied': False, 'luminosity_normalization_applied': False,
            'scale_pdf_envelope_computed': False}


def scan_hepmc2_weights(path, *, names, minimum_events, maximum_events, maximum_bytes, journal_path,
                       beam_pdg=None, energy_gev=None):
    """Retain every actual shower weight using the existing HepMC2 E/N layout.

    See event_census.census's source-backed E/N decoder. This raw transport
    reader does not reuse its positive-cross-section/nonzero-normalization or
    conditional Gram assumptions. Original-LHE joins remain unknown unless a
    separately qualified observer supplies them.
    """
    import shlex
    require(names and len(set(names))==len(names),'complete unique shower weight names required')
    require(type(minimum_events) is int and type(maximum_events) is int and 0<minimum_events<=maximum_events,'declared positive shower denominator bounds required')
    require(type(maximum_bytes) is int and maximum_bytes>0,'declared shower decoded byte ceiling required')
    path=Path(path);path_identity=regular_stream(path);before=raw_hash(path)
    opener=gzip.open if path.suffix=='.gz' else open
    started=ended=False;current=None;observed_names=None;events=0;size=0
    def finish(stream):
        nonlocal current,events
        if current is None:return
        require(observed_names==names and len(current['weights'])==len(names),'complete named shower vector required')
        require(current['units'] in (('GEV','MM'),('GEV','CM'),('MEV','MM'),('MEV','CM')) and current['particles'],
                'shower events require explicit units and finite particles')
        require(len(set(current['beam_barcodes']))==2 and all(x in current['particles'] for x in current['beam_barcodes']),
                'shower event requires its complete two-beam particle population')
        if beam_pdg is not None:
            beams=[current['particles'][x] for x in current['beam_barcodes']];beams.sort(key=lambda x:-x['pz'])
            scale=Decimal('.001') if current['units'][0]=='MEV' else Decimal(1)
            for i,beam in enumerate(beams):
                require(beam['pdg']==beam_pdg[i] and abs(beam['energy']*scale-number(energy_gev[i]))<=max(Decimal('1e-6'),number(energy_gev[i])*Decimal('1e-7')),
                        'actual shower beam identity/energy differs from intended collider')
        events+=1;require(events<=maximum_events,'shower exposure exceeds declared budget')
        stream.write(json.dumps({'ordinal':events-1,'native_event_id':current['id'],
            'weights':[{'name':name,'value':value} for name,value in zip(names,current['weights'])],
            'original_lhe_ordinal':None},allow_nan=False)+'\n');stream.flush();current=None
    with opener(path,'rb') as source,Path(journal_path).open('x') as journal:
        while True:
            raw=source.readline(1024**2+1)
            if not raw:break
            size+=len(raw);require(len(raw)<=1024**2 and size<=maximum_bytes,'shower decoded byte/line ceiling exceeded')
            line=raw.decode('utf-8').strip()
            if not line:continue
            if 'START_EVENT_LISTING' in line:
                require(not started and 'IO_GenEvent' in line,'one actual HepMC2 stream required');started=True
            elif 'END_EVENT_LISTING' in line:
                require(started and not ended,'one shower end marker required');finish(journal);ended=True
            elif line.startswith('HepMC::Version'):pass
            else:
                require(started and not ended,'shower content outside complete framing')
                fields=line.split()
                if fields[0]=='E':
                    finish(journal);require(len(fields)>=13,'complete HepMC2 event header required')
                    random_count=int(fields[11]);require(random_count>=0,'nonnegative random-state count required')
                    offset=12+random_count;require(offset<len(fields),'complete random-state population required')
                    count=int(fields[offset]);values=fields[offset+1:]
                    require(count==len(names) and len(values)==count,'complete actual shower weight population required')
                    current={'id':int(fields[1]),'weights':[str(number(x)) for x in values],
                             'beam_barcodes':[int(fields[9]),int(fields[10])],'units':None,'particles':{}}
                elif fields[0]=='N':
                    require(current is not None,'shower names require an actual event header')
                    values=shlex.split(line);require(int(values[1])==len(values[2:]) and values[2:]==names,'actual shower names differ from declared population')
                    observed_names=values[2:]
                elif fields[0]=='U':
                    require(current is not None and current['units'] is None,'one shower units declaration per event required')
                    current['units']=tuple(fields[1:])
                elif fields[0]=='P':
                    require(current is not None and len(fields)>=9,'complete shower particle record required')
                    barcode=int(fields[1]);require(barcode not in current['particles'],'duplicate shower particle identifier')
                    values=[number(x) for x in fields[3:8]]
                    current['particles'][barcode]={'pdg':int(fields[2]),'pz':values[2],'energy':values[3],'status':int(fields[8])}
        require(started and ended and minimum_events<=events<=maximum_events,'complete shower event exposure required')
    require(raw_hash(path)==before and regular_stream(path)==path_identity,'shower stream changed during weight observation')
    return {'raw_sha256':before,'decoded_bytes':size,'format':'HepMC2','returned_events':events,
        'weight_names':names,'complete_framing':True,'all_weight_vectors_retained':True,
        'original_lhe_join_qualified':False,'sampling_law':'unknown','cross_variation_independence':False}
