"""Exact released LO operative-seed lifecycle; retained bytes, never RNG proof."""
from contextlib import contextmanager
import ast
import gzip
import hashlib
import os
from pathlib import Path
import re
import stat

from .model_event_weights import require

MODE = 'mg5_2_9_27_lo_operative_seed'
MAX_DOCUMENT = 2 * 1024**2
PRIMARY = {
    'madgraph/interface/madevent_interface.py': '0f59f5a9300985fabc5da3156e42a2c6dc080b632fb94a50016284354cd402d8',
    'madgraph/various/banner.py': '17b4b0ed0b13afa013a94e6715c47a4fb1552ee160347cd3b9db644fb89c4ee9',
}


def validate(contract):
    require(type(contract) is dict and set(contract) == {'schema_version','mode'}
            and type(contract['schema_version']) is int and contract['schema_version'] == 1
            and contract['mode'] == MODE, 'exact operative-seed observation contract required')
    return contract


def _identity(s):
    return s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns


def _directories(path):
    result=[]
    for parent in reversed(path.parents):
        s=parent.lstat()
        require(stat.S_ISDIR(s.st_mode), 'operative seed evidence cannot traverse an alias')
        result.append((str(parent),s.st_dev,s.st_ino,s.st_mode))
    return result


@contextmanager
def _file(path):
    path=Path(path).absolute();dirs=_directories(path);before=path.lstat()
    require(stat.S_ISREG(before.st_mode), 'ordinary operative seed evidence required')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    stream=None
    try:
        require(_identity(os.fstat(descriptor)) == _identity(before), 'seed evidence replaced before opening')
        stream=os.fdopen(descriptor,'rb');descriptor=None
        yield stream,path
        require(_identity(os.fstat(stream.fileno())) == _identity(before)
                == _identity(path.lstat()) and _directories(path) == dirs,
                'operative seed evidence changed during consumption')
    finally:
        if stream is not None:stream.close()
        if descriptor is not None:os.close(descriptor)


def _read(path,maximum=MAX_DOCUMENT):
    maximum=min(MAX_DOCUMENT,maximum)
    with _file(path) as (stream,p):
        require(os.fstat(stream.fileno()).st_size <= maximum, 'seed document exceeds current bounded ceiling')
        raw=stream.read(maximum+1)
        require(len(raw)<=maximum, 'seed document exceeds current bounded ceiling')
    return raw,{'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def source_inputs(mgroot):
    paths=[]
    version,_=_read(Path(mgroot)/'VERSION')
    require(re.search(rb'^version\s*=\s*2\.9\.27\s*$',version,re.M), 'operative seed targets released MG5 2.9.27')
    paths.append(Path(mgroot)/'VERSION')
    for name,digest in PRIMARY.items():
        _,pin=_read(Path(mgroot)/name)
        require(pin['sha256']==digest, 'operative seed native lifecycle source changed: '+name)
        paths.append(Path(mgroot)/name)
    return paths


def _header(raw, *, banner=False):
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'seed header external/entity declaration')
    require(raw.count(b'<header>')==1 and raw.count(b'</header>')==1,
            'one complete native LHE header required')
    end=raw.index(b'</header>')+len(b'</header>')
    prefix=raw[:end]
    require(re.match(rb'^<LesHouchesEvents version="3\.0">\s*<header>',prefix), 'exact native LHE3 banner framing required')
    if banner:
        require(raw[end:].strip()==b'</LesHouchesEvents>', 'native banner has foreign trailing payload')
    return prefix


def _section(header, name):
    raw=header.decode('utf-8')
    require(raw.count('<'+name+'>')==raw.count('</'+name+'>')==1, 'one complete '+name+' section required')
    found=re.findall('<'+name+r'>\s*(.*?)\s*</'+name+'>',raw,re.S)
    require(len(found)==1, 'one complete '+name+' section required')
    return found[0]+'\n'


