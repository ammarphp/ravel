"""Concrete rounded-grid and evaluator-bias regressions; pure supplied laws."""
from copy import deepcopy
from fractions import Fraction
import unittest
from ravel.physics import native_likelihood_derivatives as d


def plan(x=0.,h=.25,lo=None,hi=None):
    return d.compile_stencil({'schema_version':1,'kind':'native-likelihood-stencil',
        'identity':{'model_sha256':'1'*64,'runtime_binding_sha256':'2'*64,'evaluation_definition_sha256':'3'*64},
        'parameters':[{'name':'x','value':x,'constant':False,'kind':'continuous','role':'poi','bounds':{'min':lo,'max':hi}}],
        'axes':[{'name':'x','step':h}],'max_points':256})


def observations(p,law):
    return {'schema_version':1,'kind':'native-likelihood-stencil-observations','identity':p['identity'],
        'plan_sha256':p['plan_sha256'],'rows':[{**deepcopy(row),'nll':float(law(Fraction.from_float(row['parameters'][0]['value'])))} for row in p['points']]}


class RefinementTests(unittest.TestCase):
    def test_reviewed_counterexample_has_no_effective_refinement(self):
        x=float(3*2**51);p=plan(x,1.1);anchor=Fraction.from_float(x)
        r=d.reduce_observations(p,observations(p,lambda v:(v-anchor)**2+(v-anchor)**4))
        self.assertEqual(len(p['points']),3)
        self.assertEqual([a['axes'][0]['nodes'] for a in p['levels']],[[x-1,x,x+1]]*2)
        self.assertEqual([a['hessian'] for a in r['levels']],[[[4.]],[[4.]]])
        self.assertEqual(r['h2_minus_h']['hessian'],[[0.]])
        self.assertEqual(r['effective_refinement']['repeated_axes'],['x'])
        self.assertEqual(r['effective_refinement']['axes'][0]['status'],'repeated_grid')
        self.assertFalse(r['effective_refinement']['all_selected_axes_effectively_refined'])
        self.assertFalse(r['effective_refinement']['h_h2_agreement_has_accuracy_authority'])
        self.assertFalse(r['profiler_derivative_qualified'])

    def test_regular_grid_contracts_but_does_not_qualify_accuracy(self):
        p=plan(1.,.25);r=d.reduce_observations(p,observations(p,lambda x:x*x))
        a=r['effective_refinement']['axes'][0]
        self.assertTrue(a['effective_refinement']);self.assertFalse(a['repeated_node_grid'])
        self.assertEqual(a['coarse_radius'],{'numerator':'1','denominator':'4'})
        self.assertEqual(a['fine_radius'],{'numerator':'1','denominator':'8'})
        self.assertIsNone(r['native_evaluation_error_bound'])
        self.assertFalse(r['truncation_error_enclosed']);self.assertFalse(r['evaluator_noise_qualified'])

    def test_boundary_cubic_has_different_gradient_and_hessian_bias_orders(self):
        p=plan(0.,.25,0.,10.);r=d.reduce_observations(p,observations(p,lambda x:x**3))
        self.assertEqual([a['gradient'][0] for a in r['levels']],[-.125,-.03125])
        self.assertEqual([a['hessian'][0][0] for a in r['levels']],[1.5,.75])
        a=r['effective_refinement']['axes'][0]
        self.assertTrue(a['uses_one_sided_stencil']);self.assertEqual(a['fine_mode'],'forward')
        self.assertEqual(a['nominal_uniform_node_orders']['one_sided'],{'first_derivative':2,'second_derivative':1})

    def test_affine_evaluator_bias_is_invisible_to_agreement(self):
        p=plan();r=d.reduce_observations(p,observations(p,lambda x:x*x+Fraction(1,8)*x))
        self.assertEqual([a['gradient'] for a in r['levels']],[[.125],[.125]])
        self.assertEqual(r['h2_minus_h']['gradient'],[0.])
        self.assertFalse(r['profiler_derivative_qualified']);self.assertIsNone(r['native_evaluation_error_bound'])

    def test_identical_returned_values_are_observation_not_flatness_authority(self):
        p=plan();r=d.reduce_observations(p,observations(p,lambda x:Fraction(10**30)+x*x))
        self.assertTrue(r['all_returned_nll_values_identical'])
        self.assertFalse(r['stationarity_qualified']);self.assertFalse(r['profiler_derivative_qualified'])

    def test_forged_refinement_metadata_refuses_even_when_rehashed(self):
        p=plan(float(3*2**51),1.1);p['effective_refinement']['all_selected_axes_effectively_refined']=True
        p['plan_sha256']=d._hash({k:v for k,v in p.items() if k!='plan_sha256'})
        with self.assertRaisesRegex(ValueError,'deterministic'):d.validate_plan(p)

if __name__=='__main__':unittest.main()
