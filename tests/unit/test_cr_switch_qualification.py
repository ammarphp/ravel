"""Tiny supplied arithmetic models; never import or compile official pyhf."""
from copy import deepcopy
import math
import unittest

from ravel.validation import cr_switch_qualification as q
from ravel.validation.cr_signal_switch import SWITCH


def workspace():
    background={'name':'background','data':[4.], 'modifiers':[{'name':'alpha','type':'normsys','data':{'lo':.9,'hi':1.1}}]}
    signal={'name':'signal','data':[2.], 'modifiers':[{'name':'mu','type':'normfactor','data':None},{'name':'alpha','type':'histosys','data':{'lo_data':[1.],'hi_data':[3.]}}]}
    channels=[{'name':name,'samples':[deepcopy(background)]} for name in ('CR','CR_absent','SR')]
    for i in (0,2):channels[i]['samples'].append(deepcopy(signal))
    channels[0]['samples'][-1]['modifiers'].append({'name':'cr_only','type':'normsys','data':{'lo':.8,'hi':1.2}})
    return {'channels':channels,'observations':[{'name':c['name'],'data':[7.]} for c in channels],
            'measurements':[{'name':'M','config':{'poi':'mu','parameters':[]}}],'version':'1.0.0'}


class ToyEngine:
    """Analytic supplied fixture; metadata reorder deliberately exercises names."""
    def __init__(self,corruption=None,fail_at=None):
        self.corruption=corruption;self.fail_at=fail_at;self.calls=0
    def compile(self,w,measurement):
        level=None
        params=w['measurements'][0]['config'].get('parameters',[])
        if params:level=params[-1]['inits'][0]
        return level
    def describe(self,level):
        names=['mu','alpha','cr_only','gamma','lumi']
        meta={'names':names,'inits':[1.,0.,0.,1.,1.], 'bounds':[[0.,5.],[-5.,5.],[-5.,5.],[.01,10.],[.5,1.5]],
              'fixed':[False,False,False,False,True], 'channels':['CR','CR_absent','SR'],
              'channel_slices':{'CR':[0,1],'CR_absent':[1,2],'SR':[2,3]},'samples':['background','signal'],
              'data':[7.,5.,8.,0.,0.,4.],
              'auxiliary':[{'parameter_set':'alpha','parameter_name':'alpha','pdf':'normal','sigma':1.,'factor':None},
                           {'parameter_set':'cr_only','parameter_name':'cr_only','pdf':'normal','sigma':2.,'factor':None},
                           {'parameter_set':'gamma','parameter_name':'gamma','pdf':'poisson','sigma':None,'factor':4.}],
              'poi':'mu','modifier_settings':{'histosys':{'interpcode':'code4p'}},
              'constraint_specs':{n:{'n_parameters':1,'constrained':n in ('alpha','cr_only','gamma')} for n in names},
              'model_compact_sha256':'synthetic_model_identity'}
        if level is not None:
            for key,val in [('names',SWITCH),('inits',level),('bounds',[0.,1.]),('fixed',True)]:meta[key].insert(1,val)
            meta['constraint_specs'][SWITCH]={'n_parameters':1,'constrained':False}
        if self.corruption=='fixed' and level==0:meta['fixed'][-1]=False
        if self.corruption=='aux' and level==0:meta['auxiliary'][0]['sigma']=1.1
        return meta
    def evaluate(self,level,point,component):
        self.calls+=1
        if self.calls==self.fail_at:raise RuntimeError('supplied fixture component failure')
        m=self.describe(level);p=dict(zip(m['names'],point));a=p['alpha'];cr=p['cr_only'];g=p['gamma'];mu=p['mu']
        signal=[2.*mu*(1.+.15*a+.02*a*a)*(1.+.1*cr)*g,0.,3.*mu*(1.+.15*a+.02*a*a)*g]
        if level is not None:signal[0]*=p[SWITCH]
        background=[4.*(1.+.05*a),5.*(1.+.04*a),6.*(1.+.03*a)]
        by_sample=[background,signal]
        expected=[b+s for b,s in zip(background,signal)]+[a,cr,4.*g]
        if component=='by_sample':
            if self.corruption=='SR' and level==0:by_sample[1][2]*=1.01
            if self.corruption=='tinyCR' and level==0:by_sample[1][0]=1e-15
            return by_sample
        if component=='expected':
            if self.corruption=='background' and level==0:expected[1]+=.01
            return expected
        if component=='twice_nll':
            value=q.independent_density(m,point,expected)[0]
            return value + (.01 if self.corruption=='density' and level==0 else 0.)
        raise ValueError(component)