def _configured_matches(rows, before, mgroot, label):
    """Use only source-declared str/list[str] writer semantics; retain every row."""
    from . import model_events as m
    raw,pin=_read(Path(mgroot)/'madgraph/various/banner.py')
    require(pin['sha256']==PRIMARY['madgraph/various/banner.py'], 'typed run-card source changed')
    module=ast.parse(raw.decode('utf-8'))
    cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='RunCardLO')
    setup=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='default_setup')
    strings=set();string_lists=set()
    for n in ast.walk(setup):
        if not (isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_param'
                and isinstance(n.func.value,ast.Name) and n.func.value.id=='self' and len(n.args)>=2):continue
        try:key,default=map(ast.literal_eval,n.args[:2])
        except (ValueError,TypeError):continue
        if type(default) is str:strings.add(key)
        if type(default) is list and default and all(type(x) is str for x in default):string_lists.add(key)
    transformations=[]
    def string(value):
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('\"',"'"):value=value[1:-1]
        return value
    for key,value in before.items():
        require(key in rows, label+' missing '+key)
        if key in strings:
            require(string(rows[key])==string(value),label+' differs at '+key)
        elif key in string_lists:
            try:original=ast.literal_eval(value);native=ast.literal_eval(rows[key])
            except (ValueError,SyntaxError) as exc:raise ValueError(label+' malformed source string list at '+key) from exc
            require(type(original) is list and type(native) is list
                    and all(type(x) is str for x in original+native),label+' typed string list required at '+key)
            # RunCard.write's exact str-list format is "['%s']" % join.
            # An empty original list consequently emits ['']; do not discard it.
            require(native==(original if original else ['']),label+' differs at '+key)
        else:m.matches(rows,{key:value},label,native_run_lists=True)
        if rows[key]!=value:transformations.append({'key':key,'supplied':value,'observed':rows[key],
            'basis':'exact_source_declared_string_writer' if key in strings|string_lists else 'existing_ordered_numeric_literal_comparison'})
    return transformations


def _lhe_header(path, maximum):
    require(type(maximum) is int and maximum>0, 'bounded decoded LHE required')
    with _file(path) as (source,p):
        endpoint={'path':str(p),'leaf':list(_identity(os.fstat(source.fileno()))),
                  'ancestors':[list(row) for row in _directories(p)]}
        encoded=hashlib.sha256();decoded=hashlib.sha256();encoded_size=0;decoded_size=0;prefix=b'';complete=False
        tail=b'';framing={b'<header>':0,b'</header>':0}
        class Raw:
            def read(self,size=-1):
                nonlocal encoded_size
                require(size>=0, 'bounded encoded LHE read required')
                raw=source.read(min(size,65536));encoded_size+=len(raw);encoded.update(raw)
                require(encoded_size<=maximum+65536, 'encoded LHE exceeds bounded source ceiling')
                return raw
        wrapper=Raw()
        stream=gzip.GzipFile(fileobj=wrapper,mode='rb') if p.suffix=='.gz' else wrapper
        try:
            while True:
                block=stream.read(min(65536,maximum-decoded_size+1))
                if not block:break
                decoded_size+=len(block);decoded.update(block)
                require(decoded_size<=maximum, 'decoded LHE exceeds declared ceiling')
                inspect=tail+block
                for token in framing:
                    start=0
                    while True:
                        index=inspect.find(token,start)
                        if index<0:break
                        if index+len(token)>len(tail):framing[token]+=1
                        start=index+1
                    require(framing[token]<=1,'duplicate embedded native header')
                tail=inspect[-16:]
                if not complete:
                    prefix+=block
                    end=prefix.find(b'</header>')
                    if end>=0:prefix=prefix[:end+len(b'</header>')];complete=True
                    require(len(prefix)<=MAX_DOCUMENT, 'embedded seed header exceeds 2MiB')
            require(complete and all(x==1 for x in framing.values()) and source.read(1)==b'', 'complete bounded LHE EOF required')
        finally:
            if stream is not wrapper:stream.close()
    return _header(prefix),{'path':str(p),'sha256':encoded.hexdigest(),'size':encoded_size},decoded.hexdigest(),decoded_size,endpoint


