"""Portable exact source fixture, no upstream module import or numerical job."""
import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import zipfile

ARCHIVE_SHA='dff1721ab88c59fe5919670dbbcd7832c7fc698d40b041faef9f70166920e60f'

def source(tmp):
    archive=Path(__file__).resolve().parents[1]/'fixtures/sfitteragents-6072a79e.zip'
    raw=archive.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ARCHIVE_SHA:raise ValueError('genuine fixed upstream fixture changed')
    root=tmp/'source';root.mkdir()
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=235 or len(set(names))!=235:raise ValueError('complete235 source required')
        for m in z.infolist():
            p=Path(m.filename)
            if p.is_absolute() or '..' in p.parts:raise ValueError('unsafe fixed source member')
            q=root/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(z.read(m));q.chmod((m.external_attr>>16)&0o777)
    _bind_census(tmp,root)
    return root


def _bind_census(tmp,root):
    """The fixture is the reviewed upstream tree with its prose generalized; its census pins these bytes."""
    import os
    from ravel.physics import sfitter_native
    packaged=json.loads((Path(sfitter_native.__file__).parents[1]/'data/sfitter/upstream-source.json').read_text())
    files={rel:hashlib.sha256((root/rel).read_bytes()).hexdigest() for rel in packaged['files']}
    census=tmp/'upstream-source.json';census.write_text(json.dumps({**packaged,'files':files}))
    os.environ[sfitter_native.UPSTREAM_CENSUS_ENV]=str(census)

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def card(tmp,root,profile,parameters,algorithm='flow'):
    from ravel.physics import sfitter_profiles as profiles
    import yaml
    full=profiles.basis(root,profile)
    observation={'ID':'synthetic','name':'nonphysical_software_control','bin_widths':[1.],
      'Meas':{'data':[1.],'modifiers':[{'name':'Pois','type':'pois','data':[0.]},{'name':'stat','type':'stat','data':[1.]}]},
      'Bkg':{'data':[0.],'modifiers':[]},'modifiers':[]}
    document={'observations':[observation],'predictions':[{'ID':'synthetic','name':observation['name'],'data':[1.],
      'modifiers':[{'name':p,'type':'WC','data':[0.]} for p in full]}]}
    cp=tmp/'card.json';cp.write_text(json.dumps(document))
    params=profiles.yaml_document((root/'sfitter/params'/profiles.PROFILES[profile][1]).read_text())
    indices=[full.index(name) for name in parameters]
    def project_coordinates(value):
        if type(value) is dict:
            for key,item in value.items():
                if key in ('mean_init','std_init') and type(item) is list:
                    if len(item)!=len(full):raise ValueError('original fixture coordinate population differs')
                    value[key]=[item[index] for index in indices]
                else:project_coordinates(item)
    project_coordinates(params)
    params.update(run_name='software_only',datacard=str(cp),parameter_names=parameters,fitter=algorithm)
    from source_record_fixtures import card_review
    if profile in ('top','higgs'):params['source_review']=card_review(tmp,root,document)
    if algorithm!='flow':
        common={'batch_size':8,'mcmc_type':'standard','mcmc_steps':1,'mcmc_step_size':.1,'temperature_steps':2,'resampling_threshold':.5,'no_resampling_steps':0}
        if algorithm=='craft':common.update(annealing_steps=1,annealing_beta=.1)
        params={k:params[k] for k in ('run_name','precision','likelihood','sector','datacard','parameter_names','fitter')}
        params.update(smc=common,prescale={'enable':False},marginalize={'target_samples_eff':16,'lower_bound_quantile':.01,'upper_bound_quantile':.99,'n_bins_1d':4,'n_bins_2d':4},profile={'strategy':'histogram','n_points':4,'gd_learning_rate':.1,'gd_steps':1,'parallel_batches':1,'annealing_steps':1,'annealing_beta':.1},profile_1d={},profile_2d={})
        if algorithm=='craft':params.update(architecture={'type':'coupling','activation':'ReLU','spline_bins':4,'layers':1,'hidden_nodes':4,'spline_bound':2.},training={'lr':.01,'batches':2,'sub_batches':1,'sub_batch_size':4,'log_interval':1,'lr_scheduler':'step','lr_decay_epochs':1,'lr_decay_factor':.5})
    if profile in ('top','higgs'):params['source_review']=card_review(tmp,root,document)
    rp=tmp/'card.yaml';rp.write_text(yaml.safe_dump(params))
    return cp,rp,params,document

