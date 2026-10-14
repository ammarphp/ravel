"""Complete supplied model grids through existing generation/response/template APIs.

This pure ordinary operation constructs inputs, never generates events or fits.
Response scenarios share each point's complete original event population. A
published scalar limit or post-fit error bar is never promoted to a likelihood.
"""
from fractions import Fraction
import json
import math
from pathlib import Path
import re

from ravel.workflow import task_completion as tc
from ravel.workflow.state_io import atomic_json
from ravel.workflow.finite_grid import required, identifier, coordinates, delivery, write_delivery, SpecificationError
from ravel.physics import detector_response as dr, model_events as gen
from ravel.physics import published_model as pm, signal_templates as st

SCOPE = 'supplied_model_grid_recipe_construction'
MAX_DELIVERY_BYTES = 128*1024**2


def require(ok, message):
    if not ok: raise ValueError(message)


def keys(d, names):
    require(type(d) is dict and set(d) == set(names), 'closed SVJ recipe fields required')


def number(x):
    require(type(x) in (int,float) and math.isfinite(x), 'finite literal SVJ coordinate required')
    return x


def names(rows):
    require(type(rows) is list and rows and len(rows) <= 128, 'bounded complete named census required')
    ids = [r['id'] for r in rows]
    require(all(type(x) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,80}',x) for x in ids) and len(set(ids)) == len(ids), 'unique safe recipe IDs required')
    return ids


def pin(path):
    from ravel.workflow.validation_io import _source_pin_bytes
    observed=gen._generated_pin(path)
    require(0 < observed['size'] <= 16*1024**2,'bounded generated recipe member required')
    _source_pin_bytes(observed,limit=16*1024**2)
    return observed


def validate(task):
    keys(task, ('input',)); require(type(task['input']) is str and task['input'], 'recipe input path required')


def _capture(task, base):
    validate(task)
    path=Path(task['input']);path=path if path.is_absolute() else Path(base)/path
    path=path.absolute();base=path.parent;session=tc._Inputs(base)
    request=session.document(session.capture(path))
    required(request, ('study_id','generation_conventions','coordinate_constraints','delivery'))
    identifier(request['study_id']); delivery(request['delivery'])
    _conventions(request['generation_conventions'])
    keys(request, ('study_id','generation_conventions','coordinate_constraints','delivery','schema_version','source','goal_binding','analysis','axes','points','response_scenarios','background_scenarios','templates','generation_policy','analysis_policy','inference_policy','child_seconds','assumptions'))
    require(type(request['schema_version']) is int and request['schema_version']==1,'SVJ recipe schema1 required')
    require(type(request['source']) is str and request['source'].strip(), 'explicit source interpretation required')
    require(type(request['assumptions']) is list and request['assumptions'] and all(type(x) is str and x.strip() for x in request['assumptions']), 'explicit conditional assumptions required')
    require(request['goal_binding'] is not None, 'original whole semi-visible-jet goal binding required')
    projection=tc.binding_projection(request['goal_binding'],base_dir=base)
    for p in projection['input_pins']:session.file(p)
    a=request['analysis'];keys(a,('id','energy_tev','lumi_fb','sources','bins','unresolved_bins','interpretation'))
    identifier(a['id'])
    require(number(a['energy_tev'])>0 and number(a['lumi_fb'])>0,'explicit positive analysis energy and exposure required')
    require(type(a['interpretation']) is str and a['interpretation'].strip(),'explicit source interpretation required')
    require(a['sources'], 'primary analysis and basis evidence required')
    for p in a['sources']:session.file(p)
    require(type(a['unresolved_bins']) is list and len(a['unresolved_bins'])<=32,'explicit unresolved fitted-bin census required')
    for missing in a['unresolved_bins']:
        keys(missing,('id','role','reason'));require(missing['role'] in ('SR','CR') and type(missing['id']) is str and type(missing['reason']) is str and missing['reason'].strip(),'unknown fitted population needs a located obligation, never an invented zero bin')
    names(a['bins']); destinations=[]
    for b in a['bins']:
        keys(b,('id','channel','sample','index','role'))
        require(all(type(b[k]) is str and b[k] for k in ('channel','sample')) and type(b['index']) is int and b['index']>=0 and b['role'] in ('SR','CR'), 'all ordered SR/CR bins required')
        destinations.append((b['channel'],b['sample'],b['index']))
    require(len(set(destinations))==len(destinations), 'duplicate likelihood bin mapping')
    grid=coordinates(request['axes'], maximum=32)
    axis_names=list(grid[0])
    require(type(request['coordinate_constraints']) is list,'explicit coordinate constraints required')
    for constraint in request['coordinate_constraints']:
        keys(constraint,('axis','min','max'))
        require(constraint['axis'] in axis_names and number(constraint['min'])<=number(constraint['max']),'located coordinate bounds required')
        require(all(constraint['min']<=p[constraint['axis']]<=constraint['max'] for p in grid),'coordinate outside supplied physical domain')
    for point in request['points']:
        keys(point['coordinate'],axis_names)
        for x in point['coordinate'].values():number(x)
    names(request['points']);require(len(request['points'])==len(grid),'complete physical-grid population required')
    require([p['coordinate'] for p in request['points']]==grid,'ordered full physical grid required; no silent point selection')
    rs=request['response_scenarios'];names(rs);names(request['background_scenarios'])
    for s in rs:
        keys(s,('id','coordinate','assumptions'))
        require(type(s['coordinate']) is list and type(s['assumptions']) is list and s['assumptions'] and all(type(x) is str and x for x in s['assumptions']),'supplied hypothetical joint response assumptions required')
    for s in rs:
        for x in s['coordinate']:number(x)
    for s in request['background_scenarios']:
        keys(s,('id','published_model','response','anchor','assumptions'))
        require(type(s['assumptions']) is list and s['assumptions'] and all(type(x) is str and x for x in s['assumptions']), 'explicit background scenario assumptions required')
        if s['published_model'] is not None:session.document(s['published_model'])
        if s['response'] is not None:
            session.document(s['response']);require(s['anchor'] is not None,'supplied background response requires its actual joint anchor')
        if s['anchor'] is not None:
            require(type(s['anchor']) is list,'background anchor coordinate required')
            for x in s['anchor']:number(x)
    for p in request['points']:
        keys(p,('id','coordinate','generation','shower_contract','analysis','response'))
        if p['generation'] is not None:
            config=session.document(p['generation']);gen.validate_config(config)
            require(p['shower_contract'] is not None,'generation requires explicit operative hidden shower contract')
            _shower(config,session.document(p['shower_contract']),p['coordinate'],session,located(p['generation'],base).parent,located(p['shower_contract'],base).parent,request['generation_conventions'])
        else:require(p['shower_contract'] is None,'absent generation cannot assert an operative shower')
        if p['analysis'] is not None:
            _analysis_spec(request,p,session,base)
        if p['response'] is not None:
            doc=session.document(p['response']);_response(doc,rs,session,located(p['response'],base).parent)
    for s in request['background_scenarios']:
        if s['response'] is not None:_response(session.document(s['response']),None,session,located(s['response'],base).parent)
    expected=[(p['id'],r['id'],b['id']) for p in request['points'] for r in rs for b in request['background_scenarios']]
    cells=request['templates'];require(type(cells) is list and len(cells)==len(expected)<=128,'complete bounded point/response/background product required')
    require([(c['point_id'],c['response_id'],c['background_id']) for c in cells]==expected,'complete ordered cell census required')
    for c in cells:
        keys(c,('point_id','response_id','background_id','template','mc_interpretation'))
        require(c['mc_interpretation'] in ('supplied_Poissonized_groups_and_source_MC_constraints','unqualified'),'explicit finite-MC auxiliary interpretation required')
        if c['template'] is not None:
            template=st.validate_template(session.document(c['template']))
            template_base=located(c['template'],base).parent
            for evidence in [*template['grounding'],*[q for channel in template['channels'] for sample in channel['samples'] for q in sample['provenance']['evidence']]]:
                _card_bytes(evidence,session,template_base)
    for p in (request['generation_policy'],request['analysis_policy'],request['inference_policy']):session.document(p)
    keys(request['child_seconds'],('generation','analysis','inference'))
    for v in request['child_seconds'].values():require(type(v) is int and 1<=v<=86400,'bounded future child scope required')
    nonempty=[s for s in request['background_scenarios'] if s['response'] is not None]
    require(len({(str(located(s['response'],base)),s['response']['sha256']) for s in nonempty})<=1,'background scenarios must share one complete same-event joint response, not independent reweighted cohorts')
    for s in nonempty:
        require(s['anchor'] in [a['point'] for a in session.document(s['response'])['anchors']],'background anchor absent from complete joint source')
    session.finish()
    return request,session,base


def _response(doc, scenarios, session, base):
    require(doc['operation']=='fixed_event_migrations','same-original-event reconstructed response required')
    for p in [*doc['source_pins'],doc['object_contract'],doc['selection'],*[a['events'] for a in doc['anchors']]]:
        # The existing response API has an id/reference pin; ordinary task pins
        # retain exact bytes, while the adapter validates its complete graph.
        path=Path(p['path']);path=path if path.is_absolute() else base/path
        own=session.capture(path);require(own['sha256']==p['sha256'],'response source hash mismatch')
    if 'category_support' in doc:
        p=doc['category_support'];own=session.capture(Path(p['path']) if Path(p['path']).is_absolute() else base/p['path']);require(own['sha256']==p['sha256'],'support hash mismatch')
    require('numerical_projection' not in doc,'numerical projection is a separate source consumer')
    coordinates=[a['point'] for a in doc['anchors']]
    if scenarios is not None:require([s['coordinate'] for s in scenarios]==coordinates,'every joint response anchor must be a requested scenario')
    require(doc['normalization']['meaning'].strip(),'explicit original cross-section/exposure normalization required')
    # Early use of the actual adapter admission catches group/weight/source
    # mismatches and retains a single complete input graph before any output.


def located(ref, base):
    p=Path(ref['path']);return p if p.is_absolute() else Path(base)/p


def _card_bytes(ref, session, base):
    p=located(ref,base)
    return session.file({'path':str(p),'sha256':ref['sha256'],'size':p.stat().st_size})[0]


def _conventions(conventions):
    required(conventions,('generation','shower'))
    keys(conventions,('generation','shower'))
    required(conventions['generation'],('beam_pdg','energy_gev','order','scheme','jet_multiplicities'))
    keys(conventions['generation'],('beam_pdg','energy_gev','order','scheme','jet_multiplicities'))
    required(conventions['shower'],('backend','merging_scale_gev','max_jets'))
    keys(conventions['shower'],('backend','merging_scale_gev','max_jets'))
    g=conventions['generation']; sh=conventions['shower']
    require(type(g['beam_pdg']) is list and len(g['beam_pdg'])==2 and all(type(p) is int for p in g['beam_pdg']),'two explicit beam identities required')
    require(type(g['energy_gev']) is list and len(g['energy_gev'])==2 and all(number(e)>0 for e in g['energy_gev']),'two explicit beam energies required')
    require(g['scheme'] in gen.SCHEMES and g['order']==gen.SCHEMES[g['scheme']],'supported compatible explicit matching convention required')
    require(type(g['jet_multiplicities']) is list and g['jet_multiplicities'] and all(type(j) is int and j>=0 for j in g['jet_multiplicities']) and sorted(set(g['jet_multiplicities']))==g['jet_multiplicities'],'explicit ordered multiplicity census required')
    require(sh['backend']=='PYTHIA8' and number(sh['merging_scale_gev'])>=0 and type(sh['max_jets']) is int and sh['max_jets']==max(g['jet_multiplicities']),'explicit compatible shower convention required')


def _shower(config, contract, point, session, base, source_base, conventions):
    required(contract,('particle_mass_bindings','decay_fraction_bindings','visible_pdgs'))
    keys(contract,('schema_version','parameter_bindings','particle_mass_bindings','decay_fraction_bindings','visible_pdgs','settings','particle_masses','invisible_pdgs','decays','source_pins','assumptions'))
    require(type(contract['schema_version']) is int and contract['schema_version']==1,'explicit hidden-shower contract schema1 required')
    require(contract['source_pins'] and contract['assumptions'],'hidden-shower source/lifetime assumptions required')
    for p in contract['source_pins']:session.file({**p,'path':str(located(p,source_base))})
    _conventions(conventions)
    require(all(config['generation'][k]==v for k,v in conventions['generation'].items()) and
            all(config['shower'][k]==v for k,v in conventions['shower'].items()),'operative generation/matching conventions differ from supplied recipe')
    require(config['cards']['pythia'] is not None,'complete supplied hidden-shower card required')
    raw=_card_bytes(config['cards']['pythia'],session,base).decode()
    rows=[line.split('#',1)[0].strip() for line in raw.splitlines() if '=' in line.split('#',1)[0]]
    pairs=[tuple(x.strip() for x in r.split('=',1)) for r in rows]
    hidden={k:v for k,v in pairs if k.startswith('HiddenValley:')}
    require(len(hidden)==sum(k.startswith('HiddenValley:') for k,v in pairs),'duplicate hidden settings forbidden')
    setting_keys={'HiddenValley:Ngauge','HiddenValley:nFlav','HiddenValley:FSR','HiddenValley:fragment','HiddenValley:alphaOrder','HiddenValley:Lambda','HiddenValley:pTminFSR','HiddenValley:probVector'}
    require(setting_keys<=set(hidden) and set(hidden)==set(contract['settings']) and all(gen.literal(hidden[k])==v for k,v in contract['settings'].items()),'complete literal hidden settings must match the supplied card; no default substitution')
    masses={int(k.split(':')[0]):float(gen.literal(v)) for k,v in pairs if re.fullmatch(r'\d+:m0',k)}
    require(masses=={int(k):number(v) for k,v in contract['particle_masses'].items()},'every supplied hidden particle mass must match')
    require(type(contract['particle_mass_bindings']) is list and contract['particle_mass_bindings'],'explicit particle mass bindings required')
    for binding in contract['particle_mass_bindings']:
        keys(binding,('axis','pdg'));require(binding['axis'] in point and type(binding['pdg']) is int and masses.get(binding['pdg'])==point[binding['axis']],'grid coordinate differs from supplied shower particle mass')
    params=gen.parameter_values(_card_bytes(config['cards']['parameter'],session,base).decode())
    require(contract['parameter_bindings'],'explicit mediator SLHA binding required')
    for m in contract['parameter_bindings']:
        keys(m,('axis','block','codes'));require(m['axis'] in point and params[(m['block'].lower(),tuple(m['codes']))]==point[m['axis']],'grid/operative SLHA binding mismatch')
    decay_lines=[(k,v) for k,v in pairs if re.fullmatch(r'\d+:(?:oneChannel|addChannel|mayDecay|isVisible)',k)]
    require(contract['decays'] and decay_lines==[tuple(x) for x in contract['decays']],'complete ordered visibility/lifetime/branching card rows required')
    fractions=contract['decay_fraction_bindings']
    require(type(fractions) is list and fractions,'explicit decaying-particle/fraction bindings required')
    active=[]
    for binding in fractions:
        keys(binding,('axis','pdg'));require(binding['axis'] in point and 0<=number(point[binding['axis']])<=1 and type(binding['pdg']) is int and binding['pdg'] in masses,'explicit physical decay fraction required');active.append(binding['pdg'])
    require(len(set(active))==len(active),'unique decaying particles required')
    visible=contract['visible_pdgs'];require(type(visible) is list and all(type(x) is int and x>0 for x in visible) and len(set(visible))==len(visible),'explicit visible daughter census required')
    invisible=contract['invisible_pdgs']
    require(type(invisible) is list and invisible and len(set(invisible))==len(invisible) and all(type(x) is int and x in masses and x not in active and x not in visible for x in invisible),'explicit distinct invisible hidden daughter identities required')
    flags=dict(decay_lines)
    require(all(gen.literal(flags.get(str(x)+':mayDecay','on')) is False and gen.literal(flags.get(str(x)+':isVisible','on')) is False for x in invisible),'invisible daughters must be explicitly stable and invisible in the operative card')
    for binding in fractions:
        pdg=binding['pdg']
        require(gen.literal(flags.get(str(pdg)+':mayDecay','off')) is True,'each active dark meson must explicitly decay in the operative card')
        channel_keys=[k.split(':')[1] for k,v in decay_lines if k.startswith(str(pdg)+':') and k.split(':')[1] in ('oneChannel','addChannel')]
        require(channel_keys and channel_keys[0]=='oneChannel' and channel_keys.count('oneChannel')==1,'oneChannel must initialize each ordered decay table before its addChannel rows')
        channels=[]
        for k,v in decay_lines:
            if k.startswith(str(pdg)+':') and k.split(':')[1] in ('oneChannel','addChannel'):
                tokens=v.split();require(len(tokens)>=5 and tokens[0]=='1','explicit active decay channel required')
                br=Fraction(tokens[1]);daughters=[int(x) for x in tokens[3:]]
                require(br>=0 and all(abs(x) in masses or abs(x) in visible for x in daughters),'explicit hidden daughter masses required')
                all_invisible=all(abs(x) in invisible for x in daughters)
                if all_invisible and br>0:require(masses[pdg]>sum(masses[abs(x)] for x in daughters),'hidden decay threshold must remain open at every grid point')
                channels.append((br,all_invisible))
        require(channels and sum(x[0] for x in channels)==1 and sum(x[0] for x in channels if x[1])==Fraction(str(point[binding['axis']])),'complete per-meson branching fractions must realize declared r_inv; no threshold-floor relabel')


def inputs(task, base):
    d,s,b=_capture(task,base);files=_expanded(d,s,b)
    s.finish();return files


def _analysis_spec(d,point,session,base):
    from ravel.workflow.science import validate,task_inputs
    task=session.document(point['analysis'])
    require(task.get('backend') in ('rivet','rivet-built','simpleanalysis-built','analysis-ir'),'existing supplied-event native or typed analysis route required')
    spec=_spec('analyze',task,d,session.document(d['analysis_policy']),d['child_seconds']['analysis'])
    validate(spec)
    # Use the future child base now: relative scientific asset paths must be
    # explicitly rebound before publishing a moved self-contained specification.
    task_inputs(spec,base)
    return spec


def _expanded(d,s,b):
    files=[Path(p['path']) for p in s.pins.values()]
    for point in d['points']:
        if point['generation'] is not None:files+=gen.inputs({'config':point['generation']['path']},b)
        if point['analysis'] is not None:
            from ravel.workflow.science import task_inputs
            files+=task_inputs(_analysis_spec(d,point,s,b),b)
        if point['response'] is not None:files+=dr.inputs({'request_file':point['response']['path']},b)
    for bg in d['background_scenarios']:
        if bg['published_model'] is not None:
            files+=pm.inputs({'input':bg['published_model']['path']},b)
        if bg['response'] is not None:files+=dr.inputs({'request_file':bg['response']['path']},b)
    return sorted(set(Path(p).absolute() for p in files))


def inputs_for_spec(spec, base):
    d,_,_= _capture(spec['task'],base)
    require(spec.get('goal_binding')==d['goal_binding'],'outer ordinary original goal must equal the recipe parent')
    return inputs(spec['task'],base)


def execution_seconds(task, base):return 60


def write_report(result, out):
    """Existing ordinary report route: whole cells, never successful curves only."""
    from ravel.workflow.validation_io import _source_pin_bytes
    for p in result['output_inventory']:_source_pin_bytes(p,limit=16*1024**2)
    destination=Path(out)/'svj-recipe-report';destination.mkdir(parents=True,exist_ok=False)
    atomic_json(destination/'cells.json',result['cells'])
    lines=['# Supplied semi-visible-jet scan recipe','',result['scope'],'',
           f"Study {result['study_id']}; analysis {result['analysis']['id']}, {result['analysis']['energy_tev']} TeV, {result['analysis']['lumi_fb']} fb−1.", '',
           '| Cell | State | Outstanding obligations |','|---|---|---|']
    for c in result['cells']:
        lines.append('| '+c['id']+' | '+c['state']+' | '+'; '.join(c['obligations']).replace('|','/')+' |')
    (destination/'report.md').write_text('\n'.join(lines)+'\n')
    return [{'id':'svj-full-grid','files':['svj-recipe-report/cells.json','svj-recipe-report/report.md'],
             'scope':SCOPE,'complete_cell_count':len(result['cells'])}]


def _spec(mode, task, d, policy, seconds):
    return {'schema_version':2,'mode':mode,'source':d['source'],'assumptions':d['assumptions'],
            'max_seconds':seconds,'approval_mode':'physicist','max_attempts':1,'task':task,
            'review_policy':policy,'goal_binding':d['goal_binding']}


def _template(d, cell, response, scenario, background, session, out, *, writer=None):
    """Bind a complete supplied uncertainty model to actual all-bin response.

    Keep the entire cross-scenario covariance. The independent-bin HistFactory
    auxiliary projection is allowed only with an explicit Poissonized-law
    assumption, diagonal within this cell, and exact nominal/sumw2 parity.
    """
    template=session.document(cell['template'])
    template_base=located(cell['template'],session.base).parent
    # Derived child paths keep the original source hashes and numerical model.
    # Explicit path rebinding is needed when the template changes directory.
    for q in [*template['grounding'],*[q for c in template['channels'] for sample in c['samples'] for q in sample['provenance']['evidence']]]:
        q['path']=str(located(q,template_base))
    src_doc=session.document(background['published_model']);source=pm.load_published_model(src_doc,located(background['published_model'],session.base).parent)
    contract=st.build_signal_template(source,template,located(cell['template'],session.base).parent)
    dest=response['destination_ids'];n=len(dest);index=[a['point'] for a in response['anchors']].index(scenario['coordinate'])
    w=response['weight_name'];moment=response['weights'][w];values=moment['normalized_values'];cov=moment['conditional_group_covariance']
    require(moment['moment_scope']=='conditional_independent_group_Poisson_Gram_fixed_denominator' and cell['mc_interpretation']=='supplied_Poissonized_groups_and_source_MC_constraints','expected template needs explicit compatible MC auxiliary law; delta/fixed-N covariance cannot become independent bins')
    mapped=[dest.index(b['id'])+index*n for b in d['analysis']['bins']]
    require(all(response['group_marks'][w][g][i]>=0 for g in response['group_ids'] for i in mapped),'expected template needs nonnegative selected independent group support for supplied finite-MC auxiliary law; moments alone do not establish this law')
    require(all(cov[i][j]==0 for i in mapped for j in mapped if i!=j),'correlated/cancelling bins require existing complete marked likelihood, not diagonal errors')
    supplied={(c['name'],s['name'],i):(s['data'][i],s['mc_stat']) for c in template['channels'] for s in c['samples'] for i in range(len(s['data']))}
    require(set(supplied)=={(b['channel'],b['sample'],b['index']) for b in d['analysis']['bins']},'every SR/CR signal bin must occur exactly once in the original requested basis')
    for b,i in zip(d['analysis']['bins'],mapped):
        v,stat=supplied[b['channel'],b['sample'],b['index']]
        require(stat['mode']=='supplied' and v==values[i] and stat['sumw2'][b['index']]==cov[i][i],'all-bin template nominal/MC moments differ from response')
    emit = atomic_json if writer is None else writer
    paths={}
    for name,doc in [('template.json',template),('workspace.json',contract.workspace()),('contract.json',contract.manifest())]:
        emit(out/name,doc);paths[name]=pin(out/name)
    bridge={'schema_version':1,'published_model':{'path':str(located(background['published_model'],session.base)),'sha256':background['published_model']['sha256']},'template':{k:paths['template.json'][k] for k in ('path','sha256')}}
    emit(out/'signal-template-input.json',bridge)
    return {'paths':paths,'bridge':pin(out/'signal-template-input.json'),'source_workspace':source.manifest()['workspace_compact_sha256'],
            'source_document':session.canonical(background['published_model']),'uncertainty':'Exact supplied all-modifier model; full joint scenario covariance retained outside the separate per-cell independent-bin likelihood assumption.'}


def run(task, base, output):
    d,session,b=_capture(task,base)
    files=_expanded(d,session,b)
    require(len(files)<=4096 and sum(p.stat().st_size for p in files)<=200*1024**2,'complete source graph exceeds declared recipe admission budget')
    original=[gen._generated_pin(p) for p in files]
    out=Path(output).absolute();require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),'fresh recipe child output required')
    require(not any(Path(p).is_relative_to(out) for p in session.pins),'output cannot contain source')
    out.mkdir(parents=True)
    generated={}
    def hold(root):
        for path in sorted(Path(root).rglob('*')):
            if path.is_file():
                observed=pin(path)
                require(str(path) not in generated or generated[str(path)]==observed,'generated recipe member changed after its producing operation')
                generated[str(path)]=observed
    gpolicy=session.document(d['generation_policy']);ipolicy=session.document(d['inference_policy'])
    report={'schema_version':1,'kind':'svj-study-recipe','status':'passed','status_scope':SCOPE,'generated_events':0,'fits':0,'physics_validated':False,'execution_authorized':False,
      'study_id':d['study_id'],'delivery':d['delivery'],'generation_conventions':d['generation_conventions'],
      'goal_binding':d['goal_binding'],'analysis':d['analysis'],'axes':d['axes'],'response_scenarios':d['response_scenarios'],'background_scenarios':d['background_scenarios'],
      'points':[],'cells':[],'expected_quantity_census':['minus2sigma','minus1sigma','median','plus1sigma','plus2sigma'],'assumptions':d['assumptions'],
      'original_task_complete':False,'scope':'Supplied full-grid recipe and conditional all-bin inputs. No native generation, calibrated response, statistical accuracy or published reproduction.'}
    responses={};backgrounds={};background_paths={};cache={}
    for bg in d['background_scenarios']:
        if bg['response'] is not None:
            identity=bg['response']['sha256']
            if identity not in cache:
                path=out/('background-'+bg['id']);bundle,_=dr.run({'request_file':bg['response']['path']},b,path);cache[identity]=(bundle,path);hold(path)
            bundle,path=cache[identity];backgrounds[bg['id']]=bundle;background_paths[bg['id']]=path
    for point in d['points']:
        row={'id':point['id'],'coordinate':point['coordinate'],'generation':None,'analysis':None,'response':None,'obligations':[]}
        if point['generation'] is None:row['obligations'].append('Complete source-compatible UFO/runtime/matching/shower cards and each mass/branching/width setting.')
        else:
            from ravel.workflow.model_event_plan import prepare
            req={'schema_version':1,'config':{'path':str(located(point['generation'],b)),'sha256':point['generation']['sha256']},'review_policy':{'path':str(located(d['generation_policy'],b)),'sha256':d['generation_policy']['sha256']},'supervisor_seconds':d['child_seconds']['generation'],'goal_binding':d['goal_binding']}
            row['generation']=prepare(req,base_dir=b,output_dir=out/('generation-'+point['id']));hold(out/('generation-'+point['id']))
        if point['analysis'] is None:row['obligations'].append('Source-compatible supplied-event analysis task/runtime and native output/reference checks; generated future files cannot stand in as current inputs.')
        else:
            dest=out/('analysis-'+point['id']);dest.mkdir()
            spec=_analysis_spec(d,point,session,dest)
            atomic_json(dest/'science.json',spec);hold(dest)
            row['analysis']={'specification':pin(dest/'science.json'),'execution_authorized':False,'actual_analysis_completed':False,'next_command':['ravel','plan','--rundir','<fresh-analysis-run>','--spec',str(dest/'science.json')]}
        if point['response'] is None:row['obligations'].append('Complete original generated/reconstructed cohort and all same-event joint response anchors, including rejected events and every weight.')
        else:
            bundle,_=dr.run({'request_file':point['response']['path']},b,out/('response-'+point['id']));hold(out/('response-'+point['id']))
            doc=session.document(point['response']);bundle['anchors']=doc['anchors'];bundle['weight_name']=doc['weight_name']
            require(set(b['id'] for b in d['analysis']['bins'])<=set(bundle['destination_ids']),'all fitted SR/CR destinations required')
            responses[point['id']]=bundle;row['response']={'complete':pin(out/('response-'+point['id'])/'complete-response.json'),'events':bundle['events'],'groups':bundle['group_ids'],
                'marked_MC':bundle.get('existing_marked_MC_handoff'),'joint_covariance_retained':True}
        report['points'].append(row)
    for cell in d['templates']:
        name='--'.join(cell[k] for k in ('point_id','response_id','background_id'));row={'id':name,**cell,'state':'blocked','obligations':[],'expected_specification':None}
        response=responses.get(cell['point_id']);bg=next(x for x in d['background_scenarios'] if x['id']==cell['background_id']);scenario=next(x for x in d['response_scenarios'] if x['id']==cell['response_id'])
        if d['analysis']['unresolved_bins']:row['obligations'].append('Unresolved full fitted SR/CR basis: '+', '.join(x['id'] for x in d['analysis']['unresolved_bins']))
        if response is None:row['obligations'].append('Missing complete same-event signal response.')
        if bg['published_model'] is None:row['obligations'].append('Missing full all-channel likelihood/auxiliary background source; SR post-fit yields cannot substitute.')
        if cell['template'] is None:row['obligations'].append('Missing complete all-bin signal and shared nuisance variation model.')
        if bg['response'] is not None:
            bundle=backgrounds[bg['id']];bd=session.document(bg['response']);idx=[a['point'] for a in bd['anchors']].index(bg['anchor']);n=len(bundle['destination_ids'])
            vals=bundle['weights'][bd['weight_name']]['normalized_values'][idx*n:(idx+1)*n]
            row['background_response']={'complete':pin(background_paths[bg['id']]/'complete-response.json'),'anchor':bg['anchor'],'values':dict(zip(bundle['destination_ids'],vals)),'joint_covariance_retained':True}
            if bg['published_model'] is not None:
                src=pm.load_published_model(session.document(bg['published_model']),located(bg['published_model'],b).parent);signal={(r['channel'],s) for r in src.manifest()['signal'] for s in r['sample_names']}
                ws=src.workspace()
                for bin_ in d['analysis']['bins']:
                    channel=next(c for c in ws['channels'] if c['name']==bin_['channel']);value=math.fsum(s['data'][bin_['index']] for s in channel['samples'] if (channel['name'],s['name']) not in signal)
                    require(value==row['background_response']['values'][bin_['id']],'hypothetical background model must match coherent all-bin response anchor')
        if not row['obligations']:
            cellout=out/'cells'/name;cellout.mkdir(parents=True)
            try:
                row['template_construction']=_template(d,cell,response,scenario,bg,session,cellout)
            except ValueError as e:
                # A missing compatible inference law is a per-cell obligation;
                # source/numerical/template inconsistencies remain hard failures.
                if 'expected template needs' not in str(e) and 'correlated/cancelling bins' not in str(e):raise
                row['obligations'].append(str(e))
            else:
                spec=_spec('signal-template',{'input':row['template_construction']['bridge']['path'],'operation':'inference'},d,ipolicy,d['child_seconds']['inference'])
                from ravel.workflow.science import validate as admit
                admit(spec);atomic_json(cellout/'expected-science.json',spec)
                row['expected_specification']=pin(cellout/'expected-science.json');row['state']='prepared_unapproved'
                row['interpretation']='Report expected five-quantile CLs only; the existing engine also retains its observed branch, which is not a projected discovery/exclusion claim.'
        if 'template_construction' in row:hold(cellout)
        report['cells'].append(row)
    require(len(report['cells'])==len(d['templates']),'whole-cell denominator changed')
    session.finish();require(original==[gen._generated_pin(p) for p in _expanded(d,session,b)],'complete recipe source graph changed')
    report['input_pins']=original
    report['prepared_cells']=sum(c['state']=='prepared_unapproved' for c in report['cells']);report['blocked_cells']=len(report['cells'])-report['prepared_cells']
    # Ending hashes bind every generated member, including child graph outputs;
    # return only after originals and all delivery bytes are revalidated.
    hold(out)
    report['output_inventory']=[generated[p] for p in sorted(generated)]
    require(sum(p['size'] for p in report['output_inventory'])<=MAX_DELIVERY_BYTES,'bounded complete recipe delivery required')
    require(d['delivery']['filename']!='svj-recipe.json','delivery cannot replace the internal custody receipt')
    write_delivery(out,d['delivery'],report,report['cells']);hold(out)
    report['output_inventory']=[generated[p] for p in sorted(generated)]
    atomic_json(out/'svj-recipe.json',report)
    try:
        session.finish()
        for p in report['output_inventory']:require(pin(p['path'])==p,'generated recipe member changed before completion')
        receipt=pin(out/'svj-recipe.json')
        require(sum(p['size'] for p in report['output_inventory'])+receipt['size']<=MAX_DELIVERY_BYTES,'completion receipt exceeds the complete recipe delivery budget')
        from ravel.workflow.validation_io import _source_pin_bytes
        require(json.loads(_source_pin_bytes(receipt,limit=16*1024**2))==report,'ending recipe receipt changed')
        require(original==[gen._generated_pin(p) for p in _expanded(d,session,b)],'ending complete recipe input changed')
    except Exception:
        (out/'svj-recipe.json').rename(out/'failed-svj-recipe.json')
        raise
    return report
