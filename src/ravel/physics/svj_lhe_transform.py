"""Fixed source-declared SVJ particle/absolute-weight representation.

No generator/model import, shower, normalization fit or sampling law. Complete
raw and derived cohorts are separate, and every changed lexical span is retained.
"""
from decimal import Decimal
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from xml.parsers import expat

from . import model_event_weights as weights
from .model_event_weights import require

MAPPED = tuple(range(49001010, 49001015))
PRESENT = tuple(range(49001011, 49001015))
TARGET = 4900101
MAX_LITERAL = 512
MAX_DIGITS = 256
MAX_EXPONENT = 400
MAX_STRUCTURAL_BYTES = 32 * 1024**2
NUMERIC = re.compile(rb'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?\Z')


def pin(path):
    path = Path(path)
    weights.regular_stream(path)
    return {'path': str(path.absolute()), 'sha256': weights.raw_hash(path),
            'size': path.stat().st_size}


def scaled_token(token, n):
    """Exact coefficient multiplication, independent of Decimal context."""
    require(type(n) is int and 1 <= n <= 1000000, 'complete bounded hard N required')
    require(type(token) is bytes and len(token) <= MAX_LITERAL and NUMERIC.fullmatch(token),
            'bounded literal weight token required')
    value = Decimal(token.decode('ascii').replace('D', 'E').replace('d', 'e'))
    sign, digits, exponent = value.as_tuple()
    require(value.is_finite() and len(digits) <= MAX_DIGITS and abs(exponent) <= MAX_EXPONENT,
            'weight exceeds exact finite representation domain')
    if value == 0:
        return token  # Preserve literal signed zero and its spelling.
    coefficient = int(''.join(map(str, digits))) * n
    result = Decimal((sign, tuple(map(int, str(coefficient))), exponent))
    native = float(result)
    require(math.isfinite(native) and native != 0,
            'scaled nonzero weight is not finite/nonzero in the native double range')
    encoded = str(result).encode('ascii')
    if token.startswith(b'+'):
        encoded = b'+' + encoded
    require(len(encoded) <= MAX_LITERAL, 'scaled weight token exceeds finite bound')
    return encoded


def _tag_end(raw, start):
    quote = None
    for i in range(start, len(raw)):
        c = raw[i]
        if quote is not None:
            if c == quote: quote = None
        elif c in (34, 39): quote = c
        elif c == 62: return i + 1
    raise ValueError('incomplete literal XML tag')


def _rows(raw, offset=0):
    """Exact byte spans of scalar rows; comments are never scalar fields."""
    masked = bytearray(raw)
    for match in re.finditer(rb'<!--.*?-->', raw, re.S):
        for i in range(match.start(), match.end()):
            if masked[i] not in (10, 13): masked[i] = 32
    require(b'<' not in masked and b'>' not in masked and b'&' not in masked,
            'literal scalar text required; escaped/CDATA scalar representation unsupported')
    result = []
    cursor = 0
    for line in bytes(masked).splitlines(keepends=True):
        content = line.split(b'#', 1)[0]
        tokens = [(offset + cursor + m.start(), offset + cursor + m.end(),
                   raw[cursor + m.start():cursor + m.end()])
                  for m in re.finditer(rb'\S+', content)]
        if tokens: result.append(tokens)
        cursor += len(line)
    return result


def _elements(raw):
    parser = expat.ParserCreate()
    rows, stack = [], []
    def start(name, attrs):
        index = parser.CurrentByteIndex
        row = {'name': name, 'attributes': attrs, 'start': index,
               'content': _tag_end(raw, index), 'parent': stack[-1]['name'] if stack else None}
        rows.append(row); stack.append(row)
    def end(name):
        row = stack.pop()
        require(row['name'] == name, 'complete XML element framing required')
        row['end_content'] = parser.CurrentByteIndex
        row['end'] = _tag_end(raw, row['end_content'])
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.ExternalEntityRefHandler = lambda *args: 0
    parser.Parse(raw, True)
    require(not stack, 'complete event XML required')
    return rows


