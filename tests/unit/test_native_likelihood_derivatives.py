"""Independent analytic polynomial/adverse controls; no native NLL execution."""
from copy import deepcopy
from fractions import Fraction
import math
import unittest
from ravel.physics import native_likelihood_derivatives as d

def parameter(name,value=1.,lower=-10.,upper=10.,constant=False,role='nuisance',kind='continuous'):
    return {'name':name,'value':value,'constant':constant,'kind':kind,'role':role,'bounds':{'min':lower,'max':upper}}

def request():
    return {'schema_version':1,'kind':'native-likelihood-stencil','identity':{'model_sha256':'1'*64,'runtime_binding_sha256':'2'*64,'evaluation_definition_sha256':'3'*64},
            'parameters':[parameter('x',1.5,role='poi'),parameter('y',.25),parameter('nom',2.,constant=True,role='global_observable')],
            'axes':[{'name':'x','step':.5},{'name':'y','step':.25}],'max_points':256}

def observe(plan,law):
    rows=[]
    for point in plan['points']:
        values={p['name']:Fraction.from_float(p['value']) for p in point['parameters']}
        rows.append({**deepcopy(point),'nll':float(law(values))})
    return {'schema_version':1,'kind':'native-likelihood-stencil-observations','identity':deepcopy(plan['identity']),'plan_sha256':plan['plan_sha256'],'rows':rows}

def quadratic(v):
    x,y=v['x'],v['y'];return 4+2*x+3*y+5*x*x+7*x*y+11*y*y

