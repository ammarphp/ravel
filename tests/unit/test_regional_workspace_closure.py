"""Pure source/fake-API tests. Never imports ROOT or executes the native worker."""
import ast
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import types
import unittest

from ravel.physics import native_likelihood as N, statistical_construction as S


class Obj:
    def __init__(self,name,cls='RooRealVar',servers=(),value=0.,constant=False):
        self.name=name; self.cls=cls; self.children=list(servers); self.value=value
        self.constant=constant; self.lo=-2.; self.hi=2.; self.reads=0
        roles=('x','mean','sigma') if cls in ('RooGaussian','SimpleGaussianConstraint') else ('x','mean') if cls=='RooPoisson' else ()
        self.proxy_roles=dict(zip(roles,self.children))
    def GetName(self):return self.name
    def ClassName(self):return self.cls
    def serverIterator(self):
        it=iter(self.children);return types.SimpleNamespace(Next=lambda:next(it,None))
    def pdfList(self):return self.children
    def getObservables(self,observables):
        return [x for x in self.children if x in observables]
    def getAnalyticalIntegral(self,all_vars,selected):
        for code,role in ((1,'x'),(2,'mean')):
            if self.proxy_roles.get(role) in all_vars:
                selected.append(self.proxy_roles[role]);return code
        return 0
    def getVal(self):self.reads+=1;return self.value
    def isConstant(self):return self.constant
    def removeRange(self):self.lo=-math.inf;self.hi=math.inf
    def setConstant(self,x):self.constant=x
    def getMin(self):return self.lo
    def getMax(self):return self.hi


def fixture(count=3):
    bins=[{'id':f'R{i}','role':'signal_region' if i==0 else ('mc_auxiliary' if i==count-1 else 'control_region'),'observed':i+3} for i in range(count)]
    d={'bins':bins,'parameters':[{'name':'mu','role':'poi','fixed':False,'bounds':['-2','2']},{'name':'beta','role':'rate','fixed':False,'bounds':['-2','2']}], 'auxiliary':{'names':['theta'],'eta_bounds':[['-2','2']]}}
    response={'kind':'regional-poisson-construction/v1','document':d,'coordinates':['mu','beta','ravel_aux_0']}
    config={'model':{'regions':[{'channel':b['id'],'role':b['role']} for b in bins]},'fit':{'poi':'mu','domain':['-2','2'],'fixed_witness_points':[]}}
    objects={'mu':Obj('mu'),'beta':Obj('beta')}; obs=[]; pdfs=[]
    for i,b in enumerate(bins):
        c=b['id'];o=Obj('n_obs_bin'+c,value=b['observed']);obs.append(o)
        fn=Obj('ravel_mean_'+str(i),'RooAddition',value=10.+i)
        full=Obj('n_exp_bin'+c+'_proc_ravel_full','ProcessNormalization',[fn],10.+i)
        dummy=Obj('n_exp_bin'+c+'_proc_ravel_dummy',value=0.,constant=True)
        mean=Obj('n_exp_bin'+c,'RooAddition',[full,dummy],10.+i)
        pdf=Obj('pdf_bin'+c,'RooPoisson',[o,mean]);pdfs.append(pdf)
        objects.update({x.name:x for x in (o,fn,full,dummy,mean,pdf)})
    eta=Obj('ravel_aux_0'); glob=Obj('ravel_aux_0_In',constant=True);glob.removeRange()
    sigma=Obj('1','RooConstVar',value=1.,constant=True)
    aux=Obj('ravel_aux_0_Pdf','SimpleGaussianConstraint',[eta,glob,sigma])
    nuisance=Obj('nuisancePdf','RooProdPdf',[aux])
    # Also exercise the >50-bin nesting shape without needing native objects.
    blocks=[Obj(f'modelObs_s_{j}','RooProdPdf',pdfs[j:j+10]) for j in range(0,count,10)]
    obsprod=Obj('modelObs_s','RooProdPdf',blocks if count>50 else pdfs)
    root=Obj('model_s','RooProdPdf',[obsprod,nuisance])
    objects.update({x.name:x for x in (eta,glob,sigma,aux,nuisance,obsprod,root,*blocks)})
    w=types.SimpleNamespace(pdf=lambda n:objects.get(n),function=lambda n:objects.get(n),var=lambda n:objects.get(n),arg=lambda n:objects.get(n))
    mc=types.SimpleNamespace(GetPdf=lambda:root,GetObservables=lambda:obs)
    tree=ast.parse(N.NATIVE_PROBE)
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('names','regional_linkage')]
    ns={'json':json,'ROOT':types.SimpleNamespace(RooArgSet=lambda *args:list(args))};exec(compile(ast.Module(body=selected,type_ignores=[]),'native-graph-source-only','exec'),ns)
    stdout=io.StringIO()
    with contextlib.redirect_stdout(stdout):q=ns['regional_linkage'](w,mc,response)
    probe={'workspace':{'pois':['mu'],'channels':[],'data_entries':1,'poi_domain':[-2.,2.],
                       'observables':[o.name for o in obs],'nuisances':['beta','ravel_aux_0'],'global_observables':['ravel_aux_0_In']},
           'construction_linkage':q,'construction_global_ranges':{'ravel_aux_0_In':{'has_min':False,'has_max':False}},
           'construction_observations':{'counts':{b['id']:b['observed'] for b in bins},'dataset_weight':1.,'auxiliary':{'ravel_aux_0_In':{'value':0.,'constant':True}}},'fixed_witnesses':[]}
    return types.SimpleNamespace(probe=probe,config=config,response=response,objects=objects,output=stdout.getvalue(),collector=ns['regional_linkage'],w=w,mc=mc)


