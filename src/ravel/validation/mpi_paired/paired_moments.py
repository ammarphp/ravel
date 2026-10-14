"""Paired categorical moments including the unselected category."""
import math


def moments(census):
    if type(census) is not list or len(census)<2 or any(type(row)is not list or len(row)!=len(census) for row in census):
        raise ValueError('Complete square pair census required')
    dimension=len(census);regions=dimension-1
    if any(type(v)is not int or v<0 for row in census for v in row):
        raise ValueError('Nonnegative exact integer paired counts required')
    n=sum(map(sum,census));on=[sum(row) for row in census];off=[sum(census[a][b] for a in range(dimension)) for b in range(dimension)]
    dn=sum(on[1:]);df=sum(off[1:])
    if n<2 or dn==0 or df==0:raise ValueError('Nonzero selected arm denominators and N>=2 required')
    pn=[a/dn for a in on[1:]];pf=[a/df for a in off[1:]]
    cells=[]
    for a in range(dimension):
        for b in range(dimension):
            count=census[a][b]
            gn=[((a==j)-pn[j-1]*(a>0))/(dn/n) for j in range(1,dimension)]
            gf=[((b==j)-pf[j-1]*(b>0))/(df/n) for j in range(1,dimension)]
            cells.append((a,b,count,gn,gf,[y-x for x,y in zip(gn,gf)]))
    def covariance(left,right):
        ml=[math.fsum(cell[2]*cell[left][j] for cell in cells)/n for j in range(regions)]
        mr=[math.fsum(cell[2]*cell[right][j] for cell in cells)/n for j in range(regions)]
        return [[math.fsum(cell[2]*(cell[left][i]-ml[i])*(cell[right][j]-mr[j]) for cell in cells)/(n*(n-1)) for j in range(regions)] for i in range(regions)]
    cn=covariance(3,3);cf=covariance(4,4);cross=covariance(3,4)
    delta_cov=covariance(5,5)
    delta=[y-x for x,y in zip(pn,pf)]
    # Exact symmetric numerator/denominator decomposition, in fraction units.
    # Each cell contribution sums to the observed ratio difference, not a
    # separate causal attribution to a cut or an official-template correction.
    decomp=[]
    for target in range(1,dimension):
        abar=(on[target]+off[target])/2;dbar=(dn+df)/2;rows=[]
        for a,b,count,_,_,_ in cells:
            numerator=count*((b==target)-(a==target))*dbar/(dn*df)
            denominator=-count*((b>0)-(a>0))*abar/(dn*df)
            rows.append({'on_category':a,'off_category':b,'count':count,'numerator_component':numerator,'denominator_component':denominator,'total':numerator+denominator})
        decomp.append({'category':target,'numerator_component':math.fsum(r['numerator_component'] for r in rows),'denominator_component':math.fsum(r['denominator_component'] for r in rows),'sum':math.fsum(r['total'] for r in rows),'cells':rows})
    return {'schema_version':1,'scope':'Complete paired fixed-N categorical moments conditional on supplied identity and constant-positive-weight admission; not transport authentication or physics acceptance','events':n,'pair_census':census,'selected_on':dn,'selected_off':df,'fractions_on':pn,'fractions_off':pf,'delta_off_minus_on':delta,'covariance_on':cn,'covariance_off':cf,'cross_covariance_on_off':cross,'delta_covariance':delta_cov,'exact_ratio_decomposition':decomp,'fixed_original_exposure':n,'unselected_category_retained':True,'physics_validated':False}