def _event_changes(raw, n, ids, ordinal):
    elements = _elements(raw)
    event = elements[0]
    require(event['name'] == 'event', 'exact event block required')
    first = min((x['start'] for x in elements[1:] if x['parent'] == 'event'),
                default=event['end_content'])
    rows = _rows(raw[event['content']:first], event['content'])
    require(rows and len(rows[0]) == 6, 'complete six-field event header required')
    nup = int(rows[0][0][2])
    require(nup > 0 and len(rows) == nup + 1 and all(len(x) == 13 for x in rows[1:]),
            'complete NUP particle-record population required')
    changes = []
    a, b, old = rows[0][2]
    changes.append((a, b, old, scaled_token(old, n), 'XWGTUP', ordinal, None))
    for particle, row in enumerate(rows[1:]):
        a, b, old = row[0]; pdg = int(old)
        if abs(pdg) in MAPPED:
            require(abs(pdg) in PRESENT, 'mapped PDG absent from authenticated original model')
            new = (b'-' if pdg < 0 else b'+' if old.startswith(b'+') else b'') + str(TARGET).encode()
            changes.append((a, b, old, new, 'IDUP', ordinal, particle))
    explicit = [x for x in elements if x['name'] == 'rwgt' and x['parent'] == 'event']
    compact = [x for x in elements if x['name'] == 'weights' and x['parent'] == 'event']
    require(len(explicit) <= 1 and len(compact) <= 1, 'unique detailed/compact weight containers required')
    values, compressed = {}, []
    for x in elements:
        if x['name'] == 'wgt' and x['parent'] == 'rwgt':
            require(set(x['attributes']) == {'id'}, 'explicit original weight identity required')
            identity = x['attributes']['id']
            tokens = [t for row in _rows(raw[x['content']:x['end_content']], x['content']) for t in row]
            require(identity not in values and len(tokens) == 1, 'one literal scalar per unique detailed weight required')
            a, b, old = tokens[0]; values[identity] = weights.number(old.decode('ascii'))
            changes.append((a, b, old, scaled_token(old, n), 'detailed_weight', ordinal, identity))
    if explicit: require(set(values) == set(ids), 'complete detailed weight population required')
    if compact:
        x = compact[0]
        tokens = [t for row in _rows(raw[x['content']:x['end_content']], x['content']) for t in row]
        require(len(tokens) == len(ids), 'complete compact header join required')
        for identity, (a, b, old) in zip(ids, tokens):
            compressed.append(weights.number(old.decode('ascii')))
            changes.append((a, b, old, scaled_token(old, n), 'compact_weight', ordinal, identity))
    require(bool(explicit or compact) or not ids, 'complete event weight payload required')
    if explicit and compact:
        require([values[i] for i in ids] == compressed, 'simultaneous detailed/compact weights differ')
    return sorted(changes)


def _init_changes(raw):
    element = _elements(raw)[0]
    rows = _rows(raw[element['content']:element['end_content']], element['content'])
    require(rows and len(rows[0]) == 10 and int(rows[0][8][2]) == -3,
            'original exact MG sum strategy -3 required')
    nproc = int(rows[0][9][2])
    require(nproc > 0 and len(rows) == nproc + 1 and all(len(x) == 4 for x in rows[1:]),
            'complete original init process population required')
    a, b, old = rows[0][8]
    return [(a, b, old, b'-4', 'IDWTUP', None, None)]