class Closure(unittest.TestCase):
    def test_actual_collector_source_and_positive_three_roles(self):
        f=fixture();self.assertEqual(N._check_workspace(f.probe,f.config,f.response),[])
        lines=f.output.splitlines();self.assertEqual(len(lines),10)
        self.assertTrue(all(x.startswith('RAVEL_REGIONAL_GRAPH_RETURN=') for x in lines))
        self.assertEqual(f.probe['construction_linkage']['extra_initial_mean_evaluations'],6)

    def test_blocked_51_bin_product_tree(self):
        f=fixture(51);N._check_workspace(f.probe,f.config,f.response)

    def test_count_and_constraint_graph_adversaries(self):
        alterations=[
            lambda p:p.pop('construction_linkage'),
            lambda p:p['construction_linkage']['rows'].pop(),
            lambda p:p['workspace']['observables'].pop(),
            lambda p:p['workspace']['nuisances'].pop(),
            lambda p:p['workspace']['global_observables'].append('extra'),
            lambda p:p['workspace'].update(pois=['beta']),
            lambda p:p['workspace'].update(data_entries=2),
            lambda p:p['construction_linkage']['rows'][1].update(declared_role='signal_region'),
            lambda p:p['construction_linkage']['rows'][0]['pdf'].update(servers=['n_obs_binR1','n_exp_binR0']),
            lambda p:p['construction_linkage']['rows'][0]['pdf'].update(**{'class':'RooGaussian'}),
            lambda p:p['construction_linkage']['rows'][0].update(pdf_observables=['n_obs_binR0','n_obs_binR1']),
            lambda p:p['construction_linkage']['rows'][0]['mean'].update(servers=['n_exp_binR0_proc_ravel_full']),
            lambda p:p['construction_linkage']['rows'][0]['full_process'].update(servers=['ravel_mean_1']),
            lambda p:p['construction_linkage']['rows'][0]['dummy'].update(value=1.),
            lambda p:p['construction_linkage']['rows'][0].update(initial_total_mean=20.),
            lambda p:p['construction_linkage']['rows'][0].update(initial_count_function=float('nan')),
            lambda p:p['construction_linkage']['root'].update(name='model_b'),
            lambda p:p['construction_linkage']['products'][0]['factors'].pop(),
            lambda p:p['construction_linkage']['leaves'].append(copy.deepcopy(p['construction_linkage']['leaves'][0])),
            lambda p:p['construction_linkage']['products'][0]['factors'].append('model_s'),
            lambda p:p['construction_linkage']['auxiliary_widths']['ravel_aux_0_Pdf'].update(value=2.),
            lambda p:p['construction_linkage']['auxiliary_widths']['ravel_aux_0_Pdf'].update(constant=False),
            lambda p:p['construction_global_ranges']['ravel_aux_0_In'].update(has_max=True),
            lambda p:p['construction_global_ranges']['ravel_aux_0_In'].update(has_min=True),
            lambda p:p['construction_linkage']['coordinate_domains']['ravel_aux_0'].update(minimum=-math.inf),
            lambda p:p['construction_linkage']['coordinate_domains']['beta'].update(constant=True),
            lambda p:p['construction_observations']['auxiliary']['ravel_aux_0_In'].update(value=1.),
        ]
        for i,change in enumerate(alterations):
            with self.subTest(i=i):
                f=fixture();change(f.probe)
                with self.assertRaises((ValueError,KeyError,TypeError)):N._check_workspace(f.probe,f.config,f.response)

    def test_arbitrary_workspace_channel_guard_remains(self):
        f=fixture();p=f.probe
        with self.assertRaisesRegex(ValueError,'channel coverage'):N._check_workspace(p,f.config,None)
        p['workspace']['channels']=['R0','R1','R2'];N._check_workspace(p,f.config,None)
        p['workspace']['channels']=['R0','R1','other']
        with self.assertRaisesRegex(ValueError,'channel coverage'):N._check_workspace(p,f.config,None)

    def test_native_raw_value_retained_before_later_failure(self):
        f=fixture();f.objects['n_exp_binR1'].getVal=lambda:(_ for _ in ()).throw(RuntimeError('synthetic native refusal'))
        out=io.StringIO()
        with contextlib.redirect_stdout(out),self.assertRaises(RuntimeError):f.collector(f.w,f.mc,f.response)
        rows=[json.loads(x.split('=',1)[1]) for x in out.getvalue().splitlines()]
        self.assertEqual([r['name'] for r in rows],['1','n_exp_binR0_proc_ravel_dummy','n_exp_binR0','ravel_mean_0','n_exp_binR1_proc_ravel_dummy'])

    def test_native_nonfinite_return_is_logged_before_host_refusal(self):
        f=fixture();f.objects['n_exp_binR0'].value=math.inf
        out=io.StringIO()
        with contextlib.redirect_stdout(out):q=f.collector(f.w,f.mc,f.response)
        self.assertIn('inf',out.getvalue());f.probe['construction_linkage']=q
        with self.assertRaises(ValueError):N._check_workspace(f.probe,f.config,f.response)

    def test_roles_bound_to_original_source(self):
        f=fixture();f.config['model']['regions'][0]['role']='control_region'
        with self.assertRaisesRegex(ValueError,'source and declared'):N._check_workspace(f.probe,f.config,f.response)

    def test_single_bin_retains_real_empty_category_census(self):
        f=fixture(1);N._check_workspace(f.probe,f.config,f.response)
        tree=ast.parse(N.NATIVE_PROBE)
        outer=next(n for n in tree.body if isinstance(n,ast.If) and 'len(sys.argv)' in ast.unparse(n.test))
        cat=next(n for n in outer.body if isinstance(n,ast.If) and ast.unparse(n.test)=='cat')
        for construction in (True,False):
            cfg={'model':{'regions':[{'channel':'R0'}],**({'construction':{}} if construction else {})}}
            ns={'cfg':cfg,'cat':None,'channels':[]}
            exec(compile(ast.Module(body=[cat],type_ignores=[]),'channel-source','exec'),ns)
            self.assertEqual(ns['channels'],[] if construction else ['R0'])

    def test_empty_auxiliary_and_flat_parameter_product(self):
        f=fixture(1);f.response['document']['auxiliary']={'names':[],'eta_bounds':[]};f.response['coordinates']=['mu','beta']
        f.objects['model_s'].children=[f.objects['modelObs_s']]
        f.probe['workspace']['nuisances']=['beta'];f.probe['workspace']['global_observables']=[]
        f.probe['construction_global_ranges']={};f.probe['construction_observations']['auxiliary']={}
        with contextlib.redirect_stdout(io.StringIO()):f.probe['construction_linkage']=f.collector(f.w,f.mc,f.response)
        N._check_workspace(f.probe,f.config,f.response)

    def test_native_source_poi_identity(self):
        f=fixture();f.response['document']['parameters'][0]['name']='other'
        with self.assertRaisesRegex(ValueError,'source and declared POI'):N._check_workspace(f.probe,f.config,f.response)

    def test_no_native_import(self):
        self.assertNotIn('ROOT',sys.modules)


