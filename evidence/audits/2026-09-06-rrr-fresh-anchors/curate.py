"""Deterministic small-file projections. Standard library; never imports producer code."""
from pathlib import Path, PurePosixPath
import csv, hashlib, io, json, math, re, runpy
HERE = Path(__file__).resolve().parent
ORIGINAL_SOURCES = runpy.run_path(str(HERE / 'source_roles.py'))['ORIGINAL_SOURCES']
QUANTILES = ['observed','expected_minus2','expected_minus1','expected_median','expected_plus1','expected_plus2']
POINTS = [(50,45,56),(100,98,5),(150,140,22)]
COPIES = {'figures/fresh-anchor-diagnostics.png':'figure_png','figures/fresh-anchor-diagnostics.pdf':'figure_pdf','tables/anchors.csv':'anchors_csv','tables/fractions.csv':'fractions_csv'}

def strict(raw):
    def pairs(items):
        out = {}
        for k,v in items:
            if k in out: raise ValueError('Duplicate JSON key: '+k)
            out[k]=v
        return out
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))

def encoded(value): return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def digest(raw): return hashlib.sha256(raw).hexdigest()
def safe(root, name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or p.as_posix()!=name or any(x in ('.','..') for x in p.parts): raise ValueError('Unsafe relative path')
    root=Path(root)
    if root.is_symlink(): raise ValueError('Symlink root')
    out=root
    for part in p.parts:
        out=out/part
        if out.is_symlink(): raise ValueError('Symlink source/artifact')
    return out

def csv_bytes(rows):
    f=io.StringIO(newline='');w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows);return f.getvalue().encode()

def primary_rows(raw, index, dependent_count):
    """Parse only the exact pinned HEPData scalar-list serialization, not generic YAML."""
    chunks=re.split(r'^- header: ',raw.decode(),flags=re.M)[1:]
    if len(chunks)!=dependent_count+2: raise ValueError('Unexpected primary table structure')
    out=[]
    for chunk in chunks:
        values=re.findall(r'^  - \{value: ([-+0-9.eE]+)\}$',chunk,flags=re.M)
        if len(values)!=75: raise ValueError('Unexpected primary table row population')
        out.append({'header':chunk.splitlines()[0], 'value':float(values[index])})
    return out

