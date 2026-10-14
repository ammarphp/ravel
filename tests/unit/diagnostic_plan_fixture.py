"""Fictional supplied plans for numerical and event diagnostics."""
TOLERANCES={'fit_requested':1e-7,'objective_agreement':1e-5,'stationarity':1e-3,'independent_density':1e-7,'gradient_atol':1e-5,'gradient_rtol':1e-4,'step_scale':1e-4}
PROFILE_LIMITS={'adapter_seconds':30,'per_backend_seconds':5,'calls_per_backend':1000,'witness_bytes':65536}
CANDIDATE_LIMITS={'adapter_seconds':30,'numerical_seconds':20,'numpy_and_fd_seconds':12,'jax_seconds':8,'evaluator_calls':256}
REFINE_LIMITS={'adapter_seconds':30,'numerical_seconds':20,'evaluator_calls':64}
CRITERIA={'step_divisors':[4,8],'tolerances':TOLERANCES,'coarse_to_quarter_drift_ratio':[.125,.5],'fine_drift_at_most_coarse_fraction':.5}
CANDIDATE_PLAN={'candidate_selectors':[['numpy',0],['numpy',1],['jax',0],['jax',1],['jax',2]],'trial_statuses':{'numpy':['succeeded','succeeded','interrupted'],'jax':['succeeded']*3}}
REFINE_PLAN={'failed_pairs':[[i,j] for i in (1,2,3,4) for j in (3,4)],'origin_properties':{'arithmetic_parity_passed':False,'all_candidate_checks_passed':False,'original_comparison_passed':False,'paired_profile_completed':False}}
STAGE_IDS=['build','probe_disabled','probe_enabled']
FAILURE={'failure_classes':['resource_floor'],'phases':['prepare','execute'],'execution_phase':'execute'}


def metadata(identity='ANA-0001', *, count=2, format='json', file='result.json'):
    return {'study_identity':identity,'parameter_grid':[{'x':i*.2} for i in range(count)],'dataset_population':['DATA-'+str(i) for i in range(count)],'output':{'format':format,'file':file}}


def intervention(n=6, regions=2):
    names=['REG-'+str(i) for i in range(regions)]
    return {'regions':names,'target_region':names[0],'reference_gap':.2,'confidence_level':.95,'bootstrap_seed':17,'bootstrap_replicates':64,'max_standard_error':1.,'analyzed_events':n,'original_events':n+3,'original_ordinals':list(range(1,n+1)),'trace_metadata':{'model':'MODEL-0001'}}


def signal(regions=2, n=6):
    names=['REG-'+str(i) for i in range(regions)]
    channels=['CH-'+str(i) for i in range(regions)]
    return {'trace_regions':names,'channel_order':channels,'channel_map':[{'channel':channel,'region':region,'equals':{},'lengths':{}} for channel,region in zip(channels,names)],'cross_section_pb':2.,'kfactor':1.5,'luminosity_pb_inverse':10.}
