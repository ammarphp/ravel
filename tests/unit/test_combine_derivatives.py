"""Inert Roo-like protocol objects, not a ROOT/native likelihood qualification."""
from copy import deepcopy
from types import SimpleNamespace
import math
import unittest
from ravel.physics import combine_derivatives as c, native_likelihood_derivatives as d

class Real:
    def __init__(self,name,value,constant=False,bounds=(-10.,10.)):
        self.name=name;self.value=value;self.constant=constant;self.bounds=bounds
    def GetName(self):return self.name
    def ClassName(self):return 'RooRealVar'
    def getVal(self):return self.value
    def getMin(self):return self.bounds[0]
    def getMax(self):return self.bounds[1]
    def isConstant(self):return self.constant
    def setConstant(self,value):self.constant=value
    def setVal(self,value):self.value=value
    def InheritsFrom(self,kind):return kind in ('RooAbsReal','RooRealVar')

class Category:
    def __init__(self,name='CMS_channel'):
        self.name=name;self.index=7;self.constant=False;self.types=[('CR',-4),('SR',7)]
    def GetName(self):return self.name
    def ClassName(self):return 'RooCategory'
    def numTypes(self):return len(self.types)
    def getOrdinal(self,i):return SimpleNamespace(first=self.types[i][0],second=self.types[i][1])
    def getIndex(self):return self.index
    def getLabel(self):return dict((i,n) for n,i in self.types)[self.index]
    def setIndex(self,index):self.index=index
    def isConstant(self):return self.constant
    def setConstant(self,value):self.constant=value
    def InheritsFrom(self,kind):return kind=='RooAbsCategory'

class Workspace:
    def __init__(self):
        self.reals=[Real('mu',1.,bounds=(0.,5.)),Real('theta',.25),Real('nom',2.,True),Real('obs',13.,bounds=(0.,100.)),Real('unrelated',3.,False)]
        self.cats=[Category()]
    def allVars(self):return self.reals
    def allCats(self):return self.cats
    def var(self,name):return next((v for v in self.reals if v.name==name),None)
    def cat(self,name):return next((v for v in self.cats if v.name==name),None)

class PDF:
    def getStringAttribute(self,key):return None
    def GetName(self):return 'full_model'
    def ClassName(self):return 'RooSimultaneousOpt'
    def getComponents(self):return [self,SimpleNamespace(GetName=lambda:'prior',ClassName=lambda:'RooGaussian')]

class MC:
    def __init__(self,w):self.w=w;self.conditional=[];self.external=[];self.pdf=PDF()
    def GetName(self):return 'ModelConfig'
    def GetPdf(self):return self.pdf
    def GetParametersOfInterest(self):return [self.w.var('mu')]
    def GetNuisanceParameters(self):return [self.w.var('theta')]
    def GetGlobalObservables(self):return [self.w.var('nom')]
    def GetObservables(self):return [self.w.var('obs'),self.w.cat('CMS_channel')]
    def GetConditionalObservables(self):return self.conditional
    def GetExternalConstraints(self):return self.external

class Data:
    def __init__(self):self.at=0;self.weights=[13.,17.];self.x=Real('obs',0.);self.cat=Category()
    def getGlobalObservables(self):return None
    def GetName(self):return 'data_obs'
    def ClassName(self):return 'RooDataHist'
    def numEntries(self):return 2
    def get(self,i):
        self.at=i;self.x.setVal(i+.5);self.cat.setIndex([-4,7][i]);return [self.x,self.cat]
    def weight(self):return self.weights[self.at]
    def sumEntries(self):return sum(self.weights)

class NLL:
    def __init__(self,w):self.w=w;self.calls=[];self.action=None
    def GetName(self):return 'the_existing_nll'
    def ClassName(self):return 'RooNLLVar'
    def getVal(self):
        self.calls.append(c.capture(self.w,MC(self.w)))
        x=self.w.var('mu').value;y=self.w.var('theta').value
        self.w.var('obs').setVal(17.);self.w.cat('CMS_channel').setIndex(-4)
        if self.action:self.action()
        return 10+2*x+3*y+5*x*x+7*x*y+11*y*y


