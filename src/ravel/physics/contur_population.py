"""Explicit Contur3.1.5 finite populations; released native grouping and laws.

Schema3 is separate from the unchanged legacy single-file schemas. It allows
default3, full4 and no-exp2, and a declared finite all-beam grid. No statistical
combination or event exposure is calculated here.
"""
from copy import deepcopy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, _unique
from ravel.physics import contur_yoda as cy, contur_import as ci

PROFILES = {'default3': ci.MODES, 'full4': ci.FULL_MODES, 'no-exp2': ci.NO_EXP_MODES}
MAX_POINTS, MAX_BEAMS, MAX_FILES, MAX_BYTES = 128, 32, 4096, 512*1024**2


def document(path, *, sha=None):
    path = science.regular(path, Path.cwd())
    with path.open('rb') as stream:
        data = stream.read(8*1024**2+1)
    if len(data)>8*1024**2 or (sha is not None and hashlib.sha256(data).hexdigest()!=sha):
        raise ValueError('bounded consumed Contur document differs from declared commitment')
    def constant(value): raise ValueError('nonfinite Contur JSON constant')
    value=json.loads(data,object_pairs_hook=_unique,parse_constant=constant)
    def finite(v):
        if isinstance(v,float) and not math.isfinite(v): raise ValueError('overflowed Contur JSON number')
        if isinstance(v,dict):
            for x in v.values(): finite(x)
        if isinstance(v,list):
            for x in v: finite(x)
    finite(value)
    return value


def source_bytes(path, sha):
    path=science.regular(path,Path.cwd())
    with path.open('rb') as stream: data=stream.read(64*1024**2+1)
    if len(data)>64*1024**2 or hashlib.sha256(data).hexdigest()!=sha:
        raise ValueError('consumed literal source bytes differ from admitted commitment')
    return data


def modes(doc):
    if doc.get('profile') not in PROFILES: raise ValueError('explicit default3/full4/no-exp2 profile required')
    return PROFILES[doc['profile']]


def settings(doc):
    value=doc['settings']; cy._keys(value, cy.EFFECTIVE_KEYS, 'explicit profile settings')
    if value['stat_types']!=list(modes(doc)): raise ValueError('profile/native raw mode population differs')
    if type(value['offline']) is not bool: raise ValueError('explicit operational offline boolean required')
    if type(value['npyscripts']) is not int or not -1<=value['npyscripts']<=4096:
        raise ValueError('bounded explicit native script count required')
    expected=(-1,True) if doc['operation']=='single' else (value['npyscripts'],value['npyscripts']!=0)
    if (value['npyscripts'],value['keep_unscaled_aos'])!=expected or type(value['keep_unscaled_aos']) is not bool:
        raise ValueError('source-defined single/grid plot policy differs')
    old=deepcopy(value);old.update(stat_types=list(ci.MODES),offline=True,npyscripts=-1,keep_unscaled_aos=True)
    if not old['only_analyses']: old['only_analyses']=['.*']
    cy.settings(old)
    return deepcopy(value)


def load(task, base):
    path=science.regular(cy.validate(task)['input'],base);doc=document(path)
    common=('schema_version','operation','profile','source','config','runtime','assets','settings','max_seconds','max_ram_mib')
    op=doc.get('operation');cy._keys(doc,(*common,'grid') if op=='grid' else (*common,'yoda','parameters','expected_events'), 'explicit Contur profile')
    if type(doc['schema_version']) is not int or doc['schema_version']!=3 or op not in ('grid','single'):
        raise ValueError('explicit Contur schema3 single/grid required')
    cy._text(doc['source'],'complete original scientific source attribution')
    for key,low,high in (('max_seconds',1,900),('max_ram_mib',512,8192)):
        if type(doc[key]) is not int or not low<=doc[key]<=high: raise ValueError('bounded '+key+' required')
    settings(doc);cy._keys(doc['runtime'],('python','manifest'),'runtime');cy._keys(doc['assets'],('source','data','user'),'assets')
    if op=='single' and (type(doc['expected_events']) is not int or not 1<=doc['expected_events']<=10000000):
        raise ValueError('single supplied exposure required')
    return path,doc


def relative(value):
    p=Path(value)
    if not isinstance(value,str) or p.is_absolute() or '..' in p.parts or p.as_posix()!=value or not p.parts:
        raise ValueError('canonical relative grid member required')
    return value


