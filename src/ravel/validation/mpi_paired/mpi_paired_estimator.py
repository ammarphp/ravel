"""Preregistered paired-MPI estimator; no simulator or optimization is launched."""
import math

from ravel.validation.mpi_paired.mpi_identity_transport import require,event_ids

from statistics import NormalDist
from ravel.validation import diagnostic_plan as plans


def descriptor(plan):
    regions=plans.required(plan,'regions')
    require(type(regions) is list and regions and all(type(x) is str and x for x in regions) and len(set(regions))==len(regions),'distinct supplied exclusive regions required')
    target=plans.required(plan,'target_region')
    require(target in regions,'estimand target must be a declared region')
    plans.positive(plans.required(plan,'reference_gap'),'reference_gap')
    confidence=plans.required(plan,'confidence_level')
    require(type(confidence) in (int,float) and 0<confidence<1,'explicit confidence level required')
    require(type(plans.required(plan,'bootstrap_seed')) is int and plan['bootstrap_seed']>=0,'nonnegative bootstrap seed required')
    plans.positive(plans.required(plan,'bootstrap_replicates'),'bootstrap_replicates',integer=True)
    plans.positive(plans.required(plan,'max_standard_error'),'max_standard_error')
    return regions,regions.index(target)+1


def classify(interval,gap):
    low,high=interval
    if low > -gap:return 'reference_gap_insufficient'
    if low <= -gap and high < 0:return 'effect_of_relevant_magnitude'
    return 'inconclusive'


def category(row,regions):
    selected=[i for i,name in enumerate(regions) if name in row['accepted_regions']]
    require(len(selected)<=1,'multiple supplied exclusive regions')
    return selected[0]+1 if selected else 0


def compare(on_rows,off_rows,on_transport,off_transport,plan):
    """Use every hard-event pair, including events outside the selected regions.

    Only constant, identical, positive weights are admitted by this bounded
    contract. The transport witnesses must come from verify_files, bound by
    supervising-stage provenance; this pure function does not authenticate them.
    """
    import numpy as np
    regions,target=descriptor(plan)
    dimension=len(regions)+1
    gap=plan['reference_gap'];seed=plan['bootstrap_seed'];replicates=plan['bootstrap_replicates']
    alpha=(1-plan['confidence_level'])/2
    require(on_transport.get('status')==off_transport.get('status')=='transport_verified',
            'verified original-content transport required in both arms')
    require(on_transport['mapping']==off_transport['mapping'],'original hard-event pairing differs')
    n=len(on_transport['mapping'])
    require(n>1 and len(on_rows)==len(off_rows)==n,'complete paired population required')
    event_ids([r['event_id'] for r in on_rows],n,'on trace')
    event_ids([r['event_id'] for r in off_rows],n,'off trace')
    weights=[r['weight_pb'] for r in [*on_rows,*off_rows]]
    require(all(type(w) in (int,float) and math.isfinite(w) and w>0 for w in weights),
            'finite positive event weights required')
    require(len({float(w).hex() for w in weights})==1,'identical constant weights required')
    cats=np.asarray([[category(a,regions),category(b,regions)] for a,b in zip(on_rows,off_rows)],dtype=int)
    counts=np.zeros((dimension,dimension),dtype=int)
    np.add.at(counts,(cats[:,0],cats[:,1]),1)
    on=np.sum(counts,axis=1);off=np.sum(counts,axis=0)
    selected_on=int(sum(on[1:]));selected_off=int(sum(off[1:]))
    require(selected_on>0 and selected_off>0,'selected denominator is zero')
    f_on=float(on[target]/selected_on);f_off=float(off[target]/selected_off)
    delta=f_off-f_on
    g_on=((cats[:,0]==target)-f_on*(cats[:,0]>0))/(selected_on/n)
    g_off=((cats[:,1]==target)-f_off*(cats[:,1]>0))/(selected_off/n)
    psi=g_off-g_on
    variance=float(np.sum((psi-np.mean(psi))**2)/(n*(n-1)))
    covariance=float(np.sum((g_on-np.mean(g_on))*(g_off-np.mean(g_off)))/(n*(n-1)))
    half=NormalDist().inv_cdf(1-alpha)*math.sqrt(variance)
    normal=[delta-half,delta+half]
    draws=np.random.default_rng(seed).multinomial(n,counts.reshape(-1)/n,size=replicates).reshape(replicates,dimension,dimension)
    boot_on=np.sum(draws,axis=2);boot_off=np.sum(draws,axis=1)
    denom_on=np.sum(boot_on[:,1:],axis=1);denom_off=np.sum(boot_off[:,1:],axis=1)
    invalid=(denom_on==0)|(denom_off==0)
    bootstrap=None;bootstrap_classification=None
    if not np.any(invalid):
        values=boot_off[:,target]/denom_off-boot_on[:,target]/denom_on
        bootstrap=np.quantile(values,[alpha,1-alpha],method='linear').tolist()
        bootstrap_classification=classify(bootstrap,gap)
    primary_classification=classify(normal,gap)
    precision=math.sqrt(variance)<=plan['max_standard_error']
    agreed=precision and not np.any(invalid) and bootstrap_classification==primary_classification
    return {'scope':'Paired conditional finite-MC sensitivity under the supplied intervention.',
        'physics_validated':False,'events_per_arm':n,'pair_census':counts.tolist(),
        'constant_weight_pb':float(weights[0]),'selected_on':selected_on,'selected_off':selected_off,
        'fraction_on':f_on,'fraction_off':f_off,'delta_off_minus_on':delta,
        'paired_variance':variance,'paired_cross_arm_covariance':covariance,'standard_error':math.sqrt(variance),
        'normal_interval':normal,'bootstrap_interval':bootstrap,
        'bootstrap_seed':seed,'bootstrap_replicates':replicates,'bootstrap_quantile_method':'linear',
        'bootstrap_zero_denominator_draws':int(np.sum(invalid)),
        'primary_classification':primary_classification,'bootstrap_classification':bootstrap_classification,
        'classification':primary_classification if agreed else 'inconclusive',
        'inconclusive_reason':None if agreed else ('precision criterion unmet' if not precision else 'zero bootstrap denominator' if np.any(invalid) else 'interval classifications disagree'),
        'reference_gap':gap,'confidence_level':plan['confidence_level'],'precision_passed':precision,'automatic_extension':False}