def _rewrite(source, destination, journal_path, *, n, ids, maximum_bytes, maximum_event_bytes):
    """Stream XML framing and publish only a pending complete derived artifact."""
    parser = expat.ParserCreate()
    buffer = bytearray(); base = 0; active = None; stack = []
    events = 0; inits = 0; output_bytes = 0; changed = 0
    unchanged_original = hashlib.sha256(); unchanged_derived = hashlib.sha256()
    opener = gzip.open if Path(source).suffix == '.gz' else open
    with opener(source, 'rb') as original, destination.open('xb') as encoded, \
            gzip.GzipFile(filename='', mode='wb', fileobj=encoded, mtime=0) as derived, \
            journal_path.open('x') as journal:
        reader = weights.BoundedReader(original, maximum_bytes)
        def emit(raw):
            nonlocal output_bytes
            output_bytes += len(raw)
            require(output_bytes <= maximum_bytes, 'derived decoded LHE exceeds declared full ceiling')
            derived.write(raw)
        def common(raw):
            unchanged_original.update(raw); unchanged_derived.update(raw); emit(raw)
        def flush(end, changes=None):
            nonlocal base, changed
            count = end - base
            require(0 <= count <= len(buffer), 'source-framed byte boundary required')
            raw = bytes(buffer[:count]); cursor = 0
            for a, b, old, new, role, ordinal, member in changes or []:
                require(cursor <= a < b <= len(raw) and raw[a:b] == old,
                        'ordered exact original token spans required')
                common(raw[cursor:a]); offset_out = output_bytes; emit(new)
                journal.write(json.dumps({'input_offset':base+a,'output_offset':offset_out,
                    'original_hex':old.hex(),'derived_hex':new.hex(),'role':role,
                    'event_ordinal':ordinal,'member':member},allow_nan=False)+'\n')
                cursor = b; changed += 1
            common(raw[cursor:]); del buffer[:count]; base = end
        def start(name, attrs):
            nonlocal active
            index = parser.CurrentByteIndex
            parent = stack[-1] if stack else None
            if not stack: require(name == 'LesHouchesEvents', 'LHE root required')
            if name in ('event', 'init'):
                require(parent == 'LesHouchesEvents' and active is None,
                        'one direct original event/init block required')
                flush(index); active = name
            stack.append(name)
        def end(name):
            nonlocal active, events, inits
            require(stack and stack.pop() == name, 'complete original XML population required')
            if name == active:
                end_index = parser.CurrentByteIndex - base
                end_offset = base + _tag_end(buffer, end_index)
                raw = bytes(buffer[:end_offset-base])
                if name == 'event':
                    require(len(raw) <= maximum_event_bytes, 'individual event exceeds explicit byte ceiling')
                    changes = _event_changes(raw, n, ids, events); events += 1
                    require(events <= n, 'hard population exceeds full original N')
                else:
                    changes = _init_changes(raw); inits += 1
                    require(inits == 1 and events == 0, 'one original init before all events required')
                flush(end_offset, changes); active = None
        parser.StartElementHandler = start; parser.EndElementHandler = end
        parser.ExternalEntityRefHandler = lambda *args: 0
        while True:
            block = reader.read(65536)
            if not block: break
            buffer.extend(block); parser.Parse(block, False)
            if active == 'event':
                require(len(buffer) <= maximum_event_bytes + 65536, 'individual event exceeds explicit byte ceiling')
            elif active == 'init':
                require(len(buffer) <= MAX_STRUCTURAL_BYTES, 'original init exceeds structural byte ceiling')
            else:
                flush(parser.CurrentByteIndex)
                require(len(buffer) <= MAX_STRUCTURAL_BYTES, 'unparsed XML exceeds structural byte ceiling')
        parser.Parse(b'', True)
        require(not stack and active is None and events == n and inits == 1,
                'complete hard cohort and EOF required before transform acceptance')
        flush(base + len(buffer))
        journal.flush(); os.fsync(journal.fileno())
    return {'events':events,'operation_rows':changed,'original_decoded_sha256':reader.digest.hexdigest(),
            'original_decoded_bytes':reader.size,'derived_decoded_bytes':output_bytes,
            'unchanged_original_sha256':unchanged_original.hexdigest(),
            'unchanged_derived_sha256':unchanged_derived.hexdigest()}


