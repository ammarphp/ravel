"""Released SFitter profile/card contracts; planning imports no numerical engine.

The selected-coordinate map embeds omitted physical operators at zero in the
full native sector. It never passes a shortened basis to native prediction code.
"""
import ast
import copy
import math
from pathlib import Path
import re

PROFILES = {'top': ('profile', 'top_fit.yaml', '_TOP_PARAMETER_NAMES'),
            'higgs': ('profile', 'higgs_fit.yaml', '_HIGGS_PARAMETER_NAMES'),
            'spiral': ('spiral', 'spiral_fit.yaml', None),
            'five_point': ('five_point', 'five_point_fit.yaml', None),
            'toy': ('toy', 'top_fit.yaml', None)}
ALGORITHMS = ('flow', 'smc', 'craft')
PHASES = ('run', 'fit', 'plot')
INFERENCE = 'native_profile_and_marginal_measure_unqualified'

def basis(root, profile):
    if profile not in PROFILES: raise ValueError('released SFitter profile required')
    field = PROFILES[profile][2]
    if field is None: return ['x1','x2','x3','x4'] if profile=='toy' else ['x1','x2']
    module=ast.parse((Path(root)/'sfitter/sfitter/likelihood/full_likelihood.py').read_text())
    cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='ProfileLikelihood')
    assignment=next(n for n in cls.body if isinstance(n,ast.Assign) and
                    any(isinstance(t,ast.Name) and t.id==field for t in n.targets))
    value=ast.literal_eval(assignment.value)
    if len(value)!=(22 if profile=='top' else 20) or len(set(value))!=len(value):
        raise ValueError('released physical sector population changed')
    return value

def selection(root, profile, parameters):
    full=basis(root,profile)
    if type(parameters) is not list or not parameters or any(type(p) is not str for p in parameters) or len(set(parameters))!=len(parameters) or any(p not in full for p in parameters):
        raise ValueError('ordered nonempty known parameter subset required')
    if profile not in ('top','higgs') and parameters!=full:
        raise ValueError('diagnostic profile keeps its complete original coordinates')
    return {'full':full,'selected':parameters.copy(),
            'indices':[full.index(p) for p in parameters],
            'fixed_zero':[p for p in full if p not in parameters]}

def yaml_document(raw):
    # Safe YAML is used only to parse an admitted supplied card. No engine import.
    import yaml
    class Unique(yaml.SafeLoader): pass
    def mapping(loader,node,deep=False):
        result={}
        for key_node,value_node in node.value:
            key=loader.construct_object(key_node,deep=deep)
            if type(key) is not str or key in result: raise ValueError('duplicate/nontext native YAML key')
            result[key]=loader.construct_object(value_node,deep=deep)
        return result
    Unique.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
    value=yaml.load(raw,Loader=Unique)
    if type(value) is not dict: raise ValueError('native card mapping required')
    return value

def _settings_source(root, algorithm):
    """Finite exact settings names consumed by the released numerical classes."""
    names=('flow_fitter.py',) if algorithm=='flow' else ('smc_fitter.py','craft.py') if algorithm=='craft' else ('smc_fitter.py',)
    consumed={}
    aliases={'arch_params':'architecture','training_params':'training'}
    for name in names:
        tree=ast.parse((Path(root)/'sfitter/sfitter/fit'/name).read_text())
        for node in ast.walk(tree):
            if not isinstance(node,ast.Subscript) or not isinstance(node.slice,ast.Constant) or type(node.slice.value) is not str:continue
            owner=node.value
            key=None
            if isinstance(owner,ast.Attribute) and isinstance(owner.value,ast.Name) and owner.value.id=='self' and owner.attr.endswith('_params'):
                key={'marginal':'marginalize'}.get(owner.attr[:-7],owner.attr[:-7])
            elif isinstance(owner,ast.Name):key=aliases.get(owner.id)
            if key and key!='smc':consumed.setdefault(key,set()).add(node.slice.value)
    return consumed