def params_text(data):
    result={}
    for line in data.decode().strip().split('\n'):
        if line.count(' = ')!=1: raise ValueError('source params.dat exact name = value grammar required')
        k,v=line.split(' = ')
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',k) or k in result: raise ValueError('duplicate parameter identity')
        if not isinstance(v,str) or not v.strip(): raise ValueError('literal numeric parameter value required')
        try: number=float(v)
        except ValueError as exc: raise ValueError('unsupported nonnumeric parameter augmentation') from exc
        cy._number(number,'parameter');result[k]=v
    if not result: raise ValueError('full parameters required')
    return result


def bounded_grid_inventory(root):
    root=Path(root).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)): raise ValueError('regular owned/declared grid root required')
    result={};total=0;directories=0
    for p in root.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()): raise ValueError('grid special/symlink member refused')
        if p.is_dir():
            directories+=1
            if directories>MAX_FILES*4: raise ValueError('grid directory census exceeds finite bound')
            continue
        total+=p.stat().st_size
        if len(result)>=MAX_FILES or total>MAX_BYTES: raise ValueError('aggregate grid member/byte ceiling exceeded before read')
        result[p.relative_to(root).as_posix()]=cy._sha(p)
    return result


def grid_admission(value, base):
    cy._keys(value,('manifest','beams','beam_selection','tag','points'),'finite grid contract')
    mp=cy._pin(value['manifest'],base);manifest=document(mp,sha=value['manifest']['sha256'])
    cy._keys(manifest,('schema_version','kind','root','files'),'grid manifest')
    if type(manifest['schema_version']) is not int or manifest['schema_version']!=1 or manifest['kind']!='contur-input-grid':
        raise ValueError('input grid manifest kind differs')
    if not isinstance(manifest['files'],dict) or not 1<=len(manifest['files'])<=MAX_FILES: raise ValueError('bounded declared grid census required')
    root=Path(manifest['root']).absolute();actual=bounded_grid_inventory(root)
    if not isinstance(manifest['files'],dict) or not 1<=len(actual)<=MAX_FILES or actual!=manifest['files']:
        raise ValueError('complete bounded grid file census differs')
    files=[mp];total=0
    for rel,sha in manifest['files'].items():
        relative(rel);p=science.regular(root/rel,root);total+=p.stat().st_size
        if total>MAX_BYTES: raise ValueError('aggregate grid byte ceiling exceeded')
        if cy._sha(p)!=sha: raise ValueError('original grid bytes changed')
        files.append(p)
    beams=value['beams']
    if not isinstance(beams,list) or not 1<=len(beams)<=MAX_BEAMS or len(set(beams))!=len(beams) or any(not re.fullmatch('[A-Za-z0-9_.+-]{1,64}',b) for b in beams):
        raise ValueError('complete distinct native beam IDs required')
    if value['beam_selection']!='all' and value['beam_selection']!=beams:
        raise ValueError('native beam selection must be all or the exact declared list')
    if not isinstance(value['tag'],str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}',value['tag']): raise ValueError('literal native YODA tag required')
    points=value['points'];seen=set();source_yodas=set();native_yodas=set();point_dirs=set();numeric_ids=set()
    if not isinstance(points,list) or not 1<=len(points)<=MAX_POINTS: raise ValueError('complete bounded point census required')
    for point in points:
        cy._keys(point,('id','parameters','inputs'),'logical point')
        ident=point['id']
        if not isinstance(ident,str) or not re.fullmatch('[0-9]{1,16}',ident) or ident in seen or int(ident) in numeric_ids:
            raise ValueError('duplicate/aliased native runpoint')
        seen.add(ident);numeric_ids.add(int(ident))
        if not isinstance(point['parameters'],dict) or not point['parameters']:
            raise ValueError('complete literal point parameters required')
        ins=point['inputs']
        if not isinstance(ins,list) or [i.get('beam') for i in ins]!=beams: raise ValueError('every declared beam/point association required in declared order')
        for item in ins:
            cy._keys(item,('beam','source_yodas','native_yodas','expected_events'),'beam point association')
            prefix=item['beam']+'/'+ident+'/';point_dirs.add(prefix[:-1])
            pp=root/prefix/'params.dat'
            prel=prefix+'params.dat'
            if prel not in manifest['files'] or params_text(source_bytes(pp,manifest['files'][prel]))!=point['parameters']: raise ValueError('full literal cross-beam parameters differ')
            for key,seen_paths in (('source_yodas',source_yodas),('native_yodas',native_yodas)):
                rows=item[key]
                if not isinstance(rows,list) or not rows or len(set(rows))!=len(rows): raise ValueError('complete distinct YODA paths required')
                for rel in rows:
                    relative(rel)
                    if not rel.startswith(prefix) or not rel.endswith(('.yoda','.yoda.gz')) or rel in seen_paths: raise ValueError('YODA association differs')
                    if key=='source_yodas' and rel not in manifest['files']: raise ValueError('unbound source YODA')
                    seen_paths.add(rel)
            events=item['expected_events']
            if not isinstance(events,dict) or set(events)!=set(item['native_yodas']) or any(type(n) is not int or not 1<=n<=10000000 for n in events.values()):
                raise ValueError('explicit per-native-input exposure census required')
    if source_yodas!={r for r in actual if r.endswith(('.yoda','.yoda.gz'))}: raise ValueError('undeclared or missing source YODA member')
    if point_dirs!={r.rsplit('/',1)[0] for r in actual if r.endswith('/params.dat')}: raise ValueError('undeclared or missing native point directory')
    return manifest,root,files