def fixture():
    w=Workspace();mc=MC(w);data=Data();nll=NLL(w)
    selection={'anchor':{'theta':.5},'axes':[{'name':'mu','step':.25},{'name':'theta','step':.125}],'max_points':256}
    context={'model_sha256':'1'*64,'runtime_binding_sha256':'2'*64,'definition':{'workspace_sha256':'3'*64,'native_root_version':'6.30/00','objective':'Existing linked-list constrained NLL'}}
    domain={'name':'mu','bounds':[0.,3.]}
    return w,mc,data,nll,selection,context,domain


def run(args):return c.execute(*args,d)

class ConsumerTests(unittest.TestCase):
    def test_exact_existing_nll_full_reset_and_offset_invariant_reduction(self):
        args=fixture();w,mc,_,nll,selection,context,domain=args;initial=c.capture(w,mc)
        result=run(args)
        self.assertEqual(c.capture(w,mc),initial);self.assertEqual(result['final_state'],initial)
        self.assertEqual(len(nll.calls),len(result['plan']['points']));self.assertEqual(result['fit_calls'],0)
        for state in nll.calls:
            self.assertEqual(state['parameters'][2]['value'],2.);self.assertTrue(state['parameters'][2]['constant'])
            self.assertEqual(state['parameters'][3]['value'],13.);self.assertEqual(state['categories'][0]['index'],7)
            self.assertEqual(state['parameters'][4]['value'],3.)
        for level in result['estimates']['levels']:
            self.assertEqual(level['gradient'],[15.5,21.]);self.assertEqual(level['hessian'],[[10.,7.],[7.,22.]])
        self.assertEqual(c.validate_delivery(result,selection,context,domain,d),result['estimates'])
        self.assertEqual(result['definition']['observed_data']['sum_weights'],30.)
        self.assertEqual([r['coordinates'][1]['index'] for r in result['definition']['observed_data']['rows']],[-4,7])

    def test_failure_restores_every_coordinate_and_category(self):
        args=fixture();w,mc,_,nll,*_=args;initial=c.capture(w,mc)
        def fail():
            w.var('nom').setConstant(False);w.var('unrelated').setVal(7.);raise RuntimeError('inert evaluator failure')
        nll.action=fail
        with self.assertRaisesRegex(RuntimeError,'evaluator failure'):run(args)
        self.assertEqual(c.capture(w,mc),initial)

    def test_nonobservable_drift_refuses_instead_of_silently_resetting_it(self):
        for name in ['mu','theta','nom','unrelated']:
            args=fixture();w,mc,_,nll,*_=args;initial=c.capture(w,mc)
            nll.action=lambda:w.var(name).setVal(w.var(name).value+1)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'non-observable'):run(args)
            self.assertEqual(c.capture(w,mc),initial)

    def test_observable_bounds_or_constant_drift_is_not_an_allowed_value_change(self):
        for change in [lambda w:w.var('obs').setConstant(True),lambda w:setattr(w.var('obs'),'bounds',(-1.,100.))]:
            args=fixture();w,mc,_,nll,*_=args;nll.action=lambda:change(w)
            with self.assertRaises(ValueError):run(args)

    def test_nonfinite_nll_refuses_with_full_final_reset(self):
        args=fixture();w,mc,_,nll,*_=args;initial=c.capture(w,mc);nll.getVal=lambda:float('inf')
        with self.assertRaisesRegex(ValueError,'finite'):run(args)
        self.assertEqual(c.capture(w,mc),initial)

    def test_data_mutation_refuses(self):
        args=fixture();data=args[2];args[3].action=lambda:data.weights.__setitem__(0,14.)
        with self.assertRaisesRegex(ValueError,'data changed'):run(args)

    def test_conditional_or_external_constraint_sets_are_explicitly_unsupported(self):
        for field in ('conditional','external'):
            args=fixture();setattr(args[1],field,[args[0].var('nom')])
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'unsupported'):run(args)
            self.assertEqual(args[3].calls,[])

    def test_invalid_or_fixed_observed_global_discrete_axes_refuse_before_nll(self):
        for name in ['obs','nom','unrelated','CMS_channel','absent']:
            args=fixture();args[4]['axes']=[{'name':name,'step':.25}]
            with self.subTest(name=name),self.assertRaises(ValueError):run(args)
            self.assertEqual(args[3].calls,[])

    def test_invalid_anchor_and_effective_domain_refuse(self):
        for anchor in [{'mu':-1.},{'mu':4.},{'nom':2.},{'obs':3.},{'absent':1.}]:
            args=fixture();args[4]['anchor']=anchor
            with self.subTest(anchor=anchor),self.assertRaises(ValueError):run(args)
            self.assertEqual(args[3].calls,[])

    def test_true_sparse_category_domain_and_explicit_unbounded_real(self):
        args=fixture();w=args[0];w.var('theta').bounds=(-float('inf'),float('inf'))
        result=run(args)
        self.assertEqual(result['plan']['request']['parameters'][1]['bounds'],{'min':None,'max':None})
        self.assertEqual(result['final_state']['categories'][0]['states'],[{'label':'CR','index':-4},{'label':'SR','index':7}])

    def test_nan_or_inverted_unbounded_native_bounds_refuse(self):
        for bounds in [(float('nan'),10.),(float('inf'),10.),(-10.,-float('inf'))]:
            args=fixture();args[0].var('theta').bounds=bounds
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):run(args)

    def test_complete_output_identity_denominator_reset_and_noise_flags_are_bound(self):
        args=fixture();result=run(args)
        mutations=[lambda r:r['observations']['rows'].pop(),lambda r:r['observations']['rows'][0].update(nll=float('nan')),
            lambda r:r['observations']['identity'].update(model_sha256='4'*64),lambda r:r['native_states'][0]['assigned_state']['parameters'][2].update(value=1.),
            lambda r:r['native_states'][0]['after_nll_state']['parameters'][1].update(value=4.),
            lambda r:r.update(fit_calls=1),lambda r:r.update(profiler_derivative_qualified=True),lambda r:r['final_state']['parameters'][0].update(value=0.),
            lambda r:r['estimates'].update(evaluator_noise_qualified=True)]
        for mutate in mutations:
            r=deepcopy(result);mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):c.validate_delivery(r,args[4],args[5],args[6],d)

    def test_same_nll_receives_all_and_only_planned_points(self):
        args=fixture();result=run(args)
        self.assertEqual(len(args[3].calls),result['native_nll_calls'])
        self.assertEqual([s['parameters'][0]['value'] for s in args[3].calls],
            [p['parameters'][0]['value'] for p in result['plan']['points']])
        self.assertEqual(result['definition']['pdf_and_nll']['nll_name'],'the_existing_nll')

