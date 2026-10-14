"""Final artifact checkpoint in the existing scientific-review journal.

These guards bind the reviewed population and blinding evidence. They do not
infer a scientific verdict, inspect hidden SR data or certify plot pixels.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
from . import execution, review_context


def _population(root, roots, *, session=None):
    from . import physics_review as review
    if type(roots) is not list or not 1<=len(roots)<=32 or any(type(x) is not str for x in roots):
        raise ValueError('complete finite final artifact roots required')
    directories=[];actual=set()
    for entry in roots:
        raw=Path(entry);raw=raw if raw.is_absolute() else root/raw
        directory=review_context._safe_path(raw)
        if not directory.is_dir() or not directory.is_relative_to(root):
            raise ValueError('final artifact roots must be owned run directories')
        if any(directory.is_relative_to(p) or p.is_relative_to(directory) for p in directories):
            raise ValueError('duplicate/overlapping final artifact roots')
        directories.append(directory)
        if session is not None:session.require_inventory(directory)
        for leaf in directory.rglob('*'):
            if leaf.is_symlink():raise ValueError('final population cannot contain symlinks')
            if leaf.is_file():actual.add(str(review._path(root,str(leaf))))
            elif not leaf.is_dir():raise ValueError('final population contains a nonregular member')
            if len(actual)>10000:raise ValueError('complete final artifact population exceeds declared bound')
    return actual


def _pin3_read(pin,root):
    from .scientific_autonomy import _document
    if type(pin) is not dict or set(pin)!={'path','sha256','size'} or type(pin['size']) is not int:
        raise ValueError('complete source-bound lineage pin required')
    path,raw=_document({k:pin[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
    if len(raw)!=pin['size']:raise ValueError('blinding lineage input size changed')
    return path,raw


def _source_blinding(root,evidence,policy,artifacts):
    """Recompute safe upstream projections and authenticate downstream lineage.

    This proves retained dataflow, not arbitrary program noninterference. Fresh
    scientific roles must still assess final claims/complement leakage and actual
    figures; a missing or unsupported producer leaves that member unresolved.
    Restricted native records are never returned as model evidence.
    """
    from . import physics_review as review,scientific_autonomy,scientific_report
    from ravel.physics import root_stream
    fields={'schema_version','kind','policy','projections','lineage'}
    if (type(evidence) is not dict or set(evidence)!=fields or type(evidence['schema_version']) is not int
            or evidence['schema_version']!=2 or evidence['kind']!='source_bound_final_blinding'):
        raise ValueError('source-reexecuted projection and complete final lineage required, not a declared pass bit')
    pp,policy_raw=_pin3_read(evidence['policy'],root)
    if {k:evidence['policy'][k] for k in ('path','sha256')}!={'path':str(pp),'sha256':policy['sha256']} or review._path(root,policy['path'])!=pp:
        raise ValueError('final lineage cannot substitute the accepted blind domain')
    build_endings=[]
    safe={};proof_pins=[{'path':str(pp),'sha256':policy['sha256']},
        *[{'path':str(Path(module.__file__).absolute()),'sha256':execution.file_hash(module.__file__)}
          for module in (root_stream,scientific_report,execution)]]
    rows=evidence['projections']
    if type(rows) is not list or not 1<=len(rows)<=64:raise ValueError('finite genuine source projection census required')
    for row in rows:
        if type(row) is not dict or set(row)!={'result','destination','public_paths'}:
            raise ValueError('exact source-native root-stream projection required')
        rp,result_raw=_pin3_read(row['result'],root)
        destination=review_context._safe_path(row['destination'])
        public=[str(review._path(root,x)) for x in row['public_paths']]
        if str(rp)!=str(destination.parent/'result.json'):
            raise ValueError('projection must consume its actual ordinary public result')
        result=review_context._strict_json_bytes(result_raw)
        expected_public=[root_stream.encoded(result),root_stream.encoded({'status':result['status'],'delivery':result['delivery'],'physics_validated':False}),root_stream.report_bytes(result)]
        observation=root_stream.blinding_check(deepcopy(result),destination,public,evidence['policy'])
        if observation.get('status')!='pass' or observation.get('sr_data_exposed') is not False:
            raise ValueError('actual source-defined projection did not preserve the blind domain')
        if observation.get('checked_paths')!=public or len(public)!=len(expected_public):
            raise ValueError('source projection returned a different public population')
        for entry,raw in zip(public,expected_public):
            path=review._path(root,entry)
            pin={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
            _pin3_read(pin,root)
            if str(path) in safe:raise ValueError('duplicate upstream public projection')
            safe[str(path)]=pin
            proof_pins.append({k:pin[k] for k in ('path','sha256')})
    expected={str(review._path(root,r['path'])):r for r in artifacts}
    lineage=evidence['lineage']
    if type(lineage) is not list or len(lineage)!=len(expected):raise ValueError('every actual final member needs exact safe-input lineage')
    seen=set()
    for row in lineage:
        if type(row) is not dict or set(row)!={'artifact','producer','inputs'}:
            raise ValueError('located actual final producer and input lineage required')
        ap,artifact_raw=_pin3_read(row['artifact'],root);name=str(ap)
        if name in seen or name not in expected or expected[name]['sha256']!=row['artifact']['sha256']:
            raise ValueError('lineage omits, aliases or replaces a final member')
        seen.add(name)
        declared=row['inputs']
        if type(declared) is not list or len(declared)>10000:raise ValueError('finite full downstream data-input census required')
        data={}
        for pin in declared:
            path,raw=_pin3_read(pin,root)
            if str(path) in data or safe.get(str(path))!=pin:
                raise ValueError('downstream input is not an exact allowed projection or previously authenticated public product')
            data[str(path)]=pin
        producer=row['producer']
        if producer is None:
            if safe.get(name)!=row['artifact'] or declared!=[row['artifact']]:
                raise ValueError('only a directly verified safe public output needs no downstream producer')
        elif type(producer) is dict and set(producer)=={'kind','recipe'} and producer['kind']=='scientific_report_draft':
            recipe_path,recipe_raw=_pin3_read(producer['recipe'],root)
            recipe=review_context._strict_json_bytes(recipe_raw)
            if 'final_results_review' in recipe:raise ValueError('draft lineage cannot borrow accepted final authority')
            genuine=scientific_report.input_pins(recipe,base_dir=root)
            # Recipe/control bindings are immutable evidence, not numerical data.
            controls={str(recipe_path)}
            if recipe.get('task_completion') is not None:
                from . import task_completion
                # Parent custody remains authenticated, but its membership must
                # never hide a source also used by the actual quantitative
                # renderer. Whole-parent metadata is not a data-source licence.
                direct_recipe={k:v for k,v in recipe.items() if k!='task_completion'}
                direct={str(Path(p['path']).absolute()) for p in scientific_report.input_pins(direct_recipe,base_dir=root)}
                completion=task_completion.evaluate(recipe['task_completion'],base_dir=root)
                _,completion_raw=_pin3_read(recipe['task_completion'],root)
                completion_request=review_context._strict_json_bytes(completion_raw)
                for outcome in completion_request['outcomes']:
                    for coverage in outcome['coverage']:
                        direct.update(str(Path(pin['path']).absolute()) for pin in coverage['evidence'])
                controls.update(str(Path(p['path']).absolute()) for p in completion['input_pins']
                    if str(Path(p['path']).absolute()) not in direct)
            needed={}
            for pin in genuine:
                if str(Path(pin['path']).absolute()) in controls:continue
                path,raw=scientific_autonomy._document({k:pin[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
                if 'size' in pin and len(raw)!=pin['size']:raise ValueError('report source size differs')
                needed[str(path)]={'path':str(path),'sha256':pin['sha256'],'size':len(raw)}
            if needed!=data:raise ValueError('report lineage omits or invents actual source-resolved inputs')
            draft=scientific_report.prepare_final(recipe,base_dir=root)
            if expected[name]['role']=='report_recipe':
                if artifact_raw!=recipe_raw:raise ValueError('final recipe differs from the actual source-bound draft recipe')
            elif expected[name]['role']=='report':
                if review_context._strict_json_bytes(artifact_raw).get('report_text')!=draft['report_text']:
                    raise ValueError('final report differs from its actual safe-input draft')
            else:raise ValueError('report producer cannot certify a foreign figure or scientific result')
            proof_pins.append({k:producer['recipe'][k] for k in ('path','sha256')})
        elif type(producer) is dict and set(producer)=={'kind','receipt'} and producer['kind']=='ordinary_stage':
            receipt_path,receipt_raw=_pin3_read(producer['receipt'],root)
            record=review_context._strict_json_bytes(receipt_raw)
            review._receipt(root,str(receipt_path))
            def leaves(snapshot):
                result={}
                for path,group in snapshot.items():
                    for leaf in group['files']:
                        item=Path(path) if group['kind']=='file' else Path(path)/leaf['name']
                        result[str(item)]={'path':str(item),'sha256':leaf['sha256'],'size':leaf['size']}
                return result
            outputs=leaves(record['output_snapshot'])
            if outputs.get(name)!=row['artifact']:raise ValueError('current successful producer did not deliver this exact final member')
            inputs=leaves(record['input_snapshot'])
            # Ordinary framework code/executable and exact plan/spec/CI1 are
            # execution custody, never a licence for private analytical inputs.
            framework=Path(__file__).resolve().parents[1]
            machinery={str(Path(record['command'][0]).resolve()),str(root/'inputs/science.json'),
                str(root/'inputs/science-plan.json'),str(root/'inputs/checkin1.json')}
            needed={path:pin for path,pin in inputs.items()
                if path not in machinery and not Path(path).is_relative_to(framework)}
            if needed!=data:raise ValueError('ordinary producer has unaccounted, private or unsupported data inputs; keep final member unresolved')
            proof_pins.append({k:producer['receipt'][k] for k in ('path','sha256')})
        elif (type(producer) is dict and set(producer)=={'kind','package','bindings'}
                and producer['kind']=='authored_manuscript'):
            from . import manuscript_production
            admitted=manuscript_production.verified_products(producer['package'],producer['bindings'],evidence['policy'],base_dir=root)
            if admitted['outputs'].get(name)!=row['artifact']:raise ValueError('actual writer did not produce this exact final member')
            needed={p['path']:p for p in admitted['data']}
            if needed!=data:raise ValueError('writer lineage must retain every actual projected analytical input')
            proof_pins.extend({k:p[k] for k in ('path','sha256')} for p in admitted['proof_pins'])
        elif (type(producer) is dict and set(producer)=={'kind','binding','package','bindings'}
                and producer['kind']=='manuscript_build'):
            from . import manuscript_production,report_integrity
            from ravel.physics import manuscript_build
            author=manuscript_production.verified_products(producer['package'],producer['bindings'],evidence['policy'],base_dir=root)
            built=manuscript_build.verified_result(producer['binding'],base_dir=root)
            package_path,_=_pin3_read(producer['package'],root)
            if built['result']['package']!={**producer['package'],'path':str(package_path)}:raise ValueError('build lineage changed the actual author package')
            receipt_path,receipt_raw=_pin3_read(producer['binding']['receipt'],root)
            record=review_context._strict_json_bytes(receipt_raw)
            outputs={}
            for path,group in record['output_snapshot'].items():
                for leaf in group['files']:
                    item=Path(path) if group['kind']=='file' else Path(path)/leaf['name']
                    outputs[str(item)]={'path':str(item),'sha256':leaf['sha256'],'size':leaf['size']}
            if outputs.get(name)!=row['artifact']:raise ValueError('current exact build did not deliver this final member')
            # Only source-authenticated reviewed support/custody and the exact
            # selected compiler/class/style/font tree are machinery. A foreign
            # data pin cannot become machinery by a caller role declaration.
            rt=built['config']['runtime'];rb=Path(built['config']['runtime_base'])
            limits=report_integrity.custody_limits(built.get('custody_limits'))
            runtime={str(manuscript_build.custody._pin(rt[k],rb)) for k in ('compiler','pdfinfo')}
            if rt['svg_converter'] is not None:runtime.add(str(manuscript_build.custody._pin(rt['svg_converter'],rb)))
            for tree in rt['asset_trees']:runtime.update(str(p) for p in manuscript_build._tree(tree,rb,limits=limits))
            controls={built['config_path'],*[p['path'] for field in ('support','machinery','custody_only') for p in author[field]]}
            qualifier_custody=set()
            if built['config']['schema_version']==2:
                typed=built['runtime_lineage']
                if type(typed) is not dict or set(typed)!={'runtime','metadata','qualification_custody'}:
                    raise ValueError('actual typed runtime/qualification lineage required')
                consumed=report_integrity.CustodyInputs();budget=report_integrity.CustodyAccumulator(limits)
                for pin in built['custody_pins']:
                    report_integrity._dependency(pin,root,consumed,limits=limits,accumulator=budget)
                for kind,pins in typed.items():
                    for pin in pins:
                        path=report_integrity._artifact_path(pin,root)
                        if consumed.get(str(path))!=pin or str(path) not in built['input_paths']:
                            raise ValueError('typed runtime proof is outside actual build custody')
                        if kind=='runtime':runtime.add(str(path))
                        elif kind=='metadata':controls.add(str(path))
                        else:qualifier_custody.add(str(path))
                build_endings.append((deepcopy(producer['binding']),built,consumed,budget,limits))
            needed={p['path']:p for p in author['data']}
            current_paper_inputs={str(report_integrity._artifact_path(pin,Path(built['package']['source_base'])))
                for pin in built['package']['input_pins']} if qualifier_custody else set()
            for path in built['input_paths']:
                if path in author['outputs']:needed[path]=author['outputs'][path]
                elif path not in runtime|controls and path not in needed:
                    if path not in qualifier_custody or path in current_paper_inputs:
                        raise ValueError('build input has no authenticated data/support/runtime lineage')
            if needed!=data:raise ValueError('build lineage omitted or invented actual scientific inputs')
            proof_pins.extend({k:p[k] for k in ('path','sha256')} for p in [*author['proof_pins'],*built['proof_pins']])
        else:raise ValueError('missing or unsupported final-member producer; preserve unresolved blinding scope')
        safe[name]=row['artifact'];proof_pins.append({k:row['artifact'][k] for k in ('path','sha256')})
    if seen!=set(expected):raise ValueError('full final safe-input lineage population differs')
    for pin in proof_pins:scientific_autonomy._document(pin,root,max_bytes=64*1024**2)
    for binding,built,consumed,budget,limits in build_endings:
        # After all public proof reads, reauthenticate the same complete build
        # and unique operational union. This custody classification never adds
        # proof_pins or substitutes for current authenticated scientific roles.
        ending=manuscript_build.verified_result(binding,base_dir=root)
        if ending!=built:raise ValueError('complete build/runtime lineage changed at final blinding ending')
        for pin in consumed.values():report_integrity._dependency(pin,root,consumed,limits=limits,accumulator=budget)
    return proof_pins


def prepare_blinding_check(root,out,*,policy,projections,lineage,artifacts):
    """Coordinator creates recheckable evidence from actual producers, not pass flags."""
    from .scientific_autonomy import _document
    root=review_context._safe_path(root);out=review_context._safe_path(out)
    value={'schema_version':2,'kind':'source_bound_final_blinding','policy':deepcopy(policy),
        'projections':deepcopy(projections),'lineage':deepcopy(lineage)}
    policy_pin={k:policy[k] for k in ('path','sha256')}
    _source_blinding(root,value,policy_pin,artifacts)
    import json,os
    raw=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with out.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    pin={'path':str(out),'sha256':hashlib.sha256(raw).hexdigest()}
    _document(pin,root);_source_blinding(root,value,policy_pin,artifacts)
    return pin


def _visual_media(path,data,role):
    """Authenticated media, never a caller role exemption."""
    suffix=path.suffix.lower()
    png=data.startswith(b'\x89PNG\r\n\x1a\n');pdf=data.startswith(b'%PDF-')
    unsupported=(suffix in {'.svg','.jpg','.jpeg','.gif','.webp','.tif','.tiff','.bmp'}
        or data.startswith((b'\xff\xd8\xff',b'GIF87a',b'GIF89a',b'II*\x00',b'MM\x00*',b'BM'))
        or (data.startswith(b'RIFF') and data[8:12]==b'WEBP'))
    if unsupported:raise ValueError('final image requires a supported actual PNG/PDF visual representation')
    if png or pdf or suffix in {'.png','.pdf'} or role=='figure':
        if not ((png and suffix=='.png') or (pdf and suffix=='.pdf')):
            raise ValueError('final image bytes and supported media suffix differ')
        if role!='figure':raise ValueError('actual final image cannot be downgraded by a nonfigure role label')
        return 'png' if png else 'pdf'
    return None


def _manuscript_visual_sources(root,manifest):
    """Exact original unsupported image -> actual same-build PDF, never a label waiver."""
    from ravel.physics import manuscript_build
    from . import scientific_autonomy,physics_review as review
    rows=manifest.get('visual_derivations',[])
    if type(rows) is not list or len(rows)>256:raise ValueError('finite authenticated figure preview census required')
    population={str(review._path(root,r['path'])):r for r in manifest['artifacts']}
    allowed={};proof=[];builds={}
    for row in rows:
        if type(row) is not dict or set(row)!={'source','preview','build'}:raise ValueError('complete exact native preview producer required')
        key=execution.digest(row['build'])
        if key not in builds:builds[key]=manuscript_build.verified_result(row['build'],base_dir=root)
        built=builds[key];matching=[c for c in built['result']['figure_conversions'] if c['source']==row['source'] and c['pdf']==row['preview']]
        if len(matching)!=1:raise ValueError('preview is not this actual source-defined native conversion')
        source,data=_pin3_read(row['source'],root);preview,pixels=_pin3_read(row['preview'],root)
        if str(source) in allowed or source.suffix.lower() not in {'.svg','.jpg','.jpeg'}:raise ValueError('distinct original unsupported media source required')
        if (str(source) not in population or population[str(source)]['sha256']!=row['source']['sha256'] or population[str(source)]['role']!='source_output'
                or str(preview) not in population or population[str(preview)]['sha256']!=row['preview']['sha256'] or population[str(preview)]['role']!='figure'):
            raise ValueError('CI3 must retain the actual original image AND its mandatory visual preview')
        _visual_media(preview,pixels,'figure');allowed[str(source)]=row['source']
        proof.extend({k:p[k] for k in ('path','sha256')} for p in [row['source'],row['preview'],*built['proof_pins']])
    for pin in proof:scientific_autonomy._document(pin,root,max_bytes=64*1024**2)
    return allowed,proof


def original_blinding_policies(root,artifacts):
    """Read concrete original study/parent producer scope, even in human mode.

    Only policy identities are returned. Source metadata and restricted native
    records are reauthenticated machine-side, never added as model evidence.
    """
    from . import science,scientific_autonomy
    from ravel.physics import root_stream
    root=review_context._safe_path(root);runs={str(root)};requests=[];seen=set();policies={}
    completion=root/'inputs/task_completion.json'
    if completion.is_file():requests.append({'path':str(completion),'sha256':execution.file_hash(completion),'size':completion.stat().st_size})
    for row in artifacts:
        if row['role']!='report_recipe':continue
        _,raw=scientific_autonomy._document({k:row[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
        recipe=review_context._strict_json_bytes(raw)
        if type(recipe) is dict and recipe.get('task_completion') is not None:requests.append(recipe['task_completion'])
    for pin in requests:
        path,raw=_pin3_read(pin,root)
        if str(path) in seen:continue
        seen.add(str(path));request=review_context._strict_json_bytes(raw)
        if (type(request) is not dict or set(request)!={'schema_version','contract','outcomes','parent_review','report'}
                or type(request['schema_version']) is not int or request['schema_version']!=1):
            raise ValueError('original final-parent completion source differs')
        if type(request['outcomes']) is not list or len(request['outcomes'])>128:raise ValueError('bounded original producer census required')
        for outcome in request['outcomes']:
            if (type(outcome) is not dict or set(outcome)!={'assignment_id','rundir','claim_scope','coverage'}
                    or type(outcome['rundir']) is not str or not outcome['rundir'].strip()):
                raise ValueError('original final producer association differs')
            rd=Path(outcome['rundir']);rd=rd if rd.is_absolute() else root/rd
            runs.add(str(review_context._safe_path(rd)))
    if len(runs)>129:raise ValueError('original final producer census exceeds its bound')
    for name in sorted(runs):
        rd=Path(name);spec_path=rd/science.SPEC
        if not spec_path.is_file():continue
        _,raw=scientific_autonomy._document({'path':str(spec_path),'sha256':execution.file_hash(spec_path)},rd)
        spec=review_context._strict_json_bytes(raw)
        if spec.get('mode')!='root-stream':continue
        plan=science.verify_plan(rd)
        capture=root_stream.core.Capture()
        _,config,dataset,analysis=root_stream._load(spec['task'],plan['base_dir'],capture)
        capture.finish()
        blind=analysis['blinding']
        if blind is None:continue
        source=blind['source'];policy_path=Path(source['path'])
        config_path=Path(spec['task']['config']['path'])
        config_path=config_path if config_path.is_absolute() else Path(plan['base_dir'])/config_path
        policy_path=policy_path if policy_path.is_absolute() else config_path.parent/policy_path
        policy_path=review_context._safe_path(policy_path)
        _,policy_raw=_pin3_read({**source,'path':str(policy_path)},root)
        policy={'path':str(policy_path),'sha256':source['sha256']}
        policies[(policy['path'],policy['sha256'])]=policy
    return list(policies.values())


def _require_original_blinding(root,artifacts,blind,delegated_policy=None):
    policies=original_blinding_policies(root,artifacts)
    if delegated_policy is not None:policies.append(delegated_policy)
    if not policies:return
    canonical=[]
    for policy in policies:
        from .scientific_autonomy import _document
        path,_=_document(policy,root);canonical.append({'path':str(path),'sha256':policy['sha256']})
    unique={(p['path'],p['sha256']) for p in canonical}
    if len(unique)!=1:raise ValueError('distinct original blind domains need an explicit supported full-final scope; cannot drop any domain')
    if blind['mode']!='blinded' or blind['policy'] is None:raise ValueError('original source-bound blinded study cannot select not_required')
    from .scientific_autonomy import _document
    path,_=_document(blind['policy'],root)
    if (str(path),blind['policy']['sha256']) not in unique:raise ValueError('final review cannot substitute or widen the original blind-domain policy')


def capture(root, pin, predecessor, checks, *, session=None):
    from . import physics_review as review, scientific_autonomy
    root=review._root(root)
    path,raw=scientific_autonomy._document(pin,root)
    value=review_context._strict_json_bytes(raw)
    fields={'schema_version','kind','source_cycle_id','source_cycle_sha256','artifact_roots','artifacts','claims','changes_since_checkin2','blinding'}
    if type(value) is not dict or set(value)!=fields|({'visual_derivations'} if 'visual_derivations' in value else set()) or type(value['schema_version']) is not int or value['schema_version']!=1 or value['kind']!='checkin3_final_results':
        raise ValueError('complete typed CHECK-IN 3 final package required')
    if (value['source_cycle_id']!=predecessor['cycle_id'] or value['source_cycle_sha256']!=predecessor['sha256']):
        raise ValueError('final results belong to a changed CI2 predecessor')
    roots=value['artifact_roots'];rows=value['artifacts']
    actual=_population(root,roots,session=session)
    if type(rows) is not list or not 1<=len(rows)<=10000:raise ValueError('complete final artifact rows required')
    allowed_media,media_proofs=_manuscript_visual_sources(root,value)
    expected={};pins=[];total_bytes=0
    roles={'report','figure','plot_data','report_recipe','statistical_result','reconstruction','source_output'}
    for row in rows:
        if type(row) is not dict or set(row)!={'path','sha256','role'} or row['role'] not in roles:
            raise ValueError('typed final artifact row required')
        p,b=scientific_autonomy._document({k:row[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
        total_bytes+=len(b)
        if total_bytes>512*1024**2:raise ValueError('complete final review exceeds512MiB admission budget')
        if str(p) not in allowed_media:_visual_media(p,b,row['role'])
        elif row['role']!='source_output' or row['sha256']!=allowed_media[str(p)]['sha256']:raise ValueError('original image custody differs from actual preview source')
        if str(p) in expected:raise ValueError('duplicate/aliased final artifact')
        expected[str(p)]={**row,'path':str(p)};pins.append(str(p))
    if set(expected)!=actual:raise ValueError('final manifest omits or invents population members')
    if any(sum(r['role']==role for r in rows)!=1 for role in ('report','report_recipe')):raise ValueError('final review needs one actual report and one complete recipe')
    claims=value['claims']
    if type(claims) is not list or not 1<=len(claims)<=256:raise ValueError('complete finite output claim census required')
    seen=set()
    for claim in claims:
        if type(claim) is not dict or set(claim)!={'id','text','evidence'}:raise ValueError('located final output claim required')
        review._ids([claim['id']],'final claim');review._text(claim['text'],'actual output claim')
        if claim['id'] in seen or type(claim['evidence']) is not list or not claim['evidence']:raise ValueError('distinct grounded final claim required')
        seen.add(claim['id'])
        for ref in claim['evidence']:
            if str(review._path(root,ref)) not in expected:raise ValueError('final claim cites unlisted final evidence')
    prior={str(review._path(root,p['path'])):p['sha256'] for p in predecessor['snapshots']}
    required={p:(prior.get(p),r['sha256']) for p,r in expected.items() if prior.get(p)!=r['sha256']}
    changes=value['changes_since_checkin2']
    if type(changes) is not list or len(changes)>10000:raise ValueError('finite complete unplanned/new artifact census required')
    supplied={}
    for row in changes:
        if type(row) is not dict or set(row)!={'path','prior_sha256','current_sha256','reason','dependent_stages'}:raise ValueError('explicit final artifact change required')
        p=str(review._path(root,row['path']));review._text(row['reason'],'final change reason')
        review._ids(row['dependent_stages'],'dependent scientific stages',empty=True)
        if p in supplied:raise ValueError('duplicate final change')
        supplied[p]=(row['prior_sha256'],row['current_sha256'])
    if supplied!=required:raise ValueError('final review must disclose every new/changed artifact since CI2')
    blind=value['blinding']
    if type(blind) is not dict or set(blind)!={'mode','policy','check'} or blind['mode'] not in {'blinded','not_required'}:
        raise ValueError('explicit final data-blinding evidence status required')
    _,document=scientific_autonomy.observed_run_document(root);delegated=scientific_autonomy.declaration(document,root)
    bound_policy=None if delegated is None else delegated['value']['blinding_policy']
    _require_original_blinding(root,rows,blind,bound_policy)
    intended={str(path):hashlib.sha256(raw).hexdigest(),**{p:r['sha256'] for p,r in expected.items()}}
    pins.extend(p['path'] for p in media_proofs);intended.update({p['path']:p['sha256'] for p in media_proofs})
    if blind['mode']=='blinded':
        if blind['policy'] is None or blind['check'] is None:raise ValueError('blinded final review needs current evidence, not a declaration')
        pp,policy_raw=scientific_autonomy._document(blind['policy'],root)
        if str(pp) not in prior or prior[str(pp)]!=blind['policy']['sha256']:
            raise ValueError('blinding policy was not captured by the original accepted review')
        cp,check_raw=scientific_autonomy._document(blind['check'],root)
        observation=review_context._strict_json_bytes(check_raw)
        lineage_pins=_source_blinding(root,observation,blind['policy'],rows)
        pins.extend(p['path'] for p in lineage_pins)
        intended.update({p['path']:p['sha256'] for p in lineage_pins})
        if not any(c['status']=='pass' and any(str(review._path(root,p['path']))==str(cp) for p in c['evidence']) for c in checks):
            raise ValueError('final scientific check census does not bind current blinding evidence')
        pins.extend([str(pp),str(cp)])
        intended.update({str(pp):blind['policy']['sha256'],str(cp):blind['check']['sha256']})
    else:
        if blind['policy'] is not None or blind['check'] is None:
            raise ValueError('not-required blinding still needs a current applicability check')
        cp,check_raw=scientific_autonomy._document(blind['check'],root)
        observation=review_context._strict_json_bytes(check_raw)
        if (type(observation) is not dict or set(observation)!={'schema_version','kind','status','sr_data_present','checked_paths'}
                or type(observation['schema_version']) is not int or observation['schema_version']!=1
                or observation['kind']!='blinding_applicability_check' or observation['status']!='pass'
                or observation['sr_data_present'] is not False
                or type(observation['checked_paths']) is not list
                or len(observation['checked_paths'])!=len(set(observation['checked_paths']))
                or {str(review._path(root,p)) for p in observation['checked_paths']}!=actual):
            raise ValueError('current blinding applicability evidence is missing or failed')
        if not any(c['status']=='pass' and any(str(review._path(root,p['path']))==str(cp) for p in c['evidence']) for c in checks):
            raise ValueError('final scientific checks omit current blinding applicability evidence')
        pins.append(str(cp));intended[str(cp)]=blind['check']['sha256']
    commitments=[{'path':review._identity(root,Path(p)),'sha256':sha} for p,sha in intended.items()]
    if any(execution.file_hash(p)!=sha for p,sha in intended.items()):raise ValueError('intended final artifacts changed before capture')
    if _population(root,roots)!=actual:raise ValueError('final population changed during capture')
    return {'manifest':{'path':review._identity(root,path),'sha256':hashlib.sha256(raw).hexdigest()},
            'source_cycle_id':predecessor['cycle_id'],'source_cycle_sha256':predecessor['sha256'],
            'commitments':commitments}, [str(path),*pins]


def gate(root, manifest, *, report=None, recipe=None):
    from . import physics_review as review
    root=review._root(root);reg,events=review._read(root);view=review._view(reg,events)
    errors=review.gate_errors(root,'delivery')
    if errors:raise ValueError('; '.join(errors))
    final=view['cycle'].get('final_results')
    if (final is None or final['manifest']['sha256']!=manifest['sha256']
            or review._path(root,final['manifest']['path'])!=review._path(root,manifest['path'])):
        raise ValueError('current accepted CHECK-IN 3 exact final package required')
    from .scientific_autonomy import _document
    _,raw=_document(manifest,root);value=review_context._strict_json_bytes(raw)
    snapshot={(p['path'],p['sha256']) for p in view['cycle']['snapshots']}
    expected={str(review._path(root,r['path'])) for r in value['artifacts']}
    if _population(root,value['artifact_roots'])!=expected:raise ValueError('final artifact population changed since CHECK-IN 3')
    for row in value['artifacts']:
        path,_=_document({k:row[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
        if (str(path),row['sha256']) not in snapshot and (str(path.relative_to(root)),row['sha256']) not in snapshot:
            raise ValueError('final artifact is outside its accepted cycle')
        if report is not None and row['role']=='report':
            _,b=_document({k:row[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
            actual=review_context._strict_json_bytes(b)
            if actual.get('report_text')!=report:raise ValueError('presentation changed since final scientific review')
        if recipe is not None and row['role']=='report_recipe':
            _,b=_document({k:row[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
            if execution.digest(review_context._strict_json_bytes(b))!=execution.digest(recipe):raise ValueError('presentation recipe differs from reviewed final recipe')
    if _population(root,value['artifact_roots'])!=expected:raise ValueError('final population changed during delivery')
    from . import scientific_autonomy
    _,document=scientific_autonomy.observed_run_document(root)
    delegated=scientific_autonomy.declaration(document,root)
    _require_original_blinding(root,value['artifacts'],value['blinding'],None if delegated is None else delegated['value']['blinding_policy'])
    _manuscript_visual_sources(root,value)
    if value['blinding']['mode']=='blinded':
        _,check_raw=_document(value['blinding']['check'],root)
        _source_blinding(root,review_context._strict_json_bytes(check_raw),value['blinding']['policy'],value['artifacts'])
    for p in final['commitments']:_document(p,root,max_bytes=64*1024**2)
    return {'rundir':str(root),'cycle_id':view['cycle']['cycle_id'],'manifest':deepcopy(manifest),
            'decision_authority':'declared_scientific_review_actors','human_identity_authenticated':False,
            'unblinding_authorized':False}


def visual_sources(root, final_binding):
    """Canonical required figure population of this exact immutable draft.

    This is input custody, not image inspection. The Host transport must present
    every PNG/PDF page to the current role before a final vote can be consumed.
    """
    from . import physics_review as review,scientific_autonomy
    root=review._root(root)
    _,raw=scientific_autonomy._document(final_binding['manifest'],root)
    manifest=review_context._strict_json_bytes(raw);sources=[]
    allowed,_=_manuscript_visual_sources(root,manifest)
    for row in manifest['artifacts']:
        path,data=scientific_autonomy._document({k:row[k] for k in ('path','sha256')},root,max_bytes=64*1024**2)
        if str(path) not in allowed and _visual_media(path,data,row['role']) is not None:
            sources.append({'path':str(path),'sha256':row['sha256'],'size':len(data)})
    if len(sources)>256:raise ValueError('finite required final figure population exceeded')
    return sources


def input_pins(root, manifest):
    """Expose the exact already-reviewed final population to ordinary model input custody."""
    gate(root,manifest)
    from . import physics_review as review
    root=review._root(root);reg,events=review._read(root);final=review._view(reg,events)['cycle']['final_results']
    return [{'path':str(review._path(root,p['path'])),'sha256':p['sha256'],
             'size':review._path(root,p['path']).stat().st_size} for p in final['commitments']]


def required(root, *, contract=None):
    """Only an authenticated calculation parent is exempt from actual research CI3."""
    from . import physics_review as review,scientific_autonomy
    root=review._root(root)
    if not review.registered(root):return False
    if contract is None:
        _,document=scientific_autonomy.observed_run_document(root)
        if 'prompt' in document:
            contract=document
        elif 'goal_binding' in document:
            source=document['goal_binding']['contract']
            _,raw=scientific_autonomy._document({k:source[k] for k in ('path','sha256')},root)
            if type(source.get('size')) is not int or len(raw)!=source['size']:
                raise ValueError('final review original task source size changed')
            contract=review_context._strict_json_bytes(raw)
        else:
            # A bare caller task_class cannot exempt an actual CI2 workflow.
            return True
    # A task-mode label never exempts a scientific/symbolic calculation. Only
    # the real bounded literal adapter has the short deterministic route.
    _,document=scientific_autonomy.observed_run_document(root)
    if document.get('schema_version')==1 and document.get('mode')=='literal-calculation':
        from ravel.physics.literal_calculation import validate_parent
        validate_parent(document['task'],root)
        return False
    return True