def admission(path, doc):
    files=[path];grid=None
    if doc['operation']=='grid':
        manifest,root,ff=grid_admission(doc['grid'],path.parent);files+=ff;grid={'manifest':manifest,'root':root}
    else:
        yoda=cy._pin(doc['yoda'],path.parent);parameters=cy._pin(doc['parameters'],path.parent)
        if not yoda.name.endswith(('.yoda','.yoda.gz')): raise ValueError('single YODA required')
        cy.parameter_values(parameters);files += [yoda,parameters]
    config=cy._pin(doc['config'],path.parent);python=cy._pin(doc['runtime']['python'],path.parent)
    if not os.access(python,os.X_OK): raise ValueError('bound native Python executable required')
    rp=cy._pin(doc['runtime']['manifest'],path.parent);runtime=document(rp,sha=doc['runtime']['manifest']['sha256'])
    cy._keys(runtime,('schema_version','kind','python_sha256','installed_distribution_version','files','environment','scope'),'runtime')
    if type(runtime['schema_version']) is not int or runtime['schema_version']!=1 or runtime['kind']!='contur-declared-runtime' or runtime['python_sha256']!=doc['runtime']['python']['sha256']: raise ValueError('runtime identity differs')
    cy._text(runtime['scope'],'runtime scope');cy._text(runtime['installed_distribution_version'],'installed distribution label')
    cy._keys(runtime['environment'],cy.ENV_KEYS,'native environment')
    if any(v is not None and (not isinstance(v,str) or '\x00' in v) for v in runtime['environment'].values()): raise ValueError('environment literal/null required')
    if not isinstance(runtime['files'],list) or not runtime['files']: raise ValueError('declared complete runtime files required')
    files += [config,python,rp]+[cy._pin(f,rp.parent) for f in runtime['files']]
    bundles={}
    for kind in ('source','data','user'):
        md,root,ff=cy._manifest(doc['assets'][kind],path.parent,'contur-'+kind)
        bundles[kind]={'manifest':md,'root':root};files+=ff
    if grid: bundles['grid']=grid
    files+=list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return path,doc,runtime,bundles,sorted(set(files))


def resolve(doc, base):
    d=deepcopy(doc)
    for key in (('config',) if doc['operation']=='grid' else ('yoda','parameters','config')):
        d[key]['path']=str(cy._pin(doc[key],base))
    for key in d['runtime']: d['runtime'][key]['path']=str(cy._pin(doc['runtime'][key],base))
    for key in d['assets']: d['assets'][key]['path']=str(cy._pin(doc['assets'][key],base))
    if doc['operation']=='grid': d['grid']['manifest']['path']=str(cy._pin(doc['grid']['manifest'],base))
    return d


def arguments(doc, work):
    s=settings(doc);work=Path(work)
    args=(['--grid',str(work/'input/grid'),'--beams','all' if doc['grid']['beam_selection']=='all' else ','.join(doc['grid']['beams']), '--tag',doc['grid']['tag'],'--pyscripts',str(s['npyscripts'])]
          if doc['operation']=='grid' else [str(work/'input'/Path(doc['yoda']['path']).name)])
    args += ['--nomultip','--csv','native.csv','--outputdir',str(work/'native-output'),'--resultsfile','results.db','--config',str(work/'input/config.dat'),'--log',str(work/'contur.log'),'--weight-name',s['weight'],'--min-num-sys',str(s['min_num_sys'])]
    if s['offline']: args.append('--offline')
    if doc['profile']=='full4': args.append('--databg')
    if doc['profile']=='no-exp2': args.append('--no-exp')
    for key,flag in cy.BOOL_FLAGS.items():
        if s[key]: args.append(flag)
    for key,flag in cy.INVERSE_FLAGS.items():
        if not s[key]: args.append(flag)
    for flag,key in (('--ana-match','only_analyses'),('--ana-unmatch','veto_analyses')):
        for pattern in s[key]: args.extend([flag,pattern])
    if s['use_spey']: args.append('--spey')
    if s['sorting_metric']=='CLs': args.append('--sort-by-cls')
    return args


