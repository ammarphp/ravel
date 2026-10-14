"""Exact artificial fixture helpers from the original statistical controls.

These supplied count/graph observations are inert software controls, not ROOT,
experimental data, native-runtime qualification, or new scientific results.
The original test suite remains intact; no test cases are duplicated here.
"""
import hashlib
from fractions import Fraction as F
from ravel.physics import statistical_construction as c

def fixture(tmp_path, correlated=False):
    src = tmp_path / 'supplied.txt'; src.write_text('Artificial source for arithmetic controls, not experimental data.\n')
    k = 2 if correlated else 0
    par = lambda n, role, v, b, fixed=False: {'name': n, 'role': role, 'initial': v, 'bounds': b, 'fixed': fixed, 'meaning': n, 'source': 's'}
    d = {'schema_version': 1, 'model_id': 'regional', 'question': 'Retain full A/B/C/D signal and transfer inference.',
         'sources': [{'id': 's', 'path': str(src), 'sha256': hashlib.sha256(src.read_bytes()).hexdigest()}],
         'parameters': [par('c', 'poi', '0', ['-2', '2']), par('beta', 'rate', '5', ['0','20']),
                        par('u','rate','2',['0','5']), par('v','rate','3',['0','5']), par('kappa','rate','1',['0','2'],True)],
         'bins': [{'id': n, 'role': 'signal_region' if n=='A' else 'control_region', 'observed': obs, 'observation_id': 'events/'+n, 'source':'s'} for n,obs in zip('ABCD',[30,10,15,5])],
         'terms': c.abcd_terms(list('ABCD'), dict(zip('ABCD','ABCD')), beta='beta', x='u', y='v', closure='kappa',source='s',auxiliary_count=k),
         'auxiliary': {'kind':'supplied_gaussian_factor','names':['shape','transfer'] if k else [], 'observed':['0','0'] if k else [],
                       'factor':[['1','0'],['3/5','4/5']] if k else [],'eta_bounds':[['-3','3'],['-4','4']] if k else [],'source':'s'},
         'partition':{'kind':'declared_disjoint_poisson_counts','source':'s','statement':'Assumed artificial disjoint A/B/C/D observations.'},
         'prediction':{'units':'expected_events','energy':'artificial','luminosity':'artificial','basis':'supplied signed c convention','scale':'same-scale artificial','domain_statement':'Box and positive full means; native domain unqualified.','source':'s'},
         'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Artificial exact inputs; no MC auxiliaries.','source':'s'},
         'assumptions':[{'id':'conditional','statement':'This artificial law is supplied, not a physics claim.','source':'s','status':'assumed'}]}
    for ident,power,coefs in [('linear',1,['-4','1','-2','0']),('square',2,['2','1','3','1'])]:
        d['terms'].append({'id':ident,'basis':'interference' if power==1 else 'bsm','coefficients':coefs,'powers':{'c':power},'log_response':[['0']*k for _ in 'ABCD'],'source':'s'})
    return d


def state(d, point=None):
    point=point or c.initial_point(d)
    s={p['name']:{'value':float(F(point[p['name']])),'minimum':float(F(p['bounds'][0])),'maximum':float(F(p['bounds'][1])),'constant':p['fixed']} for p in d['parameters']}
    for i,b in enumerate(d['auxiliary']['eta_bounds']):
        n='ravel_aux_'+str(i);s[n]={'value':float(F(point[n])),'minimum':float(F(b[0])),'maximum':float(F(b[1])),'constant':False}
    return s


def count_product_fixture(d, witnesses):
    """Supplied graph/data observations, not a ROOT result or runtime qualification.

    CountingModelBuilder represents all disjoint-bin counts in one data row.
    Its model_s multiplies their Poissons by the single nuisance factor product.
    """
    bins=d['bins']; count_names=['pdf_bin'+b['id'] for b in bins]
    aux_names=['ravel_aux_'+str(i)+'_Pdf' for i in range(len(d['auxiliary']['names']))]
    leaves=[]; rows=[]
    def proxy(roles,servers):
        codes={roles['x']:1,roles['mean']:2}
        if 'sigma' in roles:codes[roles['sigma']]=0
        return {'method':'ROOT6.22/getAnalyticalIntegral-name-match/v1','roles':roles,
                'queries':[{'server':n,'code':codes[n],'selected':[n] if codes[n] else []} for n in servers]}
    # Independent ABCD means at the fixture's c=eta=0: beta=5,u=2,v=3,kappa=1.
    initial_means=[30.,10.,15.,5.]
    for i,b in enumerate(bins):
        ident=b['id'];mean='n_exp_bin'+ident;full=mean+'_proc_ravel_full';dummy=mean+'_proc_ravel_dummy';fn='ravel_mean_'+str(i)
        pdf={'name':'pdf_bin'+ident,'class':'RooPoisson','servers':['n_obs_bin'+ident,mean]}
        pdf['proxy_identity']=proxy({'x':'n_obs_bin'+ident,'mean':mean},pdf['servers'])
        leaves.append(pdf)
        rows.append({'channel':ident,'declared_role':b['role'],'pdf':pdf,'pdf_observables':['n_obs_bin'+ident],
            'mean':{'name':mean,'class':'RooAddition','servers':[full,dummy]},
            'full_process':{'name':full,'class':'ProcessNormalization','servers':[fn]},'count_function':fn,
            'dummy':{'name':dummy,'constant':True,'value':0.},'initial_total_mean':initial_means[i],
            'initial_count_function':initial_means[i]})
    widths={}
    for i,name in enumerate(aux_names):
        leaves.append({'name':name,'class':'SimpleGaussianConstraint','servers':['ravel_aux_'+str(i),'ravel_aux_'+str(i)+'_In','1']})
        leaves[-1]['proxy_identity']=proxy({'x':'ravel_aux_'+str(i),'mean':'ravel_aux_'+str(i)+'_In','sigma':'1'},leaves[-1]['servers'])
        widths[name]={'name':'1','constant':True,'value':1.}
    domains={n:{k:v[k] for k in ('minimum','maximum','constant')} for n,v in state(d).items()}
    q={'representation':'regional_count_product/v1','coordinate_domains':domains,
       'root':{'name':'model_s','class':'RooProdPdf','servers':['modelObs_s','nuisancePdf']},
       'products':[{'name':'model_s','class':'RooProdPdf','factors':['modelObs_s','nuisancePdf']},
                   {'name':'modelObs_s','class':'RooProdPdf','factors':count_names},
                   {'name':'nuisancePdf','class':'RooProdPdf','factors':aux_names}],
       'leaves':leaves,'rows':rows,'constant_width_reads':len(aux_names),'auxiliary_widths':widths,
       'extra_initial_mean_evaluations':2*len(bins),'constant_dummy_reads':len(bins),
       'semantic_proxy_queries':3*len(aux_names)+2*len(bins)}
    globals_=['ravel_aux_'+str(i)+'_In' for i in range(len(aux_names))]
    return {'workspace':{'pois':['c'],'channels':[],'data_entries':1,'observables':['n_obs_bin'+b['id'] for b in bins],
             'poi_domain':[-2.,2.],'nuisances':['beta','u','v','ravel_aux_0','ravel_aux_1'],'global_observables':globals_},
            'fixed_witnesses':witnesses,'construction_linkage':q,
            'construction_global_ranges':{n:{'has_min':False,'has_max':False} for n in globals_},
            'construction_observations':{'counts':{b['id']:b['observed'] for b in bins},'dataset_weight':1.,
                'auxiliary':{n:{'value':0.,'constant':True} for n in globals_}}}