def ending_custody(observation):
    """Compare with the consumed commitment; never adopt a new hash/identity.

    Called after the other evidence reads and around final worker publication.
    Finite checkpoints do not promise persistence after return or a filesystem
    lock.  Leaf ctime detects the demonstrated in-place restored-bytes ABA.
    """
    if 'same_run_continuation' in observation:
        from . import native_integration_checkpoint
        ev=observation['same_run_continuation']; support=native_integration_checkpoint.storage()
        limits=ev['effective_policy'];limit=min(limits['max_member_bytes'],limits['max_bytes'])
        for pin in (ev['original_stdout'],ev['current_stdout'],ev['checkpoint']):
            raw=support.regular_bytes(pin['path'],limit)
            require(len(raw)==pin['size'] and hashlib.sha256(raw).hexdigest()==pin['sha256'], 'same-run seed evidence changed at ending')
        native_integration_checkpoint.verify(support.read_document(ev['checkpoint']['path'],limit),limits=limits)

    pin=observation['embedded_lhe'];endpoint=observation['consumed_lhe_endpoint']
    p=Path(pin['path']).absolute()
    require(endpoint['path']==str(p), 'consumed LHE endpoint belongs to another path')
    require(_read(observation['banner']['path'])[1]==observation['banner'],
            'consumed native banner changed before ending return')
    with _file(p) as (source,current):
        require(list(_identity(os.fstat(source.fileno())))==endpoint['leaf']
                and [list(row) for row in _directories(current)]==endpoint['ancestors'],
                'consumed LHE identity changed before ending return')
        maximum=observation['decoded_lhe_ceiling']+65536
        require(os.fstat(source.fileno()).st_size<=maximum, 'ending encoded LHE exceeds original ceiling')
        digest=hashlib.sha256();size=0
        while True:
            block=source.read(min(65536,maximum-size+1))
            if not block:break
            size+=len(block);require(size<=maximum, 'ending encoded LHE exceeds original ceiling')
            digest.update(block)
        require({'path':str(current),'sha256':digest.hexdigest(),'size':size}==pin,
                'consumed LHE bytes changed before ending return')
        require(list(_identity(os.fstat(source.fileno())))==endpoint['leaf'],
                'consumed LHE identity changed during ending authentication')
    require(sorted(p.parent.glob('*_banner.txt'))==[Path(observation['banner']['path'])],
            'complete unique native banner census changed before ending return')
    return True