def authenticated_fallback(record, source_pin):
    if source_pin is None or not isinstance(record,dict) or set(record)!={'source','inspire_id','returned','before','after','source_observed_fallback'}:
        return False
    if record['source']!=source_pin or record['source_observed_fallback'] is not True or record['returned']!={'bibkey':'Offline','bibtex':'Offline'}:
        return False
    before,after=record['before'],record['after']
    if not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=set(cy.EFFECTIVE_KEYS) or set(after)!=set(before): return False
    changed={k for k in before if before[k]!=after[k] or type(before[k]) is not type(after[k])}
    if changed!={'offline'} or before['offline'] is not False or after['offline'] is not True: return False
    return cy._sha(science.regular(source_pin['path'],Path.cwd()))==source_pin['sha256']


def check_effective(doc,cfg,citation_calls=(),*,citation_source=None):
    state={key:deepcopy(getattr(cfg,key)) for key in cy.EFFECTIVE_KEYS}
    other=deepcopy(doc);other['settings']=state;settings(other)
    changed={k for k in state if state[k]!=doc['settings'][k] or type(state[k]) is not type(doc['settings'][k])}
    fallback=(changed=={'offline'} and doc['settings']['offline'] is False and state['offline'] is True and
       any(authenticated_fallback(r,citation_source) for r in citation_calls))
    if changed and not fallback: raise ValueError('actual native profile settings differ without authenticated citation fallback')
    return {'requested':deepcopy(doc['settings']),'effective':state,'operation':doc['operation'],
            'offline_presentation_scope':'Explicit offline changes citation/Inspire/report behavior; no unchanged-presentation claim.',
            'comparison_scope':'Source selections and uncertainty controls may differ between original default/Spey configurations.',
            'source_observed_offline_fallback':fallback}


def citation_observer(original,cfg,source_pin,records):
    """Only the source's URL-module-import fallback may alter offline."""
    path=Path(source_pin['path'])
    if Path(original.__code__.co_filename).resolve()!=path.resolve() or cy._sha(path)!=source_pin['sha256']:
        raise ValueError('citation call is not the authenticated original get_inspire')
    def call(inspire_id):
        if cy._sha(path)!=source_pin['sha256']: raise ValueError('citation source changed')
        before={k:deepcopy(getattr(cfg,k)) for k in cy.EFFECTIVE_KEYS}
        result=original(inspire_id)
        after={k:deepcopy(getattr(cfg,k)) for k in cy.EFFECTIVE_KEYS}
        changed={k for k in before if before[k]!=after[k] or type(before[k]) is not type(after[k])}
        fallback=(changed=={'offline'} and before['offline'] is False and after['offline'] is True and
                  isinstance(result,dict) and result.get('bibkey')=='Offline' and result.get('bibtex')=='Offline')
        record={'source':deepcopy(source_pin),'inspire_id':str(inspire_id),'returned':deepcopy(result),
                'before':before,'after':after,'source_observed_fallback':fallback}
        records.append(record)
        if cy._sha(path)!=source_pin['sha256'] or (changed and not fallback): raise ValueError('unexplained native citation/settings drift')
        return result
    return call


def staged(doc,bundles,work,*,initial=False):
    work=Path(work);current=cy._workspace_inventory(work/'input');expected={'config.dat':doc['config']['sha256']}
    if doc['operation']=='grid': expected.update({'grid/'+r:s for r,s in bundles['grid']['manifest']['files'].items()})
    else: expected.update({Path(doc['yoda']['path']).name:doc['yoda']['sha256'],'params.dat':doc['parameters']['sha256']})
    if initial and current!=expected: raise ValueError('fresh staged scientific census differs from originals')
    if doc['operation']=='single' and current!=expected: raise ValueError('staged single input changed')
    if current.get('config.dat')!=expected['config.dat']: raise ValueError('staged config changed')
    user=cy._workspace_inventory(work/'user');original_user=bundles['user']['manifest']['files']
    if initial and user!=original_user: raise ValueError('fresh staged initialized user assets differ')
    return {'scientific_files':current,'scientific_changes':{r:{'original':expected.get(r),'current':current.get(r)} for r in sorted(set(current)|set(expected)) if current.get(r)!=expected.get(r)},
            'user_files':user,'user_changes':{r:{'original':original_user.get(r),'current':user.get(r)} for r in sorted(set(user)|set(original_user)) if user.get(r)!=original_user.get(r)},
            'native_mutable_grid':doc['operation']=='grid','continuous_consumption_proved':False}