class Array:
    def __init__(self,shape,values=None):
        self.dtype=SimpleNamespace(str='<f8');self.shape=tuple(shape)
        count=1
        for n in shape:count*=n
        self.raw=b''.join(struct.pack('<d',v) for v in ([1.]*count if values is None else values))
    def tobytes(self,order='C'):assert order=='C';return self.raw

def configuration(tmp,root,profile='top'):
    import sys
    from ravel.physics import sfitter_profiles as profiles, sfitter_native as legacy
    from ravel.workflow.state_io import atomic_json
    full=profiles.basis(root,profile);selected=[full[-1],full[0]]
    cp,rp,_,_=card(tmp,root,profile,selected)
    evidence=tmp/'engineering.txt';evidence.write_text('Synthetic input-admission control only; no measured physics.')
    sem={'schema_version':1,'purpose':'analytic_qualification','observables':[{'ID':'synthetic','name':'nonphysical_software_control','bins':['one'],'representation':'integrated','normalization':'absolute','unit':'pb'}],
      'eft':{'target_basis':full,'source_basis':'native_'+profile,'flavour':'explicit_native_'+profile,'coefficient_unit':'TeV^-2','lambda_unit':'TeV','source_scale_gev':1000.,'target_scale_gev':1000.,'rge_policy':'not_applied_same_scale','conversion':'identity_native_basis','linear':True,'quadratic':profile=='higgs','mixed_pairs':[],'domain':'Engineering-only conditional input','evidence':[pin(evidence)]},
      'uncertainty_policy':('native_top_percent_sources_RFit_component_clamp_named_correlation_capped_shrinkage' if profile=='top' else 'native_higgs_Poisson_Gaussian_RFit_branching_production_EWPO'),'interval_policy':'raw_native_arrays_no_qualified_intervals','sources':[pin(evidence)]}
    sp=tmp/'semantic.json';atomic_json(sp,sem)
    manifest=tmp/'source-manifest.json';known=json.loads(legacy.upstream_census_path().read_text());atomic_json(manifest,{'schema_version':1,'files':known['files']})
    asset=tmp/'site/control.txt';asset.parent.mkdir();asset.write_text('Never imported fake runtime declaration.')
    value={'schema_version':2,'operation':'fixed-vector-qualification','purpose':'analytic_qualification','source':'synthetic complete-profile control','upstream_tree':{'root':str(root),'manifest':pin(manifest)},'trusted_upstream_python':True,'runtime':{'python':pin(Path(sys.executable).resolve()),'site_roots':[str(asset.parent)],'assets':[pin(asset)],'versions':{name:'not_executed' for name in legacy.RUNTIME_PACKAGES},'device':'cpu'},'datacard':pin(cp),'run_card':pin(rp),'semantic_manifest':pin(sp),'vectors':[[0.,0.]],'max_seconds':20,'max_ram_mib':1024,'max_export_bytes':16*1024*1024,'profile':profile,'parameters':selected,'algorithm':'flow','phase':'run','saved_run':None,'production_handoff':None,'inference':profiles.INFERENCE}
    path=tmp/'native-config.json';atomic_json(path,value);return {'config':str(path)},value


def workflow_request(tmp,root,profile='top'):
    """Dedicated complete scientific phase fixture, no old test-suite import."""
    from ravel.workflow import sfitter_workflow as w, agent_graph as g
    from ravel.workflow.state_io import atomic_json,read_json
    task,config=configuration(tmp,root,profile)
    document=read_json(config['datacard']['path']);sem=read_json(config['semantic_manifest']['path'])
    sem['purpose']='supplied_full_study';atomic_json(config['semantic_manifest']['path'],sem)
    config['semantic_manifest']=pin(Path(config['semantic_manifest']['path']))
    request={'schema_version':1,'id':'software_complete','upstream_tree':config['upstream_tree'],
        'sources':sem['sources'],'target':{'observables':sem['observables'],
        'eft':{'basis':sem['eft']['target_basis'],'quadratic':sem['eft']['quadratic'],'mixed_pairs':[],
        'source_scale_gev':1000.,'target_scale_gev':1000.,'coefficient_unit':'TeV^-2','lambda_unit':'TeV','flavour':sem['eft']['flavour']},
        'process':'Synthetic complete study','perturbative_order':'Explicit engineering-only order','model_source':'No physical model'},
        'handoffs':{},'model':{'name':'not-called','reasoning_effort':'high','max_output_tokens':1000},'max_wall_seconds':60,
        'native_profile':{'profile':profile,'parameters':config['parameters'],'algorithm':'flow','run_card':config['run_card']}}
    evidence=sem['sources'][0]
    payloads={'extraction':{'rows':document['observations']},
        'sm_template':{'rows':[{'ID':o['ID'],'name':o['name'],'data':p['data'],'theory_modifiers':o['modifiers'],
            'perturbative_order':request['target']['perturbative_order'],'evidence':evidence} for o,p in zip(document['observations'],document['predictions'])]},
        'parameterization':{'rows':[{'ID':o['ID'],'name':o['name'],'modifiers':p['modifiers'],
            'scan_evidence':evidence,'coupling_sanity_evidence':evidence,'fit_diagnostics':evidence} for o,p in zip(document['observations'],document['predictions'])]},
        'conventions':{'semantic_manifest':config['semantic_manifest']}}
    for phase,payload in payloads.items():
        doc={'schema_version':1,'phase':phase,'target_sha256':g.digest(request['target']),
            'sources':[evidence],'payload':payload,'physics_validated':False,'execution_authorized':False}
        path=tmp/(phase+'.json');atomic_json(path,doc);request['handoffs'][phase]=pin(path)
    return request,config