def transform(source, output_dir, *, expected_events, expected_groups, maximum_bytes,
              maximum_event_bytes, require_detailed=False):
    """Retain raw bytes, prove complete transport, then expose derived evidence.

    Failures retain raw/pending diagnostic artifacts and never publish receipt or
    accepted derived endpoint. Only an admitted native worker may install it.
    """
    require(type(maximum_event_bytes) is int and 1 <= maximum_event_bytes <= 8*1024**2,
            'explicit bounded individual event bytes required')
    require(type(require_detailed) is bool, 'explicit native detailed-consumption flag required')
    source = Path(source).absolute(); before = pin(source); identity = weights.regular_stream(source)
    out = Path(output_dir).absolute()
    require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),
            'fresh regular transformation destination required')
    require(not source.is_relative_to(out), 'transform destination cannot contain original stream')
    out.mkdir(parents=True)
    raw = out/('raw-hard.lhe.gz' if source.suffix == '.gz' else 'raw-hard.lhe')
    with source.open('rb') as inp, raw.open('xb') as retained:
        shutil.copyfileobj(inp, retained, 65536)
    require(pin(source) == before and weights.regular_stream(source) == identity and
            pin(raw)['sha256'] == before['sha256'], 'raw hard input changed during retention')
    ids = [i for g in expected_groups for i in g['ids']]
    pending = out/'derived.lhe.gz.pending'; journal = out/'changes.jsonl.pending'
    witness = _rewrite(raw,pending,journal,n=expected_events,ids=ids,maximum_bytes=maximum_bytes,
                       maximum_event_bytes=maximum_event_bytes)
    original = weights.scan(raw,expected_events=expected_events,expected_groups=expected_groups,
        maximum_bytes=maximum_bytes,journal_path=out/'original-event-weights.jsonl',allow_equal_encodings=True)
    require(original['init']['idwtup'] == -3, 'raw hard cohort is not source-declared MG sum strategy')
    if require_detailed and ids:
        require(original['weight_encodings']['compact_only'] == 0,
                'selected released interface requires complete detailed weights; compact-only input is not a detailed native map')
    # Pending suffix is intentionally not used as a gzip selector by scan.
    provisional = out/'derived-check.lhe.gz'
    os.replace(pending, provisional)
    try:
        derived = weights.scan(provisional,expected_events=expected_events,expected_groups=expected_groups,
            maximum_bytes=maximum_bytes,journal_path=out/'derived-event-weights.jsonl',allow_equal_encodings=True)
        require(derived['init'] == dict(original['init'],idwtup=-4) and
                derived['groups'] == original['groups'] and
                derived['native_weight_header_definitions'] == original['native_weight_header_definitions'],
                'original complete init/weight identity changed beyond declared strategy')
        require(witness['original_decoded_sha256'] == original['decoded_sha256'] and
                witness['derived_decoded_bytes'] == derived['decoded_bytes'], 'source/derived byte witnesses differ')
        require(pin(source) == before and weights.regular_stream(source) == identity,
                'original hard input changed before publication')
        target = out/'derived-shower.lhe.gz'; changes = out/'changes.jsonl'
        result = {'schema_version':1,'mode':'svj_dark_flavour_absolute_v1','source_origin':before,
            'raw_hard':pin(raw),'derived_shower_input':pin(provisional),'change_journal':pin(journal),
            'evidence_files':[pin(out/x) for x in ['original-event-weights.jsonl','derived-event-weights.jsonl']],
            'complete_original_N':expected_events,'maximum_decoded_bytes':maximum_bytes,
            'maximum_event_bytes':maximum_event_bytes,'particle_map':{'absolute_sources':list(MAPPED),'absolute_target':TARGET,'preserve_sign':True},
            'normalization':'every original nominal/detailed/compact value times complete N; -3 to -4',
            'original_population':original,'derived_shower_input_population':derived,'byte_witness':witness,
            'physical_hard_to_shower_association':'unknown','scientific_acceptance':False,'native_calls':0}
        verify(result)
        os.replace(provisional,target); os.replace(journal,changes)
        result['derived_shower_input']=pin(target);result['change_journal']=pin(changes)
        verify(result)
        receipt=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode('utf-8')
        pending_receipt=out/'transform.json.pending'
        with pending_receipt.open('xb') as f:f.write(receipt);f.flush();os.fsync(f.fileno())
        verify(result)
        require(pending_receipt.read_bytes()==receipt,'transform receipt changed before publication')
        os.replace(pending_receipt,out/'transform.json')
        verify(result)
        require((out/'transform.json').read_bytes()==receipt,'transform receipt changed at ending')
        return result
    except Exception:
        for name in ('derived-check.lhe.gz','derived-shower.lhe.gz','transform.json'):
            if (out/name).exists(): os.replace(out/name,out/('failed-'+name))
        raise