def project(raw):
    d={k:strict(v) for k,v in raw.items() if ORIGINAL_SOURCES[k]['path'].endswith('.json')}
    anchors=[]
    for mass,lsp,index in POINTS:
        fit=d[f'anchor{mass}_exclusion'];model=d[f'anchor{mass}_model']
        refs=[x for x in d['limit_reference']['points'] if x['point_id']==f'm{mass}_m{lsp}']
        frefs=[x for x in d['fraction_reference']['points'] if x['point_id']==f'm{mass}_m{lsp}']
        if len(refs)!=1 or len(frefs)!=1: raise ValueError('Ambiguous reference point')
        ref=refs[0];fref=frefs[0]
        if mass!=150:
            report=d[f'anchor{mass}_report'];inc=report['inclusive'];native=report['native'];N=report['policy']['original_fresh_events']
            limits=report['limits'];bins=report['bins'];unions=report['unions']
            receipts={family:[{'stage':stage,'record_role':f'anchor{mass}_{family}_receipt_{stage}', 'receipt_sha256':item['receipt_sha256']} for stage,item in sorted(pop['receipts'].items())] for family,pop in report['producer_receipts'].items()}
            channels=[]
            for b in bins:
                channels.append({'channel':b['channel'],'selected_events':b['selected_events'],'sumw_pb':b['sumw_pb'],'sumw2_pb2':b['sumw2_pb2'],'nominal_yield':b['nominal_yield'],'mapping':b['mapping'],'likelihood_mc_constraint':b['likelihood_mc_constraint'],'histogram_relative_mc':b['histogram_relative_mc'],'diagnostic_5percent':b['diagnostic_5percent'],'streams':[{'N':N,'selected':b['selected_events'],'sigma_pb':native['one_parton_sigma_lo_pb'],'K':native['K']}]})
            union_rows=[{k:u[k] for k in ('category','selected_events','sumw_pb','sumw2_pb2','histogram_relative_mc')} for u in unions]
            model_scope=report['model_identity']
        else:
            report=d['anchor150_report'];inc={'sigma_lo_pb':report['inclusive_LO_pb'],'integration_error_pb':report['inclusive_integration_error_pb'],'original_events':d['anchor150_inclusive']['events']['n_events']}
            sample=next(x for x in report['samples'] if x['sample']=='nominal_pool_60k');N=sample['original_events']
            moment_rows={x['category']:x['nominal_60k'] for x in d['anchor150_moments']['rows']}
            exemplar=next(iter(moment_rows.values()));native={'K':report['K'],'one_parton_sigma_lo_pb':exemplar['sigma_pb'],'one_parton_sigma_after_K_pb':exemplar['sigma_times_K_pb']}
            channels=[]
            for b in model['channels']:
                p=moment_rows[b['channel']];rel=p['histogram_relative_mc_error']
                channels.append({'channel':b['channel'],'selected_events':p['selected_events'],'sumw_pb':p['retained_histogram_selected_rate_pb'],'sumw2_pb2':p['histogram_sumw2_pb2'],'nominal_yield':b['nominal_yield'],'mapping':b['mapping'],'likelihood_mc_constraint':b['mc_stat_modifier'],'histogram_relative_mc':rel,'diagnostic_5percent':'unresolved' if rel is None else ('meets_target' if rel<=.05 else 'exceeds_target'),'streams':p['streams']})
            union_rows=[]
            for name in ('SR_high','SR_low'):
                p=moment_rows[name]
                union_rows.append({'category':name,'selected_events':p['selected_events'],'sumw_pb':p['retained_histogram_selected_rate_pb'],'sumw2_pb2':p['histogram_sumw2_pb2'],'histogram_relative_mc':p['histogram_relative_mc_error']})
            limits=[]
            for i,(q,mu,fb) in enumerate(zip(QUANTILES,[sample['observed_mu']]+sample['expected_mu'],[sample['observed_sigma95_fb']]+sample['expected_sigma95_fb'])):
                reference=ref['observed_sigma95_pb'] if i==0 else ref['median_expected_sigma95_pb'] if i==3 else None
                limits.append({'quantile':q,'mu95':mu,'inclusive_sigma95_pb':fb/1000,'inclusive_sigma95_fb':fb,'generated_one_parton_sigma95_pb':mu*native['one_parton_sigma_after_K_pb'],'inclusive_generator_integration_only_error_pb':mu*report['K']*inc['integration_error_pb'],'reference_sigma95_pb':reference,'ratio_to_reference':None if reference is None else fb/1000/reference,'residual_percent':None if reference is None else 100*(fb/1000/reference-1),'reference_status':'expected_band_not_supplied' if reference is None else 'supplied_central_only','public_uncertainty':None})
            receipts={'scope':'Four derivative stages and their completed native parents are inherited from anchor150_completion; this projection does not replay those validators.'}
            model_scope={'production':'four degenerate selectron/smuon states; no produced staus','pooling':'original-exposure weighted 20k + 40k, not an independent third sample','model_transfer':'Reference-model equivalence, detector calibration and new mixing diagonalization are not established.'}
        numerics={k:fit['inference'][k] for k in ('method','test_stat','level','root_cls_atol','root_cls_max_error','fresh_check_evaluations','fresh_check_context','backend','precision','fit_tolerance','coverage_validated','model_sha256','data_sha256')}
        anchors.append({'point_id':f'm{mass}_m{lsp}','parent_GeV':mass,'lsp_GeV':lsp,'delta_m_GeV':mass-lsp,'original_events':N,'inclusive':inc,'native':native,'limits':limits,'fit_roots':{'observed':fit['obs_limit'],'expected':fit['exp_limits'],'status':fit['limit_status']},'numerical':numerics,'reference':ref,'primary_limit_rows':primary_rows(raw['original_limits_yaml'],index,2),'fraction_reference':{k:v for k,v in fref.items() if k!='regions'}|{'regions':{k:fref['regions'][k] for k in ('SR-S-high','SR-S-low')}},'primary_fraction_rows':{letter:primary_rows(raw['figure_32'+letter],index,1) for letter in 'cdef'},'channels':channels,'unions':union_rows,'model_scope':model_scope,'model_channel_identity':[{'channel':x['channel'],'nonzero_weights':x['nonzero_weights'],'sumw':x['sumw'],'sumw2':x['sumw2'],'nominal_yield':x['nominal_yield'],'mc_stat_modifier':x['mc_stat_modifier']} for x in model['channels']],'mc_policy':model['mc_stat_policy'],'luminosity_pb_inverse':model['luminosity_pb_inverse'],'inherited_receipt_projection':receipts})
    evidence={'schema_version':1,'scope':{'physics_certified':False,'acceptance_certified':False,'coverage_validated':False,'raw_payloads_included':False,'raw_payloads_reread':False,'new_events':0,'new_fits':0,'nominal_points_completed':3,'nominal_points_total':52,'remaining_nominal_points_uncompleted':49,'reference_errors_supplied':False,'reference_truth_denominator_resolved':False,'reference_migration_resolved':False,'precision_checkpoint':'Formal 5% histogram-MC primary checkpoint is 150/140; 50/45 and100/98 comparisons are analogous diagnostics, not new preregistered gates.'},'anchors':anchors,'fractions':d['fraction_report']['rows'],'preserved_failures':{'fraction_initial_schema_failure':{'source_role':'fraction_initial_failed_reader','log_role':'fraction_initial_failure_log','accepted_science_output':False},'fraction_v1_completion':{'source_role':'fraction_rejected_reader','completion_role':'fraction_rejected_complete','status':'rejected_empty_self_hash','science_unchanged_in_v2':True},'figure_v1':{'source_role':'figure_rejected_renderer','status':'legend_overlapped_footer','v2_change':'legend placement only; CSV unchanged'}},'independent_review_roles':['anchor50_review','anchor100_review','anchor150_review','fraction_math_review','fraction_repair_review','figure_review']}
    limits_table=[{'point_id':a['point_id'],**r} for a in anchors for r in a['limits']]
    moments_table=[{'point_id':a['point_id'],'original_events':a['original_events'],**{k:r[k] for k in ('channel','selected_events','sumw_pb','sumw2_pb2','nominal_yield','histogram_relative_mc','diagnostic_5percent')}} for a in anchors for r in a['channels']]
    out={'data/evidence.json':encoded(evidence),'tables/limits.csv':csv_bytes(limits_table),'tables/channel-moments.csv':csv_bytes(moments_table)}
    out.update({name:raw[role] for name,role in COPIES.items()})
    out['source-map.json']=encoded({'schema_version':1,'original_roles':ORIGINAL_SOURCES,'projection':'Selected exact scalar fields and explicitly named arithmetic from authentic small originals. Unshipped raw and full execution custody are inherited, not independently reconstructed.','source_check_scope':'Rehash all selected originals and reproduce projections/copies; no raw events, producer code imports, fits or full execution validation.','copied_artifacts':COPIES,'private_execution_context_included':False})
    return out

def projections(source_root):
    raw={}
    for role,pin in ORIGINAL_SOURCES.items():
        path=safe(source_root,pin['path']);payload=path.read_bytes()
        if len(payload)>10_000_000 or digest(payload)!=pin['sha256']: raise ValueError('Original source changed: '+role)
        raw[role]=payload
    result=project(raw)
    # Fail if a selected source changes during this bounded read.
    for role,pin in ORIGINAL_SOURCES.items():
        if digest(safe(source_root,pin['path']).read_bytes())!=pin['sha256']: raise ValueError('Original changed during curation: '+role)
    return result
