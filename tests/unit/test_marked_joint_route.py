"""Ordinary source selection and supplied-result transport; no numerical calls."""
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from ravel.workflow import science
from ravel.physics import science_worker, joint_qualification, marked_joint_study as facade
from ravel.physics import marked_joint_qualification as numerical
from ravel.plotting import science_figures

HERE = Path(__file__).resolve().parent
TASK = {'input': 'supplied.json', 'response_family': 'complete_marked_categories'}


class MarkedRouteTests(unittest.TestCase):
    def test_explicit_subtype_and_legacy_default(self):
        self.assertIs(science.adapter({'mode':'joint-qualification','task':TASK}), facade)
        self.assertIs(science.adapter({'mode':'joint-qualification','task':{'input':TASK['input']}}), joint_qualification)
        self.assertTrue(science._new_capability({'mode':'joint-qualification','task':TASK}))

    def test_unknown_family_and_extra_fields_refuse(self):
        for change in ({'response_family':'unknown'}, {'response_family':None}, {'extra':1}, {'input':1}):
            task = dict(TASK, **change)
            with self.assertRaises(ValueError):
                science.adapter({'mode':'joint-qualification','task':task}).validate(task)
        with self.assertRaises(ValueError):facade.validate({'input':TASK['input']})

    def test_real_regular_files_and_resource_transport_without_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();first=base/'input.json';second=base/'marks.json'
            first.write_text('{"fixture":1}');second.write_text('{"fixture":2}')
            task=dict(TASK,input=str(first))
            capture=({},base,{str(first):first.read_bytes(),str(second):second.read_bytes()})
            # Capture's scientific schema is qualified by separate provider controls.
            # This transport test uses two real tiny files and actual ordinary regular checks.
            with patch.object(numerical,'_capture',return_value=capture):
                files=science.task_inputs({'mode':'joint-qualification','task':task,'max_seconds':180},base)
                self.assertEqual(set(files),{first,second})
                self.assertEqual(facade.resource_bounds(task,base),numerical.resource_bounds({'input':str(first)},base))
                self.assertEqual(facade.execution_seconds(task,base),60)
                with self.assertRaisesRegex(ValueError,'hard ceiling'):
                    science.task_inputs({'mode':'joint-qualification','task':task,'max_seconds':59},base)
                second.unlink();second.symlink_to(first)
                with self.assertRaisesRegex(ValueError,re.escape(f'input path traverses a symlink: {second}')):
                    science.task_inputs({'mode':'joint-qualification','task':task,'max_seconds':180},base)

    def test_adopted_route_keeps_required_v2_without_creating_run(self):
        # Exact ordinary entry refuses schema1 before any run directory exists.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();spec=root/'spec.json';rd=root/'not-created'
            spec.write_text(json.dumps({'schema_version':1,'mode':'joint-qualification',
                'source':'pure fabricated transport fixture','assumptions':['No numerical call'],
                'max_seconds':180,'approval_mode':'scripted_yes','task':TASK}))
            with self.assertRaisesRegex(ValueError,'prospective version 2 science review policy'):
                science.plan(rd,spec)
            self.assertFalse(rd.exists())

    def worker(self,result):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            spec={'schema_version':2,'mode':'joint-qualification','task':TASK,'assumptions':['Supplied fake result only']}
            proposal={'attempt':1,'output_directory':'outputs/attempt-1','base_dir':str(HERE),
                      'stage_binding':{'input_snapshot':{'fixture':'explicitly mocked authority'}}}
            seen=[]
            def fake_run(task,base,out):
                seen.append((task,base,out));return deepcopy(result)
            # Only worker admission and terminal scientific adapter are mocked.
            # Actual facade, serializer, verification, CHECK-IN 2 and exit logic run.
            with patch.object(science_worker,'verify_worker',return_value=proposal), \
                 patch.object(science_worker,'execution_spec',return_value=spec), \
                 patch.object(numerical,'run',side_effect=fake_run), \
                 patch.object(science_figures,'render',return_value={'status':'not_applicable','figures':[],'tables':[]}):
                code=science_worker.main([str(root)])
            out=root/'outputs/attempt-1'
            self.assertEqual(seen[0][0],{'input':TASK['input']})
            self.assertEqual(seen[0][2],out)
            stored=json.loads((out/'result.json').read_text())
            self.assertEqual(stored,result)
            return code,json.loads((out/'verification.json').read_text()),json.loads((out/'checkin2.json').read_text())

    def test_passed_supplied_result_transports_without_physics_upgrade(self):
        code,verification,checkin=self.worker({'status':'passed','physics_validated':False,
            'fit_qualified':False,'coverage_qualified':False,'counts':{'scalar_calls':162}})
        self.assertEqual(code,0);self.assertTrue(verification['passed'])
        self.assertFalse(verification['physics_validated']);self.assertFalse(verification['expert_review'])
        self.assertEqual(checkin['sections']['waypoint']['status'],'passed')

    def test_failed_partial_result_is_saved_and_returns_failure(self):
        code,verification,checkin=self.worker({'status':'failed','physics_validated':False,
            'counts':{'scalar_calls':7},'cases':[{'id':'first','points':[{'returned':True}]}],
            'error_type':'TimeoutError','error':'supplied controlled timeout'})
        self.assertEqual(code,3);self.assertFalse(verification['passed'])
        self.assertEqual(checkin['sections']['waypoint']['status'],'failed')


if __name__=='__main__':unittest.main()