class GaussianSource(unittest.TestCase):
    def test_generated_done_only_unbounds_observations(self):
        # Extract only the new generated done method from the actual builder
        # using a temporary response seam; no arbitrary model API executes.
        d={'parameters':[],'auxiliary':{'names':['thetaA','thetaB'],'eta_bounds':[['-2','2'],['-3','1']]}}
        compiled={'document':d,'domain':{'name':'mu'},'factories':[],'functions':{}}
        original=S.response;S.response=lambda document:compiled
        try:src=S.native_bridge_source(compiled)
        finally:S.response=original
        tree=ast.parse(src);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        done=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='done')
        ns={};exec(compile(ast.Module(body=[done],type_ignores=[]),'generated-done','exec'),ns)
        vars={n:Obj(n,constant=n.endswith('_In')) for n in ['ravel_aux_0','ravel_aux_1','ravel_aux_0_In','ravel_aux_1_In','unrelated_In']}
        vars['ravel_aux_1'].lo=-3.;vars['ravel_aux_1'].hi=1.
        before={n:(x.lo,x.hi,x.value,x.constant) for n,x in vars.items()}
        fake=types.SimpleNamespace(modelBuilder=types.SimpleNamespace(out=types.SimpleNamespace(var=lambda n:vars.get(n))))
        ns['done'](fake)
        for n in ('ravel_aux_0','ravel_aux_1','unrelated_In'):self.assertEqual((vars[n].lo,vars[n].hi,vars[n].value,vars[n].constant),before[n])
        for n in ('ravel_aux_0_In','ravel_aux_1_In'):
            self.assertEqual((vars[n].lo,vars[n].hi),(-math.inf,math.inf));self.assertEqual(vars[n].value,0.);self.assertTrue(vars[n].constant)
        vars.pop('ravel_aux_1_In')
        with self.assertRaises(ValueError):ns['done'](fake)

    def test_untruncated_law_and_parameter_domain_are_distinct(self):
        phi=lambda x:.5*math.erfc(-x/math.sqrt(2))
        z0=phi(2)-phi(-2)
        delta=2*math.log((phi(0)-phi(-4))/z0)
        self.assertAlmostEqual(delta,-1.2932852255148823,places=13)
        self.assertEqual(.5*(2**2+2**2),4.)
        self.assertNotAlmostEqual(4.+delta,4.,places=8)
        # With a full-real observation domain the normalizer is 1 at all eta;
        # eta may nevertheless remain in [-2,2]. No posthoc NLL correction.
        for eta in [-2,-.8,0,.6,2]:self.assertEqual(phi(math.inf-eta)-phi(-math.inf-eta),1.)


if __name__=='__main__':unittest.main(verbosity=2)