def materialize(path,doc,runtime,bundles,files,work):
    work=Path(work);work.mkdir(parents=True,exist_ok=False);(work/'input').mkdir();(work/'user').mkdir()
    shutil.copyfile(cy._pin(doc['config'],path.parent),work/'input/config.dat')
    if doc['operation']=='grid':
        (work/'input/grid').mkdir()
        for rel in bundles['grid']['manifest']['files']:
            target=work/'input/grid'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(bundles['grid']['root']/rel,target)
    else:
        for key,name in (('yoda',Path(doc['yoda']['path']).name),('parameters','params.dat')): shutil.copyfile(cy._pin(doc[key],path.parent),work/'input'/name)
    for rel in bundles['user']['manifest']['files']:
        target=work/'user'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(bundles['user']['root']/rel,target)
    resolved=resolve(doc,path.parent);atomic_json(work/'native-input.json',resolved)
    before={str(p):cy._sha(p) for p in files}
    atomic_json(work/'preparation.json',{'kind':'contur-explicit-population-preparation','input_hashes':before,'arguments':arguments(resolved,work),
       'staged_inputs':staged(resolved,bundles,work,initial=True),'source_version':cy.VERSION,'source_commit_label':cy.COMMIT,'runtime_consumption_verified':False,'events_generated':0})
    if before!={str(p):cy._sha(p) for p in cy.inputs({'input':str(path)},path.parent)}: raise ValueError('bound originals changed during grid copy')
    return work/'native-input.json'


def point_map(doc):
    return {p['id']:p for p in doc['grid']['points']}


def check_jobs(jobs,doc,work):
    declared=point_map(doc);root=Path(work)/'input/grid'
    if not isinstance(jobs,dict) or set(jobs)!=set(declared): raise ValueError('native grouped logical point census differs')
    result={}
    for ident,job in jobs.items():
        p=declared[ident];cy._keys(job,('yoda_files','params'),'native job')
        expected=[str(root/r) for i in p['inputs'] for r in i['native_yodas']]
        paths=job['yoda_files']
        if not isinstance(paths,list) or len(paths)!=len(set(paths)) or set(paths)!=set(expected) or job['params']!=p['parameters']:
            raise ValueError('native full-parameter/all-beam grouping differs')
        result[ident]={'native_yoda_order':list(paths),'parameters':deepcopy(job['params']),
                       'files':{r:cy._sha(science.regular(r,root)) for r in paths}}
    return result


def point_witness(point,doc,work,*,column_encoder=None):
    requested=modes(doc)
    if set(point.full_likelihood_results)!=set(requested) or set(point.sorted_blocks_results)!=set(requested):
        raise ValueError('native missing/unknown likelihood mode population')
    confidence=cy.confidence_witness(point,modes=requested)
    info=[]
    for path,value in point.yoda_info.items():
        if not isinstance(value,dict) or not {'num_events','xsec'}<=set(value): raise ValueError('native input YODA metadata absent')
        cy._number(value['xsec'],'native per-input cross section')
        cy._number(value['num_events'],'native per-input event count')
        if value['num_events']<0: raise ValueError('native per-input event count absent')
        info.append({'path':str(path),'num_events':value['num_events'],'xsec':value['xsec']})
    expected=({r:n for i in point_map(doc)[point.runpoint]['inputs'] for r,n in i['expected_events'].items()}
              if doc['operation']=='grid' else {Path(doc['yoda']['path']).name:doc['expected_events']})
    root=Path(work)/'input/grid' if doc['operation']=='grid' else Path(work)/'input'
    actual={str(Path(r['path']).relative_to(root)):r['num_events'] for r in info}
    if len(info)!=len(actual) or actual!=expected or set(point.yoda_paths)!=set(r['path'] for r in info): raise ValueError('complete per-native-input event metadata differs')
    # Keep insertion order as a list: source writer uses the first item only.
    if not info: raise ValueError('native YODA metadata empty')
    encoded={}
    if column_encoder is not None:
        for mode in requested:
            columns,values=column_encoder(point.full_likelihood_results[mode])
            encoded[mode]={'combined':dict(zip(columns,values)),'pools':{}}
            for name,raw in point.sorted_blocks_results[mode].items():
                columns,values=column_encoder(raw);encoded[mode]['pools'][name]=dict(zip(columns,values))
    return {'confidence':confidence,'ordered_yoda_info':info,'native_first_entry':deepcopy(info[0]),
            'native_yoda_order':list(point.yoda_paths),'parameters':deepcopy(point.parameter_values),
            'native_full_likelihood':deepcopy(point.full_likelihood_results),
            'native_sorted_blocks':deepcopy(point.sorted_blocks_results),
            'native_parameter_columns':encoded,
            'csv_dominants':{m:{'pool':point.get_dominant_pool(m),'histogram':point.get_dominant_hist_name(m)} for m in requested},
            'event_scope':'DB events_num is the native first-entry count; no summed all-beam exposure.'}