def higgs_mixture_card(tmp,root,parameters,algorithm='flow'):
    """Separate synthetic three-decay/five-production law, never 5019 data.

    The old WC-only fixture stays unchanged. Active branching values are read
    from the pinned source AST; accepted fractions .2/.3/.5 are invented only
    for an explicitly labelled software control at the SM unit ggF reference.
    """
    import ast
    from fractions import Fraction
    from ravel.physics import sfitter_higgs_support
    from ravel.workflow.state_io import atomic_json
    raw=(root/'sfitter/sfitter/likelihood/sm.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=json.loads(__import__('ravel.physics.sfitter_native',fromlist=['upstream_census_path']).upstream_census_path().read_text())['files']['sfitter/sfitter/likelihood/sm.py']:
        raise ValueError('exact active SM branching source required')
    values={node.targets[0].id:ast.literal_eval(node.value) for node in ast.parse(raw).body
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
            and node.targets[0].id in ('brsmw','brsmz','brsmtau')}
    fractions=[Fraction(1,5),Fraction(3,10),Fraction(1,2)]
    branch=[Fraction(str(values[name])) for name in ('brsmw','brsmz','brsmtau')]
    weights=ast.literal_eval(next(node.value for node in ast.parse(raw).body
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='sm_values' for t in node.targets)))
    ggF=Fraction(str(weights['csgf']))
    cp,rp,params,_=card(tmp,root,'higgs',parameters,algorithm)
    document={'observations':[{'ID':'synthetic_mixture','name':'synthetic_three_decay_five_production',
        'bin_widths':[1.],'Luminosity':[1.],'Decay':['brw','brz','brtau'],
        'Meas':{'data':[1.],'modifiers':[{'name':'Pois','type':'pois','data':[0.]},{'name':'stat','type':'stat','data':[.1]}]},
        'Bkg':{'data':[0.],'modifiers':[]},'modifiers':[{'name':'theory','type':'theo','data':[.01]}]}],
        'predictions':[{'ID':'synthetic_mixture','name':'synthetic_three_decay_five_production','data':[0.],
        'modifiers':[{'name':name,'type':'Higgs','data':[float(f/(b*ggF)) for f,b in zip(fractions,branch)] if name=='csgf' else [0.,0.,0.]}
                     for name in ('csgf','cstth','csvbf','cswh','cszh')]}]}
    atomic_json(cp,document)
    from source_record_fixtures import card_review
    params['source_review']=card_review(tmp,root,document)
    import yaml
    rp.write_text(yaml.safe_dump(params))
    return cp,rp,params,document


def higgs_mixture_configuration(tmp,root,algorithm='flow'):
    from ravel.physics import sfitter_profiles
    from ravel.workflow.state_io import atomic_json
    task,config=configuration(tmp,root,'higgs')
    cp,rp,_,document=higgs_mixture_card(tmp,root,config['parameters'],algorithm)
    config.update(datacard=pin(cp),run_card=pin(rp),algorithm=algorithm)
    semantic=json.loads(Path(config['semantic_manifest']['path']).read_bytes())
    o=document['observations'][0]
    semantic['observables']=[{'ID':o['ID'],'name':o['name'],'bins':['synthetic_bin'],
        'representation':'integrated','normalization':'absolute','unit':'synthetic_dimensionless_signal_strength'}]
    atomic_json(config['semantic_manifest']['path'],semantic);config['semantic_manifest']=pin(Path(config['semantic_manifest']['path']))
    atomic_json(task['config'],config)
    return task,config,document