def verify(result):
    """Authenticate every lexical edit by replay, including all unchanged bytes."""
    pins = [result['raw_hard'],result['derived_shower_input'],result['change_journal'],*result['evidence_files']]
    require(all(pin(x['path']) == x for x in pins), 'retained transform evidence changed')
    a, b = Path(result['raw_hard']['path']), Path(result['derived_shower_input']['path'])
    opener = gzip.open if a.suffix == '.gz' else open
    h1 = hashlib.sha256(); h2 = hashlib.sha256(); cursor = 0; output = 0; count = 0
    with opener(a,'rb') as original, gzip.open(b,'rb') as derived, Path(result['change_journal']['path']).open() as journal:
        r1 = weights.BoundedReader(original,result['maximum_decoded_bytes'])
        r2 = weights.BoundedReader(derived,result['maximum_decoded_bytes'])
        def exact(reader,n):
            chunks=[]
            while n:
                block=reader.read(min(n,65536)); require(block,'complete declared lexical span required')
                chunks.append(block);n-=len(block)
            return b''.join(chunks)
        def common(n):
            nonlocal cursor,output
            while n:
                amount=min(n,65536);x=exact(r1,amount);y=exact(r2,amount)
                require(x == y, 'unapproved non-token bytes changed')
                h1.update(x);h2.update(y);cursor+=amount;output+=amount;n-=amount
        for line in journal:
            require(len(line) <= 4096, 'bounded change row required')
            row=json.loads(line)
            require(type(row['input_offset']) is int and row['input_offset'] >= cursor,
                    'ordered nonoverlapping source token journal required')
            common(row['input_offset']-cursor)
            old=bytes.fromhex(row['original_hex']);new=bytes.fromhex(row['derived_hex'])
            require(len(old) <= MAX_LITERAL and len(new) <= MAX_LITERAL and row['output_offset'] == output,
                    'bounded original/derived token join required')
            require(exact(r1,len(old)) == old and exact(r2,len(new)) == new, 'changed token differs from its exact witness')
            cursor+=len(old);output+=len(new);count+=1
        while True:
            x=r1.read(65536)
            if not x: break
            y=exact(r2,len(x));require(x==y,'unapproved trailing bytes changed');h1.update(x);h2.update(y)
        require(not r2.read(1),'extra derived byte population')
    witness=result['byte_witness']
    require(count == witness['operation_rows'] and h1.hexdigest() == witness['unchanged_original_sha256'] and
            h2.hexdigest() == witness['unchanged_derived_sha256'] and
            r1.digest.hexdigest() == witness['original_decoded_sha256'] and
            r2.digest.hexdigest() == result['derived_shower_input_population']['decoded_sha256'],
            'complete inverse/unchanged byte witness differs')
    require(all(pin(x['path']) == x for x in pins), 'transform evidence changed during replay')
    return True
