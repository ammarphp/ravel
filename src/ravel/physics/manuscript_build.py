"""Portable PDF production through ordinary source-bound science/stage execution.

Two pdflatex passes and pdfinfo use the existing native process supervisor. No
shell escape, network/package installation, automatic bibliography retrieval or
new scheduler. A PDF is a delivered rendering, not scientific/style acceptance.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re
import shutil
import time
from ravel.physics import model_tool_bridge as custody
from ravel.workflow import state_io
from ravel.physics import manuscript_assets

SCOPE = 'manuscript_pdf_delivery'


def _keys(obj, names): custody._keys(obj,names,'manuscript build')


def validate(task): _keys(task,['config']); return task


def _slides(task,base):
    validate(task)
    path=custody._regular(task['config'],base)
    from ravel.workflow import report_integrity
    if path.stat().st_size>report_integrity.MAX_OPERATIONAL_METADATA_BYTES:raise ValueError('build config metadata capacity exceeded')
    return state_io.read_json(path).get('kind')=='manuscript-slides-build'


def _tree(row, base, *, limits=None, _runtime_proof=None):
    from ravel.workflow import report_integrity as ri, publication_runtime as pr
    limits=ri.custody_limits(limits)
    _keys(row,['root','manifest']);root=custody._regular(row['root'],base,directory=True)
    manifest=custody._pin(row['manifest'],base)
    pin={'path':str(manifest),'sha256':row['manifest']['sha256'],'size':manifest.stat().st_size}
    observed_metadata=pr._identity(manifest) if _runtime_proof is not None else None
    doc=ri._operational_json(pin,base,{},limits=limits)
    if observed_metadata is not None and pr._identity(manifest)!=observed_metadata:
        raise ValueError('runtime tree metadata changed during validated read')
    _keys(doc,['schema_version','files'])
    if doc['schema_version']!=1 or type(doc['schema_version']) is not int or type(doc['files']) is not dict or not 1<=len(doc['files'])<=limits['max_files']:
        raise ValueError('complete bounded TeX/runtime asset tree required')
    observed=(pr._inventory(root,limits=limits) if _runtime_proof is None else
        _runtime_proof.inventory(row,root,limits,metadata=observed_metadata,
            replay=lambda row=deepcopy(row),base=base,limits=deepcopy(limits):_tree(row,base,limits=limits)))
    actual={k:r['sha256'] for k,r in observed.items()};files=[Path(r['path']) for r in observed.values()]
    if actual!=doc['files']:raise ValueError('complete runtime asset census changed')
    return [manifest,*files]


def load(task, base, *, _qualification_scope=None, _session=None):
    from ravel.workflow import publication_runtime as pr
    with pr._qualification_validation(_qualification_scope) as scope:
        return _load(task, base, _qualification_scope=scope, _session=_session)


def _load(task, base, *, _qualification_scope, _session=None):
    if _slides(task,base):
        from ravel.physics import manuscript_slides
        p,c,product=manuscript_slides.load(task,base)
        return p,c,product['verified']['package']
    validate(task);p=custody._regular(task['config'],base)
    from ravel.workflow import report_integrity as ri, publication_runtime as pr
    high={'max_files':20000,'max_bytes':ri.MAX_CUSTODY_BYTES,'max_metadata_bytes':ri.MAX_OPERATIONAL_METADATA_BYTES}
    c=ri._operational_json({'path':str(p),'sha256':custody._hash(p),'size':p.stat().st_size},base,{},limits=high)
    version=c.get('schema_version')
    if type(version) is not int or version not in {1,2}:raise ValueError('manuscript build/v1 or v2 required')
    _keys(c,['schema_version','package','runtime','runtime_base','max_seconds','max_ram_mib','max_output_bytes','max_main_pages',*(['custody_limits'] if version==2 else [])])
    limits=ri.custody_limits(c.get('custody_limits'))
    if p.stat().st_size>limits['max_metadata_bytes']:raise ValueError('config exceeds selected operational metadata capacity')
    runtime_base=custody._regular(c['runtime_base'],p.parent,directory=True)
    if not Path(c['runtime_base']).is_absolute():raise ValueError('authenticated original runtime base required')
    for k in ('max_seconds','max_ram_mib','max_output_bytes'):
        if type(c[k]) is not int or c[k]<=0:raise ValueError('positive complete build resource bounds required')
    if c['max_main_pages'] is not None and (type(c['max_main_pages']) is not int or c['max_main_pages']<=0):raise ValueError('explicit main-text page ceiling required')
    rt=c['runtime'];_keys(rt,['engine','compiler','pdfinfo','svg_converter','asset_trees','max_ram_mib',
        *(['schema_version','purpose','environment','closure_manifest','snapshot_root','platform'] if version==2 else [])])
    proof=None
    if version==2:
        if type(rt['schema_version']) is not int or rt['schema_version']!=2:raise ValueError('runtime/v2 required')
        if type(rt['purpose']) is not str or rt['purpose'] not in {'qualification','qualified'}:raise ValueError('explicit qualification or qualified-build purpose required')
        if Path(rt['compiler']['path']).name!='pdflatex' or Path(rt['pdfinfo']['path']).name!='pdfinfo':raise ValueError('exact invocation basename required')
        proof=pr._build_runtime_proof(task,base,p,c,_session,build_owners=_build_proof_owners)
        if proof is None:pr.closure_inputs(rt,runtime_base,limits,_qualification_scope=_qualification_scope)
        else:proof.closure(rt,runtime_base,limits,_qualification_scope)
    if rt['engine']!='pdflatex' or rt['max_ram_mib']!=c['max_ram_mib']:raise ValueError('source-bound offline pdflatex/pdfinfo runtime required')
    for name in ('compiler','pdfinfo'):custody._pin(rt[name],runtime_base)
    if rt['svg_converter'] is not None:custody._pin(rt['svg_converter'],runtime_base)
    if type(rt['asset_trees']) is not list or not rt['asset_trees']:raise ValueError('complete declared format/class/style/font/bibliography tree required')
    runtime_assets=[]
    for row in rt['asset_trees']:runtime_assets.extend(_tree(row,runtime_base,limits=limits,_runtime_proof=proof))
    package_path=custody._pin({k:c['package'][k] for k in ('path','sha256')},p.parent)
    package=state_io.read_json(package_path)
    if any(Path(pin['path']).suffix.lower()=='.svg' for pin in package.get('figures',[])) and rt['svg_converter'] is None:
        raise ValueError('SVG figures require a bound real rsvg-convert runtime')
    if (package.get('kind')!='authored-manuscript-package' or package.get('scientific_acceptance') is not False or
            package.get('execution_authorized') is not False):raise ValueError('exact unaccepted authored manuscript package required')
    from ravel.workflow import manuscript_format,manuscript_production
    manuscript_production.verify_author(package,base_dir=package_path.parent)
    source_base=custody._regular(package['source_base'],p.parent,directory=True)
    format_pins={};contract=manuscript_format.load(package['formatting_contract'],source_base,format_pins)
    pack=manuscript_format.rule_pack(contract,source_base,{})
    if pack is not None and pack['max_main_pages'] is not None and (c['max_main_pages'] is None or c['max_main_pages']>pack['max_main_pages']):
        raise ValueError('rule-pack main-text page ceiling cannot be weakened')
    required=manuscript_format.required_runtime(contract,has_svg=any(Path(x['path']).suffix.lower()=='.svg' for x in package['figures']))
    if any(Path(x['path']).suffix.lower() in {'.jpg','.jpeg'} for x in package['figures']):
        required['asset_basenames'].extend(['article.cls','graphicx.sty'])
    available={q.name for q in [*runtime_assets,*[custody._pin({k:x[k] for k in ('path','sha256')},source_base) for x in manuscript_assets.pins(package['template_assets'])]]}
    if not set(required['asset_basenames'])<=available:raise ValueError('required selected venue/class/style/format dependencies absent')
    if not any(q.suffix.lower() in {'.tfm','.pfb','.otf','.ttf'} for q in runtime_assets):raise ValueError('source-bound font assets missing')
    if Path(package['latex']['path']).name!='note.tex':raise ValueError('source-defined note.tex entry required')
    return p,c,package


def inputs(task, base, *, _qualification_scope=None, _session=None):
    from ravel.workflow import publication_runtime as pr
    with pr._qualification_validation(_qualification_scope) as scope:
        return _inputs(task, base, _qualification_scope=scope, _session=_session)


def _inputs(task, base, *, _qualification_scope, _session=None):
    if _slides(task,base):
        from ravel.physics import manuscript_slides
        return manuscript_slides.inputs(task,base)
    p,c,package=load(task,base,_qualification_scope=_qualification_scope,_session=_session);rt=c['runtime'];runtime_base=Path(c['runtime_base']);source_base=Path(package['source_base']);files=[p,custody._pin({k:c['package'][k] for k in ('path','sha256')},p.parent)]
    for row in [package['latex'],package['manuscript'],package['integrity_request'],package['model_provenance'],package['formatting_contract'],package['formatting_assessment_pin'],package['author_binding'],*package['figures'],*manuscript_assets.pins(package['template_assets']),*package['input_pins']]:
        q=custody._pin({k:row[k] for k in ('path','sha256')},source_base)
        if row.get('size')!=q.stat().st_size:raise ValueError('complete manuscript source size changed')
        files.append(q)
    for name in ('compiler','pdfinfo'):files.append(custody._pin(rt[name],runtime_base))
    if rt['svg_converter'] is not None:files.append(custody._pin(rt['svg_converter'],runtime_base))
    from ravel.workflow import report_integrity,publication_runtime
    limits=report_integrity.custody_limits(c.get('custody_limits'))
    proof=(publication_runtime._build_runtime_proof(task,base,p,c,_session,build_owners=_build_proof_owners)
        if c['schema_version']==2 else None)
    for row in rt['asset_trees']:files.extend(_tree(row,runtime_base,limits=limits,_runtime_proof=proof))
    if c['schema_version']==2:
        closure=(publication_runtime.closure_inputs(rt,runtime_base,limits,_qualification_scope=_qualification_scope)
            if proof is None else proof.closure(rt,runtime_base,limits,_qualification_scope))
        files.extend(closure[1])
    files=sorted(set(files))
    from ravel.workflow import report_integrity
    if len(files)>limits['max_files'] or sum(q.stat().st_size for q in files)>limits['max_bytes']:
        raise ValueError('complete operational build closure exceeds supported final review envelope; no truncation')
    return files


def execution_seconds(task,base,*,_session=None): return load(task,base,_session=_session)[1]['max_seconds']


def _validation_inputs(task,base,session):
    return inputs(task,base,_session=session)


def _validation_execution_seconds(task,base,session):
    return execution_seconds(task,base,_session=session)


def _identity(paths):
    from ravel.workflow import publication_runtime as pr
    result={}
    for p in paths:
        p=custody._regular(p,Path.cwd());row=pr._identity(p);s=row['identity']
        result[str(p)]=[row['sha256'],s[0],s[1],s[3],s[4],s[5]]
    return result


def _bytes(out, ceiling):
    total=0
    for p in out.rglob('*'):
        if p.is_symlink():raise ValueError('aliased build output')
        if p.is_file():total+=p.stat().st_size
        elif not p.is_dir():raise ValueError('nonregular build output')
    if total>ceiling:raise ValueError('build output byte ceiling exceeded')
    return total


def _approved(task, out):
    from ravel.workflow import science
    for rd in out.parents:
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd)
            if (spec['schema_version']!=2 or spec['mode']!='manuscript-build' or spec['task']!=task or
                out!=(rd/plan['output_directory']/'manuscript-build').resolve()):raise ValueError('ordinary build task/output differs from approval')
            return plan
    raise ValueError('ordinary approved manuscript worker required')


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if (spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0
            or set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']):
        raise ValueError('portable PDF build requires exact one-attempt delivery-only ordinary review')


def page_census(pdfinfo, aux, *, max_main_pages, segments=None):
    matches=re.findall(r'^Pages:\s+([1-9][0-9]*)\s*$',pdfinfo,re.M)
    def boundary(identity,required):
        rows=re.findall(r'\\zref@newlabel\{'+identity+r'\}\{([^\n]*)\}',aux)
        if (required and len(rows)!=1) or (not required and len(rows)>1):raise ValueError('unique native absolute-page label required')
        if not rows:return None
        absolute=re.findall(r'\\abspage\{([1-9][0-9]*)\}',rows[0])
        if len(absolute)!=1:raise ValueError('actual shipped physical-page property required; logical labels are insufficient')
        return int(absolute[0])
    if len(matches)!=1:raise ValueError('actual PDF page census required')
    total=int(matches[0]);reference=boundary('ravel-reference-start',True);appendix=boundary('ravel-appendix-start',False)
    if segments is not None:
        if type(segments) is not list or not segments:raise ValueError('complete emitted physical section population required')
        seen=set();labels=set();main=set();covered=set();intervals=[]
        for row in segments:
            _keys(row,['id','section','start','end','counted'])
            if (type(row['counted']) is not bool or type(row['id']) is not str or row['id'] in seen or
                    any(type(row[k]) is not str or not re.fullmatch('[A-Za-z0-9-]+',row[k]) for k in ('start','end'))):
                raise ValueError('distinct source-defined physical segment required')
            if row['start']==row['end'] or {row['start'],row['end']}&labels:raise ValueError('every emitted segment needs distinct physical boundary labels')
            labels.update((row['start'],row['end']))
            seen.add(row['id']);start=boundary(row['start'],True);end=boundary(row['end'],True)
            if not 1<=start<=end<=total:raise ValueError('compiled section shipout boundaries inconsistent')
            pages=set(range(start,end+1));covered.update(pages)
            if row['counted']:main.update(pages)
            intervals.append({**deepcopy(row),'first_physical_page':start,'last_physical_page':end})
        # Unclassified physical pages cannot quietly inherit a reference suffix exemption.
        unknown=set(range(1,total+1))-covered;main.update(unknown)
        if not main:raise ValueError('compiled main-text population empty')
        if max_main_pages is not None and len(main)>max_main_pages:raise ValueError('main-text page ceiling exceeded, including post-reference main sections')
        return {'total_pages':total,'main_text_pages':len(main),'main_physical_pages':sorted(main),
            'unclassified_pages_conservatively_counted':sorted(unknown),'section_intervals':intervals,
            'references_start_physical_page':reference,'appendices_start_physical_page':appendix,
            'reference_and_appendix_pages':total-len(main),'main_text_ceiling':max_main_pages,
            'basis':'actual pdfinfo and complete emitted zref-abspage intervals; shared pages count once if any main content occupies them'}
    # Historical standalone prefix fixtures remain interpretable. New ordinary runs
    # always supply the complete authenticated materialization's section intervals.
    main=min(reference,appendix or reference)-1
    if not 1<=main<total or not 1<reference<=total or (appendix is not None and not 1<appendix<=total):
        raise ValueError('source/PDF physical page census inconsistent')
    if max_main_pages is not None and main>max_main_pages:raise ValueError('main-text page ceiling exceeded, references/appendices separated')
    return {'total_pages':total,'main_text_pages':main,'references_start_physical_page':reference,
        'appendices_start_physical_page':appendix,'reference_and_appendix_pages':total-main,
        'main_text_ceiling':max_main_pages,'basis':'actual pdfinfo physical page count and native zref-abspage deferred shipout boundaries'}


def run(task, base, output):
    if _slides(task,base):
        from ravel.physics import manuscript_slides
        return manuscript_slides.run(task,base,output)
    out=Path(output).absolute();plan=_approved(task,out);p,c,package=load(task,base)
    from ravel.workflow import report_integrity as ri,publication_runtime as pr
    limits=ri.custody_limits(c.get('custody_limits'));rt=c['runtime'];snapshot=None
    qualification=c['schema_version']==2 and rt['purpose']=='qualification'
    if c['schema_version']==2:
        snapshot,_=pr.closure_inputs(rt,Path(c['runtime_base']),limits,require_qualified=not qualification)
        if snapshot['platform']!='Darwin':raise ValueError('supported native loader observation required before effect; qualification held')
        if qualification and snapshot['qualification'] is not None:raise ValueError('qualification purpose requires the original unqualified snapshot')
    before=_identity(inputs(task,base));started=time.monotonic()
    if c['max_seconds']>plan['max_seconds']:raise ValueError('build exceeds ordinary admitted wall')
    if out.exists() or any(q.is_symlink() for q in (out,*out.parents)):raise ValueError('fresh regular build output required')
    out.mkdir(parents=True);source=out/'source';source.mkdir();copied=[]
    placements=[(pin,Path(pin['path']).name) for pin in [package['latex'],*package['figures']]]
    placements+=manuscript_assets.placements(package['template_assets'],Path(package['source_base']))
    for pin,relative in placements:
        path=custody._pin({k:pin[k] for k in ('path','sha256')},Path(package['source_base']));target=source/relative
        if target.exists():raise ValueError('duplicate note asset basename')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        if custody._hash(target)!=pin['sha256']:raise ValueError('copied build source differs')
        copied.append((target,pin['sha256']))
    from ravel.physics.reinterpret_db import execute_native
    # Each pass is a substep of the SAME declared wall ceiling; no reset per pass.
    runtime_base=Path(c['runtime_base']);compiler=custody._pin(c['runtime']['compiler'],runtime_base);pdfinfo=custody._pin(c['runtime']['pdfinfo'],runtime_base)
    receipts=[];conversions=[];tex_input_observations=[];runtime_observations=[]
    def invoke(tool,command,work,document):
        # Historical adapters remain inherited-environment; v2 is explicit only.
        if c['schema_version']==1:return execute_native(command,work,document)
        current,_=pr.closure_inputs(rt,runtime_base,limits,require_qualified=not qualification)
        if current!=snapshot:raise ValueError('runtime capability changed before effect')
        env=pr.tool_environment(rt,tool,work)
        receipt=execute_native(command,work,document,environment=env)
        if (receipt.get('command')!=command or receipt.get('environment_mode')!='explicit' or
                receipt.get('effective_environment')!=env or receipt.get('working_directory')!=str(Path(work).absolute()) or
                type(receipt.get('pid')) is not int):
            raise ValueError('native effective environment/invocation receipt differs')
        stderr=Path(work)/'native-stderr.log';raw=stderr.read_bytes()
        if len(raw)>limits['max_metadata_bytes']:raise ValueError('complete loader observation exceeds metadata capacity')
        images=pr.observed_images(raw.decode(),pid=receipt['pid'],snapshot=snapshot,platform_dependencies=snapshot['platform_dependencies'])
        if not any(x['path']==command[0] for x in images):raise ValueError('native executable missing from actual loader observation')
        runtime_observations.append({'tool':tool,'receipt_index':len(receipts),'stderr':{'path':str(stderr),
            'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)},'loaded_images':images,'host_identity':pr.host_identity()})
        return receipt
    for path,sha in copied:
        if path.suffix.lower()=='.svg':
            from xml.etree import ElementTree as ET
            raw=path.read_bytes()
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('self-contained SVG required')
            tree=ET.fromstring(raw)
            if any((k.endswith('href') and not v.startswith('#')) or ('url(' in v and 'url(#' not in v) for node in tree.iter() for k,v in node.attrib.items()):
                raise ValueError('SVG external assets require explicit source materialization; no remote/local implicit fetch')
            if any(node.tag.split('}')[-1] in {'script','foreignObject','style'} for node in tree.iter()):raise ValueError('unsupported active/CSS SVG requires separately qualified renderer')
            converter=custody._pin(c['runtime']['svg_converter'],runtime_base);target=path.with_suffix('.pdf')
            if target.exists():raise ValueError('converted figure would overwrite an admitted asset')
            log=out/('svg-'+path.stem);log.mkdir()
            remaining=c['max_seconds']-(time.monotonic()-started)
            if remaining<=0:raise ValueError('SVG rendering exhausted complete build wall')
            receipts.append(invoke('svg_converter',[str(converter),'--format=pdf','--output='+str(target),str(path)],log,{**c,'max_seconds':remaining}))
            if not target.is_file() or not target.read_bytes().startswith(b'%PDF-'):raise ValueError('real converted SVG PDF required')
            original=next(x for x in package['figures'] if Path(x['path']).name==path.name)
            conversions.append({'source':deepcopy(original),'copied_source':{'path':str(path),'sha256':sha,'size':path.stat().st_size},'pdf':{'path':str(target),'sha256':custody._hash(target),'size':target.stat().st_size},'command':receipts[-1]['command'],'kind':'rsvg-pdf','recorder':None})
            _bytes(out,c['max_output_bytes'])
        elif path.suffix.lower() in {'.jpg','.jpeg'}:
            if not path.read_bytes().startswith(b'\xff\xd8\xff'):raise ValueError('source JPEG media signature required')
            preview=out/('preview-'+path.stem);preview.mkdir();entry=preview/'preview.tex'
            raw=(r'\documentclass{article}\usepackage{graphicx}\pagestyle{empty}\begin{document}'
                r'\noindent\includegraphics[width=\linewidth]{../source/'+path.name+r'}\end{document}'+'\n').encode()
            entry.write_bytes(raw);entry_sha=custody._hash(entry)
            remaining=c['max_seconds']-(time.monotonic()-started)
            if remaining<=0:raise ValueError('JPEG preview exhausted complete build wall')
            receipts.append(invoke('compiler',[str(compiler),'-no-shell-escape','-interaction=nonstopmode','-halt-on-error',
                '-recorder','-output-directory='+str(preview),str(entry)],preview,{**c,'max_seconds':remaining}))
            target=preview/'preview.pdf';fls=preview/'preview.fls'
            if not target.is_file() or not target.read_bytes().startswith(b'%PDF-') or not fls.is_file() or custody._hash(entry)!=entry_sha:
                raise ValueError('actual JPEG PDF preview/recorder and exact preview source required')
            observed=[]
            for line in fls.read_text().splitlines():
                if not line.startswith('INPUT '):continue
                q=Path(line[6:]);q=custody._regular(q if q.is_absolute() else preview/q,preview)
                if str(q) in before:
                    if _identity([q])[str(q)]!=before[str(q)]:raise ValueError('JPEG preview runtime changed')
                elif q==entry:
                    if custody._hash(q)!=entry_sha:raise ValueError('preview source changed')
                elif q==path:
                    if custody._hash(q)!=sha:raise ValueError('preview source JPEG changed')
                elif q!=preview/'preview.aux':raise ValueError('JPEG preview consumed undeclared input')
                observed.append({'path':str(q),'sha256':custody._hash(q),'size':q.stat().st_size})
            if str(path) not in {r['path'] for r in observed}:raise ValueError('JPEG source not observed in preview recorder')
            if c['schema_version']==2 and not any(Path(x['path']).name=='pdflatex.fmt' and Path(x['path']).is_relative_to(Path(rt['snapshot_root'])) for x in observed):
                raise ValueError('JPEG pdflatex invocation did not load the admitted format')
            original=next(x for x in package['figures'] if Path(x['path']).name==path.name)
            conversions.append({'source':deepcopy(original),'copied_source':{'path':str(path),'sha256':sha,'size':path.stat().st_size},
                'pdf':{'path':str(target),'sha256':custody._hash(target),'size':target.stat().st_size},'command':receipts[-1]['command'],
                'kind':'pdflatex-jpeg-pdf','recorder':{'path':str(fls),'sha256':custody._hash(fls),'size':fls.stat().st_size},
                'preview_source':{'path':str(entry),'sha256':entry_sha,'size':len(raw)},'observed_inputs':observed})
            _bytes(out,c['max_output_bytes'])
    for attempt in (1,2):
        log=out/('pass-'+str(attempt));log.mkdir()
        remaining=c['max_seconds']-(time.monotonic()-started)
        if remaining<=0:raise ValueError('complete manuscript build wall exhausted')
        argv=[str(compiler),'-no-shell-escape','-interaction=nonstopmode','-halt-on-error','-file-line-error','-recorder',
            '-output-directory='+str(source),str(source/'note.tex')]
        receipts.append(invoke('compiler',argv,source,{**c,'max_seconds':remaining}))
        for name in ('native-stdout.log','native-stderr.log','native-process.json','native-execution.json'):
            origin=source/name;shutil.copyfile(origin,log/name)
            if custody._hash(origin)!=custody._hash(log/name):raise ValueError('retained per-pass supervision log changed')
        if c['schema_version']==2:runtime_observations[-1]['stderr']['path']=str(log/'native-stderr.log')
        fls=source/'note.fls'
        if not fls.is_file():raise ValueError('actual TeX recorder input census required')
        observed=[]
        for line in fls.read_text().splitlines():
            if not line.startswith('INPUT '):continue
            path=Path(line[6:]);path=path if path.is_absolute() else source/path
            path=custody._regular(path,source);absolute=str(path)
            if absolute in before:
                if _identity([path])[absolute]!=before[absolute]:raise ValueError('consumed TeX runtime asset changed')
                kind='admitted_source_or_runtime'
            elif any(path==q for q,sha in copied):
                sha=next(sha for q,sha in copied if q==path)
                if custody._hash(path)!=sha:raise ValueError('consumed manuscript source changed')
                kind='exact_copied_source'
            elif any(path==Path(x['pdf']['path']) for x in conversions):
                if custody._hash(path)!=next(x['pdf']['sha256'] for x in conversions if path==Path(x['pdf']['path'])):raise ValueError('consumed figure conversion changed')
                kind='actual_bound_figure_conversion'
            elif path==source/'note.aux':kind='same_build_generated_auxiliary'
            else:raise ValueError('TeX consumed an undeclared file: '+str(path))
            observed.append({'path':str(path),'sha256':custody._hash(path),'size':path.stat().st_size,'kind':kind})
        if not any(x['path']==str(source/'note.tex') for x in observed):raise ValueError('TeX recorder did not consume the exact entry source')
        if c['schema_version']==2 and not any(Path(x['path']).name=='pdflatex.fmt' and Path(x['path']).is_relative_to(Path(rt['snapshot_root'])) for x in observed):
            raise ValueError('selected pdflatex invocation did not load the admitted format')
        tex_input_observations.append({'pass':attempt,'recorder_sha256':custody._hash(fls),'observed_inputs':observed,
            'limit':'Native TeX INPUT recorder/current file commitments, not dynamic-library/ABI or arbitrary scientific consumption proof.'})
        shutil.copyfile(fls,log/'note.fls')
        _bytes(out,c['max_output_bytes'])
    pdf=source/'note.pdf';aux=source/'note.aux'
    if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-') or not aux.is_file():raise ValueError('actual nonempty compiled PDF/aux required')
    info=out/'pdfinfo';info.mkdir();remaining=c['max_seconds']-(time.monotonic()-started)
    if remaining<=0:raise ValueError('page census wall exhausted')
    receipts.append(invoke('pdfinfo',[str(pdfinfo),str(pdf)],info,{**c,'max_seconds':remaining}))
    pages=page_census((info/'native-stdout.log').read_text(),aux.read_text(),max_main_pages=c['max_main_pages'],segments=package['page_segments'])
    for path,sha in copied:
        if custody._hash(custody._regular(path,out))!=sha:raise ValueError('compiler modified admitted note or figure')
    for conversion in conversions:
        for key in ('pdf','copied_source','recorder','preview_source'):
            pin=conversion.get(key)
            if pin is not None:
                q=custody._pin({k:pin[k] for k in ('path','sha256')},out)
                if q.stat().st_size!=pin['size']:raise ValueError('actual preview/source commitment changed')
    if _identity(inputs(task,base))!=before:raise ValueError('build inputs/runtime changed')
    from ravel.workflow import manuscript_format
    format_pins={};formatting=manuscript_format.load(package['formatting_contract'],Path(package['source_base']),format_pins)
    format_assessment=deepcopy(package['formatting_assessment'])
    for row in format_assessment['rules']:
        if row['rule']['kind']=='max_main_pages':
            row['observed']=pages['main_text_pages'];row['state']='mechanically_passed' if row['observed']<=row['rule']['value'] else 'mechanically_failed'
    format_assessment['pending_rule_ids']=[row['rule']['id'] for row in format_assessment['rules'] if row['state'] not in {'mechanically_passed','not_required'}]
    result={'status':'passed','kind':'manuscript-pdf-build','scope':SCOPE,'package':c['package'],
        'template_assets':deepcopy(package['template_assets']),
        'formatting_assessment':format_assessment,'pdf':{'path':str(pdf),'sha256':custody._hash(pdf),'size':pdf.stat().st_size},'pages':pages,
        'executions':receipts,'tex_input_observations':tex_input_observations,'figure_conversions':conversions,'input_identity':before,'output_bytes':_bytes(out,c['max_output_bytes']),
        'physics_validated':False,'scientific_acceptance':False,'visual_style_accepted':False,
        'parent_task_accepted':False,'execution_authorized':False,
        'limitations':['Rendered PDF does not verify claims, bibliography, ATLAS visual style or whole-task acceptance.',
                       'Declared runtime assets are commitments; loaded library/TeX search-path closure requires separate runtime qualification.',
                       'Final delivery requires source-bound independent integrity/visual review and ordinary CI3.']}
    if c['schema_version']==2:
        result.update({'custody_limits':limits,'runtime_closure_manifest':rt['closure_manifest'],
            'runtime_purpose':rt['purpose'],'runtime_qualified':not qualification,
            'runtime_observations':runtime_observations,
            'runtime_qualification_scope':'Current selected Darwin image UUID/snapshot-byte and TeX recorder inputs; not ABI universality, full-cache identity, scientific or publisher acceptance.'})
        if qualification:
            observed_tools={}
            for row,receipt in zip(runtime_observations,receipts):
                tool=row['tool'];stderr=Path(row['stderr']['path']);work=stderr.parent
                native=pr._identity(work/'native-execution.json')
                recorder=pr._identity(work/'note.fls') if tool=='compiler' and work.name.startswith('pass-') else None
                if tool=='compiler' and recorder is None:continue # Main two-pass observation is retained below.
                document={'schema_version':1,'kind':'publication-runtime-observation','purpose':'qualification','runtime_qualified':False,'tool':tool,'host_identity':pr.host_identity(),
                    'native_execution':{k:native[k] for k in ('path','sha256','size')},'stderr':row['stderr'],
                    'tex_recorder':None if recorder is None else {k:recorder[k] for k in ('path','sha256','size')}}
                observed_tools[tool]=document
            required={k for k in ('compiler','pdfinfo','svg_converter') if rt[k] is not None}
            if set(observed_tools)!=required:raise ValueError('qualification output needs every selected tool observation')
            result['qualification_observations']={tool:ri._operational_new(out/('runtime-observation-'+tool+'.json'),document,limits=limits)
                for tool,document in observed_tools.items()}
            result['limitations'].append('Qualification-purpose output is capability evidence only; it cannot satisfy final manuscript delivery or CI3. Authenticate its successful ordinary receipt, then run the normal qualified build.')
        pr.closure_inputs(rt,runtime_base,limits,require_qualified=not qualification)
    expected=deepcopy(result)
    if len(pr._encoded(expected))>limits['max_metadata_bytes']:raise ValueError('complete build result exceeds selected metadata capacity')
    if c['schema_version']==2:
        ri._operational_new(out/'manuscript-build.json',expected,limits=limits)
    else:state_io.atomic_json(out/'manuscript-build.json',deepcopy(expected))
    if state_io.read_json(out/'manuscript-build.json')!=expected:raise ValueError('built-result durable commitment changed')
    return state_io.read_json(out/'manuscript-build.json')


def verified_result(binding, *, base_dir, _qualification_scope=None):
    from ravel.workflow import publication_runtime as pr
    with pr._qualification_validation(_qualification_scope) as scope:
        return _verified_result(binding, base_dir=base_dir, _qualification_scope=scope)


def _verified_result(binding, *, base_dir, _qualification_scope):
    """Current exact ordinary build, actual emitted PDF/preview and complete runtime inputs.

    This authenticates the selected producer and recorder evidence, not TeX ABI,
    pixels, scientific correctness or publisher conformance.
    """
    from ravel.workflow import report_integrity,science,publication_runtime as pr
    _keys(binding,['rundir','receipt','result']);consumed=report_integrity.CustodyInputs()
    rundir=custody._regular(binding['rundir'],base_dir,directory=True)
    spec=science.execution_spec(rundir)
    if spec.get('schema_version')!=2 or spec.get('mode')!='manuscript-build':raise ValueError('foreign ordinary stage cannot certify manuscript rendering')
    if _slides(spec['task'],rundir/'inputs'):
        raise ValueError('slide rendering cannot substitute an authenticated note PDF build')
    stage_base=rundir/'inputs'
    p,c,package=load(spec['task'],stage_base,_qualification_scope=_qualification_scope)
    if c['schema_version']==2 and c['runtime']['purpose']!='qualified':
        raise ValueError('qualification-purpose output cannot satisfy final manuscript delivery')
    limits=report_integrity.custody_limits(c.get('custody_limits'));budget=report_integrity.CustodyAccumulator(limits)
    result=report_integrity._operational_json(binding['result'],base_dir,consumed,limits=limits,accumulator=budget)
    stage=report_integrity._executed({k:binding[k] for k in ('rundir','receipt')},[],
        [{'artifact':binding['result'],'format':'json','location':'','value':result}],base_dir,consumed,limits=limits,accumulator=budget)
    if stage['state']!='current_successful_stage' or result.get('kind')!='manuscript-pdf-build' or result.get('status')!='passed':
        raise ValueError('exact current successful ordinary manuscript build required')
    if result['package']!=c['package'] or result['input_identity']!=_identity(inputs(spec['task'],stage_base,_qualification_scope=_qualification_scope)):
        raise ValueError('saved PDF build belongs to changed inputs/runtime/package')
    output=report_integrity._artifact_path(binding['result'],base_dir).parent
    report_integrity._dependency(result['pdf'],base_dir,consumed,limits=limits,accumulator=budget)
    with report_integrity._artifact_path(result['pdf'],base_dir).open('rb') as stream:pdf_header=stream.read(5)
    if pdf_header!=b'%PDF-':raise ValueError('actual supported compiled PDF required')
    info=output/'pdfinfo/native-stdout.log';aux=output/'source/note.aux'
    pages=page_census(info.read_text(),aux.read_text(),max_main_pages=c['max_main_pages'],segments=package['page_segments'])
    if pages!=result['pages']:raise ValueError('retained build physical page census differs from actual outputs')
    runtime_lineage=None
    if c['schema_version']==2:
        rt=c['runtime'];snapshot,closure_paths=pr.closure_inputs(rt,Path(c['runtime_base']),limits,require_qualified=True,_qualification_scope=_qualification_scope)
        if result.get('custody_limits')!=limits or result.get('runtime_closure_manifest')!=rt['closure_manifest']:
            raise ValueError('result operational policy/closure differs from ordinary config')
        if result.get('runtime_purpose')!='qualified' or result.get('runtime_qualified') is not True:
            raise ValueError('unqualified capability result cannot satisfy final delivery')
        observed=result.get('runtime_observations')
        if type(observed) is not list or len(observed)!=len(result['executions']):raise ValueError('complete native runtime observations required')
        for index,(row,receipt) in enumerate(zip(observed,result['executions'])):
            _keys(row,['tool','receipt_index','stderr','loaded_images','host_identity'])
            tool=row['tool']
            if row['receipt_index']!=index or tool not in {'compiler','pdfinfo','svg_converter'} or row['host_identity']!=pr.host_identity():
                raise ValueError('same-call tool/host observation differs')
            work=Path(receipt['working_directory']);env=pr.tool_environment(rt,tool,work,create=False)
            if (rt[tool] is None or type(receipt.get('pid')) is not int or receipt['pid']<=0 or
                    receipt.get('returncode')!=0 or receipt.get('resource_violation') is not None or
                    receipt.get('command',[None])[0]!=rt[tool]['path'] or receipt.get('environment_mode')!='explicit' or receipt.get('effective_environment')!=env):
                raise ValueError('bound native invocation/environment differs')
            report_integrity._dependency(row['stderr'],base_dir,consumed,limits=limits,accumulator=budget)
            raw=report_integrity._artifact_path(row['stderr'],base_dir).read_bytes()
            if len(raw)>limits['max_metadata_bytes']:raise ValueError('loader metadata bound exceeded')
            images=pr.observed_images(raw.decode(),pid=receipt['pid'],snapshot=snapshot,platform_dependencies=snapshot['platform_dependencies'])
            if images!=row['loaded_images']:raise ValueError('saved loader observation differs from exact retained native output')
        # These classes come from the reverified selected closure and its real
        # prior ordinary qualification, not from caller labels or all inputs.
        # Prior qualifier paper/data remains machine-only custody, never a
        # current scientific input or something to present to final reviewers.
        record=report_integrity._operational_json(binding['receipt'],base_dir,consumed,limits=limits,accumulator=budget)
        runtime_paths={str(Path(snapshot['snapshot_root'])/name) for name in snapshot['files']}
        metadata_paths={str(report_integrity._artifact_path(pin,Path(c['runtime_base']))) for pin in
            (rt['closure_manifest'],snapshot['tree_manifest'],snapshot['qualification']['original_snapshot'])}
        runtime_lineage={'runtime':[],'metadata':[],'qualification_custody':[]}
        for path in sorted(set(closure_paths)):
            identity=pr._identity(path);pin={k:identity[k] for k in ('path','sha256','size')}
            report_integrity._dependency(pin,base_dir,consumed,limits=limits,accumulator=budget)
            if not report_integrity._snapshot_member(record,'input_snapshot',pin):
                raise ValueError('runtime/qualification proof is outside this actual build input custody')
            kind='runtime' if pin['path'] in runtime_paths else 'metadata' if pin['path'] in metadata_paths else 'qualification_custody'
            runtime_lineage[kind].append(pin)
    figures={p['path']:p for p in package['figures']};seen=set()
    for row in result['figure_conversions']:
        source=row['source'];name=source['path']
        if name in seen or figures.get(name)!=source or Path(name).suffix.lower() not in {'.svg','.jpg','.jpeg'}:
            raise ValueError('preview mapping is not the exact original figure population')
        seen.add(name);original=report_integrity._raw(source,base_dir,consumed)
        copied=report_integrity._raw(row['copied_source'],base_dir,consumed)
        if copied!=original:raise ValueError('preview changed original scientific source')
        report_integrity._dependency(row['pdf'],base_dir,consumed,limits=limits,accumulator=budget)
        with report_integrity._artifact_path(row['pdf'],base_dir).open('rb') as stream:preview_header=stream.read(5)
        if preview_header!=b'%PDF-':raise ValueError('unsupported actual preview representation')
        if not any(e['command']==row['command'] for e in result['executions']):raise ValueError('preview has no same-build native process receipt')
        if Path(name).suffix.lower()=='.svg':
            converter=custody._pin(c['runtime']['svg_converter'],Path(c['runtime_base']))
            if row['kind']!='rsvg-pdf' or row['command']!=[str(converter),'--format=pdf','--output='+row['pdf']['path'],row['copied_source']['path']]:
                raise ValueError('SVG preview command differs from selected source-bound conversion')
        else:
            compiler=custody._pin(c['runtime']['compiler'],Path(c['runtime_base']))
            entry=report_integrity._raw(row['preview_source'],base_dir,consumed)
            expected=(r'\documentclass{article}\usepackage{graphicx}\pagestyle{empty}\begin{document}'
                r'\noindent\includegraphics[width=\linewidth]{../source/'+Path(row['copied_source']['path']).name+r'}\end{document}'+'\n').encode()
            preview_entry=Path(row['preview_source']['path'])
            expected_command=[str(compiler),'-no-shell-escape','-interaction=nonstopmode','-halt-on-error','-recorder',
                '-output-directory='+str(preview_entry.parent),str(preview_entry)]
            if row['kind']!='pdflatex-jpeg-pdf' or entry!=expected or row['command']!=expected_command:raise ValueError('JPEG preview is not exact source-defined native materialization')
            recorder=report_integrity._raw(row['recorder'],base_dir,consumed).decode()
            recorded=[]
            for line in recorder.splitlines():
                if line.startswith('INPUT '):
                    q=Path(line[6:]);q=custody._regular(q if q.is_absolute() else preview_entry.parent/q,preview_entry.parent)
                    recorded.append(str(q))
            if row['copied_source']['path'] not in recorded:raise ValueError('preview recorder omits original JPEG')
    if seen!={p['path'] for p in package['figures'] if Path(p['path']).suffix.lower() in {'.svg','.jpg','.jpeg'}}:
        raise ValueError('full original unsupported figure population needs actual supported previews')
    for pin in list(consumed.values()):report_integrity._dependency(pin,base_dir,consumed,limits=limits,accumulator=budget)
    # Re-obtain complete membership after all leaf/metadata reads, not before them.
    ending=inputs(spec['task'],stage_base,_qualification_scope=_qualification_scope)
    if result['input_identity']!=_identity(ending):raise ValueError('complete build input closure changed at verifier ending')
    presented=[binding['receipt'],binding['result'],result['pdf']]
    for row in result['figure_conversions']:
        presented.extend(row[k] for k in ('source','copied_source','pdf','recorder','preview_source') if row.get(k) is not None)
    # Operational input closure remains authenticated above. Private ancestor
    # stage captures are not promoted to final model evidence by this renderer.
    return {'result':result,'package':package,'config':c,'config_path':str(p),'proof_pins':presented,
        'input_paths':[str(q) for q in ending],'custody_limits':limits,
        'custody_pins':list(consumed.values()),
        **({'runtime_lineage':runtime_lineage} if runtime_lineage is not None else {}),
        'limit':'Actual current selected producer/output/recorder commitments; actual visual CI3 and native runtime qualification remain distinct.'}


def _build_proof_owners():
    return tuple((globals()[name],original) for name,original in _BUILD_PROOF_OWNERS)


_BUILD_PROOF_OWNERS=tuple((name,globals()[name]) for name in ('_tree','_load','_inputs','load','inputs','execution_seconds','_build_proof_owners'))