def reconcile(points,doc,work,observed):
    requested=modes(doc);expected=point_map(doc) if doc['operation']=='grid' else {'':None}
    if len(points)!=len(expected) or {p['raw']['run_point'] for p in points}!=set(expected) or set(observed['points'])!=set(expected): raise ValueError('complete native result point census differs')
    for p in points:
        ident=p['raw']['run_point'];w=observed['points'][ident]
        params=expected[ident]['parameters'] if doc['operation']=='grid' else params_text(source_bytes(doc['parameters']['path'],doc['parameters']['sha256']))
        if p['parameters']!={k:float(v) for k,v in params.items()} or w['parameters']!=params: raise ValueError('native full parameter identity differs')
        if p['original_yoda_paths']!=w['native_yoda_order'] or [r['raw']['stat_type'] for r in p['runs']]!=list(requested): raise ValueError('native DB point/path/mode correspondence differs')
        for r in p['runs']:
            mode=r['raw']['stat_type'];cw=w['confidence'][mode]
            if r['raw']['events_num']!=w['native_first_entry']['num_events'] or r['native_exclusion_confidence']!=cw['combined'] or {x['pool_name']:x['exclusion'] for x in r['pools']}!=cw['pools']:
                raise ValueError('native DB first-event/confidence/pool witness differs')
            native=w['native_full_likelihood'][mode]
            for dbkey,key in (('nll','NLL'),('llr','LLR'),('mu_lower_limit','mu_lower_limit'),('mu_upper_limit','mu_upper_limit'),('mu_hat','mu_hat')):
                if r['raw'][dbkey]!=native.get(key): raise ValueError('native raw likelihood/parameter result differs')
            # Released write_point writes the pool key/config mode, CLs, NLL,
            # LLR, encoded parameter columns and literal histos. id is assigned
            # by SQLite; run_id must join this run. Missing NLL/LLR remain NULL.
            for pool in r['pools']:
                if pool['run_id']!=r['raw']['id'] or pool['stat_type']!=mode:
                    raise ValueError('native pool/run/mode relationship differs')
                native_pool=w['native_sorted_blocks'][mode][pool['pool_name']]
                for dbkey,key in (('nll','NLL'),('llr','LLR'),('histos','histos')):
                    expected_value=native_pool.get(key)
                    if dbkey=='histos':
                        if not isinstance(expected_value,str):
                            raise ValueError('native pool histogram must have source-defined non-NULL text')
                    elif expected_value is not None:
                        cy._number(expected_value,'native pool '+key)
                    if pool[dbkey]!=expected_value:
                        raise ValueError('native per-pool raw '+dbkey+' correspondence differs')
            encoded=w.get('native_parameter_columns',{}).get(mode)
            if encoded is not None:
                if any(k not in r['raw'] or r['raw'][k]!=v for k,v in encoded['combined'].items()): raise ValueError('native full parameter-level DB columns differ')
                for pool in r['pools']:
                    if any(k not in pool or pool[k]!=v for k,v in encoded['pools'][pool['pool_name']].items()): raise ValueError('native per-pool parameter-level DB columns differ')
    return points


