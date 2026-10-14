"""Execute actual retained-call helper bodies with literal fake oracle data."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ravel.physics import marked_joint_qualification as q


def helpers(out, *, bad_aux=False):
    tree=ast.parse(Path(q.__file__).read_text())
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    wanted={n.name:n for n in ast.walk(run) if isinstance(n,ast.FunctionDef) and n.name in {'save','record','check','call','scalar_call'}}
    initial=ast.parse('sequence=0\nprevious=None\nwritten=0\nstarted=0.0\nreport={"counts":{"scalar_calls":0}}\njournal=out/"progress.jsonl"').body
    body=initial+[deepcopy(wanted[n]) for n in ('save','record','check','call','scalar_call')]+ast.parse('return scalar_call').body
    function=ast.FunctionDef(name='factory',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=body,decorator_list=[])
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    raw={'finite':True,'joint_logpdf':-7.,'source':{'main_means':[3.],'background_means':[1.],'signal_means':[2.]}}
    class FakeScalar:
        def evaluate(self,*args,**kwargs):return deepcopy(raw)
    class FakeBackground:
        def contract(self):return {'retained_auxiliaries':[{'coordinate':'missing' if bad_aux else 'a','pdf':'normal','factor':1}]}
    class FakeMC:
        class_ids=['x','y']
        def document(self):return {'mc_design':{'total_groups':10}}
    namespace=dict(vars(q));namespace.update(out=out,scalar=FakeScalar(),bg=FakeBackground(),mc=FakeMC())
    exec(compile(module,'<actual sealed adapter helper bodies>','exec'),namespace)
    return namespace['factory'](),raw


class RetentionTests(unittest.TestCase):
    point={'mu':1,'source':{'a':.3},'latent':{'x':.2,'y':.8}}

    def test_raw_return_survives_later_auxiliary_metadata_exception(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(q.time,'monotonic',return_value=1.):
            out=Path(tmp).resolve();call,raw=helpers(out,bad_aux=True)
            with self.assertRaises(KeyError):call(self.point,'literal-fake-call')
            records=[json.loads(s) for s in (out/'progress.jsonl').read_text().splitlines()]
            self.assertEqual([r['state'] for r in records],['running','returned'])
            self.assertEqual(records[-1]['result'],raw)
            self.assertEqual(json.loads((out/'marked-qualification.json').read_text())['counts']['scalar_calls'],1)

    def test_raw_and_derived_populations_saved_separately(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(q.time,'monotonic',return_value=1.):
            out=Path(tmp).resolve();call,raw=helpers(out);result=call(self.point,'literal-fake-call')
            self.assertEqual(result['complete_distribution_means'],[3.,.3,2.,8.])
            records=[json.loads(s) for s in (out/'progress.jsonl').read_text().splitlines()]
            self.assertEqual([r['state'] for r in records],['running','returned','derived_scalar_means'])
            self.assertEqual(records[1]['result'],raw)
            self.assertNotIn('complete_distribution_means',records[1]['result'])

    def test_post_return_clock_expiry_retains_return_and_refuses_derivation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(q.time,'monotonic',side_effect=[0.,61.]):
            out=Path(tmp).resolve();call,raw=helpers(out)
            with self.assertRaises(TimeoutError):call(self.point,'literal-fake-call')
            records=[json.loads(s) for s in (out/'progress.jsonl').read_text().splitlines()]
            self.assertEqual(records[-1]['state'],'returned');self.assertEqual(records[-1]['result'],raw)


if __name__=='__main__':unittest.main()