def validate_settings(root, params, algorithm, count):
    if algorithm not in ALGORITHMS:raise ValueError('released fitter required')
    sections=_settings_source(root,algorithm)
    if algorithm!='flow':
        common={'batch_size','mcmc_type','mcmc_steps','mcmc_step_size','temperature_steps','resampling_threshold','no_resampling_steps'}
        sections['smc']=common|({'annealing_steps','annealing_beta'} if algorithm=='craft' else set())
        sections['prescale']=common|{'enable'}
        sections['marginalize']=common|{'target_samples_eff','lower_bound_quantile','upper_bound_quantile','n_bins_1d','n_bins_2d'}
        profile=common|{'strategy','n_points','batch_size','gd_learning_rate','gd_steps','parallel_batches','annealing_steps','annealing_beta'}
        sections['profile_1d']=profile;sections['profile_2d']=profile
    top={'run_name','precision','likelihood','sector','datacard','fitter','parameter_names','syst_correlation_rho','corr_eigenvalue_floor','corr_max_shrinkage'}|set(sections)|({'profile'} if algorithm!='flow' else set())|{'sigma','outer_offset','outer_sigma','inner_mag','inner_sigma'}
    if set(params)-top:raise ValueError('unknown native numerical card section')
    for section,required in sections.items():
        v=params.get(section)
        # Native SMC inheritance: section overrides its common smc defaults.
        v={**params.get('smc',{}),**params.get('profile',{}),**(v or {})} if section.startswith('profile_') and algorithm!='flow' else {**params.get('smc',{}),**params.get('marginalize',{}),**(v or {})} if algorithm!='flow' and section=='prescale' else {**params.get('smc',{}),**(v or {})} if algorithm!='flow' and section=='marginalize' else v
        if type(v) is not dict:raise ValueError('native settings section missing: '+section)
        allowed=required|{'mean_init','std_init','adam_betas','adam_eps','weight_decay','lr_scheduler','max_lr','lr_decay_epochs','lr_decay_factor','n_bins'}
        if algorithm!='flow' and section in ('prescale','marginalize'):allowed|=sections['smc']
        if algorithm!='flow' and section=='prescale':allowed|=sections['marginalize']
        # Conditional scheduler branches, not all mutually exclusive keys at once.
        required=required-{'lr_decay_epochs','lr_decay_factor','max_lr','mean_init','std_init'}
        if set(v)-allowed or not required<=set(v):raise ValueError('complete source-defined settings required: '+section)
        for key,value in v.items():
            if key in ('enable','buffer_replacement'):
                if type(value) is not bool:raise ValueError('native Boolean setting required')
            elif type(value) is str:
                enums={'mcmc_type':('standard','langevin'),'optimizer':('adam','lbfgs'),
                       'strategy':('histogram','annealing'),'type':('coupling','maf'),
                       'activation':('ReLU','LeakyReLU','Tanh','ELU','SiLU'),
                       'lr_scheduler':('step','one_cycle','cosine_annealing')}
                if value not in enums.get(key,()):raise ValueError('source-supported numerical option required: '+key)
            elif type(value) is list:
                expected=2 if key=='adam_betas' else count
                if key not in ('mean_init','std_init','adam_betas') or len(value)!=expected or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):raise ValueError('complete native coordinate setting required')
                if key=='std_init' and any(x<=0 for x in value):raise ValueError('positive native standard deviations required')
            elif type(value) not in (int,float) or not math.isfinite(value) or value<0 or value>100_000_000:
                raise ValueError('finite prospectively bounded numerical setting required')
            elif key not in ('weight_decay','no_resampling_steps','annealing_steps','gd_steps') and value==0:
                raise ValueError('positive native numerical allocation required')
            populations={'samples','smc_steps','mcmc_steps','spline_bins','layers','hidden_nodes','batch_size','epochs','log_interval','batches','steps','buffer_size','min_buffer_size','buffer_batches','marginal_bins_1d','marginal_bins_2d','profile_points_1d','profile_points_2d','weight_bins','gd_steps','temperature_steps','no_resampling_steps','annealing_steps','target_samples_eff','n_bins_1d','n_bins_2d','n_points','parallel_batches','sub_batches','sub_batch_size','lr_decay_epochs','n_bins'}
            if key in populations and type(value) is not int:
                raise ValueError('integer native numerical population required')
        for key in ('resampling_threshold','smc_resampling_threshold','target_acceptance'):
            if key in v and not 0<v[key]<=1:raise ValueError('source probability allocation requires (0,1]')
        if 'adam_betas' in v and any(not 0<x<1 for x in v['adam_betas']):raise ValueError('optimizer betas require (0,1)')
        for low,high in (('lower_bound_quantile','upper_bound_quantile'),('weight_lower_bound_quantile','weight_upper_bound_quantile')):
            if low in v and not 0<v[low]<v[high]<1:raise ValueError('ordered interior native quantiles required')
        if section=='training' and algorithm=='craft':
            mode=v['lr_scheduler'];needed={'step':{'lr_decay_epochs','lr_decay_factor'},'one_cycle':{'max_lr'},'cosine_annealing':set()}[mode]
            if not needed<=set(v):raise ValueError('complete selected native scheduler required')
    if algorithm!='flow' and ('profile' in params and (type(params['profile']) is not dict or set(params['profile'])-sections['profile_1d'])):raise ValueError('unknown native profile override')
    if 'syst_correlation_rho' in params and (type(params['syst_correlation_rho']) not in (int,float) or not -1<=params['syst_correlation_rho']<=1):raise ValueError('explicit bounded source nuisance correlation required')
    for key,expected in (('corr_eigenvalue_floor',.001),('corr_max_shrinkage',.10)):
        if key in params and (type(params[key]) not in (int,float) or params[key]!=expected):
            raise ValueError('retained native correlation guard defaults required; broader scientific changes need separate qualification')
    return copy.deepcopy(params)