def observe(c, supplied, ending, *, supplied_process, mgroot, model_path, process_root,
            process_identity, stdout_path, artifacts, continuation=None):
    """Recompute from native sources and complete output bytes; no stored-proof override."""
    from . import model_events as m
    m.validate_config(c);validate(c['operative_seed_observation'])
    require(c['generation']['order']=='LO', 'operative seed observation supports exact LO lifecycle only')
    source_paths=source_inputs(mgroot);source_pins=[_read(p)[1] for p in source_paths]
    before=m.assignments(supplied)
    final=m.assignments(ending,native_lo_empty_strings=True)
    require('run_tag' in before, 'explicit native run tag required')
    tag=m.literal(before['run_tag'])
    require(type(tag) is str and re.fullmatch('[A-Za-z0-9_]{1,64}',tag), 'literal native run tag required')
    process_root=Path(process_root).absolute()
    relative=Path(c['outputs']['lhe_relative'])
    require(not relative.is_absolute() and all(x not in ('','.','..') for x in relative.parts)
            and relative.parts[0]=='Events', 'native LHE must belong to this generated process')
    lhe=process_root/relative
    directory=lhe.parent
    banner=directory/(directory.name+'_'+tag+'_banner.txt')
    candidates=sorted(directory.glob('*_banner.txt'))
    require(candidates==[banner], 'complete unique matching native banner required')
    raw,banner_pin=_read(banner);header=_header(raw,banner=True)
    require(_section(header,'MGVersion').strip()=='2.9.27', 'native banner version differs')
    embedded,lhe_pin,decoded_hash,decoded_size,lhe_endpoint=_lhe_header(lhe,c['outputs']['max_decoded_lhe_bytes'])
    require(embedded==header, 'complete native banner differs from actual embedded LHE header')
    pins={x['path']:x for x in artifacts}
    require(len(pins)==len(artifacts) and pins.get(str(banner))==banner_pin and pins.get(str(lhe))==lhe_pin,
            'operative seed evidence differs from initial generated artifact commitments')
    operative=_section(header,'MGRunCard')
    rows=m.assignments(operative,native_lo_empty_strings=True)
    require(set(before)==set(rows)==set(final), 'complete run-card field population differs')
    seed=c['generation']['seed']
    require(m.literal(before['iseed'])==m.literal(rows['iseed'])==seed
            and m.literal(final['iseed'])==0, 'configured original seed/banner/ending reset mismatch')
    transformations=_configured_matches(rows,before,mgroot,'complete configured operative run card')
    _configured_matches(final,{k:v for k,v in rows.items() if k!='iseed'},mgroot,'complete ending nonseed run card')
    # Banner.load_basic includes both complete native representations.  The
    # legacy procdef is not a modern import/generate command card.
    modern,modern_pin=_read(process_root/'Cards/proc_card_mg5.dat')
    legacy,legacy_pin=_read(process_root/'SubProcesses/procdef_mg5.dat')
    for name,native in [('MG5ProcCard',modern),('MGProcCard',legacy)]:
        # Exact Banner.write framing for these non-forbidden tags.  This is
        # a literal wrapper comparison, not a general XML/command normalizer.
        text=native.decode('utf-8').strip()
        framed='<![CDATA[\n'+text+'\n]]>' if '<' in text or '@' in text else text
        require(_section(header,name).strip()==framed,
                'complete embedded process cards differ from native generated cards')
    require(type(process_identity) is dict and process_identity.get('matched') is True
            and type(process_identity.get('source')) is dict,
            'matched generation-time ProcessDefinition identity required')
    from . import model_event_process as observer
    from ravel.workflow.state_io import _unique
    import json
    journal,journal_pin=_read(process_identity['source']['path'])
    require(journal_pin==process_identity['source'], 'generation-time identity journal changed')
    proof_rows=[json.loads(line,object_pairs_hook=_unique,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite native identity')))
        for line in journal.decode('utf-8').splitlines()]
    commitment=process_identity['commitment']
    require(commitment['model_import']=='import model '+str(model_path)+'-full',
            'generation-time identity belongs to foreign model')
    checked_identity=observer.verify(proof_rows,m.process_commands(supplied_process,c),commitment)
    require(checked_identity=={k:v for k,v in process_identity.items() if k!='source'},
            'generation-time identity differs from complete source journal')
    process=m.observe_exported_process(modern.decode('utf-8'),supplied_process,c,
                         model_path=model_path,identity_observation=process_identity)
    require(process['matched'], 'operative seed banner belongs to a foreign process/model')
    parameter,parameter_pin=_read(process_root/'Cards/param_card.dat')
    require(_section(header,'slha').strip()==parameter.decode('utf-8').strip(), 'complete embedded native parameter card differs')
    generation=_section(header,'MGGenerationInfo')
    counts=re.findall(r'^#\s*Number of Events\s*:\s*(\d+)\s*$',generation,re.M)
    require(counts==[str(c['generation']['events'])], 'banner generation event denominator differs')
    stdout,stdout_pin=_read(stdout_path,MAX_DOCUMENT if continuation is None else continuation['effective_policy']['max_member_bytes'])
    offsets=re.findall(rb'Using random number seed offset = (\d+)\b',stdout)
    continuation_pins=[]
    if continuation is None:
        require(offsets==[str(seed).encode('ascii')], 'one actual logged original seed offset required')
    else:
        from . import native_integration_checkpoint
        require(continuation['kind']==native_integration_checkpoint.KIND and continuation['declared_seed']==seed and
                continuation['same_sample_lineage'] is True and continuation['independent_sample'] is False,
                'authenticated same-run original-survey seed evidence required')
        require(stdout_pin==continuation['current_stdout'] and not offsets,'actual continued tail must not rerun survey')
        support=native_integration_checkpoint.storage(); capsule=continuation['checkpoint']
        limit=min(continuation['effective_policy']['max_bytes'],continuation['effective_policy']['max_member_bytes'])
        raw=support.regular_bytes(capsule['path'],limit)
        require(len(raw)==capsule['size'] and hashlib.sha256(raw).hexdigest()==capsule['sha256'], 'original checkpoint changed at seed consumption')
        record=support.read_document(capsule['path'],limit); native_integration_checkpoint.verify(record,limits=continuation['effective_policy'])
        require(record['compatibility']==native_integration_checkpoint.compatibility(c,continuation['current_source_base']),
                'operative seed continuation changes complete original source/cards/runtime/exposure')
        origin=continuation['original_stdout']; original,origin_pin=_read(origin['path'],continuation['effective_policy']['max_member_bytes'])
        require(origin_pin==origin and record['survey_stdout']['path']==origin['path'], 'original survey stdout identity differs')
        prefix=support.regular_bytes(Path(record['tree']['root'])/'survey-stdout-prefix.bin',continuation['effective_policy']['max_member_bytes'])
        require(original.startswith(prefix) and re.findall(rb'Using random number seed offset = (\d+)\b',original)==[str(seed).encode('ascii')],
                'one genuine original survey offset required for continuation')
        continuation_pins=[origin]
    # Ending current cards are bound separately; never rewritten or relabelled.
    current,current_pin=_read(process_root/'Cards/run_card.dat')
    require(current.decode('utf-8')==ending, 'ending mutable card changed after observation')
    for pin in [*source_pins,banner_pin,stdout_pin,parameter_pin,current_pin,modern_pin,legacy_pin,journal_pin,*continuation_pins]:
        require(_read(pin['path'],MAX_DOCUMENT if continuation is None or pin not in [stdout_pin,*continuation_pins] else continuation['effective_policy']['max_member_bytes'])[1]==pin, 'operative seed source/evidence changed at ending validation')
    if continuation is not None:
        require(support.read_document(capsule['path'],limit)==record,'checkpoint changed during operative seed validation')
        native_integration_checkpoint.verify(record,limits=continuation['effective_policy'])
    observation={'schema_version':1,'mode':MODE,'scope':'source_bound_native_LO_operative_seed_observation',
        'matched':True,'configured_seed_offset':seed,'operative_seed_offset':seed,'ending_mutable_seed':0,
        'operative_run_card':operative,'ending_run_card_rows':final,'complete_nonseed_field_count':len(final)-1,
        'configured_writer_transformations':transformations,
        'native_sources':source_pins,'banner':banner_pin,'embedded_lhe':lhe_pin,
        'decoded_lhe_sha256':decoded_hash,'decoded_lhe_bytes':decoded_size,'complete_lhe_eof':True,
        'decoded_lhe_ceiling':c['outputs']['max_decoded_lhe_bytes'],
        'consumed_lhe_endpoint':lhe_endpoint,
        'native_stdout':stdout_pin,'ending_mutable_card':current_pin,'native_parameter_card':parameter_pin,
        **({'same_run_continuation':continuation} if continuation is not None else {}),
        'native_process_observation':process,'native_modern_process_card':modern_pin,
        'native_legacy_process_card':legacy_pin,'generation_identity_journal':journal_pin,
        'sampling_law_independently_verified':False,
        'rng_realization_independently_verified':False,'cross_run_independence_verified':False,
        'randinit_used_as_configured_seed':False,'scientific_acceptance':False}
    ending_custody(observation)
    return observation