def native_worker(input_path,work,rundir):
    if sys.flags.optimize: raise ValueError('optimized runtime is not admitted')
    work=Path(work).resolve();path=Path(input_path).resolve()
    if path!=work/'native-input.json': raise ValueError('native input outside prepared workspace')
    _,doc,runtime,bundles,_=cy._admission({'input':str(path)},path.parent)
    cy._delegated_parent(rundir,doc,work)
    observed={'staged_before_sdk':staged(doc,bundles,work,initial=True),'citation_calls':[],'point_returns':{},'points':{}}
    for k,v in runtime['environment'].items():
        if os.environ.get(k)!=v: raise ValueError('native environment differs: '+k)
    os.environ['CONTUR_USER_DIR']=str(work/'user');os.environ['CONTUR_DATA_PATH']=str(bundles['data']['root'])
    sys.path.insert(0,str(bundles['source']['root']/'src'))
    import contur
    from contur.run import arg_utils,run_analysis
    from contur.config import config as cfg,state
    from contur.data import data_access_db
    from contur.util import utils
    if contur.__version__!=cy.VERSION: raise ValueError('native Contur version differs')
    src=bundles['source'];declared={str(src['root']/r):h for r,h in src['manifest']['files'].items()}
    deps={str(cy._pin(p,Path(doc['runtime']['manifest']['path']).parent)):p['sha256'] for p in runtime['files']}
    def loaded(): return cy.module_witness(src['root'],declared,deps)
    original_citation=utils.get_inspire
    citation_path=str(src['root']/'src/contur/util/utils.py')
    citation_pin={'path':citation_path,'sha256':declared[citation_path]}
    utils.get_inspire=citation_observer(original_citation,cfg,citation_pin,observed['citation_calls'])
    names=('process_grid','process_single','group_yodas_by_runpoint','write_point');original={n:getattr(run_analysis,n) for n in names}
    def before_process(args,target,csvfile=None):
        expected=work/'input/grid' if doc['operation']=='grid' else work/'input'/Path(doc['yoda']['path']).name
        if Path(target).absolute()!=expected: raise ValueError('native operation target differs')
        observed['staged_before_inference']=staged(doc,bundles,work,initial=True)
        observed['effective_settings']=check_effective(doc,cfg,observed['citation_calls'],citation_source=citation_pin);observed['loaded_before_inference']=loaded()
        observed['source_config_state']={'signal_config':deepcopy(state.signal_config),'parameter_config':deepcopy(state.parameter_config),'fit_mode':state.fit_mode}
        atomic_json(work/'native-observation.json',deepcopy(observed))
        return original['process_'+doc['operation']](args,target,csvfile)
    def grouped(beam_dirs,args):
        jobs=original['group_yodas_by_runpoint'](beam_dirs,args)
        observed['native_grouping']=check_jobs(jobs,doc,work)
        observed['staged_after_native_cleanup_merge']=staged(doc,bundles,work)
        atomic_json(work/'native-observation.json',deepcopy(observed));return jobs
    def before_write(point,*args):
        ident=point.runpoint
        if ident in observed['point_returns']: raise ValueError('duplicate native point write')
        observed['point_returns'][ident]={'runpoint':ident,'parameters':deepcopy(point.parameter_values),
            'native_yoda_order':list(point.yoda_paths),'full_likelihood_results':deepcopy(point.full_likelihood_results),
            'sorted_blocks_results':deepcopy(point.sorted_blocks_results)}
        atomic_json(work/'native-observation.json',deepcopy(observed))
        observed['points'][ident]=point_witness(point,doc,work,column_encoder=data_access_db.param_cols_and_values)
        atomic_json(work/'native-observation.json',deepcopy(observed))
        return original['write_point'](point,*args)
    run_analysis.process_grid=before_process;run_analysis.process_single=before_process
    if doc['operation']=='grid': run_analysis.group_yodas_by_runpoint=grouped
    run_analysis.write_point=before_write
    try: run_analysis.main(arg_utils.get_args(arguments(doc,work),'analysis'))
    finally:
        for n,v in original.items(): setattr(run_analysis,n,v)
        utils.get_inspire=original_citation
        observed['ending_effective_settings']=check_effective(doc,cfg,observed['citation_calls'],citation_source=citation_pin)
        observed['staged_after_inference']=staged(doc,bundles,work);observed['loaded_after_inference']=loaded()
        observed['source_observer_intervention']='Checked process/group/write wrappers only; released native grouping, merging, likelihood and pooling unchanged.'
        atomic_json(work/'native-observation.json',deepcopy(observed))
    if not observed['points'] or (doc['operation']=='grid' and 'native_grouping' not in observed): raise ValueError('native complete raw point/group witness absent')
    return observed