def compile_card(root, datacard, run_card, profile, parameters, algorithm, *, source_review=None):
    from ravel.physics import sfitter_inputs
    root=Path(root).absolute();run_card=Path(run_card).absolute()
    select=selection(root,profile,parameters);params=yaml_document(run_card.read_text())
    declared_review=params.pop('source_review',None)
    if source_review is not None and declared_review is not None and source_review!=declared_review:
        raise ValueError('explicit review differs from run-card selection')
    source_review=source_review or declared_review
    if source_review is not None:
        source_review={**source_review,'path':str((run_card.parent/Path(source_review['path'])).absolute())}
    if params.get('fitter')!=algorithm or params.get('likelihood')!=PROFILES[profile][0] or params.get('precision')!='double':raise ValueError('native profile/fitter/precision differs')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}',str(params.get('run_name'))):raise ValueError('safe original native run name required')
    if profile in ('top','higgs'):
        if params.get('sector')!=profile:raise ValueError('physical sector differs')
        supplied=params.get('parameter_names',select['full'])
        if supplied!=parameters:raise ValueError('native declared selection differs')
        target=Path(params.get('datacard',''))
        target=target if target.is_absolute() else run_card.parent.parent/target
        if target.absolute()!=Path(datacard).absolute():raise ValueError('native datacard path differs')
        census=sfitter_inputs.inspect_profile_datacard(sfitter_inputs._load(datacard),root,profile,source_review=source_review)
    else:
        if datacard is not None or 'datacard' in params or 'parameter_names' in params:raise ValueError('diagnostic source profile has no measurement card or sector subset')
        census={'observations':0,'bins':0,'population':[],'diagnostic_only':True}
    diagnostic={'spiral':{'sigma'},'five_point':{'outer_offset','outer_sigma','inner_mag','inner_sigma'},'toy':set()}.get(profile,set())
    present=set(params)&{'sigma','outer_offset','outer_sigma','inner_mag','inner_sigma'}
    if present-diagnostic or any(type(params[k]) not in (int,float) or not math.isfinite(params[k]) or params[k]<=0 for k in present):raise ValueError('positive actual diagnostic-profile settings required')
    validate_settings(root,params,algorithm,len(parameters))
    if declared_review is not None:params['source_review']=declared_review
    return {'schema_version':2,'kind':'sfitter_complete_card_contract','profile':profile,'algorithm':algorithm,
            'selection':select,'params':params,'census':census,'inference':INFERENCE,
            'run_card':sfitter_inputs._pin(run_card),
            'datacard':sfitter_inputs._pin(datacard) if datacard is not None else None,
            'source_template':sfitter_inputs._pin(root/'sfitter/params'/PROFILES[profile][1]),
            'physics_validated':False,
            **({k:copy.deepcopy(census[k]) for k in ('native_law_assumptions','scientific_input_support','scientific_input_holds')} if profile in ('top','higgs') else {})}
