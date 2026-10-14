"""Exact rational common-rescaling witnesses; no density or model call."""
import ast
from copy import deepcopy
from fractions import Fraction as F
import math
from pathlib import Path
import unittest

from ravel.physics import marked_response as kernel
from ravel.physics import marked_response_provider as provider
from ravel.physics import mc_auxiliary as mc
from ravel.physics import joint_analytic as analytic
from test_marked_response_provider import fixture, P


class StableRatioTests(unittest.TestCase):
    def check_scale(self, common, scale):
        d,c,s,doc=fixture()
        d['category_weights']=[common]*3;d['denominator_marks']=[common]*3;d['scale']=scale
        doc['mc_design']['kappa']=scale
        for row in doc['classes']:
            row['denominator_mark']=common;row['contribution']=[common*v for v in row['contribution']]
        provider.bind_mark_law(d,c,s,doc,{'alpha','beta'},['SR','CR'])
        point={'alpha':.5,'beta':.25}
        jet=provider.mark_jet(d,point,P,s['active_parameter_names'],c['axis_to_source'],['SR','CR'])
        answer=kernel.evaluate(d,P,{'a':.5,'b':.25})
        # Unit-denominator independent rational result: rSR=pA*a*b=1/40.
        expected=F(str(scale))*F(1,40)
        self.assertTrue(math.isclose(jet['signal'][0],float(expected),rel_tol=1e-13,abs_tol=0))
        self.assertTrue(math.isclose(answer['values'][0],float(expected),rel_tol=1e-13,abs_tol=0))
        for actual, coefficient in zip(jet['latent_jacobian'][0],[F(1,10),F(-1,40),F(-1,40)]):
            self.assertTrue(math.isclose(actual,float(F(str(scale))*coefficient),rel_tol=1e-13,abs_tol=0))
        for actual, coefficient in zip(jet['source_jacobian'][0][:2],[F(1,20),F(1,10)]):
            self.assertTrue(math.isclose(actual,float(F(str(scale))*coefficient),rel_tol=1e-13,abs_tol=0))
        self.assertTrue(math.isclose(answer['nuisance_derivatives']['a']['derivative'][0],float(F(str(scale))*F(1,20)),rel_tol=1e-13,abs_tol=0))

    def test_small_common_marks_have_finite_unscaled_jacobian(self):self.check_scale(1e-200,1.)
    def test_large_common_marks_have_finite_unscaled_jacobian(self):self.check_scale(1e200,1.)
    def test_small_scale_and_marks_do_not_underflow_before_division(self):self.check_scale(1e-200,1e-200)
    def test_large_scale_and_marks_do_not_overflow_before_division(self):self.check_scale(1e200,1e200)

    def test_actual_schema2_nominal_expression_order(self):
        # Execute only the literal arithmetic expression, not a model method.
        tree=ast.parse(Path(mc.__file__).read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MCAuxiliaryBlock')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='nominal')
        node=next(n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='signal' for t in n.targets))
        code=compile(ast.fix_missing_locations(ast.Expression(node.value)),'<nominal arithmetic expression>','eval')
        for common,scale in [(1e-200,1e-200),(1e200,1e200)]:
            value=eval(code,{'doc':{'schema_version':2,'mc_design':{'kappa':scale}},'raw':[common*.025],'denominator':common,'fixed':True})[0]
            self.assertTrue(math.isclose(value,float(F(str(scale))*F(1,40)),rel_tol=1e-13,abs_tol=0))

    def test_unused_legacy_ratio_derivative_requires_legacy_branch(self):
        tree=ast.parse(Path(analytic.__file__).read_text())
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_evaluate_with_gradient')
        parents={child:parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}
        assignments=[n for n in ast.walk(fn) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='jsnom' for t in n.targets)]
        self.assertEqual(len(assignments),2)
        for node in assignments:
            parent=parents[node]
            self.assertIsInstance(parent,ast.If)
            self.assertEqual(ast.unparse(parent.test),'self._provider is None')

    def test_zero_denominator_still_refuses_without_repair_or_clipping(self):
        d,c,s,_=fixture();d['denominator_marks']=[0,0,0]
        with self.assertRaisesRegex(ValueError,'positive expected'):provider.mark_jet(d,{'alpha':.5,'beta':.25},P,s['active_parameter_names'],c['axis_to_source'],['SR','CR'])


if __name__=='__main__':unittest.main()