class QualificationTests(unittest.TestCase):
    def run_case(self,engine=None,clock=lambda:0.,reference_change=None):
        import hashlib,json
        m=ToyEngine().describe(None)
        reference={source:m[target] for source,target in {'parameter_names':'names','bounds':'bounds','inits':'inits','fixed':'fixed','channel_order':'channels','channel_slices':'channel_slices','sample_order':'samples','observed_and_auxiliary_data':'data','constraints':'constraint_specs','modifier_settings':'modifier_settings','model_compact_sha256':'model_compact_sha256'}.items()}
        reference.update(npars=5,nauxdata=3,data_compact_sha256=hashlib.sha256(json.dumps(reference['observed_and_auxiliary_data'],separators=(',',':')).encode()).hexdigest())
        if reference_change:reference_change(reference)
        saved=[];w=workspace();before=deepcopy(w)
        r=q.qualify(w,measurement='M',signal='signal',all_controls=['CR','CR_absent'],original_reference=reference,engine=engine or ToyEngine(),persist=saved.append,clock=clock)
        self.assertEqual(w,before)
        return r,saved
    def test_complete_denominators_and_exact_named_mapping(self):
        r,saved=self.run_case()
        self.assertTrue(r['passed']);self.assertEqual(len(r['calls']),45);self.assertEqual(len(r['compilations']),3)
        self.assertEqual(len(r['rows']),5);self.assertTrue(all(x['status']=='passed' for x in r['rows']))
        for row in r['rows']:
            self.assertEqual(row['parameters']['zero'][1],0.);self.assertEqual(row['parameters']['one'][1],1.)
            self.assertEqual(row['parameters']['original'],row['parameters']['zero'][:1]+row['parameters']['zero'][2:])
        self.assertEqual(r['control_membership'][1]['signal_sample_present'],False)
        self.assertFalse(r['physics_validated'])
    def test_simultaneous_points_move_all_free_coordinates_preserve_fixed(self):
        m=ToyEngine().describe(None);v=q.vectors(m)
        self.assertEqual(len(v),5)
        for row in v[1:]:
            self.assertTrue(all(x!=y for x,y in zip(row['parameters'][:4],m['inits'][:4])))
            self.assertEqual(row['parameters'][4],m['inits'][4])
    def test_bounds_reflect_not_clip_and_fixed_metadata_strict(self):
        m=ToyEngine().describe(None);m['inits'][0]=0.
        for row in q.vectors(m):self.assertGreaterEqual(row['parameters'][0],0.)
        m['fixed'][0]=1
        with self.assertRaises(ValueError):q.vectors(m)
    def test_source_only_constraint_retained_candidate(self):
        r,_=self.run_case();rows=r['potential_main_response_flat_sets']
        self.assertEqual([x['parameter_set'] for x in rows],['cr_only'])
        self.assertEqual(rows[0]['auxiliary_rows_retained'],1)
        self.assertFalse(rows[0]['full_nll_flatness_established'])
    def test_metadata_fixed_and_auxiliary_corruption_refused_before_calls(self):
        for corruption in ('fixed','aux'):
            with self.subTest(corruption=corruption):
                r,_=self.run_case(ToyEngine(corruption));self.assertFalse(r['passed']);self.assertEqual(r['calls'],[])
    def test_response_density_and_literal_zero_adversaries(self):
        for corruption in ('SR','tinyCR','background','density'):
            with self.subTest(corruption=corruption):
                r,_=self.run_case(ToyEngine(corruption));self.assertFalse(r['passed']);self.assertEqual(len(r['calls']),9)
    def test_every_returned_component_retained_before_second_call_failure(self):
        r,saved=self.run_case(ToyEngine(fail_at=2))
        self.assertEqual([x['status'] for x in r['calls']],['completed','failed'])
        self.assertIn('result',r['calls'][0]);self.assertIn('by_sample',r['rows'][0]['values']['original'])
        self.assertTrue(any(len(s['calls'])==2 and s['calls'][1]['status']=='running' and 'result' in s['calls'][0] for s in saved))
    def test_compilation_failure_preserves_started_identity_and_prior_metadata(self):
        e=ToyEngine();compile_fn=e.compile;seen=[]
        def broken(*args):
            seen.append(1)
            if len(seen)==2:raise RuntimeError('compile refused')
            return compile_fn(*args)
        e.compile=broken;r,saved=self.run_case(e)
        self.assertEqual([x['status'] for x in r['compilations']],['completed','failed'])
        self.assertEqual(r['compilations'][1]['label'],'one');self.assertEqual(r['calls'],[])
    def test_postcall_budget_failure_retains_completed_value(self):
        now=[0.];e=ToyEngine();evaluate=e.evaluate
        def overtime(*args):
            value=evaluate(*args);now[0]=121.;return value
        e.evaluate=overtime;r,_=self.run_case(e,lambda:now[0])
        self.assertFalse(r['passed']);self.assertEqual(len(r['calls']),1)
        self.assertEqual(r['calls'][0]['status'],'completed');self.assertIn('result',r['calls'][0])
    def test_original_density_auxiliary_constants(self):
        m=ToyEngine().describe(None);p=m['inits'];e=ToyEngine().evaluate(None,p,'expected')
        value,aux,terms=q.independent_density(m,p,e)
        main=sum(2.*(mu-n*math.log(mu)+math.lgamma(n+1.)) for n,mu in zip(m['data'][:3],e[:3]))
        reference=main+math.log(2.*math.pi)+math.log(8.*math.pi)+2.*(4.-4.*math.log(4.)+math.lgamma(5.))
        self.assertAlmostEqual(value,reference,places=12);self.assertEqual(aux,[0.,0.,4.]);self.assertEqual(len(terms),6)
    def test_poisson_zero_and_invalid_points(self):
        self.assertEqual(q.poisson(0,0),0.)
        for n,mu in [(1.,0.),(-1.,2.),(1.,-1.),(True,1.),(1.,float('nan'))]:
            with self.subTest(n=n,mu=mu),self.assertRaises(ValueError):q.poisson(n,mu)
    def test_membership_absence_duplicate_and_unknown_refusal(self):
        w=workspace();self.assertFalse(q.intervention(w,'signal',['CR_absent','CR'])[0]['signal_sample_present'])
        for names in (['CR','CR'],['unknown'],['CR_absent']):
            with self.assertRaises(ValueError):q.intervention(w,'signal',names)
    def test_no_pyhf_or_optimizer_import_on_module_load(self):
        import ast
        from pathlib import Path
        tree=ast.parse(Path(q.__file__).read_text())
        imports=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any('pyhf' in ast.unparse(n) or 'scipy' in ast.unparse(n) for n in imports))
    def test_original_reference_drift_refuses_before_endpoint_compilation(self):
        for field in ('model_compact_sha256','data_compact_sha256','npars'):
            with self.subTest(field=field):
                r,_=self.run_case(reference_change=lambda v:v.__setitem__(field,'changed'))
                self.assertFalse(r['passed']);self.assertEqual(len(r['compilations']),1);self.assertEqual(r['calls'],[])


if __name__=='__main__':unittest.main()