if __name__=='__main__':unittest.main()

class AdditionalStateTests(unittest.TestCase):
    def test_signed_zero_mismatch_is_not_accepted_as_a_complete_reset(self):
        w,mc,*_=fixture();w.var('theta').setVal(-0.0);initial=c.capture(w,mc)
        original=w.var('theta').setVal
        w.var('theta').setVal=lambda v:original(0.0 if v==0.0 else v)
        with self.assertRaisesRegex(ValueError,'reset failed'):c.restore(w,mc,initial)

    def test_overlapping_observable_membership_never_permits_global_drift(self):
        args=fixture();w,mc,_,nll,*_=args
        mc.GetObservables=lambda:[w.var('obs'),w.var('nom'),w.cat('CMS_channel')]
        nll.action=lambda:w.var('nom').setVal(3.)
        with self.assertRaisesRegex(ValueError,'non-observable'):run(args)

    def test_recorded_data_population_or_category_domain_cannot_be_rehashed_away(self):
        args=fixture();result=run(args)
        mutations=[lambda r:r['definition']['observed_data']['rows'].pop(),
                   lambda r:r['definition']['observed_data']['rows'][0]['coordinates'].pop(),
                   lambda r:r['definition']['initial_state']['categories'].clear(),
                   lambda r:r['definition']['initial_state']['categories'][0]['states'].append({'label':'fake','index':7}),
                   lambda r:r['definition']['initial_state']['model_config']['external_constraints'].append('extra'),
                   lambda r:r.update(schema_version=True),lambda r:r.update(fit_calls=False)]
        for mutate in mutations:
            r=deepcopy(result);mutate(r)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):c.validate_delivery(r,args[4],args[5],args[6],d)