def run(task,base,output):
    rd,selected=cy._approved(task,output)
    if cy.execution_seconds(task,base)>selected['max_seconds']: raise ValueError('aggregate native/readback ceiling exceeds ordinary stage')
    files=cy.inputs(task,base);before={str(p):cy._sha(p) for p in files}
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=True);work=out/'contur-work'
    native_input=cy.materialize(task,base,work);doc=document(native_input)
    from ravel.physics.reinterpret_db import execute_native
    command=[doc['runtime']['python']['path'],'-B','-X','pycache_prefix='+str(work/'bytecode-cache'),str(Path(cy.__file__).resolve()),'--native-worker','--input',str(native_input),'--out',str(work),'--rundir',str(rd)]
    receipt=execute_native(command,out,doc)
    _,_,_,bundles,_=cy._admission(task,base);observed=document(work/'native-observation.json')
    state=deepcopy(doc);state['settings']=observed['effective_settings']['effective'];settings(state)
    class State: pass
    cfg=State()
    for k,v in state['settings'].items(): setattr(cfg,k,v)
    citation_path=str(bundles['source']['root']/'src/contur/util/utils.py')
    citation_pin={'path':citation_path,'sha256':bundles['source']['manifest']['files'].get('src/contur/util/utils.py')}
    check_effective(doc,cfg,observed['citation_calls'],citation_source=citation_pin)
    for k,v in observed['ending_effective_settings']['effective'].items(): setattr(cfg,k,v)
    check_effective(doc,cfg,observed['citation_calls'],citation_source=citation_pin)
    database=work/'native-output/results.db';csvfile=work/'native-output/native.csv'
    points=ci.decode_database(database,modes=modes(doc));reconcile(points,doc,work,observed)
    native_csv=check_csv(csvfile,doc,observed)
    native_inventory=cy._workspace_inventory(work/'native-output')
    work_inventory=cy._workspace_inventory(work)
    result={'schema_version':1,'kind':'native-contur-explicit-'+doc['operation'],'status':'passed','physics_validated':False,
      'source':doc['source'],'profile':doc['profile'],'mode_population':list(modes(doc)),'points':points,'fresh_inference':True,
      'native_execution':receipt,'runtime_observation':observed,'native_csv':native_csv,'native_output_inventory':native_inventory,'work_artifact_inventory':work_inventory,
      'database':{'path':str(database),'sha256':cy._sha(database)},'staged_after_readback':staged(doc,bundles,work),
      'events_generated':0,'detector_validated':False,'event_weights_validated':False,
      'limitations':['Native source grouping/pooling and confidence are retained; no new likelihood law or statistical calibration.',
       'All-beam metadata remain ordered; native DB event count is first-entry only, not combined exposure.',
       'Original default/Spey subset and uncertainty choices may differ; no isolated backend comparison.',
       'Declared offline operational choice changes citation/Inspire/presentation behavior.',
       'Byte checkpoints and loaded module witnesses do not prove full OS file/shared-library consumption.',
       'Finite declared population and resource ceilings do not imply scientific qualification or whole-catalogue coverage.']}
    commitments=ci.mode_delivery(out,'contur-results.json',result,points,modes=modes(doc))
    if before!={str(p):cy._sha(p) for p in cy.inputs(task,base)}: raise ValueError('bound population inputs changed before return')
    if cy._workspace_inventory(work/'native-output')!=native_inventory: raise ValueError('native DB/CSV/plot artifact ending bytes changed')
    if cy._workspace_inventory(work)!=work_inventory: raise ValueError('native observation/preparation/staged artifact ending bytes changed')
    ci.verify_full_mode_delivery(out,'contur-results.json',result,commitments)
    return result


def check_csv(path,doc,observed):
    """Read native CSV against raw returns, preserving native rounding/label bug."""
    path=science.regular(path,Path(path).parent);data=path.read_bytes()
    reader=csv.DictReader(data.decode().splitlines());rows=list(reader)
    expected=observed['points'];fields=list(next(iter(expected.values()))['parameters'])
    for m in modes(doc): fields += [x+m for x in ('CL','MULO','MUUP','MUHAT','LLR','dominant-pool','dominant-pool-histo','dominant-pool-llr')]
    if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=set(fields) or len(rows)!=len(expected): raise ValueError('native full CSV row/column census differs')
    unmatched=set(expected)
    for row in rows:
        matches=[k for k in unmatched if all(float(row[p])==float(v) for p,v in expected[k]['parameters'].items())]
        if len(matches)!=1: raise ValueError('native CSV full parameter association ambiguous')
        k=matches[0];unmatched.remove(k);w=expected[k]
        for m in modes(doc):
            native=w['native_full_likelihood'][m]
            for prefix,key,places in (('CL','CLs',None),('MULO','mu_lower_limit',2),('MUUP','mu_upper_limit',2),('MUHAT','mu_hat',2),('LLR','LLR',3)):
                value=native.get(key);actual=row[prefix+m]
                if value is None:
                    if actual!='': raise ValueError('native CSV absent field changed')
                elif not math.isfinite(float(actual)) or float(actual)!=(value if places is None else round(value,places)): raise ValueError('native CSV source rounding/confidence differs')
            d=w['csv_dominants'][m]
            if row['dominant-pool'+m]!=d['pool'] or row['dominant-pool-histo'+m]!=d['histogram'] or row['dominant-pool-llr'+m]!=d['histogram']: raise ValueError('native CSV dominant source semantics differ')
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'row_count':len(rows),'columns':reader.fieldnames,
            'semantics':'Source native rounding and histogram-valued dominant-pool-llr preserved; no independent uncertainty calculation.'}
