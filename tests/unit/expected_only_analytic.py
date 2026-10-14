"""Independent Decimal source-law anchors; no RAVEL/ROOT/native imports.

These are mathematical synthetic-law calculations, not coverage or native tests.
The fixed-template one-bin formula is exact for its specified Poisson law.
"""
from decimal import Decimal as D, localcontext

PI=D('3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117067982148086513282306647')
QUANTILES=tuple(map(D,('.025','.16','.5','.84','.975')))

def normal_cdf(x):
    x=D(x)
    if x<0:return 1-normal_cdf(-x)
    term=total=x;n=1
    while True:
        term=term*x*x/D(2*n+1);new=total+term
        if new==total:break
        total=new;n+=1
        if n>1000:raise ValueError('bounded normal CDF series exhausted')
    return D('.5')+(-x*x/2).exp()*total/(2*PI).sqrt()

def normal_quantile(p):
    p=D(p)
    if not 0<p<1:raise ValueError('open probability required')
    lo,hi=D(-8),D(8)
    for _ in range(430):
        mid=(lo+hi)/2
        if normal_cdf(mid)<p:lo=mid
        else:hi=mid
    return (lo+hi)/2

def poisson_q(mu,b,s):
    mu,b,s=map(D,(mu,b,s))
    if min(b,s)<=0 or mu<0:raise ValueError('positive fixed rates and nonnegative strength required')
    return 2*(mu*s-b*(1+mu*s/b).ln())

def known_background():
    with localcontext() as c:
        c.prec=110
        b,s=D('20.25'),D('3.5');rows=[]
        for p in QUANTILES:
            threshold=(normal_quantile(p)+normal_quantile(1-D('.05')*p))**2
            lo,hi=D(0),D(20)
            for _ in range(430):
                mid=(lo+hi)/2
                if poisson_q(mid,b,s)<threshold:lo=mid
                else:hi=mid
            value=(lo+hi)/2
            rows.append({'quantile':str(p),'q_threshold':str(threshold),'limit':str(value),'residual':str(poisson_q(value,b,s)-threshold)})
        return {'kind':'analytic_synthetic_Poisson_Asimov_CLs_crossing','background':str(b),'signal_per_mu':str(s),'rows':rows,'native_observed':False,'coverage_qualified':False}

def conditional_anchor():
    with localcontext() as c:
        c.prec=110
        b=[D('20.25'),D('40.5')];n=[D(20),D(40)]
        beta=sum(n)/sum(b)
        return {'kind':'analytic_background_only_MLE','beta':str(beta),'counts':[str(beta*v) for v in b],
            'score_at_mle':str(sum(b)-sum(n)/beta),'observed_information':str(sum(n)/(beta*beta)),
            'inverse_information':str(beta*beta/sum(n)), 'likelihood':'independent Poisson n_i | beta*b_i; fixed mu=0; no auxiliary, unbounded-interior beta',
            'native_observed':False,'globality_argument':'strict convexity in beta>0 for these positive counts; no claim for general construction'}