class DerivativeTests(unittest.TestCase):
    def test_complete_mixed_quadratic_with_constant_cancellation(self):
        plan=d.compile_stencil(request());obs=observe(plan,quadratic);result=d.reduce_observations(plan,obs)
        for level in result['levels']:
            self.assertEqual(level['gradient'],[18.75,19.])
            self.assertEqual(level['hessian'],[[10.,7.],[7.,22.]])
        self.assertEqual(result['h2_minus_h'],{'gradient':[0.,0.],'hessian':[[0.,0.],[0.,0.]]})
        shifted=observe(plan,lambda v:quadratic(v)+2**20)
        self.assertEqual(d.reduce_observations(plan,shifted)['levels'],result['levels'])
        self.assertFalse(result['stationarity_qualified']);self.assertFalse(result['covariance_qualified']);self.assertFalse(result['truncation_error_enclosed'])

    def test_source_order_and_axis_order_are_distinct(self):
        r=request();r['axes'].reverse();plan=d.compile_stencil(r);result=d.reduce_observations(plan,observe(plan,quadratic))
        self.assertEqual(result['parameter_order'],['x','y','nom']);self.assertEqual(result['axis_order'],['y','x'])
        self.assertEqual(result['levels'][0]['gradient'],[19.,18.75]);self.assertEqual(result['levels'][0]['hessian'],[[22.,7.],[7.,10.]])

    def test_boundary_one_sided_nodes_not_clipped(self):
        r=request();r['parameters'][0].update(value=0.,bounds={'min':0.,'max':10.});r['parameters'][1].update(value=3.,bounds={'min':-3.,'max':3.})
        plan=d.compile_stencil(r)
        for level in plan['levels']:
            self.assertEqual([a['mode'] for a in level['axes']],['forward','backward'])
        result=d.reduce_observations(plan,observe(plan,quadratic))
        for level in result['levels']:
            self.assertEqual(level['gradient'],[23.,69.]);self.assertEqual(level['hessian'],[[10.,7.],[7.,22.]])

    def test_nonquadratic_refinement_is_not_an_error_bound(self):
        r=request();r['parameters'][0]['value']=1.;r['axes']=r['axes'][:1]
        plan=d.compile_stencil(r);result=d.reduce_observations(plan,observe(plan,lambda v:v['x']**3))
        self.assertEqual([l['gradient'] for l in result['levels']],[[3.25],[3.0625]])
        self.assertEqual(result['h2_minus_h']['gradient'],[-.1875]);self.assertFalse(result['truncation_error_enclosed'])

    def test_actual_binary64_nodes_not_requested_ideal_spacing(self):
        r=request();r['parameters'][0]['value']=.1;r['axes']=[{'name':'x','step':.1}]
        plan=d.compile_stencil(r)
        # Verify polynomial moments from ACTUAL assigned values, independently
        # of the coefficient generator and its rational reduction.
        for level in plan['levels']:
            a=level['axes'][0];xs=[Fraction.from_float(x)-Fraction.from_float(.1) for x in a['nodes']]
            w=[Fraction(int(t['numerator']),int(t['denominator'])) for t in a['first_weights']]
            q=[Fraction(int(t['numerator']),int(t['denominator'])) for t in a['second_weights']]
            self.assertEqual([sum(wi*x**p for wi,x in zip(w,xs)) for p in range(3)],[0,1,0])
            self.assertEqual([sum(wi*x**p for wi,x in zip(q,xs)) for p in range(3)],[0,0,2])

    def test_overflowing_central_branch_can_use_finite_backward(self):
        r=request();x=float.fromhex('0x1.fffffffffffffp+1023');r['parameters'][0].update(value=x,bounds={'min':None,'max':None});r['axes']=[{'name':'x','step':2*math.ulp(x)}]
        plan=d.compile_stencil(r)
        self.assertTrue(all(l['axes'][0]['mode']=='backward' for l in plan['levels']))
        self.assertTrue(all(math.isfinite(p['parameters'][0]['value']) for p in plan['points']))

    def test_information_already_lost_in_native_rounding_is_not_recovered(self):
        plan=d.compile_stencil(request());result=d.reduce_observations(plan,observe(plan,lambda v:Fraction(10**30)+quadratic(v)))
        self.assertEqual(result['raw_nll_range'][0],result['raw_nll_range'][1])
        self.assertEqual(result['levels'][0]['gradient'],[0.,0.])
        self.assertIn('cannot recover information',result['limitations'][1]);self.assertFalse(result['stationarity_qualified'])

    def test_every_point_retains_full_nonaxis_state(self):
        plan=d.compile_stencil(request())
        self.assertEqual(len({tuple(p['value'].hex() for p in row['parameters']) for row in plan['points']}),len(plan['points']))
        self.assertTrue(all(row['parameters'][2]=={'name':'nom','value':2.,'constant':True} for row in plan['points']))

    def test_prospective_budget_refuses_before_any_evaluation(self):
        r=request();r['max_points']=5
        with self.assertRaisesRegex(ValueError,'budget'):d.compile_stencil(r)

    def test_narrow_domain_no_clipping_or_widening(self):
        r=request();r['parameters'][0]['bounds']={'min':1.4,'max':1.6}
        with self.assertRaisesRegex(ValueError,'no clipping'):d.compile_stencil(r)

    def test_too_small_and_refinement_underflow_steps_refuse(self):
        for h in [1e-20,float.fromhex('0x0.0000000000001p-1022')]:
            r=request();r['axes']=[{'name':'x','step':h}]
            with self.subTest(h=h),self.assertRaises(ValueError):d.compile_stencil(r)

    def test_fixed_discrete_and_data_or_global_axes_refuse(self):
        for change in [{'constant':True},{'kind':'discrete'},{'role':'observable'},{'role':'global_observable'},{'role':'fixed'}]:
            r=request();r['parameters'][0].update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'floating continuous'):d.compile_stencil(r)

    def test_duplicate_names_unknown_axis_and_inverted_bounds_refuse(self):
        for mutate in [lambda r:r['parameters'][1].update(name='x'),lambda r:r['axes'][0].update(name='absent'),lambda r:r['parameters'][0].update(bounds={'min':10.,'max':0.})]:
            r=request();mutate(r)
            with self.assertRaises(ValueError):d.compile_stencil(r)

    def test_bad_types_and_nonfinite_are_explicit_refusals(self):
        for name,value in [('kind',{}),('role',[]),('constant',1),('value',True),('value',float('inf')),('value',2**53+1)]:
            r=request();r['parameters'][0][name]=value
            with self.subTest(name=name,value=value),self.assertRaises(ValueError):d.compile_stencil(r)

    def test_identity_rows_order_flags_and_values_are_exact(self):
        plan=d.compile_stencil(request());good=observe(plan,quadratic)
        mutations=[lambda o:o['identity'].update(model_sha256='4'*64),lambda o:o['rows'].pop(),lambda o:o['rows'].append(deepcopy(o['rows'][0])),
                   lambda o:o['rows'].reverse(),lambda o:o['rows'][0]['parameters'].reverse(),
                   lambda o:o['rows'][0]['parameters'][2].update(constant=False),lambda o:o['rows'][0]['parameters'][0].update(value=2.),
                   lambda o:o['rows'][0].update(nll=float('nan')),lambda o:o.update(plan_sha256='0'*64)]
        for mutate in mutations:
            o=deepcopy(good);mutate(o)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):d.reduce_observations(plan,o)

    def test_rehashed_plan_does_not_override_deterministic_source(self):
        plan=d.compile_stencil(request());plan['levels'][0]['axes'][0]['mode']='backward';plan['plan_sha256']=d._hash({k:v for k,v in plan.items() if k!='plan_sha256'})
        with self.assertRaisesRegex(ValueError,'deterministic'):d.validate_plan(plan)

    def test_ordinary_point_bridge_preserves_anchor_overrides(self):
        plan=d.compile_stencil(request());rows=d.native_point_overrides(plan,{'y':.25})
        for row,point in zip(rows,plan['points']):
            self.assertEqual(row['id'],point['id']);self.assertEqual(row['parameters'],{p['name']:p['value'] for p in point['parameters'] if p['name'] in plan['axis_order']})
        for bad in [{'x':0.},{'nom':2.},{'missing':1.}]:
            with self.assertRaises(ValueError):d.native_point_overrides(plan,bad)

if __name__=='__main__':unittest.main()
